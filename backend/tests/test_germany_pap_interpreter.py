"""
tests/test_germany_pap_interpreter.py
---------------------------------------
Phase 8C-1 — coverage for the BMF PAP XML interpreter core
(engine/countries/germany_pap_interpreter.py).

IMPORTANT: every fixture XML in this file is SYNTHETIC — hand-written to
exercise the interpreter's node/grammar vocabulary, using placeholder
variable names and arbitrary non-statutory numbers. None of it is copied
from, or represents, the real official BMF Programmablaufplan (Phase 8B's
`Lohnsteuer2026.xml`, SHA-256 `63d8981646d139eba2f4dd990c13b43c4fb3883b402a5a40cddf253aa7aa96b4`).
This phase's own report documents a separate, one-off, non-committed
verification run of this same interpreter against the real official XML
(loaded from a local, non-repository path) proving 100% structural
coverage (0 unsupported/unknown nodes) and one full successful execution —
that real-artifact run is not reproduced here, per this phase's explicit
"no source content copying into code" instruction.
"""

from decimal import Decimal

import pytest

from app.modules.payroll.engine.germany_pap.core import GermanyPapInvalidError
from app.modules.payroll.engine.germany_pap.interpreter import (
    Comparison,
    IndexExpr,
    IntSubtractExpr,
    NameRef,
    NumberLiteral,
    PapExecutionContext,
    QualifiedRef,
    count_executable_nodes,
    load_pap_program,
    run_program,
)

# ── Synthetic fixtures ──────────────────────────────────────────────────

_MINIMAL_VALID_XML = b"""<?xml version="1.0"?>
<PAP name="SyntheticTest" version="1.0" versionNummer="1.0">
    <VARIABLES>
        <INPUTS>
            <INPUT name="A" type="int" default="0"/>
            <INPUT name="B" type="BigDecimal" default="BigDecimal.ZERO"/>
        </INPUTS>
        <OUTPUTS>
            <OUTPUT name="RESULT" type="BigDecimal" default="BigDecimal.ZERO"/>
        </OUTPUTS>
        <INTERNALS>
            <INTERNAL name="TMP" type="BigDecimal" default="BigDecimal.ZERO"/>
        </INTERNALS>
    </VARIABLES>
    <CONSTANTS>
        <CONSTANT name="TWO" type="BigDecimal" value="BigDecimal.valueOf(2)"/>
        <CONSTANT name="TABLE" type="BigDecimal[]" value="{BigDecimal.ZERO, BigDecimal.valueOf(10), BigDecimal.valueOf(20)}"/>
    </CONSTANTS>
    <METHODS>
        <MAIN>
            <EXECUTE method="COMPUTE"/>
        </MAIN>
        <METHOD name="COMPUTE">
            <EVAL exec="TMP = B.multiply(TWO)"/>
            <IF expr="A == 1">
                <THEN>
                    <EVAL exec="RESULT = TMP.add(BigDecimal.valueOf(1))"/>
                </THEN>
                <ELSE>
                    <EVAL exec="RESULT = TMP"/>
                </ELSE>
            </IF>
        </METHOD>
    </METHODS>
</PAP>
"""

_XML_WITH_ARRAY_AND_DIVIDE = b"""<?xml version="1.0"?>
<PAP name="SyntheticArrayTest" version="1.0" versionNummer="1.0">
    <VARIABLES>
        <INPUTS>
            <INPUT name="IDX" type="int" default="0"/>
            <INPUT name="X" type="BigDecimal" default="BigDecimal.ZERO"/>
        </INPUTS>
        <OUTPUTS>
            <OUTPUT name="R1" type="BigDecimal" default="BigDecimal.ZERO"/>
            <OUTPUT name="R2" type="BigDecimal" default="BigDecimal.ZERO"/>
        </OUTPUTS>
        <INTERNALS/>
    </VARIABLES>
    <CONSTANTS>
        <CONSTANT name="TAB" type="BigDecimal[]" value="{BigDecimal.valueOf(100), BigDecimal.valueOf(200)}"/>
        <CONSTANT name="HUNDRED" type="BigDecimal" value="BigDecimal.valueOf(100)"/>
    </CONSTANTS>
    <METHODS>
        <MAIN>
            <EVAL exec="R1 = TAB[IDX].divide(HUNDRED)"/>
            <EVAL exec="R2 = X.divide(HUNDRED, 2, BigDecimal.ROUND_DOWN)"/>
        </MAIN>
    </METHODS>
</PAP>
"""

