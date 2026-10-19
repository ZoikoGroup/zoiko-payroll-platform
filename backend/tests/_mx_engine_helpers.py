"""Shared builders for the Mexico engine tests (Phase 5).

EVERY value here is SYNTHETIC — chosen to be easy to compute by hand and
deliberately unlike any published Mexican figure. None is a statutory value
and none may be copied into mexico_content or a golden vector."""

import copy
from datetime import date
from decimal import Decimal

D = Decimal
PAY_DATE = date(2026, 6, 15)


def amt(v):
    return {"employee_rate_pct": None, "employer_rate_pct": None, "flat_amount": str(v), "jurisdiction_state": None,
            "text_value": None}


def ee(v):
    return {**amt(None), "flat_amount": None, "employee_rate_pct": str(v)}


def er(v):
    return {**amt(None), "flat_amount": None, "employer_rate_pct": str(v)}


def txt(v):
    return {**amt(None), "flat_amount": None, "text_value": v}


SYN_RATES = {
    "mx_uma_daily": amt("100"), "mx_uma_monthly": amt("3000"), "mx_uma_annual": amt("36500"),
    "mx_subsidy_rate_pct": ee("10"), "mx_subsidy_income_ceiling_monthly": amt("8000"),
    "mx_subsidy_period_days_divisor": amt("30"),
    "mx_sbc_max_uma_multiple": amt("20"),
    "mx_imss_em_fixed_quota_er_pct": er("15"), "mx_imss_em_excess_threshold_uma": amt("4"),
    "mx_imss_em_excess_er_pct": er("1.2"), "mx_imss_em_excess_ee_pct": ee("0.5"),
    "mx_imss_em_cash_er_pct": er("0.8"), "mx_imss_em_cash_ee_pct": ee("0.3"),
    "mx_imss_em_pensioner_er_pct": er("1.1"), "mx_imss_em_pensioner_ee_pct": ee("0.4"),
    "mx_imss_iv_er_pct": er("1.6"), "mx_imss_iv_ee_pct": ee("0.7"),
    "mx_imss_guarderias_er_pct": er("1.2"), "mx_imss_retiro_er_pct": er("2.5"), "mx_imss_ceav_ee_pct": ee("1.1"),
    "mx_ceav_lowest_band_min_wage_ref": txt("GENERAL"),
    "mx_infonavit_er_pct": er("4"),
    "mx_aguinaldo_min_days": amt("10"), "mx_vacation_premium_min_pct": ee("20"), "mx_sunday_premium_min_pct": ee("20"),
    "mx_risk_premium_min_pct": er("0.1"), "mx_risk_premium_max_pct": er("9"),
    "mx_rounding_rule": txt("HALF_UP:0.01"), "mx_sbc_min_rule": txt("RAISE_TO_ZONE_MIN_WAGE"),
}


def isr_slabs(period):
    """11 brackets of 1000 each: lower i*1000+0.01 (first 0.01), fixed 5*i*(i+1) (continuous),
    rate (i+1) %. SYNTHETIC."""
    out = []
    for i in range(11):
        out.append({"rule_type": "MX_ISR_TARIFF", "filing_status": period,
                    "min_amount": str(D(i * 1000) + D("0.01")) if i else "0.01",
                    "max_amount": None if i == 10 else str((i + 1) * 1000),
                    "flat_amount": str(5 * i * (i + 1)), "rate_pct": str(i + 1), "jurisdiction_state": None,
                    "assessment_basis": None})
    return out


def base_slabs():
    slabs = []
    for p in ("DAILY", "WEEKLY_7", "DECENAL_10", "QUINCENAL_15", "MONTHLY"):
        slabs += isr_slabs(p)
    slabs += [
        {"rule_type": "MX_MIN_WAGE", "filing_status": "GENERAL", "flat_amount": "80", "assessment_basis": "ZONE",
         "jurisdiction_state": None},
        {"rule_type": "MX_MIN_WAGE", "filing_status": "ZLFN", "flat_amount": "120", "assessment_basis": "ZONE",
         "jurisdiction_state": None},
        {"rule_type": "MX_CEAV_BAND", "filing_status": "1.00SM", "min_amount": "1.00", "max_amount": "1.00",
         "rate_pct": "3", "assessment_basis": "SM/SM"},
        {"rule_type": "MX_CEAV_BAND", "filing_status": "1.01UMA", "min_amount": "1.01", "max_amount": "1.50",
         "rate_pct": "4", "assessment_basis": "UMA/UMA"},
        {"rule_type": "MX_CEAV_BAND", "filing_status": "1.51UMA", "min_amount": "1.51", "max_amount": "2.00",
         "rate_pct": "5", "assessment_basis": "UMA/UMA"},
        {"rule_type": "MX_CEAV_BAND", "filing_status": "2.01UMA", "min_amount": "2.01", "max_amount": None,
         "rate_pct": "9", "assessment_basis": "UMA/-"},
        {"rule_type": "MX_WORKWEEK", "filing_status": "WEEKLY_MAX", "flat_amount": "50", "min_amount": "0"},
        {"rule_type": "MX_VACATION_DAYS", "filing_status": "YEAR_1", "min_amount": "1", "max_amount": "1", "flat_amount": "10"},
        {"rule_type": "MX_VACATION_DAYS", "filing_status": "YEAR_2", "min_amount": "2", "max_amount": "2", "flat_amount": "12"},
        {"rule_type": "MX_VACATION_DAYS", "filing_status": "YEAR_3", "min_amount": "3", "max_amount": None, "flat_amount": "14"},
    ]
    return slabs


