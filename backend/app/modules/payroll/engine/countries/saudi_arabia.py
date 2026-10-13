"""modules/payroll/engine/countries/saudi_arabia.py
---------------------------------------------------
Saudi Arabia (ZP-SA-ENG-001) — fail-closed GOSI payroll calculation on the
shared engine. Same doctrine as italy.py / sweden.py / switzerland.py: one
country file, `calculate(ctx) -> dict`, no framework or ORM imports.

Scope of v1 (spec §1):
  1. Scope + worker class (SA-001). Only ordinary private-sector SAUDI and
     NON_SAUDI workers are calculated. GCC nationals, domestic workers and any
     recorded special category (flexible work, public sector, …) BLOCK — they
     never default to Saudi or expatriate logic.
  2. GOSI cohort (spec §3, SA-005/006). A Saudi worker's NEW / LEGACY social-
     insurance system is an employee-owned, evidenced fact; missing or
     unevidenced BLOCKS. Non-Saudi workers have no cohort (no pension, no SANED).
  3. GOSI branches (spec §4, SA-003/009), each an effective-dated TaxSlab row
     (rule_type="SA_GOSI_BRANCH"):
       * SAUDI     — pension (cohort's regime) + SANED + Occupational Hazards
       * NON_SAUDI — Occupational Hazards ONLY (employer 2%)
     Each branch is separately rounded. The branch row is chosen by the
     contribution month and the configured sa_rate_selection_basis (SA-007): a
     month in which a branch's rate changes BLOCKS until G1 signs the basis.
  4. Contributory wage (spec §5, SA-011/012/013): the REGISTERED GOSI wage when
     recorded, otherwise the sum of components classified INCLUDED for GOSI
     (SA_EARNING_CLASS rows). An unclassified or REVIEW component BLOCKS. A
     wage below a branch minimum BLOCKS or is floored per
     sa_gosi_below_min_behaviour; above the maximum it is capped.
  5. Labour controls (spec §11, SA-028/029/030): authorised deductions are
     validated per type and in aggregate and then DEDUCTED from net pay; a
     breach BLOCKS. Approved overtime must be paid at least the statutory
     amount (hourly wage + premium% of basic hourly wage) unless consented
     compensatory leave is recorded. Hours are a compliance report.

Saudi Arabia is NOT a PAYE jurisdiction (SA-004): this module NEVER returns a
`tds` key. Every statutory figure is a configured row; a missing row raises
SACalculationBlockedError (a MissingComplianceConfigurationError, so the
existing MISSING_COMPLIANCE_CONFIGURATION 400 handler applies unchanged).
"""

import calendar
from datetime import date
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, ROUND_UP

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError
from app.modules.payroll.engine.countries import saudi_arabia_content as _content
from app.modules.payroll.engine.jurisdictions.saudi_arabia import labour as _labour

_COUNTRY = "SA"
ZERO = Decimal("0")
HUNDRED = Decimal("100")

# ── Worker classes / cohorts / branches (ZP-SA-ENG-001 §3/§4) ─────────────
WORKER_CLASS_SAUDI = "SAUDI"
WORKER_CLASS_NON_SAUDI = "NON_SAUDI"
WORKER_CLASS_GCC = "GCC"
WORKER_CLASS_DOMESTIC = "DOMESTIC"
WORKER_CLASSES = _content.WORKER_CLASSES_SUPPORTED
BLOCKED_WORKER_CLASSES = _content.WORKER_CLASSES_BLOCKED
KNOWN_WORKER_CLASSES = WORKER_CLASSES + BLOCKED_WORKER_CLASSES

COHORT_NEW = "NEW"
COHORT_LEGACY = "LEGACY"
COHORTS = (COHORT_NEW, COHORT_LEGACY)
PENSION_REGIME_NEW = "PENSION_NEW"
PENSION_REGIME_LEGACY = "PENSION_LEGACY"
BRANCH_PENSION = "PENSION"
BRANCH_SANED = "SANED"
BRANCH_OCCUPATIONAL_HAZARDS = "OCCUPATIONAL_HAZARDS"

