"""
tests/test_hong_kong_e2e.py
---------------------------
Hong Kong (ZP-HK-ENG-001) through the SHARED runtime and database: real
generate_payslips_for_run months, the effective-dated statutory profile,
payroll snapshot reproducibility, IR56G holds against the bank export, IRD
annual return / duplicate suppression / amendments, eMPF batches, average
wage + entitlements from committed payroll, termination, Super Admin
activation gates, onboarding gate, RBAC, tenant isolation, audit, API
validation and the migration.

SQLite in-memory (conftest `db`); app.* imported lazily. All identifiers are
synthetic (A123456(3) is the published HKID check-digit example).
"""

from datetime import date, timedelta
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

import pytest

MAKER = SimpleNamespace(id=101)
CHECKER = SimpleNamespace(id=202)

# FILED needs the external-submission record (how the employer submitted).
INTERNAL_FILING = {"submissionMode": "INTERNAL_PREPARATION_ONLY", "authorizedSigner": "Director (test)"}


# ── fixtures / helpers ──────────────────────────────────────────────────

@pytest.fixture()
def hk(db, organization, monkeypatch):
    """Both HK packs Active (test-only — production activation is gated),
    the org registered for HK, one employee joining 16 Jan 2026 with an HK
    profile version."""
    import app.core.code_generation as code_generation
    from app.modules.payroll.models import CompanyComplianceDetails
    from scripts.seed_hong_kong_canonical_pack import seed_hong_kong_all

    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)
    p25, p26 = seed_hong_kong_all(db)
    for p in (p25, p26):
        p.status = "Active"
    db.add(CompanyComplianceDetails(organization_id=organization.id, jurisdiction_country="HK", active_pack_id=p26.id,
                                    tax_identifiers={"br_number": "12345678", "ird_employer_file_number": "6A1-12345678",
                                                     "empf_employer_account": "ER-0001"}))
    db.commit()
    emp = _employee(db, organization.id, "HK1")
    _profile(db, emp, organization.id, "2026-01-16", hkgLikelyChargeable=True)
    return SimpleNamespace(org=organization, emp=emp, packs=(p25, p26))


def _employee(db, org_id, code, **kw):
    from app.modules.payroll.models import PayrollEmployee

    fields = dict(organization_id=org_id, employee_code=code, name=f"Employee {code}", country_code="HK",
                  ctc=D("240000"), date_of_birth=date(1990, 1, 1), date_of_joining=date(2026, 1, 16),
                  compliance_fields={"hkid": "A123456(3)", "mpf_member_account": f"MB-{code}"})
    fields.update(kw)
    emp = PayrollEmployee(**fields)
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _profile(db, emp, org_id, effective_from, actor=None, **fields):
    from app.modules.payroll import service
    from app.modules.payroll.schemas import EmployeeStatutoryProfileCreate

    data = EmployeeStatutoryProfileCreate(effectiveFrom=effective_from, countryCode="HK", **{
        "hkgEmploymentRelationship": "EMPLOYEE", "hkgMpfExemptionCode": "NONE", "hkgPayBasis": "MONTHLY", **fields})
    return service.create_employee_statutory_profile_version(db, emp.id, org_id, data, actor)


def _month(db, org, m, year=2026, status=None):
    import calendar

    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollRun, PayrollStatus

    last = calendar.monthrange(year, m)[1]
    run = PayrollRun(organization_id=org.id, period_label=f"{year}-{m:02d}", period_start=date(year, m, 1),
                     period_end=date(year, m, last), pay_date=date(year, m, last))
    db.add(run)
    db.commit()
    service.generate_payslips_for_run(db, run, org.id)
    run.status = status or PayrollStatus.APPROVED
    db.commit()
    return run


def _item(db, run, emp):
    from app.modules.payroll.models import PayslipItem

    return db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id).one()


def _other_org(db, code):
    from app.modules.organizations.models import Organization

    org = Organization(organization_name=f"Org {code}", organization_code=code)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


# ── End-to-end payroll (cases A–E through the shared runtime) ───────────

def test_e2e_runs_60_day_catch_up_pack_switch_no_withholding(db, hk):
    runs = {m: _month(db, hk.org, m) for m in (1, 2, 3, 4)}
    jan, feb, mar, apr = (_item(db, runs[m], hk.emp) for m in (1, 2, 3, 4))
    assert jan.hkg_calculation_trace["mpf"]["coverage"]["status"] == "PENDING_60_DAY"
    assert (jan.employee_pension, jan.employer_pension) == (0, 0)
    assert jan.hkg_calculation_trace["workerFacts"]["preJoiningUnpaidDays"] == 15
    # March: employer 5% from the FIRST day (Jan's pro-rated RI + Feb + Mar); employee from March only.
    jan_ri = D(jan.hkg_calculation_trace["mpf"]["currentPeriod"]["relevantIncome"])
    assert mar.employer_pension == (jan_ri * D("0.05")).quantize(D("0.01")) + D("1000") + D("1000")
    assert mar.employee_pension == D("1000.00")
    assert [c["payslipId"] for c in mar.hkg_calculation_trace["mpf"]["catchUp"]] == [jan.id, feb.id]
    assert (apr.employee_pension, apr.employer_pension, apr.hkg_calculation_trace["mpf"]["catchUp"]) == (1000, 1000, [])
    # Effective dating: Jan–Mar = YA 2025/26 pack, April = YA 2026/27 pack.
    p25, p26 = hk.packs
    assert {jan.tax_policy_pack_id, feb.tax_policy_pack_id, mar.tax_policy_pack_id} == {p25.id}
    assert apr.tax_policy_pack_id == p26.id
    for item in (jan, feb, mar, apr):
        assert item.tds == 0 and item.hkg_calculation_trace["salariesTax"]["withholding"] == "NONE"
        assert item.employee_statutory_profile_id is not None


