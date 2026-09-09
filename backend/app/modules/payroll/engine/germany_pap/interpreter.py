"""
modules/payroll/engine/germany_pap/interpreter.py
----------------------------------------------------
Phase 8C-1 — BMF PAP XML interpreter CORE.

(Relocated from `engine/countries/germany_pap_interpreter.py` in Phase
8E-0A into the `engine/germany_pap/` subsystem package, alongside
`core.py`, `adapter.py`, and `golden_vector.py`.)

Loads and executes the official BMF Programmablaufplan XML pseudocode
language identified in Phase 8B (docs/PHASE_8B_GERMANY_PAP_SOURCE_ACQUISITION_REPORT.md)
against the real, independently-re-verified 2026 artifact
(`Lohnsteuer2026.xml`, SHA-256 `63d8981646d139eba2f4dd990c13b43c4fb3883b402a5a40cddf253aa7aa96b4`
as of this phase — see the Phase 8C-1 report for the re-verification record).

SCOPE, EXPLICITLY: this module is the *interpreter core* — a generic
engine capable of loading, validating, and executing any BMF PAP program
written in the closed five-node vocabulary this phase inventoried
(`EVAL`/`IF`/`THEN`/`ELSE`/`EXECUTE`) and the closed expression grammar
found in the actual 2026 XML (§19 of this phase's brief; see the
Phase 8C-1 report §10 for the full inventory: only `==`/`<`/`>`/`>=`/`&&`
appear as condition operators, and only `.add`/`.subtract`/`.multiply`/
`.divide`/`.setScale`/`.compareTo`/`.longValue`/`BigDecimal.valueOf`/
`BigDecimal.ZERO`/`BigDecimal.ONE`/`BigDecimal.ROUND_DOWN`/
`BigDecimal.ROUND_UP` appear anywhere in the document). It is NOT
registered in `resolve_pap_executor()` — Germany production payroll
remains on `UnavailablePapExecutor`, exactly as before.

PHASE 8C-2 UPDATE: this module has ZERO knowledge of any Zoiko-specific
concept (no `PapInputContract`, no `EmployeeStatutoryProfile`, no
`GermanyPapCalculationResult`) — that mapping now lives entirely in
`germany_pap_adapter.py`, which imports this module, never the reverse.
This module remains a pure, artifact-agnostic engine: give it bytes and
an input dict keyed by the PAP's own field names, get back an executed
`PapExecutionContext`. Phase 8C-1 originally included a thin
`InterpreterPapExecutor` here as a placeholder; it has been moved to
`germany_pap_adapter.py` where the Zoiko-specific mapping it depends on
actually belongs (see that module for the real, full 35-input contract
integration).

SECURITY: the XML is treated as untrusted input regardless of its
official origin. No `eval()`/`exec()`/`compile()` is used anywhere in this
module. Every expression is tokenized and parsed into a typed AST by a
hand-written, closed-grammar parser (see `_tokenize`/`_ExpressionParser`
below); any construct outside the inventoried grammar raises
`GermanyPapInvalidError` immediately (fail-closed) rather than being
skipped, approximated, or passed through to a general-purpose evaluator.
`xml.etree.ElementTree` is used for XML parsing — Python's stdlib expat
backend does not resolve external entities or expand DTDs by default, and
this module never sets an entity resolver, so the standard XXE attack
class does not apply; the file is additionally treated as a fixed,
hash-verified artifact (see `PapExecutionEnvironment`/`load_pap_program`),
never as arbitrary runtime-supplied XML.

NO SOURCE CONTENT COPYING: this file contains zero excerpts of the actual
BMF PAP algorithm (no statutory constants, no method bodies) — it is a
generic interpreter for the *language* the PAP happens to be written in.
The actual 2026 algorithm remains an external, versioned, hash-verified
`PapAlgorithmAsset` (Phase 3) — never hardcoded here.
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN, ROUND_UP, DivisionByZero, InvalidOperation, localcontext
from typing import Optional, Union

from app.modules.payroll.engine.germany_pap.core import GermanyPapInvalidError

# ── EXECUTION BUDGET (defense-in-depth, Phase 8BD §14) ─────────────────
# The PAP language is loop-free (EVAL / IF-THEN-ELSE / EXECUTE only), so a
# well-formed artifact always terminates: the official 2026 program has
# exactly 334 static executable nodes, and even full EXECUTE/IF re-entry
# stays well under these bounds. These caps exist solely to bound a
# *pathological* (malformed/malicious synthetic) program that a
# hash-verified asset can never legitimately reach — e.g. a pathological
# depth of nested IFs/EXECUTEs otherwise collapsing Python's interpreter
# recursion, or an unbounded statement fan-out. They are set far above any
# legitimate execution and therefore cannot alter statutory semantics.
MAX_EXECUTION_STEPS = 100_000   # total statement executions across MAIN + recursion
MAX_NESTING_DEPTH = 100         # IF/EXECUTE recursion depth (<< Python's ~1000 limit)

# ═════════════════════════════════════════════════════════════════════
# 1. PAP PROGRAM MODEL
# ═════════════════════════════════════════════════════════════════════
# Typed, immutable representation of one parsed PAP XML document. Built
# once at load time (see load_pap_program), then reused for every
# execution — parsing/validation cost is paid once per PapAlgorithmAsset,
# not per payslip.


@dataclass(frozen=True)
class PapVariableDecl:
    """One <INPUT>/<OUTPUT>/<INTERNAL> declaration."""
    name: str
    type: str                       # "int" | "double" | "BigDecimal" — exactly as declared in the XML
    default_text: Optional[str] = None  # raw default="..." text, unparsed (e.g. "BigDecimal.ZERO", "1")


@dataclass(frozen=True)
class PapConstantDecl:
    """One <CONSTANT> declaration (scalar or array — TAB1-5 are arrays)."""
    name: str
    type: str                       # e.g. "BigDecimal", "BigDecimal[]"
    value_text: str                 # raw value="..." text, unparsed


# ── Expression AST (produced by the restricted parser, §3) ─────────────

@dataclass(frozen=True)
class NumberLiteral:
    text: str


@dataclass(frozen=True)
class NameRef:
    name: str


@dataclass(frozen=True)
class QualifiedRef:
    """A bare `Namespace.MEMBER` reference with no call, e.g.
    `BigDecimal.ZERO`, `BigDecimal.ROUND_DOWN`."""
    namespace: str
    member: str


@dataclass(frozen=True)
class IndexExpr:
    """`base[index]` — used only for the TAB1-5 constant arrays in the
    real 2026 document, but supported generically."""
    base: "ExprNode"
    index: "ExprNode"


@dataclass(frozen=True)
class CallExpr:
    """`base.method(args...)` — covers both `BigDecimal.valueOf(x)`
    (base is a QualifiedRef-style namespace name) and fluent BigDecimal
    method chains like `KVZ.divide(ZAHL2)`."""
    base: "ExprNode"
    method: str
    args: tuple


@dataclass(frozen=True)
class IntSubtractExpr:
    """`left - right` — raw infix subtraction between two `int`-typed
    operands. The ONLY raw arithmetic operator found anywhere in the
    official 2026 document (Phase 8C-1 report §10 update): exactly two
    occurrences, both of the form `<int variable> - <int literal>`,
    computing an array index for the age-relief tables. Deliberately its
    own AST node (not a generic BinOp) — this grammar has no other raw
    arithmetic operator, and int subtraction must never be confused with
    BigDecimal `.subtract()`, which is a completely different operation
    on a completely different type."""
    left: "ExprNode"
    right: "ExprNode"


ExprNode = Union[NumberLiteral, NameRef, QualifiedRef, IndexExpr, CallExpr, IntSubtractExpr]


@dataclass(frozen=True)
class Comparison:
    left: ExprNode
    op: str                          # "==" | "<" | ">" | ">="
    right: ExprNode


@dataclass(frozen=True)
class LogicalAnd:
    left: "CondNode"
    right: "CondNode"


CondNode = Union[Comparison, LogicalAnd]


# ── Statements ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class PapAssignStatement:
    target: str
    expr: ExprNode


@dataclass(frozen=True)
class PapExecuteStatement:
    method_name: str


@dataclass(frozen=True)
class PapIfStatement:
    condition: CondNode
    then_body: tuple  # tuple[PapStatement, ...]
    else_body: tuple  # tuple[PapStatement, ...] — empty tuple if no <ELSE>


PapStatement = Union[PapAssignStatement, PapExecuteStatement, PapIfStatement]


@dataclass(frozen=True)
class PapMethod:
    name: str
    statements: tuple  # tuple[PapStatement, ...]


@dataclass(frozen=True)
class PapProgram:
    """One fully-parsed, fully-validated PAP program. Immutable —
    re-executing it never mutates this object; see PapExecutionContext
    for per-run mutable state."""
    name: str
    version: str
    version_number: str
    inputs: dict            # name -> PapVariableDecl
    outputs: dict           # name -> PapVariableDecl
    internals: dict         # name -> PapVariableDecl
    constants: dict         # name -> PapConstantDecl
    methods: dict           # name -> PapMethod
    main: tuple             # tuple[PapStatement, ...]
    source_sha256: str      # computed from the exact bytes this program was parsed from
    byte_length: int

    @property
    def declared_names(self) -> set:
        """The single shared PAP variable/constant namespace — inputs,
        outputs, internals, and constants all live in one flat namespace
        in the official pseudocode (a bare identifier can refer to any
        of them). Computed once, not stored, so it can never drift from
        the four dicts above."""
        return (
            set(self.inputs) | set(self.outputs) | set(self.internals) | set(self.constants)
        )


# ═════════════════════════════════════════════════════════════════════
# 2. XML LOADER + STRUCTURAL VALIDATOR
# ═════════════════════════════════════════════════════════════════════

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# The only qualified (dotted, no-call) references the real 2026 document
# uses — see Phase 8C-1 report §10 for the full inventory. Anything else
# of the shape `X.Y` with no call parentheses is rejected.
_KNOWN_QUALIFIED_REFS = {
    ("BigDecimal", "ZERO"),
    ("BigDecimal", "ONE"),
    ("BigDecimal", "ROUND_DOWN"),
    ("BigDecimal", "ROUND_UP"),
}

# The only zero-arg-base call form found: BigDecimal.valueOf(x).
_NAMESPACE_STATIC_METHODS = {("BigDecimal", "valueOf")}

# The only fluent instance methods found on a BigDecimal-typed value.
_SUPPORTED_INSTANCE_METHODS = {"add", "subtract", "multiply", "divide", "setScale", "compareTo", "longValue"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GermanyPapInvalidError(message)


def load_pap_program(xml_bytes: bytes) -> PapProgram:
    """Parse and fully structurally validate a BMF PAP XML document.

    Fail-closed: any node, attribute, reference, or expression outside
    the closed vocabulary/grammar this phase inventoried raises
    GermanyPapInvalidError immediately — nothing is silently skipped,
    approximated, or passed through. The returned PapProgram is fully
    ready to execute; no further validation happens at run time except
    the deliberate re-checks noted in `run_program` (declared-name
    lookups, division-by-zero, etc., which are genuine runtime
    conditions, not parse-time omissions)."""
    _require(isinstance(xml_bytes, (bytes, bytearray)) and len(xml_bytes) > 0, "PAP source is empty or not bytes.")

    source_sha256 = hashlib.sha256(xml_bytes).hexdigest()

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise GermanyPapInvalidError(f"PAP source is not well-formed XML: {exc}") from exc

    _require(root.tag == "PAP", f"Expected root element <PAP>, found <{root.tag}>.")
    name = root.attrib.get("name")
    version = root.attrib.get("version")
    version_number = root.attrib.get("versionNummer")
    _require(bool(name and version and version_number), "Root <PAP> is missing name/version/versionNummer.")

    child_tags = [c.tag for c in root]
    _require(
        set(child_tags) <= {"VARIABLES", "CONSTANTS", "METHODS"},
        f"Unexpected top-level section(s) in <PAP>: {sorted(set(child_tags) - {'VARIABLES', 'CONSTANTS', 'METHODS'})}",
    )
    variables_el = root.find("VARIABLES")
    constants_el = root.find("CONSTANTS")
    methods_el = root.find("METHODS")
    _require(variables_el is not None, "Missing required <VARIABLES> section.")
    _require(constants_el is not None, "Missing required <CONSTANTS> section.")
    _require(methods_el is not None, "Missing required <METHODS> section.")

    inputs = _parse_variable_group(variables_el, "INPUTS", "INPUT")
    outputs: dict = {}
    output_blocks = variables_el.findall("OUTPUTS")
    _require(len(output_blocks) >= 1, "No <OUTPUTS> block found under <VARIABLES>.")
    for block in output_blocks:
        for name_, decl in _parse_variable_block(block, "OUTPUT").items():
            _require(name_ not in outputs, f"Duplicate OUTPUT declaration: {name_!r}")
            outputs[name_] = decl
    internals = _parse_variable_group(variables_el, "INTERNALS", "INTERNAL")
    _require(
        set(c.tag for c in variables_el) <= {"INPUTS", "OUTPUTS", "INTERNALS"},
        "Unexpected node directly under <VARIABLES> (expected only INPUTS/OUTPUTS/INTERNALS).",
    )

    constants: dict = {}
    for c in constants_el:
        _require(c.tag == "CONSTANT", f"Unexpected node under <CONSTANTS>: <{c.tag}>")
        cname = c.attrib.get("name")
        _require(bool(cname), "A <CONSTANT> is missing its name attribute.")
        _require(cname not in constants, f"Duplicate CONSTANT declaration: {cname!r}")
        constants[cname] = PapConstantDecl(name=cname, type=c.attrib.get("type", ""), value_text=c.attrib.get("value", ""))

    # ── Shared-namespace duplicate check (inputs/outputs/internals/constants) ──
    seen: dict = {}
    for group_name, group in (("INPUTS", inputs), ("OUTPUTS", outputs), ("INTERNALS", internals), ("CONSTANTS", constants)):
        for vname in group:
            _require(vname not in seen, f"Variable/constant name {vname!r} declared in both {seen.get(vname)} and {group_name}.")
            seen[vname] = group_name

    declared_names = set(inputs) | set(outputs) | set(internals) | set(constants)

    main_els = methods_el.findall("MAIN")
    _require(len(main_els) == 1, f"Expected exactly one <MAIN>, found {len(main_els)}.")
    method_els = methods_el.findall("METHOD")
    _require(
        set(c.tag for c in methods_el) <= {"MAIN", "METHOD"},
        "Unexpected node directly under <METHODS> (expected only MAIN/METHOD).",
    )

    methods: dict = {}
    for m_el in method_els:
        mname = m_el.attrib.get("name")
        _require(bool(mname), "A <METHOD> is missing its name attribute.")
        _require(mname not in methods, f"Duplicate METHOD declaration: {mname!r}")
        methods[mname] = PapMethod(name=mname, statements=tuple(_parse_statements(m_el, declared_names)))

    main_statements = tuple(_parse_statements(main_els[0], declared_names))

    # ── Second pass: every EXECUTE target must resolve to a real METHOD ──
    def _check_execute_targets(statements: tuple) -> None:
        for stmt in statements:
            if isinstance(stmt, PapExecuteStatement):
                _require(
                    stmt.method_name in methods,
                    f"EXECUTE references undefined method {stmt.method_name!r}.",
                )
            elif isinstance(stmt, PapIfStatement):
                _check_execute_targets(stmt.then_body)
                _check_execute_targets(stmt.else_body)

    _check_execute_targets(main_statements)
    for method in methods.values():
        _check_execute_targets(method.statements)

    return PapProgram(
        name=name, version=version, version_number=version_number,
        inputs=inputs, outputs=outputs, internals=internals, constants=constants,
        methods=methods, main=main_statements,
        source_sha256=source_sha256, byte_length=len(xml_bytes),
    )


def _parse_variable_group(variables_el: ET.Element, group_tag: str, item_tag: str) -> dict:
    group_el = variables_el.find(group_tag)
    if group_el is None:
        return {}
    return _parse_variable_block(group_el, item_tag)


def _parse_variable_block(block_el: ET.Element, item_tag: str) -> dict:
    result: dict = {}
    for item in block_el:
        _require(item.tag == item_tag, f"Unexpected node under <{block_el.tag}>: <{item.tag}> (expected <{item_tag}>)")
        vname = item.attrib.get("name")
        _require(bool(vname) and bool(_IDENT_RE.match(vname)), f"Invalid or missing variable name: {vname!r}")
        _require(vname not in result, f"Duplicate {item_tag} declaration: {vname!r}")
        result[vname] = PapVariableDecl(name=vname, type=item.attrib.get("type", ""), default_text=item.attrib.get("default"))
    return result


def _parse_statements(container_el: ET.Element, declared_names: set) -> list:
    statements = []
    for node in container_el:
        if node.tag == "EVAL":
            exec_text = node.attrib.get("exec")
            _require(exec_text is not None, "<EVAL> is missing its exec attribute.")
            statements.append(_parse_assign_statement(exec_text, declared_names))
        elif node.tag == "IF":
            expr_text = node.attrib.get("expr")
            _require(expr_text is not None, "<IF> is missing its expr attribute.")
            children = list(node)
            _require(len(children) >= 1 and children[0].tag == "THEN", "<IF> must contain a <THEN> block first.")
            _require(
                all(c.tag in ("THEN", "ELSE") for c in children) and len(children) <= 2,
                "<IF> may only contain <THEN> followed optionally by <ELSE>.",
            )
            then_body = tuple(_parse_statements(children[0], declared_names))
            else_el = node.find("ELSE")
            else_body = tuple(_parse_statements(else_el, declared_names)) if else_el is not None else ()
            condition = _parse_condition(expr_text, declared_names)
            statements.append(PapIfStatement(condition=condition, then_body=then_body, else_body=else_body))
        elif node.tag == "EXECUTE":
            method_name = node.attrib.get("method")
            _require(bool(method_name), "<EXECUTE> is missing its method attribute.")
            statements.append(PapExecuteStatement(method_name=method_name))
        else:
            raise GermanyPapInvalidError(f"Unknown/unsupported PAP node: <{node.tag}>")
    return statements


def _parse_assign_statement(exec_text: str, declared_names: set) -> PapAssignStatement:
    # Split on the FIRST top-level '=' that is not part of '=='. The
    # official document's exec text is always "TARGET = <expr>" or
    # "TARGET=<expr>" (whitespace-insensitive) — never a compound/chained
    # assignment — confirmed by the Phase 8C-1 grammar inventory.
    m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?!=)(.*)$", exec_text, re.DOTALL)
    _require(bool(m), f"Malformed EVAL assignment: {exec_text!r}")
    target, rhs_text = m.group(1), m.group(2)
    _require(target in declared_names, f"EVAL assigns to undeclared variable: {target!r}")
    expr = _ExpressionParser(rhs_text, declared_names).parse_expression_only()
    return PapAssignStatement(target=target, expr=expr)


def _parse_condition(expr_text: str, declared_names: set) -> CondNode:
    return _ExpressionParser(expr_text, declared_names).parse_condition_only()


# ═════════════════════════════════════════════════════════════════════
# 3. RESTRICTED EXPRESSION PARSER
# ═════════════════════════════════════════════════════════════════════
# A small, hand-written recursive-descent parser for EXACTLY the grammar
# found in the official 2026 XML (Phase 8C-1 report §10's inventory).
# Deliberately NOT a general expression language: unsupported operators/
# tokens raise GermanyPapInvalidError rather than being accepted and
# ignored. No `eval`/`exec`/`compile` anywhere in this class.

_TOKEN_SPEC = [
    ("NUMBER", r"\d+\.\d+|\d+"),
    ("IDENT", r"[A-Za-z_][A-Za-z0-9_]*"),
    ("GE", r">="),
    ("EQ", r"=="),
    ("AND", r"&&"),
    ("LT", r"<"),
    ("GT", r">"),
    ("MINUS", r"-"),
    ("DOT", r"\."),
    ("LPAREN", r"\("),
    ("RPAREN", r"\)"),
    ("LBRACK", r"\["),
    ("RBRACK", r"\]"),
    ("COMMA", r","),
    ("SKIP", r"\s+"),
]
_MASTER_TOKEN_RE = re.compile("|".join(f"(?P<{name}>{pattern})" for name, pattern in _TOKEN_SPEC))


@dataclass(frozen=True)
class _Token:
    kind: str
    text: str


def _tokenize(text: str) -> list:
    tokens = []
    pos = 0
    while pos < len(text):
        m = _MASTER_TOKEN_RE.match(text, pos)
        if not m:
            raise GermanyPapInvalidError(f"Unrecognized character in PAP expression at position {pos}: {text[pos:pos+20]!r}")
        kind = m.lastgroup
        if kind != "SKIP":
            tokens.append(_Token(kind, m.group()))
        pos = m.end()
    tokens.append(_Token("EOF", ""))
    return tokens


class _ExpressionParser:
    """Recursive-descent parser over the closed grammar:

        condition  := comparison ( '&&' comparison )*
        comparison := expression ( '==' | '<' | '>' | '>=' ) expression
        expression := chain ( '-' chain )*                         # int subtraction — the ONLY raw
                                                                     # arithmetic operator in the real
                                                                     # 2026 document (2 occurrences,
                                                                     # both int-array-index computations)
        chain      := primary ( '.' IDENT '(' [args] ')' )*         # fluent chain
        primary    := NUMBER
                    | IDENT '.' IDENT                              # qualified bare ref
                    | IDENT '[' expression ']'                     # array index
                    | IDENT                                        # variable ref
                    | '(' expression ')'
        args       := expression ( ',' expression )*
    """

    def __init__(self, text: str, declared_names: set):
        self._tokens = _tokenize(text)
        self._pos = 0
        self._declared_names = declared_names
        self._source_text = text

    def _peek(self) -> _Token:
        return self._tokens[self._pos]

    def _advance(self) -> _Token:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _expect(self, kind: str) -> _Token:
        tok = self._peek()
        if tok.kind != kind:
            raise GermanyPapInvalidError(
                f"Malformed PAP expression {self._source_text!r}: expected {kind}, found {tok.kind} ({tok.text!r})"
            )
        return self._advance()

    def parse_expression_only(self) -> ExprNode:
        node = self._parse_expression()
        self._expect("EOF")
        return node

    def parse_condition_only(self) -> CondNode:
        node = self._parse_condition()
        self._expect("EOF")
        return node

    def _parse_condition(self) -> CondNode:
        node = self._parse_comparison()
        while self._peek().kind == "AND":
            self._advance()
            right = self._parse_comparison()
            node = LogicalAnd(left=node, right=right)
        return node

    def _parse_comparison(self) -> Comparison:
        left = self._parse_expression()
        tok = self._peek()
        if tok.kind not in ("EQ", "LT", "GT", "GE"):
            raise GermanyPapInvalidError(f"Malformed PAP condition {self._source_text!r}: expected a comparison operator, found {tok.kind} ({tok.text!r})")
        op_token = self._advance()
        op = {"EQ": "==", "LT": "<", "GT": ">", "GE": ">="}[op_token.kind]
        right = self._parse_expression()
        return Comparison(left=left, op=op, right=right)

    def _parse_expression(self) -> ExprNode:
        node = self._parse_chain()
        while self._peek().kind == "MINUS":
            self._advance()
            right = self._parse_chain()
            node = IntSubtractExpr(left=node, right=right)
        return node

    def _parse_chain(self) -> ExprNode:
        node = self._parse_primary()
        while self._peek().kind == "DOT":
            self._advance()
            method_tok = self._expect("IDENT")
            if self._peek().kind == "LPAREN":
                self._advance()
                args = self._parse_args()
                self._expect("RPAREN")
                node = CallExpr(base=node, method=method_tok.text, args=tuple(args))
            else:
                # Bare qualified reference, e.g. BigDecimal.ZERO — only
                # valid directly on a NameRef base (a namespace name).
                if not isinstance(node, NameRef):
                    raise GermanyPapInvalidError(f"Malformed PAP expression {self._source_text!r}: qualified reference on a non-namespace base")
                qualified = QualifiedRef(namespace=node.name, member=method_tok.text)
                if (qualified.namespace, qualified.member) not in _KNOWN_QUALIFIED_REFS:
                    raise GermanyPapInvalidError(
                        f"Unsupported qualified reference {qualified.namespace}.{qualified.member} "
                        f"in PAP expression {self._source_text!r}"
                    )
                node = qualified
        return node

    def _parse_args(self) -> list:
        args = []
        if self._peek().kind == "RPAREN":
            return args
        args.append(self._parse_expression())
        while self._peek().kind == "COMMA":
            self._advance()
            args.append(self._parse_expression())
        return args

    def _parse_primary(self) -> ExprNode:
        tok = self._peek()
        if tok.kind == "MINUS":
            # Unary minus on a numeric literal ONLY — the sole use found
            # in the real 2026 document is `.compareTo(x) == -1` (Java's
            # Comparable "less than" contract). No other unary-minus use
            # exists (binary int subtraction, e.g. `VJAHR - 2004`, is
            # handled one level up in _parse_expression).
            self._advance()
            num_tok = self._expect("NUMBER")
            return NumberLiteral(text="-" + num_tok.text)
        if tok.kind == "NUMBER":
            self._advance()
            return NumberLiteral(text=tok.text)
        if tok.kind == "LPAREN":
            self._advance()
            node = self._parse_expression()
            self._expect("RPAREN")
            return node
        if tok.kind == "IDENT":
            self._advance()
            name = tok.text
            if self._peek().kind == "LBRACK":
                self._advance()
                index = self._parse_expression()
                self._expect("RBRACK")
                base = NameRef(name=name)
                self._validate_name_ref(base)
                return IndexExpr(base=base, index=index)
            ref = NameRef(name=name)
            # Namespace names (currently only "BigDecimal") are validated
            # at the point of qualified/call use, not here, since a bare
            # namespace reference alone is never a complete expression in
            # this grammar.
            if name != "BigDecimal":
                self._validate_name_ref(ref)
            return ref
        raise GermanyPapInvalidError(f"Malformed PAP expression {self._source_text!r}: unexpected token {tok.kind} ({tok.text!r})")

    def _validate_name_ref(self, ref: NameRef) -> None:
        if ref.name not in self._declared_names:
            raise GermanyPapInvalidError(f"Reference to undeclared PAP variable/constant: {ref.name!r}")


# ═════════════════════════════════════════════════════════════════════
# 4. EXECUTION ENVIRONMENT + EVALUATOR
# ═════════════════════════════════════════════════════════════════════

# Java's BigDecimal.ROUND_DOWN/ROUND_UP truncate toward/away from zero —
# identical semantics to Python decimal's ROUND_DOWN/ROUND_UP constants.
# This is a direct, faithful 1:1 mapping, not an approximation (Phase
# 8C-1 report §11/§21).
_ROUNDING_MODE_MAP = {
    "ROUND_DOWN": ROUND_DOWN,
    "ROUND_UP": ROUND_UP,
}


@dataclass
class PapExecutionTrace:
    """Diagnostic record for one interpreter run — method-entry/exit and
    branch-taken events only, never raw statutory input/output values
    (those belong to the caller's own GermanyCalculationTrace, which
    already redacts appropriately). Kept separate from
    GermanyCalculationTrace so the interpreter core has zero dependency
    on that trace's employee/organization-scoped fields."""
    pap_version: Optional[str] = None
    pap_source_sha256: Optional[str] = None
    method_sequence: list = field(default_factory=list)   # ordered list of method names entered
    branch_log: list = field(default_factory=list)         # ordered list of "IF <cond> -> THEN|ELSE"
    eval_count: int = 0
    error: Optional[str] = None


