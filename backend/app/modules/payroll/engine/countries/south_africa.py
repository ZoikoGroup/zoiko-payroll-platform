"""modules/payroll/engine/countries/south_africa.py
---------------------------------------------------
South Africa (ZP-ZA-ENG-001) — fail-closed PAYE / UIF / SDL calculation on the
shared engine. Same doctrine as saudi_arabia.py / brazil.py: one country file,
`calculate(ctx) -> dict`, no framework or ORM imports, no clock, no network
(spec §6: the calculation core stays pure). "ZA" is South Africa; "SA" in this
repository is Saudi Arabia.

Scope of v1 (spec §1):
  1. Applicability first (ZA-005). Monthly pay, a RESIDENT STANDARD employee
     (or ordinary director) with a date of birth and an income tax number, an
     employer registration on record. Anything missing or unsupported BLOCKS
     with a reason key — never guessed: weekly / fortnightly pay, non-residents,
     non-standard employment, and a section 7B variable payment whose earned
     period is missing or falls outside the pay period while the timing rule is
     unsigned.
  2. Independent bases (spec §4). Every pay component is classified per
     obligation by ZA_EARNING_CLASS rows: PAYE remuneration, UIF remuneration
     and SDL leviable remuneration are separate sums, never one "taxable
     gross". A non-zero component that is unclassified or REVIEW BLOCKS.
     The fixed travel allowance enters PAYE at the configured 80% / 20% (ZA-008).
  3. PAYE (spec §3). The retirement-fund deduction (27.5%, annual cap / 12) is
     taken from PAYE remuneration; the result is annualised x12, taxed on the
     ZA_PAYE_BAND rows, reduced by the primary / secondary / tertiary rebates
     for the employee's age on the last day of the tax year, de-annualised,
     then reduced by the monthly medical scheme fees tax credit (never below
     zero), plus any authorised voluntary additional PAYE.
     The specification calls these bands VALIDATION ANCHORS for the certified
     SARS periodic algorithm: this annualised-monthly method reproduces
     fixtures F1 / F2 and is recorded in the trace as such — production
     certification (G1) still needs the full SARS deduction-table corpus.
  4. UIF (1% + 1%, capped per employee at the monthly ceiling) and SDL
     (employer-only 1% where the employer registration says it is liable).
  5. Tax directives (ZA-007). An APPROVED directive for THIS employee, in
     force on the pay date, for THIS tax year may replace the computed PAYE
     (FIXED_PERCENTAGE on PAYE remuneration, or FIXED_AMOUNT). Any other
     directive state or type BLOCKS; directives are never generalised.
  6. ETI is an employer incentive (ZA-010): it is NEVER part of the employee's
     PAYE or net pay and never enters an employee/employer total. A broken ETI
     configuration leaves employee pay intact and reports ETI BLOCKED.
  7. Section 7B variable remuneration uses each item's structured earned
     period (`za_variable_items`), never a caller-supplied same-period claim.

Every statutory figure is a configured row; a missing row raises
ZACalculationBlockedError (a MissingComplianceConfigurationError, so the
existing MISSING_COMPLIANCE_CONFIGURATION 400 handler applies unchanged).
"""

import calendar
from datetime import date
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, ROUND_UP

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError
from app.modules.payroll.engine.countries import south_africa_content as _content
from app.modules.payroll.engine.countries import south_africa_eti as _eti

_COUNTRY = "ZA"
ZERO = Decimal("0")
HUNDRED = Decimal("100")
TWELVE = Decimal("12")

ZA_PAYE_BAND_RULE = _content.ZA_PAYE_BAND_RULE
ZA_EARNING_CLASS_RULE = _content.ZA_EARNING_CLASS_RULE

# The scalar parameter catalog — the content file is the one source of truth.
ZA_PARAMETER_KEYS = _content.ZA_PARAMETER_KEYS

MODE_HALF_UP, MODE_DOWN, MODE_UP = _content.ROUNDING_MODES
_DECIMAL_MODE = {MODE_HALF_UP: ROUND_HALF_UP, MODE_DOWN: ROUND_DOWN, MODE_UP: ROUND_UP}
BASIS_PAYMENT_DATE, BASIS_EARNING_DATE, BASIS_PENDING = _content.DATE_BASES

EMPLOYMENT_STANDARD = "STANDARD"
RESIDENT = "RESIDENT"

# Pay components (south_africa_content.ZA_COMPONENTS) and where each comes from.
COMPONENT_SALARY = "SALARY"
COMPONENT_OVERTIME = "OVERTIME"
COMPONENT_TRAVEL_FIXED = "TRAVEL_FIXED"
COMPONENT_OTHER = "OTHER_EARNINGS"
# Named components a service passes in ctx.za_components (amount per period).
NAMED_COMPONENTS = ("BONUS", "COMMISSION", "LEAVE_PAYOUT", "TRAVEL_FIXED", "TRAVEL_REIMBURSIVE",
                    "FRINGE_BENEFIT")
