"""South Africa SARS filing and reconciliation (ZP-ZA-ENG-001 Phase 8).

Payslips are calculated by the REAL engine (golden fixtures F1 / F2), frozen
with the real za_payslip_snapshot and committed in an Approved run, so the
filing builders read exactly what production stores. "ZA" is South Africa;
"SA" is Saudi Arabia.
"""
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import south_africa_filing as filing
from app.modules.payroll import south_africa_service as svc
from app.modules.payroll.engine.countries import south_africa_content as content
from app.modules.payroll.engine.resolver import calculate_payroll
from app.modules.payroll.hmrc_golden_harness import build_context
from app.modules.payroll.models import (
    PayrollEmployee, PayrollHoliday, PayrollRun, PayrollZaEtiLedgerEntry, PayslipItem,
)

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "za_golden"
PREPARER, APPROVER = 501, 502


def _calc(fixture: str, **overrides):
    case = json.loads((GOLDEN / f"{fixture}.json").read_text(encoding="utf-8"))["context"]
    case.update(overrides)
    return calculate_payroll(build_context(case), "standard")


def _employee(db, organization, code, *, tax_number="0123456789"):
    fields = {"national_id": "8001015009087"}
    if tax_number:
        fields["tax_number"] = tax_number
    emp = PayrollEmployee(organization_id=organization.id, employee_code=code, name=f"Employee {code}",
                          date_of_joining=date(2020, 1, 1), basic=Decimal("10000"), country_code="ZA",
                          compliance_fields=fields)
    db.add(emp)
    db.flush()
    return emp


def _run(db, organization, pay_date, status="Approved"):
    run = PayrollRun(organization_id=organization.id, period_label=pay_date.strftime("%Y-%m"),
                     period_start=pay_date.replace(day=1), period_end=pay_date, pay_date=pay_date, status=status)
    db.add(run)
    db.flush()
    return run


def _payslip(db, organization, run, employee, result):
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=employee.id, organization_id=organization.id,
        employee_name=employee.name, country_code="ZA", gross_pay=Decimal(str(result.gross)),
        net_pay=result.net_pay, tds=result.tds, esi=result.employee_esi, employer_esi=result.employer_esi,
        employer_payroll_tax=result.employer_payroll_tax, employee_pension=result.employee_pension,
        za_calculation_snapshot=svc.za_payslip_snapshot(result))
    db.add(item)
    db.flush()
    return item


def _holidays(db, organization, *days):
    for d in days:
        db.add(PayrollHoliday(organization_id=organization.id, date=d, name="Public holiday", country="ZA"))
    db.flush()


@pytest.fixture()
def september(db, organization):
    """F1 (R50,000, age 40) + F2 (R30,000, age 68, one dependant) paid 30 Sep 2026."""
    _holidays(db, organization, date(2026, 12, 25), date(2026, 9, 24))
    run = _run(db, organization, date(2026, 9, 30))
    e1, e2 = _employee(db, organization, "ZA-F1"), _employee(db, organization, "ZA-F2")
    _payslip(db, organization, run, e1, _calc("f1_monthly_salary_age_40"))
    _payslip(db, organization, run, e2, _calc("f2_age_68_one_medical_dependant"))
    return run, e1, e2


# ── EMP201 ──────────────────────────────────────────────────────────────────
def test_emp201_totals_for_f1_and_f2(db, organization, september):
    emp201 = filing.build_za_emp201(db, organization.id, "2026-09")
    # PAYE 11,075.58 + 3,115.25 ; SDL 500 + 300 ; UIF (177.12 + 177.12) x 2
    assert (emp201["paye"], emp201["sdl"], emp201["uif"]) == ("14190.83", "800.00", "708.48")
    assert emp201["amountDue"] == "15699.31"
    assert emp201["employeeCount"] == 2 and emp201["etiUtilised"] == "0.00"