def test_final_period_is_unpaid_after_the_termination_date(db, hk):
    """D-13: the joiner side already leaves pre-joining days unpaid; the leaver
    side must be symmetric, or a mid-month leaver is paid for a month they
    never worked. The convention is the platform's own 30-day month."""
    from app.modules.payroll import hk_service

    _hours(db, hk.org, hk.emp, date(2026, 1, 16), date(2026, 2, 28))
    full = _month(db, hk.org, 2)
    full_net = _item(db, full, hk.emp).net_pay

    hk_service.identify_departure(db, hk.org.id, hk.emp.id, date(2026, 2, 18), actor_id=MAKER.id)
    db.query(type(hk.emp)).filter(type(hk.emp).id == hk.emp.id).update({"date_of_leaving": date(2026, 2, 18)})
    db.commit()
    final = _month(db, hk.org, 2)
    item = _item(db, final, hk.emp)
    facts = item.hkg_calculation_trace["workerFacts"]
    assert facts["postLeavingUnpaidDays"] == 10          # 19–28 Feb, the days after termination
    assert facts["finalPeriodTerminationDate"] == "2026-02-18"
    expected_absence = (D(item.gross_pay) / D(30)).quantize(D("0.01")) * D(10)
    assert item.net_pay == D(item.gross_pay) - expected_absence - D(item.employee_pension)
    assert item.net_pay < full_net
    absence = [line for obligation in item.hkg_calculation_trace["classification"].values()
               for line in obligation["lines"] if line.get("component") == "unpaid_absence"]
    assert absence and D(absence[0]["amount"]) == -expected_absence
    # 34 days of employment is under 60, so the leaver attracts no MPF at all.
    assert item.hkg_calculation_trace["mpf"]["coverage"]["status"] == "NOT_COVERED_LEFT_BEFORE_60_DAYS"


def test_payroll_snapshot_is_reproducible_and_keeps_its_profile_version(db, hk):
    from app.modules.payroll import service

    run = _month(db, hk.org, 3)
    before = _item(db, run, hk.emp)
    first = (before.employee_pension, before.employer_pension, before.net_pay, before.employee_statutory_profile_id)
    # A later profile version (effective 1 June) must not change a March recalculation.
    _profile(db, hk.emp, hk.org.id, "2026-06-01", hkgMpfExemptionCode="EXEMPT_ORSO", hkgMpfExemptionEvidenceRef="ORSO-9")
    run.status = "Draft"
    db.commit()
    service.regenerate_employee_payslip(db, run.id, hk.emp.id, hk.org.id)
    again = _item(db, run, hk.emp)
    assert (again.employee_pension, again.employer_pension, again.net_pay, again.employee_statutory_profile_id) == first


def test_mpf_exempt_profile_version_applies_from_its_effective_date(db, hk):
    _profile(db, hk.emp, hk.org.id, "2026-05-01", hkgMpfExemptionCode="EXEMPT_ORSO", hkgMpfExemptionEvidenceRef="ORSO-1")
    may = _item(db, _month(db, hk.org, 5), hk.emp)
    assert may.hkg_calculation_trace["mpf"]["coverage"]["status"] == "EXEMPT" and may.employer_pension == 0


def test_payroll_blocks_without_active_pack(db, hk):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollRun, PayslipItem, PayslipStatus

    for p in hk.packs:
        p.status = "Draft"
    db.commit()
    run = PayrollRun(organization_id=hk.org.id, period_label="x", period_start=date(2026, 6, 1),
                     period_end=date(2026, 6, 30), pay_date=date(2026, 6, 30))
    db.add(run)
    db.commit()
    try:
        service.generate_payslips_for_run(db, run, hk.org.id)
    except Exception as exc:                      # the fail-closed error surfaces …
        assert "HK" in str(exc) or "statutory" in str(exc).lower()
    else:                                          # … or the payslip is recorded FAILED, never calculated
        items = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).all()
        assert all(i.status == PayslipStatus.FAILED for i in items)


# ── Employee statutory profile ──────────────────────────────────────────

def test_profile_versions_are_append_only_with_carry_forward(db, hk):
    from app.modules.payroll import service

    v2 = _profile(db, hk.emp, hk.org.id, "2026-07-01", hkgExpectedDepartureDate="2026-12-31")
    history = service.list_employee_statutory_profile_history(db, hk.emp.id, hk.org.id)
    v1 = history[-1]
    assert v1.effective_to == date(2026, 6, 30) and v1.hkg_expected_departure_date is None     # history intact
    assert v2.hkg_likely_chargeable is True and v2.hkg_expected_departure_date == date(2026, 12, 31)  # carried forward
    # D-19: a keyed, versioned token ("v2:" + HMAC-SHA256), never the raw identifier.
    assert v2.hkg_identity_token.startswith("v2:") and len(v2.hkg_identity_token) == 67
    assert "A123456" not in v2.hkg_identity_token


def test_frozen_pre_transition_wage_cannot_change_in_a_later_version(db, organization):
    from app.core.exceptions import BadRequestException

    emp = _employee(db, organization.id, "HKT", date_of_joining=date(2015, 5, 1))
    _profile(db, emp, organization.id, "2015-05-01", hkgPreTransitionMonthlyWage="24000",
             hkgPreTransitionWageBasis="LAST_FULL_MONTH", hkgPreTransitionEvidenceRef="PAYSLIP-2025-04")
    with pytest.raises(BadRequestException, match="frozen"):
        _profile(db, emp, organization.id, "2026-01-01", hkgPreTransitionMonthlyWage="30000",
                 hkgPreTransitionEvidenceRef="X")
    assert _profile(db, emp, organization.id, "2026-01-01").hkg_pre_transition_monthly_wage == D("24000")


@pytest.mark.parametrize("fields,match", [
    ({"hkgMpfExemptionCode": "EXEMPT_EVERYTHING"}, "hkg_mpf_exemption_code"),
    ({"hkgMpfExemptionCode": "EXEMPT_ORSO"}, "evidence"),
    ({"hkgContractualWeeklyHours": "200"}, "168"),
    ({"hkgPreTransitionMonthlyWage": "20000"}, "HK-017"),
    ({"hkgEmploymentRelationship": "FREELANCE"}, "hkg_employment_relationship"),
])
def test_profile_validation(db, hk, fields, match):
    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException, match=match):
        _profile(db, hk.emp, hk.org.id, "2026-08-01", **fields)