class PapExecutionContext:
    """Mutable per-run state: the shared PAP variable environment plus a
    trace. A fresh context must be created per execution — never reused
    across employees/payslips, since the PAP's own semantics are
    procedural/stateful (EXECUTE shares state with its caller, matching
    the official pseudocode's own convention — see this phase's §16)."""

    def __init__(self, program: PapProgram, inputs: dict):
        self.program = program
        self.trace = PapExecutionTrace(pap_version=program.version, pap_source_sha256=program.source_sha256)
        self._values: dict = {}
        self._steps: int = 0      # total statements executed (Phase 8BD §14 budget)
        self._depth: int = 0      # current IF/EXECUTE nesting depth (Phase 8BD §14 budget)

        # Constants are resolved once, up front — arrays become tuples of
        # Decimal, scalars become their declared-type Python value.
        for name, decl in program.constants.items():
            self._values[name] = _eval_constant_literal(decl)

        # Inputs: caller-supplied values take precedence; any declared
        # input the caller didn't supply falls back to its own default
        # (matching the XML's own default="..." semantics) — never
        # silently zero for a field with no declared default (matching
        # this phase's "undeclared/missing" fail-closed principle for the
        # one official field, `R`, that has no default).
        for name, decl in program.inputs.items():
            if name in inputs:
                self._values[name] = _coerce_input_value(decl, inputs[name])
            elif decl.default_text is not None:
                self._values[name] = _eval_default_literal(decl)
            else:
                raise GermanyPapInvalidError(f"Required PAP input {name!r} was not supplied and has no declared default.")

        # Outputs/internals: the XML's own default="..." attribute means
        # exactly what it says for these too, not only for INPUTS — e.g.
        # the real 2026 document declares <INTERNAL name="EFA" ...
        # default="BigDecimal.ZERO"/> and expects EFA to read as ZERO on
        # any code path that never reaches its own EVAL assignment
        # (confirmed by direct execution against the real artifact during
        # this phase's own testing — treating "has a declared default" as
        # INPUTS-only was a real bug this phase found and fixed, not an
        # assumption). Only a variable with NO declared default remains
        # genuinely "unassigned until EVAL" — reading THAT one before
        # assignment is a real program error, not a modeling gap.
        self._declared_unassigned = set()
        for name, decl in {**program.outputs, **program.internals}.items():
            if decl.default_text is not None:
                self._values[name] = _eval_default_literal(decl)
            else:
                self._declared_unassigned.add(name)

    def get(self, name: str) -> object:
        if name in self._values:
            return self._values[name]
        if name in self._declared_unassigned:
            raise GermanyPapInvalidError(f"PAP variable {name!r} is declared but read before being assigned.")
        raise GermanyPapInvalidError(f"PAP variable {name!r} is not declared.")

    def set(self, name: str, value: object) -> None:
        self._values[name] = value
        self._declared_unassigned.discard(name)

    def outputs(self) -> dict:
        return {name: self._values.get(name) for name in self.program.outputs if name in self._values}


