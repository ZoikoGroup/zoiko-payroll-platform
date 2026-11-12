"""SYNTHETIC Belgium pack and records for engine tests (Block A3).

TEST ONLY content: made-up codes ("X1", "W1") and obviously fake figures
(rates 10.00 / 1.00, flat amounts 30 / 50, gross 1000). Nothing here is taken
from the specification's proposed values, and nothing touches the real seeded
Draft pack. Imports are lazy (collection-order hazard)."""
from datetime import date
from decimal import Decimal

TEST = "TEST ONLY"
START = "2026-01-01"
PAY = date(2026, 3, 31)

SCOPE = {
    "be_onss_supported_employer_categories": "X1",
    "be_onss_supported_worker_codes": "W1,W2",
    "be_supported_worker_categories": "MANUAL,EMPLOYEE",
    "be_supported_contract_types": "INDEFINITE,FIXED_TERM",
    "be_supported_pay_frequencies": "MONTHLY",
    "be_supported_pay_bases": "SALARIED",
    "be_onss_manual_base_categories": "MANUAL",
}
TEXT = {"be_rounding_onss": "CENT_HALF_UP", "be_rounding_withholding": "CENT_HALF_UP",
        "be_rounding_holiday": "CENT_HALF_UP", "be_red_structural": "NOT_SUPPORTED",
        "be_red_target_group": "NOT_SUPPORTED",
        "be_wht_applicability_rule": "TEST_ONLY", "be_wht_taxable_basis_rule": "TEST_ONLY",
        "be_wht_period_strategy": "TEST_ONLY", "be_wht_nonresident_rule": "TEST_ONLY"}
EMPLOYEE_RATES = {"be_onss_employee_rate": "10.00", "be_onss_manual_base_uplift": "10.00"}
# B1 (TEST ONLY): interprofessional fallback 1000, minimum age 10, limits 12 h / 50 h.
AMOUNTS = {"be_wage_rmmmg": "1000", "be_wage_rmmmg_min_age": "10", "be_wt_daily_limit_hours": "12",
           "be_wt_weekly_limit_hours": "50", "be_wage_index_centime_threshold": "1000"}
# B1 (TEST ONLY): overtime premiums 10 / 20 %, wage-norm margin 10 %, one public holiday.
B1_EMPLOYEE_RATES = {"be_ot_premium_weekday": "10.00", "be_ot_premium_sunday_holiday": "20.00"}
B1_EMPLOYER_RATES = {"be_wage_norm_margin": "10.00"}
B1_FORMULAS = {"be_ot_compensatory_rest_rule": "overtime * 1", "be_wage_index_centime_rule": "min(increase, 10)"}
TEST_HOLIDAY = "2026-04-06"
# B2 (TEST ONLY): double holiday 10 %, fund debit 10 %, guaranteed 10 days at 10 %, contract condition 5 months,
# relapse window 3 weeks, manual bands day 1-7 at 10 % / day 8-30 at 5 %, birth leave 20 days of which 3 employer.
B2_TEXT = {"be_hol_wc_simple_rule": "TEST_ONLY", "be_hol_wc_double_contribution_rule": "TEST_ONLY"}
B2_EMPLOYEE_RATES = {"be_hol_wc_double_pct": "10.00"}
B2_EMPLOYER_RATES = {"be_hol_manual_annual_debit": "10.00", "be_abs_wc_guaranteed_pct": "10.00"}
B2_AMOUNTS = {"be_abs_wc_guaranteed_days": "10", "be_abs_wc_min_contract_months": "5",
              "be_abs_relapse_window_weeks": "3", "be_abs_birth_leave_days": "20", "be_abs_birth_leave_employer_days": "3"}
B2_FORMULAS = {"be_hol_additional_rule": "days * 10", "be_hol_departure_rule": "reference * months / 100"}
EMPLOYER_RATES = {"be_onss_wage_moderation": "10.00", "be_onss_special_160": "10.00",
                  "be_onss_pension_special": "10.00", "be_hol_manual_quarterly_contribution": "10.00"}
SLAB_KEYS = ("be_red_social_work_bonus", "be_onss_employer_base_rate", "be_onss_fund_contributions",
             "be_wht_annex3_regular_scale", "be_wht_family_reductions", "be_wht_annex3_amendment_2026",
             "be_wht_fiscal_work_bonus", "be_wht_exceptional_rule", "be_wht_holiday_pay_rule", "be_wht_arrears_rule",
             "be_wht_overtime_rule")
