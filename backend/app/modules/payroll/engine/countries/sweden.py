"""
modules/payroll/engine/countries/sweden.py
-------------------------------------------
Sweden (ZP-SE-ENG-001, Priority Market #24) — applicability-first payroll
calculation on the shared engine. One file per country, same doctrine as
ireland.py/singapore.py/france.py.

Statutory scope implemented here (spec §3/§5/§6/§9):
  * Employer contributions (arbetsgivaravgifter): component-level rates
    summed to the standard rate, with the birth-year cohorts (full /
    10.21% pension-only / 0%) and the temporary youth reduction (payment-
    date windowed, monthly SEK threshold, above-threshold excess at the
    full rate) — never one hardcoded percentage (spec §3, SE-005).
  * Preliminary tax withholding (spec §5): four DISTINCT strategies —
    tax table/column authority lookup, 30% supplementary income, one-time
    payment table, SINK — plus a Skatteverket decision override that
    wins within its own dates. Never blended; cash-limit rule honoured.
  * Special payroll tax on pension costs (SLP, 24.26%) from a separate
    employer pension-cost base (SE-007) — never a % of employee gross.
  * Occupational pension/insurance employee+employer shares ONLY when the
    worker's profile carries a configured plan share (spec §1 gate).

Fail-closed doctrine: Sweden is in shared._VALIDATION_ENABLED_COUNTRIES
from day one (zero pre-existing SE orgs, exactly Singapore's situation),
and this module defines NO hardcoded statutory fallback — every rate comes
from the configured row via require_pct/require_amount, and every missing
worker fact (payment date, birth date, tax status/role, table/column,
SINK status, decision value) raises SwedenCalculationBlockedError, a
MissingComplianceConfigurationError subclass, so the existing MISSING_
COMPLIANCE_CONFIGURATION 400 handler applies unchanged.

Tax-table content strategy (spec §5): SE_TAX_TABLE / SE_ONE_TIME_PAYMENT
TaxSlab rows are AUTHORITY LOOKUP rows, stored in the unit Skatteverket
publishes them in — never converted:
  * SE_TAX_TABLE: min_amount/max_amount is the MONTHLY taxable-pay band of
    the monthly table, and the band states either a monthly withholding
    AMOUNT (assessment_basis "AMOUNT", flat_amount) or — for the top
    incomes, where the authority table itself publishes a percentage — an
    authority PERCENTAGE (assessment_basis "PERCENT", rate_pct). The first
    release supports monthly payroll only (spec §1), so a non-monthly pay
    frequency blocks rather than rescaling a monthly table.
  * SE_ONE_TIME_PAYMENT: min_amount/max_amount is the worker's expected
    ANNUAL income band and rate_pct the authority percentage withheld from
    the one-time amount (spec §3 "by applicable column and annual income
    band"); the annual income input is the worker fact se_annual_income,
    retained in the trace.
The engine never derives a percentage from an amount band, never
interpolates between bands and never infers municipal tax from a rate
(spec §3: never one national percentage). Percent-type ContributionRate
values are PERCENT numbers (31.42 = 31.42%), France's convention.

Content catalog: SE_PARAMETER_KEYS is the single backend catalog of every
seedable Sweden parameter, parity-tested against the frontend's
config/jurisdictions/seComponentConfig.js (tests/test_sweden_statutory_
catalog.py). Fallback-registry entries (engine/fallback_registry.py)
declare which of them are REQUIRED for a readiness check; the _SE_*
constants below exist solely so the registry can read them live and are
deliberately None — no fallback, ever.
"""

from datetime import date
from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import (
    MissingComplianceConfigurationError,
    resolve_periods_per_year,
)

_COUNTRY = "SE"
ZERO = Decimal("0")
HUNDRED = Decimal("100")

# Temporary youth reduction window (spec §3 [S1], spec §6): payment dates
# 1 Apr 2026 – 30 Sep 2027 only. The engine enforces this from the ROW's
# own effective_from/effective_to (row presence alone is not enough —
# SE-005 makes payment date a first-class key), independent of which
# resolution path supplied the row.
YOUTH_WINDOW_FROM = date(2026, 4, 1)
YOUTH_WINDOW_TO = date(2027, 9, 30)