# Section 7B variable remuneration (ZA-006).
VARIABLE_COMPONENTS = ("OVERTIME", "BONUS", "COMMISSION", "LEAVE_PAYOUT")
# Directive types the engine can apply. LUMP_SUM / OTHER are captured but not
# certified for calculation: they BLOCK rather than being approximated.
SUPPORTED_DIRECTIVES = ("FIXED_PERCENTAGE", "FIXED_AMOUNT")

TREATMENT_INCLUDED, TREATMENT_EXCLUDED, TREATMENT_TRAVEL, TREATMENT_REVIEW = _content.TREATMENTS

METHOD = "ANNUALISED_MONTHLY"
METHOD_NOTE = ("Annualised monthly method over the ZA_PAYE_BAND validation anchors (spec §3); "
               "the certified SARS periodic algorithm governs at G1.")
_DIRECTIVE_POLICY = ("PENDING_G1: the specification does not state whether a directive replaces PAYE "
                     "before or after the medical scheme credit. The engine replaces the computed PAYE "
                     "(medical credit already applied) and then adds authorised voluntary additional PAYE.")


class ZACalculationBlockedError(MissingComplianceConfigurationError):
    """A South African statutory calculation that must not proceed — missing
    configured row, missing or contradictory employee fact, or an unsupported
    case (spec §1: unsupported cases are blocked, never approximated)."""

    def __init__(self, key: str, reason: str, organization_id: int = None):
        super().__init__(key, _COUNTRY, organization_id)
        self.reason = reason
        self.args = (f"South Africa calculation blocked ({key}): {reason}",)


def _dec(value) -> Decimal:
    if value is None or value == "":
        return ZERO
    return Decimal(str(value))


def _upper(value) -> str:
    return "" if value is None else str(value).strip().upper()


def _as_date(value):
    """ISO string / date / datetime -> date, else None (never guessed)."""
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _field(value, name):
    """A directive / item fact from a dict or an ORM-like object."""
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _fact(ctx, profile, name):
    """An employee fact from the context, else the statutory profile."""
    value = getattr(ctx, name, None)
    if value is None or value == "":
        value = getattr(profile, name, None) if profile is not None else None
    return value


class _Pack:
    """Typed, fail-closed reader over ctx.rate_map — a configured row is the
    ONLY source of a value, and a missing row blocks (never a default)."""

    def __init__(self, rate_map: dict, organization_id):
        self.rate_map = rate_map or {}
        self.organization_id = organization_id

    def block(self, key: str, reason: str):
        raise ZACalculationBlockedError(key, reason, self.organization_id)

    def _row(self, key: str):
        row = self.rate_map.get(key)
        if row is None:
            self.block(key, "no configured parameter row")
        return row

    def require_amount(self, key: str) -> Decimal:
        value = getattr(self._row(key), "flat_amount", None)
        if value is None:
            self.block(key, "row has no amount configured")
        return Decimal(str(value))

    def require_pct(self, key: str, side: str) -> Decimal:
        attr = "employee_rate_pct" if side == "employee" else "employer_rate_pct"
        value = getattr(self._row(key), attr, None)
        if value is None:
            self.block(key, f"row has no {side} rate configured")
        return Decimal(str(value))

    def require_text(self, key: str, allowed=None) -> str:
        value = getattr(self._row(key), "text_value", None)
        if value is None or str(value).strip() == "":
            self.block(key, "row has no value configured")
        value = str(value).strip().upper()
        if allowed is not None and value not in allowed:
            self.block(key, f"{value!r} is not one of {', '.join(allowed)}")
        return value


# ── rounding (configured, never assumed) ────────────────────────────────────
def _rounding(pack: _Pack):
    mode = pack.require_text("za_rounding_mode", _content.ROUNDING_MODES)
    precision = pack.require_amount("za_rounding_precision")
    if precision != precision.to_integral_value() or precision < 0 or precision > 6:
        pack.block("za_rounding_precision", f"precision {precision} is not a whole number in 0-6")
    quantum = Decimal(1).scaleb(-int(precision))
    return lambda value: value.quantize(quantum, rounding=_DECIMAL_MODE[mode]), mode, int(precision)


# ── dates: tax year and age (ZA-006) ────────────────────────────────────────
def tax_year_end(on: date) -> date:
    """The last day (28/29 February) of the South African tax year containing `on`."""
    year = on.year + 1 if on.month >= 3 else on.year
    return date(year, 2, calendar.monthrange(year, 2)[1])


def month_end(on: date) -> date:
    return date(on.year, on.month, calendar.monthrange(on.year, on.month)[1])


