"""
engine/countries/netherlands.py
--------------------------------
Netherlands payroll calculator (ZP-NL-ENG-001 v1.0). Pure: no ORM, no
framework — everything it reads arrives on the PayrollContext, resolved by
netherlands_service.resolve_nl_calc_inputs (the nl_* fields in engine/base.py).

Order of calculation for one pay period:
  1. Classify every non-zero earning on its seven independent axes (NL-047);
     an unclassified earning BLOCKS.
  2. Taxable benefits (company-car addition, NL-024/025) and the expat
     facility (NL-026..028) adjust the wage bases — never cash.
  3. Pension (scheme-owned, NL-043): employee share reduces the wage bases.
  4. Wage tax from the ACTIVE official table rows (NL-005..010): period table,
     special-remuneration table, or the anonymous rate (NL-008); voluntary
     extra withholding only adds.
  5. Employee insurance on the VCR increment (NL-012..018): AWf (class from
     contract facts), Aof (employer size), Wko, Whk (employer decision).
  6. Zvw on its own VCR series for the employment's path (NL-019..021).
  7. Net pay and employer cost kept apart (NL-035/NL-048).
  8. Labour checks: hourly minimum wage (NL-041), sickness-pay floor (NL-042),
     vacation-allowance accrual (NL-009), WKR contribution (NL-022/023).

Missing statutory data raises NetherlandsCalculationBlockedError (the payslip
fails closed). Compliance findings that an operator must resolve are returned
as `exceptions` with severity BLOCK/WARN — a BLOCK stops run approval
(netherlands_service.nl_run_preflight), never the preview.

The result is one `nl_result` dict (no flat `nl_*` fields: "NL" is also
Canada's Newfoundland and Labrador, whose PayrollResult fields start nl_).
`nl_result["inputs"]` is the frozen calculation context that corrections
replay without any live lookup (NL-004/NL-045).
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .shared import MissingComplianceConfigurationError
from ..jurisdictions.netherlands import company_car, expat, minimum_wage, pension, sickness_pay
from ..jurisdictions.netherlands import vacation_allowance, wkr
from ..jurisdictions.netherlands.premiums import (
    AwfContractFacts, EmployerPremiumDecision, PremiumConfigurationError,
    calculate_aof, calculate_awf, calculate_whk, calculate_wko, get_rates_from_pack, _rate_value,
)
from ..jurisdictions.netherlands.vcr import (
    VcrError, VcrFamily, VcrInput, advance as vcr_advance, round_currency, state_from_dict,
)
from ..jurisdictions.netherlands.wage_tax import NLBlock as _WageTaxBlock, calculate_wage_tax
from ..jurisdictions.netherlands.zvw import ZvwPathError, calculate_zvw_period, get_zvw_rates_from_pack, normalise_path

_COUNTRY = "NL"
ZERO = Decimal("0.00")
ENGINE_VERSION = "NL-ENGINE-2026.1"
NL_PERIOD_MAX_RULE = "NL_PERIOD_MAX"


class NLError(Exception):
    """Netherlands calculation error that is not a statutory block (e.g. the
    simple calculation mode, which can never run Dutch payroll)."""

    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(f"{code}: {message}" if message else code)


class NetherlandsCalculationBlockedError(MissingComplianceConfigurationError):
    """A Dutch statutory calculation that must not proceed — missing pack row,
    missing worker/employer fact, or a case not certified in this release."""

    def __init__(self, key: str, reason: str, organization_id: int = None):
        super().__init__(key, _COUNTRY, organization_id)
        self.reason = reason
        self.args = (f"Netherlands calculation blocked ({key}): {reason}",)


NLBlock = NetherlandsCalculationBlockedError


# ── Periods ────────────────────────────────────────────────────────────────
# Platform pay frequency -> (content period code, periods/year, wage-tax PeriodCode).
# Daily payroll is not certified (the daily-table day count is not in the spec);
# bi-weekly / semi-monthly are not Dutch table periods at all.
_PERIODS = {
    "WEEKLY": ("WEEKLY", 52, "WEEK"),
    "FOUR_WEEKLY": ("FOUR_WEEKLY", 13, "FOUR_WEEK"),
    "MONTHLY": ("MONTHLY", 12, "MONTHLY"),
    "QUARTERLY": ("QUARTERLY", 4, "QUARTER"),
    "ANNUAL": ("ANNUAL", 1, "YEAR"),
}
_FREQUENCY_ALIASES = {
    "MONTHLY": "MONTHLY", "MONTH": "MONTHLY",
    "WEEKLY": "WEEKLY", "WEEK": "WEEKLY",
    "FOUR_WEEKLY": "FOUR_WEEKLY", "FOUR-WEEKLY": "FOUR_WEEKLY", "4-WEEKLY": "FOUR_WEEKLY",
    "4WEEKLY": "FOUR_WEEKLY", "FOURWEEKLY": "FOUR_WEEKLY", "FOUR WEEKLY": "FOUR_WEEKLY", "FOUR_WEEK": "FOUR_WEEKLY",
    "QUARTERLY": "QUARTERLY", "QUARTER": "QUARTERLY",
    "ANNUAL": "ANNUAL", "ANNUALLY": "ANNUAL", "YEARLY": "ANNUAL", "YEAR": "ANNUAL",
}


def normalise_period(frequency: Optional[str]) -> tuple:
    key = _FREQUENCY_ALIASES.get((frequency or "").strip().upper())
    if key is None:
        raise NLBlock("nl_payroll_period", f"pay frequency {frequency!r} is not a Dutch wage-tax table period "
                                           "(weekly, four-weekly, monthly, quarterly or annual)")
    return _PERIODS[key]


# ── Small helpers ──────────────────────────────────────────────────────────

def _d(value) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _q(value) -> Decimal:
    return _d(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _s(value) -> Optional[str]:
    return None if value is None else str(value)


def _jsonable(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _sha(payload) -> str:
    return hashlib.sha256(json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _profile_fact(profile, name):
    if profile is None:
        return None
    return profile.get(name) if isinstance(profile, Mapping) else getattr(profile, name, None)


def earnings_from_ctx(ctx) -> Dict[str, Decimal]:
    """The payslip's cash components as earning codes (same codes as CH)."""
    earnings = {"base_salary": ctx.basic, "hra": ctx.hra, "special_allowance": ctx.special_allowance,
                "overtime": ctx.overtime, "additional_compensation": ctx.additional_compensation}
    return {k: _d(v) for k, v in earnings.items()}