def _eval_constant_literal(decl: PapConstantDecl) -> object:
    """CONSTANT value="..." text is a small, fixed set of literal shapes
    in the real 2026 document — either a BigDecimal array literal
    `{BigDecimal.ZERO, BigDecimal.valueOf(x), ...}` or a scalar
    `BigDecimal.ONE`/`BigDecimal.valueOf(n)`. Parsed with the SAME
    restricted expression parser as EVAL/IF (never eval()), just applied
    to each comma-separated element inside the outer braces for arrays."""
    text = decl.value_text.strip()
    if text.startswith("{") and text.endswith("}"):
        inner = text[1:-1]
        elements = _split_top_level_commas(inner)
        values = []
        for element in elements:
            node = _ExpressionParser(element.strip(), declared_names=set()).parse_expression_only()
            values.append(_evaluate_constant_expr(node))
        return tuple(values)
    node = _ExpressionParser(text, declared_names=set()).parse_expression_only()
    return _evaluate_constant_expr(node)


def _split_top_level_commas(text: str) -> list:
    parts, depth, current = [], 0, []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current))
    return parts


def _evaluate_constant_expr(node: ExprNode) -> Decimal:
    """Constants only ever reference literals/BigDecimal.valueOf/BigDecimal.ZERO
    /BigDecimal.ONE — never other variables — so this is evaluated with an
    empty environment/context (any NameRef here is a genuine authoring
    error in the artifact and correctly fails closed)."""
    return _evaluate_expr(node, context=None)