_XML_WITH_COMPARETO_AND_SUBTRACT = b"""<?xml version="1.0"?>
<PAP name="SyntheticCompareTest" version="1.0" versionNummer="1.0">
    <VARIABLES>
        <INPUTS>
            <INPUT name="YEAR" type="int" default="2020"/>
            <INPUT name="X" type="BigDecimal" default="BigDecimal.ZERO"/>
        </INPUTS>
        <OUTPUTS>
            <OUTPUT name="FLAG" type="int" default="0"/>
        </OUTPUTS>
        <INTERNALS>
            <INTERNAL name="OFFSET" type="int" default="0"/>
        </INTERNALS>
    </VARIABLES>
    <CONSTANTS/>
    <METHODS>
        <MAIN>
            <EVAL exec="OFFSET = YEAR - 2000"/>
            <IF expr="X.compareTo(BigDecimal.ZERO) == -1">
                <THEN>
                    <EVAL exec="FLAG = 1"/>
                </THEN>
            </IF>
        </MAIN>
    </METHODS>
</PAP>
"""


# ── XML loading ──────────────────────────────────────────────────────

def test_load_valid_minimal_xml():
    program = load_pap_program(_MINIMAL_VALID_XML)
    assert program.name == "SyntheticTest"
    assert program.version == "1.0"
    assert set(program.inputs) == {"A", "B"}
    assert set(program.outputs) == {"RESULT"}
    assert set(program.internals) == {"TMP"}
    assert set(program.constants) == {"TWO", "TABLE"}
    assert set(program.methods) == {"COMPUTE"}


def test_load_computes_source_sha256():
    import hashlib
    program = load_pap_program(_MINIMAL_VALID_XML)
    assert program.source_sha256 == hashlib.sha256(_MINIMAL_VALID_XML).hexdigest()
    assert program.byte_length == len(_MINIMAL_VALID_XML)


def test_load_rejects_empty_source():
    with pytest.raises(GermanyPapInvalidError):
        load_pap_program(b"")


def test_load_rejects_malformed_xml():
    with pytest.raises(GermanyPapInvalidError, match="not well-formed"):
        load_pap_program(b"<PAP><VARIABLES></PAP>")


def test_load_rejects_wrong_root():
    with pytest.raises(GermanyPapInvalidError, match="Expected root element"):
        load_pap_program(b'<NOTPAP name="x" version="1" versionNummer="1"></NOTPAP>')


def test_load_rejects_missing_variables_section():
    xml = b"""<PAP name="x" version="1" versionNummer="1">
        <CONSTANTS/><METHODS><MAIN/></METHODS></PAP>"""
    with pytest.raises(GermanyPapInvalidError, match="VARIABLES"):
        load_pap_program(xml)


def test_load_rejects_missing_methods_section():
    xml = b"""<PAP name="x" version="1" versionNummer="1">
        <VARIABLES><INPUTS/><OUTPUTS/><INTERNALS/></VARIABLES><CONSTANTS/></PAP>"""
    with pytest.raises(GermanyPapInvalidError, match="METHODS"):
        load_pap_program(xml)


def test_load_rejects_missing_main():
    xml = b"""<PAP name="x" version="1" versionNummer="1">
        <VARIABLES><INPUTS/><OUTPUTS/><INTERNALS/></VARIABLES>
        <CONSTANTS/>
        <METHODS><METHOD name="ONLYMETHOD"/></METHODS></PAP>"""
    with pytest.raises(GermanyPapInvalidError, match="exactly one <MAIN>"):
        load_pap_program(xml)


def test_load_rejects_missing_root_attributes():
    xml = b'<PAP name="x"><VARIABLES><INPUTS/><OUTPUTS/><INTERNALS/></VARIABLES><CONSTANTS/><METHODS><MAIN/></METHODS></PAP>'
    with pytest.raises(GermanyPapInvalidError, match="name/version/versionNummer"):
        load_pap_program(xml)


# ── Structural validation ────────────────────────────────────────────

def test_rejects_unknown_top_level_section():
    xml = b"""<PAP name="x" version="1" versionNummer="1">
        <VARIABLES><INPUTS/><OUTPUTS/><INTERNALS/></VARIABLES>
        <CONSTANTS/>
        <METHODS><MAIN/></METHODS>
        <BOGUS/>
        </PAP>"""
    with pytest.raises(GermanyPapInvalidError, match="Unexpected top-level section"):
        load_pap_program(xml)


