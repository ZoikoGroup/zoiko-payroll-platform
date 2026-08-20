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

def _calculate_annual_tax(annual_income: Decimal, slabs) -> Decimal:
    """Progressive slab-based tax on annual income.

    If any slab row opts into rule_type="FORMULA", that row's
    formula_expression is evaluated directly against annual_income instead
    of the bracket-sum loop — one formula row replaces the whole table for
    that jurisdiction (matches how Germany's real Lohnsteuer works: one
    continuous function, not a set of bands)."""
    formula_row = next((s for s in slabs if getattr(s, "rule_type", None) == "FORMULA" and s.formula_expression), None)
    if formula_row is not None:
        return evaluate_tax_formula(formula_row.formula_expression, annual_income)

    # SURCHARGE rows are a tax-on-tax overlay (surcharge % applied to the
    # tax amount above an income threshold — India's high-earner surcharge),
    # not an ordinary income bracket — they're consumed separately (see
    # india.py's _apply_surcharge) and must be excluded here or they'd be
    # double-counted as if they were plain marginal brackets.
    bracket_slabs = [s for s in slabs if getattr(s, "rule_type", None) != "SURCHARGE"]

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