SA_GOSI_BRANCH_RULE = _content.SA_GOSI_BRANCH_RULE
SA_EARNING_CLASS_RULE = _content.SA_EARNING_CLASS_RULE

# A recorded special category other than these BLOCKS (spec §1 deferrals).
ORDINARY_CATEGORIES = ("", "NONE", "ORDINARY")

MODE_HALF_UP, MODE_DOWN, MODE_UP = _content.ROUNDING_MODES
_DECIMAL_MODE = {MODE_HALF_UP: ROUND_HALF_UP, MODE_DOWN: ROUND_DOWN, MODE_UP: ROUND_UP}
BASIS_MONTH_START, BASIS_MONTH_END, BASIS_PENDING = _content.RATE_SELECTION_BASES
BELOW_MIN_BLOCK, BELOW_MIN_FLOOR = _content.BELOW_MIN_BEHAVIOURS

# Pay components the GOSI classification covers, and where each comes from.
COMPONENT_BASIC = "BASIC"
COMPONENT_HOUSING = "HOUSING"
COMPONENT_HOUSING_IN_KIND = "HOUSING_IN_KIND"
COMPONENT_ALLOWANCE_REGULAR = "ALLOWANCE_REGULAR"
COMPONENT_OVERTIME = "OVERTIME"
COMPONENT_OTHER = "OTHER_EARNINGS"

# The scalar parameter catalog — the content file is the one source of truth.
SA_PARAMETER_KEYS = _content.SA_PARAMETER_KEYS

# ── Fallback-registry constants (engine/fallback_registry.py) ─────────────
# Value is always None: Saudi Arabia has no engine fallback by design.
_SA_RATE_SELECTION_BASIS = None
_SA_GOSI_BELOW_MIN_BEHAVIOUR = None
_SA_NORMAL_HOURS_DAILY = None
_SA_NORMAL_HOURS_WEEKLY = None
_SA_RAMADAN_HOURS_DAILY = None
_SA_RAMADAN_HOURS_WEEKLY = None
_SA_OVERTIME_BASIC_PREMIUM_PCT = None
_SA_MONTHLY_HOURS_DIVISOR = None
_SA_LOAN_CAP_PCT = None
_SA_DAMAGE_CAP_PCT = None
_SA_AGGREGATE_DEDUCTION_CAP_PCT = None
_SA_GOSI_DUE_DAY = None
_SA_EOS_FIRST_5_YEARS_MONTHS = None
_SA_EOS_AFTER_5_YEARS_MONTHS = None
_SA_EOS_RESIGN_FRAC_UNDER_2 = None
_SA_EOS_RESIGN_FRAC_2_TO_5 = None
_SA_EOS_RESIGN_FRAC_5_TO_10 = None
_SA_EOS_RESIGN_FRAC_10_PLUS = None
_SA_SETTLEMENT_DEADLINE_TERMINATION_DAYS = None
_SA_SETTLEMENT_DEADLINE_RESIGNATION_DAYS = None


class SACalculationBlockedError(MissingComplianceConfigurationError):
    """A Saudi statutory calculation that must not proceed — missing configured
    row, missing or contradictory worker fact, or an unsupported case."""

    def __init__(self, key: str, reason: str, organization_id: int = None):
        super().__init__(key, _COUNTRY, organization_id)
        self.reason = reason
        self.args = (f"Saudi Arabia calculation blocked ({key}): {reason}",)


def _dec(value) -> Decimal:
    if value is None or value == "":
        return ZERO
    return Decimal(str(value))


def _upper(value) -> str:
    return "" if value is None else str(value).strip().upper()


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ("true", "1", "yes", "y")


def _fact(ctx, profile, name):
    """A worker fact from the context, else the statutory profile."""
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
        raise SACalculationBlockedError(key, reason, self.organization_id)

    def require_amount(self, key: str) -> Decimal:
        row = self.rate_map.get(key)
        if row is None:
            self.block(key, "no configured parameter row")
        value = getattr(row, "flat_amount", None)
        if value is None:
            self.block(key, "row has no amount configured")
        return Decimal(str(value))

    def require_text(self, key: str, allowed) -> str:
        row = self.rate_map.get(key)
        if row is None:
            self.block(key, "no configured parameter row")
        value = getattr(row, "text_value", None)
        if value is None or str(value).strip() == "":
            self.block(key, "row has no value configured")
        value = str(value).strip().upper()
        if value not in allowed:
            self.block(key, f"{value!r} is not one of {', '.join(allowed)}")
        return value