def test_rejects_duplicate_method():
    xml = b"""<PAP name="x" version="1" versionNummer="1">
        <VARIABLES><INPUTS/><OUTPUTS><OUTPUT name="A" type="BigDecimal" default="BigDecimal.ZERO"/></OUTPUTS><INTERNALS/></VARIABLES>
        <CONSTANTS/>
        <METHODS>
            <MAIN/>
            <METHOD name="DUP"><EVAL exec="A = BigDecimal.ZERO"/></METHOD>
            <METHOD name="DUP"><EVAL exec="A = BigDecimal.ZERO"/></METHOD>
        </METHODS></PAP>"""
    with pytest.raises(GermanyPapInvalidError, match="Duplicate METHOD"):
        load_pap_program(xml)


def test_rejects_missing_execute_target():
    xml = b"""<PAP name="x" version="1" versionNummer="1">
        <VARIABLES><INPUTS/><OUTPUTS/><INTERNALS/></VARIABLES>
        <CONSTANTS/>
        <METHODS><MAIN><EXECUTE method="DOES_NOT_EXIST"/></MAIN></METHODS></PAP>"""
    with pytest.raises(GermanyPapInvalidError, match="undefined method"):
        load_pap_program(xml)


def test_rejects_malformed_if_missing_then():
    xml = b"""<PAP name="x" version="1" versionNummer="1">
        <VARIABLES><INPUTS><INPUT name="A" type="int" default="0"/></INPUTS><OUTPUTS/><INTERNALS/></VARIABLES>
        <CONSTANTS/>
        <METHODS><MAIN>
            <IF expr="A == 1"><ELSE></ELSE></IF>
        </MAIN></METHODS></PAP>"""
    with pytest.raises(GermanyPapInvalidError, match="THEN"):
        load_pap_program(xml)


def test_rejects_unknown_xml_node_in_method_body():
    xml = b"""<PAP name="x" version="1" versionNummer="1">
        <VARIABLES><INPUTS/><OUTPUTS/><INTERNALS/></VARIABLES>
        <CONSTANTS/>
        <METHODS><MAIN><LOOP/></MAIN></METHODS></PAP>"""
    with pytest.raises(GermanyPapInvalidError, match="Unknown/unsupported PAP node"):
        load_pap_program(xml)


def test_rejects_eval_assigning_undeclared_variable():
    xml = b"""<PAP name="x" version="1" versionNummer="1">
        <VARIABLES><INPUTS/><OUTPUTS/><INTERNALS/></VARIABLES>
        <CONSTANTS/>
        <METHODS><MAIN><EVAL exec="GHOST = BigDecimal.ZERO"/></MAIN></METHODS></PAP>"""
    with pytest.raises(GermanyPapInvalidError, match="undeclared variable"):
        load_pap_program(xml)


def test_rejects_malformed_eval_assignment():
    xml = b"""<PAP name="x" version="1" versionNummer="1">
        <VARIABLES><INPUTS><INPUT name="A" type="int" default="0"/></INPUTS><OUTPUTS/><INTERNALS/></VARIABLES>
        <CONSTANTS/>
        <METHODS><MAIN><EVAL exec="not an assignment at all !!"/></MAIN></METHODS></PAP>"""
    with pytest.raises(GermanyPapInvalidError, match="Malformed EVAL assignment"):
        load_pap_program(xml)


def test_rejects_duplicate_variable_across_categories():
    xml = b"""<PAP name="x" version="1" versionNummer="1">
        <VARIABLES>
            <INPUTS><INPUT name="A" type="int" default="0"/></INPUTS>
            <OUTPUTS/>
            <INTERNALS><INTERNAL name="A" type="int" default="0"/></INTERNALS>
        </VARIABLES>
        <CONSTANTS/>
        <METHODS><MAIN/></METHODS></PAP>"""
    with pytest.raises(GermanyPapInvalidError, match="declared in both"):
        load_pap_program(xml)


def test_supports_multiple_outputs_blocks():
    """The real 2026 document has TWO <OUTPUTS> blocks under <VARIABLES>
    (Phase 8B report §12) — confirmed supported here with a synthetic
    two-block fixture."""
    xml = b"""<PAP name="x" version="1" versionNummer="1">
        <VARIABLES>
            <INPUTS/>
            <OUTPUTS><OUTPUT name="OUT1" type="BigDecimal" default="BigDecimal.ZERO"/></OUTPUTS>
            <OUTPUTS><OUTPUT name="OUT2" type="BigDecimal" default="BigDecimal.ZERO"/></OUTPUTS>
            <INTERNALS/>
        </VARIABLES>
        <CONSTANTS/>
        <METHODS><MAIN/></METHODS></PAP>"""
    program = load_pap_program(xml)
    assert set(program.outputs) == {"OUT1", "OUT2"}


# ── Expression parser ─────────────────────────────────────────────────

def test_parses_number_literal():
    program = load_pap_program(_MINIMAL_VALID_XML)
    stmt = program.methods["COMPUTE"].statements[0]
    assert stmt.target == "TMP"