# ── IR56G departure hold (case I) ───────────────────────────────────────

def test_case_i_ir56g_hold_bank_export_ledger_and_four_eyes_release(db, hk):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hk_service, service
    from app.modules.payroll.models import HkgTaxClearanceHoldLine, PayslipItem

    _month(db, hk.org, 5)
    hold = hk_service.identify_departure(db, hk.org.id, hk.emp.id, date(2026, 7, 31), MAKER.id,
                                         identified_on=date(2026, 6, 26))          # 35 days ahead
    assert (hold.state, hold.filing_deadline) == ("DEPARTURE_IDENTIFIED", date(2026, 6, 30))
    hold = hk_service.record_ir56g_filed(db, hk.org.id, hold.id, date(2026, 6, 28), "IR56G-REF-1", MAKER.id)
    assert hold.state == "IR56G_FILED_HOLD_ACTIVE" and hold.statutory_hold_expiry == date(2026, 7, 28)
    june = _month(db, hk.org, 6)
    item = _item(db, june, hk.emp)
    treatment = hk_service.payment_treatment(db, hk.org.id, june, [item])
    assert treatment[item.id][0] == "HELD"
    lines = db.query(HkgTaxClearanceHoldLine).filter(HkgTaxClearanceHoldLine.hold_id == hold.id).all()
    assert [(l.payslip_item_id, l.amount) for l in lines] == [(item.id, item.net_pay)]
    assert db.query(PayslipItem).get(item.id).net_pay == item.net_pay        # a legal hold, NOT a deduction
    with pytest.raises(BadRequestException, match="no active hold|basis"):
        hk_service.request_hold_release(db, hk.org.id, hold.id, "BECAUSE", None, "x", MAKER.id)
    hk_service.request_hold_release(db, hk.org.id, hold.id, "LETTER_OF_RELEASE", "LOR-77", "letter.pdf", MAKER.id)
    with pytest.raises(BadRequestException, match="four-eyes"):
        hk_service.approve_hold_release(db, hk.org.id, hold.id, MAKER.id)
    hold = hk_service.approve_hold_release(db, hk.org.id, hold.id, CHECKER.id)
    assert hold.state == "LETTER_OF_RELEASE_RECEIVED" and hold.released_amount == item.net_pay
    assert hk_service.payment_treatment(db, hk.org.id, june, [item]) == {}
    assert hk_service.close_hold(db, hk.org.id, hold.id, CHECKER.id).state == "CASE_CLOSED"


def test_bank_export_leaves_out_held_payslips(db, hk, monkeypatch):
    from app.modules.payroll import hk_service, service

    hold = hk_service.identify_departure(db, hk.org.id, hk.emp.id, date(2026, 7, 31), MAKER.id,
                                         identified_on=date(2026, 6, 1))
    hk_service.record_ir56g_filed(db, hk.org.id, hold.id, date(2026, 6, 20), "REF", MAKER.id)
    june = _month(db, hk.org, 6)
    other = _employee(db, hk.org.id, "HK2", date_of_joining=date(2025, 1, 1))
    _profile(db, other, hk.org.id, "2025-01-01")
    service.generate_payslips_for_run(db, june, hk.org.id)
    db.commit()
    from app.modules.payroll.models import PayslipItem

    items = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == june.id).all()
    paid = {r.employee_id for r in service._build_bank_export_rows(db, june, items, hk.org.id)}
    assert str(hk.emp.id) not in paid and str(other.id) in paid           # held pay is not in the payment file


def test_changed_departure_keeps_holding_until_release(db, hk):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hk_service

    hold = hk_service.identify_departure(db, hk.org.id, hk.emp.id, date(2026, 7, 31), MAKER.id, identified_on=date(2026, 6, 1))
    hk_service.record_ir56g_filed(db, hk.org.id, hold.id, date(2026, 6, 20), "REF", MAKER.id)
    _month(db, hk.org, 6)
    with pytest.raises(BadRequestException, match="evidence"):
        hk_service.change_departure(db, hk.org.id, hold.id, "cancelled", None, MAKER.id)
    hold = hk_service.change_departure(db, hk.org.id, hold.id, "trip cancelled", "email.pdf", MAKER.id)
    assert hold.state == "DEPARTURE_CANCELLED_OR_CHANGED"
    with pytest.raises(BadRequestException, match="still holds money"):
        hk_service.close_hold(db, hk.org.id, hold.id, MAKER.id)


def test_ir56g_not_required_for_frequent_traveller(db, hk):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hk_service

    _profile(db, hk.emp, hk.org.id, "2026-05-01", hkgFrequentTravelExempt=True)
    with pytest.raises(BadRequestException, match="frequent"):
        hk_service.identify_departure(db, hk.org.id, hk.emp.id, date(2026, 9, 30), MAKER.id, identified_on=date(2026, 6, 1))


# ── IRD reporting (cases J, amendments, reconciliation) ─────────────────