# Youth cohort age bounds at 1 Jan of the income year (19–23 inclusive;
# 2026 ⇒ born 2003–2007, spec §3). Rule-shape constants like Ireland's
# NMW age bands — the RATE for this rule is content (se_youth_reduced),
# never a code constant.
YOUTH_MIN_AGE = 19
YOUTH_MAX_AGE = 23

# The seven statutory components whose sum is the standard employer
# contribution (spec §3 "Store component rates and total"). Values are
# seeded Draft content; the engine only ever sums what is configured.
SE_ER_COMPONENT_KEYS = (
    "se_er_age_pension",
    "se_er_health_insurance",
    "se_er_parental_insurance",
    "se_er_labour_market",
    "se_er_work_injury",
    "se_er_survivor_pension",
    "se_er_general_payroll_tax",
)

# TaxSlab.rule_type discriminators for the two Sweden table families
# (models.TaxSlab, migration e8f1a2b3c4d5).
SE_TAX_TABLE_RULE = "SE_TAX_TABLE"
SE_ONE_TIME_PAYMENT_RULE = "SE_ONE_TIME_PAYMENT"

# The one backend catalog of seedable Sweden parameters — each key is a
# ContributionRate.component_key. Parity-tested against the frontend's
# seComponentConfig.js. Kind: employer_pct | employee_pct | amount.
SE_PARAMETER_KEYS = {
    "se_er_age_pension": "employer_pct",
    "se_er_health_insurance": "employer_pct",
    "se_er_parental_insurance": "employer_pct",
    "se_er_labour_market": "employer_pct",
    "se_er_work_injury": "employer_pct",
    "se_er_survivor_pension": "employer_pct",
    "se_er_general_payroll_tax": "employer_pct",
    "se_youth_reduced": "employer_pct",
    "se_sink": "employee_pct",
    "se_supplementary_rate": "employee_pct",
    "se_slp": "employer_pct",
    "se_youth_monthly_threshold": "amount",
    "se_older_cohort_max_birth_year": "amount",
    "se_zero_cohort_max_birth_year": "amount",
    "se_vacation_percentage": "amount",
    "se_sick_qualifying_deduction_pct": "amount",
}

# ── Fallback-registry constants (engine/fallback_registry.py) ─────────────
# Each names the resolver key its registry entry declares REQUIRED. Value
# is always None: Sweden has no engine fallback by design (spec §30), so
# the readiness check, not a default, is what keeps payroll honest.
_SE_ER_AGE_PENSION = None
_SE_ER_HEALTH_INSURANCE = None
_SE_ER_PARENTAL_INSURANCE = None
_SE_ER_LABOUR_MARKET = None
_SE_ER_WORK_INJURY = None
_SE_ER_SURVIVOR_PENSION = None
_SE_ER_GENERAL_PAYROLL_TAX = None
_SE_YOUTH_REDUCED = None
_SE_SINK = None
_SE_SUPPLEMENTARY_RATE = None
_SE_SLP = None
_SE_YOUTH_MONTHLY_THRESHOLD = None
_SE_OLDER_COHORT_MAX_BIRTH_YEAR = None
_SE_ZERO_COHORT_MAX_BIRTH_YEAR = None


class SwedenCalculationBlockedError(MissingComplianceConfigurationError):
    """A Sweden statutory calculation that must not proceed — missing
    configured row, missing/contradictory worker fact, or an unsupported
    case (spec §5 failure cases). Subclasses MissingComplianceConfiguration
    so the existing main.py handler returns the same
    MISSING_COMPLIANCE_CONFIGURATION 400 every other fail-closed
    jurisdiction uses (same pattern as SingaporeCalculationBlockedError)."""

    def __init__(self, key: str, reason: str, organization_id: int = None):
        super().__init__(key, _COUNTRY, organization_id)
        self.reason = reason
        self.args = (f"Sweden calculation blocked ({key}): {reason}",)


def _dec(value) -> Decimal:
    if value is None or value == "":
        return ZERO
    return Decimal(str(value))


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ("true", "1", "yes", "y")


def _age_at_year_start(date_of_birth: date, income_year: int) -> int:
    return income_year - date_of_birth.year