def _slab_rows(slabs: Iterable[Any], rule_type: str) -> List[Any]:
    return [s for s in slabs or () if getattr(s, "rule_type", None) == rule_type]


def _period_max(slabs, period_code: str, on: date) -> Decimal:
    for row in _slab_rows(slabs, NL_PERIOD_MAX_RULE):
        eff_from, eff_to = getattr(row, "effective_from", None), getattr(row, "effective_to", None)
        if row.filing_status == period_code and (eff_from is None or eff_from <= on) and (eff_to is None or eff_to >= on):
            if row.flat_amount is not None:
                return _d(row.flat_amount)
    raise NLBlock("nl_period_max", f"no NL_PERIOD_MAX row for {period_code} on {on} in the active pack — the VCR "
                                   "time-period maximum is required (spec §5 states only the annual and monthly figures)")


def _rate(rate_map, key: str, *, required: bool = True) -> Optional[Decimal]:
    value = _rate_value(rate_map.get(key))
    if value is None:
        entry = rate_map.get(key)
        if entry is not None and getattr(entry, "flat_amount", None) is not None:
            value = _d(entry.flat_amount)
    if value is None and required:
        raise NLBlock(key, f"{key} is not configured in the active NL pack")
    return value


def _amount(rate_map, key: str) -> Optional[Decimal]:
    entry = rate_map.get(key)
    if entry is None:
        return None
    if getattr(entry, "flat_amount", None) is not None:
        return _d(entry.flat_amount)
    if isinstance(entry, (int, float, str, Decimal)):
        return _d(entry)
    return None


