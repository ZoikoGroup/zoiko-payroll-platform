"""Japan Phase 9: release gates, parallel cycles and My Number key rotation
(ZP-JP-ENG-001 §14). Synthetic values only."""
import json
from datetime import date

import pytest

from app.config import settings
from app.core.exceptions import BadRequestException
from app.modules.payroll import japan_my_number as mn
from app.modules.payroll import japan_parallel as parallel
from app.modules.payroll import japan_readiness as readiness
from app.modules.payroll import japan_service as jp
from app.modules.payroll.models import (
    ContributionRate, PayrollEmployee, PayrollJpMyNumberVault, PayrollJpParallelImport,
)
from tests.test_japan_phase8 import _payslip, _run

KEY_1 = "a" * 32
KEY_2 = "b" * 32
FINGERPRINT_KEY = "f" * 32
WEIGHTS = (6, 5, 4, 3, 2, 7, 6, 5, 4, 3, 2)


def _number(body="31415926535"):
    total = sum(int(d) * w for d, w in zip(body, WEIGHTS))
    check = 11 - (total % 11)
    return body + str(0 if check >= 10 else check)


@pytest.fixture()
def employee(db, organization):
    row = PayrollEmployee(organization_id=organization.id, employee_code="JP-P9-1",
                          name="Synthetic Employee", country_code="JP")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ── release gates ───────────────────────────────────────────────────────────
def test_a_freshly_seeded_pack_passes_only_the_scope_checks(db):
    jp.seed_japan_pack(db)
    db.commit()
    state = readiness.jp_readiness(db)
    gates = {g["gate"]: g for g in state["gates"]}
    assert [c["ok"] for c in gates["G0"]["checks"]] == [True, True]
    assert not gates["G0"]["passed"]                                  # evidence not recorded yet
    for gate in ("G1", "G2", "G3", "G4", "G5", "G7"):
        assert not all(c["ok"] for c in gates[gate]["checks"]), gate
    assert state["allPassed"] is False
    keys = {u["key"] for u in readiness.jp_unmet_requirements(db)}
    assert {"G0", "G1", "G8", "D-1"} <= keys


def test_a_signed_row_turns_its_check_green(db):
    pack = jp.seed_japan_pack(db)
    row = (db.query(ContributionRate)
           .filter(ContributionRate.jurisdiction_pack_id == pack.id,
                   ContributionRate.component_key == "jp_wht_rounding").one())
    check = lambda: next(c for c in readiness.jp_code_checks(db)["G1"] if c["key"] == "jp_wht_rounding")  # noqa: E731
    assert check()["ok"] is False
    row.text_value = "DOWN"
    assert check()["ok"] is False                                     # still labelled PENDING G1
    row.label = row.label.replace(" [PENDING G1]", "")
    db.commit()
    assert check()["ok"] is True


def test_prefecture_checks_need_all_47(db):
    jp.seed_japan_pack(db)
    check = next(c for c in readiness.jp_code_checks(db)["G4"] if c["key"] == "JP_MIN_WAGE")
    assert check["ok"] is False and check["detail"].startswith("0/47")


def test_key_presence_is_checked_without_reading_the_keys(db, monkeypatch):
    monkeypatch.setattr(settings, "JP_MY_NUMBER_KEYRING", json.dumps({"1": KEY_1}))
    monkeypatch.setattr(settings, "JP_MY_NUMBER_FINGERPRINT_KEY", FINGERPRINT_KEY)
    checks = readiness.jp_code_checks(db)["G6"]
    assert all(c["ok"] for c in checks)
    assert KEY_1 not in json.dumps(checks) and FINGERPRINT_KEY not in json.dumps(checks)


def test_service_availability_lists_every_unmet_gate(db):
    from app.modules.payroll import jurisdiction_hooks

    jp.seed_japan_pack(db)
    unmet = readiness.jp_unmet_requirements(db)
    assert [u["key"] for u in unmet][:9] == [f"G{i}" for i in range(9)]
    assert jurisdiction_hooks.get("JP", "service_registry_transition") is not None