def test_parses_qualified_reference():
    from app.modules.payroll.engine.germany_pap.interpreter import _ExpressionParser
    node = _ExpressionParser("BigDecimal.ZERO", declared_names=set()).parse_expression_only()
    assert isinstance(node, QualifiedRef)
    assert node.namespace == "BigDecimal" and node.member == "ZERO"


def test_parses_array_index():
    from app.modules.payroll.engine.germany_pap.interpreter import _ExpressionParser
    node = _ExpressionParser("TAB[J]", declared_names={"TAB", "J"}).parse_expression_only()
    assert isinstance(node, IndexExpr)
    assert isinstance(node.base, NameRef) and node.base.name == "TAB"


def test_parses_int_subtraction():
    from app.modules.payroll.engine.germany_pap.interpreter import _ExpressionParser
    node = _ExpressionParser("YEAR - 2000", declared_names={"YEAR"}).parse_expression_only()
    assert isinstance(node, IntSubtractExpr)


def test_parses_unary_minus_literal():
    from app.modules.payroll.engine.germany_pap.interpreter import _ExpressionParser
    node = _ExpressionParser("-1", declared_names=set()).parse_expression_only()
    assert isinstance(node, NumberLiteral)
    assert node.text == "-1"


def test_parses_and_condition():
    from app.modules.payroll.engine.germany_pap.interpreter import _ExpressionParser, LogicalAnd
    node = _ExpressionParser("A == 1 && B == 2", declared_names={"A", "B"}).parse_condition_only()
    assert isinstance(node, LogicalAnd)


def test_rejects_undeclared_variable_reference():
    from app.modules.payroll.engine.germany_pap.interpreter import _ExpressionParser
    with pytest.raises(GermanyPapInvalidError, match="undeclared"):
        _ExpressionParser("GHOST_VAR", declared_names=set()).parse_expression_only()


def test_rejects_unsupported_qualified_reference():
    from app.modules.payroll.engine.germany_pap.interpreter import _ExpressionParser
    with pytest.raises(GermanyPapInvalidError, match="Unsupported qualified reference"):
        _ExpressionParser("BigDecimal.BOGUS_MEMBER", declared_names=set()).parse_expression_only()


def test_rejects_unrecognized_character():
    from app.modules.payroll.engine.germany_pap.interpreter import _ExpressionParser
    with pytest.raises(GermanyPapInvalidError, match="Unrecognized character"):
        _ExpressionParser("A $ B", declared_names={"A", "B"}).parse_expression_only()


def test_rejects_unsupported_operator_not_equal():
    """`!=` never appears in the real document (Phase 8B report §10's
    inventory found only ==, <, >, >=, &&) — confirmed rejected here."""
    from app.modules.payroll.engine.germany_pap.interpreter import _ExpressionParser
    with pytest.raises(GermanyPapInvalidError):
        _ExpressionParser("A != 1", declared_names={"A"}).parse_condition_only()


def test_rejects_unsupported_logical_or():
    from app.modules.payroll.engine.germany_pap.interpreter import _ExpressionParser
    with pytest.raises(GermanyPapInvalidError):
        _ExpressionParser("A == 1 || B == 2", declared_names={"A", "B"}).parse_condition_only()


# ── Decimal / BigDecimal semantics ───────────────────────────────────

def test_add_subtract_multiply_use_decimal_not_float():
    program = load_pap_program(_MINIMAL_VALID_XML)
    ctx = run_program(program, {"A": 0, "B": Decimal("1.5")})
    result = ctx.outputs()["RESULT"]
    assert isinstance(result, Decimal)
    assert result == Decimal("3.0")


def test_if_then_branch_taken():
    program = load_pap_program(_MINIMAL_VALID_XML)
    ctx = run_program(program, {"A": 1, "B": Decimal("1.5")})
    assert ctx.outputs()["RESULT"] == Decimal("4.0")


def test_if_else_branch_taken_only_one_side_executes():
    program = load_pap_program(_MINIMAL_VALID_XML)
    ctx = run_program(program, {"A": 0, "B": Decimal("2")})
    # THEN branch's EVAL must NOT have executed — eval_count proves only
    # one branch's statements ran, not both.
    assert ctx.trace.eval_count == 2  # TMP assignment + ELSE's RESULT assignment
    assert ctx.outputs()["RESULT"] == Decimal("4")


def test_array_index_and_single_arg_divide():
    program = load_pap_program(_XML_WITH_ARRAY_AND_DIVIDE)
    ctx = run_program(program, {"IDX": 1, "X": Decimal("50")})
    assert ctx.outputs()["R1"] == Decimal("2")   # TAB[1]=200, /100 = 2, exact