def test_emp201_reads_committed_runs_of_this_organisation_only(db, organization, september):
    from app.modules.organizations.models import Organization

    draft = _run(db, organization, date(2026, 9, 29), status="Draft")
    _payslip(db, organization, draft, _employee(db, organization, "ZA-DRAFT"), _calc("f1_monthly_salary_age_40"))
    other = Organization(organization_name="Other ZA Org", organization_code="OTHERZA")
    db.add(other)
    db.flush()
    other_run = _run(db, other, date(2026, 9, 30))
    _payslip(db, other, other_run, _employee(db, other, "ZA-OTHER"), _calc("f1_monthly_salary_age_40"))
    assert filing.build_za_emp201(db, organization.id, "2026-09")["paye"] == "14190.83"


def test_eti_is_shown_available_but_not_utilised_while_the_policy_is_pending(db, organization, september):
    run, e1, _e2 = september
    db.add(PayrollZaEtiLedgerEntry(organization_id=organization.id, employee_id=e1.id,
                                   claim_month=date(2026, 9, 1), qualifying_month_no=1, paid_hours=Decimal("160"),
                                   remuneration=Decimal("5000"), normalised_remuneration=Decimal("5000"),
                                   eti_amount=Decimal("1500"), status="CALCULATED"))
    db.flush()
    emp201 = filing.build_za_emp201(db, organization.id, "2026-09")
    assert (emp201["etiAvailable"], emp201["etiUtilised"], emp201["etiOffsetPolicy"]) == ("1500.00", "0.00", "PENDING_G1")
    assert emp201["paye"] == "14190.83"                       # employee PAYE never reduced (ZA-010)
    assert emp201["warnings"]


# ── due date (spec §9) ──────────────────────────────────────────────────────
@pytest.mark.parametrize("period, holiday, expected", [
    ("2026-09", None, date(2026, 10, 7)),          # Wednesday 7 October
    ("2026-10", None, date(2026, 11, 6)),          # 7 November is a Saturday -> Friday 6
    ("2026-05", None, date(2026, 6, 5)),           # 7 June is a Sunday -> Friday 5
    ("2026-09", date(2026, 10, 7), date(2026, 10, 6)),   # 7th a public holiday -> preceding business day
])
def test_due_date_moves_to_the_preceding_business_day(db, organization, period, holiday, expected):
    _holidays(db, organization, date(2026, 12, 25), *([holiday] if holiday else []))
    due, blocked = filing.za_due_date(db, organization.id, period)
    assert (due, blocked) == (expected, None)


def test_due_date_blocks_without_a_holiday_calendar(db, organization):
    due, blocked = filing.za_due_date(db, organization.id, "2026-09")
    assert due is None and "holiday calendar" in blocked


# ── artefact lifecycle (ZA-019, ZA-020) ─────────────────────────────────────
def _emp201_artifact(db, organization, actor=PREPARER):
    return filing.record_za_artifact(db, organization.id, "EMP201", "2026-09",
                                     filing.build_za_emp201(db, organization.id, "2026-09"), actor_id=actor)


def test_same_payload_reuses_the_version_and_a_change_supersedes(db, organization, september):
    first = _emp201_artifact(db, organization)
    assert (first.version, first.status, first.validation_status) == (1, "VALIDATED", "PASSED")
    assert _emp201_artifact(db, organization).id == first.id
    run = _run(db, organization, date(2026, 9, 15))
    _payslip(db, organization, run, _employee(db, organization, "ZA-LATE"), _calc("uif_below_ceiling_band_1"))
    second = _emp201_artifact(db, organization)
    assert (second.version, second.supersedes_id) == (2, first.id)
    assert first.status == "SUPERSEDED" and first.payload["paye"] == "14190.83"   # never edited