def _text(rate_map, key: str) -> Optional[str]:
    entry = rate_map.get(key)
    if entry is None:
        return None
    return getattr(entry, "text_value", None) if not isinstance(entry, str) else entry


def _exception(code: str, severity: str, message: str, **detail) -> dict:
    return {"code": code, "severity": severity, "message": message, **({"detail": _jsonable(detail)} if detail else {})}


# ── Calculation ────────────────────────────────────────────────────────────

def calculate(ctx) -> dict:
    if (getattr(ctx, "country", "") or "").upper() != _COUNTRY:
        return {}
    org_id = getattr(ctx, "nl_organization_id", None)

    def block(key, reason):
        return NLBlock(key, reason, org_id)

    pay_date = getattr(ctx, "pay_date", None)
    if pay_date is None:
        raise block("pay_date", "the pay date is required for Dutch payroll")
    profile = getattr(ctx, "nl_statutory_profile", None)
    if profile is None:
        raise block("nl_statutory_profile", "employee has no Netherlands statutory profile in force on the pay date")
    dob = getattr(ctx, "date_of_birth", None)
    if dob is None:
        raise block("date_of_birth", "date of birth is required (AOW cohort, minimum-wage age)")
    if (_profile_fact(profile, "nl_cross_border_status") or "NONE").upper() not in ("NONE", "SUPPORTED"):
        raise block("nl_cross_border_status", "unsupported cross-border / A1 case — live payroll is blocked (spec §11)")

    period_code, periods_per_year, table_period = normalise_period(
        getattr(ctx, "nl_payroll_period", None) or getattr(ctx, "pay_frequency", None))
    rate_map = getattr(ctx, "rate_map", None) or {}
    slabs = getattr(ctx, "slabs", None) or []
    exceptions: List[dict] = []
    trace: List[dict] = []

    # 1. Earnings + classification (NL-047) ─────────────────────────────────
    earnings = {k: _d(v) for k, v in (getattr(ctx, "nl_earnings", None) or earnings_from_ctx(ctx)).items()}
    classifications = getattr(ctx, "nl_earning_classifications", None) or {}
    unclassified = sorted(code for code, amount in earnings.items() if amount != 0 and code not in classifications)
    if unclassified:
        raise block("nl_earning_classification",
                    f"earning code(s) without an ACTIVE NL classification: {', '.join(unclassified)} (NL-047)")

    def total(axis: str, *, special: Optional[bool] = None) -> Decimal:
        out = Decimal("0")
        for code, amount in earnings.items():
            cls = classifications.get(code) or {}
            if not cls.get(axis):
                continue
            if special is not None and (cls.get("remuneration_type") == "SPECIAL") != special:
                continue
            out += amount
        return out

    cash_regular = total("wage_tax", special=False)
    cash_special = total("wage_tax", special=True)
    ei_earnings = total("employee_insurance_wage")
    zvw_earnings = total("zvw_wage")
    pensionable = total("pensionable")

    # 2a. Company-car addition (benefit in kind) ─────────────────────────────
    cars = []
    for car in getattr(ctx, "nl_company_cars", None) or []:
        try:
            cars.append(company_car.period_addition(car, slabs=slabs, periods_per_year=periods_per_year))
        except company_car.CompanyCarError as exc:
            raise block("nl_company_car", str(exc))
    car_addition = sum((c.period_addition for c in cars), ZERO)

    # 2b. Expat facility (NL-026..028) ────────────────────────────────────────
    expat_params = {k: _amount(rate_map, k) for k in (
        "nl_expat_salary_threshold", "nl_expat_salary_threshold_young_master", "nl_expat_allowance_cap", "nl_wnt_cap")}
    expat_params["nl_expat_max_facility_pct"] = _rate(rate_map, "nl_expat_max_facility_pct", required=False)
    try:
        expat_result = expat.apply(getattr(ctx, "nl_expat_decision", None), package=cash_regular, on=pay_date,
                                   periods_per_year=periods_per_year, params=expat_params)
    except expat.ExpatError as exc:
        raise block("nl_expat", str(exc))
    if expat_result.risk:
        exceptions.append(_exception("EXPAT_THRESHOLD_RISK", "WARN", expat_result.risk))
    expat_allowance = expat_result.allowance

    # 3. Pension (NL-043) ─────────────────────────────────────────────────────
    try:
        pension_result = pension.contributions(getattr(ctx, "nl_pension_scheme", None),
                                               pensionable_earnings=pensionable, periods_per_year=periods_per_year)
    except pension.PensionError as exc:
        raise block("nl_pension", str(exc))
    pension_ee = pension_result.employee if pension_result else ZERO
    pension_er = pension_result.employer if pension_result else ZERO

    # Employee pension contributions and the tax-free expat allowance are not
    # wage for wage tax, employee insurance or Zvw; the car addition is wage
    # for wage tax and Zvw but not for the employee insurances. (G1/G2 review.)
    table_wage = _q(cash_regular + car_addition - expat_allowance - pension_ee)
    ei_base_period = _q(ei_earnings - expat_allowance - pension_ee)
    zvw_base_period = _q(zvw_earnings + car_addition - expat_allowance - pension_ee)
    trace.append({"code": "BASES", "tableWage": str(table_wage), "specialWage": str(_q(cash_special)),
                  "eiWage": str(ei_base_period), "zvwWage": str(zvw_base_period),
                  "carAddition": str(car_addition), "expatAllowance": str(expat_allowance),
                  "pensionEmployee": str(pension_ee)})

    # 4. Wage tax (NL-005..010) ───────────────────────────────────────────────
    anonymous = bool(getattr(ctx, "nl_anonymous", False))
    instruction = getattr(ctx, "nl_with_tax_credit", None)  # None = no signed instruction in force
    wage_tax_table = getattr(ctx, "nl_wage_tax_table", None) or {}
    special_table = getattr(ctx, "nl_special_tax_table", None) or {}
    # select_table_key reads these from ctx; mirror the profile facts onto it.
    for attr, value in (("payroll_period_code", table_period),
                        ("nl_table_color", _profile_fact(profile, "nl_table_color")),
                        ("nl_residence_variant", _profile_fact(profile, "nl_residence_variant") or "NL"),
                        ("nl_with_tax_credit", bool(instruction))):
        setattr(ctx, attr, value)
    extra = _d(_profile_fact(profile, "nl_voluntary_extra_withholding"))
    wage_tax_lines = []
    try:
        if anonymous:
            regular = calculate_wage_tax(ctx, _q(table_wage + cash_special), anonymous=True,
                                         anonymous_rate_pct=_rate(rate_map, "nl_anonymous_rate_pct"),
                                         voluntary_extra_amount=extra or None)
            wage_tax_lines.append(regular)
            exceptions.append(_exception("ANONYMOUS_RATE", "WARN",
                                         "anonymous-person rate applied — obtain and verify the BSN (NL-008)"))
        else:
            if not wage_tax_table.get("rows"):
                raise block("nl_wage_tax_table", "no ACTIVE official wage-tax table for this employee's table key "
                                                 "(import and activate the Belastingdienst file — gate G1)")
            regular = calculate_wage_tax(ctx, table_wage, rows=wage_tax_table["rows"],
                                         voluntary_extra_amount=extra or None)
            wage_tax_lines.append(regular)
            if cash_special:
                reference = getattr(ctx, "nl_reference_annual_wage", None)
                if reference is None:
                    raise block("nl_reference_annual_wage",
                                "special remuneration needs the reference annual wage (NL-010)")
                if not special_table.get("rows"):
                    raise block("nl_special_tax_table", "no ACTIVE special-remuneration table (gate G1)")
                wage_tax_lines.append(calculate_wage_tax(ctx, _q(cash_special), special_remuneration=True,
                                                         rows=special_table["rows"],
                                                         reference_annual_wage=_d(reference)))
    except _WageTaxBlock as exc:
        raise block("nl_wage_tax", str(exc))
    wage_tax = _q(sum((r.withholding_amount for r in wage_tax_lines), ZERO))
    if not anonymous and instruction is None:
        exceptions.append(_exception("NO_TAX_CREDIT_INSTRUCTION", "WARN",
                                     "no signed loonheffingskorting instruction in force — table applied without the "
                                     "payroll-tax credit (NL-031)"))

    # 5. Employee insurance on the EI VCR series (NL-012..018) ───────────────
    vcr_before = getattr(ctx, "nl_vcr_before", None)
    if vcr_before is None:
        raise block("nl_vcr_before", "the committed VCR state before this period was not resolved (NL-012)")
    period_max = _period_max(slabs, period_code, pay_date)
    vcr_after: Dict[str, dict] = {}
    vcr_increments: Dict[str, str] = {}
    ei_insured = _profile_fact(profile, "nl_ei_insured")
    premiums_er = {"awf": ZERO, "aof": ZERO, "wko": ZERO, "whk": ZERO}
    whk_employee = ZERO
    awf_class = None
    contract = getattr(ctx, "nl_contract", None)
    decision = getattr(ctx, "nl_premium_decision", None)
    if ei_insured is None:
        raise block("nl_ei_insured", "employee-insurance coverage is not recorded on the NL profile")
    if ei_insured:
        if contract is None:
            raise block("nl_contract", "no contract version in force — the AWf class is derived from contract facts (NL-015)")
        if decision is None:
            raise block("nl_premium_decision", "no ACTIVE employer premium decision (Aof size class, Whk rates) for this year (NL-017)")
        try:
            rates = get_rates_from_pack(rate_map)
        except PremiumConfigurationError as exc:
            raise block("nl_premium_rates", str(exc))
        facts = AwfContractFacts(
            is_permanent=contract.get("contract_term") == "INDEFINITE", fixed_term_months=None,
            has_written_contract=bool(contract.get("written_record")),
            is_on_call_no_guaranteed_hours=bool(contract.get("on_call")), is_standby_contract=False,
            statutory_exception_code=contract.get("statutory_exception_code"))
        # NL-016: an applied statutory revision (e.g. the contract ended within
        # its revision window) charges the HIGH rate retroactively, whatever
        # the contract facts would otherwise give.
        revision_trigger = contract.get("awf_revision_trigger")
        awf_class = "HIGH" if revision_trigger else ("LOW" if facts.qualifies_for_low_rate() else "HIGH")
        if revision_trigger:
            facts = AwfContractFacts(is_permanent=False, fixed_term_months=None, has_written_contract=False,
                                     is_on_call_no_guaranteed_hours=False, is_standby_contract=False)
        emp_decision = EmployerPremiumDecision(
            aof_size_class=decision.get("aof_size_class"),
            whk_wga_pct=None if decision.get("whk_wga_pct") is None else _d(decision["whk_wga_pct"]),
            whk_wga_employee_recoverable_pct=None if decision.get("whk_wga_employee_recoverable_pct") is None
            else _d(decision["whk_wga_employee_recoverable_pct"]),
            whk_zw_flex_pct=None if decision.get("whk_zw_flex_pct") is None else _d(decision["whk_zw_flex_pct"]))
        ei = vcr_advance(state_from_dict(vcr_before.get(VcrFamily.EI)), VcrInput(ei_base_period, period_max))
        try:
            awf = calculate_awf(ei, facts, rates)
            aof = calculate_aof(ei, emp_decision, rates)
            wko = calculate_wko(ei, rates)
            whk = calculate_whk(ei, emp_decision)
        except ValueError as exc:
            raise block("nl_employee_insurance", str(exc))
        premiums_er = {"awf": awf.amount, "aof": aof.amount, "wko": wko.amount, "whk": whk.employer_total}
        whk_employee = whk.employee_recoverable
        vcr_after[VcrFamily.EI] = ei.new_state.as_dict()
        vcr_increments[VcrFamily.EI] = str(ei.base_increment)
        if ei.base_increment < 0:
            exceptions.append(_exception("VCR_NEGATIVE_INCREMENT", "WARN",
                                         "negative employee-insurance base increment (negative wage or correction)"))
        for line in (awf, aof, wko):
            trace.append({"code": line.premium.upper(), "base": str(line.base_increment), "rate": str(line.rate_pct),
                          "amount": str(line.amount), "side": "EMPLOYER"})
        trace.append({"code": "WHK", "base": str(ei.base_increment), "amount": str(whk.employer_total),
                      "employeeRecoverable": str(whk.employee_recoverable), "side": "EMPLOYER"})
        trace.append({"code": "AWF_CLASS", "value": awf_class,
                      "reason": (f"AWf revision ({revision_trigger}) — high rate applies retroactively (NL-016)"
                                 if revision_trigger else facts.low_rate_reason() or "low-rate conditions not met")})
    elif not _profile_fact(profile, "nl_insurance_exception_code"):
        raise block("nl_insurance_exception_code", "employee is not insured for the employee insurances but no exception code/evidence is recorded")

    # 6. Zvw on its own series (NL-019..021) ──────────────────────────────────
    try:
        zvw_path = normalise_path(_profile_fact(profile, "nl_zvw_path"))
        zvw_rates = get_zvw_rates_from_pack(rate_map)
    except (ZvwPathError, PremiumConfigurationError) as exc:
        raise block("nl_zvw", str(exc))
    zvw_family = VcrFamily.ZVW_LEVY if zvw_path == "EMPLOYER_LEVY" else VcrFamily.ZVW_CONTRIB
    zvw_step = vcr_advance(state_from_dict(vcr_before.get(zvw_family)), VcrInput(zvw_base_period, period_max))
    zvw = calculate_zvw_period(zvw_path, zvw_step, zvw_rates)
    vcr_after[zvw_family] = zvw_step.new_state.as_dict()
    vcr_increments[zvw_family] = str(zvw_step.base_increment)
    trace.append({"code": "ZVW", "path": zvw_path, "base": str(zvw.base_increment), "rate": str(zvw.rate_pct),
                  "amount": str(zvw.amount), "side": "EMPLOYER" if zvw_path == "EMPLOYER_LEVY" else "EMPLOYEE"})

    # 7. Net pay and employer cost (NL-035/NL-048) ────────────────────────────
    zvw_employee = zvw.employee_contribution
    nl_employee_total = _q(zvw_employee + whk_employee)
    net_pay = _q(_d(ctx.gross) - wage_tax - pension_ee - nl_employee_total)
    if net_pay < 0:
        exceptions.append(_exception("NEGATIVE_NET", "BLOCK", "deductions exceed gross pay"))
    employer_premiums = _q(sum(premiums_er.values(), ZERO) + zvw.employer_levy)
    employer_cost = _q(employer_premiums + pension_er)

    # 8. Labour checks ────────────────────────────────────────────────────────
    hours = getattr(ctx, "nl_period_hours", None)
    if hours is None:
        hours = minimum_wage.period_hours(_profile_fact(profile, "nl_contract_hours_per_week"), periods_per_year)
    reckonable = total("minimum_wage_reckonable")
    mw_result = None
    try:
        mw_result = minimum_wage.check(slabs=slabs, date_of_birth=dob, pay_date=pay_date,
                                       reckonable_wage=reckonable, hours=hours)
        if not mw_result.compliant:
            exceptions.append(_exception("MIN_WAGE_BREACH", "BLOCK",
                                         f"hourly wage {mw_result.actual_hourly} is below the statutory "
                                         f"{mw_result.required_hourly} ({mw_result.age_cohort}) (NL-041)",
                                         shortfall=mw_result.shortfall))
    except minimum_wage.MinimumWageError as exc:
        exceptions.append(_exception("MIN_WAGE_UNVERIFIED", "BLOCK", str(exc)))

    sickness = getattr(ctx, "nl_sickness", None)
    sickness_floor = None
    if sickness:
        try:
            sickness_floor = sickness_pay.floor(
                policy=sickness.get("policy") or {}, statutory_pct=_rate(rate_map, "nl_sick_pay_pct", required=False),
                first_sick_day=sickness["first_sick_day"] if isinstance(sickness["first_sick_day"], date)
                else date.fromisoformat(sickness["first_sick_day"]),
                on=pay_date, contractual_wage=_d(ctx.basic),
                min_wage_period=(mw_result.required_hourly * mw_result.hours) if mw_result else None)
        except (sickness_pay.SicknessPayError, KeyError, ValueError) as exc:
            exceptions.append(_exception("SICK_PAY_UNVERIFIED", "BLOCK", str(exc)))
        if sickness_floor and _d(ctx.gross) < sickness_floor.floor:
            exceptions.append(_exception("SICK_PAY_BELOW_FLOOR", "BLOCK",
                                         f"pay {ctx.gross} is below the sickness-pay floor {sickness_floor.floor} (NL-042)"))

    try:
        vac_pct = vacation_allowance.resolve_pct(_rate(rate_map, "nl_vacation_allowance_pct", required=False),
                                                 _profile_fact(profile, "nl_vacation_allowance_pct"))
    except vacation_allowance.VacationAllowanceError as exc:
        raise block("nl_vacation_allowance", str(exc))
    vac = vacation_allowance.accrue(
        basis_amount=vacation_allowance.basis(earnings, classifications), pct=vac_pct,
        prior_balance=_d(getattr(ctx, "nl_vacation_balance_before", None)),
        payout=earnings.get("vacation_allowance", ZERO))

    try:
        wkr_component = wkr.payslip_components({k: v for k, v in earnings.items() if v != 0}, classifications,
                                               fiscal_wage=_q(table_wage + cash_special))
    except wkr.WkrError as exc:
        raise block("nl_wkr", str(exc))

    # Frozen inputs: everything the calculation read, JSON-safe, so a
    # correction replays it exactly with no live pack/table lookup (NL-004).
    used_rate_keys = sorted(k for k in rate_map if str(k).startswith("nl_"))
    frozen = _jsonable({
        "engineVersion": ENGINE_VERSION,
        "payDate": pay_date, "periodStart": getattr(ctx, "period_start", None), "periodEnd": getattr(ctx, "period_end", None),
        "periodCode": period_code, "periodsPerYear": periods_per_year, "payFrequency": getattr(ctx, "pay_frequency", None),
        "gross": _q(ctx.gross), "basic": _q(ctx.basic), "dateOfBirth": dob,
        "earnings": earnings, "classifications": classifications,
        "profile": {k: _profile_fact(profile, k) for k in (
            "nl_table_color", "nl_residence_variant", "nl_zvw_path", "nl_ei_insured", "nl_insurance_exception_code",
            "nl_cross_border_status", "nl_voluntary_extra_withholding", "nl_vacation_allowance_pct",
            "nl_contract_hours_per_week")},
        "withTaxCredit": instruction,
        "taxCreditInstructionId": getattr(ctx, "nl_tax_credit_instruction_id", None),
        "anonymous": anonymous,
        "wageTaxTable": {k: wage_tax_table.get(k) for k in ("fileId", "fileSha256", "tableKey")},
        "specialTaxTable": {k: special_table.get(k) for k in ("fileId", "fileSha256", "tableKey")} if special_table else None,
        "referenceAnnualWage": getattr(ctx, "nl_reference_annual_wage", None),
        "contract": contract, "premiumDecision": decision, "vcrBefore": vcr_before,
        "companyCars": getattr(ctx, "nl_company_cars", None) or [],
        "expatDecision": getattr(ctx, "nl_expat_decision", None),
        "pensionScheme": getattr(ctx, "nl_pension_scheme", None),
        "sickness": sickness, "periodHours": hours,
        "vacationBalanceBefore": getattr(ctx, "nl_vacation_balance_before", None),
        "rates": {k: {"employee": _s(getattr(rate_map[k], "employee_rate_pct", None)),
                      "employer": _s(getattr(rate_map[k], "employer_rate_pct", None)),
                      "amount": _s(getattr(rate_map[k], "flat_amount", None)),
                      "text": getattr(rate_map[k], "text_value", None)}
                  if not isinstance(rate_map[k], (str, int, float, Decimal)) else {"value": str(rate_map[k])}
                  for k in used_rate_keys},
        "slabs": [{"ruleType": s.rule_type, "key": s.filing_status, "min": _s(getattr(s, "min_amount", None)),
                   "max": _s(getattr(s, "max_amount", None)), "rate": _s(getattr(s, "rate_pct", None)),
                   "amount": _s(getattr(s, "flat_amount", None)), "from": getattr(s, "effective_from", None),
                   "to": getattr(s, "effective_to", None)}
                  for s in slabs if str(getattr(s, "rule_type", "")).startswith("NL_")],
    })

    nl_result = {
        "status": "BLOCKED_EXCEPTIONS" if any(e["severity"] == "BLOCK" for e in exceptions) else "OK",
        "engineVersion": ENGINE_VERSION,
        "periodCode": period_code,
        "gross": str(_q(ctx.gross)),
        "wageTax": {"total": str(wage_tax), "lines": [r.as_dict() for r in wage_tax_lines],
                    "withTaxCredit": bool(instruction) and not anonymous, "anonymous": anonymous},
        "employeeInsurance": {"insured": bool(ei_insured), "awfClass": awf_class,
                              **{k: str(v) for k, v in premiums_er.items()},
                              "whkEmployeeRecoverable": str(whk_employee)},
        "zvw": {"path": zvw_path, "employerLevy": str(zvw.employer_levy),
                "employeeContribution": str(zvw_employee), "rate": str(zvw.rate_pct)},
        "pension": pension_result.as_dict() if pension_result else None,
        "companyCars": [c.as_dict() for c in cars],
        "expat": expat_result.as_dict(),
        "minimumWage": mw_result.as_dict() if mw_result else None,
        "sicknessFloor": sickness_floor.as_dict() if sickness_floor else None,
        "vacationAllowance": vac.as_dict(),
        "wkr": wkr_component,
        "vcr": {"periodMax": str(period_max), "before": _jsonable(vcr_before), "after": vcr_after,
                "increments": vcr_increments},
        "totals": {"gross": str(_q(ctx.gross)), "wageTax": str(wage_tax), "pensionEmployee": str(pension_ee),
                   "zvwEmployee": str(zvw_employee), "whkEmployee": str(whk_employee),
                   "employeeDeductions": str(_q(wage_tax + pension_ee + nl_employee_total)),
                   "netPay": str(net_pay), "employerPremiums": str(employer_premiums),
                   "pensionEmployer": str(pension_er), "employerCost": str(employer_cost)},
        "exceptions": exceptions,
        "trace": trace,
        "inputs": frozen,
        "inputHash": _sha(frozen),
    }
    return {
        "tds": wage_tax,
        "employee_pension": pension_ee,
        "employer_pension": pension_er,
        "employer_social_security": employer_premiums,
        "nl_employee_total": nl_employee_total,
        "nl_result": nl_result,
    }


__all__ = ["calculate", "NLError", "NLBlock", "NetherlandsCalculationBlockedError", "normalise_period",
           "earnings_from_ctx", "ENGINE_VERSION"]