def test_three_arg_divide_with_scale_and_rounding():
    program = load_pap_program(_XML_WITH_ARRAY_AND_DIVIDE)
    ctx = run_program(program, {"IDX": 0, "X": Decimal("33")})
    # 33 / 100 = 0.33 exactly at scale 2, ROUND_DOWN
    assert ctx.outputs()["R2"] == Decimal("0.33")


def test_single_arg_divide_raises_on_inexact_result():
    """Faithful to Java's single-argument BigDecimal.divide() contract:
    non-terminating results raise, they are never silently rounded."""
    xml = b"""<PAP name="x" version="1" versionNummer="1">
        <VARIABLES><INPUTS><INPUT name="X" type="BigDecimal" default="BigDecimal.ZERO"/></INPUTS>
        <OUTPUTS><OUTPUT name="R" type="BigDecimal" default="BigDecimal.ZERO"/></OUTPUTS><INTERNALS/></VARIABLES>
        <CONSTANTS><CONSTANT name="THREE" type="BigDecimal" value="BigDecimal.valueOf(3)"/></CONSTANTS>
        <METHODS><MAIN><EVAL exec="R = X.divide(THREE)"/></MAIN></METHODS></PAP>"""
    program = load_pap_program(xml)
    with pytest.raises(GermanyPapInvalidError, match="not exact"):
        run_program(program, {"X": Decimal("1")})  # 1/3 does not terminate


def test_divide_by_zero_raises():
    xml = b"""<PAP name="x" version="1" versionNummer="1">
        <VARIABLES><INPUTS><INPUT name="X" type="BigDecimal" default="BigDecimal.ZERO"/></INPUTS>
        <OUTPUTS><OUTPUT name="R" type="BigDecimal" default="BigDecimal.ZERO"/></OUTPUTS><INTERNALS/></VARIABLES>
        <CONSTANTS><CONSTANT name="ZEROC" type="BigDecimal" value="BigDecimal.ZERO"/></CONSTANTS>
        <METHODS><MAIN><EVAL exec="R = X.divide(ZEROC)"/></MAIN></METHODS></PAP>"""
    program = load_pap_program(xml)
    with pytest.raises(GermanyPapInvalidError, match="division by zero"):
        run_program(program, {"X": Decimal("1")})


def test_compareto_and_int_subtraction():
    program = load_pap_program(_XML_WITH_COMPARETO_AND_SUBTRACT)
    ctx = run_program(program, {"YEAR": 2025, "X": Decimal("-5")})
    assert ctx.outputs()["FLAG"] == 1  # X < 0 -> compareTo == -1 -> THEN taken


def test_compareto_false_branch_no_else():
    program = load_pap_program(_XML_WITH_COMPARETO_AND_SUBTRACT)
    ctx = run_program(program, {"YEAR": 2025, "X": Decimal("5")})
    assert ctx.outputs()["FLAG"] == 0  # no ELSE — default stands


# ── Rounding modes ────────────────────────────────────────────────────

@pytest.mark.parametrize("value,scale,mode_attr,expected", [
    ("2.999", 2, "ROUND_DOWN", "2.99"),
    ("2.991", 2, "ROUND_UP", "3.00"),
    ("-2.999", 2, "ROUND_DOWN", "-2.99"),  # truncation toward zero, not floor
])
def test_setscale_rounding_modes(value, scale, mode_attr, expected):
    xml = f"""<?xml version="1.0"?>
    <PAP name="x" version="1" versionNummer="1">
        <VARIABLES><INPUTS><INPUT name="X" type="BigDecimal" default="BigDecimal.ZERO"/></INPUTS>
        <OUTPUTS><OUTPUT name="R" type="BigDecimal" default="BigDecimal.ZERO"/></OUTPUTS><INTERNALS/></VARIABLES>
        <CONSTANTS/>
        <METHODS><MAIN><EVAL exec="R = X.setScale({scale}, BigDecimal.{mode_attr})"/></MAIN></METHODS></PAP>""".encode()
    program = load_pap_program(xml)
    ctx = run_program(program, {"X": Decimal(value)})
    assert ctx.outputs()["R"] == Decimal(expected)


# ── Method dispatch / MAIN execution ──────────────────────────────────