# ── currency rounding (configured, never assumed) ───────────────────────────
def _round_amount(value: Decimal, mode: str, precision: int) -> Decimal:
    if precision < 0 or precision > 6:
        raise SACalculationBlockedError(
            "sa_rounding_precision", f"rounding precision {precision} is outside 0-6")
    return value.quantize(Decimal(1).scaleb(-precision), rounding=_DECIMAL_MODE[mode])


def _rounding(pack: _Pack):
    mode = pack.require_text("sa_rounding_mode", _content.ROUNDING_MODES)
    precision = pack.require_amount("sa_rounding_precision")
    if precision != precision.to_integral_value():
        pack.block("sa_rounding_precision", f"precision {precision} is not a whole number")
    return mode, int(precision)


# ── scope, worker class, cohort ─────────────────────────────────────────────
def resolve_worker_class(ctx: PayrollContext, profile, pack: _Pack) -> str:
    """§3 / SA-001 — the GOSI branch selector, an employee-owned fact (never
    inferred from nationality, name or wage). Unsupported classes and special
    categories BLOCK with the reason and the evidence needed."""
    value = _upper(_fact(ctx, profile, "sa_worker_class"))
    if not value:
        pack.block("sa_worker_class",
                   "no worker class is recorded (SAUDI / NON_SAUDI); the GOSI branches depend on it (SA-001)")
    if value not in KNOWN_WORKER_CLASSES:
        pack.block("sa_worker_class",
                   f"unknown worker class {value!r} (expected {', '.join(WORKER_CLASSES)})")
    if value == WORKER_CLASS_GCC:
        pack.block("sa_scope",
                   "GCC nationals are outside the launch scope: the GCC protection-extension "
                   "calculation is not certified (spec §3, SA-001)")
    if value == WORKER_CLASS_DOMESTIC:
        pack.block("sa_scope",
                   "domestic workers / Musaned are excluded from this release (SA-020)")
    category = _upper(_fact(ctx, profile, "sa_special_category"))
    if category not in ORDINARY_CATEGORIES:
        pack.block("sa_scope",
                   f"special category {category!r} is deferred unless separately certified (spec §1, SA-001)")
    return value


def resolve_cohort(ctx: PayrollContext, profile, worker_class: str, pack: _Pack):
    """Spec §3 / SA-005 / SA-006. Saudi workers only: the NEW / LEGACY social-
    insurance system, sourced from authoritative evidence. Non-Saudi workers
    have no cohort (no Saudi pension, no SANED)."""
    if worker_class != WORKER_CLASS_SAUDI:
        return None
    value = _upper(_fact(ctx, profile, "sa_cohort"))
    if not value:
        pack.block("sa_cohort",
                   "the social-insurance cohort (NEW / LEGACY) for this Saudi worker is not recorded; "
                   "it is never inferred from ID or hire date (SA-006)")
    if value not in COHORTS:
        pack.block("sa_cohort", f"unknown cohort {value!r} (expected {', '.join(COHORTS)})")
    evidence = (getattr(profile, "sa_cohort_source_document_id", None) if profile is not None else None) \
        or _fact(ctx, profile, "sa_cohort_evidence_ref")
    if not evidence:
        pack.block("sa_cohort_evidence_ref",
                   f"cohort {value} carries no GOSI / onboarding evidence (SA-005); payroll is blocked "
                   "for this worker until the evidence is recorded")
    return value


# ── contribution month and branch-row selection (SA-007) ───────────────────
def contribution_month(ctx: PayrollContext):
    anchor = getattr(ctx, "period_end", None) or ctx.pay_date
    start = date(anchor.year, anchor.month, 1)
    end = date(anchor.year, anchor.month, calendar.monthrange(anchor.year, anchor.month)[1])
    return start, end


