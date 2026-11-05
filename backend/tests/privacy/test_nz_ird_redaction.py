"""New Zealand privacy proof (ZP-NZ-ENG-001 §13, NZ-025, release gate G4).

A valid IRD number is GENERATED here (check digit computed at run time) — the
file holds no IRD-number literal. It is taken through every path that handles
it: capture, duplicate and check-digit refusals, the reveal flow, the masked
list, the employee summary, the payday filing payload, the vault access log,
the tax audit trail, the activity log, logs and a parallel-run file. Only the
explicit, approved, single-use reveal may return the digits; nothing else may
carry them, in plain, padded, grouped or spaced form. A notice's narrative is
never stored, and the employee's bank account never appears on a New Zealand
surface.

Isolation: through the REAL app and auth chain (the privacy world: tenants A
and B, two legal entities each), tenant B's admin is refused every tenant-A
New Zealand record, and inside tenant A two legal employers' filings and
remittance periods never mix.
"""
import json
import logging
import random
import re
from datetime import date

import pytest

from app.config import settings
from app.core.exceptions import BadRequestException
from app.core.jurisdiction import nz_ird_number_valid
from app.modules.payroll import new_zealand_service as nzs
from app.modules.payroll import nz_filing, nz_parallel, nz_remittance
from app.modules.payroll.models import (
    PayrollActivityLog, PayrollEmployee, PayrollNzAuthorityDeduction, PayrollNzFiling, PayrollNzIrdAccessEvent,
    PayrollNzRemittance, PayrollRun, PayrollStatus, PayslipItem, TaxConfigurationAudit,
)

NARRATIVE = "Synthetic narrative: arrears after separation, see attached court minute"


def _generated_ird(seed: int) -> str:
    rng = random.Random(seed)
    while True:
        candidate = str(rng.randint(10_000_000, 99_999_999))
        if nz_ird_number_valid(candidate):
            return candidate


def _forms(number: str) -> tuple:
    nine = number.zfill(9)
    return (number, nine, f"{nine[:3]}-{nine[3:6]}-{nine[6:]}", f"{nine[:3]} {nine[3:6]} {nine[6:]}",
            f"{number[:2]}-{number[2:5]}-{number[5:]}")


def _absent(number: str, text: str, where: str):
    for form in _forms(number):
        assert form not in text, f"IRD number found in {where}"


def _rows(db, model, **filters) -> str:
    rows = db.query(model).filter_by(**filters).all()
    return json.dumps([{c.name: getattr(r, c.name) for c in r.__table__.columns} for r in rows], default=str)


@pytest.fixture()
def keys(monkeypatch):
    monkeypatch.setattr(settings, "NZ_IRD_KEYRING", json.dumps({"1": "k" * 32}))
    monkeypatch.setattr(settings, "NZ_IRD_FINGERPRINT_KEY", "p" * 32)


@pytest.fixture()
def _codes(monkeypatch):
    from app.core import code_generation

    counter = iter(range(1, 10_000))
    monkeypatch.setattr(code_generation, "generate_business_code",
                        lambda db, org, prefix, *a, **k: f"TEST{prefix}{next(counter):05d}")


def _employee(db, organization_id, code, legal_entity_id=None):
    row = PayrollEmployee(organization_id=organization_id, employee_code=code, name="Synthetic Worker",
                          country_code="NZ", legal_entity_id=legal_entity_id, bank_account="12-3456-7654321-00")
    db.add(row)
    db.commit()
    return row


def _profile(db, organization_id, legal_entity_id=None, name="Synthetic Employer"):
    row = nzs.record_nz_employer_profile(db, organization_id, {
        "effective_from": date(2026, 4, 1), "legal_name": name, "legal_entity_id": legal_entity_id,
        "filing_method": "PAYDAY_GATEWAY", "remittance_class": "MONTHLY"}, 1, "setup")
    nzs.approve_nz_employer_profile(db, organization_id, row.id, 2)
    db.commit()
    return row


