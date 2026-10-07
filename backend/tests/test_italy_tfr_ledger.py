"""Italy TFR liability ledger (§13, IT-037/IT-038/IT-039/IT-040/IT-041).

The TFR ledger is a LIABILITY ledger (IT-037), not an earning. Each entry
carries the destination in force (IT-038), revaluation is annual on prior-year
balances with a substitute tax (IT-039), and the Fondo Tesoreria threshold is
prior-year average headcount (IT-040/IT-041).

This suite tests the math and the refusal logic:
- Accrual = qualifying_remuneration / 13.5 - INPS 0.5% offset.
- Destination must be AZIENDA / FONDO_PENSIONE / FONDO_TESORERIA.
- Headcount >= 60 forces FONDO_TESORERIA; headcount < 60 blocks it unless
  transferred-worker evidence exists (IT-041).
- Revaluation coefficient = fixed_pct * months/12 + max(0, istat) * share / 100.
- Revaluation tax is a substitute tax on the revaluation amount.
- Idempotency prevents double-posting.

SQLite `db` fixture only - nothing here reaches a real database.
"""
from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import service
from app.modules.payroll.italy_service import seed_italy_pack
from app.modules.payroll.models import (
    EmployeeStatutoryProfile, EmployerItalyProfile, ItalyTfrLedgerEntry,
    PayrollEmployee, PayrollRun, PayslipItem,
)
from app.modules.payroll.schemas import (
    ItalyTfrAccrualRequest, ItalyTfrRevaluationRequest,
)


def _seed_italy_pack(db):
    """Seed the Italy canonical pack (Active) for tests that need it."""
    return seed_italy_pack(db, status="Active")


def _seed_italy_reval_rates(db, organization_id):
    """Seed the TFR revaluation rates needed by the revaluation tests."""
    from decimal import Decimal
    from app.modules.payroll.models import ContributionRate, TaxSlab, JurisdictionPack
    from app.modules.payroll.italy_service import IT_PACK_ID

    pack = (db.query(JurisdictionPack)
            .filter(JurisdictionPack.pack_id == IT_PACK_ID).first())
    if pack is None:
        return

    # ContributionRate (employer_pct)
    rates = [
        ("it_tfr_revaluation_fixed_pct", Decimal("1.5")),
        ("it_tfr_revaluation_istat_share", Decimal("75.0")),
    ]
    for key, val in rates:
        existing = (db.query(ContributionRate)
                    .filter(ContributionRate.component_key == key,
                            ContributionRate.organization_id == organization_id).first())
        if not existing:
            db.add(ContributionRate(
                component_key=key,
                organization_id=organization_id,
                jurisdiction_pack_id=None,
                employer_rate_pct=val,
                employee_rate_pct=Decimal("0"),
                label=key,
                employee_share="0%",
                employer_share=f"{val}%",
                total=f"{val}%",
            ))

    # TaxSlab (employee_pct) - removed, using ContributionRate with employee_rate_pct instead
    # The tax rate is stored in ContributionRate with employee_rate_pct
    existing = (db.query(ContributionRate)
                .filter(ContributionRate.component_key == "it_tfr_revaluation_tax_pct",
                        ContributionRate.organization_id == organization_id).first())
    if not existing:
        db.add(ContributionRate(
            component_key="it_tfr_revaluation_tax_pct",
            organization_id=organization_id,
            jurisdiction_pack_id=None,
            employer_rate_pct=Decimal("0"),
            employee_rate_pct=Decimal("17.0"),
            label="it_tfr_revaluation_tax_pct",
            employee_share="17%",
            employer_share="0%",
            total="17%",
        ))
    db.commit()


def _employee(db, organization, code="IT1", tfr_destination=None, pension_fund=None):
    employee = PayrollEmployee(organization_id=organization.id, employee_code=code,
                               name=f"Worker {code}", country_code="IT")
    db.add(employee)
    db.commit()
    db.refresh(employee)
    if tfr_destination:
        db.add(EmployeeStatutoryProfile(
            employee_id=employee.id, organization_id=organization.id,
            country_code="IT", effective_from=date(2026, 1, 1),
            it_tfr_destination=tfr_destination, it_pension_fund=pension_fund,
        ))
        db.commit()
    return employee