FORMULAS = {"be_wht_annex3_amendment_2026": "tax", "be_wht_fiscal_work_bonus": "social_bonus * 0.5",
            "be_wht_holiday_pay_rule": "amount * 0.1", "be_wht_arrears_rule": "amount * 0.1",
            "be_wht_overtime_rule": "tax"}
# component -> obligations where it is INCLUDED (every other obligation: EXCLUDED)
CLASSES = {
    "SALARY": ("ONSS_EMPLOYEE", "ONSS_EMPLOYER", "ONSS_MANUAL_108", "WITHHOLDING_REGULAR", "HOLIDAY_BASE",
               "SECTOR_MIN_WAGE"),
    "BONUS": ("ONSS_EMPLOYEE", "ONSS_EMPLOYER", "ONSS_MANUAL_108", "WITHHOLDING_EXCEPTIONAL"),
    "HOLIDAY_PAY_DOUBLE": ("WITHHOLDING_EXCEPTIONAL",),
    "ARREARS": ("ONSS_EMPLOYEE", "ONSS_EMPLOYER", "ONSS_MANUAL_108", "WITHHOLDING_EXCEPTIONAL"),
    "OVERTIME_PREMIUM": ("ONSS_EMPLOYEE", "ONSS_EMPLOYER", "ONSS_MANUAL_108", "WITHHOLDING_REGULAR"),
    "GUARANTEED_SALARY": ("ONSS_EMPLOYEE", "ONSS_EMPLOYER", "ONSS_MANUAL_108", "WITHHOLDING_REGULAR"),
    "BIRTH_LEAVE_PAY": ("ONSS_EMPLOYEE", "ONSS_EMPLOYER", "ONSS_MANUAL_108", "WITHHOLDING_REGULAR"),
    "DEPARTURE_HOLIDAY_PAY": ("WITHHOLDING_EXCEPTIONAL",),
}


def rate(key, text=None, employee=None, employer=None, label=TEST, start=START, end=None):
    return {"component_key": key, "label": label, "text_value": text, "employee_rate_pct": employee,
            "employer_rate_pct": employer, "flat_amount": None, "effective_from": start, "effective_to": end}


def slab(key, low="0", high=None, pct="0", flat=None, dims=None, formula=None, name=None, start=START, end=None,
         label=TEST):
    from app.modules.payroll.engine.countries import belgium_content as c

    return {"rule_type": c.RULE_TYPES[key], "filing_status": dims, "min_amount": low, "max_amount": high,
            "rate_pct": pct, "flat_amount": flat, "formula_expression": formula, "tax_formula": name or key,
            "rate_label": f"{label} {key}", "effective_from": start, "effective_to": end, "sort_order": 0}