# ── parallel cycles ─────────────────────────────────────────────────────────
CSV = "Employee,Gross,Tax,SI,EI,RT,Net\nJP-P9-1,300000,5000,42450,1500,10000,{net}\n"
MAPPING = {"employeeCode": "Employee", "gross": "Gross", "withholding": "Tax",
           "social_insurance_employee": "SI", "employment_insurance_employee": "EI",
           "resident_tax": "RT", "net_pay": "Net"}


def _committed(db, organization, employee, month=6):
    run = _run(db, organization, date(2026, month, 25), status="Paid", created_by=1)
    item = _payslip(db, organization, employee, run)
    return run, item


def test_a_matching_file_has_no_differences_and_is_accepted_by_a_second_person(db, organization, employee):
    run, item = _committed(db, organization, employee)
    out = parallel.import_jp_parallel(db, organization.id, {"payrollRunId": run.id, "sourceLabel": "Incumbent",
                                                      "csv": CSV.format(net=item.net_pay), "columnMapping": MAPPING}, 1)
    db.commit()
    assert out["differences"] == [] and out["clean"] and out["matched_count"] == 1
    with pytest.raises(BadRequestException, match="four-eyes"):
        parallel.accept_jp_parallel_import(db, organization.id, out["id"], 1)
    assert parallel.accept_jp_parallel_import(db, organization.id, out["id"], 2)["status"] == "ACCEPTED"
    with pytest.raises(BadRequestException, match="already imported"):
        parallel.import_jp_parallel(db, organization.id, {"payrollRunId": run.id, "sourceLabel": "Incumbent",
                                                    "csv": CSV.format(net=item.net_pay), "columnMapping": MAPPING}, 1)


def test_differences_are_explained_and_accepted_by_different_people(db, organization, employee):
    run, item = _committed(db, organization, employee)
    out = parallel.import_jp_parallel(db, organization.id, {"payrollRunId": run.id, "sourceLabel": "Incumbent",
                                                      "csv": CSV.format(net=1), "columnMapping": MAPPING}, 1)
    db.commit()
    diff = out["differences"][0]
    assert diff["concept"] == "net_pay" and not out["clean"]
    with pytest.raises(BadRequestException, match="Every row must match"):
        parallel.accept_jp_parallel_import(db, organization.id, out["id"], 2)
    parallel.explain_jp_parallel_difference(db, organization.id, diff["id"], "incumbent rounds differently", 3)
    db.commit()
    with pytest.raises(BadRequestException, match="four-eyes"):
        parallel.accept_jp_parallel_difference(db, organization.id, diff["id"], 3)
    parallel.accept_jp_parallel_difference(db, organization.id, diff["id"], 2)
    db.commit()
    assert parallel.accept_jp_parallel_import(db, organization.id, out["id"], 2)["status"] == "ACCEPTED"


@pytest.mark.parametrize("csv_text,match", [
    ("Employee,My Number,Gross\nJP-P9-1,x,300000\n", "identifier column"),
    ("Employee,Bank account,Gross\nJP-P9-1,x,300000\n", "identifier column"),
    ("Employee,Gross,Note\nJP-P9-1,300000,1234 5678 9012\n", "shaped like a My Number"),
])
def test_identifiers_refuse_the_whole_file(db, organization, employee, csv_text, match):
    run, _item = _committed(db, organization, employee)
    with pytest.raises(BadRequestException, match=match):
        parallel.import_jp_parallel(db, organization.id, {"payrollRunId": run.id, "sourceLabel": "Incumbent",
                                                    "csv": csv_text, "columnMapping": {"employeeCode": "Employee",
                                                                                       "gross": "Gross"}}, 1)
    assert db.query(PayrollJpParallelImport).count() == 0


def test_only_committed_runs_are_compared(db, organization, employee):
    run = _run(db, organization, date(2026, 6, 25), status="Draft")
    _payslip(db, organization, employee, run)
    with pytest.raises(BadRequestException, match="committed"):
        parallel.import_jp_parallel(db, organization.id, {"payrollRunId": run.id, "sourceLabel": "x",
                                                    "csv": CSV.format(net=0), "columnMapping": MAPPING}, 1)


