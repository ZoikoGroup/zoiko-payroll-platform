"""New Zealand release gates, golden check, parallel cycles, IRD key rotation
and the Option 3 canary (ZP-NZ-ENG-001 Phase 9; SQLite only)."""
import json
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.core.exceptions import BadRequestException
from app.modules.payroll import new_zealand_service as nzs
from app.modules.payroll import nz_golden, nz_parallel
from app.modules.payroll import nz_ird_number as ird
from app.modules.payroll import nz_super_admin as console
from app.modules.payroll.engine.countries import new_zealand as engine
from app.modules.payroll.models import (
    PayrollEmployee, PayrollNzIrdAccessEvent, PayrollNzIrdVault, PayrollNzParallelImport, PayrollRun, PayrollStatus,
    PayslipItem, SourceArtifact,
)
from scripts import nz_local_demo_pack as demo
from tests._nz_engine_helpers import TEST_IRD_EXAMPLE, build_pack

D = Decimal
IRD = "49091850"
KEY1, KEY2 = "a" * 32, "b" * 32


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setattr(settings, "NZ_IRD_KEYRING", json.dumps({"1": KEY1}))
    monkeypatch.setattr(settings, "NZ_IRD_FINGERPRINT_KEY", "f" * 32)


def _user(db, email):
    from app.modules.auth.models import User, UserRole

    user = User(email=email, hashed_password="x", role=UserRole.SUPER_ADMIN, first_name="T", last_name="U",
                is_active=True)
    db.add(user)
    db.commit()
    return user.id


def _evidence(db, tag, creator, reviewer):
    db.add(SourceArtifact(agency="Zoiko", title=f"TEST {tag}", form_number=tag, retrieved_at=datetime(2026, 11, 5),
                          checksum_sha256="e" * 64, file_path=f"gates/{tag}.pdf", created_by_id=creator,
                          reviewer_id=reviewer))
    db.commit()


# ── golden check (G1) ───────────────────────────────────────────────────────
def test_example_format_is_validated():
    spec = nz_golden.parse_example(TEST_IRD_EXAMPLE)
    assert spec["inputs"]["F"] == "FORTNIGHTLY" and spec["inputs"]["C"] == "M SL"
    assert spec["expected"]["payeTotal"] == D("653.29")
    for text, message in (("F=FORTNIGHTLY;C=M;G=1", "inputs => expected"),
                          ("F=FORTNIGHTLY;C=M => paye=1", "G is required"),
                          ("F=DAILY;C=M;G=1 => paye=1", "F must be one of"),
                          ("F=WEEKLY;C=M;G=1;X=2 => paye=1", "unknown input"),
                          ("F=WEEKLY;C=M;G=1 => bonus=1", "unknown expected"),
                          ("F=WEEKLY;C=M;G=1;KS=3.5 => paye=1", "ESCT and EB"),
                          ("F=WEEKLY;C=M;G=1 =>", "at least one expected"),
                          ("F=WEEKLY;C=M;G=1;D=26-4-8 => paye=1", "D must be a date"),
                          ("F=WEEKLY;C=M;G=1 => paye=" + "1" * 150, "at most 150")):
        with pytest.raises(ValueError, match=message):
            nz_golden.parse_example(text)


def test_example_replays_the_worked_example_through_the_engine():
    rate_map, slabs = build_pack()
    result = engine.calculate(nz_golden.example_context(nz_golden.parse_example(TEST_IRD_EXAMPLE), rate_map, slabs,
                                                        date(2026, 4, 1)))["nz_result"]
    assert result["obligations"]["payeTotal"] == "653.29" and result["obligations"]["esct"] == "31.50"


def test_golden_check_on_a_signed_pack_passes_and_reports_a_mismatch(db):
    pack = demo.build_demo_pack(db)
    report = console.golden_check(db, pack.id)
    assert report["examples"] == 1 and report["passed"] and report["results"][0]["ok"]
    from app.modules.payroll.models import TaxSlab

    db.add(TaxSlab(jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country="NZ",
                   rule_type="NZ_IRD_EXAMPLE", filing_status="EX2", min_amount=0, rate_pct=0,
                   tax_formula="F=FORTNIGHTLY;C=M;G=3000;D=2026-04-08 => payeTotal=1.00", rate_label="TEST wrong"))
    db.commit()
    report = console.golden_check(db, pack.id)
    bad = next(r for r in report["results"] if r["example"] == "EX2")
    assert not report["passed"] and bad["failures"] == [{"field": "payeTotal", "expected": "1.00",
                                                         "actual": "653.29"}]


