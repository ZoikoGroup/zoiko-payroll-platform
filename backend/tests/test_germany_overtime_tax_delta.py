"""
tests/test_germany_overtime_tax_delta.py
-----------------------------------------
Phase 8BW — regression coverage for the overtime premium marginal wage-tax/
Soli/Kirchensteuer delta (previously always 0, disclosed as
PARTIAL_WAGE_TAX_PENDING_PAP because computing it correctly was believed to
require the certified BMF PAP). This is no longer true: the internal §32a/
§39b EStG calculator (engine/germany_internal_tax.py, Phase 8BR) already
computes the base payslip's own Lohnsteuer/Soli — this phase reuses THOSE
SAME functions (compute_tax_for_class/compute_soli), never a second engine,
to compute a T2-T1 marginal delta on the EXACT zvE base the payslip's own
germany_calculation_snapshot already recorded.

Each test builds a real PayslipItem whose germany_calculation_snapshot comes
from an ACTUAL germany.calculate() call (same engine, same fake-profile
pattern as test_germany_pap_calculation.py) — never a hand-typed fake
snapshot — so the marginal-delta cross-checks below are checking real
engine output against real engine output, not against each other's
assumptions.
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import service
from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.countries import germany
from app.modules.payroll.engine.germany_internal_tax import compute_soli, compute_tax_for_class, resolve_income_tax_tariff
from app.modules.payroll.hardcoded_defaults import _DE_SOLI_RATE, _DE_SOLI_THRESHOLD
from app.modules.payroll.models import (
    GermanyOvertimePremiumComponent, GermanyOvertimeWorkRecord,
    PayrollEmployee, PayrollRun, PayslipAllowanceItem, PayslipItem,
)
from app.modules.payroll.schemas import GermanyOvertimeWorkRecordCreate


@dataclass
class _FakeCeiling:
    annual_ceiling: Decimal
    id: int = 1


@dataclass
class _FakeHealthFund:
    supplementary_rate_pct: Decimal
    id: int = 1
    health_fund_id: str = "TEST-FUND"


@dataclass
class _FakePvConfig:
    is_saxony: bool
    standard_employee_rate_pct: Decimal = Decimal("2.4000")
    employer_rate_pct: Decimal = Decimal("1.8000")
    saxony_employee_rate_pct: Decimal = Decimal("2.9000")
    saxony_employer_rate_pct: Decimal = Decimal("1.3000")
    id: int = 1


@dataclass
class _FakeProfile:
    id: int = 1
    effective_from: date = date(2026, 1, 1)
    de_tax_class: str = "I"
    de_factor: Decimal = None
    de_child_count: int = 0
    de_childless: bool = True
    de_saxony: bool = False
    de_church_tax_liable: bool = False
    de_church_tax_land: str = None
    de_health_insurance_status: str = "PUBLIC"
    de_health_fund_code: str = "TEST-FUND"
    de_pension_insurance_exempt: bool = False
    de_unemployment_insurance_exempt: bool = False
    de_employment_classification: str = "REGULAR"
    de_zkf_override: Decimal = None
    de_jfreib: Decimal = None
    de_lzzfreib: Decimal = None
    de_jhinzu: Decimal = None
    de_lzzhinzu: Decimal = None
    de_pkpv: Decimal = None
    de_pkpvagz: Decimal = None
    de_main_employment: bool = None


def _ctx(**overrides):
    kwargs = dict(
        gross=Decimal("5000"), basic=Decimal("5000"), country="DE",
        germany_statutory_profile=_FakeProfile(),
        germany_pap_asset=None,
        germany_health_fund=_FakeHealthFund(Decimal("1.7000")),
        germany_ceiling_gkv_pv=_FakeCeiling(Decimal("69750")),
        germany_ceiling_rv_alv=_FakeCeiling(Decimal("101400")),
        germany_pv_configuration=_FakePvConfig(is_saxony=False),
        germany_payroll_date=date(2026, 1, 1),
    )
    kwargs.update(overrides)
    return PayrollContext(**kwargs)


def _make_employee(db, org_id, code="DE-OT-TAX-01"):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="DE", ctc=72000, basic=6000, hra=0, status="Active",
        date_of_joining=date(2026, 1, 1),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _make_run(db, org_id, pay_date=date(2026, 2, 1)):
    run = PayrollRun(
        organization_id=org_id, period_label="Jan 2026", period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31), pay_date=pay_date, status="Draft",
        calculation_mode="standard",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _make_real_payslip_item(db, run, emp, org_id, ctx_overrides=None):
    """Builds a real PayslipItem whose germany_calculation_snapshot/tds/
    soli/church_tax/pf/esi come from an ACTUAL germany.calculate() call —
    the same engine the production payroll-run path uses, not a hand-typed
    fake snapshot."""
    result = germany.calculate(_ctx(**(ctx_overrides or {})))
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=emp.id, organization_id=org_id,
        employee_name=emp.name, country_code="DE",
        gross_pay=Decimal("5000.00"),
        pf=result["employee_pf"], esi=result["employee_esi"],
        tds=result["tds"], soli=result["soli"], church_tax=result["church_tax"],
        total_deductions=result["employee_pf"] + result["employee_esi"] + result["tds"] + result["church_tax"],
        net_pay=(
            Decimal("5000.00") - result["employee_pf"] - result["employee_esi"]
            - result["tds"] - result["church_tax"]
        ),
        germany_calculation_snapshot=result["_germany_calculation_snapshot"],
        status="Pending",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item, result


def _make_work_record(db, emp, org_id, start, end, approval="APPROVED"):
    row = service.create_germany_overtime_work_record(
        db, emp.id, org_id,
        GermanyOvertimeWorkRecordCreate(
            work_date=start.date(), start_datetime=start, end_datetime=end,
            hours=Decimal("2.00"), entry_source="MANUAL",
        ),
        actor_id=1,
    )
    if approval and row.hr_approval_status != approval:
        row = service.set_germany_overtime_work_record_approval(db, row.id, org_id, approval, actor_id=1)
    return row


def _make_component(db, work_record, org_id, gross, taxable, tax_free=Decimal("0.00"), si_contributory=None,
                     combination_status="COMPLETE"):
    component = GermanyOvertimePremiumComponent(
        organization_id=org_id, work_record_id=work_record.id,
        segment_start=work_record.start_datetime, segment_end=work_record.end_datetime,
        work_date_local=work_record.work_date, qualifying_hours=Decimal("2.0000"),
        combination_status=combination_status,
        gross_premium_amount=gross, wage_tax_free_amount=tax_free, wage_taxable_amount=taxable,
        si_exempt_amount=Decimal("0.00"), si_contributory_amount=si_contributory if si_contributory is not None else gross,
    )
    db.add(component)
    db.commit()
    db.refresh(component)
    return component


def _expected_deltas(tax_class, zve_lohnsteuer, zve_surcharges, taxable, church_tax_rate=None):
    """Independent expected-value computation using the SAME public
    functions the production code calls — a cross-check that the wiring
    (which snapshot keys are read, whether the tariff is re-resolved
    correctly) is right, not a re-implementation of the tax law itself."""
    tariff = resolve_income_tax_tariff(date(2026, 1, 1))
    t1 = compute_tax_for_class(zve_lohnsteuer, tax_class, tariff)
    t2 = compute_tax_for_class(zve_lohnsteuer + taxable, tax_class, tariff)
    wage_tax_delta = (t2 - t1).quantize(Decimal("0.01"))

    s1_base = compute_tax_for_class(zve_surcharges, tax_class, tariff)
    s2_base = compute_tax_for_class(zve_surcharges + taxable, tax_class, tariff)
    soli1 = compute_soli(s1_base, is_splitting=(tax_class == "III"), soli_threshold_single=_DE_SOLI_THRESHOLD, soli_rate_pct=_DE_SOLI_RATE)
    soli2 = compute_soli(s2_base, is_splitting=(tax_class == "III"), soli_threshold_single=_DE_SOLI_THRESHOLD, soli_rate_pct=_DE_SOLI_RATE)
    soli_delta = (soli2 - soli1).quantize(Decimal("0.01"))

    church_tax_delta = Decimal("0.00")
    if church_tax_rate is not None:
        church_tax_delta = ((s2_base - s1_base) * church_tax_rate / Decimal("100")).quantize(Decimal("0.01"))
    return wage_tax_delta, soli_delta, church_tax_delta


# ═══════════════════════════════════════════════════════════════════════
# 1. CALCULATED path — real snapshot, real cross-checked marginal deltas
# ═══════════════════════════════════════════════════════════════════════

def test_attach_computes_real_wage_tax_and_soli_deltas_not_church_liable(db, organization):
    """Regular employee, Tax Class I, not church-tax-liable, WITH a real
    taxable overtime premium: wage_tax_delta and soli_delta must be
    genuinely nonzero and match an independent expected-value cross-check;
    church_tax_delta must be a REAL zero (not liable), status CALCULATED."""
    emp = _make_employee(db, organization.id)
    run = _make_run(db, organization.id)
    item, result = _make_real_payslip_item(db, run, emp, organization.id)
    snap = item.germany_calculation_snapshot
    assert snap["calculationStatus"] == "COMPLETE"

    wr = _make_work_record(db, emp, organization.id,
                            datetime(2026, 1, 5, 18, 0, tzinfo=timezone.utc), datetime(2026, 1, 5, 20, 0, tzinfo=timezone.utc))
    component = _make_component(db, wr, organization.id, gross=Decimal("300.00"), taxable=Decimal("300.00"))

    attached = service.attach_germany_overtime_premium_component_to_payslip(
        db, component.id, item.id, organization.id, actor_id=1,
    )
    assert attached.financial_integration_status == "CALCULATED"

    zve_lohnsteuer = Decimal(snap["resolved"]["internal_wage_tax"]["ZVE_LOHNSTEUER"])
    zve_surcharges = Decimal(snap["resolved"]["internal_wage_tax"]["ZVE_SURCHARGES"])
    expected_wage_tax, expected_soli, _ = _expected_deltas("I", zve_lohnsteuer, zve_surcharges, Decimal("300.00"))

    assert attached.applied_wage_tax_delta == expected_wage_tax
    assert attached.applied_wage_tax_delta > Decimal("0.00")
    assert attached.applied_soli_delta == expected_soli
    assert attached.applied_church_tax_delta == Decimal("0.00")

    db.refresh(item)
    assert item.tds == result["tds"] + expected_wage_tax + expected_soli
    assert item.soli == result["soli"] + expected_soli
    assert item.church_tax == result["church_tax"]
    assert item.net_pay == (
        Decimal("5000.00") + Decimal("300.00")
        - item.pf - item.esi - item.tds - item.church_tax
    )


def test_attach_church_tax_liable_employee_computes_kirchensteuer_delta(db, organization):
    """Church-tax-liable employee (Bavaria, 8%) WITH taxable overtime:
    church_tax_delta must be genuinely nonzero and match the independent
    cross-check; status CALCULATED (all three components resolved)."""
    emp = _make_employee(db, organization.id, code="DE-OT-TAX-CT")
    run = _make_run(db, organization.id)
    profile = _FakeProfile(de_church_tax_liable=True, de_church_tax_land="DE-BY")
    item, result = _make_real_payslip_item(db, run, emp, organization.id, ctx_overrides={"germany_statutory_profile": profile})
    snap = item.germany_calculation_snapshot
    assert snap["churchTaxLiableUsed"] is True
    church_tax_rate = Decimal(snap["churchTaxRateUsed"])
    assert church_tax_rate > 0

    wr = _make_work_record(db, emp, organization.id,
                            datetime(2026, 1, 6, 18, 0, tzinfo=timezone.utc), datetime(2026, 1, 6, 20, 0, tzinfo=timezone.utc))
    component = _make_component(db, wr, organization.id, gross=Decimal("300.00"), taxable=Decimal("300.00"))

    attached = service.attach_germany_overtime_premium_component_to_payslip(
        db, component.id, item.id, organization.id, actor_id=1,
    )
    assert attached.financial_integration_status == "CALCULATED"

    zve_lohnsteuer = Decimal(snap["resolved"]["internal_wage_tax"]["ZVE_LOHNSTEUER"])
    zve_surcharges = Decimal(snap["resolved"]["internal_wage_tax"]["ZVE_SURCHARGES"])
    expected_wage_tax, expected_soli, expected_church_tax = _expected_deltas(
        "I", zve_lohnsteuer, zve_surcharges, Decimal("300.00"), church_tax_rate=church_tax_rate,
    )
    assert attached.applied_church_tax_delta == expected_church_tax
    assert attached.applied_church_tax_delta > Decimal("0.00")

    db.refresh(item)
    assert item.church_tax == result["church_tax"] + expected_church_tax


def test_attach_fully_tax_free_overtime_yields_zero_deltas_but_calculated_status(db, organization):
    """A premium entirely §3b tax-free (wage_taxable_amount=0) must yield a
    REAL zero for all three tax deltas, and status CALCULATED (never
    BLOCKED — there's genuinely nothing to compute, not something unknown)."""
    emp = _make_employee(db, organization.id, code="DE-OT-TAX-FREE")
    run = _make_run(db, organization.id)
    item, _result = _make_real_payslip_item(db, run, emp, organization.id)

    wr = _make_work_record(db, emp, organization.id,
                            datetime(2026, 1, 11, 22, 0, tzinfo=timezone.utc), datetime(2026, 1, 12, 2, 0, tzinfo=timezone.utc))
    component = _make_component(
        db, wr, organization.id, gross=Decimal("50.00"), taxable=Decimal("0.00"), tax_free=Decimal("50.00"),
    )

    attached = service.attach_germany_overtime_premium_component_to_payslip(
        db, component.id, item.id, organization.id, actor_id=1,
    )
    assert attached.financial_integration_status == "CALCULATED"
    assert attached.applied_wage_tax_delta == Decimal("0.00")
    assert attached.applied_soli_delta == Decimal("0.00")
    assert attached.applied_church_tax_delta == Decimal("0.00")
    # Gross still increases even though nothing taxable was added.
    assert attached.applied_gross_delta == Decimal("50.00")


# ═══════════════════════════════════════════════════════════════════════
# 2. BLOCKED / PARTIAL paths — never fabricate a tax delta
# ═══════════════════════════════════════════════════════════════════════

def test_attach_with_no_snapshot_is_blocked_not_fabricated(db, organization):
    """A payslip with NO germany_calculation_snapshot at all (e.g. a
    manually-constructed row, or one from a pre-Phase-8BR era) must yield
    BLOCKED with all three tax deltas at a real, unfabricated 0 — gross/SI
    still apply."""
    emp = _make_employee(db, organization.id, code="DE-OT-TAX-NOSNAP")
    run = _make_run(db, organization.id)
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=emp.id, organization_id=organization.id,
        employee_name=emp.name, gross_pay=Decimal("5000.00"), total_deductions=Decimal("0.00"),
        net_pay=Decimal("5000.00"), pf=Decimal("0.00"), esi=Decimal("0.00"),
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    wr = _make_work_record(db, emp, organization.id,
                            datetime(2026, 1, 7, 18, 0, tzinfo=timezone.utc), datetime(2026, 1, 7, 20, 0, tzinfo=timezone.utc))
    component = _make_component(db, wr, organization.id, gross=Decimal("200.00"), taxable=Decimal("200.00"))

    attached = service.attach_germany_overtime_premium_component_to_payslip(
        db, component.id, item.id, organization.id, actor_id=1,
    )
    assert attached.financial_integration_status == "BLOCKED"
    assert attached.applied_wage_tax_delta == Decimal("0.00")
    assert attached.applied_soli_delta == Decimal("0.00")
    assert attached.applied_church_tax_delta == Decimal("0.00")
    assert attached.applied_gross_delta == Decimal("200.00")
    db.refresh(item)
    assert "OVERTIME_WAGE_TAX_BLOCKED" in (item.notes or "")


def test_attach_church_tax_unavailable_base_is_partial_not_fabricated(db, organization):
    """The base payslip itself is Phase 8BU PARTIAL — church-tax-liable but
    Land unresolved. Wage tax/Soli on the overtime premium ARE genuinely
    computable (pap_result IS present); only the Kirchensteuer delta stays
    an explicitly-flagged, unfabricated 0 — status PARTIAL, never BLOCKED
    (that would incorrectly discard the real wage-tax/Soli deltas too)."""
    emp = _make_employee(db, organization.id, code="DE-OT-TAX-PARTIAL")
    run = _make_run(db, organization.id)
    profile = _FakeProfile(de_church_tax_liable=True, de_church_tax_land=None)
    item, _result = _make_real_payslip_item(db, run, emp, organization.id, ctx_overrides={"germany_statutory_profile": profile})
    snap = item.germany_calculation_snapshot
    assert snap["calculationStatus"] == "PARTIALLY_CALCULATED"
    assert snap["unavailableComponents"] == ["church_tax"]

    wr = _make_work_record(db, emp, organization.id,
                            datetime(2026, 1, 8, 18, 0, tzinfo=timezone.utc), datetime(2026, 1, 8, 20, 0, tzinfo=timezone.utc))
    component = _make_component(db, wr, organization.id, gross=Decimal("300.00"), taxable=Decimal("300.00"))

    attached = service.attach_germany_overtime_premium_component_to_payslip(
        db, component.id, item.id, organization.id, actor_id=1,
    )
    assert attached.financial_integration_status == "PARTIAL"
    assert attached.applied_wage_tax_delta > Decimal("0.00")
    assert attached.applied_soli_delta >= Decimal("0.00")
    assert attached.applied_church_tax_delta == Decimal("0.00")
    db.refresh(item)
    assert "OVERTIME_CHURCH_TAX_PENDING" in (item.notes or "")


# ═══════════════════════════════════════════════════════════════════════
# 3. Multiple components, detach reversal, recalculation, idempotency
# ═══════════════════════════════════════════════════════════════════════

def test_multiple_overtime_components_sum_tax_deltas_correctly(db, organization):
    """Two attached components' wage_tax/soli/church_tax deltas must SUM
    onto the payslip, each computed against the SAME original zvE base
    (not compounding against each other's already-applied delta) — matching
    how a real one-off SONSTB payment's marginal tax is computed once per
    component, then simply summed."""
    emp = _make_employee(db, organization.id, code="DE-OT-TAX-MULTI")
    run = _make_run(db, organization.id)
    item, result = _make_real_payslip_item(db, run, emp, organization.id)
    snap = item.germany_calculation_snapshot
    zve_lohnsteuer = Decimal(snap["resolved"]["internal_wage_tax"]["ZVE_LOHNSTEUER"])
    zve_surcharges = Decimal(snap["resolved"]["internal_wage_tax"]["ZVE_SURCHARGES"])

    wr1 = _make_work_record(db, emp, organization.id,
                             datetime(2026, 1, 9, 18, 0, tzinfo=timezone.utc), datetime(2026, 1, 9, 20, 0, tzinfo=timezone.utc))
    wr2 = _make_work_record(db, emp, organization.id,
                             datetime(2026, 1, 10, 18, 0, tzinfo=timezone.utc), datetime(2026, 1, 10, 20, 0, tzinfo=timezone.utc))
    c1 = _make_component(db, wr1, organization.id, gross=Decimal("100.00"), taxable=Decimal("100.00"))
    c2 = _make_component(db, wr2, organization.id, gross=Decimal("150.00"), taxable=Decimal("150.00"))

    a1 = service.attach_germany_overtime_premium_component_to_payslip(db, c1.id, item.id, organization.id, actor_id=1)
    db.refresh(item)
    a2 = service.attach_germany_overtime_premium_component_to_payslip(db, c2.id, item.id, organization.id, actor_id=1)

    # Each component's own delta was computed independently against the
    # ORIGINAL base zvE (not the post-c1 base) — proven by cross-checking
    # c2's delta against the same original zve_lohnsteuer/zve_surcharges.
    expected_wage_tax_1, expected_soli_1, _ = _expected_deltas("I", zve_lohnsteuer, zve_surcharges, Decimal("100.00"))
    expected_wage_tax_2, expected_soli_2, _ = _expected_deltas("I", zve_lohnsteuer, zve_surcharges, Decimal("150.00"))
    assert a1.applied_wage_tax_delta == expected_wage_tax_1
    assert a2.applied_wage_tax_delta == expected_wage_tax_2

    db.refresh(item)
    assert item.tds == (
        result["tds"] + expected_wage_tax_1 + expected_soli_1 + expected_wage_tax_2 + expected_soli_2
    )


def test_detach_reverses_wage_tax_soli_church_tax_deltas_exactly(db, organization):
    """Detach must return net_pay/tds/soli/church_tax to EXACTLY their
    pre-attach values — not just gross/SI as before Phase 8BW."""
    emp = _make_employee(db, organization.id, code="DE-OT-TAX-DETACH")
    run = _make_run(db, organization.id)
    profile = _FakeProfile(de_church_tax_liable=True, de_church_tax_land="DE-NW")
    item, result = _make_real_payslip_item(db, run, emp, organization.id, ctx_overrides={"germany_statutory_profile": profile})
    pre_tds, pre_soli, pre_church, pre_net = item.tds, item.soli, item.church_tax, item.net_pay

    wr = _make_work_record(db, emp, organization.id,
                            datetime(2026, 1, 13, 18, 0, tzinfo=timezone.utc), datetime(2026, 1, 13, 20, 0, tzinfo=timezone.utc))
    component = _make_component(db, wr, organization.id, gross=Decimal("250.00"), taxable=Decimal("250.00"))
    service.attach_germany_overtime_premium_component_to_payslip(db, component.id, item.id, organization.id, actor_id=1)
    db.refresh(item)
    assert item.tds != pre_tds  # sanity: attach actually changed something

    service.detach_germany_overtime_premium_component_from_payslip(db, component.id, organization.id, actor_id=1)
    db.refresh(item)
    assert item.tds == pre_tds
    assert item.soli == pre_soli
    assert item.church_tax == pre_church
    assert item.net_pay == pre_net

    db.refresh(component)
    assert component.financial_integration_status == "REVERSED"
    assert component.applied_wage_tax_delta is None
    assert component.applied_soli_delta is None
    assert component.applied_church_tax_delta is None


def test_reattach_after_detach_is_idempotent_and_reproduces_identical_deltas(db, organization):
    """Detach then re-attach the SAME component must land on the exact
    same tax deltas as the first attach — no drift, no double-application."""
    emp = _make_employee(db, organization.id, code="DE-OT-TAX-REATTACH")
    run = _make_run(db, organization.id)
    item, _result = _make_real_payslip_item(db, run, emp, organization.id)

    wr = _make_work_record(db, emp, organization.id,
                            datetime(2026, 1, 14, 18, 0, tzinfo=timezone.utc), datetime(2026, 1, 14, 20, 0, tzinfo=timezone.utc))
    component = _make_component(db, wr, organization.id, gross=Decimal("100.00"), taxable=Decimal("100.00"))

    first = service.attach_germany_overtime_premium_component_to_payslip(db, component.id, item.id, organization.id, actor_id=1)
    first_wage_tax = first.applied_wage_tax_delta
    service.detach_germany_overtime_premium_component_from_payslip(db, component.id, organization.id, actor_id=1)
    second = service.attach_germany_overtime_premium_component_to_payslip(db, component.id, item.id, organization.id, actor_id=1)
    assert second.applied_wage_tax_delta == first_wage_tax

    # Attaching an already-ATTACHED component again must be rejected, never
    # silently double-apply its tax delta.
    with pytest.raises(BadRequestException):
        service.attach_germany_overtime_premium_component_to_payslip(db, component.id, item.id, organization.id, actor_id=1)


def test_unapproved_overtime_component_cannot_be_attached(db, organization):
    """An overtime component whose work record is not APPROVED must be
    rejected outright — never silently attached with a fabricated tax
    delta."""
    emp = _make_employee(db, organization.id, code="DE-OT-TAX-UNAPPROVED")
    run = _make_run(db, organization.id)
    item, _result = _make_real_payslip_item(db, run, emp, organization.id)

    wr = _make_work_record(
        db, emp, organization.id,
        datetime(2026, 1, 15, 18, 0, tzinfo=timezone.utc), datetime(2026, 1, 15, 20, 0, tzinfo=timezone.utc),
        approval="PENDING",
    )
    component = _make_component(db, wr, organization.id, gross=Decimal("100.00"), taxable=Decimal("100.00"))

    with pytest.raises(BadRequestException):
        service.attach_germany_overtime_premium_component_to_payslip(db, component.id, item.id, organization.id, actor_id=1)

    db.refresh(item)
    # Nothing was applied — gross/tds/net_pay must be exactly the pre-attempt values.
    assert item.gross_pay == Decimal("5000.00")


def test_recalculation_preserves_overtime_tax_deltas(db, organization):
    """_reapply_attached_germany_overtime_deltas is called by
    regenerate_employee_payslip AFTER its own engine recompute has reset
    the payslip to its base (zero-overtime) figures — its own documented
    precondition (see the function's docstring). This test reproduces that
    exact sequence (capture attached components -> engine resets base
    figures -> reapply) rather than calling reapply on top of an
    already-attached payslip (which would double-apply the delta, a test
    bug, not an implementation one)."""
    emp = _make_employee(db, organization.id, code="DE-OT-TAX-RECALC")
    run = _make_run(db, organization.id)
    item, base_result = _make_real_payslip_item(db, run, emp, organization.id)
    base_tds = item.tds

    wr = _make_work_record(db, emp, organization.id,
                            datetime(2026, 1, 16, 18, 0, tzinfo=timezone.utc), datetime(2026, 1, 16, 20, 0, tzinfo=timezone.utc))
    component = _make_component(db, wr, organization.id, gross=Decimal("100.00"), taxable=Decimal("100.00"))
    attached = service.attach_germany_overtime_premium_component_to_payslip(db, component.id, item.id, organization.id, actor_id=1)
    db.refresh(item)
    tds_after_attach = item.tds
    assert attached.applied_wage_tax_delta > Decimal("0.00")
    assert tds_after_attach == base_tds + attached.applied_wage_tax_delta + attached.applied_soli_delta

    # Capture the attached components BEFORE simulating the engine's own
    # recompute reset (mirrors regenerate_employee_payslip's real call
    # order — see _attached_germany_overtime_components_for_item's own
    # docstring on why the join must be read before the reset).
    attached_components = service._attached_germany_overtime_components_for_item(db, item.id, organization.id)
    # Simulate the engine recompute resetting the payslip to its base
    # (zero-overtime) figures — exactly what happens inside
    # regenerate_employee_payslip before it calls the reapply function.
    item.tds = base_tds
    db.commit()

    service._reapply_attached_germany_overtime_deltas(db, item, organization.id, attached_components, actor_id=1)
    db.refresh(item)
    assert item.tds == tds_after_attach