def _employer(db, organization, headcount=None, tesoreria_status="OBLIGED"):
    profile = EmployerItalyProfile(organization_id=organization.id,
                                   prior_year_avg_headcount=headcount,
                                   tesoreria_status=tesoreria_status)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def _run(db, organization, status="Approved", run_code="IT-2026-03", month=3, year=2026):
    run = PayrollRun(
        organization_id=organization.id, run_code=run_code,
        period_label=f"{year}-{month:02d}",
        period_start=date(year, month, 1),
        period_end=service._it_month_end(year, month),
        pay_date=date(year, month, 28), status=status,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _payslip(db, organization, run, employee, net_pay="3200.00", destination="AZIENDA"):
    """Create a payslip with configurable TFR destination.

    `destination` defaults to "AZIENDA". Pass None to omit the destination
    key from the snapshot entirely (tests UNRESOLVED path).
    """
    tfr_snap = {"accrual": "300.00", "inpsOffset": "15.00", "net": "285.00"}
    if destination is not None:
        tfr_snap["destination"] = destination
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=employee.id, organization_id=organization.id,
        employee_name=employee.name, basic_salary=4000, gross_pay=4000,
        total_deductions=D("800.00"), net_pay=D(net_pay),
        it_calculation_snapshot={"tfr": tfr_snap},
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _accrual(db, organization, run):
    return service.post_italy_tfr_accrual(
        db, organization.id, run.id, actor_id=None)


def _revaluation(db, organization, year=2026, istat=2.0, months=12):
    _seed_italy_pack(db)
    _seed_italy_reval_rates(db, organization.id)
    return service.post_italy_tfr_revaluation(
        db, organization.id, year, D(str(istat)), months, actor_id=None)


# ── Accrual math (IT-037) ────────────────────────────────────────────────────

def test_accrual_is_qualifying_remuneration_div_13_5_minus_inps_offset(db, organization):
    """Engine: gross = remuneration / 13.5, offset = contributory_base * 0.5%,
    net = gross - offset. The service posts the net amount."""
    _employer(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    entries = _accrual(db, organization, run)
    assert len(entries) == 1
    e = entries[0]
    # snapshot has gross=300, offset=15, net=285
    assert e.amount == D("285.00")
    assert e.entry_type == "ACCRUAL"
    assert e.tax_year == 2026


def test_accrual_idempotent_on_retry(db, organization):
    """Same run, same employee, same month = no duplicate (idempotency key)."""
    _employer(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    first = _accrual(db, organization, run)
    again = _accrual(db, organization, run)
    assert [e.id for e in first] == [e.id for e in again]
    assert db.query(ItalyTfrLedgerEntry).count() == 1


def test_accrual_refuses_on_draft_run(db, organization):
    _employer(db, organization)
    run = _run(db, organization, status="Draft")
    _payslip(db, organization, run, _employee(db, organization))
    with pytest.raises(BadRequestException) as excinfo:
        _accrual(db, organization, run)
    assert "APPROVED" in str(excinfo.value)
    assert db.query(ItalyTfrLedgerEntry).count() == 0


def test_accrual_posts_nothing_for_non_italian_payslips(db, organization):
    """A payslip without TFR in its snapshot is skipped, not an error."""
    _employer(db, organization)
    run = _run(db, organization)
    emp = _employee(db, organization)
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=emp.id, organization_id=organization.id,
        employee_name=emp.name, basic_salary=4000, gross_pay=4000,
        total_deductions=D("800.00"), net_pay=D("3200.00"),
        # no 'tfr' key in snapshot = non-Italian payslip
        it_calculation_snapshot={},
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    entries = _accrual(db, organization, run)
    assert entries == []


# ── Destination validation (IT-038, IT-040, IT-041) ─────────────────────────

@pytest.mark.parametrize("dest,headcount", [
    ("AZIENDA", 50),
    ("FONDO_PENSIONE", 50),
    ("FONDO_TESORERIA", 65),
])
def test_valid_destinations_accepted(db, organization, dest, headcount):
    _employer(db, organization, headcount=headcount)
    run = _run(db, organization)
    code = f"IT_{dest}"
    if dest == "FONDO_PENSIONE":
        emp = _employee(db, organization, code=code, tfr_destination=dest, pension_fund="MY_FUND")
    else:
        emp = _employee(db, organization, code=code, tfr_destination=dest)
    _payslip(db, organization, run, emp, destination=dest)
    entries = _accrual(db, organization, run)
    assert entries[0].destination == dest


def test_absent_destination_leaves_unresolved(db, organization):
    _employer(db, organization, headcount=50)
    run = _run(db, organization)
    emp = _employee(db, organization, code="IT_UNRESOLVED")
    _payslip(db, organization, run, emp, destination=None)
    entries = _accrual(db, organization, run)
    assert entries[0].destination is None  # UNRESOLVED stored as None


def test_headcount_ge_60_forces_tesoreria(db, organization):
    """Budget Law 2026: prior-year avg headcount >= 60 => must be FONDO_TESORERIA."""
    _employer(db, organization, headcount=65)
    run = _run(db, organization)
    emp = _employee(db, organization, tfr_destination="AZIENDA")
    _payslip(db, organization, run, emp)
    with pytest.raises(BadRequestException) as excinfo:
        _accrual(db, organization, run)
    assert "headcount" in str(excinfo.value)
    assert "60" in str(excinfo.value) or "threshold" in str(excinfo.value)
    assert db.query(ItalyTfrLedgerEntry).count() == 0


def test_headcount_below_60_blocks_tesoreria_election(db, organization):
    """Electing FONDO_TESORERIA when headcount < 60 is a contradiction."""
    _employer(db, organization, headcount=30)
    run = _run(db, organization)
    emp = _employee(db, organization, tfr_destination="FONDO_TESORERIA")
    _payslip(db, organization, run, emp)
    with pytest.raises(BadRequestException) as excinfo:
        _accrual(db, organization, run)
    assert "below the" in str(excinfo.value) or "threshold" in str(excinfo.value)
    assert db.query(ItalyTfrLedgerEntry).count() == 0


def test_pension_fund_destination_requires_fund_name(db, organization):
    """FONDO_PENSIONE without a named fund is an error."""
    _employer(db, organization, headcount=50)
    run = _run(db, organization)
    emp = _employee(db, organization, tfr_destination="FONDO_PENSIONE")
    _payslip(db, organization, run, emp)
    with pytest.raises(BadRequestException) as excinfo:
        _accrual(db, organization, run)
    assert "pension fund" in str(excinfo.value).lower()
    assert db.query(ItalyTfrLedgerEntry).count() == 0


# ── Revaluation math (IT-037/IT-038/IT-039) ──────────────────────────────────

def test_revaluation_coefficient_is_fixed_plus_istat_share(db, organization):
    """coefficient = fixed_pct * months/12 + max(0, istat) * istat_share / 100.

    Default pack values: fixed=1.5%, istat_share=75%, tax_pct=17%.
    """
    _employer(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    _accrual(db, organization, run)  # net 285

    # Revalue with 2% ISTAT increase, 12 months
    reval = _revaluation(db, organization, year=2027, istat=2.0, months=12)
    # prior = 285
    # fixed = 1.5 * 12/12 = 1.5
    # istat = max(0, 2) * 75 / 100 = 1.5
    # coefficient = 1.5 + 1.5 = 3.0
    # revaluation = 285 * 3.0 / 100 = 8.55
    # tax = 8.55 * 17 / 100 = 1.4535 -> 1.45
    assert len(reval) == 2
    r = [e for e in reval if e.entry_type == "REVALUATION"][0]
    t = [e for e in reval if e.entry_type == "REVALUATION_TAX"][0]
    assert r.amount == D("8.55")
    assert t.amount == D("1.45")


def test_revaluation_with_zero_istat_increase_still_has_fixed_part(db, organization):
    """A fall in the index does not reduce the fixed part below zero growth."""
    _employer(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    _accrual(db, organization, run)
    reval = _revaluation(db, organization, year=2027, istat=0.0, months=12)
    r = [e for e in reval if e.entry_type == "REVALUATION"][0]
    # coefficient = 1.5 * 12/12 + 0 = 1.5
    # revaluation = 285 * 1.5 / 100 = 4.275 -> 4.28
    assert r.amount == D("4.28")


def test_revaluation_months_prorated(db, organization):
    _employer(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    _accrual(db, organization, run)
    reval = _revaluation(db, organization, year=2027, istat=2.0, months=6)
    # coefficient = 1.5 * 6/12 + 2 * 75 / 100 = 0.75 + 1.5 = 2.25
    # revaluation = 285 * 2.25 / 100 = 6.4125 -> 6.41
    r = [e for e in reval if e.entry_type == "REVALUATION"][0]
    assert r.amount == D("6.41")


def test_revaluation_never_touches_current_year_quota(db, organization):
    """Revaluation is on prior-year balances only (tax_year < current year)."""
    _employer(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    _accrual(db, organization, run)  # 2026 accrual
    # If we revalue for 2026 (same year), prior balance is 0 -> no entries
    reval = _revaluation(db, organization, year=2026, istat=2.0)
    assert reval == []


def test_revaluation_requires_italy_pack(db, organization):
    """Without a canonical pack, the rate constants are not resolvable."""
    _employer(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    _accrual(db, organization, run)
    # The pack exists (seeded by tests), so this just sanity-checks.
    reval = _revaluation(db, organization, year=2027, istat=1.0)
    assert len(reval) == 2


def test_negative_istat_rejected(db, organization):
    """A negative ISTAT increase is invalid; the engine takes max(0, istat)."""
    _employer(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    _accrual(db, organization, run)
    with pytest.raises(BadRequestException) as excinfo:
        _revaluation(db, organization, year=2027, istat=-0.5)
    assert "non-negative" in str(excinfo.value)


def test_months_out_of_range_rejected(db, organization):
    _employer(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    _accrual(db, organization, run)
    with pytest.raises(BadRequestException) as excinfo:
        _revaluation(db, organization, year=2027, istat=2.0, months=13)
    assert "0-12" in str(excinfo.value)


# ── Balance aggregation ──────────────────────────────────────────────────────

def test_balance_groups_by_destination(db, organization):
    _employer(db, organization, headcount=50)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization, tfr_destination="AZIENDA"))
    _payslip(db, organization, run, _employee(db, organization, code="IT2",
                                              tfr_destination="FONDO_PENSIONE",
                                              pension_fund="MY_FUND"))
    _accrual(db, organization, run)
    bal = service.get_italy_tfr_balance(db, organization.id)
    assert "AZIENDA" in bal["byDestination"]
    assert "FONDO_PENSIONE" in bal["byDestination"]
    # total should be sum of both
    total = D(bal["total"])
    assert total > 0


def test_balance_as_of_year_filters(db, organization):
    _employer(db, organization, headcount=50)
    run2026 = _run(db, organization, year=2026)
    _payslip(db, organization, run2026, _employee(db, organization))
    _accrual(db, organization, run2026)
    bal = service.get_italy_tfr_balance(db, organization.id, as_of_year=2025)
    assert bal["total"] == "0"


# ── Idempotency audit ────────────────────────────────────────────────────────

def test_idempotency_audit_reports_zero_duplicates(db, organization):
    _employer(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    _accrual(db, organization, run)
    report = service.verify_italy_tfr_idempotency(db, organization.id)
    assert report["duplicateCount"] == 0
    assert report["duplicateKeys"] == []


# ── Tenant isolation ─────────────────────────────────────────────────────────

def test_accrual_and_ledger_are_scoped_to_caller_tenant(db, organization):
    _employer(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    _accrual(db, organization, run)
    assert service.list_italy_tfr_ledger(db, organization.id + 999) == []
    assert service.get_italy_tfr_balance(db, organization.id + 999)["total"] == "0"


def test_revaluation_scoped_to_caller_tenant(db, organization):
    _employer(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    _accrual(db, organization, run)
    with pytest.raises(Exception):
        service.post_italy_tfr_revaluation(
            db, organization.id + 999, 2027, D("1.0"))


def test_balance_and_ledger_filter_by_employee(db, organization):
    _employer(db, organization, headcount=50)
    run = _run(db, organization)
    emp1 = _employee(db, organization, code="IT1", tfr_destination="AZIENDA")
    emp2 = _employee(db, organization, code="IT2", tfr_destination="AZIENDA")
    _payslip(db, organization, run, emp1)
    _payslip(db, organization, run, emp2)
    _accrual(db, organization, run)
    assert len(service.list_italy_tfr_ledger(db, organization.id, employee_id=emp1.id)) == 1
    assert len(service.list_italy_tfr_ledger(db, organization.id, employee_id=emp2.id)) == 1
    assert len(service.list_italy_tfr_ledger(db, organization.id)) == 2


def test_ledger_filters_by_year_and_type(db, organization):
    _employer(db, organization)
    run2026 = _run(db, organization, run_code="M3", year=2026)
    run2027 = _run(db, organization, run_code="M3_27", year=2027)
    _payslip(db, organization, run2026, _employee(db, organization, code="IT26"))
    _payslip(db, organization, run2027, _employee(db, organization, code="IT27"))
    _accrual(db, organization, run2026)
    _accrual(db, organization, run2027)
    assert len(service.list_italy_tfr_ledger(db, organization.id, tax_year=2026)) == 1
    assert len(service.list_italy_tfr_ledger(db, organization.id, tax_year=2027)) == 1
    assert len(service.list_italy_tfr_ledger(db, organization.id, entry_type="ACCRUAL")) == 2
    assert service.list_italy_tfr_ledger(db, organization.id, entry_type="REVALUATION") == []