def _paid_run(db, organization_id, employees, pay_date=date(2026, 10, 9)):
    run = PayrollRun(organization_id=organization_id, period_label="NZ", period_start=date(2026, 9, 26),
                     period_end=pay_date, pay_date=pay_date, status=PayrollStatus.PAID, nz_payment_kind="REGULAR")
    db.add(run)
    db.flush()
    for employee in employees:
        db.add(PayslipItem(payroll_run_id=run.id, employee_id=employee.id, organization_id=organization_id,
                           employee_name=employee.name, country_code="NZ", gross_pay=3000, net_pay=1195.85,
                           nz_calculation_snapshot={"taxCode": "M", "obligations": {"payeTotal": "653.29"},
                                                    "netPay": "1195.85", "employeeTotal": "1150.86",
                                                    "accumulatorDeltas": {"PAYE_GROSS": "3000"}, "exceptions": [],
                                                    "hashes": {"resultHash": f"h{employee.id}"}}))
    db.commit()
    return run


# ── the IRD number never leaves the vault except through an approved reveal ──
def test_ird_number_never_leaves_the_vault_except_through_an_approved_reveal(db, organization, keys, _codes,
                                                                            caplog):
    caplog.set_level(logging.DEBUG)
    number = _generated_ird(20261105)
    employee = _employee(db, organization.id, "NZ-PRIV-1")
    row = nzs.create_nz_ird_number(db, organization.id, "EMPLOYEE", number, 1, employee_id=employee.id)
    db.commit()
    _absent(number, json.dumps(nzs.nz_ird_view(row), default=str), "the create response")

    other = _employee(db, organization.id, "NZ-PRIV-2")
    with pytest.raises(BadRequestException) as duplicate:
        nzs.create_nz_ird_number(db, organization.id, "EMPLOYEE", number, 1, employee_id=other.id)
    _absent(number, str(duplicate.value.detail), "the duplicate refusal")
    bad = number[:7] + str((int(number[7]) + 1) % 10)
    if not nz_ird_number_valid(bad):
        with pytest.raises(BadRequestException) as invalid:
            nzs.create_nz_ird_number(db, organization.id, "EMPLOYEE", bad, 1, employee_id=other.id)
        _absent(bad, str(invalid.value.detail), "the check-digit refusal")
    db.rollback()

    nzs.request_nz_ird_reveal(db, organization.id, row.id, "payday filing correction", 1)
    db.commit()
    nzs.approve_nz_ird_reveal(db, organization.id, row.id, 2)
    db.commit()
    revealed = nzs.reveal_nz_ird_number(db, organization.id, row.id, 1)
    db.commit()
    assert revealed["irdNumber"].lstrip("0") == number.lstrip("0")           # the one sanctioned path
    with pytest.raises(BadRequestException) as again:
        nzs.reveal_nz_ird_number(db, organization.id, row.id, 1)             # single use
    _absent(number, str(again.value.detail), "the second-reveal refusal")

    _profile(db, organization.id)
    run = _paid_run(db, organization.id, [employee])
    [filing] = nz_filing.build_filings(db, run, 1)
    db.commit()
    payload = json.dumps(nz_filing.filing_view(filing, include_payload=True), default=str)
    assert '"irdVaultId": %d' % row.id in payload
    _absent(number, payload, "the payday filing payload")

    _absent(number, json.dumps(nzs.list_nz_ird_numbers(db, organization.id, employee.id), default=str),
            "the masked list")
    _absent(number, json.dumps(nzs.employee_summary(db, organization.id, employee.id), default=str),
            "the employee summary")
    _absent(number, _rows(db, PayrollNzIrdAccessEvent, organization_id=organization.id), "the vault access log")
    _absent(number, _rows(db, TaxConfigurationAudit), "the audit trail")
    _absent(number, _rows(db, PayrollActivityLog), "the activity log")
    _absent(number, _rows(db, PayrollNzFiling), "the stored filings")
    _absent(number, caplog.text, "the logs")


def test_a_parallel_file_holding_an_ird_number_is_refused_without_echo(db, organization):
    number = _generated_ird(7)
    employee = _employee(db, organization.id, "NZ-PRIV-3")
    run = _paid_run(db, organization.id, [employee])
    for cell in _forms(number):
        with pytest.raises(BadRequestException) as refused:
            nz_parallel.import_parallel(db, organization.id, {
                "runId": run.id, "sourceName": "Incumbent", "reason": "cycle",
                "csv": f"Employee,Gross,Memo\nNZ-PRIV-3,3000.00,{cell}\n",
                "columnMap": {"employeeCode": "Employee", "gross": "Gross"}}, 1)
        _absent(number, str(refused.value.detail), "the parallel-run refusal")


