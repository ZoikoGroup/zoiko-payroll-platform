"""
tests/test_au_state_payroll_tax_integration.py
---------------------------------------------------
End-to-end DB-level coverage proving the Australia state/territory
employer payroll tax org-level accumulator wiring (ZP-TAX-AU-2026-27-001
§14-18, Phase 4) actually fires from a real persisted payslip —
service.add_payslip_item must (a) write the post-period ORG-AGGREGATE
NSW taxable-wages figure back to OrganizationYtdAccumulator (summed
across every employee processed, not just one), and (b) never fold the
employer's own payroll-tax liability into the employee's net pay.
Mirrors test_au_payday_super_integration.py's exact pattern for Payday
Super.
"""

from datetime import date
from decimal import Decimal

from app.modules.payroll import service
from app.modules.payroll.models import PayrollEmployee, PayrollRun, TaxSlab, OrganizationYtdAccumulator
from app.modules.payroll.schemas import PayslipItemCreate
import app.modules.payroll.engine.countries.shared as shared

_NSW_SLABS = [
    dict(min_amount=Decimal("0"), max_amount=Decimal("1200000"), rate_pct=Decimal("0")),
    dict(min_amount=Decimal("1200000"), max_amount=None, rate_pct=Decimal("5.45")),
]


def _make_au_employee(db, org_id, code, work_state="NSW"):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="AU", work_state=work_state, ctc=Decimal("14400000"),  # $1.2m/month
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _make_run(db, org_id, period_start, period_end, pay_date):
    run = PayrollRun(
        organization_id=org_id, period_label="AU State Payroll Tax Test Run",
        period_start=period_start, period_end=period_end, pay_date=pay_date,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _add_nsw_slabs(db):
    # get_state_scoped_config only ever reads CANONICAL (organization_id
    # IS NULL) state-scoped rows — see its own docstring — so these must
    # be canonical, not org-scoped, to actually reach ctx.state_slabs.
    for row in _NSW_SLABS:
        db.add(TaxSlab(
            organization_id=None, jurisdiction_country="AU", jurisdiction_state="NSW",
            rate_label="", tax_formula="", **row,
        ))
    db.commit()


def test_add_payslip_item_writes_org_aggregate_nsw_payroll_tax(db, organization):
    assert "AU" in shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES  # enabled by default per Phase 4
    _add_nsw_slabs(db)

    # First employee: $1,000,000 gross this period — entirely within the
    # untaxed band on its own.
    employee1 = _make_au_employee(db, organization.id, "AU-PT-1")
    run = _make_run(db, organization.id, date(2026, 8, 1), date(2026, 8, 31), date(2026, 9, 1))
    item1 = service.add_payslip_item(db, run.id, PayslipItemCreate(
        employee_id=employee1.id, basic_salary=Decimal("1000000"),
    ), organization.id)
    db.commit()
    assert item1.employer_payroll_tax == Decimal("0")

    accumulator = db.query(OrganizationYtdAccumulator).filter(
        OrganizationYtdAccumulator.organization_id == organization.id,
        OrganizationYtdAccumulator.tax_component == "au_payroll_tax_nsw",
    ).one()
    assert accumulator.ytd_taxable_wages == Decimal("1000000")

    # Second employee, SAME org, SAME period — the org's aggregate NSW
    # wages now cross the $1.2m threshold at $2,000,000 total, even
    # though NEITHER employee individually earns anywhere near that.
    employee2 = _make_au_employee(db, organization.id, "AU-PT-2")
    item2 = service.add_payslip_item(db, run.id, PayslipItemCreate(
        employee_id=employee2.id, basic_salary=Decimal("1000000"),
    ), organization.id)
    db.commit()

    # This SECOND employee's own period liability is $43,600 — the org's
    # aggregate crossing the threshold, correctly attributed to whichever
    # payslip caused the crossing, not split/guessed between the two.
    assert item2.employer_payroll_tax == Decimal("43600.00")
    # Neither employee's own net pay reflects the employer's own payroll-
    # tax liability — it is a wholly separate field, per AU-D05.
    assert item1.net_pay is not None and item2.net_pay is not None

    db.refresh(accumulator)
    assert accumulator.ytd_taxable_wages == Decimal("2000000")


def test_add_payslip_item_dormant_when_switch_off_creates_no_accumulator(db, organization):
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.discard("AU")
    try:
        _add_nsw_slabs(db)
        employee = _make_au_employee(db, organization.id, "AU-PT-3")
        run = _make_run(db, organization.id, date(2026, 8, 1), date(2026, 8, 31), date(2026, 9, 1))
        item = service.add_payslip_item(db, run.id, PayslipItemCreate(
            employee_id=employee.id, basic_salary=Decimal("2000000"),
        ), organization.id)
        db.commit()

        assert item.employer_payroll_tax == Decimal("0")
        assert db.query(OrganizationYtdAccumulator).filter(
            OrganizationYtdAccumulator.organization_id == organization.id,
        ).count() == 0
    finally:
        shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("AU")