def _eval_default_literal(decl: PapVariableDecl) -> object:
    text = (decl.default_text or "").strip()
    if decl.type == "int":
        _require(bool(re.match(r"^-?\d+$", text)), f"Invalid int default for {decl.name!r}: {text!r}")
        return int(text)
    if decl.type == "double":
        return float(text) if text not in ("", None) else 0.0
    node = _ExpressionParser(text, declared_names=set()).parse_expression_only()
    return _evaluate_constant_expr(node)


def _coerce_input_value(decl: PapVariableDecl, value: object) -> object:
    if decl.type == "int":
        return int(value)
    if decl.type == "double":
        return float(value)
    # BigDecimal-typed input — always represented as Decimal internally.
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


# ── Expression evaluation ───────────────────────────────────────────

def _evaluate_expr(node: ExprNode, context: Optional[PapExecutionContext]):
    if isinstance(node, NumberLiteral):
        return Decimal(node.text) if "." in node.text else int(node.text)
    if isinstance(node, NameRef):
        if context is None:
            raise GermanyPapInvalidError(f"Cannot resolve variable {node.name!r} outside an execution context.")
        return context.get(node.name)
    if isinstance(node, QualifiedRef):
        if node.namespace != "BigDecimal":
            raise GermanyPapInvalidError(f"Unsupported namespace: {node.namespace!r}")
        if node.member == "ZERO":
            return Decimal(0)
        if node.member == "ONE":
            return Decimal(1)
        if node.member in _ROUNDING_MODE_MAP:
            return _ROUNDING_MODE_MAP[node.member]
        raise GermanyPapInvalidError(f"Unsupported BigDecimal member: {node.member!r}")
    if isinstance(node, IndexExpr):
        base_value = _evaluate_expr(node.base, context)
        index_value = _evaluate_expr(node.index, context)
        if not isinstance(base_value, tuple):
            raise GermanyPapInvalidError("Attempted to index a non-array PAP value.")
        if not isinstance(index_value, int):
            raise GermanyPapInvalidError("PAP array index must evaluate to an int.")
        if not (0 <= index_value < len(base_value)):
            raise GermanyPapInvalidError(f"PAP array index {index_value} out of range (length {len(base_value)}).")
        return base_value[index_value]
    if isinstance(node, CallExpr):
        return _evaluate_call(node, context)
    if isinstance(node, IntSubtractExpr):
        left = _evaluate_expr(node.left, context)
        right = _evaluate_expr(node.right, context)
        if not (isinstance(left, int) and isinstance(right, int)):
            raise GermanyPapInvalidError(
                f"Raw '-' subtraction requires two int operands (got {type(left).__name__}, {type(right).__name__})."
            )
        return left - right
    raise GermanyPapInvalidError(f"Unsupported expression node: {type(node).__name__}")