def test_annual_return_from_committed_payroll_reconciles_and_files_four_eyes(db, hk):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hk_service

    for m in (1, 2, 3):
        _month(db, hk.org, m)
    _month(db, hk.org, 4)                                 # YA 2026/27 — must not be in the 2025/26 return
    out = hk_service.generate_annual_return(db, hk.org.id, "2025/26", MAKER.id)
    emp_row = out["employees"][0]
    assert emp_row["status"] == "PREPARED" and emp_row["validationErrors"] == []
    case = hk_service._case(db, hk.org.id, emp_row["caseId"])
    assert (case.income_period_start, case.income_period_end) == (date(2026, 1, 16), date(2026, 3, 31))
    # Jan: HK$20,000 − 15 unpaid days × 666.67 = 9,999.95; Feb + Mar 20,000 each.
    assert D(case.payload["total"]) == D(out["reportedTotal"]) == D(out["committedPayrollGross"]) == D("49999.95")
    hk_service.transition_ird_case(db, hk.org.id, case.id, "VALIDATED", MAKER.id)
    with pytest.raises(BadRequestException, match="four-eyes"):
        hk_service.transition_ird_case(db, hk.org.id, case.id, "FILED", MAKER.id, filing_reference="ER-2026-1", submission=INTERNAL_FILING)
    hk_service.transition_ird_case(db, hk.org.id, case.id, "FILED", CHECKER.id, filing_reference="ER-2026-1", submission=INTERNAL_FILING)
    payload_hash = case.payload_hash
    again = hk_service.generate_annual_return(db, hk.org.id, "2025/26", MAKER.id)
    assert again["employees"][0]["status"] == "FILED" and case.payload_hash == payload_hash   # never regenerated
    amendment = hk_service.amend_ird_case(db, hk.org.id, case.id, "late bonus", MAKER.id)
    db.refresh(case)
    assert (case.status, case.payload_hash, amendment.amends_case_id, amendment.status) == (
        "AMENDED", payload_hash, case.id, "PREPARED")


def test_case_j_ir56b_suppressed_after_prior_ir56f(db, hk):
    from app.modules.payroll import hk_service
    from app.modules.payroll.models import HkgIrdReportingCase

    for m in (1, 2, 3):
        _month(db, hk.org, m)
    db.add(HkgIrdReportingCase(organization_id=hk.org.id, employee_id=hk.emp.id, form_type="IR56F",
                               year_of_assessment="2025/26", event_date=date(2026, 3, 31), status="FILED",
                               income_period_start=date(2025, 4, 1), income_period_end=date(2026, 3, 31)))
    db.commit()
    out = hk_service.generate_annual_return(db, hk.org.id, "2025/26", MAKER.id)
    row = out["employees"][0]
    assert row["status"] == "SUPPRESSED" and "twice" in row["message"]


def test_uncommitted_runs_are_not_reported(db, hk):
    from app.modules.payroll import hk_service
    from app.modules.payroll.models import PayrollStatus

    _month(db, hk.org, 3, status=PayrollStatus.DRAFT)
    assert hk_service.generate_annual_return(db, hk.org.id, "2025/26", MAKER.id)["employees"] == []


def test_ir56e_event_case_from_profile_facts(db, hk):
    from app.modules.payroll import hk_service

    cases = hk_service.create_event_cases(db, hk.org.id, hk.emp.id, MAKER.id)
    assert [(c.form_type, c.due_date) for c in cases] == [("IR56E", date(2026, 4, 16))]
    assert hk_service.create_event_cases(db, hk.org.id, hk.emp.id, MAKER.id) == []          # idempotent


# ── eMPF (rejected row never rewrites payroll) ──────────────────────────

def test_empf_batch_partial_rejection_does_not_touch_payroll(db, hk):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hk_service

    run = _month(db, hk.org, 4)
    before = _item(db, run, hk.emp).employee_pension
    sub = hk_service.prepare_empf_submission(db, hk.org.id, "2026-04", MAKER.id)
    assert sub.status == "VALIDATED" and sub.totals["employees"] == 1 and sub.contribution_day == date(2026, 5, 10)
    assert "A123456(3)" not in str(sub.rows)                                      # identifiers masked
    with pytest.raises(BadRequestException, match="four-eyes"):
        hk_service.transition_empf_submission(db, hk.org.id, sub.id, "SUBMITTED", MAKER.id, submission_reference="E-1")
    hk_service.transition_empf_submission(db, hk.org.id, sub.id, "SUBMITTED", CHECKER.id, submission_reference="E-1")
    with pytest.raises(BadRequestException, match="PARTIAL"):
        hk_service.transition_empf_submission(db, hk.org.id, sub.id, "ACCEPTED", CHECKER.id,
                                              row_outcomes=[{"payslipId": 1, "status": "ACCEPTED"},
                                                            {"payslipId": 2, "status": "REJECTED"}])
    sub = hk_service.transition_empf_submission(db, hk.org.id, sub.id, "PARTIAL", CHECKER.id,
                                                row_outcomes=[{"payslipId": 1, "status": "ACCEPTED"},
                                                              {"payslipId": 2, "status": "REJECTED"}])
    assert sub.status == "PARTIAL" and _item(db, run, hk.emp).employee_pension == before


def test_empf_validation_flags_missing_identity_and_employer_account(db, hk):
    from app.modules.payroll import hk_service
    from app.modules.payroll.models import CompanyComplianceDetails

    hk.emp.compliance_fields = {}
    comp = db.query(CompanyComplianceDetails).filter(CompanyComplianceDetails.organization_id == hk.org.id).one()
    comp.tax_identifiers = {}
    db.commit()
    _month(db, hk.org, 4)
    sub = hk_service.prepare_empf_submission(db, hk.org.id, "2026-04", MAKER.id)
    assert sub.status == "PREPARED" and any("eMPF employer account" in e for e in sub.validation_errors)
    assert any("HKID" in e for e in sub.validation_errors)


# ── Average wage + entitlements from committed payroll ──────────────────

def test_average_wage_from_committed_payroll_shorter_period_and_override_four_eyes(db, hk):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hk_service

    for m in (1, 2, 3, 4):
        _month(db, hk.org, m)
    snap = hk_service.calculate_average_wage(db, hk.org.id, hk.emp.id, "ANNUAL_LEAVE", date(2026, 5, 10), [], MAKER.id)
    assert (snap.lookback_start, snap.lookback_end, snap.total_days) == (date(2026, 1, 16), date(2026, 4, 30), 105)
    assert snap.result["shorterEmploymentPeriod"] is True and len(snap.included_rows) == 4
    assert snap.total_wages == D("69999.95")                       # Jan 9,999.95 (pro-rated) + Feb–Apr
    with pytest.raises(BadRequestException, match="evidence"):
        hk_service.request_average_wage_override(db, hk.org.id, snap.id, "700", "", None, MAKER.id)
    hk_service.request_average_wage_override(db, hk.org.id, snap.id, "700", "court order", "ORDER-1", MAKER.id)
    with pytest.raises(BadRequestException, match="four-eyes"):
        hk_service.approve_average_wage_override(db, hk.org.id, snap.id, MAKER.id)
    snap = hk_service.approve_average_wage_override(db, hk.org.id, snap.id, CHECKER.id)
    eff = hk_service.effective_average(snap)
    assert eff["averageDailyWage"] == "700.0000" and eff["calculatedAverageDailyWage"] == snap.result["averageDailyWage"]


