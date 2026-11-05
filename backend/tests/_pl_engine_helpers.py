"""Test helpers for the Poland P3 engine.

`build_pack()` turns poland_content into an in-memory rate_map / slabs the way
seed_poland_pack writes them. With signed=True (the default) it strips the
"[PENDING G1]" labels and fills every value the specification leaves open with
clearly labelled TEST fixtures — simulating a G1-signed pack. TEST values are
fixtures only: they are never copied into poland_content.py and are not
statutory content. signed=False reproduces the shipped (unsigned) content.
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.countries import poland_content as content

PENDING = " [PENDING G1]"
WINDOW_FROM, WINDOW_TO = content.PL_2026[1], content.PL_2026[2]
PAY_DATE = date(2026, 3, 31)

# TEST fixtures for the points the specification does not decide.
TEST_TEXT = {
    "pl_rounding_pit": "FULL_PLN_HALF_UP",
    "pl_rounding_zus": "GROSZ_HALF_UP",
    "pl_rounding_health": "GROSZ_HALF_UP",
    "pl_rounding_ppk": "GROSZ_HALF_UP",
    "pl_health_limitation_rule": "NONE",
    "pl_ppk_employer_pit_treatment": "TAXABLE_EMPLOYEE_INCOME",
    "pl_fp_fs_min_base_rule": "BASE_AT_LEAST_MIN_WAGE",
    "pl_fund_cap_rule": "CAPPED_WITH_PENSION_BASE",
    "pl_sick_age_rule": "FROM_YEAR_AFTER_REACHING_AGE",
}
TEST_AMOUNTS = {
    "pl_costs_standard_annual_cap": "3000",
    "pl_costs_standard_multi_annual_cap": "4500",
    "pl_costs_commuter_annual_cap": "3600",
    "pl_costs_commuter_multi_annual_cap": "5400",
    "pl_pit0_annual_limit": "85528",
}


def _rate(row, pending):
    key, label, ee, er, flat, text, _src, is_pending, eff_from, eff_to, _basis = row
    return SimpleNamespace(component_key=key, label=label + (PENDING if pending and is_pending else ""),
                           employee_rate_pct=None if ee is None else Decimal(ee),
                           employer_rate_pct=None if er is None else Decimal(er),
                           flat_amount=None if flat is None else Decimal(flat), text_value=text,
                           effective_from=eff_from or WINDOW_FROM, effective_to=eff_to or WINDOW_TO)


def _slab(**kw):
    base = dict(id=None, rule_type=None, filing_status=None, tax_regime=None, assessment_basis=None,
                min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("0"), flat_amount=None,
                rate_label="row", sort_order=0, effective_from=WINDOW_FROM, effective_to=WINDOW_TO)
    base.update(kw)
    return SimpleNamespace(**base)


def build_pack(overrides=None, signed=True, classes=None):
    """(rate_map, slabs). `overrides` sets text_value (str for text keys),
    flat_amount, or (employee_pct, employer_pct) tuples; `classes` overrides
    earning-class treatments {(obligation, component): treatment}."""
    rate_map = {row[0]: _rate(row, pending=not signed) for row in content.POLAND_SCALAR_CONTENT}
    if signed:
        for key, value in TEST_TEXT.items():
            rate_map[key].text_value = value
        for key, value in TEST_AMOUNTS.items():
            rate_map[key].flat_amount = Decimal(value)
    for key, value in (overrides or {}).items():
        kind = content.POLAND_PARAMETER_KEYS[key]
        if isinstance(value, tuple):
            rate_map[key].employee_rate_pct, rate_map[key].employer_rate_pct = (
                None if v is None else Decimal(str(v)) for v in value)
        elif kind == "text":
            rate_map[key].text_value = value
        else:
            rate_map[key].flat_amount = None if value is None else Decimal(str(value))
    slabs, ident = [], 0
    for lo, hi, rate, base, label, _src in content.POLAND_PIT_BANDS:
        ident += 1
        slabs.append(_slab(id=ident, rule_type=content.PL_PIT_BAND_RULE, min_amount=Decimal(lo),
                           max_amount=None if hi is None else Decimal(hi), rate_pct=Decimal(rate),
                           flat_amount=Decimal(base), rate_label=label))
    treatments = {(o, c): t for (o, t, c, *_r) in content.POLAND_EARNING_CLASSES}
    treatments.update(classes or {})
    for (obligation, component), treatment in treatments.items():
        ident += 1
        slabs.append(_slab(id=ident, rule_type=content.PL_EARNING_CLASS_RULE, tax_regime=obligation,
                           filing_status=component, assessment_basis=treatment, rate_label="class"))
    return rate_map, slabs


def profile(**overrides):
    values = dict(contract_type="UMOWA_O_PRACE", pay_frequency="MONTHLY", tax_residency="RESIDENT",
                  fte_numerator=1, fte_denominator=1, service_credit_months=60,
                  cov_pension=True, cov_disability=True, cov_sickness=True, cov_accident=True, cov_health=True,
                  other_titles_declared=False, a1_certificate=False, is_student=False, is_pensioner=False,
                  fep_qualifying=False, fep_from=None, fep_to=None, fund_exemption_code=None,
                  status="ACTIVE", effective_from=date(2026, 1, 1), effective_to=None)
    values.update(overrides)
    return SimpleNamespace(**values)


def registration(**overrides):
    values = dict(status="ACTIVE", effective_from=date(2026, 1, 1), effective_to=None,
                  accident_rate_pct=Decimal("1.67"), accident_rate_source="ZUS_NOTICE",
                  accident_rate_from=date(2025, 4, 1), accident_rate_to=date(2026, 3, 31),
                  fp_fs_applicable=True, fgsp_applicable=True, ppk_employer_additional_pct=None)
    values.update(overrides)
    return SimpleNamespace(**values)


def declaration(kind, value=None, status="APPROVED", effective_from=date(2026, 1, 1), effective_to=None, ident=None):
    return {"id": ident, "declaration_type": kind, "status": status, "effective_from": effective_from,
            "effective_to": effective_to, "value": value or {}}


def ytd(**overrides):
    values = {key: Decimal("0") for key in content.ACCUMULATORS}
    values.update({k: Decimal(str(v)) for k, v in overrides.items()})
    return values


DEFAULT_DECLARATIONS = (declaration("PIT2", {"allocation": "FULL"}, ident=1),)


def ctx(gross="8000", components=None, pack=None, pay_date=PAY_DATE, declarations=DEFAULT_DECLARATIONS,
        ppk_state="ENROLLED", profile_overrides=None, registration_overrides=None, ytd_overrides=None,
        **extra):
    rate_map, slabs = pack or build_pack()
    gross = Decimal(str(gross))
    values = dict(
        gross=gross, basic=gross, country="PL", rate_map=rate_map, slabs=slabs, pay_date=pay_date,
        pl_pay_date=pay_date, pl_profile=profile(**(profile_overrides or {})),
        pl_registration=registration(**(registration_overrides or {})),
        pl_components=components if components is not None else {"SALARY": gross},
        pl_declarations=list(declarations),
        pl_ppk=None if ppk_state is None else SimpleNamespace(state=ppk_state),
        pl_ytd=ytd(**(ytd_overrides or {})), pl_organization_id=1, pl_employee_id=1,
    )
    values.update(extra)
    return PayrollContext(**values)