def _evaluate_call(node: CallExpr, context: Optional[PapExecutionContext]):
    # Static namespace call: BigDecimal.valueOf(x)
    if isinstance(node.base, NameRef) and node.base.name == "BigDecimal":
        if node.method != "valueOf":
            raise GermanyPapInvalidError(f"Unsupported static BigDecimal method: {node.method!r}")
        _require(len(node.args) == 1, "BigDecimal.valueOf() must take exactly one argument.")
        arg = _evaluate_expr(node.args[0], context)
        return Decimal(str(arg))

    base_value = _evaluate_expr(node.base, context)
    if node.method not in _SUPPORTED_INSTANCE_METHODS:
        raise GermanyPapInvalidError(f"Unsupported PAP method: .{node.method}()")
    if not isinstance(base_value, Decimal):
        raise GermanyPapInvalidError(f".{node.method}() called on a non-BigDecimal value ({type(base_value).__name__}).")

    args = [_evaluate_expr(a, context) for a in node.args]

    if node.method == "add":
        _require(len(args) == 1 and isinstance(args[0], Decimal), ".add() requires exactly one BigDecimal argument.")
        return base_value + args[0]
    if node.method == "subtract":
        _require(len(args) == 1 and isinstance(args[0], Decimal), ".subtract() requires exactly one BigDecimal argument.")
        return base_value - args[0]
    if node.method == "multiply":
        _require(len(args) == 1 and isinstance(args[0], Decimal), ".multiply() requires exactly one BigDecimal argument.")
        return base_value * args[0]
    if node.method == "divide":
        return _bigdecimal_divide(base_value, args)
    if node.method == "setScale":
        _require(
            len(args) == 2 and isinstance(args[0], int) and args[1] in _ROUNDING_MODE_MAP.values(),
            ".setScale() requires (int scale, BigDecimal.ROUND_DOWN|ROUND_UP).",
        )
        quantum = Decimal(1).scaleb(-args[0])
        return base_value.quantize(quantum, rounding=args[1])
    if node.method == "compareTo":
        _require(len(args) == 1 and isinstance(args[0], Decimal), ".compareTo() requires exactly one BigDecimal argument.")
        if base_value < args[0]:
            return -1
        if base_value > args[0]:
            return 1
        return 0
    if node.method == "longValue":
        _require(len(args) == 0, ".longValue() takes no arguments.")
        return int(base_value.to_integral_value(rounding=ROUND_DOWN))
    raise GermanyPapInvalidError(f"Unsupported PAP method: .{node.method}()")