class _Pack:
    """Typed, fail-closed reader over ctx.rate_map — Ireland's _Pack with
    Sweden's semantics: a configured row is the ONLY source of a value,
    and a missing row blocks (never a default, spec §30)."""

    def __init__(self, rate_map: dict, organization_id):
        self.rate_map = rate_map or {}
        self.organization_id = organization_id

    def row(self, key: str):
        return self.rate_map.get(key)

    def require_pct(self, key: str, side: str) -> Decimal:
        row = self.rate_map.get(key)
        if row is None:
            raise SwedenCalculationBlockedError(
                key, "no configured contribution-rate row", self.organization_id)
        value = getattr(row, f"{side}_rate_pct", None)
        if value is None:
            raise SwedenCalculationBlockedError(
                key, f"row has no {side} rate percentage configured", self.organization_id)
        return Decimal(str(value))

    def require_amount(self, key: str) -> Decimal:
        row = self.rate_map.get(key)
        if row is None:
            raise SwedenCalculationBlockedError(
                key, "no configured parameter row", self.organization_id)
        value = getattr(row, "flat_amount", None)
        if value is None:
            raise SwedenCalculationBlockedError(
                key, "row has no amount configured", self.organization_id)
        return Decimal(str(value))


def resolve_employer_contribution(
    ctx: PayrollContext, pack: _Pack, pay_date: date,
) -> dict:
    """spec §3/§6 — component rates, birth-year cohorts, payment-date
    windowed youth relief with the monthly SEK threshold allocator.

    Returns the employer-contribution slice of the result dict."""
    date_of_birth = ctx.date_of_birth
    if date_of_birth is None:
        raise SwedenCalculationBlockedError(
            "date_of_birth",
            "birth-year cohort decides the employer-contribution rate (spec §6)",
            pack.organization_id,
        )

    income_year = pay_date.year
    birth_year = date_of_birth.year

    component_rates = []
    for key in SE_ER_COMPONENT_KEYS:
        rate = pack.require_pct(key, side="employer")
        component_rates.append((key, rate))
    full_rate = sum((r for _, r in component_rates), ZERO)

    zero_max = pack.require_amount("se_zero_cohort_max_birth_year")
    older_max = pack.require_amount("se_older_cohort_max_birth_year")

    base = ctx.se_contribution_base if getattr(ctx, "se_contribution_base", None) is not None else ctx.gross
    base = _dec(base)

    components_trace = []
    youth_applied = False
    month_compensation = base

    if birth_year <= int(zero_max):
        # Persons born 1937 or earlier: 0% (spec §3 [S1]) — a genuine
        # statutory zero, not a missing-configuration zero.
        rate = ZERO
        cohort = "ZERO"
    elif birth_year <= int(older_max):
        # Born 1938–1958 (2026 income year): only the age pension
        # component remains, 10.21% (spec §3).
        rate = next(r for k, r in component_rates if k == "se_er_age_pension")
        cohort = "OLDER"
        components_trace = [
            {"key": "se_er_age_pension", "ratePct": str(rate),
             "amount": str(_round2(rate / HUNDRED * base))},
        ]
    else:
        rate = full_rate
        cohort = "STANDARD"
        youth_row = pack.row("se_youth_reduced")
        age_at_year_start = _age_at_year_start(date_of_birth, income_year)
        # Payment date decides the window (SE-005): the row's own
        # effective_from/effective_to, not mere presence.
        youth_window_hit = (
            youth_row is not None
            and (getattr(youth_row, "effective_from", None) is None or youth_row.effective_from <= pay_date)
            and (getattr(youth_row, "effective_to", None) is None or youth_row.effective_to >= pay_date)
        )
        if (youth_window_hit
                and YOUTH_MIN_AGE <= age_at_year_start <= YOUTH_MAX_AGE):
            youth_rate = pack.require_pct("se_youth_reduced", side="employer")
            threshold = pack.require_amount("se_youth_monthly_threshold")
            prior = _dec(getattr(ctx, "se_month_to_date_prior", None))
            month_compensation = prior + base
            remaining = threshold - prior
            if remaining < ZERO:
                remaining = ZERO
            reduced_base = base if base <= remaining else remaining
            excess_base = base - reduced_base
            amount = _round2(
                youth_rate / HUNDRED * reduced_base + full_rate / HUNDRED * excess_base)
            rate = youth_rate if base <= remaining else full_rate
            cohort = "YOUTH"
            youth_applied = True
            components_trace = [
                {"key": "se_youth_reduced", "ratePct": str(youth_rate),
                 "base": str(reduced_base), "amount": str(_round2(youth_rate / HUNDRED * reduced_base))},
                {"key": "standard_total", "ratePct": str(full_rate),
                 "base": str(excess_base), "amount": str(_round2(full_rate / HUNDRED * excess_base))},
            ]
            return {
                "se_employer_contribution": amount,
                "se_employer_contribution_rate": rate,
                "se_employer_contribution_cohort": cohort,
                "se_employer_contribution_components": components_trace,
                "se_youth_applied": youth_applied,
                "se_month_compensation": month_compensation,
                "se_employer_contribution_base": base,
            }
        components_trace = [
            {"key": k, "ratePct": str(r), "amount": str(_round2(r / HUNDRED * base))}
            for k, r in component_rates
        ]

    amount = _round2(rate / HUNDRED * base)
    return {
        "se_employer_contribution": amount,
        "se_employer_contribution_rate": rate,
        "se_employer_contribution_cohort": cohort,
        "se_employer_contribution_components": components_trace,
        "se_youth_applied": youth_applied,
        "se_month_compensation": month_compensation,
        "se_employer_contribution_base": base,
    }


