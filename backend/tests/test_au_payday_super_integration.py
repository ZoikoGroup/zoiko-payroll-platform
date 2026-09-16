"""
tests/test_au_payday_super_integration.py
---------------------------------------------
End-to-end DB-level coverage proving the Australia Payday Super wiring
(ZP-TAX-AU-2026-27-001 §10, Payday Super Phase 2) actually fires from a
real persisted payslip, not just in isolation — service.add_payslip_item
must both (a) write the post-period SG-qualifying-earnings figure back to
PayrollYtdAccumulator and (b) create exactly one SuperGuaranteeLiability
row per real payslip. Mirrors the "manually add a payslip" path
test_engine_jurisdiction_db_integration.py already covers for other
countries' YTD wiring.
"""

from datetime import date
from decimal import Decimal

from app.modules.payroll import service
from app.modules.payroll.models import (
    PayrollEmployee, PayrollRun, ContributionRate, PayrollYtdAccumulator, SuperGuaranteeLiability, TaxabilityRule,
)
from app.modules.payroll.schemas import PayslipItemCreate
import app.modules.payroll.engine.countries.shared as shared


def _make_au_employee(db, org_id, code="AU-PS-1"):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="AU", ctc=Decimal("120000"),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _make_run(db, org_id, period_start, period_end, pay_date):
    run = PayrollRun(
        organization_id=org_id, period_label="AU Payday Super Test Run",
        period_start=period_start, period_end=period_end, pay_date=pay_date,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def test_add_payslip_item_creates_sg_liability_and_writes_ytd_accumulator(db, organization):
    assert "AU" in shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES  # enabled by default per Phase 2

    db.add(ContributionRate(
        organization_id=organization.id, jurisdiction_country="AU",
        component_key="super", label="Superannuation Guarantee",
        employee_share="0%", employer_share="12%", total="12%",
        employer_rate_pct=Decimal("12.00"),
    ))
    employee = _make_au_employee(db, organization.id)

    # Pre-existing YTD state for this employee's AU financial year — the
    # "before" this payslip must read and build on.
    db.add(PayrollYtdAccumulator(
        employee_id=employee.id, tax_year="AU-FY-2026-27", tax_component="au_sg_qualifying_earnings",
        ytd_taxable_wages=Decimal("50000.00"),
    ))
    db.commit()

    run = _make_run(db, organization.id, date(2026, 8, 1), date(2026, 8, 31), date(2026, 9, 1))
    item = service.add_payslip_item(db, run.id, PayslipItemCreate(
        employee_id=employee.id, basic_salary=Decimal("10000"),
    ), organization.id)
    db.commit()

    # (a) Post-period SG-qualifying-earnings written back — real amount,
    # never a guess: before (50000) + this period's gross (10000) = 60000.
    accumulator = db.query(PayrollYtdAccumulator).filter(
        PayrollYtdAccumulator.employee_id == employee.id,
        PayrollYtdAccumulator.tax_component == "au_sg_qualifying_earnings",
    ).one()
    assert accumulator.ytd_taxable_wages == Decimal("60000.00")
    assert accumulator.last_updated_payslip_id == item.id

    # (b) Exactly one Payday Super liability row created for this payslip.
    liability = db.query(SuperGuaranteeLiability).filter(
        SuperGuaranteeLiability.payslip_item_id == item.id,
    ).one()
    assert liability.employee_id == employee.id
    assert liability.organization_id == organization.id
    assert liability.pay_date == date(2026, 9, 1)
    assert liability.qualifying_earnings == Decimal("10000")
    assert liability.sg_amount == Decimal("1200.00")  # 10000 * 12%
    assert liability.status == "PENDING"
    assert liability.mcb_reached is False
    assert liability.fund_receipt_deadline > liability.pay_date

    # The frozen ytd_snapshot on the payslip itself must agree with the
    # accumulator write — never allowed to silently disagree.
    assert item.ytd_snapshot["sg_qualifying_earnings"]["ytd_before"] == "50000.00"
    assert item.ytd_snapshot["sg_qualifying_earnings"]["ytd_after"] == "60000.00"


def test_add_payslip_item_dormant_when_switch_off_creates_no_liability(db, organization):
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.discard("AU")
    try:
        db.add(ContributionRate(
            organization_id=organization.id, jurisdiction_country="AU",
            component_key="super", label="Superannuation Guarantee",
            employee_share="0%", employer_share="12%", total="12%",
            employer_rate_pct=Decimal("12.00"),
        ))
        employee = _make_au_employee(db, organization.id, code="AU-PS-2")
        db.commit()

        run = _make_run(db, organization.id, date(2026, 8, 1), date(2026, 8, 31), date(2026, 9, 1))
        item = service.add_payslip_item(db, run.id, PayslipItemCreate(
            employee_id=employee.id, basic_salary=Decimal("10000"),
        ), organization.id)
        db.commit()

        # Dormant fallback still computes a real SG amount (current-period
        # annualized estimate) — only the liability/accumulator wiring is
        # gated off.
        assert item.employer_pension > 0
        assert db.query(SuperGuaranteeLiability).filter(SuperGuaranteeLiability.payslip_item_id == item.id).count() == 0
        assert db.query(PayrollYtdAccumulator).filter(PayrollYtdAccumulator.employee_id == employee.id).count() == 0
    finally:
        shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.add("AU")


def test_taxability_rule_excluding_basic_zeroes_sg_liability_end_to_end(db, organization):
    # §11: a real TaxabilityRule row configured through the normal
    # Super Admin CRUD path must actually reach the SG calculation via
    # get_au_taxability_rules_bundle -> build_context_from_employee ->
    # australia.py's _calculate_au_program_wages — not just work in
    # engine-level unit tests with a hand-built rules dict.
    db.add(ContributionRate(
        organization_id=organization.id, jurisdiction_country="AU",
        component_key="super", label="Superannuation Guarantee",
        employee_share="0%", employer_share="12%", total="12%",
        employer_rate_pct=Decimal("12.00"),
    ))
    db.add(TaxabilityRule(
        jurisdiction_country="AU", earning_type="basic", tax_component="sg_qualifying_earnings",
        is_taxable=False, organization_id=None,
    ))
    employee = _make_au_employee(db, organization.id, code="AU-PS-3")
    db.commit()

    run = _make_run(db, organization.id, date(2026, 8, 1), date(2026, 8, 31), date(2026, 9, 1))
    item = service.add_payslip_item(db, run.id, PayslipItemCreate(
        employee_id=employee.id, basic_salary=Decimal("10000"),
    ), organization.id)
    db.commit()

    # basic_salary is the only nonzero component -> SG qualifying wage
    # base is genuinely zero, so no liability is created at all (there is
    # nothing to record) and the accumulator's ytd_after reflects 0 added.
    assert item.employer_pension == Decimal("0")
    liability = db.query(SuperGuaranteeLiability).filter(SuperGuaranteeLiability.payslip_item_id == item.id).first()
    assert liability is not None  # still created (a real $0 payday event, not silently skipped)
    assert liability.qualifying_earnings == Decimal("0")
    assert liability.sg_amount == Decimal("0")