def _bigdecimal_divide(dividend: Decimal, args: list):
    """Faithfully replicates the two forms found in the official 2026
    document (Phase 8C-1 report §10):

      .divide(x)                    — EXACT division only. Java's single-
                                       argument BigDecimal.divide() throws
                                       ArithmeticException if the result is
                                       non-terminating; this is preserved
                                       exactly (fail-closed), not
                                       approximated with Python Decimal's
                                       default context rounding.
      .divide(x, scale, roundMode)  — division to an explicit scale with
                                       an explicit rounding mode.

    No other arities are supported."""
    if len(args) == 1:
        divisor = args[0]
        _require(isinstance(divisor, Decimal), ".divide() argument must be a BigDecimal.")
        if divisor == 0:
            raise GermanyPapInvalidError("PAP division by zero (.divide()).")
        with localcontext() as ctx:
            ctx.traps[InvalidOperation] = True
            # A generous but finite precision — if the division does not
            # terminate within this many significant digits, Java's own
            # exact-division semantics would also have thrown, so this is
            # a faithful (not approximate) rejection, not a silent
            # truncation.
            ctx.prec = 50
            result = dividend / divisor
            # Verify exactness: re-multiplying must reproduce the dividend
            # exactly, matching Java's own "exact or throw" contract.
            if (result * divisor) != dividend:
                raise GermanyPapInvalidError(
                    f"PAP division {dividend}/{divisor} is not exact — the official "
                    "single-argument BigDecimal.divide() would raise ArithmeticException here."
                )
            return result
    if len(args) == 3:
        divisor, scale, rounding = args
        _require(isinstance(divisor, Decimal), ".divide() argument must be a BigDecimal.")
        _require(isinstance(scale, int), ".divide() scale argument must be an int.")
        _require(rounding in _ROUNDING_MODE_MAP.values(), ".divide() rounding argument must be BigDecimal.ROUND_DOWN|ROUND_UP.")
        if divisor == 0:
            raise GermanyPapInvalidError("PAP division by zero (.divide()).")
        with localcontext() as ctx:
            ctx.prec = 50
            raw = dividend / divisor
        quantum = Decimal(1).scaleb(-scale)
        return raw.quantize(quantum, rounding=rounding)
    raise GermanyPapInvalidError(f".divide() called with unsupported argument count: {len(args)}")