def test_average_wage_blocks_on_uncertified_eo_classification(db, hk, monkeypatch):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hk_service, service

    monkeypatch.setattr(service, "_sum_attendance_extras", lambda *a, **k: D("3000"))   # additional compensation
    for m in (2, 3):
        _month(db, hk.org, m)
    with pytest.raises(BadRequestException, match="not certified"):
        hk_service.calculate_average_wage(db, hk.org.id, hk.emp.id, "SICKNESS", date(2026, 4, 2), [], MAKER.id)


def test_annual_leave_entitlement_through_the_service(db, hk):
    from app.modules.payroll import hk_service

    for m in (1, 2, 3, 4):
        _month(db, hk.org, m)
    hk_service.record_work_hours(db, hk.org.id, hk.emp.id,
                                 [{"date": d.isoformat(), "hours": "8"}
                                  for d in (date(2026, 1, 16) + timedelta(days=i) for i in range(115)) if d.weekday() < 5],
                                 MAKER.id)
    snap = hk_service.calculate_average_wage(db, hk.org.id, hk.emp.id, "ANNUAL_LEAVE", date(2026, 5, 10), [], MAKER.id)
    out = hk_service.calculate_entitlement(db, hk.org.id, hk.emp.id, "ANNUAL_LEAVE_PAY",
                                           {"averageWageSnapshotId": snap.id, "days": "3", "date": "2026-05-10"})
    assert D(out["amount"]) == (D(snap.result["averageDailyWage"]) * 3).quantize(D("0.01"))


def test_work_hours_are_append_only(db, hk):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hk_service
    from app.modules.payroll.models import HkgWorkHours

    hk_service.record_work_hours(db, hk.org.id, hk.emp.id, [{"date": "2026-02-02", "hours": "8"}], MAKER.id)
    with pytest.raises(BadRequestException, match="reason"):
        hk_service.record_work_hours(db, hk.org.id, hk.emp.id, [{"date": "2026-02-02", "hours": "9"}], MAKER.id)
    hk_service.record_work_hours(db, hk.org.id, hk.emp.id, [{"date": "2026-02-02", "hours": "9"}], MAKER.id, "timesheet fix")
    rows = db.query(HkgWorkHours).filter(HkgWorkHours.employee_id == hk.emp.id).order_by(HkgWorkHours.id).all()
    assert [(r.hours, r.superseded_by_id is not None) for r in rows] == [(D("8"), True), (D("9"), False)]
    assert hk_service.hours_map(db, hk.emp.id, date(2026, 2, 1), date(2026, 2, 28)) == {"2026-02-02": "9.00"}


# ── Termination (case K) ────────────────────────────────────────────────

def test_case_k_termination_through_the_service_with_frozen_wage_and_four_eyes(db, organization, hk):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hk_service

    emp = _employee(db, hk.org.id, "HKK", date_of_joining=date(2015, 5, 1))
    _profile(db, emp, hk.org.id, "2015-05-01", hkgContractualWeeklyHours="44", hkgPreTransitionMonthlyWage="24000",
             hkgPreTransitionWageBasis="LAST_FULL_MONTH", hkgPreTransitionEvidenceRef="PAYSLIP-2025-04")
    row = hk_service.calculate_termination(db, hk.org.id, emp.id, {
        "terminationDate": "2027-03-31", "reason": "REDUNDANCY", "postTransitionWage": "30000",
        "offsets": [{"type": "EMPLOYER_MANDATORY_MPF", "amount": "500000"}]}, MAKER.id)
    r = row.result
    assert r["paymentType"] == "SP" and r["portions"]["preTransition"]["wage"] == "24000.00"
    assert row.net_statutory_payment == D(r["portions"]["postTransition"]["amount"])   # mandatory offset hits pre only
    with pytest.raises(BadRequestException, match="frozen"):
        hk_service.calculate_termination(db, hk.org.id, emp.id, {
            "terminationDate": "2027-03-31", "reason": "REDUNDANCY", "postTransitionWage": "30000",
            "preTransitionWage": "40000"}, MAKER.id)
    with pytest.raises(BadRequestException, match="four-eyes"):
        hk_service.approve_termination(db, hk.org.id, row.id, MAKER.id)
    assert hk_service.approve_termination(db, hk.org.id, row.id, CHECKER.id).status == "APPROVED"


# ── Super Admin lifecycle / activation gates ────────────────────────────

def _draft_packs(db):
    from scripts.seed_hong_kong_canonical_pack import seed_hong_kong_all

    packs = seed_hong_kong_all(db)
    db.commit()
    return packs


def _specialist_verified(db, pack, actor_id):
    """TEST-ONLY stand-in for the G1 specialist's confirmation, recorded the
    production way: every row that is not SOURCED is re-linked (governed edit,
    Draft pack) to a reviewed, hashed source. Values are unchanged."""
    from app.modules.payroll import hk_configuration
    from app.modules.payroll.models import SourceArtifact

    src = SourceArtifact(agency="HK specialist (TEST)", title="TEST verified statutory source", form_number="HK-TEST-VERIFIED",
                         checksum_sha256="1" * 64, file_path="verified.pdf", created_by_id=MAKER.id, reviewer_id=CHECKER.id)
    db.add(src)
    db.commit()
    for d in hk_configuration.domains(db, pack.id)["domains"]:
        for r in d["rows"]:
            if r["status"] != "SOURCED":
                hk_configuration.update_row(db, r["kind"], r["id"], {"reason": "TEST specialist verification",
                                                                     "sourceDocumentId": src.id,
                                                                     "specialistVerified": True}, actor_id)


