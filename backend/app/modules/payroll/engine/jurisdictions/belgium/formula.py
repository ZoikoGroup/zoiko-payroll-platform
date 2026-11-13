"""Belgium restricted formula grammar (ZP-BE-ENG-001 Block A3; gap note from
Phase 3B: signed formula text is NEVER passed to eval / exec).

A signed formula row (TaxSlab.formula_expression of a KIND_FORMULA key, or of a
band row) is parsed with ``ast.parse(mode="eval")`` and walked by a WHITELIST
evaluator. Allowed:

  * numbers (read from the source text as Decimal — never a binary float)
  * named variables supplied by the engine (unknown names refuse)
  * + - * / and unary + / -
  * parentheses
  * min(...) / max(...) (positional arguments only)
  * comparisons (< <= > >= == !=, chains allowed), ``and`` / ``or`` / ``not``
  * the if-expression ``a if condition else b``

Everything else refuses with FormulaError: attribute access, subscripts, any
other call, lambdas, comprehensions, strings, names that were not supplied,
power, floor division, modulo, bit operators, keywords, starred arguments.
Decimal throughout; rounding is never done here (only pack.rounder(), D8).
"""
from __future__ import annotations

import ast
from decimal import Decimal, DivisionByZero, InvalidOperation
from typing import Mapping

INTERPRETER_VERSION = "BE-FORMULA-1"
_MAX_LENGTH = 2000          # structural guard against pathological input, not content
_MAX_DEPTH = 60

_BINARY = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
           ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b}
_COMPARE = {ast.Lt: lambda a, b: a < b, ast.LtE: lambda a, b: a <= b, ast.Gt: lambda a, b: a > b,
            ast.GtE: lambda a, b: a >= b, ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b}
_FUNCTIONS = {"min": min, "max": max}


class FormulaError(ValueError):
    """A formula that is not in the restricted grammar, or that cannot be
    evaluated (unknown variable, division by zero, wrong types)."""


def _number(node: ast.Constant, source: str) -> Decimal:
    value = node.value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FormulaError("only numbers are allowed as literals")
    text = ast.get_source_segment(source, node) or str(value)
    try:
        return Decimal(text.replace("_", ""))
    except InvalidOperation:
        raise FormulaError("malformed number")


def _eval(node, variables: Mapping[str, Decimal], source: str, depth: int):
    if depth > _MAX_DEPTH:
        raise FormulaError("formula is nested too deeply")
    nxt = depth + 1
    if isinstance(node, ast.Expression):
        return _eval(node.body, variables, source, nxt)
    if isinstance(node, ast.Constant):
        return _number(node, source)
    if isinstance(node, ast.Name):
        if node.id not in variables:
            raise FormulaError(f"unknown variable {node.id!r}")
        value = variables[node.id]
        if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
            raise FormulaError(f"variable {node.id!r} is not a number")
        return Decimal(value)
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _eval(node.left, variables, source, nxt), _eval(node.right, variables, source, nxt)
        _numeric(left, right)
        try:
            return _BINARY[type(node.op)](left, right)
        except (DivisionByZero, InvalidOperation, ZeroDivisionError):
            raise FormulaError("division by zero")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd, ast.Not)):
        operand = _eval(node.operand, variables, source, nxt)
        if isinstance(node.op, ast.Not):
            _boolean(operand)
            return not operand
        _numeric(operand)
        return -operand if isinstance(node.op, ast.USub) else operand
    if isinstance(node, ast.Compare) and all(type(op) in _COMPARE for op in node.ops):
        left = _eval(node.left, variables, source, nxt)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval(comparator, variables, source, nxt)
            _numeric(left, right)
            if not _COMPARE[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
        values = [_eval(v, variables, source, nxt) for v in node.values]
        _boolean(*values)
        return all(values) if isinstance(node.op, ast.And) else any(values)
    if isinstance(node, ast.IfExp):
        test = _eval(node.test, variables, source, nxt)
        _boolean(test)
        return _eval(node.body if test else node.orelse, variables, source, nxt)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
            raise FormulaError("only min() and max() may be called")
        if node.keywords or not node.args or any(isinstance(a, ast.Starred) for a in node.args):
            raise FormulaError("min() / max() take positional numeric arguments only")
        args = [_eval(a, variables, source, nxt) for a in node.args]
        _numeric(*args)
        return _FUNCTIONS[node.func.id](args)
    raise FormulaError(f"{type(node).__name__} is not allowed in a Belgian formula")


def _numeric(*values) -> None:
    if any(isinstance(v, bool) or not isinstance(v, Decimal) for v in values):
        raise FormulaError("a number was expected")


def _boolean(*values) -> None:
    if any(not isinstance(v, bool) for v in values):
        raise FormulaError("a condition (comparison) was expected")


def parse(text: str) -> ast.Expression:
    if not isinstance(text, str) or not text.strip():
        raise FormulaError("the formula is empty")
    if len(text) > _MAX_LENGTH:
        raise FormulaError("the formula is too long")
    try:
        return ast.parse(text.strip(), mode="eval")
    except SyntaxError:
        raise FormulaError("the formula is not valid syntax")


def evaluate_be_formula(text: str, variables: Mapping[str, Decimal]) -> Decimal:
    """The Decimal value of a signed formula with the engine's variables."""
    source = text.strip() if isinstance(text, str) else text
    tree = parse(source)
    value = _eval(tree, dict(variables), source, 0)
    _numeric(value)
    return value


# Short alias for callers outside the engine (an assignment, not a def, so the
# route-registry call graph never links a generic "evaluate" name to it).
evaluate = evaluate_be_formula


def validate(text: str, names) -> None:
    """Parse-time check for the console: grammar + only known variable names."""
    tree = parse(text)
    allowed = (ast.Expression, ast.Constant, ast.Name, ast.Load, ast.BinOp, ast.UnaryOp, ast.Compare, ast.BoolOp,
               ast.IfExp, ast.Call, ast.And, ast.Or, ast.Not, ast.USub, ast.UAdd, *_BINARY, *_COMPARE)
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            raise FormulaError(f"{type(node).__name__} is not allowed in a Belgian formula")
        if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS
                                           or node.keywords):
            raise FormulaError("only min() and max() may be called")
        if isinstance(node, ast.Name) and node.id not in names and node.id not in _FUNCTIONS:
            raise FormulaError(f"unknown variable {node.id!r}")
        if isinstance(node, ast.Constant) and (isinstance(node.value, bool)
                                               or not isinstance(node.value, (int, float))):
            raise FormulaError("only numbers are allowed as literals")