def test_console_refuses_a_malformed_example(db):
    nzs.seed_nz_pack(db)
    db.commit()
    from app.modules.payroll.models import JurisdictionPack

    pack = db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == "NZ").first()
    a, b = _user(db, "nz-p9-a@zoikotest.example.com"), _user(db, "nz-p9-b@zoikotest.example.com")
    source = SourceArtifact(agency="Inland Revenue", title="TEST", retrieved_at=datetime(2026, 11, 1),
                            checksum_sha256="c" * 64, file_path="nz/x.pdf", created_by_id=a, reviewer_id=b)
    db.add(source)
    db.commit()
    with pytest.raises(BadRequestException, match="NZ_IRD_EXAMPLE taxFormula"):
        console.add_table_row(db, pack.id, "NZ_IRD_EXAMPLE", {"reason": "x", "sourceDocumentId": source.id,
                                                               "filingStatus": "EX1", "name": "bad",
                                                               "taxFormula": "{}"}, a)


# ── gates and evidence ──────────────────────────────────────────────────────
# ── parallel cycles (G5) ────────────────────────────────────────────────────
def _paid_run(db, organization, pay_date=date(2026, 10, 9), code="NZ-1", status=PayrollStatus.PAID):
    employee = (db.query(PayrollEmployee).filter_by(organization_id=organization.id, employee_code=code).first()
                or PayrollEmployee(organization_id=organization.id, employee_code=code, name="Aroha", country_code="NZ"))
    db.add(employee)
    db.flush()
    run = PayrollRun(organization_id=organization.id, period_label="NZ", period_start=pay_date, period_end=pay_date,
                     pay_date=pay_date, status=status)
    db.add(run)
    db.flush()
    db.add(PayslipItem(payroll_run_id=run.id, employee_id=employee.id, organization_id=organization.id,
                       employee_name="Aroha", country_code="NZ", gross_pay=D("3000"), net_pay=D("1195.85"),
                       nz_calculation_snapshot={"obligations": {"payeTotal": "653.29", "studentLoan": "248.64",
                                                                "ksEmployee": "105.00", "esct": "31.50"}}))
    db.commit()
    return run


CSV = "Employee,Gross,PAYE,Net\nNZ-1,3000.00,{paye},1195.85\n"
MAP = {"employeeCode": "Employee", "gross": "Gross", "paye_incl_acc": "PAYE", "net_pay": "Net"}


def _import(db, organization, run, paye="653.29", actor=1, **kw):
    body = {"runId": run.id, "sourceName": "Incumbent", "csv": CSV.format(paye=paye), "columnMap": MAP,
            "reason": "parallel cycle", **kw}
    return nz_parallel.import_parallel(db, organization.id, body, actor)


def test_matching_file_is_accepted_by_a_second_person(db, organization):
    run = _paid_run(db, organization)
    summary = _import(db, organization, run)
    db.commit()
    assert summary["clean"] and summary["differences"] == [] and summary["matchedCount"] == 1
    assert summary["cycleMonth"] == "2026-10-01"
    with pytest.raises(BadRequestException, match="four-eyes"):
        nz_parallel.accept_import(db, organization.id, summary["id"], 1)
    assert nz_parallel.accept_import(db, organization.id, summary["id"], 2)["status"] == "ACCEPTED"


def test_differences_are_explained_then_accepted_by_someone_else(db, organization):
    run = _paid_run(db, organization)
    summary = _import(db, organization, run, paye="653.30")
    db.commit()
    [diff] = summary["differences"]
    assert (diff["concept"], diff["difference"]) == ("paye_incl_acc", "-0.01")       # zero tolerance
    with pytest.raises(BadRequestException, match="Every row must match"):
        nz_parallel.accept_import(db, organization.id, summary["id"], 2)
    with pytest.raises(BadRequestException, match="reason"):
        nz_parallel.explain_difference(db, organization.id, diff["id"], " ", 1)
    nz_parallel.explain_difference(db, organization.id, diff["id"], "incumbent rounds up", 1)
    db.commit()
    with pytest.raises(BadRequestException, match="four-eyes"):
        nz_parallel.accept_difference(db, organization.id, diff["id"], 1)
    nz_parallel.accept_difference(db, organization.id, diff["id"], 2)
    db.commit()
    assert nz_parallel.accept_import(db, organization.id, summary["id"], 3)["clean"]


@pytest.mark.parametrize("csv_text, message", [
    ("Employee,IRD Number,Gross\nNZ-1,49091850,3000\n", "identifier column"),
    ("Employee,Ref,Gross\nNZ-1,49091850,3000\n", "IRD number"),
    ("Employee,Ref,Gross\nNZ-1,12-3456-7890123-00,3000\n", "bank account"),
])
def test_files_carrying_identifiers_are_refused_whole(db, organization, csv_text, message):
    run = _paid_run(db, organization)
    with pytest.raises(BadRequestException, match=message):
        nz_parallel.import_parallel(db, organization.id, {"runId": run.id, "sourceName": "X", "csv": csv_text,
                                                           "columnMap": {"employeeCode": "Employee", "gross": "Gross"},
                                                           "reason": "x"}, 1)
    assert db.query(PayrollNzParallelImport).count() == 0