def _overlaps(row, start: date, end: date) -> bool:
    eff_from = getattr(row, "effective_from", None)
    eff_to = getattr(row, "effective_to", None)
    if eff_from is not None and eff_from > end:
        return False
    if eff_to is not None and eff_to < start:
        return False
    return True


def _in_force(row, on: date) -> bool:
    return _overlaps(row, on, on)


def select_gosi_band(slabs, worker_class: str, branch: str, month, basis: str, pack: _Pack):
    """The single GOSI branch row for (worker_class, branch) in the
    contribution month. Zero rows BLOCKS (never another class/branch's rate).
    Two rows in force on the same date is ambiguous content and BLOCKS. A
    month in which the branch's rate changes is resolved ONLY by a signed
    sa_rate_selection_basis — engineering never pro-rates a rate (SA-007)."""
    month_start, month_end = month
    rows = [r for r in (slabs or [])
            if (getattr(r, "rule_type", None) or "") == SA_GOSI_BRANCH_RULE
            and _upper(getattr(r, "filing_status", None)) == worker_class
            and _upper(getattr(r, "tax_regime", None)) == branch
            and _overlaps(r, month_start, month_end)]
    label = f"{worker_class}/{branch} in {month_start:%Y-%m}"
    if not rows:
        pack.block("sa_gosi_branch",
                   f"no GOSI row for {label} — a branch never falls back to another rate")
    transition = len(rows) > 1
    if transition:
        if basis == BASIS_PENDING:
            pack.block("sa_gosi_rate_transition",
                       f"the {branch} rate changes inside {month_start:%Y-%m}; the contribution-month "
                       "selection rule is PENDING_G1 and engineering may not pro-rate it (SA-007, SA-027)")
        on = month_start if basis == BASIS_MONTH_START else month_end
        rows = [r for r in rows if _in_force(r, on)]
        if not rows:
            pack.block("sa_gosi_branch", f"no GOSI row for {label} on the selection date {on}")
    if len(rows) > 1:
        pack.block("sa_gosi_branch", f"{len(rows)} GOSI rows match {label} — ambiguous content")
    return rows[0], transition


# ── contributory wage (spec §5, SA-011/012) ────────────────────────────────
def _gosi_classes(slabs) -> dict:
    out = {}
    for r in slabs or []:
        if (getattr(r, "rule_type", None) or "") != SA_EARNING_CLASS_RULE:
            continue
        if _upper(getattr(r, "tax_regime", None)) != "GOSI":
            continue
        out[_upper(getattr(r, "filing_status", None))] = _upper(getattr(r, "assessment_basis", None))
    return out


def contributory_wage(ctx: PayrollContext, profile, pack: _Pack) -> dict:
    """The REGISTERED GOSI contributory wage when recorded (it is not reduced
    by unpaid absence or disciplinary deductions — spec §5). Otherwise the sum
    of pay components classified INCLUDED for GOSI; a non-zero component that
    is unclassified or REVIEW BLOCKS (an independent, evidenced inclusion flag
    is required — spec §5)."""
    registered = _fact(ctx, profile, "sa_contributory_wage")
    if registered not in (None, "") and _dec(registered) > ZERO:
        return {"wage": _dec(registered), "source": "REGISTERED", "components": []}

    classes = _gosi_classes(getattr(ctx, "slabs", None))
    basic, housing = _dec(ctx.basic), _dec(ctx.hra)
    special, overtime = _dec(ctx.special_allowance), _dec(ctx.overtime)
    in_kind = _dec(getattr(profile, "sa_in_kind_housing_value", None) if profile is not None else None)
    other = _dec(ctx.gross) - basic - housing - special - overtime
    amounts = (
        (COMPONENT_BASIC, basic), (COMPONENT_HOUSING, housing),
        (COMPONENT_HOUSING_IN_KIND, in_kind), (COMPONENT_ALLOWANCE_REGULAR, special),
        (COMPONENT_OVERTIME, overtime), (COMPONENT_OTHER, other if other > ZERO else ZERO),
    )
    wage = ZERO
    components = []
    for component, amount in amounts:
        if amount <= ZERO:
            continue
        treatment = classes.get(component)
        if treatment is None:
            pack.block(f"sa_earning_class:{component}",
                       f"pay component {component} ({amount}) has no GOSI classification row")
        if treatment == "REVIEW":
            pack.block(f"sa_earning_class:{component}",
                       f"pay component {component} ({amount}) is classified REVIEW for GOSI — a signed "
                       "inclusion rule is required before it can count (spec §5); record the registered "
                       "contributory wage instead")
        if treatment not in ("INCLUDED", "EXCLUDED"):
            pack.block(f"sa_earning_class:{component}", f"unknown GOSI treatment {treatment!r}")
        components.append({"component": component, "amount": str(amount), "treatment": treatment})
        if treatment == "INCLUDED":
            wage += amount
    if wage <= ZERO:
        pack.block("sa_contributory_wage",
                   "no registered GOSI contributory wage and no GOSI-included pay component (SA-011)")
    return {"wage": wage, "source": "DERIVED_FROM_CLASSIFICATION", "components": components}


