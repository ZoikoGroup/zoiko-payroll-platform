"""
modules/payroll/engine/countries/shared.py
---------------------------------------------
Genuinely cross-cutting helpers used by every country's calculator —
nothing here is specific to one jurisdiction's rules. Moved verbatim out
of engine/standard.py as part of splitting that file's per-country logic
into its own module per country (engine/countries/{india,us,uk,...}.py).
"""

import ast
import logging
import operator
from decimal import Decimal

MONTHS_PER_YEAR = Decimal("12")
_logger = logging.getLogger("zoiko")


class MissingComplianceConfigurationError(Exception):
    """A federal/national-scope statutory parameter has no configured row
    (canonical or org-scoped) for a country that has opted into required-
    configuration validation (see _VALIDATION_ENABLED_COUNTRIES below).

    Plain Exception, not a FastAPI HTTPException — this module is
    deliberately framework/ORM-free (see this file's own docstring) so it
    stays import-safe from anywhere. The service/router layer is
    responsible for catching this and turning it into a proper 4xx
    response (see app.core.exceptions' handler, registered in main.py)."""
    def __init__(self, key: str, country: str, organization_id: int = None):
        self.key = key
        self.country = country
        self.organization_id = organization_id
        super().__init__(
            f"No statutory configuration found for '{key}' ({country}) — "
            f"configure it under Super Admin > Compliance before running payroll for this jurisdiction."
        )


# Per-jurisdiction rollout switch for the fail-fast behavior above — a
# plain in-code set, not a DB-backed flag, deliberately: this module has
# no DB access by design, and this is a rollout switch a developer flips
# per phase, not something an admin should toggle at runtime.
#
# Fallback Removal Fix Plan, Phase 6 rollout log:
#   IN — attempted 2026-09-03, REVERTED same day. Canonical data was
#        confirmed complete (component_key rebate_87a_mrelief/
#        surcharge_mrelief backfilled that day, linked to Active pack
#        IN-PAYROLL-FY2026-27 id=2) — but enabling it broke 35 existing
#        tests immediately, because canonical completeness does NOT imply
#        an EXISTING org's own already-synced ContributionRate rows are
#        complete: sync_org_rates_from_canonical only runs on an org's
#        FIRST use of a jurisdiction, never re-runs when canonical data
#        gains a new key later. The one real India org in the live DB
#        synced its rows before this backfill existed, so it almost
#        certainly lacks rebate_87a_mrelief/surcharge_mrelief today —
#        enabling validation would have broken its very next payroll run.
#        A real fix needs a re-sync mechanism (or a one-time backfill of
#        EVERY existing org's own rows, not just canonical) before this
#        can be safely re-attempted — not done here; flagged for a
#        separate, explicit decision.
#   US — same unresolved risk applies (never actually attempted).
#   UK — also blocked by its tax pack still being Draft (see history above
#        this rewrite) — _find_active_tax_pack only matches status=="Active".
_VALIDATION_ENABLED_COUNTRIES: set[str] = set()

# Per-country rollout switch for real YTD-accumulator-based caps (Canada
# CPP/CPP2/EI's YMPE/YAMPE/MIE, per ZP-TAX-CA-2026-001 §10/§11 — "exact
# year-to-date accumulators," not the current-period-annualized estimate
# engine/countries/canada.py uses today). Same deliberate plain-set
# convention as _VALIDATION_ENABLED_COUNTRIES above: a developer-flipped
# rollout gate, not a runtime admin toggle. service.py's _load_ca_ytd only
# queries/returns YTD data when the country is in this set; canada.py's own
# `ctx.ytd_pensionable_earnings is not None` check is the second,
# independent dormancy gate at the calculation layer — both must be true
# for YTD-based caps to actually apply.
#
# CA — not yet enabled. No backfill of existing PayslipItems is possible
#      (their figures were computed with the isolated-period bug, not just
#      missing metadata), so flipping this mid-tax-year for an org with
#      existing 2026 CA payslips would create a partial-year gap (prior
#      periods' pensionable/insurable earnings excluded from the room
#      calculation for the rest of the year). Flip only at a tax-year
#      boundary (Jan 1) for orgs with existing CA payslips; a CA org
#      onboarding fresh can be enabled immediately.
# US — Social Security wage base / FUTA wage base / Additional Medicare
#      threshold share the identical current-period-annualized bug (see
#      engine/countries/us.py) and are designed to reuse this exact
#      mechanism — not enabled here, tracked as a separate follow-up.
_YTD_ACCUMULATOR_ENABLED_COUNTRIES: set[str] = set()

# ── Pay frequency (generic — any country's calculator may use this) ────────
# PayrollContext.pay_frequency defaults to "Monthly", so
# PERIODS_PER_YEAR["Monthly"] == MONTHS_PER_YEAR by construction — every
# existing calculation (which never set pay_frequency) is completely
# unaffected. Only engine/countries/uk.py currently varies its own
# annualization by this.
PERIODS_PER_YEAR = {
    "Weekly": Decimal("52"),
    "Fortnightly": Decimal("26"),
    "FourWeekly": Decimal("13"),
    "Monthly": MONTHS_PER_YEAR,
}