def test_g7_needs_two_accepted_months(db, organization, employee):
    for month in (5, 6):
        run, item = _committed(db, organization, employee, month)
        out = parallel.import_jp_parallel(db, organization.id, {"payrollRunId": run.id, "sourceLabel": "Incumbent",
                                                          "csv": CSV.format(net=item.net_pay),
                                                          "columnMapping": MAPPING}, 1)
        db.commit()
        # Before this month's acceptance there is at most one accepted month.
        assert next(c for c in readiness.jp_code_checks(db)["G7"])["ok"] is False
        parallel.accept_jp_parallel_import(db, organization.id, out["id"], 2)
        db.commit()
    assert next(c for c in readiness.jp_code_checks(db)["G7"])["ok"] is True


# ── key rotation ────────────────────────────────────────────────────────────
def test_rotation_reencrypts_under_the_newest_key_and_keeps_the_fingerprint(db, organization, employee,
                                                                            monkeypatch):
    monkeypatch.setattr(settings, "JP_MY_NUMBER_KEYRING", json.dumps({"1": KEY_1}))
    monkeypatch.setattr(settings, "JP_MY_NUMBER_FINGERPRINT_KEY", FINGERPRINT_KEY)
    number = _number()
    row = jp.create_my_number(db, organization.id, employee.id, {"myNumber": number}, 1)
    db.commit()
    vault_id = row["id"] if isinstance(row, dict) else row.id
    vault = db.get(PayrollJpMyNumberVault, vault_id)
    fingerprint = vault.fingerprint
    assert vault.key_version == 1

    monkeypatch.setattr(settings, "JP_MY_NUMBER_KEYRING", json.dumps({"1": KEY_1, "2": KEY_2}))
    dry = jp.rotate_my_number_keys(db, dry_run=True)
    assert (dry["rotated"], dry["examined"], dry["failed"]) == (1, 1, [])
    db.refresh(vault)
    assert vault.key_version == 1                                     # a dry run writes nothing

    applied = jp.rotate_my_number_keys(db, dry_run=False)
    db.commit()
    db.refresh(vault)
    assert applied["rotated"] == 1 and vault.key_version == 2 and vault.fingerprint == fingerprint
    owner = mn.vault_owner(organization.id, employee.id, vault.id)
    assert mn.decrypt(vault.ciphertext, 2, owner=owner) == number
    assert number not in json.dumps(applied) and number not in json.dumps(dry)
    assert jp.rotate_my_number_keys(db, dry_run=True)["current"] == 1


def test_rotation_reports_a_row_that_does_not_decrypt(db, organization, employee, monkeypatch):
    monkeypatch.setattr(settings, "JP_MY_NUMBER_KEYRING", json.dumps({"1": KEY_1}))
    monkeypatch.setattr(settings, "JP_MY_NUMBER_FINGERPRINT_KEY", FINGERPRINT_KEY)
    row = jp.create_my_number(db, organization.id, employee.id, {"myNumber": _number()}, 1)
    db.commit()
    vault = db.get(PayrollJpMyNumberVault, row["id"] if isinstance(row, dict) else row.id)
    vault.employee_id = employee.id + 1000                            # the owner binding no longer matches
    db.commit()
    monkeypatch.setattr(settings, "JP_MY_NUMBER_KEYRING", json.dumps({"1": KEY_1, "2": KEY_2}))
    out = jp.rotate_my_number_keys(db, dry_run=False)
    assert out["rotated"] == 0 and out["failed"][0]["id"] == vault.id


def test_rotation_script_refuses_a_remote_database_without_confirmation(monkeypatch):
    from scripts import rotate_jp_my_number_keys as script

    called = {}
    monkeypatch.setattr(script, "assert_local_database",
                        lambda name: called.setdefault("guard", name) and (_ for _ in ()).throw(SystemExit(2)))
    with pytest.raises(SystemExit):
        script.main([])
    assert called["guard"] == "rotate_jp_my_number_keys"