def build_pack(rates_over=None, slabs_over=None, drop_slabs=()):
    """(rate_map, slabs) of a complete synthetic signed pack."""
    from app.modules.payroll.engine.countries import belgium_content as c

    rate_map = {k: rate(k, text=v) for k, v in {**SCOPE, **TEXT}.items()}
    rate_map.update({k: rate(k, employee=v) for k, v in EMPLOYEE_RATES.items()})
    rate_map.update({k: rate(k, employer=v) for k, v in EMPLOYER_RATES.items()})
    rate_map.update({k: dict(rate(k), flat_amount=v) for k, v in AMOUNTS.items()})
    rate_map.update({k: rate(k, employee=v) for k, v in B1_EMPLOYEE_RATES.items()})
    rate_map.update({k: rate(k, employer=v) for k, v in B1_EMPLOYER_RATES.items()})
    rate_map.update({k: rate(k, text=c.SLAB_ROWS) for k in (*B1_FORMULAS, "be_public_holidays")})
    rate_map["be_ot_threshold_rule"] = rate("be_ot_threshold_rule", text="TEST_ONLY")
    rate_map.update({k: rate(k, text=v) for k, v in B2_TEXT.items()})
    rate_map.update({k: rate(k, employee=v) for k, v in B2_EMPLOYEE_RATES.items()})
    rate_map.update({k: rate(k, employer=v) for k, v in B2_EMPLOYER_RATES.items()})
    rate_map.update({k: dict(rate(k), flat_amount=v) for k, v in B2_AMOUNTS.items()})
    rate_map.update({k: rate(k, text=c.SLAB_ROWS) for k in (*B2_FORMULAS, "be_abs_manual_day_bands")})
    rate_map.update({k: rate(k, text=c.SLAB_ROWS) for k in SLAB_KEYS})
    slabs = []
    for component, included in CLASSES.items():
        for obligation in c.OBLIGATIONS:
            slabs.append({"rule_type": c.EARNING_CLASS_RULE, "tax_regime": obligation, "filing_status": component,
                          "assessment_basis": "INCLUDED" if obligation in included else "EXCLUDED",
                          "rate_label": f"{TEST} class", "effective_from": START, "effective_to": None})
    slabs += [
        slab("be_red_social_work_bonus", flat="30"),
        slab("be_onss_employer_base_rate", pct="10.00", dims="EC=X1;WC=W1"),
        slab("be_onss_employer_base_rate", pct="10.00", dims="EC=X1;WC=W2"),
        slab("be_onss_fund_contributions", pct="1.00", dims="EC=X1;WC=W1", name="FUND_A"),
        slab("be_onss_fund_contributions", pct="1.00", dims="EC=X1;WC=W2", name="FUND_A"),
        slab("be_wht_annex3_regular_scale", pct="10.00"),
        slab("be_wht_family_reductions", high="1", flat="0"),
        slab("be_wht_family_reductions", low="1", flat="50"),
        slab("be_wht_exceptional_rule", pct="10.00"),
    ]
    slabs += [slab(k, formula=v) for k, v in FORMULAS.items()]
    slabs += [slab(k, formula=v) for k, v in B1_FORMULAS.items()]
    slabs += [slab(k, formula=v) for k, v in B2_FORMULAS.items()]
    slabs += [slab("be_abs_manual_day_bands", low="1", high="8", pct="10.00"),
              slab("be_abs_manual_day_bands", low="8", high="31", pct="5.00")]
    slabs.append({"rule_type": c.PUBLIC_HOLIDAY_RULE, "effective_from": TEST_HOLIDAY, "effective_to": TEST_HOLIDAY,
                  "tax_formula": "TEST ONLY holiday", "rate_label": f"{TEST} holiday", "min_amount": "0"})
    slabs = [s for s in slabs if s["rule_type"] not in {c.RULE_TYPES[k] for k in drop_slabs}]
    for key, value in (rates_over or {}).items():
        if value is None:
            rate_map.pop(key, None)
        else:
            rate_map[key] = value
    slabs += list(slabs_over or [])
    return rate_map, slabs


def records(**over):
    rows = {
        "be_registration": {"id": 1, "legal_entity_id": None, "status": "ACTIVE", "verification_state": "VERIFIED",
                            "employer_category_code": "X1", "onss_special_160_status": "NOT_APPLICABLE",
                            "effective_from": START, "effective_to": None},
        "be_profile": {"id": 2, "status": "ACTIVE", "worker_category": "EMPLOYEE", "onss_worker_code": "W1",
                       "residency": "RESIDENT", "special_status": None, "pay_basis": "SALARIED", "effective_from": START,
                       "effective_to": None},
        "be_classifications": [{"id": 3, "employment_line": "MAIN", "status": "ACTIVE", "joint_committee": "200",
                                "sub_committee": None, "collective_agreement_id": 30, "function_class": "B",
                                "seniority_months": 24, "establishment_unit_id": None, "work_schedule_id": None,
                                "contract_type": "INDEFINITE",
                                "effective_from": START, "effective_to": None}],
        "be_schedules": [{"id": 40, "status": "ACTIVE", "regime": "EFFECTIVE", "weekly_hours": "38",
                          "effective_from": START, "effective_to": None}],
        "be_agreements": {30: {"id": 30, "agreement_code": "BE-PC-200-1.0", "jurisdiction_country": "BE",
                               "status": "Active", "effective_from": START, "effective_to": None}},
        "be_units": {}, "be_declarations": [],
        "be_pay_frequency": "Monthly", "be_component_mappings": {"PLATFORM_FIELD:basic": "SALARY"},
        "be_ytd": {}, "be_pack_version": "TEST-PACK@1.0", "be_organization_id": 1,
        "be_date_of_birth": "1990-01-01",
    }
    rows.update(over)
    return rows


def context(gross="1000", pay_date=PAY, pack=None, components=None, **over):
    from app.modules.payroll.engine.base import PayrollContext

    rate_map, slabs = pack or build_pack()
    return PayrollContext(gross=Decimal(gross), basic=Decimal(gross), country="BE", rate_map=rate_map, slabs=slabs,
                          pay_date=pay_date, be_pay_date=pay_date, be_components=components,
                          **records(**over))