def resolve_periods_per_year(pay_frequency: str | None) -> Decimal:
    return PERIODS_PER_YEAR.get(pay_frequency or "Monthly", PERIODS_PER_YEAR["Monthly"])


def resolve_period_threshold(annual_threshold: Decimal, pay_frequency: str | None) -> Decimal:
    """An annual statutory threshold (e.g. the NI Primary Threshold),
    converted to the equivalent per-period figure for this pay frequency —
    the reusable piece of "annualize, calculate, de-annualize" that every
    country calculator already does inline, factored out so it isn't
    duplicated once frequency-awareness spreads beyond UK."""
    return annual_threshold / resolve_periods_per_year(pay_frequency)


# ── Government-mandated scalar parameters (Global Payroll Tax Engine) ──────
# A rate_map row (ContributionRate, org-scoped, synced from the Super-
# Admin-owned canonical row of the same component_key) overrides the
# hardcoded per-country default passed in as `default` — Super Admin
# editing e.g. the US Social Security wage base actually reaches the
# calculator. A jurisdiction/org with no such row behaves exactly as if
# this mechanism didn't exist — additive, never a behavior change.

def _param_amount(rate_map: dict, key: str, default: Decimal) -> Decimal:
    row = rate_map.get(key)
    if row is not None and row.flat_amount is not None:
        return row.flat_amount
    return default


def _param_pct(rate_map: dict, key: str, side: str, default: Decimal) -> Decimal:
    row = rate_map.get(key)
    if row is not None:
        value = row.employee_rate_pct if side == "employee" else row.employer_rate_pct
        if value is not None:
            return value
    return default


def _param_text(rate_map: dict, key: str, default: str) -> str:
    """Same convention as _param_amount/_param_pct, for a non-numeric
    configuration value (ContributionRate.text_value) — e.g. UK's pension
    calculation basis. A configured row overrides the hardcoded default;
    no row means unaffected/as-before."""
    row = rate_map.get(key)
    if row is not None and getattr(row, "text_value", None):
        return row.text_value
    return default


def is_parameter_configured(rate_map: dict, key: str, side: str = None) -> bool:
    """Whether `key` resolves from a real configured row rather than
    falling back to a hardcoded default — the same check
    resolve_jurisdiction_parameter already does internally to decide
    whether to log a warning, exposed here so a caller can build a
    fallback-parameter list (Section 16 traceability) WITHOUT changing
    resolve_jurisdiction_parameter's own return shape, which every
    existing call site across every country relies on staying a plain
    scalar."""
    row = rate_map.get(key)
    if row is None:
        return False
    if side is not None:
        return getattr(row, f"{side}_rate_pct", None) is not None
    return row.flat_amount is not None


def resolve_jurisdiction_parameter(
    rate_map: dict,
    key: str,
    default,
    side: str = None,
    country: str = None,
    organization_id: int = None,
):
    """The one central resolver for a named scalar parameter (a wage
    ceiling, standard deduction, rebate cap, threshold, allowance, ...)
    consumed via rate_map — every country calculator in
    engine/countries/*.py calls this instead of calling `_param_amount`/
    `_param_pct` directly.

    It is a thin wrapper, not a re-implementation: the actual "does a
    configured row override the hardcoded constant" logic stays exactly
    where it already was (and was already correct) — `_param_amount`
    for a flat-amount parameter (side=None), `_param_pct` for a
    percentage parameter (side="employee"|"employer"). This function's
    only addition is provenance: it logs a warning, naming the missing
    key/country/org, whenever no configured row exists and the
    hardcoded engine default had to be used — so a compliance gap is
    visible in logs rather than silently invisible, without changing
    what value gets returned.

    Lives here (not in engine/tax_resolver.py, despite the name overlap)
    deliberately: this module has zero dependency on the ORM/database
    layer, which is what lets engine/countries/*.py stay import-safe
    from anywhere. tax_resolver.py imports payroll.models directly —
    routing this function through there would pull the ORM into the
    engine package's module-load chain and reintroduce exactly the kind
    of import coupling this module's isolation already avoids.

    Same call shape as the functions it wraps (`rate_map, key, default`
    for an amount; add `side=` for a percentage), so swapping a call
    site is a rename, not a restructure — no calculation changes as a
    result of adopting this resolver by itself."""
    if side is not None:
        value = _param_pct(rate_map, key, side, default)
        row = rate_map.get(key)
        configured = row is not None and getattr(row, f"{side}_rate_pct", None) is not None
    else:
        value = _param_amount(rate_map, key, default)
        row = rate_map.get(key)
        configured = row is not None and row.flat_amount is not None

    if not configured:
        if country in _VALIDATION_ENABLED_COUNTRIES:
            raise MissingComplianceConfigurationError(key, country, organization_id)
        _logger.warning(
            "[jurisdiction-param-fallback] key=%s country=%s organization_id=%s "
            "no configured row found — using hardcoded default %s",
            key, country, organization_id, default,
        )
    return value