def test_four_eyes_submission_and_receipt(db, organization, september):
    art = _emp201_artifact(db, organization)
    with pytest.raises(BadRequestException, match="Four-eyes"):
        filing.approve_za_artifact(db, organization.id, art.id, approver_id=PREPARER)
    with pytest.raises(BadRequestException, match="APPROVED"):
        filing.record_za_submission(db, organization.id, art.id, "EASYFILE")
    filing.approve_za_artifact(db, organization.id, art.id, approver_id=APPROVER)
    with pytest.raises(BadRequestException, match="channel"):
        filing.record_za_submission(db, organization.id, art.id, "PORTAL_BOT")
    filing.record_za_submission(db, organization.id, art.id, "easyfile")
    with pytest.raises(BadRequestException, match="receipt"):
        filing.record_za_receipt(db, organization.id, art.id, accepted=True, receipt_ref=" ")
    filing.record_za_receipt(db, organization.id, art.id, accepted=True, receipt_ref="SARS-REC-1")
    assert (art.status, art.submission_channel, art.receipt_ref) == ("ACCEPTED", "EASYFILE", "SARS-REC-1")


def test_rejection_keeps_the_raw_response_and_the_correction_is_a_new_version(db, organization, september):
    art = _emp201_artifact(db, organization)
    filing.approve_za_artifact(db, organization.id, art.id, approver_id=APPROVER)
    filing.record_za_submission(db, organization.id, art.id, "EFILING")
    payload_before = dict(art.payload)
    filing.record_za_receipt(db, organization.id, art.id, accepted=False, raw_response={"error": "E123"})
    assert art.status == "REJECTED" and art.external_response == {"error": "E123"}
    assert art.payload == payload_before
    run = _run(db, organization, date(2026, 9, 16))
    _payslip(db, organization, run, _employee(db, organization, "ZA-FIX"), _calc("below_tax_threshold"))
    fixed = _emp201_artifact(db, organization)
    assert fixed.version == 2 and fixed.supersedes_id == art.id


def test_blocked_due_date_leaves_the_emp201_unapprovable(db, organization):
    run = _run(db, organization, date(2026, 9, 30))
    _payslip(db, organization, run, _employee(db, organization, "ZA-NOHOL"), _calc("f1_monthly_salary_age_40"))
    art = filing.record_za_artifact(db, organization.id, "EMP201", "2026-09",
                                    filing.build_za_emp201(db, organization.id, "2026-09"), actor_id=PREPARER)
    assert (art.status, art.validation_status) == ("DRAFT", "FAILED")
    with pytest.raises(BadRequestException):
        filing.approve_za_artifact(db, organization.id, art.id, approver_id=APPROVER)


# ── SARS payments ───────────────────────────────────────────────────────────
def test_payment_allocation_must_add_up_and_a_prn_is_unique(db, organization):
    with pytest.raises(BadRequestException, match="add up"):
        filing.record_za_sars_payment(db, organization.id, period_key="2026-09", paid_on="2026-10-06",
                                      amount="100.00", payment_reference="PRN1", allocation={"paye": "90.00"})
    row = filing.record_za_sars_payment(db, organization.id, period_key="2026-09", paid_on="2026-10-06",
                                        amount="100.00", payment_reference="PRN1",
                                        allocation={"paye": "60.00", "sdl": "20.00", "uif": "20.00"})
    with pytest.raises(BadRequestException, match="already recorded"):
        filing.record_za_sars_payment(db, organization.id, period_key="2026-09", paid_on="2026-10-06",
                                      amount="100.00", payment_reference="PRN1", allocation={"paye": "100.00"})
    filing.reverse_za_sars_payment(db, organization.id, row.id)
    assert row.status == "REVERSED"


# ── reconciliation (ZA-019) ─────────────────────────────────────────────────
def _declare_and_pay(db, organization, amount="15699.31"):
    art = _emp201_artifact(db, organization)
    filing.approve_za_artifact(db, organization.id, art.id, approver_id=APPROVER)
    if amount:
        filing.record_za_sars_payment(db, organization.id, period_key="2026-09", paid_on="2026-10-06",
                                      amount=amount, payment_reference="PRN-SEP",
                                      allocation={"paye": "14190.83", "sdl": "800.00", "uif": "708.48"}
                                      if amount == "15699.31" else {"paye": amount})
    return art