def test_only_committed_runs_and_each_file_once(db, organization):
    open_run = _paid_run(db, organization, status=PayrollStatus.REVIEW)
    with pytest.raises(BadRequestException, match="committed"):
        _import(db, organization, open_run)
    run = _paid_run(db, organization, pay_date=date(2026, 11, 6))
    first = _import(db, organization, run)
    db.commit()
    with pytest.raises(BadRequestException, match="already imported"):
        _import(db, organization, run)
    with pytest.raises(BadRequestException, match="reason"):
        nz_parallel.withdraw_import(db, organization.id, first["id"], "", 1)
    nz_parallel.withdraw_import(db, organization.id, first["id"], "wrong export", 1)
    db.commit()
    assert _import(db, organization, run)["status"] == "OPEN"                          # withdrawn frees the file


def test_g5_needs_two_employers_each_with_two_months(db, organization):
    from app.modules.organizations.models import Organization

    other = Organization(organization_name="Other", organization_code="OTHERNZ")
    db.add(other)
    db.commit()

    def accepted(org_id, month):
        db.add(PayrollNzParallelImport(organization_id=org_id, pay_date=month, cycle_month=month, source_name="X",
                                       file_hash=f"{org_id}{month}".ljust(64, "0"), column_map={}, status="ACCEPTED",
                                       created_by_id=1, approved_by_id=2))
        db.commit()

    accepted(organization.id, date(2026, 9, 1))
    accepted(organization.id, date(2026, 10, 1))
    accepted(other.id, date(2026, 10, 1))
    assert nz_parallel.g5_state(db)[0] is False
    accepted(other.id, date(2026, 11, 1))
    ok, detail = nz_parallel.g5_state(db)
    assert ok and detail.startswith("2 legal employer(s)")
    db.add(PayrollNzParallelImport(organization_id=organization.id, pay_date=date(2026, 12, 1),
                                   cycle_month=date(2026, 12, 1), source_name="X", file_hash="z" * 64, column_map={},
                                   status="ACCEPTED", created_by_id=1, approved_by_id=1))
    with pytest.raises(IntegrityError):
        db.commit()                                                                   # four-eyes in the database
    db.rollback()


# ── IRD-number key rotation (G4) ────────────────────────────────────────────
@pytest.fixture()
def vault_row(db, organization):
    employee = PayrollEmployee(organization_id=organization.id, employee_code="NZ-9", name="B", country_code="NZ")
    db.add(employee)
    db.commit()
    row = nzs.create_nz_ird_number(db, organization.id, "EMPLOYEE", IRD, 1, employee_id=employee.id)
    db.commit()
    return row


def test_rotation_dry_run_writes_nothing_and_apply_rotates(db, vault_row, monkeypatch):
    monkeypatch.setattr(settings, "NZ_IRD_KEYRING", json.dumps({"1": KEY1, "2": KEY2}))
    before = vault_row.ciphertext
    out = nzs.rotate_nz_ird_keys(db)
    assert (out["rotated"], out["written"], vault_row.key_version, vault_row.ciphertext) == (1, False, 1, before)
    out = nzs.rotate_nz_ird_keys(db, dry_run=False)
    db.commit()
    assert out["written"] and vault_row.key_version == 2 and IRD not in json.dumps(out)
    assert ird.decrypt(vault_row.ciphertext, 2, nzs._nz_vault_owner(vault_row)) == ird.normalise(IRD)
    assert db.query(PayrollNzIrdAccessEvent).filter_by(vault_id=vault_row.id, action="ROTATED").count() == 1
    assert nzs.rotate_nz_ird_keys(db)["current"] == 1                                 # nothing left to rotate


def test_rotation_stops_with_nothing_written_on_a_bad_row(db, vault_row, monkeypatch):
    monkeypatch.setattr(settings, "NZ_IRD_KEYRING", json.dumps({"1": "c" * 32, "2": KEY2}))   # key 1 is wrong
    out = nzs.rotate_nz_ird_keys(db, dry_run=False)
    assert out["failed"] == [{"id": vault_row.id, "reason": "does not decrypt with its owner binding"}]
    assert out["written"] is False and vault_row.key_version == 1


def test_rotation_script_refuses_a_remote_database(monkeypatch):
    from scripts import rotate_nz_ird_keys

    monkeypatch.setenv("PAYROLL_DATABASE_URL", "postgresql://u:p@db.example-remote.net/zoiko")
    monkeypatch.delenv("ZOIKO_ALLOW_NONLOCAL_DB_WRITES", raising=False)
    with pytest.raises(SystemExit) as exc:
        rotate_nz_ird_keys.main(["--apply"])
    assert exc.value.code == 2


def test_vault_rows_never_store_plaintext(db, vault_row):
    row = db.get(PayrollNzIrdVault, vault_row.id)
    assert IRD not in (row.ciphertext or "") and IRD not in (row.fingerprint or "")