# ── Formula-based tax rules (rule_type="FORMULA") ──────────────────────────
# Not every jurisdiction's income tax is a clean bracket table — Germany's
# real Lohnsteuer is a continuous formula, not flat bands. TABLE_LOOKUP/
# MARGINAL_RATE slabs (every jurisdiction's current data) keep using the
# bracket loop below unchanged; a slab row that opts into rule_type=FORMULA
# is evaluated here instead. Deliberately NOT `eval()` — a restricted AST
# walk that only allows arithmetic on a fixed `income` variable, so a
# formula_expression can never execute arbitrary code.

_SAFE_OPERATORS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval_safe_node(node, variables: dict) -> Decimal:
    if isinstance(node, ast.Expression):
        return _eval_safe_node(node.body, variables)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return Decimal(str(node.value))
    if isinstance(node, ast.Name):
        if node.id in variables:
            return variables[node.id]
        raise ValueError(f"Unknown variable in tax formula: {node.id}")
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPERATORS:
        return _SAFE_OPERATORS[type(node.op)](_eval_safe_node(node.left, variables), _eval_safe_node(node.right, variables))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPERATORS:
        return _SAFE_OPERATORS[type(node.op)](_eval_safe_node(node.operand, variables))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("min", "max"):
        args = [_eval_safe_node(a, variables) for a in node.args]
        return (min if node.func.id == "min" else max)(*args)
    raise ValueError(f"Disallowed expression in tax formula: {ast.dump(node)}")


def evaluate_tax_formula(expression: str, income: Decimal) -> Decimal:
    """Evaluate a stored formula_expression against a taxable `income`.
    Only arithmetic (+ - * / **), parentheses, min()/max(), and the
    `income` variable are permitted."""
    tree = ast.parse(expression, mode="eval")
    result = _eval_safe_node(tree, {"income": income})
    return max(Decimal("0"), Decimal(result))


# ── Generic bracket calculator ──────────────────────────────────────────

def _calculate_annual_tax(annual_income: Decimal, slabs, filing_status: str | None = None) -> Decimal:
    """Progressive slab-based tax on annual income.

    If any slab row opts into rule_type="FORMULA", that row's
    formula_expression is evaluated directly against annual_income instead
    of the bracket-sum loop — one formula row replaces the whole table for
    that jurisdiction (matches how Germany's real Lohnsteuer works: one
    continuous function, not a set of bands).

    `filing_status` (US-specific; NULL for every other jurisdiction and for
    US callers who don't pass one): if AT LEAST ONE slab in the list
    carries a non-NULL `filing_status` (i.e. Super Admin has configured
    filing-status-specific brackets — e.g. separate Single/MFJ/HoH tables),
    only rows matching this employee's filing_status are used, falling
    back to filing-status-agnostic rows if none match. If NO slab carries a
    filing_status at all (every jurisdiction today, and any US org that
    hasn't configured per-filing-status brackets yet), this is a complete
    no-op — bracket_slabs is built exactly as before this parameter
    existed."""
    formula_row = next((s for s in slabs if getattr(s, "rule_type", None) == "FORMULA" and s.formula_expression), None)
    if formula_row is not None:
        return evaluate_tax_formula(formula_row.formula_expression, annual_income)

    # SURCHARGE rows are a tax-on-tax overlay (surcharge % applied to the
    # tax amount above an income threshold — India's high-earner surcharge),
    # not an ordinary income bracket — they're consumed separately (see
    # india.py's _apply_surcharge) and must be excluded here or they'd be
    # double-counted as if they were plain marginal brackets. PT_FLAT rows
    # (India's state-level Professional Tax, resolved additively elsewhere
    # via get_state_scoped_config) are excluded for the same reason — if one
    # ever ends up in this list by mistake (see tax_resolver.py's
    # _pack_has_income_tax_slabs guard, the primary fix), it must not be
    # silently summed as a 0%-rate income bracket.
    bracket_slabs = [s for s in slabs if getattr(s, "rule_type", None) not in ("SURCHARGE", "PT_FLAT")]

    filing_status_tagged = [s for s in bracket_slabs if getattr(s, "filing_status", None) is not None]
    if filing_status_tagged:
        matching = [s for s in filing_status_tagged if s.filing_status == filing_status]
        bracket_slabs = matching if matching else [s for s in bracket_slabs if getattr(s, "filing_status", None) is None]

    if slabs and not bracket_slabs:
        _logger.warning(
            "[income-tax-slabs-unusable] %d configured slab row(s) contained no usable "
            "income-tax bracket (MARGINAL_RATE/FORMULA/TABLE_LOOKUP/FIXED_PLUS_MARGINAL) — "
            "income tax will compute as 0 for every income.",
            len(slabs),
        )

    tax = Decimal("0")
    for slab in sorted(bracket_slabs, key=lambda s: s.min_amount):
        lower = slab.min_amount
        upper = slab.max_amount if slab.max_amount is not None else annual_income
        if annual_income <= lower:
            continue
        taxable_in_band = min(annual_income, upper) - lower
        if taxable_in_band > 0:
            tax += taxable_in_band * (slab.rate_pct / Decimal("100"))
    return tax