def _g1(db, tmp_path):
    from app.modules.payroll.models import SourceArtifact

    doc = tmp_path / "g1.pdf"
    doc.write_bytes(b"%PDF-1.4 signed")
    art = SourceArtifact(agency="HK specialist", title="G1 certification", form_number="HK-GATE-G1",
                         created_by_id=MAKER.id, reviewer_id=CHECKER.id, file_path=str(doc))
    db.add(art)
    db.commit()
    return art


def test_hk_activation_requires_g1_golden_and_distinct_approver_activator(db, tmp_path):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    _p25, p26 = _draft_packs(db)
    run = service.run_golden_test_certification(db, jurisdiction_country="HK", actor_id=CHECKER.id)
    assert (run.status, run.real_case_count) == ("PASS", run.total_cases) and run.total_cases >= 11
    service.set_jurisdiction_pack_approver(db, p26.id, CHECKER.id)
    with pytest.raises(BadRequestException, match="G1"):
        service.set_jurisdiction_pack_status(db, p26.id, "Active", actor_id=MAKER.id)
    _g1(db, tmp_path)
    with pytest.raises(BadRequestException, match="not source-verified"):          # unverified rows never go Active
        service.set_jurisdiction_pack_status(db, p26.id, "Active", actor_id=MAKER.id)
    db.rollback()
    _specialist_verified(db, p26, MAKER.id)                                         # resets the approval
    service.set_jurisdiction_pack_approver(db, p26.id, CHECKER.id)
    with pytest.raises(BadRequestException, match="approved this pack cannot also activate"):
        service.set_jurisdiction_pack_status(db, p26.id, "Active", actor_id=CHECKER.id)
    assert service.set_jurisdiction_pack_status(db, p26.id, "Active", actor_id=MAKER.id).status == "Active"
    with pytest.raises(BadRequestException, match="supersede"):
        service.set_jurisdiction_pack_status(db, p26.id, "Draft", actor_id=MAKER.id)


def test_hk_hotfix_activation_is_refused_and_audited(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import TaxConfigurationAudit

    _p25, p26 = _draft_packs(db)
    with pytest.raises(BadRequestException, match="hotfix activation is not permitted"):
        service.activate_jurisdiction_pack_hotfix(db, p26.id, "INC-1", "urgent", actor_id=MAKER.id)
    assert db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.action == "refused",
                                                  TaxConfigurationAudit.entity_id == p26.id).count() >= 1