def age_on(born: date, on: date) -> int:
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


def resolve_tax_year(ctx: PayrollContext, pack: _Pack) -> dict:
    """The date that selects the tax year. Earning date and payment date are
    distinct (ZA-006); when they fall in different tax years the signed
    za_paye_tax_year_date_basis decides, and PENDING_G1 BLOCKS."""
    paid = ctx.pay_date
    earned = getattr(ctx, "period_end", None) or paid
    basis = pack.require_text("za_paye_tax_year_date_basis", _content.DATE_BASES)
    if tax_year_end(earned) == tax_year_end(paid):
        anchor = paid
    elif basis == BASIS_PENDING:
        pack.block("za_paye_tax_year_date_basis",
                   f"earned {earned} and paid {paid} fall in different tax years and the date that "
                   "selects the tax year is PENDING_G1 (ZA-006)")
    else:
        anchor = paid if basis == BASIS_PAYMENT_DATE else earned
    return {"anchor": anchor, "taxYearEnd": tax_year_end(anchor), "basis": basis,
            "earnedOn": earned, "paidOn": paid}


# ── applicability (ZA-005) ──────────────────────────────────────────────────
def resolve_applicability(ctx: PayrollContext, profile, pack: _Pack) -> dict:
    if ctx.pay_date is None:
        pack.block("pay_date", "payment date is a first-class rule-pack key")
    supported = [f.strip() for f in pack.require_text("za_supported_pay_frequencies").split(",") if f.strip()]
    frequency = _upper(ctx.pay_frequency)
    if frequency not in supported:
        pack.block("pay_frequency",
                   f"{ctx.pay_frequency!r} pay is not certified (supported: {', '.join(supported)}); weekly "
                   "and fortnightly payroll wait for their own deduction-table tests (spec §1)")
    if profile is None:
        pack.block("za_statutory_profile", "no South African statutory profile in force for the pay date")

    residency = _upper(_fact(ctx, profile, "za_tax_residency"))
    if not residency:
        pack.block("za_tax_residency", "tax residency is not recorded (ZA-005)")
    if residency != RESIDENT:
        pack.block("za_scope", f"tax residency {residency!r} is deferred scope — non-resident and treaty "
                               "cases are blocked until separately certified (spec §1)")
    employment = _upper(_fact(ctx, profile, "za_employment_type"))
    if not employment:
        pack.block("za_employment_type", "standard / non-standard employment is not recorded (ZA-005)")
    if employment not in _content.EMPLOYMENT_TYPES:
        pack.block("za_employment_type", f"unknown employment type {employment!r}")
    if employment != EMPLOYMENT_STANDARD:
        pack.block("za_scope", "non-standard employment PAYE is not in the certified rule pack (spec §3)")

    born = getattr(ctx, "date_of_birth", None)
    if born is None:
        pack.block("date_of_birth", "date of birth is required for the age rebates (spec §2)")
    if not getattr(ctx, "za_has_tax_number", None):
        pack.block("za_tax_number", "no income tax reference number is recorded — required for a supported "
                                    "SARS profile and IRP5 acceptance (spec §1, §9)")
    if _fact(ctx, profile, "za_sez_employee") is True:
        pack.block("za_scope", "SEZ-specific ETI is deferred scope (spec §1)")

    registration = getattr(ctx, "za_employer_registration", None)
    if registration is None:
        pack.block("za_employer_registration", "no active employer PAYE / UIF / SDL registration for the pay "
                                               "date (ZA-011: liability is an employer fact, never inferred)")
    return {"frequency": frequency, "residency": residency, "employment": employment,
            "dateOfBirth": born, "registration": registration}


# ── independent bases (spec §4) ─────────────────────────────────────────────
def _classes(slabs) -> dict:
    out = {}
    for r in slabs or []:
        if (getattr(r, "rule_type", None) or "") != ZA_EARNING_CLASS_RULE:
            continue
        key = (_upper(getattr(r, "tax_regime", None)), _upper(getattr(r, "filing_status", None)))
        out[key] = _upper(getattr(r, "assessment_basis", None))
    return out


def pay_components(ctx: PayrollContext, pack: _Pack) -> list:
    """(component, amount) for every non-zero pay component. SALARY is the
    basic, OVERTIME the overtime line, the named components come from
    ctx.za_components and OTHER_EARNINGS is whatever of gross is left."""
    named = {_upper(k): _dec(v) for k, v in (getattr(ctx, "za_components", None) or {}).items()}
    unknown = sorted(set(named) - set(NAMED_COMPONENTS))
    if unknown:
        pack.block("za_components", f"unknown pay component(s) {', '.join(unknown)}")
    amounts = [(COMPONENT_SALARY, _dec(ctx.basic)), (COMPONENT_OVERTIME, _dec(ctx.overtime))]
    amounts += [(name, named.get(name, ZERO)) for name in NAMED_COMPONENTS]
    for name, amount in amounts:
        if amount < ZERO:
            pack.block("za_components", f"pay component {name} is negative ({amount})")
    other = _dec(ctx.gross) - sum((a for _n, a in amounts), ZERO)
    if other < ZERO:
        pack.block("za_components", f"the pay components exceed gross by {-other}")
    amounts.append((COMPONENT_OTHER, other))
    return [(name, amount) for name, amount in amounts if amount > ZERO]


