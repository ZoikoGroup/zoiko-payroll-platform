"""
modules/payroll/engine/countries/shared.py
---------------------------------------------
Genuinely cross-cutting helpers used by every country's calculator —
nothing here is specific to one jurisdiction's rules. Moved verbatim out
of engine/standard.py as part of splitting that file's per-country logic
into its own module per country (engine/countries/{india,us,uk,...}.py).
"""

import ast
import operator
from decimal import Decimal

MONTHS_PER_YEAR = Decimal("12")


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

    tax = Decimal("0")
    for slab in sorted(slabs, key=lambda s: s.min_amount):
        lower = slab.min_amount
        upper = slab.max_amount if slab.max_amount is not None else annual_income
        if annual_income <= lower:
            continue
        taxable_in_band = min(annual_income, upper) - lower
        if taxable_in_band > 0:
            tax += taxable_in_band * (slab.rate_pct / Decimal("100"))
    return tax