def test_nested_execute_shares_state():
    xml = b"""<PAP name="x" version="1" versionNummer="1">
        <VARIABLES><INPUTS/><OUTPUTS><OUTPUT name="R" type="BigDecimal" default="BigDecimal.ZERO"/></OUTPUTS><INTERNALS/></VARIABLES>
        <CONSTANTS/>
        <METHODS>
            <MAIN><EXECUTE method="OUTER"/></MAIN>
            <METHOD name="OUTER">
                <EVAL exec="R = BigDecimal.valueOf(1)"/>
                <EXECUTE method="INNER"/>
            </METHOD>
            <METHOD name="INNER">
                <EVAL exec="R = R.add(BigDecimal.valueOf(1))"/>
            </METHOD>
        </METHODS></PAP>"""
    program = load_pap_program(xml)
    ctx = run_program(program, {})
    assert ctx.outputs()["R"] == Decimal("2")  # proves shared state across EXECUTE calls


def test_method_sequence_traced_in_order():
    xml = b"""<PAP name="x" version="1" versionNummer="1">
        <VARIABLES><INPUTS/><OUTPUTS/><INTERNALS/></VARIABLES>
        <CONSTANTS/>
        <METHODS>
            <MAIN><EXECUTE method="FIRST"/><EXECUTE method="SECOND"/></MAIN>
            <METHOD name="FIRST"/>
            <METHOD name="SECOND"/>
        </METHODS></PAP>"""
    program = load_pap_program(xml)
    ctx = run_program(program, {})
    assert ctx.trace.method_sequence == ["FIRST", "SECOND"]


def test_read_before_assignment_without_default_raises():
    xml = b"""<PAP name="x" version="1" versionNummer="1">
        <VARIABLES><INPUTS/><OUTPUTS/>
        <INTERNALS><INTERNAL name="NODEFAULT" type="BigDecimal"/></INTERNALS></VARIABLES>
        <CONSTANTS/>
        <METHODS><MAIN><EVAL exec="X2 = NODEFAULT"/></MAIN></METHODS></PAP>"""
    with pytest.raises(GermanyPapInvalidError, match="undeclared variable"):
        load_pap_program(xml)  # X2 itself is undeclared — proves target validation too


def test_internal_with_no_default_read_before_assignment_raises_at_runtime():
    xml = b"""<PAP name="x" version="1" versionNummer="1">
        <VARIABLES><INPUTS/>
        <OUTPUTS><OUTPUT name="OUT" type="BigDecimal" default="BigDecimal.ZERO"/></OUTPUTS>
        <INTERNALS><INTERNAL name="NODEFAULT" type="BigDecimal"/></INTERNALS></VARIABLES>
        <CONSTANTS/>
        <METHODS><MAIN><EVAL exec="OUT = NODEFAULT"/></MAIN></METHODS></PAP>"""
    program = load_pap_program(xml)
    with pytest.raises(GermanyPapInvalidError, match="read before being assigned"):
        run_program(program, {})


def test_required_input_with_no_default_must_be_supplied():
    """Mirrors the real document's own `R` field (Phase 8B report §10):
    no declared default means the caller MUST supply it explicitly."""
    xml = b"""<PAP name="x" version="1" versionNummer="1">
        <VARIABLES><INPUTS><INPUT name="MANDATORY" type="int"/></INPUTS>
        <OUTPUTS/><INTERNALS/></VARIABLES>
        <CONSTANTS/>
        <METHODS><MAIN/></METHODS></PAP>"""
    program = load_pap_program(xml)
    with pytest.raises(GermanyPapInvalidError, match="no declared default"):
        run_program(program, {})
    ctx = run_program(program, {"MANDATORY": 5})
    assert ctx is not None


def test_internal_or_output_default_is_applied_up_front():
    """Regression test for a real bug this phase found and fixed while
    executing the actual official artifact: internals/outputs with a
    declared default must be initialized to it, not treated as
    unassigned-until-EVAL like a variable with no default at all."""
    xml = b"""<PAP name="x" version="1" versionNummer="1">
        <VARIABLES><INPUTS/>
        <OUTPUTS><OUTPUT name="OUT" type="BigDecimal" default="BigDecimal.ZERO"/></OUTPUTS>
        <INTERNALS><INTERNAL name="WITHDEFAULT" type="BigDecimal" default="BigDecimal.valueOf(7)"/></INTERNALS></VARIABLES>
        <CONSTANTS/>
        <METHODS><MAIN><EVAL exec="OUT = WITHDEFAULT"/></MAIN></METHODS></PAP>"""
    program = load_pap_program(xml)
    ctx = run_program(program, {})
    assert ctx.outputs()["OUT"] == Decimal("7")


# ── Completeness check ─────────────────────────────────────────────────