def test_hk_gate_evidence_needs_an_uploaded_document_and_a_second_reviewer(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hk_service, service
    from app.modules.payroll.models import SourceArtifact

    art = SourceArtifact(agency="x", title="G1", form_number="HK-GATE-G1", created_by_id=MAKER.id)
    db.add(art)
    db.commit()
    with pytest.raises(BadRequestException, match="uploaded document"):
        service.mark_source_artifact_reviewed(db, art.id, CHECKER.id)
    art.file_path = "/tmp/doc.pdf"
    db.commit()
    with pytest.raises(BadRequestException, match="different"):
        service.mark_source_artifact_reviewed(db, art.id, MAKER.id)
    assert hk_service.gate_state(db, "G1") == "SUBMITTED"
    service.mark_source_artifact_reviewed(db, art.id, CHECKER.id)
    assert hk_service.gate_state(db, "G1") == "PASS"


def test_statutory_summary_lists_gates_blockers_and_g1_items(db):
    from app.modules.payroll import hk_service

    _draft_packs(db)
    s = hk_service.statutory_summary(db)
    assert [g["gate"] for g in s["gates"]] == ["G1", "G2", "G3", "G4", "G5", "G6", "G7"]
    assert all(g["state"] == "EVIDENCE_REQUIRED" for g in s["gates"])
    assert s["serviceRegistry"] == "PLANNED" and s["certificationItems"]
    assert all(p["unsourcedRows"] == [] for p in s["packs"])
    assert "organization" not in str(s).lower()                            # platform-level only


def test_onboarding_into_hk_is_blocked_while_planned_or_unregistered(db):
    from app.modules.billing.models import JurisdictionServiceRegistry
    from app.modules.payroll.engine.tax_resolver import (get_jurisdiction_change_block_reason,
                                                         get_jurisdiction_onboarding_block_reason)

    assert get_jurisdiction_onboarding_block_reason(db, "Hong Kong") is not None      # no registry row
    _draft_packs(db)
    assert db.query(JurisdictionServiceRegistry).filter_by(country="HK").one().availability == "PLANNED"
    assert get_jurisdiction_change_block_reason(db, "Singapore", "Hong Kong") is not None


def test_super_admin_preview_runs_engine_on_draft_pack_and_writes_nothing(db):
    from app.modules.payroll import hk_service
    from app.modules.payroll.models import PayslipItem
    from app.modules.payroll.schemas import HKCalculationPreviewRequest

    _draft_packs(db)
    out = hk_service.preview_calculation(db, HKCalculationPreviewRequest(
        payDate=date(2026, 6, 30), gross="45000", dateOfBirth=date(1990, 1, 1), dateOfJoining=date(2024, 1, 1)))
    assert (out["status"], out["packStatus"], out["mpfEmployee"], out["incomeTaxWithheld"]) == ("CALCULATED", "Draft", "1500.00", "0")
    assert db.query(PayslipItem).count() == 0


# ── Tenant isolation / RBAC / API ───────────────────────────────────────

def test_tenant_isolation_across_hk_operations(db, hk):
    from app.core.exceptions import BadRequestException, NotFoundException
    from app.modules.payroll import hk_service

    other = _other_org(db, "OTHERHK")
    hold = hk_service.identify_departure(db, hk.org.id, hk.emp.id, date(2026, 9, 30), MAKER.id, identified_on=date(2026, 6, 1))
    with pytest.raises(NotFoundException):
        hk_service._hold(db, other.id, hold.id)
    with pytest.raises(NotFoundException):
        hk_service.identify_departure(db, other.id, hk.emp.id, date(2026, 9, 30), MAKER.id)
    with pytest.raises(NotFoundException):
        hk_service.calculate_average_wage(db, other.id, hk.emp.id, "SICKNESS", date(2026, 5, 1), [], MAKER.id)
    for m in (1, 2, 3):
        _month(db, hk.org, m)
    assert hk_service.generate_annual_return(db, other.id, "2025/26", MAKER.id)["employees"] == []
    sg = _employee(db, hk.org.id, "SG1", country_code="SG")
    with pytest.raises(BadRequestException, match="not a Hong Kong employee"):
        hk_service.record_work_hours(db, hk.org.id, sg.id, [{"date": "2026-02-02", "hours": "8"}], MAKER.id)


def _hours(db, org, emp, start, end, per_day=8):
    """Verified daily hours (weekdays only) so continuous contract and the
    minimum-wage test can be evaluated from records, not assumptions."""
    from app.modules.payroll import hk_service

    entries = [{"date": (start + timedelta(days=i)).isoformat(), "hours": D(per_day)}
               for i in range((end - start).days + 1)
               if (start + timedelta(days=i)).weekday() < 5]
    hk_service.record_work_hours(db, org.id, emp.id, entries, MAKER.id)
    return entries


def test_preflight_on_a_calculated_run_is_clear_and_names_the_pack(db, hk):
    from app.modules.payroll import service

    _hours(db, hk.org, hk.emp, date(2026, 1, 16), date(2026, 3, 31))
    run = _month(db, hk.org, 3)                      # period ends 31 Mar, paid 31 Mar
    out = service.hk_payroll_preflight(db, hk.org.id, run.id, today=date(2026, 3, 31))
    assert out["employeeCount"] == 1 and out["calculated"] == 1
    assert out["pack"].startswith(hk.packs[0].pack_id)
    assert out["wagePeriodEnd"] == "2026-03-31"
    assert not [c for c in out["checks"] if c["severity"] == "BLOCK"], out["checks"]
    codes = {c["code"] for c in out["checks"]}
    assert {"EO_WAGE_PAYMENT_TIMING", "EO_CONTINUOUS_CONTRACT"} <= codes


def test_preflight_blocks_when_continuity_cannot_be_determined(db, hk):
    from app.modules.payroll import service

    # No recorded hours and no contractual weekly hours: continuity is NEVER assumed.
    run = _month(db, hk.org, 3)
    out = service.hk_payroll_preflight(db, hk.org.id, run.id, today=date(2026, 3, 31))
    assert out["status"] == "BLOCKED"
    blocked = {c["code"]: c for c in out["checks"] if c["severity"] == "BLOCK"}
    assert blocked["EO_CC_UNDETERMINED"]["employeeId"] == hk.emp.id


def test_preflight_blocks_a_late_run_and_a_leaver(db, hk):
    from app.modules.payroll import service

    _hours(db, hk.org, hk.emp, date(2026, 1, 16), date(2026, 2, 28))
    run = _month(db, hk.org, 2)
    hk.emp.date_of_leaving = date(2026, 2, 20)
    db.commit()
    out = service.hk_payroll_preflight(db, hk.org.id, run.id, today=date(2026, 2, 28))
    assert out["status"] == "BLOCKED"
    assert "EO_TERMINATION_WAGES_DUE_IMMEDIATELY" in {c["code"] for c in out["checks"]}


def test_preflight_dry_runs_an_uncalculated_run_and_reports_the_ir56g_hold(db, hk):
    import calendar

    from app.modules.payroll import hk_service, service
    from app.modules.payroll.models import PayrollRun

    _hours(db, hk.org, hk.emp, date(2026, 1, 16), date(2026, 4, 30))
    last = calendar.monthrange(2026, 4)[1]
    run = PayrollRun(organization_id=hk.org.id, period_label="2026-04", period_start=date(2026, 4, 1),
                     period_end=date(2026, 4, last), pay_date=date(2026, 4, last))
    db.add(run)
    db.commit()
    out = service.hk_payroll_preflight(db, hk.org.id, run.id, today=date(2026, 4, 30))
    assert out["calculated"] == 0 and not [c for c in out["checks"] if c["severity"] == "BLOCK"], out["checks"]
    # A departure on the last day of the period: IR56G due, so final payment is held.
    hk_service.identify_departure(db, hk.org.id, hk.emp.id, date(2026, 4, last), actor_id=MAKER.id)
    held = service.hk_payroll_preflight(db, hk.org.id, run.id, today=date(2026, 4, 30))
    assert "IR56G_NOT_YET_FILED" in {c["code"] for c in held["checks"]}


def test_hk_preflight_block_refuses_approval_until_it_is_resolved(db, hk):
    """A BLOCK check is a statutory exception, so the Approve button must not
    move the run — and must let it through once the exception is gone."""
    from fastapi import HTTPException

    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollStatus

    _hours(db, hk.org, hk.emp, date(2026, 1, 16), date(2026, 2, 28))
    run = _month(db, hk.org, 2, status=PayrollStatus.REVIEW)
    hk.emp.date_of_leaving = date(2026, 2, 20)      # EO: residual wages due immediately
    db.commit()
    with pytest.raises(HTTPException) as blocked:
        service.advance_payroll_run_status(db, run.id, MAKER.id, hk.org.id)
    assert blocked.value.status_code == 409 and "Hong Kong preflight" in blocked.value.detail
    assert db.query(type(run)).get(run.id).status == PayrollStatus.REVIEW
    hk.emp.date_of_leaving = None                  # the exception is resolved
    db.commit()
    assert service.advance_payroll_run_status(db, run.id, MAKER.id, hk.org.id).status == PayrollStatus.APPROVED


def test_shared_holiday_calendar_is_seeded_from_the_hk_pack(db, hk):
    """D-9: the shared PayrollHoliday calendar comes from the pack's own
    source-linked holiday rows — and a year the pack does not cover seeds
    nothing rather than a guessed date."""
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollHoliday

    rows = service._seed_holidays_for_country(db, hk.org.id, "HK", 2026)
    assert [r.name for r in rows][:6] == ["The first day of January", "Lunar New Year's Day", "The second day of "
                                                                                          "Lunar New Year",
                                            "The third day of Lunar New Year", "Ching Ming Festival",
                                            "Easter Monday"]
    assert all(r.category == "Statutory" and r.country == "HK" for r in rows)
    assert db.query(PayrollHoliday).filter(PayrollHoliday.organization_id == hk.org.id,
                                           PayrollHoliday.country == "HK").count() == len(rows)
    # No Labour Department calendar for 2031 in the pack: nothing is invented.
    assert service._seed_holidays_for_country(db, hk.org.id, "HK", 2031) == []


def test_every_hk_route_is_role_gated():
    from app.core.dependencies import get_current_payroll_operator, get_current_super_admin
    from app.main import app

    def deps(route):
        found, stack = set(), list(route.dependant.dependencies)
        while stack:
            d = stack.pop()
            found.add(d.call)
            stack.extend(d.dependencies)
        return found

    hk_routes = [r for r in app.routes if "hong-kong" in getattr(r, "path", "")]
    assert len(hk_routes) >= 28
    for r in hk_routes:
        needed = get_current_super_admin if "/super-admin/" in r.path else get_current_payroll_operator
        assert needed in deps(r), r.path
    assert any(r.path == "/api/payroll/hong-kong/runs/{run_id}/preflight" for r in hk_routes)


def test_api_validation_and_operator_role_over_http(db, hk):
    from fastapi.testclient import TestClient

    from app.core.dependencies import get_current_org_scoped_principal, get_current_user
    from app.database import get_db
    from app.main import app
    from app.modules.billing.entitlements import require_active_subscription
    from app.modules.payroll import router as payroll_router_module

    operator = SimpleNamespace(id=MAKER.id, organization_id=hk.org.id, role="payroll_admin", is_active=True)
    saved = dict(app.dependency_overrides)
    app.dependency_overrides.update({get_db: lambda: db, get_current_user: lambda: operator,
                                     get_current_org_scoped_principal: lambda: operator,
                                     require_active_subscription: lambda: None,
                                     payroll_router_module._HK_WRITE[1].dependency: lambda: None})
    try:
        client = TestClient(app)
        bad = client.post(f"/api/payroll/hong-kong/employees/{hk.emp.id}/work-hours",
                          json={"entries": [{"date": "2026-02-02", "hours": "8"}], "unexpected": 1})
        assert bad.status_code == 422                                              # extra fields forbidden
        ok = client.post(f"/api/payroll/hong-kong/employees/{hk.emp.id}/work-hours",
                         json={"entries": [{"date": "2026-02-02", "hours": "8"}]})
        assert ok.status_code == 200 and ok.json()[0]["hours"] == "8.00"
        bad_ya = client.post("/api/payroll/hong-kong/ird/annual-return", json={"yearOfAssessment": "2026"})
        assert bad_ya.status_code == 422
        est = client.post("/api/payroll/hong-kong/salaries-tax/estimate",
                          json={"yearOfAssessment": "2026/27", "income": "380000", "allowances": {"basic": 1}})
        assert est.status_code == 200 and est.json()["estimatedTax"] == "21950.00"
        assert est.json()["label"] == "INFORMATIONAL_NOT_WITHHELD"
        employee_user = SimpleNamespace(id=9, organization_id=hk.org.id, role="employee", is_active=True)
        app.dependency_overrides[get_current_user] = lambda: employee_user
        app.dependency_overrides[get_current_org_scoped_principal] = lambda: employee_user
        assert client.get("/api/payroll/hong-kong/tax-clearance").status_code == 403
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)


