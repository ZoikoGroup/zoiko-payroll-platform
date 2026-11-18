"""UAE pension contributions (ZP-AE-ENG-001 §6 GPSSA, §7 ADPF, §8 GCC).

Contribution salary S is the authority-backed value on the employee
(AE-019: never derived from Basic Wage or total Wage). Then:

    S_used          = min(S, scheme maximum)          (below a scheme minimum -> block)
    employee        = S_used × employee share
    employer gross  = S_used × employer share
    gov. support    = S_used × support share   (GPSSA, only when the employee is
                      marked eligible; Law 57 only while S_used < the support limit)
    employer cash   = employer gross − gov. support    (AE-018: shown separately)

GCC nationals (AE-025): the home-country row ae_gcc_<CC> (employee / employer
shares, optional ae_gcc_<CC>_salary_max) as configured by Super Admin; the spec
gives no values, so a missing row blocks with a named reason.
"""
from decimal import Decimal

from app.modules.payroll.engine.base import _round2
from app.modules.payroll.engine.jurisdictions.uae import errors as E
from app.modules.payroll.engine.jurisdictions.uae import params as P

# scheme -> (rate key, maximum-salary key, minimum-salary key, support key, support-limit key)
_SCHEMES = {
    "GPSSA_LAW_7_1999": ("ae_gpssa_law7", "ae_gpssa_law7_salary_max", None, "ae_gpssa_law7_gov_support", None),
    "GPSSA_LAW_57_2023": ("ae_gpssa_law57", "ae_gpssa_law57_salary_max", "ae_gpssa_law57_salary_min",
                          "ae_gpssa_law57_gov_support", "ae_gpssa_law57_gov_support_limit"),
    "ADPF_IN_SERVICE": ("ae_adpf_in_service", "ae_adpf_in_service_salary_max", None, None, None),
    "ADPF_NEW_MEMBER": ("ae_adpf_new", "ae_adpf_new_salary_max", None, None, None),
}
_ZERO = Decimal("0")


def _block(code, reason):
    return E.AECalculationBlockedError(code, reason)


def contribution_salary(facts: dict) -> Decimal:
    raw = (facts or {}).get("pension_contribution_salary")
    if raw in (None, ""):
        raise _block(E.keyed(E.EMPLOYEE_FACT_MISSING, "pension_contribution_salary"),
                     "the employee's pension contribution salary (from the GPSSA / ADPF / GCC record) is not set.")
    return Decimal(str(raw))


def calculate(facts: dict, rate_map: dict) -> dict:
    """Returns {"scheme", "contribution_salary", "salary_used", "employee", "employer_gross",
    "government_support", "employer_cash", "rates"}; all zero for an expatriate."""
    nationality = (facts.get("nationality_category") or "").upper()
    scheme = (facts.get("pension_scheme") or "").upper()
    if nationality == "EXPATRIATE":
        return {"scheme": "NONE", "contribution_salary": _ZERO, "salary_used": _ZERO, "employee": _ZERO,
                "employer_gross": _ZERO, "government_support": _ZERO, "employer_cash": _ZERO, "rates": {}}

    if nationality == "GCC_NATIONAL":
        country = (facts.get("gcc_country") or "").upper()
        key = f"ae_gcc_{country.lower()}"
        if not country or not P.has(rate_map, key):
            raise _block(E.keyed(E.GCC_RATES_NOT_CONFIGURED, country or "?"),
                         f"GCC home-country contribution rates for '{country or 'unknown'}' are not configured "
                         f"(add '{key}' in Super Admin → Compliance → United Arab Emirates → Contribution Rates).")
        rate_key, max_key, min_key, support_key, limit_key = key, f"{key}_salary_max", None, None, None
        scheme = f"GCC_EXTENSION_{country}"
    elif nationality == "UAE_NATIONAL" and scheme in _SCHEMES:
        rate_key, max_key, min_key, support_key, limit_key = _SCHEMES[scheme]
    else:
        raise _block(E.keyed(E.EMPLOYEE_FACT_MISSING, "pension_scheme"),
                     "a UAE national needs a GPSSA or ADPF pension scheme; a GCC national needs a GCC country.")

    salary = contribution_salary(facts)
    if min_key:
        minimum = P.amount(rate_map, min_key)
        if salary < minimum:
            raise _block(E.PENSION_SALARY_BELOW_MINIMUM,
                         f"pension contribution salary AED {salary} is below the scheme minimum AED {minimum} "
                         "(ZP-AE-ENG-001 §6); correct the authority salary before running payroll.")
    maximum = P.amount(rate_map, max_key) if not scheme.startswith("GCC_") else P.optional_amount(rate_map, max_key)
    used = min(salary, maximum) if maximum is not None else salary

    employee_rate = P.pct(rate_map, rate_key, "employee")
    employer_rate = P.pct(rate_map, rate_key, "employer")
    employee = _round2(used * employee_rate)
    employer_gross = _round2(used * employer_rate)

    support = _ZERO
    support_rate = None
    eligible = (facts.get("government_support_eligible") or "").upper() == "YES"
    if support_key and eligible:
        within_limit = True
        if limit_key:
            within_limit = used < P.amount(rate_map, limit_key)
        if within_limit:
            support_rate = P.pct(rate_map, support_key, "employer")
            support = min(_round2(used * support_rate), employer_gross)

    return {
        "scheme": scheme, "contribution_salary": salary, "salary_used": used, "employee": employee,
        "employer_gross": employer_gross, "government_support": support,
        "employer_cash": _round2(employer_gross - support),
        "rates": {"employee": employee_rate, "employer": employer_rate, "support": support_rate,
                  "salary_max": maximum},
    }