def obligation_base(obligation: str, components: list, classes: dict, pack: _Pack, travel_pct=None) -> dict:
    """The sum of the components this obligation includes. An unclassified or
    REVIEW non-zero component BLOCKS; TRAVEL_RULE applies only to PAYE."""
    base = ZERO
    lines = []
    for component, amount in components:
        treatment = classes.get((obligation, component))
        if treatment is None:
            pack.block(f"za_earning_class:{obligation}:{component}",
                       f"pay component {component} ({amount}) has no {obligation} classification row")
        if treatment == TREATMENT_REVIEW:
            pack.block(f"za_earning_class:{obligation}:{component}",
                       f"pay component {component} ({amount}) is classified REVIEW for {obligation} — a "
                       "signed treatment is required before it can be calculated (spec §4)")
        if treatment == TREATMENT_INCLUDED:
            counted = amount
        elif treatment == TREATMENT_EXCLUDED:
            counted = ZERO
        elif treatment == TREATMENT_TRAVEL and travel_pct is not None:
            counted = amount * travel_pct / HUNDRED
        else:
            pack.block(f"za_earning_class:{obligation}:{component}",
                       f"treatment {treatment!r} is not valid for {obligation}")
        base += counted
        lines.append({"component": component, "amount": str(amount), "treatment": treatment,
                      "counted": str(counted)})
    return {"base": base, "lines": lines}


# ── PAYE (spec §2, §3) ──────────────────────────────────────────────────────
def _paye_band(slabs, annual: Decimal, pack: _Pack):
    rows = [r for r in (slabs or []) if (getattr(r, "rule_type", None) or "") == ZA_PAYE_BAND_RULE]
    if not rows:
        pack.block("za_paye_band", "no PAYE band rows are configured")
    matches = [r for r in rows
               if annual > _dec(getattr(r, "min_amount", None))
               and (getattr(r, "max_amount", None) is None or annual <= _dec(r.max_amount))]
    if len(matches) != 1:
        pack.block("za_paye_band", f"{len(matches)} PAYE bands match annual taxable income {annual} — "
                                   "the band table is incomplete or ambiguous")
    return matches[0]