def _lookup_authority_band(slabs, income: Decimal, table_key: str, organization_id):
    """spec §5 step 3/7 — pure authority-table lookup: the ONE band whose
    [min_amount, max_amount) covers `income`. Blocks when no band covers it
    (never interpolate) or when more than one does (overlapping content is
    a content defect, not something to pick from)."""
    candidates = []
    for row in slabs:
        minimum = _dec(getattr(row, "min_amount", None))
        maximum = getattr(row, "max_amount", None)
        if income < minimum:
            continue
        if maximum is not None and income >= _dec(maximum):
            continue
        candidates.append(row)
    if not candidates:
        raise SwedenCalculationBlockedError(
            table_key,
            f"income {income} falls outside every configured band",
            organization_id,
        )
    if len(candidates) > 1:
        raise SwedenCalculationBlockedError(
            table_key,
            f"income {income} matches {len(candidates)} overlapping bands — content defect",
            organization_id,
        )
    return candidates[0]


def _band_withholding(row, income: Decimal, table_key: str, organization_id) -> Decimal:
    """The statutory withholding a monthly SE_TAX_TABLE band states, in the
    band's OWN declared basis: AMOUNT → flat_amount as published; PERCENT →
    the authority's published percentage of the period income. A band with
    no declared basis or no value blocks (Draft scaffolds stay inert)."""
    basis = (getattr(row, "assessment_basis", None) or "").strip().upper()
    if basis == "AMOUNT":
        amount = getattr(row, "flat_amount", None)
        if amount is None:
            raise SwedenCalculationBlockedError(
                table_key, "configured band has no statutory withholding amount", organization_id)
        return Decimal(str(amount))
    if basis == "PERCENT":
        rate = getattr(row, "rate_pct", None)
        if rate is None or Decimal(str(rate)) <= ZERO:
            raise SwedenCalculationBlockedError(
                table_key, "percentage band has no authority percentage", organization_id)
        return Decimal(str(rate)) / HUNDRED * income
    raise SwedenCalculationBlockedError(
        table_key,
        "configured band declares no AMOUNT/PERCENT basis (unfilled Draft scaffold)",
        organization_id,
    )


