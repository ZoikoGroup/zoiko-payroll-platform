"""
modules/payroll/engine/resolver
-------------------------------
Resolves the organization's payroll policy to the correct strategy
and provides the top-level ``calculate_payroll()`` entry point.

The core payroll engine ORCHESTRATES only — all calculation logic
lives in the resolved strategy.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from app.modules.payroll.engine.base import (
    PAYROLL_DAYS,
    PayrollContext,
    PayrollResult,
    PayrollStrategy,
    _round2,
)
from app.modules.payroll.engine.simple import SimpleStrategy
from app.modules.payroll.engine.standard import StandardStrategy
from app.modules.payroll.engine.enterprise import EnterpriseStrategy

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# ── Strategy registry ──────────────────────────────────────────────────────

_STRATEGY_MAP: dict[str, type[PayrollStrategy]] = {
    "simple": SimpleStrategy,
    "standard": StandardStrategy,
    "enterprise": EnterpriseStrategy,
}

# Singleton instances (stateless strategies — safe to reuse)
_STRATEGY_INSTANCES: dict[str, PayrollStrategy] = {
    k: cls() for k, cls in _STRATEGY_MAP.items()
}


def resolve_strategy(calculation_mode: str | None = None) -> PayrollStrategy:
    """Return the strategy instance for the given calculation mode.

    Falls back to ``StandardStrategy`` for unknown / ``None`` modes.
    """
    key = (calculation_mode or "standard").lower().strip()
    return _STRATEGY_INSTANCES.get(key, _STRATEGY_INSTANCES["standard"])


def calculate_payroll(
    ctx: PayrollContext,
    calculation_mode: str | None = None,
) -> PayrollResult:
    """Convenience entry point — resolve strategy and calculate in one call.

    This is the single function that the rest of the payroll module should
    call.  It replaces the old ``_calculate_employee_monthly_payroll()``
    and the duplicated logic in ``preview_payroll_run``.
    """
    key = (calculation_mode or "standard").lower().strip()
    ctx.trace_id = ctx.trace_id or uuid.uuid4().hex
    logger = logging.getLogger("zoiko")
    # DEBUG, not INFO: a full payroll run calls this once per employee, so an
    # always-on per-employee log line here would flood production logs.
    logger.debug(
        "[payroll-calc trace_id=%s] country=%s mode=%s starting",
        ctx.trace_id, ctx.country, key,
    )
    if (ctx.country or "").upper() == "DE" and key == "simple":
        # Simple mode intentionally omits statutory deductions. It must never
        # be an escape hatch around Germany's statutory calculation boundary.
        from app.modules.payroll.engine.jurisdictions.germany.pap.core import GermanyCalculationError

        raise GermanyCalculationError(
            "GERMANY_SIMPLE_MODE_UNSUPPORTED",
            "Germany payroll cannot use simple calculation mode; use standard or enterprise.",
        )

    strategy = resolve_strategy(calculation_mode)
    try:
        result = strategy.calculate(ctx)
    except Exception:
        logger.warning(
            "[payroll-calc trace_id=%s] country=%s mode=%s failed",
            ctx.trace_id, ctx.country, key,
        )
        raise
    result.trace_id = ctx.trace_id
    return result


def build_context_from_employee(
    employee,
    gross: Decimal,
    basic: Decimal,
    hra: Decimal = Decimal("0"),
    special_allowance: Decimal = Decimal("0"),
    overtime: Decimal = Decimal("0"),
    additional_compensation: Decimal = Decimal("0"),
    unpaid_leave_days: int = 0,
    country: str = "IN",
    rate_map: dict | None = None,
    slabs: list | None = None,
    code_wages_rules: dict | None = None,
    epf_base_rules: dict | None = None,
    esi_base_rules: dict | None = None,
    pt_base_rules: dict | None = None,
    ca_taxability_rules: dict | None = None,
    us_taxability_rules: dict | None = None,
    au_taxability_rules: dict | None = None,
    other_income_for_tds: Decimal = Decimal("0"),
    tds_already_deducted: Decimal = Decimal("0"),
    annual_claims_total: Decimal = Decimal("0"),
    annual_perquisites_total: Decimal = Decimal("0"),
    payroll_days: int = PAYROLL_DAYS,
    work_state: str | None = None,
    state_rate_map: dict | None = None,
    state_slabs: list | None = None,
    employer_tax_profiles: dict | None = None,
    reciprocity_suppresses_work_state: bool = False,
    resident_state_rate_map: dict | None = None,
    resident_state_slabs: list | None = None,
    locality_rate=None,
    residence_locality_rate=None,
    germany_statutory_profile=None,
    germany_pap_asset=None,
    germany_health_fund=None,
    germany_u1_tariff=None,
    germany_ceiling_gkv_pv=None,
    germany_ceiling_rv_alv=None,
    germany_pv_configuration=None,
    germany_employee_id: int | None = None,
    germany_organization_id: int | None = None,
    germany_payroll_date=None,
    germany_sonstb=None,
    germany_earning_taxability: dict | None = None,
    germany_church_tax_exception=None,
    germany_minijob_midijob_parameters: dict | None = None,
    ytd_pensionable_earnings: Decimal | None = None,
    ytd_cpp2_pensionable_earnings: Decimal | None = None,
    ytd_insurable_earnings: Decimal | None = None,
    ytd_basic_exemption_used: Decimal | None = None,
    ytd_ss_wages_before: Decimal | None = None,
    ytd_futa_wages_before: Decimal | None = None,
    ytd_medicare_wages_before: Decimal | None = None,
    ytd_sg_qualifying_earnings_before: Decimal | None = None,
    option2_cumulative_gross_before: Decimal | None = None,
    option2_periods_elapsed_before: int | None = None,
    option2_federal_tax_withheld_before: Decimal | None = None,
    option2_provincial_tax_withheld_before: Decimal | None = None,
    on_eht_ytd_remuneration_before: Decimal | None = None,
    appr_levy_ytd_pay_bill_before: Decimal | None = None,
    employer_ni_ytd_before: Decimal | None = None,
    bc_eht_ytd_remuneration_before: Decimal | None = None,
    mb_he_levy_ytd_remuneration_before: Decimal | None = None,
    nl_hapset_ytd_remuneration_before: Decimal | None = None,
    bc_eht_employer_classification: str | None = None,
    qc_hsf_ytd_remuneration_before: Decimal | None = None,
    qc_hsf_employer_category: str | None = None,
    au_state_payroll_tax_ytd_remuneration_before: Decimal | None = None,
    au_payroll_tax_regional_status: str | None = None,
    au_payroll_tax_charity_exempt: bool | None = None,
    au_national_taxable_wages_ytd_before: Decimal | None = None,
    au_statutory_deduction_orders: list | None = None,
    pay_date=None,
    ytd_director_ni_gross: Decimal | None = None,
    ytd_director_ni_employee_paid: Decimal | None = None,
    ytd_director_ni_employer_paid: Decimal | None = None,
    is_final_ni_period: bool = False,
    ni_category_override: str | None = None,
) -> PayrollContext:
    """Helper to build a PayrollContext from a PayrollEmployee ORM object
    and pre-computed salary components. Tax-profile fields (tax_code,
    ni_category, study_loan_plan/balance, church_tax_liable) are read
    directly off `employee` here rather than added as more explicit
    params to every caller — they're genuinely employee-sourced, exactly
    like the identity/bank fields _compute_payslip_values already reads
    straight off `employee` elsewhere."""
    return PayrollContext(
        gross=gross,
        basic=basic,
        hra=hra,
        special_allowance=special_allowance,
        overtime=overtime,
        additional_compensation=additional_compensation,
        unpaid_leave_days=unpaid_leave_days,
        payroll_days=payroll_days,
        country=country,
        rate_map=rate_map or {},
        slabs=slabs or [],
        code_wages_rules=code_wages_rules or {},
        epf_base_rules=epf_base_rules or {},
        esi_base_rules=esi_base_rules or {},
        pt_base_rules=pt_base_rules or {},
        ca_taxability_rules=ca_taxability_rules or {},
        us_taxability_rules=us_taxability_rules or {},
        au_taxability_rules=au_taxability_rules or {},
        option2_cumulative_gross_before=option2_cumulative_gross_before,
        option2_periods_elapsed_before=option2_periods_elapsed_before,
        option2_federal_tax_withheld_before=option2_federal_tax_withheld_before,
        option2_provincial_tax_withheld_before=option2_provincial_tax_withheld_before,
        other_income_for_tds=other_income_for_tds,
        tds_already_deducted=tds_already_deducted,
        annual_claims_total=annual_claims_total,
        annual_perquisites_total=annual_perquisites_total,
        work_state=work_state,
        state_rate_map=state_rate_map or {},
        state_slabs=state_slabs or [],
        employer_tax_profiles=employer_tax_profiles or {},
        reciprocity_suppresses_work_state=reciprocity_suppresses_work_state,
        resident_state_rate_map=resident_state_rate_map or {},
        resident_state_slabs=resident_state_slabs or [],
        locality_rate=locality_rate,
        residence_locality_rate=residence_locality_rate,
        tax_code=getattr(employee, "tax_code", None),
        # ZP-TAX-UK-2026-27-001 §9.1/§9.3 gap-closure Part 2 (2026-09-09):
        # a derived category (from real Freeport/Investment Zone/veteran/
        # apprentice facts — see uk.py's derive_ni_category, called by
        # service.py's callers of this function) takes precedence over
        # the manually-set field when the caller supplies one; None
        # (every caller today, and every caller for any non-UK employee)
        # preserves the exact existing behavior.
        ni_category=ni_category_override or getattr(employee, "ni_category", None),
        study_loan_plan=getattr(employee, "study_loan_plan", None),
        study_loan_balance=getattr(employee, "study_loan_balance", None),
        has_postgrad_loan=bool(getattr(employee, "has_postgrad_loan", False)),
        church_tax_liable=bool(getattr(employee, "church_tax_liable", False)),
        tax_regime=getattr(employee, "tax_regime", None),
        pay_frequency=getattr(employee, "pay_frequency", None) or "Monthly",
        au_tfn_status=getattr(employee, "au_tfn_status", None),
        au_residency_status=getattr(employee, "au_residency_status", None),
        au_tax_free_threshold_claimed=getattr(employee, "au_tax_free_threshold_claimed", None),
        au_medicare_levy_exemption=getattr(employee, "au_medicare_levy_exemption", None),
        au_withholding_variation_pct=getattr(employee, "au_withholding_variation_pct", None),
        au_extra_pay_calendar=getattr(employee, "au_extra_pay_calendar", None),
        au_sapto_category=getattr(employee, "au_sapto_category", None),
        w4_filing_status=getattr(employee, "w4_filing_status", None),
        w4_form_vintage=getattr(employee, "w4_form_vintage", None),
        w4_step2_checkbox=bool(getattr(employee, "w4_step2_checkbox", False)),
        w4_allowances_claimed=getattr(employee, "w4_allowances_claimed", None),
        is_nonresident_alien=bool(getattr(employee, "is_nonresident_alien", False)),
        w4_dependents_credit_annual=getattr(employee, "w4_dependents_credit_annual", None),
        w4_other_income_annual=getattr(employee, "w4_other_income_annual", None),
        w4_extra_withholding_per_period=getattr(employee, "w4_extra_withholding_per_period", None),
        ct_withholding_code=getattr(employee, "ct_withholding_code", None),
        nj_rate_table=getattr(employee, "nj_rate_table", None),
        ks_k4_dependents=getattr(employee, "ks_k4_dependents", None),
        residence_locality=getattr(employee, "residence_locality", None),
        state_income_tax_election_pct=getattr(employee, "state_income_tax_election_pct", None),
        germany_statutory_profile=germany_statutory_profile,
        germany_pap_asset=germany_pap_asset,
        germany_health_fund=germany_health_fund,
        germany_u1_tariff=germany_u1_tariff,
        germany_ceiling_gkv_pv=germany_ceiling_gkv_pv,
        germany_ceiling_rv_alv=germany_ceiling_rv_alv,
        germany_pv_configuration=germany_pv_configuration,
        germany_employee_id=germany_employee_id,
        germany_organization_id=germany_organization_id,
        germany_payroll_date=germany_payroll_date,
        germany_sonstb=germany_sonstb,
        germany_earning_taxability=germany_earning_taxability,
        germany_church_tax_exception=germany_church_tax_exception,
        germany_minijob_midijob_parameters=germany_minijob_midijob_parameters,
        td1_claim_amount=getattr(employee, "td1_claim_amount", None),
        provincial_td1_claim_amount=getattr(employee, "provincial_td1_claim_amount", None),
        qc_tp1015_claim_amount=getattr(employee, "qc_tp1015_claim_amount", None),
        td1_additional_tax=getattr(employee, "td1_additional_tax", None),
        lsvcc_investment_amount=getattr(employee, "lsvcc_investment_amount", None),
        cpp_qpp_election_status=getattr(employee, "cpp_qpp_election_status", None),
        cpp_election_effective_date=getattr(employee, "cpp_election_effective_date", None),
        date_of_birth=getattr(employee, "date_of_birth", None),
        gender=getattr(employee, "gender", None),
        tax_residency_status=getattr(employee, "tax_residency_status", None),
        is_director=bool(getattr(employee, "is_director", False)),
        director_ni_method=getattr(employee, "director_ni_method", None),
        ytd_director_ni_gross=ytd_director_ni_gross,
        ytd_director_ni_employee_paid=ytd_director_ni_employee_paid,
        ytd_director_ni_employer_paid=ytd_director_ni_employer_paid,
        is_final_ni_period=is_final_ni_period,
        pay_date=pay_date,
        ytd_pensionable_earnings=ytd_pensionable_earnings,
        ytd_cpp2_pensionable_earnings=ytd_cpp2_pensionable_earnings,
        ytd_insurable_earnings=ytd_insurable_earnings,
        ytd_basic_exemption_used=ytd_basic_exemption_used,
        ytd_ss_wages_before=ytd_ss_wages_before,
        ytd_futa_wages_before=ytd_futa_wages_before,
        ytd_medicare_wages_before=ytd_medicare_wages_before,
        ytd_sg_qualifying_earnings_before=ytd_sg_qualifying_earnings_before,
        on_eht_ytd_remuneration_before=on_eht_ytd_remuneration_before,
        appr_levy_ytd_pay_bill_before=appr_levy_ytd_pay_bill_before,
        employer_ni_ytd_before=employer_ni_ytd_before,
        bc_eht_ytd_remuneration_before=bc_eht_ytd_remuneration_before,
        mb_he_levy_ytd_remuneration_before=mb_he_levy_ytd_remuneration_before,
        nl_hapset_ytd_remuneration_before=nl_hapset_ytd_remuneration_before,
        bc_eht_employer_classification=bc_eht_employer_classification,
        qc_hsf_ytd_remuneration_before=qc_hsf_ytd_remuneration_before,
        qc_hsf_employer_category=qc_hsf_employer_category,
        au_state_payroll_tax_ytd_remuneration_before=au_state_payroll_tax_ytd_remuneration_before,
        au_payroll_tax_regional_status=au_payroll_tax_regional_status,
        au_payroll_tax_charity_exempt=au_payroll_tax_charity_exempt,
        au_national_taxable_wages_ytd_before=au_national_taxable_wages_ytd_before,
        au_statutory_deduction_orders=au_statutory_deduction_orders or [],
    )