def compute_paye(ctx: PayrollContext, profile, pack: _Pack, remuneration: Decimal, rnd, tax_year: dict,
                 applicability: dict) -> dict:
    # Retirement fund contribution deduction (spec §2) — PENDING_G1 algorithm.
    contribution = _dec(getattr(ctx, "za_retirement_fund_contribution", None))
    if contribution < ZERO:
        pack.block("za_retirement_fund_contribution", "the retirement fund contribution is negative")
    pct_limit = remuneration * pack.require_pct("za_retirement_deduction_pct", "employee") / HUNDRED
    cap_limit = pack.require_amount("za_retirement_annual_cap") / TWELVE
    retirement_deduction = min(contribution, pct_limit, cap_limit)
    monthly_taxable = remuneration - retirement_deduction
    annual_taxable = monthly_taxable * TWELVE

    if annual_taxable > ZERO:
        band = _paye_band(getattr(ctx, "slabs", None), annual_taxable, pack)
        band_min = _dec(band.min_amount)
        annual_tax = _dec(getattr(band, "flat_amount", None)) + (annual_taxable - band_min) * _dec(band.rate_pct) / HUNDRED
        band_info = {"min": str(band_min),
                     "max": None if band.max_amount is None else str(_dec(band.max_amount)),
                     "ratePct": str(_dec(band.rate_pct)), "baseTax": str(_dec(band.flat_amount))}
    else:
        annual_tax, band_info = ZERO, None

    age = age_on(applicability["dateOfBirth"], tax_year["taxYearEnd"])
    rebates = [("primary", pack.require_amount("za_rebate_primary"))]
    if age >= pack.require_amount("za_rebate_secondary_age"):
        rebates.append(("secondary", pack.require_amount("za_rebate_secondary")))
    if age >= pack.require_amount("za_rebate_tertiary_age"):
        rebates.append(("tertiary", pack.require_amount("za_rebate_tertiary")))
    rebate_total = sum((amount for _n, amount in rebates), ZERO)
    annual_after_rebates = max(annual_tax - rebate_total, ZERO)
    monthly_before_mtc = rnd(annual_after_rebates / TWELVE)

    # Medical scheme fees tax credit (monthly, non-refundable).
    member = _fact(ctx, profile, "za_medical_scheme_member")
    dependants_raw = _fact(ctx, profile, "za_medical_dependants")
    if member is True:
        if dependants_raw is None:
            pack.block("za_medical_dependants", "a medical scheme member must record the number of dependants "
                                                "(0 or more) for the medical tax credit")
        dependants = int(dependants_raw)
        mtc = pack.require_amount("za_mtc_main_member")
        if dependants >= 1:
            mtc += pack.require_amount("za_mtc_first_dependant")
        if dependants > 1:
            mtc += pack.require_amount("za_mtc_additional_dependant") * (dependants - 1)
    else:
        dependants = int(dependants_raw or 0)
        if dependants:
            pack.block("za_medical_dependants", "dependants are recorded but the employee is not a medical "
                                                "scheme member — contradictory facts")
        mtc = ZERO
    mtc_applied = min(mtc, monthly_before_mtc)
    voluntary = _dec(_fact(ctx, profile, "za_voluntary_additional_paye"))
    if voluntary < ZERO:
        pack.block("za_voluntary_additional_paye", "voluntary additional PAYE is negative")
    paye = rnd(monthly_before_mtc - mtc_applied + voluntary)

    return {
        "paye": paye, "annualTaxAfterRebates": annual_after_rebates,
        "trace": {
            "method": METHOD, "methodNote": METHOD_NOTE,
            "remuneration": str(remuneration),
            "retirementContribution": str(contribution),
            "retirementDeduction": str(retirement_deduction),
            "retirementLimits": {"pctOfRemuneration": str(pct_limit), "monthlyCap": str(cap_limit)},
            "monthlyTaxable": str(monthly_taxable), "annualTaxable": str(annual_taxable),
            "band": band_info, "annualTaxBeforeRebates": str(annual_tax),
            "ageAtTaxYearEnd": age, "rebates": [{"rebate": n, "amount": str(a)} for n, a in rebates],
            "annualTaxAfterRebates": str(annual_after_rebates),
            "monthlyBeforeMedicalCredit": str(monthly_before_mtc),
            "medicalSchemeMember": member is True, "medicalDependants": dependants,
            "medicalCreditEntitlement": str(mtc), "medicalCreditApplied": str(mtc_applied),
            "voluntaryAdditionalPaye": str(voluntary), "paye": str(paye),
        },
    }


# ── UIF and SDL (spec §2, §4) ───────────────────────────────────────────────
def compute_uif(ctx: PayrollContext, profile, pack: _Pack, base: Decimal, rnd) -> dict:
    excluded = _fact(ctx, profile, "za_uif_excluded")
    director = _fact(ctx, profile, "za_is_director") is True
    if director and excluded is None:
        pack.block("za_uif_excluded", "a director's UIF contributor status must be recorded explicitly "
                                      "(ZA-005) — it is never assumed")
    if excluded is True:
        reason = _fact(ctx, profile, "za_uif_exclusion_reason")
        if not reason:
            pack.block("za_uif_exclusion_reason", "UIF exclusion is recorded without its reason / evidence")
        return {"employee": ZERO, "employer": ZERO,
                "trace": {"status": "EXCLUDED", "reason": reason, "base": str(base)}}
    ceiling = pack.require_amount("za_uif_monthly_ceiling")
    capped = min(base, ceiling)
    employee = rnd(capped * pack.require_pct("za_uif", "employee") / HUNDRED)
    employer = rnd(capped * pack.require_pct("za_uif", "employer") / HUNDRED)
    return {"employee": employee, "employer": employer,
            "trace": {"status": "CONTRIBUTING", "base": str(base), "ceiling": str(ceiling),
                      "cappedBase": str(capped), "ceilingApplied": base > ceiling,
                      "employee": str(employee), "employer": str(employer)}}


def compute_sdl(pack: _Pack, base: Decimal, rnd, registration) -> dict:
    liable = getattr(registration, "sdl_liable", None)
    if liable is None:
        pack.block("za_employer_registration", "the employer registration does not state SDL liability")
    if not liable:
        reason = getattr(registration, "sdl_exemption_reason", None)
        if not reason:
            pack.block("za_employer_registration", "the employer is recorded as not SDL-liable without a reason")
        return {"employer": ZERO, "trace": {"status": "EXEMPT", "reason": reason, "base": str(base)}}
    levy = rnd(base * pack.require_pct("za_sdl", "employer") / HUNDRED)
    return {"employer": levy, "trace": {"status": "LIABLE", "base": str(base), "levy": str(levy)}}