def resolve_withholding(ctx: PayrollContext, pack: _Pack, pay_date: date) -> dict:
    """spec §5 — resolve status → role → table/column → decision → amount.
    Four strategies, never blended; cash-limit rule before any amount."""
    profile = getattr(ctx, "sweden_statutory_profile", None)
    if profile is None:
        raise SwedenCalculationBlockedError(
            "worker_tax_profile",
            "an A-tax/SINK worker with no withholding profile blocks payroll (spec §5)",
            pack.organization_id,
        )

    periods = resolve_periods_per_year(ctx.pay_frequency)
    cash_pay = ctx.se_cash_pay if getattr(ctx, "se_cash_pay", None) is not None else ctx.gross
    cash_pay = _dec(cash_pay)
    taxable_base = _dec(ctx.gross)
    annual_income = taxable_base * periods

    tax_status = (getattr(profile, "se_tax_status", None) or "").strip().upper()
    income_role = (getattr(profile, "se_income_role", None) or "").strip().upper()
    table = getattr(profile, "se_tax_table", None)
    column = getattr(profile, "se_tax_column", None)

    def _decision_applies() -> bool:
        if not _truthy(getattr(profile, "se_decision_override", None)):
            return False
        decision_from = getattr(profile, "se_decision_effective_from", None)
        decision_to = getattr(profile, "se_decision_effective_to", None)
        if decision_from is not None and decision_from > pay_date:
            return False
        if decision_to is not None and decision_to < pay_date:
            return False
        return True

    if _decision_applies():
        # spec §5 step 4 — the instruction wins within its dates; an
        # override flag with no executable value cannot run (the profile
        # validator refuses to persist that state, this is defense in depth).
        monthly_amount = getattr(profile, "se_decision_monthly_withholding", None)
        decision_rate = getattr(profile, "se_decision_rate_pct", None)
        if monthly_amount is not None:
            tax = _round2(_dec(monthly_amount))
            strategy = "DECISION_AMOUNT"
            unrounded = _dec(monthly_amount)
        elif decision_rate is not None:
            unrounded = Decimal(str(decision_rate)) / HUNDRED * taxable_base
            tax = _round2(unrounded)
            strategy = "DECISION_RATE"
        else:
            raise SwedenCalculationBlockedError(
                "se_decision_value",
                "decision override is set but carries neither a monthly amount nor a rate",
                pack.organization_id,
            )
        if cash_pay <= ZERO:
            tax = ZERO
            strategy = "CASH_LIMIT"
        return _withholding_slice(strategy, tax, unrounded, table, column, profile, annual_income, periods)

    if tax_status == "SINK":
        if (getattr(profile, "se_sink_status", None) or "").strip().upper() != "VALID":
            raise SwedenCalculationBlockedError(
                "se_sink_status",
                "SINK applies only with a VALID status/decision (spec §3 [S5])",
                pack.organization_id,
            )
        if cash_pay <= ZERO:
            return _withholding_slice("CASH_LIMIT", ZERO, ZERO, table, column, profile, annual_income, periods)
        rate = pack.require_pct("se_sink", side="employee")
        base = ctx.se_sink_base if getattr(ctx, "se_sink_base", None) is not None else taxable_base
        unrounded = rate / HUNDRED * _dec(base)
        return _withholding_slice("SINK", _round2(unrounded), unrounded, table, column, profile, annual_income, periods)

    if tax_status != "A_TAX":
        raise SwedenCalculationBlockedError(
            "se_tax_status",
            f"unsupported/ambiguous worker tax status {tax_status or 'unset'} (spec §5 step 1)",
            pack.organization_id,
        )

    if income_role == "SUPPLEMENTARY_INCOME":
        # spec §5 step 2 + §3 [S3] — 30% path, never blended with the
        # main-income table.
        if cash_pay <= ZERO:
            return _withholding_slice("CASH_LIMIT", ZERO, ZERO, table, column, profile, annual_income, periods)
        rate = pack.require_pct("se_supplementary_rate", side="employee")
        unrounded = rate / HUNDRED * taxable_base
        return _withholding_slice("SUPPLEMENTARY", _round2(unrounded), unrounded, table, column, profile, annual_income, periods)

    if income_role in ("MAIN_INCOME", "POST_EMPLOYMENT", "ONE_TIME_PAYMENT"):
        if cash_pay <= ZERO:
            return _withholding_slice("CASH_LIMIT", ZERO, ZERO, table, column, profile, annual_income, periods)
        if income_role == "ONE_TIME_PAYMENT":
            # spec §5 step 5 / §3 [S4] — never the ordinary monthly table:
            # the authority percentage for the worker's expected ANNUAL
            # income band and column, applied to the one-time amount.
            if not column:
                raise SwedenCalculationBlockedError(
                    "se_tax_column",
                    "one-time payments require the worker's applicable column (spec §5 step 5)",
                    pack.organization_id,
                )
            expected_annual = getattr(profile, "se_annual_income", None)
            if expected_annual is None:
                raise SwedenCalculationBlockedError(
                    "se_annual_income",
                    "one-time payment tables are keyed on expected annual income — not captured",
                    pack.organization_id,
                )
            rows = [
                r for r in ctx.slabs
                if getattr(r, "rule_type", None) == SE_ONE_TIME_PAYMENT_RULE
                and (getattr(r, "tax_column", None) or "") == column
            ]
            if not rows:
                raise SwedenCalculationBlockedError(
                    "se_one_time_payment_table",
                    f"no one-time-payment rows configured for column {column}",
                    pack.organization_id,
                )
            band = _lookup_authority_band(
                rows, _dec(expected_annual), "se_one_time_payment_table", pack.organization_id)
            # A published 0% band is legitimate (low expected annual income),
            # so the band must DECLARE its basis — an unfilled Draft scaffold
            # (rate_pct 0.00, no basis) must never read as a real 0%.
            rate = getattr(band, "rate_pct", None)
            if (getattr(band, "assessment_basis", None) or "").strip().upper() != "PERCENT" or rate is None:
                raise SwedenCalculationBlockedError(
                    "se_one_time_payment_table",
                    "configured one-time band declares no PERCENT basis (unfilled Draft scaffold)",
                    pack.organization_id,
                )
            unrounded = Decimal(str(rate)) / HUNDRED * taxable_base
            return _withholding_slice("ONE_TIME", _round2(unrounded), unrounded, table, column,
                                      profile, _dec(expected_annual), periods)

        if not table or not column:
            raise SwedenCalculationBlockedError(
                "se_tax_table",
                "main-income withholding needs the worker's resolved tax table AND column (spec §5 step 3)",
                pack.organization_id,
            )
        rows = [
            r for r in ctx.slabs
            if getattr(r, "rule_type", None) == SE_TAX_TABLE_RULE
            and (getattr(r, "tax_table_number", None) or "") == table
            and (getattr(r, "tax_column", None) or "") == column
        ]
        if not rows:
            raise SwedenCalculationBlockedError(
                "se_tax_table",
                f"no authority bands configured for table {table} column {column}",
                pack.organization_id,
            )
        if periods != Decimal("12"):
            raise SwedenCalculationBlockedError(
                "pay_frequency",
                f"Skatteverket monthly tax tables apply to monthly pay; pay frequency "
                f"{ctx.pay_frequency or 'unset'} is outside the first certified release (spec §1)",
                pack.organization_id,
            )
        band = _lookup_authority_band(rows, taxable_base, "se_tax_table", pack.organization_id)
        unrounded = _band_withholding(band, taxable_base, "se_tax_table", pack.organization_id)
        return _withholding_slice("TAX_TABLE", _round2(unrounded), unrounded, table, column, profile, annual_income, periods)

    raise SwedenCalculationBlockedError(
        "se_income_role",
        f"unsupported income role {income_role or 'unset'} (spec §5 step 2)",
        pack.organization_id,
    )