def classification(code="SALARY", **over):
    row = {"id": 1, "earning_code": code, "version": 1, "effective_from": date(2026, 1, 1), "effective_to": None,
           "status": "ACTIVE", "isr_treatment": "TAXABLE", "isr_exempt_rule_key": None, "sbc_treatment": "FIXED",
           "infonavit_included": True, "isn_default_included": True, "isn_state_overrides": None,
           "ptu_wage_base_included": True, "cfdi_node_type": "PERCEPCION", "cfdi_concept_code": None}
    row.update(over)
    return row


def facts(**over):
    """Every Mexico fact of one SYNTHETIC quincenal payslip (salary 600/day)."""
    f = {
        "mx_payroll_date": PAY_DATE, "mx_payment_period": "QUINCENAL_15",
        "mx_profile": {"mx_daily_salary": D("600"), "mx_seniority_date": date(2024, 3, 1), "mx_work_state": "CDMX",
                       "mx_identifier_validation_status": "FORMAT_ONLY", "mx_professional_min_code": None},
        "mx_registration": {"id": 1, "status": "ACTIVE"},
        "mx_risk_premium": {"registration_id": 1, "status": "ACTIVE", "premium_rate_pct": "0.5",
                            "period_from": date(2026, 3, 1), "period_to": date(2027, 2, 28)},
        "mx_labor_policy": {"ordinary_weekly_hours": "40", "aguinaldo_days": "15", "vacation_premium_pct": "25",
                            "sunday_premium_pct": "25",
                            "vacation_policy": [{"serviceYearFrom": 1, "serviceYearTo": 1, "days": 12},
                                                {"serviceYearFrom": 2, "serviceYearTo": 2, "days": 14},
                                                {"serviceYearFrom": 3, "serviceYearTo": None, "days": 16}]},
        "mx_isn_state_pack": {"state": "CDMX", "status": "Active", "pack_id": "MX-ISN-CDMX-2026", "version": 1,
                              "rate_map": {"mx_isn_rate_pct": er("3")}},
        "mx_classifications": {"SALARY": classification()},
        "mx_earnings": [{"code": "SALARY", "kind": "ORDINARY_SALARY", "amount": D("9000")}],
        "mx_period": {"start": date(2026, 6, 1), "end": date(2026, 6, 15), "days_paid": 15},
        "mx_hours": None,
        "mx_variable_accumulator": {"total": 0, "days": 0},
        "mx_min_wage_zone": "GENERAL",
        "mx_month_to_date": {"taxable": 0, "subsidy_applied": 0},
        "mx_infonavit_notices": [],
        "mx_pack": {"pack_id": "MX-PAYROLL-2026", "version": 1, "source_codes": ["SYNTHETIC"]},
        "mx_organization_id": 11,
    }
    f.update(over)
    return f


def ctx(rates=None, slabs=None, gross=None, **over):
    from app.modules.payroll.engine.base import PayrollContext

    f = facts(**over)
    if gross is None:
        gross = sum((D(str(l["amount"])) for l in f["mx_earnings"]), D("0"))
    return PayrollContext(gross=D(str(gross)), basic=D(str(gross)), country="MX",
                          rate_map=copy.deepcopy(SYN_RATES) if rates is None else rates,
                          slabs=base_slabs() if slabs is None else slabs, **f)


def content(rates=None, slabs=None):
    from app.modules.payroll.engine.jurisdictions.mexico.content import Content

    return Content(copy.deepcopy(SYN_RATES) if rates is None else rates, base_slabs() if slabs is None else slabs)


def without(key):
    rates = copy.deepcopy(SYN_RATES)
    rates.pop(key)
    return rates