def _branch_base(row, wage: Decimal, below_min: str, branch: str, pack: _Pack):
    floor = getattr(row, "min_amount", None)
    ceiling = getattr(row, "max_amount", None)
    base, floored, capped = wage, False, False
    if floor is not None and _dec(floor) > ZERO and base < _dec(floor):
        if below_min == BELOW_MIN_BLOCK:
            pack.block("sa_gosi_below_minimum",
                       f"contributory wage {wage} is below the {branch} minimum {_dec(floor)} (SA-010); "
                       "correct the registered wage or have G1 sign FLOOR")
        base, floored = _dec(floor), True
    if ceiling is not None and _dec(ceiling) > ZERO and base > _dec(ceiling):
        base, capped = _dec(ceiling), True
    return base, floored, capped, floor, ceiling


def resolve_gosi(ctx: PayrollContext, pack: _Pack, profile) -> dict:
    worker_class = resolve_worker_class(ctx, profile, pack)
    cohort = resolve_cohort(ctx, profile, worker_class, pack)
    mode, precision = _rounding(pack)
    basis = pack.require_text("sa_rate_selection_basis", _content.RATE_SELECTION_BASES)
    below_min = pack.require_text("sa_gosi_below_min_behaviour", _content.BELOW_MIN_BEHAVIOURS)
    wage_info = contributory_wage(ctx, profile, pack)
    wage = wage_info["wage"]
    month = contribution_month(ctx)
    slabs = list(getattr(ctx, "slabs", None) or [])

    if worker_class == WORKER_CLASS_SAUDI:
        pension_regime = PENSION_REGIME_NEW if cohort == COHORT_NEW else PENSION_REGIME_LEGACY
        plan = ((BRANCH_PENSION, pension_regime), (BRANCH_SANED, BRANCH_SANED),
                (BRANCH_OCCUPATIONAL_HAZARDS, BRANCH_OCCUPATIONAL_HAZARDS))
    else:
        # Spec §3/§4: an ordinary non-Saudi worker has no Saudi pension and no
        # SANED — Occupational Hazards (employer) only.
        pension_regime = None
        plan = ((BRANCH_OCCUPATIONAL_HAZARDS, BRANCH_OCCUPATIONAL_HAZARDS),)

    branches = []
    totals = {"pension_employee": ZERO, "pension_employer": ZERO,
              "saned_employee": ZERO, "saned_employer": ZERO, "oh_employer": ZERO}
    any_transition = False
    for branch, regime in plan:
        row, transition = select_gosi_band(slabs, worker_class, regime, month, basis, pack)
        any_transition = any_transition or transition
        base, floored, capped, floor, ceiling = _branch_base(row, wage, below_min, regime, pack)
        ee_pct, er_pct = _dec(getattr(row, "rate_pct", None)), _dec(getattr(row, "employer_rate_pct", None))
        if branch == BRANCH_OCCUPATIONAL_HAZARDS and ee_pct != ZERO:
            pack.block("sa_gosi_branch", "Occupational Hazards is employer-only; the row carries an employee rate")
        ee = _round_amount(ee_pct * base / HUNDRED, mode, precision)
        er = _round_amount(er_pct * base / HUNDRED, mode, precision)
        if branch == BRANCH_PENSION:
            totals["pension_employee"] += ee
            totals["pension_employer"] += er
        elif branch == BRANCH_SANED:
            totals["saned_employee"] += ee
            totals["saned_employer"] += er
        else:
            totals["oh_employer"] += er
        branches.append({
            "branch": branch, "regime": regime, "workerClass": worker_class,
            "ratePct": str(ee_pct), "employerRatePct": str(er_pct),
            "rowFrom": getattr(row, "effective_from", None).isoformat() if getattr(row, "effective_from", None) else None,
            "rowTo": getattr(row, "effective_to", None).isoformat() if getattr(row, "effective_to", None) else None,
            "rowLabel": getattr(row, "rate_label", None) or None,
            "contributoryWage": str(wage), "base": str(base),
            "floor": None if floor is None else str(_dec(floor)),
            "ceiling": None if ceiling is None else str(_dec(ceiling)),
            "floorApplied": floored, "ceilingApplied": capped,
            "employee": str(ee), "employer": str(er),
        })

    return {
        "worker_class": worker_class, "cohort": cohort, "pension_regime": pension_regime,
        "rate_selection_basis": basis, "below_min_behaviour": below_min,
        "rounding_mode": mode, "rounding_precision": precision,
        "contributory_wage": wage, "wage_source": wage_info["source"],
        "wage_components": wage_info["components"],
        "contribution_month": month[0].strftime("%Y-%m"), "rate_transition": any_transition,
        "branches": branches, "totals": totals,
        "employee": totals["pension_employee"] + totals["saned_employee"],
        "employer": totals["pension_employer"] + totals["saned_employer"] + totals["oh_employer"],
    }