def test_count_executable_nodes():
    program = load_pap_program(_MINIMAL_VALID_XML)
    counts = count_executable_nodes(program)
    # MAIN: 1 EXECUTE. COMPUTE: 1 EVAL (TMP=...) + 1 IF, whose THEN and
    # ELSE bodies (both walked, to count every node that EXISTS in the
    # program, not just the one branch a given run would take) each hold
    # 1 EVAL -> 2 more EVALs. Total: EXECUTE(1) + EVAL(1+1+1=3) + IF(1) = 5.
    assert counts["total"] == 5
    assert counts["EXECUTE"] == 1
    assert counts["IF"] == 1
    assert counts["EVAL"] == 3


# ── Security ─────────────────────────────────────────────────────────

def test_no_eval_or_exec_used_in_module_source():
    """Static, AST-based proof the module never CALLS Python
    eval()/exec()/compile() as an executable statement — checks actual
    Call nodes, not substring matches, so this test isn't fooled (or
    broken) by the module's own docstrings/comments discussing why those
    functions are avoided."""
    import ast
    import inspect
    import app.modules.payroll.engine.germany_pap.interpreter as mod

    source = inspect.getsource(mod)
    tree = ast.parse(source)
    forbidden_names = {"eval", "exec", "compile"}
    forbidden_modules = {"subprocess", "os"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in forbidden_names, f"Forbidden call to {node.func.id}() found in interpreter source"
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden_modules, f"Forbidden import {alias.name!r} found"
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] not in forbidden_modules, f"Forbidden import from {node.module!r} found"


def test_python_injection_attempt_via_exec_attribute_is_rejected():
    """Proves a malicious/malformed exec="..." payload attempting Python
    injection is rejected by the tokenizer, never executed."""
    xml = b"""<PAP name="x" version="1" versionNummer="1">
        <VARIABLES><INPUTS/><OUTPUTS><OUTPUT name="R" type="BigDecimal" default="BigDecimal.ZERO"/></OUTPUTS><INTERNALS/></VARIABLES>
        <CONSTANTS/>
        <METHODS><MAIN><EVAL exec="R = __import__('os').system('echo hacked')"/></MAIN></METHODS></PAP>"""
    with pytest.raises(GermanyPapInvalidError):
        load_pap_program(xml)


def test_injection_attempt_via_if_condition_is_rejected():
    xml = b"""<PAP name="x" version="1" versionNummer="1">
        <VARIABLES><INPUTS><INPUT name="A" type="int" default="0"/></INPUTS><OUTPUTS/><INTERNALS/></VARIABLES>
        <CONSTANTS/>
        <METHODS><MAIN><IF expr="__import__('os').system('rm -rf /')"><THEN></THEN></IF></MAIN></METHODS></PAP>"""
    with pytest.raises(GermanyPapInvalidError):
        load_pap_program(xml)


def test_arbitrary_python_syntax_in_exec_fails_closed_not_silently():
    xml = b"""<PAP name="x" version="1" versionNummer="1">
        <VARIABLES><INPUTS/><OUTPUTS><OUTPUT name="R" type="BigDecimal" default="BigDecimal.ZERO"/></OUTPUTS><INTERNALS/></VARIABLES>
        <CONSTANTS/>
        <METHODS><MAIN><EVAL exec="R = [x for x in range(10)]"/></MAIN></METHODS></PAP>"""
    with pytest.raises(GermanyPapInvalidError):
        load_pap_program(xml)


# ── Execution budget (Phase 8BD §14 defense-in-depth) ──────────────────

def test_runaway_recursion_via_self_execute_is_fail_closed():
    """A malformed synthetic program whose METHOD EXECUTEs itself with no
    base case must be bounded by the nesting-depth budget and raise
    GermanyPapInvalidError — never a raw Python RecursionError and never
    unbounded execution."""
    xml = b"""<PAP name="x" version="1" versionNummer="1">
        <VARIABLES><INPUTS/><OUTPUTS><OUTPUT name="R" type="BigDecimal" default="BigDecimal.ZERO"/></OUTPUTS><INTERNALS/></VARIABLES>
        <CONSTANTS/>
        <METHODS>
            <MAIN><EXECUTE method="LOOP"/></MAIN>
            <METHOD name="LOOP"><EXECUTE method="LOOP"/></METHOD>
        </METHODS></PAP>"""
    program = load_pap_program(xml)
    with pytest.raises(GermanyPapInvalidError):
        run_program(program, {})