# ── section 7B variable remuneration (ZA-006) ───────────────────────────────
def check_variable_remuneration(ctx: PayrollContext, components: list, pack: _Pack) -> dict:
    """Section 7B timing from the items' own earned periods.

    Every variable component paid this period must have structured items
    (`za_variable_items`: component, amount, earned_from, earned_to) and those
    items must account for the paid amount. The same-period fact is DERIVED
    from the periods, never taken from the caller. While the paid/accrual
    timing rule is PENDING_G1, variable pay not earned inside the pay period
    BLOCKS; under an EARNING_DATE basis, a prior-period item is a correction
    run (P9) and also BLOCKS."""
    variable = [(n, a) for n, a in components if n in VARIABLE_COMPONENTS]
    basis = pack.require_text("za_variable_remuneration_basis", _content.DATE_BASES)
    if not variable:
        return {"basis": basis, "components": [], "samePeriod": False, "items": []}

    items = []
    for raw in (getattr(ctx, "za_variable_items", None) or []):
        name = _upper(_field(raw, "component"))
        amount_raw = _field(raw, "amount")
        start = _as_date(_field(raw, "earned_from") or _field(raw, "earnedFrom"))
        end = _as_date(_field(raw, "earned_to") or _field(raw, "earnedTo"))
        if not name:
            pack.block("za_variable_remuneration_basis", "a section 7B item has no pay component")
        if amount_raw is None or amount_raw == "":
            pack.block("za_variable_remuneration_basis", f"section 7B item {name} has no amount")
        if start is None or end is None:
            pack.block("za_variable_remuneration_basis",
                       f"section 7B item {name} has no structured earned period (ZA-006)")
        if end < start:
            pack.block("za_variable_remuneration_basis",
                       f"section 7B item {name} earned period ends before it starts")
        amount = _dec(amount_raw)
        if amount < ZERO:
            pack.block("za_variable_remuneration_basis", f"section 7B item {name} is negative ({amount})")
        items.append({"component": name, "amount": amount, "earned_from": start, "earned_to": end})

    for name, paid in variable:
        matching = [i for i in items if i["component"] == name]
        if not matching:
            pack.block("za_variable_remuneration_basis",
                       f"section 7B variable remuneration {name} has no earned-period item (ZA-006)")
        itemised = sum((i["amount"] for i in matching), ZERO)
        if itemised != paid:
            pack.block("za_variable_remuneration_basis",
                       f"section 7B {name} items total {itemised} but the paid component is {paid}")

    period_start = _as_date(getattr(ctx, "period_start", None))
    period_end = _as_date(getattr(ctx, "period_end", None))
    if period_start is None or period_end is None:
        pack.block("za_variable_remuneration_basis",
                   "the pay period is not recorded, so section 7B timing cannot be derived (ZA-006)")
    outside = [i for i in items if i["earned_from"] < period_start or i["earned_to"] > period_end]
    same_period = not outside
    if outside and basis == BASIS_PENDING:
        names = ", ".join(sorted({i["component"] for i in outside}))
        pack.block("za_variable_remuneration_basis",
                   f"section 7B variable remuneration ({names}) was not earned inside "
                   f"{period_start}..{period_end} and the paid/accrual timing rule is PENDING_G1 (ZA-006)")
    prior = [i for i in outside if i["earned_to"] < period_start]
    if basis == BASIS_EARNING_DATE and prior:
        pack.block("za_variable_remuneration_basis",
                   "section 7B variable remuneration earned in a prior period under the earning-date basis "
                   "is a correction run (P9), not an in-period calculation")

    return {"basis": basis, "components": [n for n, _a in variable], "samePeriod": same_period,
            "items": [{"component": i["component"], "amount": str(i["amount"]),
                       "earnedFrom": i["earned_from"].isoformat(),
                       "earnedTo": i["earned_to"].isoformat()} for i in items]}