def test_audit_trail_for_profile_hold_and_filing(db, hk):
    from app.modules.payroll import hk_service
    from app.modules.payroll.models import TaxConfigurationAudit

    hold = hk_service.identify_departure(db, hk.org.id, hk.emp.id, date(2026, 9, 30), MAKER.id, identified_on=date(2026, 6, 1))
    hk_service.record_ir56g_filed(db, hk.org.id, hold.id, date(2026, 8, 20), "REF", MAKER.id)
    types = {a.entity_type for a in db.query(TaxConfigurationAudit).all()}
    assert {"employee_statutory_profile", "hkg_tax_clearance_hold", "jurisdiction_pack"} <= types


# ── Payslip presentation / report fields ────────────────────────────────

def test_payslip_labels_mpf_and_never_income_tax_withheld(db, hk):
    from app.modules.payroll import service

    run = _month(db, hk.org, 4)
    item = _item(db, run, hk.emp)
    assert "tds" not in service._PAYSLIP_FIELDS_BY_COUNTRY["HK"]
    assert "employee_pension" in service._PAYSLIP_FIELDS_BY_COUNTRY["HK"]
    assert service._PAYSLIP_FIELD_LABEL_OVERRIDES["HK"]["employee_pension"].startswith("MPF")
    data = service._serialize_payslip(item, run, "HK")
    assert data["hkgCalculationTrace"]["result"]["mpfEmployee"] == "1000.00"
    assert data["hkgCalculationTrace"]["salariesTax"]["withholding"] == "NONE"


# ── Migration ───────────────────────────────────────────────────────────

def test_every_hkg_table_and_column_is_created_by_the_migration():
    from app.database import Base
    import app.modules.payroll.models  # noqa: F401

    src = (Path(__file__).parents[1] / "alembic/versions/cd62503afe26_hong_kong_statutory_foundation.py").read_text(encoding="utf8")
    for name, table in Base.metadata.tables.items():
        if name.startswith("hkg_"):
            assert f"'{name}'" in src, name
            for col in table.columns:
                assert f"'{col.name}'" in src, f"{name}.{col.name}"
        for col in table.columns:
            if col.name.startswith("hkg_") and not name.startswith("hkg_"):
                assert f"'{col.name}'" in src, f"{name}.{col.name}"
    assert "down_revision: Union[str, Sequence[str], None] = '445abd6a9083'" in src