def _withholding_slice(strategy: str, tax: Decimal, unrounded: Decimal, table, column,
                       profile, annual_income: Decimal, periods: Decimal) -> dict:
    return {
        "se_preliminary_tax": tax,
        "se_tax_strategy": strategy,
        "se_withholding_unrounded": unrounded,
        "se_tax_table": table,
        "se_tax_column": column,
        "se_withholding_annual_income": annual_income,
        "se_withholding_periods": periods,
        "se_income_role": (getattr(profile, "se_income_role", None) or None),
        "se_tax_status": (getattr(profile, "se_tax_status", None) or None),
    }


def resolve_occupational_pension(ctx: PayrollContext, pack: _Pack) -> dict:
    """spec §1/§9 — occupational pension ONLY through a configured plan
    share on the worker's profile; no share configured means no premium,
    never a national default."""
    profile = getattr(ctx, "sweden_statutory_profile", None)
    base = _dec(ctx.gross)
    employee_share = getattr(profile, "se_employee_pension_share", None) if profile else None
    employer_share = getattr(profile, "se_employer_pension_share", None) if profile else None
    employee_amount = _round2(Decimal(str(employee_share)) / HUNDRED * base) if employee_share is not None else ZERO
    employer_amount = _round2(Decimal(str(employer_share)) / HUNDRED * base) if employer_share is not None else ZERO
    plan = getattr(profile, "se_pension_plan", None) if profile else None
    return {
        "se_occupational_pension_employee": employee_amount,
        "se_occupational_pension_employer": employer_amount,
        "se_pension_plan": plan,
    }


