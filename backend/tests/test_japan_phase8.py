"""Japan Phase 8: replay, run exceptions, corrections, obligations, journal,
year-end adjustment and filing previews (ZP-JP-ENG-001 §8). Every value is
synthetic; the year-end tables below are test fixtures, not statutory figures.
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.exceptions import BadRequestException
from app.modules.payroll import japan_filing as filing
from app.modules.payroll import japan_journal as journal
from app.modules.payroll import japan_lifecycle as lifecycle
from app.modules.payroll import japan_service as jp
from app.modules.payroll import japan_year_end as yea
from app.modules.payroll.engine.countries import japan
from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError
from app.modules.payroll.engine.jurisdictions.japan import year_end
from app.modules.payroll.engine.standard import StandardStrategy
from app.modules.payroll.models import (
    PayrollEmployee, PayrollJpEmployerRegistration, PayrollRun, PayslipItem,
)
from tests.test_japan_engine import D, _base_rate_map, _context, _slabs


# ── synthetic signed content ────────────────────────────────────────────────
def _yea_rows():
    row = lambda rule, low, high, **kw: SimpleNamespace(  # noqa: E731
        rule_type=rule, min_amount=D(low), max_amount=None if high is None else D(high),
        rate_pct=kw.get("rate"), flat_amount=kw.get("flat"), formula_expression=None,
        filing_status=kw.get("category"), tax_regime=None, tax_column=None, tax_table_number=None,
        jurisdiction_state=None, effective_from=None, effective_to=None)
    return [row("JP_YEA_EID", 0, None, rate=D(30)),                 # 30% of annual pay
            row("JP_YEA_BASIC", 0, None, flat=D(480000)),
            row("JP_YEA_RATE", 0, None, rate=D(10), flat=D(0)),
            row("JP_YEA_DEPENDANT", 0, None, flat=D(380000), category="GENERAL"),
            row("JP_YEA_SPOUSE", 0, 1000000, flat=D(380000)),
            row("JP_YEA_LIFE_INS", 0, None, rate=D(50))]


def _yea_rate_map(policy=None, earliest="11"):
    rate_map = _base_rate_map()
    values = {"jp_yea_income_limit": ("flat_amount", D(20000000)),
              "jp_yea_earthquake_cap": ("flat_amount", D(50000)),
              "jp_reconstruction_surtax_pct": ("flat_amount", D(2)),
              "jp_yea_taxable_rounding": ("text_value", "DOWN_1000"),
              "jp_yea_rounding": ("text_value", "DOWN_100"),
              "jp_yea_earliest_month": ("text_value", earliest)}
    for key, (field, value) in values.items():
        setattr(rate_map[key], field, value)
    if policy:
        rate_map["jp_correction_policy"].text_value = policy
    return rate_map


def _ctx(**overrides):
    kwargs = dict(rate_map=_yea_rate_map(overrides.pop("policy", None)), slabs=_slabs() + _yea_rows())
    kwargs.update(overrides)
    return _context(**kwargs)


def _snap(ctx):
    result = StandardStrategy().calculate(ctx)
    return result, jp.jp_payslip_snapshot(result.jp_result, jp.jp_freeze_context(ctx))


@pytest.fixture()
def employee(db, organization):
    row = PayrollEmployee(organization_id=organization.id, employee_code="JP-P8-1",
                          name="Synthetic Employee", country_code="JP")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _run(db, organization, pay_date, status="Paid", created_by=1):
    run = PayrollRun(organization_id=organization.id, period_label=str(pay_date),
                     period_start=pay_date.replace(day=1), period_end=pay_date, pay_date=pay_date,
                     status=status, created_by=created_by)
    db.add(run)
    db.flush()
    return run


def _payslip(db, organization, employee, run, ctx=None):
    result, snap = _snap(ctx or _ctx())
    item = PayslipItem(payroll_run_id=run.id, employee_id=employee.id, organization_id=organization.id,
                       employee_name=employee.name, country_code="JP", gross_pay=result.gross,
                       tds=result.tds, total_deductions=result.total_deductions, net_pay=result.net_pay,
                       jp_calculation_snapshot=snap)
    db.add(item)
    db.commit()
    return item


# ── replay ──────────────────────────────────────────────────────────────────
def test_a_frozen_payslip_replays_exactly():
    ctx = _ctx()
    result, snap = _snap(ctx)
    replayed = jp.jp_replay(snap["frozenContext"])
    assert replayed.tds == result.tds
    assert replayed.jp_result["jp_employee_total"] == result.jp_result["jp_employee_total"]
    assert replayed.jp_result["jp_resident_tax"] == result.jp_result["jp_resident_tax"]


def test_a_payslip_without_a_frozen_context_cannot_be_replayed():
    with pytest.raises(BadRequestException):
        jp.jp_thaw_context({})


# ── engine: the year-end difference ─────────────────────────────────────────
def test_year_end_refund_lowers_this_payment_withholding():
    jp_result = japan.calculate(_context(jp_year_end_difference=D(1200), jp_yea_case_id=5))
    assert jp_result["tds"] == D(5000 - 1200)
    assert jp_result["jp_result"]["jp_yea_difference"] == "1200"
    assert jp_result["jp_result"]["trace"]["yearEnd"]["direction"] == "REFUND"


@pytest.mark.parametrize("overrides,key", [
    ({"jp_year_end_difference": D(100)}, "jp_yea_case_id"),
    ({"jp_year_end_difference": D(100), "jp_yea_case_id": 1, "jp_payment_kind": "BONUS",
      "gross": D(0), "basic": D(0)}, "jp_year_end_difference"),
])
def test_year_end_difference_needs_its_case_and_a_salary_payment(overrides, key):
    with pytest.raises(MissingComplianceConfigurationError) as exc:
        japan.calculate(_context(**overrides))
    assert exc.value.key in (key, "jp_payment_kind")


# ── run exceptions (four-eyes, bound to the payload) ────────────────────────
def test_run_exceptions_need_a_second_person_and_follow_the_payload(db, organization, employee):
    run = _run(db, organization, date(2026, 6, 25), status="Review", created_by=1)
    item = _payslip(db, organization, employee, run)
    codes = {e["code"] for e in lifecycle.jp_run_exceptions(db, run)}
    assert codes == {"FIRST_OR_LAST_PAYROLL", "BANK_CHANGE_HISTORY_UNAVAILABLE"}

    key = "FIRST_OR_LAST_PAYROLL:%d" % employee.id
    with pytest.raises(BadRequestException, match="preparer"):
        lifecycle.approve_jp_run_exception(db, organization_id=organization.id, run_id=run.id,
                                           key=key, approver_id=1)
    lifecycle.approve_jp_run_exception(db, organization_id=organization.id, run_id=run.id,
                                       key=key, approver_id=2, note="new hire")
    db.commit()
    assert next(e for e in lifecycle.jp_run_exceptions(db, run) if e["key"] == key)["approved"]

    # A changed payslip is a new payload: the earlier approval no longer covers it.
    item.jp_calculation_snapshot = {**item.jp_calculation_snapshot, "jp_wht": "9999"}
    db.commit()
    assert not next(e for e in lifecycle.jp_run_exceptions(db, run) if e["key"] == key)["approved"]


def test_approval_is_refused_while_an_exception_is_open(db, organization, employee):
    from app.modules.payroll.models import PayrollStatus

    run = _run(db, organization, date(2026, 6, 25), status="Review")
    _payslip(db, organization, employee, run)
    with pytest.raises(HTTPException) as exc:
        jp.before_run_transition(db, run, PayrollStatus.APPROVED, 1)
    assert exc.value.status_code == 409 and "exception" in exc.value.detail


# ── corrections (JP-006) ────────────────────────────────────────────────────
def test_corrections_block_while_the_policy_is_pending(db, organization, employee):
    run = _run(db, organization, date(2026, 6, 25))
    item = _payslip(db, organization, employee, run)
    with pytest.raises(BadRequestException, match="jp_correction_policy is PENDING_G1"):
        lifecycle.create_jp_correction(db, organization_id=organization.id, payslip_item_id=item.id,
                                       reason="late pay change", changes={"basic": "310000"}, actor_id=1)


def test_signed_policy_books_a_delta_payslip_and_never_edits_the_original(db, organization, employee):
    run = _run(db, organization, date(2026, 6, 25))
    item = _payslip(db, organization, employee, run, _ctx(policy="DELTA_PAYSLIP"))
    original = dict(item.jp_calculation_snapshot)
    out = lifecycle.create_jp_correction(
        db, organization_id=organization.id, payslip_item_id=item.id, reason="late pay change",
        changes={"gross": "310000", "basic": "310000"}, actor_id=1)
    db.commit()
    assert out["grossDelta"] == "10000"
    assert out["deltas"]["employee"] == "50"            # EI 0.5% of the extra 10,000 (synthetic)
    delta = db.get(PayslipItem, out["payslipId"])
    assert delta.gross_pay == D(10000) and delta.jp_calculation_snapshot["correction"]["originalPayslipId"] == item.id
    assert db.get(PayrollRun, out["correctionRunId"]).notes.startswith(lifecycle.JP_CORRECTION_MARKER)
    db.refresh(item)
    assert item.jp_calculation_snapshot == original
    with pytest.raises(BadRequestException, match="not correctable"):
        lifecycle.create_jp_correction(db, organization_id=organization.id, payslip_item_id=item.id,
                                       reason="x", changes={"tds": "0"}, actor_id=1)


# ── obligations ─────────────────────────────────────────────────────────────
def test_paid_run_records_each_obligation_once_with_signed_due_dates(db, organization, employee):
    run = _run(db, organization, date(2026, 6, 25))
    _payslip(db, organization, employee, run)
    created = filing.record_run_obligations(db, run, actor_id=1)
    db.commit()
    by_type = {o.obligation_type: o for o in created}
    assert by_type["WHT_REMITTANCE"].amount == D(5000)
    assert by_type["WHT_REMITTANCE"].due_on == date(2026, 7, 10)
    assert by_type["SI_REMITTANCE"].amount == D(42450 * 2)              # employee + employer
    assert by_type["SI_REMITTANCE"].due_on == date(2026, 7, 31)
    rt = by_type["RESIDENT_TAX_REMITTANCE"]
    assert (rt.amount, rt.municipality_code, rt.due_on) == (D(10000), "131016", None)   # rule not signed
    assert filing.record_run_obligations(db, run, actor_id=1) == []                   # written once

    wht = by_type["WHT_REMITTANCE"]
    with pytest.raises(BadRequestException, match="four-eyes"):
        filing.approve_obligation(db, organization.id, wht.id, 1)
    filing.approve_obligation(db, organization.id, wht.id, 2)
    filing.submit_obligation(db, organization.id, wht.id, "bank transfer")
    with pytest.raises(BadRequestException, match="receipt reference"):
        filing.record_obligation_receipt(db, organization.id, wht.id, accepted=True, receipt_ref="")
    assert filing.record_obligation_receipt(db, organization.id, wht.id, accepted=True,
                                            receipt_ref="RCPT-1")["status"] == "ACCEPTED"


def test_small_employer_twice_yearly_scheme_is_refused(db, organization):
    db.add(PayrollJpEmployerRegistration(
        organization_id=organization.id, effective_from=date(2026, 1, 1), health_insurer_type="KYOKAI_KENPO",
        health_insurer_prefecture="13",
        ei_industry_class="GENERAL", withholding_payer_status="SMALL_EMPLOYER_SPECIAL", status="ACTIVE"))
    run = _run(db, organization, date(2026, 6, 25), status="Review")
    db.commit()
    with pytest.raises(HTTPException, match="twice-yearly"):
        filing.refuse_uncertified_remittance_scheme(db, run)


# ── journal ─────────────────────────────────────────────────────────────────
ACCOUNTS = {k: f"ACC-{i}" for i, k in enumerate(journal.ACCOUNT_KEYS)}


def test_journal_needs_the_account_map_and_balances(db, organization, employee):
    run = _run(db, organization, date(2026, 6, 25))
    _payslip(db, organization, employee, run)
    assert journal.build_jp_journal(db, organization.id, run.id)["status"] == "BLOCKED"
    out = journal.build_jp_journal(db, organization.id, run.id, ACCOUNTS)
    assert out["status"] == "READY" and out["debit"] == out["credit"]
    memos = {line["memo"] for line in out["lines"]}
    assert "Resident tax payable — 131016" in memos


# ── year-end adjustment: the calculation ────────────────────────────────────
FACTS = {"annualIncome": "3600000", "taxWithheld": "60000", "socialInsuranceWithheld": "527400",
         "residency": "RESIDENT", "declarationClass": "PRIMARY"}


def _pack(rate_map=None):
    return japan._Pack(rate_map or _yea_rate_map(), 7)


def test_year_end_tax_on_synthetic_tables():
    # 3,600,000 - 30% = 2,520,000; minus SI 527,400 and basic 480,000 = 1,512,600
    # -> 1,512,000; 10% = 151,200; +2% = 154,224 -> 154,200; 60,000 - 154,200.
    got = year_end.year_end_tax(FACTS, {}, _yea_rows(), _pack())
    assert got.employment_income == D(2520000)
    assert got.taxable == D(1512000)
    assert got.annual_tax == D(154200)
    assert got.difference == D(-94200)


def test_declarations_reduce_the_tax():
    declarations = {"DEPENDANTS": {"categories": {"GENERAL": 1}},
                    "INSURANCE_PREMIUMS": {"life": "40000", "earthquake": "80000"},
                    "HOUSING_LOAN": {"credit": "10000"}}
    got = year_end.year_end_tax(FACTS, declarations, _yea_rows(), _pack())
    assert got.deductions["dependants"] == D(380000)
    assert got.deductions["lifeInsurance"] == D(20000)            # 50% (synthetic)
    assert got.deductions["earthquakeInsurance"] == D(50000)      # capped
    # taxable 1,512,600 - 450,000 = 1,062,600 -> 1,062,000; 106,200 - 10,000 = 96,200; +2% -> 98,124 -> 98,100
    assert got.annual_tax == D(98100)


@pytest.mark.parametrize("facts,reason", [
    ({**FACTS, "residency": "NON_RESIDENT"}, "NON_RESIDENT"),
    ({**FACTS, "declarationClass": "SECONDARY"}, "SECONDARY_COLUMN"),
    ({**FACTS, "annualIncome": "20000001"}, "INCOME_ABOVE_LIMIT"),
])
def test_excluded_employees(facts, reason):
    assert year_end.yea_eligibility(facts, _pack()) == reason


def test_shipped_content_blocks_the_year_end_calculation():
    with pytest.raises(MissingComplianceConfigurationError) as exc:
        year_end.year_end_tax(FACTS, {}, [], japan._Pack(_base_rate_map(), 7))
    assert exc.value.key == "JP_YEA_EID"
    with pytest.raises(MissingComplianceConfigurationError):
        year_end.yea_eligibility(FACTS, japan._Pack(_base_rate_map(), 7))       # limit is empty


def test_unknown_declaration_fields_block():
    with pytest.raises(MissingComplianceConfigurationError):
        year_end.year_end_tax(FACTS, {"HOUSING_LOAN": {"refund": "1"}}, _yea_rows(), _pack())


# ── year-end adjustment: the workflow ───────────────────────────────────────
def _paid_months(db, organization, employee, months=(1, 2), ctx=None):
    for month in months:
        _payslip(db, organization, employee, _run(db, organization, date(2026, month, 25)), ctx)


def test_year_end_workflow_end_to_end(db, organization, employee):
    _paid_months(db, organization, employee)
    record = yea.record_declaration(db, organization.id, employee.id, {
        "tax_year": 2026, "declaration_type": "DEPENDANTS", "payload": {"categories": {"GENERAL": 1}}}, 1)
    db.commit()
    with pytest.raises(BadRequestException, match="four-eyes"):
        yea.approve_declaration(db, organization.id, record.id, 1)
    yea.approve_declaration(db, organization.id, record.id, 2)
    case = yea.open_case(db, organization.id, employee.id, 2026, 1)
    db.commit()
    with pytest.raises(BadRequestException, match="already exists"):
        yea.open_case(db, organization.id, employee.id, 2026, 1)

    yea.calculate_case(db, organization.id, case.id, actor_id=1)
    db.commit()                    # as the route does; a refused review rolls back
    # Two months: pay 600,000, withheld 10,000; deductions exceed income -> tax 0, refund 10,000.
    assert case.state == "CALCULATED"
    assert (case.annual_income, case.tax_withheld, case.annual_tax, case.difference) == \
        (D(600000), D(10000), D(0), D(10000))
    with pytest.raises(BadRequestException, match="four-eyes"):
        yea.review_case(db, organization.id, case.id, 1)
    yea.review_case(db, organization.id, case.id, 2)
    db.commit()

    december = _run(db, organization, date(2026, 12, 25), status="Draft")
    october = _run(db, organization, date(2026, 10, 25), status="Draft")
    db.commit()
    with pytest.raises(BadRequestException, match="no earlier than month 11"):
        yea.apply_case(db, organization.id, case.id, october.id, 1)
    yea.apply_case(db, organization.id, case.id, december.id, 1)
    assert case.state == "APPLIED"
    inputs = jp._jp_year_end_inputs(db, organization.id, employee.id, december)
    assert inputs == {"jp_year_end_difference": D(10000), "jp_yea_case_id": case.id}

    _payslip(db, organization, employee, december)            # calculated before applying: no case on it
    with pytest.raises(HTTPException, match="recalculate"):
        yea.require_cases_reflected(db, december)
    yea.lock_cases_for_run(db, december)
    assert case.state == "LOCKED"
    with pytest.raises(BadRequestException, match="LOCKED"):
        yea.void_case(db, organization.id, case.id, 1)

    cert = filing.withholding_certificate(db, organization.id, case.id)
    assert cert["withheld"] == "10000" and cert["exportRefusal"]
    assert not any("my_number" in key.lower() or "mynumber" in key.lower() for key in cert)


def test_year_end_blocks_on_shipped_content_and_unsigned_month(db, organization, employee):
    _paid_months(db, organization, employee, ctx=_context())        # the content as shipped
    case = yea.open_case(db, organization.id, employee.id, 2026, 1)
    with pytest.raises(BadRequestException, match="blocked"):
        yea.calculate_case(db, organization.id, case.id, 1)


def test_year_end_needs_committed_payslips(db, organization, employee):
    case = yea.open_case(db, organization.id, employee.id, 2026, 1)
    with pytest.raises(BadRequestException, match="No committed Japan payslip"):
        yea.calculate_case(db, organization.id, case.id, 1)


def test_declaration_validation(db, organization, employee):
    for payload, match in [
        ({"tax_year": 2026, "declaration_type": "LOTTERY", "payload": {"amount": 1}}, "declaration_type"),
        ({"tax_year": 2026, "declaration_type": "HOUSING_LOAN", "payload": {"refund": 1}}, "accepts only"),
        ({"tax_year": 2026, "declaration_type": "HOUSING_LOAN", "payload": {"credit": -1}}, "non-negative"),
    ]:
        with pytest.raises(BadRequestException, match=match):
            yea.record_declaration(db, organization.id, employee.id, payload, 1)


# ── filing previews ─────────────────────────────────────────────────────────
def test_every_submission_file_is_refused_until_g5():
    for document in filing.DOCUMENTS:
        assert "no certified export schema" in filing.export_refusal(document)


def test_bonus_report_preview_lists_the_bonus_events(db, organization, employee):
    from app.modules.payroll.models import PayrollJpSocialInsuranceEvent

    db.add(PayrollJpSocialInsuranceEvent(
        organization_id=organization.id, employee_id=employee.id, event_type="BONUS",
        effective_from=date(2026, 7, 10), bonus_paid_on=date(2026, 7, 10), sba_amount=D(500000),
        report_due_on=date(2026, 7, 15), submission_status="CREATED", created_by_id=1))
    db.commit()
    preview = filing.bonus_payment_report(db, organization.id, "2026-07-10")
    assert preview["reportDueOn"] == "2026-07-15" and preview["employees"][0]["sbaAmount"] == "500000"