# ── labour controls (spec §11) ──────────────────────────────────────────────
def _labour_controls(ctx: PayrollContext, pack: _Pack) -> dict:
    rate_map = ctx.rate_map or {}
    ramadan = _truthy(getattr(ctx, "sa_ramadan", False))
    out = {"deductionsTotal": ZERO}

    orders = getattr(ctx, "sa_deduction_orders", None)
    if orders:
        evaluation = _labour.evaluate_deductions(orders, _dec(ctx.gross), rate_map)
        if evaluation["errors"]:
            pack.block("sa_deductions", "; ".join(evaluation["errors"]) + " (SA-029/SA-030)")
        out["deductions"] = {k: v for k, v in evaluation.items() if k != "errors"}
        out["deductions"]["total"] = str(evaluation["total"])
        out["deductionsTotal"] = evaluation["total"]

    hours = getattr(ctx, "sa_overtime_hours", None)
    if hours is not None and _dec(hours) > ZERO:
        wage = _dec(ctx.basic) + _dec(ctx.hra) + _dec(ctx.special_allowance)
        ot = _labour.overtime_pay(wage, _dec(ctx.basic), _dec(hours), rate_map)
        if ot["status"] != "OK":
            pack.block("sa_overtime", ot["reason"] + " (SA-028)")
        statutory = ot["amount"]
        paid = _dec(ctx.overtime)
        comp_leave = _truthy(getattr(ctx, "sa_overtime_comp_leave_consented", False))
        if not comp_leave and paid < statutory:
            pack.block("sa_overtime_underpaid",
                       f"{hours} approved overtime hours require at least {statutory} (hourly wage + "
                       f"{ot['premiumPct']}% of basic hourly); {paid} is paid (spec §11)")
        out["overtime"] = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in ot.items()}
        out["overtime"]["paid"] = str(paid)
        out["overtime"]["compensatoryLeave"] = comp_leave

    records = getattr(ctx, "sa_work_hours_records", None)
    if records:
        hc = _labour.hours_check(records, rate_map, ramadan=ramadan)
        out["hoursCheck"] = {"status": hc["status"], "breaches": hc.get("breaches") or [],
                             "weeks": hc.get("weeks") or {}}
    return out