def test_notice_narrative_and_bank_account_never_reach_a_new_zealand_surface(db, organization):
    employee = _employee(db, organization.id, "NZ-PRIV-4")
    meta = {"deduction_type": "CHILD_SUPPORT", "notice_id": "CS-SYN-1", "issuer": "INLAND_REVENUE",
            "received_at": "2026-10-01T09:00:00", "effective_from": "2026-10-01", "amount_per_payday": "120",
            "protected_earnings_policy": "IRD_PROTECTED_NET"}
    with pytest.raises(BadRequestException) as refused:
        nzs.import_nz_authority_notice(db, organization.id, employee.id, {**meta, "narrative": NARRATIVE},
                                       NARRATIVE.encode(), 1)
    assert "narrative" in str(refused.value.detail) and NARRATIVE not in str(refused.value.detail)
    db.rollback()
    nzs.import_nz_authority_notice(db, organization.id, employee.id, meta, NARRATIVE.encode(), 1)
    db.commit()
    stored = _rows(db, PayrollNzAuthorityDeduction, organization_id=organization.id)
    assert NARRATIVE not in stored and "Synthetic narrative" not in stored              # only the file hash
    summary = json.dumps(nzs.employee_summary(db, organization.id, employee.id), default=str)
    assert NARRATIVE not in summary and "7654321" not in summary
    assert "7654321" not in _rows(db, TaxConfigurationAudit) + _rows(db, PayrollActivityLog)


# ── cross-tenant denial through the real app ────────────────────────────────
@pytest.fixture()
def nz_world(world, monkeypatch, keys, _codes):
    from app.modules.payroll.models import CompanyComplianceDetails

    monkeypatch.setattr(settings, "NZ_TENANT_ONBOARDING_ENABLED", True)
    db = world.db
    for key in ("A", "B"):
        world.orgs[key].country = "New Zealand"
        db.add(CompanyComplianceDetails(organization_id=world.orgs[key].id, jurisdiction_country="NZ"))
    for key in ("A1", "A2", "B1"):
        world.employees[key].country_code = "NZ"
    db.commit()
    org_a, a1, a2 = world.orgs["A"].id, world.employees["A1"], world.employees["A2"]
    e1, e2 = world.entities["A-E1"].id, world.entities["A-E2"].id
    number = _generated_ird(424242)
    ids = {"vault": nzs.create_nz_ird_number(db, org_a, "EMPLOYEE", number, 1, employee_id=a1.id).id}
    ids["profile1"], ids["profile2"] = _profile(db, org_a, e1, "Entity One Ltd").id, _profile(db, org_a, e2,
                                                                                               "Entity Two Ltd").id
    run = _paid_run(db, org_a, [a1, a2])
    nz_remittance.post_run(db, run, 1)
    filings = nz_filing.build_filings(db, run, 1)
    db.commit()
    ids.update(run=run.id, filing=filings[0].id,
               remittance=db.query(PayrollNzRemittance).filter_by(organization_id=org_a).first().id)
    summary = nz_parallel.import_parallel(db, org_a, {
        "runId": run.id, "sourceName": "Incumbent", "reason": "cycle",
        "csv": f"Employee,Gross\n{a1.employee_code},3000.00\n{a2.employee_code},3000.00\n",
        "columnMap": {"employeeCode": "Employee", "gross": "Gross"}}, 1)
    db.commit()
    ids["parallel"] = summary["id"]
    from app.modules.payroll import nz_leave_service as lv
    from app.modules.payroll import nz_lifecycle as life

    employment = lv.record_nz_employment(db, org_a, a1.id, {"start_date": date(2025, 5, 12)}, 1, "hired")
    lv.approve_nz_employment(db, org_a, employment.id, 2)
    ids["case"] = life.open_final_pay_case(db, org_a, a1.id, date(2026, 10, 15), "RESIGNED", 1, "resigned").id
    db.commit()
    return world, ids, number, run, filings