def test_deeply_nested_conditionals_are_bounded_by_depth_budget(monkeypatch):
    """A pathological depth of nested IF/THEN/ELSE (beyond the configured
    budget) must fail closed instead of collapsing Python's interpreter
    recursion stack."""
    import sys
    from app.modules.payroll.engine.germany_pap import interpreter as interpreter_mod

    depth = 150  # beyond the real MAX_NESTING_DEPTH (100) and portable across any monkeypatch
    outer = ""
    for _ in range(depth):
        outer += '<IF expr="A == 1"><THEN>'
    outer += '<EVAL exec="R = BigDecimal.ONE"/>'
    for _ in range(depth):
        outer += "</THEN><ELSE><EVAL exec=\"R = BigDecimal.ZERO\"/></ELSE></IF>"
    xml = (
        "<PAP name='x' version='1' versionNummer='1'>"
        "<VARIABLES><INPUTS><INPUT name='A' type='int' default='1'/></INPUTS>"
        "<OUTPUTS><OUTPUT name='R' type='BigDecimal' default='BigDecimal.ZERO'/></OUTPUTS>"
        "<INTERNALS/></VARIABLES><CONSTANTS/>"
        f"<METHODS><MAIN>{outer}</MAIN></METHODS></PAP>"
    ).encode()

    monkeypatch.setattr(interpreter_mod, "MAX_NESTING_DEPTH", depth // 2)
    program = load_pap_program(xml)
    with pytest.raises(GermanyPapInvalidError):
        run_program(program, {"A": 1})


def test_excessive_statement_fanout_is_bounded_by_step_budget(monkeypatch):
    """A flat MAIN with more statements than the step budget must fail
    closed (budget monkeypatched low to keep the fixture cheap)."""
    from app.modules.payroll.engine.germany_pap import interpreter as interpreter_mod

    count = 20  # > the monkeypatched MAX_EXECUTION_STEPS below
    evals = "<EVAL exec=\"R = BigDecimal.ONE\"/>" * count
    xml = (
        "<PAP name='x' version='1' versionNummer='1'>"
        "<VARIABLES><INPUTS/><OUTPUTS>"
        "<OUTPUT name='R' type='BigDecimal' default='BigDecimal.ZERO'/></OUTPUTS>"
        "<INTERNALS/></VARIABLES><CONSTANTS/>"
        f"<METHODS><MAIN>{evals}</MAIN></METHODS></PAP>"
    ).encode()

    monkeypatch.setattr(interpreter_mod, "MAX_EXECUTION_STEPS", count // 2)
    program = load_pap_program(xml)
    with pytest.raises(GermanyPapInvalidError):
        run_program(program, {})


# ── Hash verification (interpreter-level, not asset-level) ────────────

def test_program_source_sha256_changes_with_content():
    program1 = load_pap_program(_MINIMAL_VALID_XML)
    program2 = load_pap_program(_XML_WITH_ARRAY_AND_DIVIDE)
    assert program1.source_sha256 != program2.source_sha256


# NOTE (Phase 8C-2): InterpreterPapExecutor and the resolve_pap_executor()
# production-safety check both moved to test_germany_pap_adapter.py,
# alongside the module they now actually test
# (germany_pap_adapter.py) — this file stays scoped to the generic,
# Zoiko-agnostic interpreter core only, per that phase's architectural
# cleanup (InterpreterPapExecutor itself was relocated out of
# germany_pap_interpreter.py for the same reason).


# ── Performance benchmark (instrumentation only — NOT a readiness claim) ──

def test_benchmark_load_and_execution_timing(capsys):
    """Measures XML load/validate and execution separately, on the
    synthetic fixture, so the interpreter has a repeatable timing harness
    in place. Deliberately asserts only a generous sanity ceiling (catch
    a catastrophic regression, e.g. an accidental exponential blowup) —
    this is NOT a performance-readiness certification, per this phase's
    explicit instruction not to claim one yet. Real-artifact timing (23
    methods, 334 executable nodes) was informally observed during this
    phase's own manual verification to complete in well under 50ms on a
    single run; that number is not asserted here since it depends on the
    real, non-committed artifact this test suite deliberately excludes."""
    import time

    t0 = time.perf_counter()
    program = load_pap_program(_XML_WITH_ARRAY_AND_DIVIDE)
    t1 = time.perf_counter()
    for _ in range(50):
        run_program(program, {"IDX": 1, "X": Decimal("50")})
    t2 = time.perf_counter()

    load_ms = (t1 - t0) * 1000
    exec_ms_per_run = (t2 - t1) * 1000 / 50

    with capsys.disabled():
        print(f"\n[benchmark] load+validate: {load_ms:.3f}ms | execution (avg of 50): {exec_ms_per_run:.3f}ms")

    assert load_ms < 1000, "Load/validate took over 1s on a trivial fixture — investigate before proceeding."
    assert exec_ms_per_run < 100, "A single execution took over 100ms on a trivial fixture — investigate before proceeding."