# ── tax directives (ZA-007) ─────────────────────────────────────────────────
def apply_directive(ctx: PayrollContext, profile, pack: _Pack, computed_paye: Decimal,
                    paye_remuneration: Decimal, tax_year: dict, rnd) -> dict:
    """Replace the computed PAYE with an APPROVED directive for THIS employee,
    THIS tax year, in force on the pay date. The directive replaces the PAYE
    produced by the ordinary calculation (including the medical credit) but
    never the employee's authorised voluntary additional PAYE, which is added
    on top. PENDING_G1: the spec does not say whether a directive replaces PAYE
    after the medical credit; that choice is recorded, not silently assumed.

    A directive is never ignored and never generalised: multiple in-force
    directives, an unapproved one, another employee's, another tax year's, an
    unsupported type, or a missing window/rate/amount all BLOCK with
    `za_tax_directive`."""
    directives = getattr(ctx, "za_directives", None) or []
    if not directives:
        return {"applied": None, "paye": computed_paye, "policyNote": _DIRECTIVE_POLICY}

    pay_date = ctx.pay_date
    in_force = []
    for directive in directives:
        start = _as_date(_field(directive, "effective_from") or _field(directive, "effectiveFrom"))
        end = _as_date(_field(directive, "effective_to") or _field(directive, "effectiveTo"))
        if start is None:
            pack.block("za_tax_directive", "a recorded tax directive has no effective-from date (ZA-007)")
        if end is not None and end < start:
            pack.block("za_tax_directive", "a recorded tax directive's window ends before it starts")
        if start <= pay_date and (end is None or pay_date <= end):
            in_force.append(directive)
    if not in_force:
        return {"applied": None, "paye": computed_paye, "policyNote": _DIRECTIVE_POLICY}
    if len(in_force) > 1:
        pack.block("za_tax_directive", f"{len(in_force)} tax directives are in force for the employee on "
                                       f"{pay_date} — the override is ambiguous (ZA-007)")
    directive = in_force[0]

    if _upper(_field(directive, "status")) != "APPROVED":
        pack.block("za_tax_directive", "the in-force tax directive has not passed four-eyes approval "
                                       "(status APPROVED) — ZA-007")
    employee_id = _field(directive, "employee_id")
    if employee_id is None or employee_id != getattr(ctx, "za_employee_id", None):
        pack.block("za_tax_directive", "the tax directive belongs to another employee — never generalised "
                                       "(ZA-007)")
    directive_year = str(_field(directive, "tax_year") or "").strip()
    expected_year = str(tax_year["taxYearEnd"].year)
    if directive_year != expected_year:
        pack.block("za_tax_directive", f"the tax directive is for tax year {directive_year!r}, not "
                                       f"{expected_year!r} — ZA-007")
    directive_type = _upper(_field(directive, "directive_type") or _field(directive, "directiveType"))
    if directive_type not in SUPPORTED_DIRECTIVES:
        pack.block("za_tax_directive", f"directive type {directive_type!r} is not certified for calculation "
                                       f"(supported: {', '.join(SUPPORTED_DIRECTIVES)}); it replaces nothing "
                                       "and is never approximated (ZA-007)")

    rate = amount = None
    if directive_type == "FIXED_PERCENTAGE":
        rate_raw = _field(directive, "rate_pct")
        if rate_raw is None or rate_raw == "":
            pack.block("za_tax_directive", "a FIXED_PERCENTAGE directive has no rate (ZA-007)")
        rate = _dec(rate_raw)
        if rate < ZERO or rate > HUNDRED:
            pack.block("za_tax_directive", f"directive rate {rate} is outside 0..100%")
        paye = rnd(paye_remuneration * rate / HUNDRED)
    else:  # FIXED_AMOUNT
        amount_raw = _field(directive, "amount")
        if amount_raw is None or amount_raw == "":
            pack.block("za_tax_directive", "a FIXED_AMOUNT directive has no amount (ZA-007)")
        amount = _dec(amount_raw)
        if amount < ZERO:
            pack.block("za_tax_directive", f"directive amount {amount} is negative")
        paye = rnd(amount)

    voluntary = _dec(_fact(ctx, profile, "za_voluntary_additional_paye"))
    if voluntary < ZERO:
        pack.block("za_voluntary_additional_paye", "voluntary additional PAYE is negative")
    paye = rnd(paye + voluntary)
    applied = {
        "id": _field(directive, "id"),
        "directiveNumber": _field(directive, "directive_number") or _field(directive, "directiveNumber"),
        "type": directive_type,
        "ratePct": None if rate is None else str(rate),
        "amount": None if amount is None else str(amount),
        "computedPaye": str(computed_paye),
        "paye": str(paye),
        "policyNote": _DIRECTIVE_POLICY,
    }
    return {"applied": applied, "paye": paye, "policyNote": _DIRECTIVE_POLICY}