def _a_record_paths(world, ids):
    """Every NZ GET route that takes a record id, filled with tenant A's ids —
    generated from the router, so a new route is swept automatically (an id the
    world does not provide fails here rather than being skipped)."""
    from app.modules.payroll.nz_org_router import router

    values = {"employee_id": world.employees["A1"].id, "run_id": ids["run"], "filing_id": ids["filing"],
              "remittance_id": ids["remittance"], "import_id": ids["parallel"], "case_id": ids["case"]}
    paths = []
    for route in router.routes:
        if "GET" in route.methods and "{" in route.path:
            names = re.findall(r"\{(\w+)\}", route.path)
            missing = [n for n in names if n not in values]
            assert not missing, f"{route.path}: the isolation world has no tenant-A id for {missing}"
            paths.append(route.path.removeprefix("/new-zealand").format(**{n: values[n] for n in names}))
    return paths


def test_tenant_b_is_refused_every_tenant_a_record(nz_world, client):
    world, ids, number, _run, _filings = nz_world
    for path in _a_record_paths(world, ids):
        response = client.get(f"/api/payroll/new-zealand{path}", headers=world.headers("TB"))
        assert response.status_code in (403, 404), (path, response.status_code)
        _absent(number, response.text, f"tenant B's response for {path}")
    for path in ("/filings", "/remittances", "/parallel-imports"):
        response = client.get(f"/api/payroll/new-zealand{path}", headers=world.headers("TB"))
        assert response.status_code == 200 and response.json() == [], path
    for path in (f"/ird-numbers/{ids['vault']}/reveal-requests", f"/filings/{ids['filing']}/approve",
                 f"/parallel-imports/{ids['parallel']}/accept"):
        response = client.post(f"/api/payroll/new-zealand{path}", headers=world.headers("TB"),
                               json={"reason": "probe"})
        assert response.status_code in (403, 404), (path, response.status_code)


def test_tenant_a_sees_its_records_masked(nz_world, client):
    world, ids, number, _run, _filings = nz_world
    for path in _a_record_paths(world, ids):
        response = client.get(f"/api/payroll/new-zealand{path}", headers=world.headers("TA"))
        assert response.status_code == 200, (path, response.status_code, response.text[:200])
        _absent(number, response.text, f"tenant A's response for {path}")
        assert "7654321" not in response.text and "GB00SYNTH" not in response.text, path


# ── legal employers inside one organisation never mix ───────────────────────
def test_legal_employers_have_separate_filings_and_remittance_periods(nz_world):
    world, _ids, _number, _run, filings = nz_world
    db = world.db
    e1, e2 = world.entities["A-E1"].id, world.entities["A-E2"].id
    by_entity = {f.legal_entity_id: f for f in filings if f.filing_type == nz_filing.EI}
    assert set(by_entity) == {e1, e2}
    assert [r["employeeId"] for r in by_entity[e1].payload["employees"]] == [world.employees["A1"].id]
    assert [r["employeeId"] for r in by_entity[e2].payload["employees"]] == [world.employees["A2"].id]
    paye = {r.legal_entity_id: r.amount for r in db.query(PayrollNzRemittance).filter_by(obligation="PAYE")}
    assert set(paye) == {e1, e2} and all(str(v) == "653.29" for v in paye.values())


def test_a_mixed_employer_parallel_cycle_counts_for_no_single_employer(nz_world):
    world, ids, _number, _run, _filings = nz_world
    summary = nz_parallel.parallel_summary(world.db, world.orgs["A"].id, ids["parallel"])
    assert summary["legalEntityId"] is None and summary["clean"]


def test_journal_refuses_employers_with_different_account_maps(nz_world):
    from app.modules.payroll import nz_journal

    world, ids, _number, _run, _filings = nz_world
    db, org_a = world.db, world.orgs["A"].id
    accounts = {k: f"6{n:03d}" for n, k in enumerate(nz_journal.ACCOUNT_KEYS)}
    nz_journal.set_journal_accounts(db, org_a, ids["profile1"], accounts, 1, "chart")
    nz_journal.set_journal_accounts(db, org_a, ids["profile2"], {**accounts, "salary_expense": "7000"}, 1, "chart")
    db.commit()
    journal = nz_journal.build_nz_journal(db, org_a, ids["run"])
    assert journal["status"] == "BLOCKED" and "different account maps" in journal["reason"]
