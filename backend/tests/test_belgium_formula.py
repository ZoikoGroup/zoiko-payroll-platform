"""Belgium (ZP-BE-ENG-001) Block A3: the restricted formula grammar.

Signed formula text is never passed to eval / exec: an AST whitelist evaluates
numbers, supplied variables, + - * /, parentheses, min / max, comparisons and
the if-expression; every other construct refuses. Values are TEST ONLY."""
from decimal import Decimal

import pytest

VARS = {"x": Decimal("1000"), "rate": Decimal("10.00"), "tax": Decimal("93")}


def _f():
    from app.modules.payroll.engine.jurisdictions.belgium import formula

    return formula


@pytest.mark.parametrize("text, expected", [
    ("x * rate / 100", "100"), ("(x - 400) * 0.1", "60"), ("-x + 1000", "0"), ("+tax", "93"),
    ("min(x, tax, 50)", "50"), ("max(x, tax)", "1000"),
    ("100 if x > 500 else 0", "100"), ("1 if 0 < x <= 1000 else 2", "1"), ("1 if x == 1000 and tax != 0 else 2", "1"),
    ("1 if x < 0 or tax > 90 else 2", "1"), ("1 if not x < 0 else 2", "1"), ("0.1 + 0.2", "0.3"),
])
def test_allowed_constructs_evaluate_in_decimal(text, expected):
    value = _f().evaluate(text, VARS)
    assert isinstance(value, Decimal) and value == Decimal(expected)


def test_literals_are_exact_decimals_not_binary_floats():
    assert _f().evaluate("0.1 + 0.2", {}) == Decimal("0.3")


@pytest.mark.parametrize("text", [
    "__import__('os').system('echo')", "x.real", "x.__class__", "abs(x)", "round(x)", "eval('1')", "exec('1')",
    "open('f')", "(lambda: 1)()", "[x][0]", "{'a': 1}", "'text'", "x ** 2", "x // 2", "x % 2", "x & 1",
    "x << 1", "[i for i in (1,)]", "min(x, key=tax)", "min(*[x])", "unknown + 1", "True", "None",
    "x if 'a' else 1", "x if x else 1", "not x", "min()", "(x := 1)", "f'{x}'", "x @ x", "~x",
])
def test_every_forbidden_construct_refuses(text):
    with pytest.raises(_f().FormulaError):
        _f().evaluate(text, VARS)


@pytest.mark.parametrize("text", ["", "   ", "x +", "1 +* 2", "x" * 3000])
def test_empty_malformed_or_oversized_formulas_refuse(text):
    with pytest.raises(_f().FormulaError):
        _f().evaluate(text, VARS)


def test_division_by_zero_refuses():
    with pytest.raises(_f().FormulaError, match="division by zero"):
        _f().evaluate("x / (tax - 93)", VARS)


def test_deep_nesting_refuses():
    with pytest.raises(_f().FormulaError):
        _f().evaluate("-" * 80 + "x", VARS)       # each unary minus is one AST level


def test_a_non_number_variable_refuses():
    with pytest.raises(_f().FormulaError):
        _f().evaluate("x + 1", {"x": "1000"})
    with pytest.raises(_f().FormulaError):
        _f().evaluate("x + 1", {"x": True})


def test_validate_checks_grammar_and_names_without_evaluating():
    f = _f()
    f.validate("x / (tax - tax) if x > 0 else 0", ("x", "tax"))          # no division happens at validation
    for bad in ("y + 1", "abs(x)", "x.real", "x ** 2", "'a'"):
        with pytest.raises(f.FormulaError):
            f.validate(bad, ("x", "tax"))


def test_the_module_never_calls_eval_or_exec():
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(_f()))
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not called & {"eval", "exec", "compile", "__import__"}