def calculate(ctx: PayrollContext) -> dict:
    """South Africa entry point (standard + enterprise dispatch)."""
    pack = _Pack(ctx.rate_map, getattr(ctx, "za_organization_id", None))
    profile = getattr(ctx, "za_statutory_profile", None)
    applicability = resolve_applicability(ctx, profile, pack)
    rnd, mode, precision = _rounding(pack)
    tax_year = resolve_tax_year(ctx, pack)

    components = pay_components(ctx, pack)
    variable = check_variable_remuneration(ctx, components, pack)
    classes = _classes(getattr(ctx, "slabs", None))
    business_use = _fact(ctx, profile, "za_travel_business_use_80") is True
    travel_key = "za_travel_inclusion_business_pct" if business_use else "za_travel_inclusion_default_pct"
    travel_pct = pack.require_pct(travel_key, "employee")
    paye_base = obligation_base("PAYE", components, classes, pack, travel_pct=travel_pct)
    uif_base = obligation_base("UIF", components, classes, pack)
    sdl_base = obligation_base("SDL", components, classes, pack)

    paye = compute_paye(ctx, profile, pack, paye_base["base"], rnd, tax_year, applicability)
    uif = compute_uif(ctx, profile, pack, uif_base["base"], rnd)
    sdl = compute_sdl(pack, sdl_base["base"], rnd, applicability["registration"])
    retirement = _dec(getattr(ctx, "za_retirement_fund_contribution", None))

    directive = apply_directive(ctx, profile, pack, paye["paye"], paye_base["base"], tax_year, rnd)
    paye_applied = directive["paye"]

    # ETI is an employer incentive (ZA-010): it is never added to an employee or
    # employer total and never changes the employee's PAYE / net pay. A broken
    # ETI configuration is confined to the ETI result (BLOCKED), so pay proceeds.
    registered_eti = getattr(applicability["registration"], "eti_registered", None)
    eligible_eti = _fact(ctx, profile, "za_eti_eligible")
    eti_inputs = {
        "claim_month_end": month_end(tax_year["anchor"]),
        "date_of_birth": applicability["dateOfBirth"],
        "hire_date": getattr(ctx, "date_of_joining", None),
        "eligible_flag": eligible_eti,
        "employer_registered": registered_eti,
        "paid_hours": getattr(ctx, "za_eti_paid_hours", None),
        "qualifying_month_no": getattr(ctx, "za_eti_qualifying_month_no", None),
        "pack": pack, "slabs": getattr(ctx, "slabs", None), "rnd": rnd,
    }
    if registered_eti is True and eligible_eti is True:
        try:
            eti_base = obligation_base("ETI", components, classes, pack)
            eti = _eti.compute_eti(remuneration=eti_base["base"], **eti_inputs)
        except ZACalculationBlockedError as exc:
            eti = _eti.blocked_result(getattr(exc, "reason", str(exc)),
                                      month_no=eti_inputs["qualifying_month_no"],
                                      paid_hours=eti_inputs["paid_hours"], rnd=rnd)
    else:
        eti = _eti.compute_eti(remuneration=None, **eti_inputs)
    eti_result = {**eti, "amount": str(eti["amount"])}

    employee_total = paye_applied + uif["employee"] + retirement
    employer_total = uif["employer"] + sdl["employer"]

    trace = {
        "jurisdiction": _COUNTRY,
        "payDate": ctx.pay_date.isoformat(),
        "taxYearEnd": tax_year["taxYearEnd"].isoformat(),
        "taxYearDateBasis": tax_year["basis"],
        "earnedOn": tax_year["earnedOn"].isoformat(),
        "payFrequency": applicability["frequency"],
        "residency": applicability["residency"],
        "employmentType": applicability["employment"],
        "roundingMode": mode, "roundingPrecision": precision,
        "travelInclusionPct": str(travel_pct), "travelBusinessUse80": business_use,
        "variableRemuneration": variable,
        "bases": {name: {"base": str(b["base"]), "lines": b["lines"]}
                  for name, b in (("PAYE", paye_base), ("UIF", uif_base), ("SDL", sdl_base))},
        "paye": paye["trace"],
        "directive": {"applied": directive["applied"], "computedPaye": str(paye["paye"]),
                      "paye": str(paye_applied), "policyNote": _DIRECTIVE_POLICY},
        "uif": uif["trace"],
        "sdl": sdl["trace"],
        "eti": eti_result,
        "employeeTotal": str(employee_total),
        "employerTotal": str(employer_total),
        "rateKeys": sorted((ctx.rate_map or {}).keys()),
    }

    return {
        "tds": paye_applied,
        "annual_tax": paye["annualTaxAfterRebates"],
        "employee_esi": uif["employee"],
        "employer_esi": uif["employer"],
        "employer_payroll_tax": sdl["employer"],
        "employee_pension": retirement,
        "za_result": {
            "za_paye": str(paye_applied),
            "za_paye_computed": str(paye["paye"]),
            "za_paye_remuneration": str(paye_base["base"]),
            "za_uif_employee": str(uif["employee"]),
            "za_uif_employer": str(uif["employer"]),
            "za_uif_base": str(uif_base["base"]),
            "za_sdl": str(sdl["employer"]),
            "za_sdl_base": str(sdl_base["base"]),
            "za_retirement_contribution": str(retirement),
            "za_medical_credit_applied": paye["trace"]["medicalCreditApplied"],
            "za_employee_total": str(employee_total),
            "za_employer_total": str(employer_total),
            "za_eti": eti_result,
            "za_eti_amount": str(eti["amount"]),
            "trace": trace,
        },
    }