def _evaluate_condition(node: CondNode, context: PapExecutionContext) -> bool:
    if isinstance(node, LogicalAnd):
        return _evaluate_condition(node.left, context) and _evaluate_condition(node.right, context)
    if isinstance(node, Comparison):
        left = _evaluate_expr(node.left, context)
        right = _evaluate_expr(node.right, context)
        if node.op == "==":
            return left == right
        if node.op == "<":
            return left < right
        if node.op == ">":
            return left > right
        if node.op == ">=":
            return left >= right
        raise GermanyPapInvalidError(f"Unsupported comparison operator: {node.op!r}")
    raise GermanyPapInvalidError(f"Unsupported condition node: {type(node).__name__}")


# ═════════════════════════════════════════════════════════════════════
# 5. METHOD DISPATCH / MAIN EXECUTION
# ═════════════════════════════════════════════════════════════════════

def _execute_statements(statements: tuple, context: PapExecutionContext, program: PapProgram, _depth: int = 0) -> None:
    for stmt in statements:
        context._steps += 1
        if context._steps > MAX_EXECUTION_STEPS:
            raise GermanyPapInvalidError(
                f"PAP execution exceeded the step budget ({MAX_EXECUTION_STEPS} statements) — "
                "aborting to bound runaway execution."
            )
        if isinstance(stmt, PapAssignStatement):
            value = _evaluate_expr(stmt.expr, context)
            context.set(stmt.target, value)
            context.trace.eval_count += 1
        elif isinstance(stmt, PapIfStatement):
            taken = _evaluate_condition(stmt.condition, context)
            context.trace.branch_log.append("THEN" if taken else "ELSE")
            _enter_nested(
                _execute_statements,
                stmt.then_body if taken else stmt.else_body,
                context, program, _depth + 1,
            )
        elif isinstance(stmt, PapExecuteStatement):
            context.trace.method_sequence.append(stmt.method_name)
            method = program.methods[stmt.method_name]  # existence already guaranteed by load_pap_program
            _enter_nested(_execute_statements, method.statements, context, program, _depth + 1)
        else:
            raise GermanyPapInvalidError(f"Unsupported statement type during execution: {type(stmt).__name__}")