def test_interim_covers_march_to_august_and_annual_march_to_february():
    assert filing._tax_year_months("2027-INTERIM") == [f"2026-{m:02d}" for m in range(3, 9)]
    annual = filing._tax_year_months("2027-ANNUAL")
    assert annual[0] == "2026-03" and annual[-1] == "2027-02" and len(annual) == 12


def test_balanced_year_is_ready(db, organization, september):
    _declare_and_pay(db, organization)
    report = filing.build_za_reconciliation(db, organization.id, "2027-ANNUAL")
    assert report["status"] == "READY", report["issues"]
    sep = next(m for m in report["months"] if m["month"] == "2026-09")
    assert (sep["payroll"], sep["emp201"], sep["paid"]) == ("15699.31", "15699.31", "15699.31")


def test_short_payment_is_imbalanced_until_a_second_person_approves_the_variance(db, organization, september):
    _declare_and_pay(db, organization, amount="15000.00")
    report = filing.build_za_reconciliation(db, organization.id, "2027-ANNUAL")
    assert report["status"] == "IMBALANCED"
    assert {"month": "2026-09", "measure": "EMP201_VS_PAYMENT", "difference": "699.31"} in report["issues"]
    variance = filing.propose_za_variance(db, organization.id, reconciliation_period="2027-ANNUAL",
                                          month_key="2026-09", measure="EMP201_VS_PAYMENT", amount="699.31",
                                          reason="Balance paid with the October payment", actor_id=PREPARER)
    with pytest.raises(BadRequestException, match="Four-eyes"):
        filing.approve_za_variance(db, organization.id, variance.id, approver_id=PREPARER)
    assert filing.build_za_reconciliation(db, organization.id, "2027-ANNUAL")["status"] == "IMBALANCED"
    filing.approve_za_variance(db, organization.id, variance.id, approver_id=APPROVER)
    assert filing.build_za_reconciliation(db, organization.id, "2027-ANNUAL")["status"] == "READY"


def test_undeclared_payroll_and_missing_tax_number_block_ready(db, organization):
    _holidays(db, organization, date(2026, 12, 25))
    run = _run(db, organization, date(2026, 9, 30))
    _payslip(db, organization, run, _employee(db, organization, "ZA-NOTAX", tax_number=None),
             _calc("f1_monthly_salary_age_40"))
    report = filing.build_za_reconciliation(db, organization.id, "2027-ANNUAL")
    assert report["status"] == "IMBALANCED"
    measures = {i["measure"] for i in report["issues"]}
    assert {"PAYROLL_VS_EMP201", "CERTIFICATE_VALIDATION"} <= measures


# ── certificates and the BRS mapping layer (ZA-015, ZA-018) ─────────────────
def test_certificates_are_canonical_and_masked(db, organization, september):
    certs = {c["employeeName"]: c for c in filing.build_za_certificates(db, organization.id, "2027-ANNUAL")}
    f1 = certs["Employee ZA-F1"]
    assert f1["certificateType"] == "IRP5" and f1["validation"] == "PASSED"
    assert (f1["lines"]["SALARY"], f1["lines"]["PAYE"], f1["lines"]["UIF_EMPLOYEE"]) == \
        ("50000.00", "11075.58", "177.12")
    assert certs["Employee ZA-F2"]["lines"]["MEDICAL_CREDIT"] == "752.00"
    assert f1["taxNumberMasked"] == "******6789"
    assert set(f1["lines"]) == set(content.ZA_CERTIFICATE_LINES)