def resolve_slp(ctx: PayrollContext, pack: _Pack) -> Decimal:
    """spec §3/SE-007 — special payroll tax on pension costs: 24.26% of
    the employer's pension-cost LEDGER base, never of employee gross.
    An unset base is a legitimate zero (no pension-cost entries yet)."""
    base = _dec(getattr(ctx, "se_pension_cost_base", None))
    if base <= ZERO:
        return ZERO
    rate = pack.require_pct("se_slp", side="employer")
    return _round2(rate / HUNDRED * base)


def calculate(ctx: PayrollContext) -> dict:
    """Sweden entry point (standard + enterprise dispatch). Returns the
    deductions/contributions dict standard.py folds into PayrollResult."""
    pay_date = ctx.pay_date
    if pay_date is None:
        raise SwedenCalculationBlockedError(
            "pay_date",
            "payment date is a first-class rule-pack key (SE-005) — cannot calculate without it",
            getattr(ctx, "se_organization_id", None),
        )

    pack = _Pack(ctx.rate_map, getattr(ctx, "se_organization_id", None))
    profile = getattr(ctx, "sweden_statutory_profile", None)

    employer = resolve_employer_contribution(ctx, pack, pay_date)
    withholding = resolve_withholding(ctx, pack, pay_date)
    pension = resolve_occupational_pension(ctx, pack)
    slp = resolve_slp(ctx, pack)

    preliminary_tax = withholding["se_preliminary_tax"]
    employee_total = _round2(
        preliminary_tax + pension["se_occupational_pension_employee"])
    employer_total = _round2(
        employer["se_employer_contribution"]
        + pension["se_occupational_pension_employer"]
        + slp)

    trace = {
        "jurisdiction": _COUNTRY,
        "payDate": pay_date.isoformat(),
        "incomeYear": pay_date.year,
        "taxStrategy": withholding["se_tax_strategy"],
        "taxTable": withholding.get("se_tax_table"),
        "taxColumn": withholding.get("se_tax_column"),
        "annualIncome": str(withholding.get("se_withholding_annual_income")),
        "periodsPerYear": str(withholding.get("se_withholding_periods")),
        "withholdingUnrounded": str(withholding.get("se_withholding_unrounded")),
        "employerCohort": employer["se_employer_contribution_cohort"],
        "youthApplied": employer["se_youth_applied"],
        "monthCompensation": str(employer["se_month_compensation"]),
        "decisionId": getattr(profile, "se_skatteverket_decision_id", None) if profile else None,
        "cbaStatus": getattr(profile, "se_cba_status", None) if profile else None,
        "cbaId": getattr(profile, "se_cba_id", None) if profile else None,
        "sinkStatus": getattr(profile, "se_sink_status", None) if profile else None,
        "rateKeys": sorted(ctx.rate_map.keys()),
    }

    return {
        # employer side — employer_social_security is the generic
        # PayrollResult slot standard.py already propagates.
        "employer_social_security": employer["se_employer_contribution"],
        "se_employer_contribution": employer["se_employer_contribution"],
        "se_employer_contribution_rate": employer["se_employer_contribution_rate"],
        "se_employer_contribution_cohort": employer["se_employer_contribution_cohort"],
        "se_employer_contribution_components": employer["se_employer_contribution_components"],
        "se_employer_contribution_base": employer["se_employer_contribution_base"],
        "se_youth_applied": employer["se_youth_applied"],
        "se_month_compensation": employer["se_month_compensation"],
        "se_slp": slp,
        "se_occupational_pension_employer": pension["se_occupational_pension_employer"],
        "se_pension_plan": pension["se_pension_plan"],
        "se_employer_total": employer_total,
        # employee side
        "se_preliminary_tax": withholding["se_preliminary_tax"],
        "se_tax_strategy": withholding["se_tax_strategy"],
        "se_withholding_unrounded": withholding["se_withholding_unrounded"],
        "se_tax_table": withholding.get("se_tax_table"),
        "se_tax_column": withholding.get("se_tax_column"),
        "se_income_role": withholding.get("se_income_role"),
        "se_tax_status": withholding.get("se_tax_status"),
        "se_occupational_pension_employee": pension["se_occupational_pension_employee"],
        "se_employee_total": employee_total,
        "se_calculation_trace": trace,
    }