def _enter_nested(fn, *args) -> None:
    """Bounds IF/EXECUTE recursion depth. Called only for recursion into a
    nested statement body or a METHOD — the loop itself stays in
    `_execute_statements` (which never recursively re-invokes itself
    directly). Kept as a tiny helper so the depth guard is a single,
    auditable choke point instead of duplicated inline checks."""
    context = args[1]
    if context._depth + 1 > MAX_NESTING_DEPTH:
        raise GermanyPapInvalidError(
            f"PAP execution exceeded the nesting-depth budget ({MAX_NESTING_DEPTH}) — "
            "aborting to bound runaway recursion."
        )
    context._depth += 1
    try:
        fn(*args)
    finally:
        context._depth -= 1


def run_program(program: PapProgram, inputs: dict) -> PapExecutionContext:
    """Execute a fully-validated PapProgram's MAIN entry point against a
    fresh PapExecutionContext, following the XML's statement order
    exactly — no reordering, no dead-code elimination, no
    "optimization" of any kind, per this phase's explicit instruction.
    Returns the context so the caller can read `.outputs()` and
    `.trace`."""
    context = PapExecutionContext(program, inputs)
    try:
        _execute_statements(program.main, context, program)
    except GermanyPapInvalidError as exc:
        context.trace.error = str(exc)
        raise
    return context


# ═════════════════════════════════════════════════════════════════════
# 6. COMPLETENESS CHECK (Phase 8C-1 §49)
# ═════════════════════════════════════════════════════════════════════

def count_executable_nodes(program: PapProgram) -> dict:
    """Walks every statement in MAIN and every METHOD, returning counts
    of total/EVAL/IF/EXECUTE nodes. Since `load_pap_program` already
    raises on any node outside {EVAL, IF, EXECUTE} (via `_parse_statements`'s
    closing `else: raise`), a program that loads successfully at all has,
    by construction, zero unsupported/unknown executable nodes — this
    function exists to produce the explicit, auditable count this phase's
    completeness test requires, not to perform new validation."""
    counts = {"total": 0, "EVAL": 0, "IF": 0, "EXECUTE": 0}

    def walk(statements: tuple) -> None:
        for stmt in statements:
            counts["total"] += 1
            if isinstance(stmt, PapAssignStatement):
                counts["EVAL"] += 1
            elif isinstance(stmt, PapIfStatement):
                counts["IF"] += 1
                walk(stmt.then_body)
                walk(stmt.else_body)
            elif isinstance(stmt, PapExecuteStatement):
                counts["EXECUTE"] += 1

    walk(program.main)
    for method in program.methods.values():
        walk(method.statements)
    return counts