def test_brs_mapping_blocks_while_the_catalogue_is_empty_and_never_guesses(db, organization, september,
                                                                            monkeypatch):
    certs = filing.build_za_certificates(db, organization.id, "2027-ANNUAL")
    assert filing.map_to_brs(certs)["status"] == "BLOCKED"
    monkeypatch.setitem(content.ZA_BRS_CATALOG, "25.3.0",
                        {"source_codes": {"SALARY": "TEST-A"}, "fields": {}, "evidence": "S4"})
    partial = filing.map_to_brs(certs)
    assert partial["status"] == "BLOCKED" and "PAYE" in partial["reason"]
    art = filing.record_za_artifact(db, organization.id, "IRP5", "2027-ANNUAL",
                                    {"certificates": certs, "brs": filing.map_to_brs(certs)}, actor_id=PREPARER)
    assert art.status == "DRAFT" and any(e["code"] == "ZA_BRS_BLOCKED" for e in art.validation_errors)


def test_irp5_and_emp501_templates_cannot_be_activated_without_the_catalogue():
    from types import SimpleNamespace

    assert "BRS" in svc.template_activation_refusal(None, SimpleNamespace(report_type="ZA_IRP5_PREVIEW"), 1)
    assert svc.template_activation_refusal(None, SimpleNamespace(report_type="ZA_PAYROLL_REGISTER"), 1) is None


# ── COIDA evidence ──────────────────────────────────────────────────────────
def test_coida_evidence_counts_salary_and_flags_review_components(db, organization, september):
    run = _run(db, organization, date(2026, 10, 30))
    _payslip(db, organization, run, _employee(db, organization, "ZA-OCT"), _calc("f1_monthly_salary_age_40"))
    september_item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == september[0].id).first()
    # A component COIDA classifies as REVIEW is reported, never silently counted or dropped.
    snap = dict(september_item.za_calculation_snapshot)
    snap["trace"]["bases"]["PAYE"]["lines"].append({"component": "BONUS", "amount": "1000.00"})
    september_item.za_calculation_snapshot = snap
    db.flush()
    evidence = filing.build_za_coida_evidence(db, organization.id, "2027")
    assert evidence["workerCounts"]["2026-09"] == 2 and evidence["workerCounts"]["2026-10"] == 1
    assert evidence["totalEarnings"] == "130000.00"            # 50,000 + 30,000 + 50,000 salary
    assert evidence["unclassifiedEarnings"] == {"BONUS": "1000.00"}
    assert "assessment rate" in evidence["note"]


# ── report templates seed cleanly ───────────────────────────────────────────
def test_za_report_templates_seed_as_drafts(db):
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "seed_statutory_report_templates.py"
    spec = importlib.util.spec_from_file_location("seed_templates", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    seeded = module.seed_south_africa(db)
    assert len(seeded) == 4
    assert {t.report_type for t in seeded} == {"ZA_PAYROLL_REGISTER", "ZA_EMP201_SUMMARY", "ZA_IRP5_PREVIEW",
                                               "ZA_COIDA_EARNINGS"}
    assert all(t.status == "Draft" and t.jurisdiction_country == "ZA" for t in seeded)


# ── routes ──────────────────────────────────────────────────────────────────
def test_filing_routes_are_registered_behind_the_dormancy_guard():
    from app.modules.payroll import tenant_statutory_router as r

    paths = {route.path for route in r.router.routes}
    for p in ("/south-africa/emp201/{period_key}", "/south-africa/reconciliation/{period}",
              "/south-africa/certificates/{period}", "/south-africa/artifacts", "/south-africa/sars-payments",
              "/south-africa/coida-evidence/{assessment_year}", "/south-africa/variances/{variance_id}/approve"):
        assert p in paths, p
    for route in r.router.routes:
        if route.path.startswith("/south-africa/") and any(
                k in route.path for k in ("emp201", "reconciliation", "certificates", "artifacts", "sars-payments",
                                          "coida", "variances")):
            deps = {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}
            assert "_za_org" in deps, route.path