def calculate(ctx: PayrollContext) -> dict:
    """Saudi Arabia entry point (standard + enterprise dispatch). NEVER returns
    a `tds` key: ordinary employment salary is STRUCTURAL_NOT_APPLICABLE for
    Saudi payroll income-tax withholding (SA-004)."""
    organization_id = getattr(ctx, "sa_organization_id", None)
    pack = _Pack(ctx.rate_map, organization_id)
    if ctx.pay_date is None:
        pack.block("pay_date", "payment date is a first-class rule-pack key")
    if (ctx.pay_frequency or "").strip().lower() != "monthly":
        pack.block("pay_frequency",
                   f"{ctx.pay_frequency!r} pay is not supported in v1 (monthly-paid workers only; weekly "
                   "pay for daily-paid workers is deferred)")
    profile = getattr(ctx, "sa_statutory_profile", None)
    if profile is None:
        pack.block("sa_statutory_profile", "no Saudi statutory profile in force for the pay date")

    gosi = resolve_gosi(ctx, pack, profile)
    labour = _labour_controls(ctx, pack)
    totals = gosi["totals"]
    other_deductions = labour.pop("deductionsTotal")
    labour["deductionsTotal"] = str(other_deductions)

    trace = {
        "jurisdiction": _COUNTRY,
        "incomeTax": "STRUCTURAL_NOT_APPLICABLE",
        "payDate": ctx.pay_date.isoformat(),
        "contributionMonth": gosi["contribution_month"],
        "workerClass": gosi["worker_class"],
        "cohort": gosi["cohort"],
        "pensionRegime": gosi["pension_regime"],
        "rateSelectionBasis": gosi["rate_selection_basis"],
        "rateTransition": gosi["rate_transition"],
        "belowMinBehaviour": gosi["below_min_behaviour"],
        "roundingMode": gosi["rounding_mode"],
        "roundingPrecision": gosi["rounding_precision"],
        "contributoryWage": str(gosi["contributory_wage"]),
        "contributoryWageSource": gosi["wage_source"],
        "wageComponents": gosi["wage_components"],
        "branches": gosi["branches"],
        "employeeTotal": str(gosi["employee"]),
        "employerTotal": str(gosi["employer"]),
        "otherDeductionsTotal": str(other_deductions),
        "labour": labour,
        "rateKeys": sorted((ctx.rate_map or {}).keys()),
    }

    return {
        "employee_pension": totals["pension_employee"],
        "employer_pension": totals["pension_employer"],
        # SANED -> the generic social-security slots (both sides).
        "social_security": totals["saned_employee"],
        "employer_social_security": totals["saned_employer"],
        # Occupational Hazards -> its own employer-only slot.
        "employer_occupational_hazard": totals["oh_employer"],
        # Validated Labour-Law deductions — deducted from net (standard.py).
        "sa_other_deductions_total": other_deductions,
        "sa_employee_total": gosi["employee"],
        "sa_employer_total": gosi["employer"],
        "sa_worker_class": gosi["worker_class"],
        "sa_cohort": gosi["cohort"],
        "sa_gosi_branches": gosi["branches"],
        "sa_calculation_trace": trace,
        # The whole SA picture as one JSON-safe dict (decimal strings), the
        # shape golden cases assert sa_* fields from and the service snapshots.
        "sa_result": {
            "sa_worker_class": gosi["worker_class"],
            "sa_cohort": gosi["cohort"],
            "sa_pension_regime": gosi["pension_regime"],
            "sa_contributory_wage": str(gosi["contributory_wage"]),
            "sa_contributory_wage_source": gosi["wage_source"],
            "sa_contribution_month": gosi["contribution_month"],
            "sa_rate_transition": gosi["rate_transition"],
            "sa_employee_total": str(gosi["employee"]),
            "sa_employer_total": str(gosi["employer"]),
            "sa_other_deductions_total": str(other_deductions),
            "employee_pension": str(totals["pension_employee"]),
            "employer_pension": str(totals["pension_employer"]),
            "social_security": str(totals["saned_employee"]),
            "employer_social_security": str(totals["saned_employer"]),
            "employer_occupational_hazard": str(totals["oh_employer"]),
            "branches": gosi["branches"],
            "labour": labour,
            "trace": trace,
        },
    }
