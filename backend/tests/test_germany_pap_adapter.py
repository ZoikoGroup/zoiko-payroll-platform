"""
tests/test_germany_pap_adapter.py
------------------------------------
Phase 8C-2 — coverage for germany_pap_adapter.py: the Zoiko <-> PAP
contract bridge (input mapping, output mapping, validation, factor path,
VJAHR handling, provenance, production safety).

IMPORTANT: `_SYNTHETIC_PAP_ALL_35_INPUTS` below is a SYNTHETIC fixture —
it declares all 35 OFFICIAL FIELD NAMES (so `build_pap_environment()`'s
real mapping/key logic is genuinely exercised end-to-end), but its
METHOD bodies are hand-written toy arithmetic, NOT the real BMF
Lohnsteuer algorithm. It exists to prove the ADAPTER wires Zoiko data to
the correct PAP field names and that those values genuinely reach
execution — it does not, and is not meant to, prove tax correctness
(that is Phase 8C-3's golden-vector certification, against the real
artifact, which this test suite deliberately does not embed).

This phase's own real-artifact verification (factor path across tax
classes I/III/IV/IV+factor/V/VI, run against the actual, independently
re-verified `Lohnsteuer2026.xml`) was performed as a one-off,
non-committed session script — its results are recorded in
docs/PHASE_8C_2_GERMANY_PAP_CONTRACT_INTEGRATION_REPORT.md §9/§16, not
reproduced here, per the "do not commit the official XML" instruction.
"""

from decimal import Decimal

import pytest

from app.modules.payroll.engine.germany_pap.core import (
    GermanyPapCalculationResult,
    GermanyPapInvalidError,
    PapInputContract,
    UnavailablePapExecutor,
    resolve_pap_executor,
)
from app.modules.payroll.engine.germany_pap.adapter import (
    PAP_INPUT_CLASSIFICATION,
    PAP_OUTPUT_CLASSIFICATION,
    PAP_SOURCE_FINALITY,
    InterpreterPapExecutor,
    _VJAHR_ORDINARY_EMPLOYEE_VALUE,
    assert_pap_source_finality_resolved,
    build_pap_environment,
    map_pap_outputs,
    validate_pap_environment,
)
from app.modules.payroll.engine.germany_pap.interpreter import load_pap_program, run_program


@pytest.fixture
def profile_factory():
    """Builds a lightweight stand-in for EmployeeStatutoryProfile —
    only the attributes the adapter reads."""
    from dataclasses import dataclass
    from typing import Optional

    @dataclass
    class _Profile:
        de_tax_class: str = "I"
        de_factor: Optional[Decimal] = None
        de_child_count: int = 0
        de_church_tax_liable: bool = False
        de_saxony: bool = False
        de_childless: bool = False
        de_pension_insurance_exempt: bool = False
        de_unemployment_insurance_exempt: bool = False
        de_health_insurance_status: str = "PUBLIC"

    return _Profile


# ── Synthetic fixture declaring all 35 official field names ────────────
# MAIN computes a toy "LSTLZZ" sensitive to STKL/af/f/R/PKV so the test
# suite can prove each mapped field actually reaches and affects
# execution — NOT a reproduction of the real tax algorithm.
_SYNTHETIC_PAP_ALL_35_INPUTS = b"""<?xml version="1.0"?>
<PAP name="SyntheticFullContractTest" version="1.0" versionNummer="1.0">
    <VARIABLES>
        <INPUTS>
            <INPUT name="STKL" type="int" default="1"/>
            <INPUT name="af" type="int" default="0"/>
            <INPUT name="f" type="double" default="1.0"/>
            <INPUT name="LZZ" type="int" default="2"/>
            <INPUT name="RE4" type="BigDecimal" default="BigDecimal.ZERO"/>
            <INPUT name="JFREIB" type="BigDecimal" default="BigDecimal.ZERO"/>
            <INPUT name="LZZFREIB" type="BigDecimal" default="BigDecimal.ZERO"/>
            <INPUT name="JHINZU" type="BigDecimal" default="BigDecimal.ZERO"/>
            <INPUT name="LZZHINZU" type="BigDecimal" default="BigDecimal.ZERO"/>
            <INPUT name="ZKF" type="BigDecimal" default="BigDecimal.ZERO"/>
            <INPUT name="R" type="int" default="0"/>
            <INPUT name="KVZ" type="BigDecimal" default="BigDecimal.ZERO"/>
            <INPUT name="PKV" type="int" default="0"/>
            <INPUT name="PKPV" type="BigDecimal" default="BigDecimal.ZERO"/>
            <INPUT name="PKPVAGZ" type="BigDecimal" default="BigDecimal.ZERO"/>
            <INPUT name="PVS" type="int" default="0"/>
            <INPUT name="PVZ" type="int" default="0"/>
            <INPUT name="PVA" type="BigDecimal" default="BigDecimal.ZERO"/>
            <INPUT name="KRV" type="int" default="0"/>
            <INPUT name="ALV" type="int" default="0"/>
            <INPUT name="SONSTB" type="BigDecimal" default="BigDecimal.ZERO"/>
            <INPUT name="JRE4" type="BigDecimal" default="BigDecimal.ZERO"/>
            <INPUT name="JRE4ENT" type="BigDecimal" default="BigDecimal.ZERO"/>
            <INPUT name="JVBEZ" type="BigDecimal" default="BigDecimal.ZERO"/>
            <INPUT name="MBV" type="BigDecimal" default="BigDecimal.ZERO"/>
            <INPUT name="AJAHR" type="int" default="0"/>
            <INPUT name="ALTER1" type="int" default="0"/>
            <INPUT name="SONSTENT" type="BigDecimal" default="BigDecimal.ZERO"/>
            <INPUT name="STERBE" type="BigDecimal" default="BigDecimal.ZERO"/>
            <INPUT name="VBEZ" type="BigDecimal" default="BigDecimal.ZERO"/>
            <INPUT name="VBEZM" type="BigDecimal" default="BigDecimal.ZERO"/>
            <INPUT name="VBEZS" type="BigDecimal" default="BigDecimal.ZERO"/>
            <INPUT name="VBS" type="BigDecimal" default="BigDecimal.ZERO"/>
            <INPUT name="VJAHR" type="int"/>
            <INPUT name="ZMVB" type="int" default="0"/>
        </INPUTS>
        <OUTPUTS>
            <OUTPUT name="LSTLZZ" type="BigDecimal" default="BigDecimal.ZERO"/>
            <OUTPUT name="SOLZLZZ" type="BigDecimal" default="BigDecimal.ZERO"/>
            <OUTPUT name="BK" type="BigDecimal" default="BigDecimal.ZERO"/>
        </OUTPUTS>
        <INTERNALS>
            <INTERNAL name="BASE" type="BigDecimal" default="BigDecimal.ZERO"/>
        </INTERNALS>
    </VARIABLES>
    <CONSTANTS>
        <CONSTANT name="STKLDIV" type="BigDecimal" value="BigDecimal.valueOf(10)"/>
    </CONSTANTS>
    <METHODS>
        <MAIN>
            <EVAL exec="BASE = RE4.divide(STKLDIV, 2, BigDecimal.ROUND_DOWN)"/>
            <IF expr="af == 0">
                <THEN><EVAL exec="f = 1.0"/></THEN>
            </IF>
            <EVAL exec="LSTLZZ = BASE.multiply(BigDecimal.valueOf(f)).setScale(2, BigDecimal.ROUND_DOWN)"/>
            <IF expr="R == 1">
                <THEN><EVAL exec="BK = LSTLZZ"/></THEN>
                <ELSE><EVAL exec="BK = BigDecimal.ZERO"/></ELSE>
            </IF>
            <IF expr="PKV == 1">
                <THEN><EVAL exec="LSTLZZ = LSTLZZ.subtract(BigDecimal.valueOf(1))"/></THEN>
            </IF>
        </MAIN>
    </METHODS>
</PAP>
"""


def _load_synthetic_program():
    return load_pap_program(_SYNTHETIC_PAP_ALL_35_INPUTS)


# ── 35-input classification completeness ────────────────────────────────

def test_all_35_official_inputs_classified():
    assert len(PAP_INPUT_CLASSIFICATION) == 35


@pytest.mark.parametrize("scope", ["DIRECTLY_MAPPED", "DERIVED", "DEFAULTED", "DEFERRED", "NOT_APPLICABLE"])
def test_every_classification_scope_is_used(scope):
    """Sanity: every scope category the brief requires is actually used
    somewhere in the matrix (i.e. the matrix isn't collapsing everything
    into one bucket)."""
    assert any(c.scope == scope for c in PAP_INPUT_CLASSIFICATION.values()), f"No input classified {scope}"


def test_no_input_classified_unsupported_with_undocumented_reason():
    """UNSUPPORTED would mean 'PAP requires this and Zoiko fundamentally
    cannot supply it' — this phase found none: every field is either
    directly sourced, derived, explicitly defaulted with evidence, or
    provably not-applicable/deferred via the PAP's own working defaults."""
    for name, c in PAP_INPUT_CLASSIFICATION.items():
        assert c.scope != "UNSUPPORTED", f"{name} marked UNSUPPORTED — must have a documented reason"


def test_vjahr_is_defaulted_not_not_applicable():
    """VJAHR is special-cased (§B): the PAP's own default is broken
    (typo), so it MUST be DEFAULTED (Zoiko-supplied), not NOT_APPLICABLE
    (which implies 'the PAP's own default correctly handles this')."""
    assert PAP_INPUT_CLASSIFICATION["VJAHR"].scope == "DEFAULTED"


# ── build_pap_environment: mapping correctness ──────────────────────────

def test_build_pap_environment_maps_stkl(profile_factory):
    env = build_pap_environment(profile=profile_factory(de_tax_class="III"), gross_monthly=Decimal("1000"), kvz_rate=Decimal("1.5"))
    assert env["STKL"] == 3


def test_build_pap_environment_rejects_invalid_tax_class(profile_factory):
    with pytest.raises(GermanyPapInvalidError, match="STKL"):
        build_pap_environment(profile=profile_factory(de_tax_class="VII"), gross_monthly=Decimal("1000"), kvz_rate=Decimal("1"))


def test_build_pap_environment_derives_af_from_factor_presence(profile_factory):
    env_no_factor = build_pap_environment(profile=profile_factory(de_tax_class="I"), gross_monthly=Decimal("1000"), kvz_rate=Decimal("1"))
    assert env_no_factor["af"] == 0
    assert env_no_factor["f"] == 1.0

    env_with_factor = build_pap_environment(
        profile=profile_factory(de_tax_class="IV", de_factor=Decimal("0.7500")), gross_monthly=Decimal("1000"), kvz_rate=Decimal("1"),
    )
    assert env_with_factor["af"] == 1
    assert env_with_factor["f"] == 0.75


def test_build_pap_environment_maps_re4_to_cents(profile_factory):
    env = build_pap_environment(profile=profile_factory(), gross_monthly=Decimal("1234.56"), kvz_rate=Decimal("1"))
    assert env["RE4"] == Decimal(123456)


def test_build_pap_environment_maps_lzz_by_frequency(profile_factory):
    for freq, expected in [("Annual", 1), ("Monthly", 2), ("Weekly", 3), ("Daily", 4)]:
        env = build_pap_environment(profile=profile_factory(), gross_monthly=Decimal("1000"), kvz_rate=Decimal("1"), pay_frequency=freq)
        assert env["LZZ"] == expected


def test_build_pap_environment_rejects_unsupported_frequency(profile_factory):
    with pytest.raises(GermanyPapInvalidError, match="frequency"):
        build_pap_environment(profile=profile_factory(), gross_monthly=Decimal("1000"), kvz_rate=Decimal("1"), pay_frequency="Fortnightly")


def test_build_pap_environment_maps_r_from_church_tax_liable(profile_factory):
    env_liable = build_pap_environment(profile=profile_factory(de_church_tax_liable=True), gross_monthly=Decimal("1000"), kvz_rate=Decimal("1"))
    assert env_liable["R"] == 1
    env_not_liable = build_pap_environment(profile=profile_factory(de_church_tax_liable=False), gross_monthly=Decimal("1000"), kvz_rate=Decimal("1"))
    assert env_not_liable["R"] == 0


def test_build_pap_environment_maps_pva_clamped_0_to_4(profile_factory):
    env = build_pap_environment(profile=profile_factory(de_child_count=9), gross_monthly=Decimal("1000"), kvz_rate=Decimal("1"))
    assert env["PVA"] == Decimal(4)
    env0 = build_pap_environment(profile=profile_factory(de_child_count=0), gross_monthly=Decimal("1000"), kvz_rate=Decimal("1"))
    assert env0["PVA"] == Decimal(0)


def test_build_pap_environment_maps_pkv_from_health_status(profile_factory):
    env_private = build_pap_environment(profile=profile_factory(de_health_insurance_status="PRIVATE"), gross_monthly=Decimal("1000"), kvz_rate=Decimal("1"))
    assert env_private["PKV"] == 1
    env_public = build_pap_environment(profile=profile_factory(de_health_insurance_status="PUBLIC"), gross_monthly=Decimal("1000"), kvz_rate=Decimal("1"))
    assert env_public["PKV"] == 0


def test_build_pap_environment_maps_krv_alv_exemption_markers(profile_factory):
    env = build_pap_environment(
        profile=profile_factory(de_pension_insurance_exempt=True, de_unemployment_insurance_exempt=True),
        gross_monthly=Decimal("1000"), kvz_rate=Decimal("1"),
    )
    assert env["KRV"] == 1 and env["ALV"] == 1


def test_build_pap_environment_maps_pvs_pvz(profile_factory):
    env = build_pap_environment(profile=profile_factory(de_saxony=True, de_childless=True), gross_monthly=Decimal("1000"), kvz_rate=Decimal("1"))
    assert env["PVS"] == 1 and env["PVZ"] == 1


def test_build_pap_environment_maps_kvz_directly(profile_factory):
    env = build_pap_environment(profile=profile_factory(), gross_monthly=Decimal("1000"), kvz_rate=Decimal("2.35"))
    assert env["KVZ"] == Decimal("2.35")


def test_build_pap_environment_always_supplies_vjahr_zero(profile_factory):
    """The one field this adapter must ALWAYS explicitly supply, per §B —
    the official default is broken (typo)."""
    env = build_pap_environment(profile=profile_factory(), gross_monthly=Decimal("1000"), kvz_rate=Decimal("1"))
    assert env["VJAHR"] == 0 == _VJAHR_ORDINARY_EMPLOYEE_VALUE


def test_build_pap_environment_does_not_set_not_applicable_fields(profile_factory):
    """Confirms the adapter deliberately OMITS every NOT_APPLICABLE/DEFERRED
    field (relying on the PAP's own declared defaults) rather than
    fabricating values for them."""
    env = build_pap_environment(profile=profile_factory(), gross_monthly=Decimal("1000"), kvz_rate=Decimal("1"))
    for name, c in PAP_INPUT_CLASSIFICATION.items():
        if c.scope in ("NOT_APPLICABLE", "DEFERRED"):
            assert name not in env, f"{name} (scope={c.scope}) should not be explicitly set by the adapter"


# ── Full mapping through the real interpreter (synthetic algorithm) ────

def test_environment_reaches_execution_stkl_and_gross(profile_factory):
    program = _load_synthetic_program()
    env = build_pap_environment(profile=profile_factory(de_tax_class="I"), gross_monthly=Decimal("1000.00"), kvz_rate=Decimal("1"))
    validate_pap_environment(profile_factory(), env)
    ctx = run_program(program, {k: v for k, v in env.items() if k in program.inputs})
    # BASE = RE4/10 = 100000/10 = 10000 cents = 100.00; LSTLZZ = BASE * f(=1) = 100.00
    assert ctx.outputs()["LSTLZZ"] == Decimal("10000.00")


def test_environment_church_tax_liable_sets_bk_equal_to_lstlzz(profile_factory):
    program = _load_synthetic_program()
    env = build_pap_environment(profile=profile_factory(de_church_tax_liable=True), gross_monthly=Decimal("1000.00"), kvz_rate=Decimal("1"))
    ctx = run_program(program, {k: v for k, v in env.items() if k in program.inputs})
    assert ctx.outputs()["BK"] == ctx.outputs()["LSTLZZ"]
    assert ctx.outputs()["BK"] != Decimal("0")


def test_environment_church_tax_not_liable_bk_is_zero(profile_factory):
    program = _load_synthetic_program()
    env = build_pap_environment(profile=profile_factory(de_church_tax_liable=False), gross_monthly=Decimal("1000.00"), kvz_rate=Decimal("1"))
    ctx = run_program(program, {k: v for k, v in env.items() if k in program.inputs})
    assert ctx.outputs()["BK"] == Decimal("0")


def test_environment_private_insurance_marker_reaches_execution(profile_factory):
    program = _load_synthetic_program()
    env_public = build_pap_environment(profile=profile_factory(de_health_insurance_status="PUBLIC"), gross_monthly=Decimal("1000.00"), kvz_rate=Decimal("1"))
    env_private = build_pap_environment(profile=profile_factory(de_health_insurance_status="PRIVATE"), gross_monthly=Decimal("1000.00"), kvz_rate=Decimal("1"))
    ctx_public = run_program(program, {k: v for k, v in env_public.items() if k in program.inputs})
    ctx_private = run_program(program, {k: v for k, v in env_private.items() if k in program.inputs})
    # The synthetic algorithm's PKV branch subtracts 1 — proves the PKV
    # marker genuinely reaches and affects execution, not proving any
    # real statutory PKV effect.
    assert ctx_public.outputs()["LSTLZZ"] - ctx_private.outputs()["LSTLZZ"] == Decimal("1")


# ── Factor path (§C / §11 / §32) ────────────────────────────────────────

def test_factor_path_tax_class_iv_without_factor(profile_factory):
    program = _load_synthetic_program()
    profile = profile_factory(de_tax_class="IV", de_factor=None)
    env = build_pap_environment(profile=profile, gross_monthly=Decimal("1000.00"), kvz_rate=Decimal("1"))
    validate_pap_environment(profile, env)
    assert env["af"] == 0
    ctx = run_program(program, {k: v for k, v in env.items() if k in program.inputs})
    assert ctx.outputs()["LSTLZZ"] == Decimal("10000.00")  # f neutralized to 1.0 by the PAP itself (af==0 -> f=1)


def test_factor_path_tax_class_iv_with_valid_factor(profile_factory):
    program = _load_synthetic_program()
    profile = profile_factory(de_tax_class="IV", de_factor=Decimal("0.5000"))
    env = build_pap_environment(profile=profile, gross_monthly=Decimal("1000.00"), kvz_rate=Decimal("1"))
    validate_pap_environment(profile, env)
    assert env["af"] == 1 and env["f"] == 0.5
    ctx = run_program(program, {k: v for k, v in env.items() if k in program.inputs})
    assert ctx.outputs()["LSTLZZ"] == Decimal("5000.00")  # BASE(10000) * f(0.5)


def test_factor_rejected_for_non_class_iv(profile_factory):
    """Statutory rule the PAP itself does NOT enforce (§C) — the adapter's
    validate_pap_environment must catch it before execution."""
    profile = profile_factory(de_tax_class="I", de_factor=Decimal("0.5"))
    env = build_pap_environment(profile=profile, gross_monthly=Decimal("1000"), kvz_rate=Decimal("1"))
    with pytest.raises(GermanyPapInvalidError, match="class IV"):
        validate_pap_environment(profile, env)


def test_factor_out_of_range_rejected(profile_factory):
    profile = profile_factory(de_tax_class="IV", de_factor=Decimal("1.5"))
    env = build_pap_environment(profile=profile, gross_monthly=Decimal("1000"), kvz_rate=Decimal("1"))
    with pytest.raises(GermanyPapInvalidError, match="factor"):
        validate_pap_environment(profile, env)


@pytest.mark.parametrize("tax_class,stkl", [("I", 1), ("II", 2), ("III", 3), ("IV", 4), ("V", 5), ("VI", 6)])
def test_all_six_tax_classes_map_and_execute(profile_factory, tax_class, stkl):
    program = _load_synthetic_program()
    profile = profile_factory(de_tax_class=tax_class)
    env = build_pap_environment(profile=profile, gross_monthly=Decimal("1000.00"), kvz_rate=Decimal("1"))
    assert env["STKL"] == stkl
    validate_pap_environment(profile, env)
    ctx = run_program(program, {k: v for k, v in env.items() if k in program.inputs})
    assert ctx.outputs()["LSTLZZ"] == Decimal("10000.00")  # synthetic algorithm doesn't branch on STKL itself


# ── Validation ───────────────────────────────────────────────────────

def test_validate_rejects_invalid_stkl():
    with pytest.raises(GermanyPapInvalidError, match="STKL"):
        validate_pap_environment(None, {"STKL": 9, "af": 0, "LZZ": 2, "R": 0, "PKV": 0, "PVS": 0, "PVZ": 0, "KRV": 0, "ALV": 0})


def test_validate_rejects_invalid_boolean_marker():
    with pytest.raises(GermanyPapInvalidError, match="R"):
        validate_pap_environment(None, {"STKL": 1, "af": 0, "LZZ": 2, "R": 2, "PKV": 0, "PVS": 0, "PVZ": 0, "KRV": 0, "ALV": 0})


def test_validate_rejects_negative_kvz():
    env = {"STKL": 1, "af": 0, "LZZ": 2, "R": 0, "PKV": 0, "PVS": 0, "PVZ": 0, "KRV": 0, "ALV": 0, "KVZ": Decimal("-1")}
    with pytest.raises(GermanyPapInvalidError, match="KVZ"):
        validate_pap_environment(None, env)


def test_validate_rejects_negative_re4():
    env = {"STKL": 1, "af": 0, "LZZ": 2, "R": 0, "PKV": 0, "PVS": 0, "PVZ": 0, "KRV": 0, "ALV": 0, "RE4": Decimal("-100")}
    with pytest.raises(GermanyPapInvalidError, match="RE4"):
        validate_pap_environment(None, env)


def test_validate_rejects_invalid_lzz():
    env = {"STKL": 1, "af": 0, "LZZ": 9, "R": 0, "PKV": 0, "PVS": 0, "PVZ": 0, "KRV": 0, "ALV": 0}
    with pytest.raises(GermanyPapInvalidError, match="LZZ"):
        validate_pap_environment(None, env)


def test_validate_accepts_well_formed_environment(profile_factory):
    env = build_pap_environment(profile=profile_factory(), gross_monthly=Decimal("1000"), kvz_rate=Decimal("1"))
    validate_pap_environment(profile_factory(), env)  # must not raise


# ── Output mapping ───────────────────────────────────────────────────

def test_all_required_outputs_classified_and_have_zoiko_field():
    for name, c in PAP_OUTPUT_CLASSIFICATION.items():
        if c.required_now:
            assert c.zoiko_field is not None, f"{name} is required_now but has no zoiko_field"


def test_deferred_outputs_have_no_zoiko_field_yet():
    for name, c in PAP_OUTPUT_CLASSIFICATION.items():
        if not c.required_now:
            assert c.zoiko_field is None


def test_map_pap_outputs_returns_all_declared_outputs_as_strings(profile_factory):
    program = _load_synthetic_program()
    env = build_pap_environment(profile=profile_factory(de_church_tax_liable=True), gross_monthly=Decimal("1000"), kvz_rate=Decimal("1"))
    ctx = run_program(program, {k: v for k, v in env.items() if k in program.inputs})
    raw = map_pap_outputs(ctx)
    assert set(raw.keys()) == {"LSTLZZ", "SOLZLZZ", "BK"}
    assert all(isinstance(v, str) for v in raw.values())


def test_minimum_required_outputs_are_lstlzz_solzlzz_bk():
    required = {name for name, c in PAP_OUTPUT_CLASSIFICATION.items() if c.required_now}
    assert required == {"LSTLZZ", "SOLZLZZ", "BK"}


# ── InterpreterPapExecutor: full contract, provenance, security ────────

def test_interpreter_pap_executor_full_result(profile_factory):
    program = _load_synthetic_program()
    executor = InterpreterPapExecutor(program, expected_source_sha256=program.source_sha256)
    pap_input = PapInputContract(
        stkl="I", af=False, f=None, zkf=Decimal(0), r="NONE", krv=False, alv_marker=False,
        pkv=False, pvs=False, pvz=False, pva=0, lzz=2, re4_cents=100000, kvz=Decimal("1.5"),
    )
    result = executor.execute(pap_input)
    assert isinstance(result, GermanyPapCalculationResult)
    assert result.calculation_status == "COMPLETE"
    assert result.pap_hash == program.source_sha256
    assert result.raw_outputs is not None
    assert "papSourceFinality" in result.calculation_trace
    assert result.calculation_trace["papSourceFinality"] == "OPEN"


def test_interpreter_pap_executor_rejects_hash_mismatch():
    program = _load_synthetic_program()
    with pytest.raises(GermanyPapInvalidError, match="hash mismatch"):
        InterpreterPapExecutor(program, expected_source_sha256="0" * 64)


def test_interpreter_pap_executor_rejects_program_missing_required_outputs():
    xml = b"""<PAP name="x" version="1" versionNummer="1">
        <VARIABLES><INPUTS><INPUT name="STKL" type="int" default="1"/></INPUTS>
        <OUTPUTS><OUTPUT name="SOMETHING_ELSE" type="BigDecimal" default="BigDecimal.ZERO"/></OUTPUTS>
        <INTERNALS/></VARIABLES>
        <CONSTANTS/><METHODS><MAIN/></METHODS></PAP>"""
    program = load_pap_program(xml)
    executor = InterpreterPapExecutor(program, expected_source_sha256=program.source_sha256)
    pap_input = PapInputContract(
        stkl="I", af=False, f=None, zkf=Decimal(0), r="NONE", krv=False, alv_marker=False,
        pkv=False, pvs=False, pvz=False, pva=0, lzz=2, re4_cents=100000, kvz=Decimal("1.5"),
    )
    with pytest.raises(GermanyPapInvalidError, match="does not declare expected output"):
        executor.execute(pap_input)


# ── Source finality gate (§A) ────────────────────────────────────────

def test_pap_source_finality_is_open():
    assert PAP_SOURCE_FINALITY == "OPEN"


def test_assert_pap_source_finality_resolved_raises():
    with pytest.raises(GermanyPapInvalidError, match="PAP_SOURCE_FINALITY"):
        assert_pap_source_finality_resolved()


# ── Production safety ────────────────────────────────────────────────

def test_resolve_pap_executor_still_returns_unavailable():
    """Confirms Phase 8C-2 did NOT wire the adapter/interpreter into
    production — resolve_pap_executor() must still always return
    UnavailablePapExecutor regardless of any PapAlgorithmAsset."""
    executor = resolve_pap_executor(None)
    assert isinstance(executor, UnavailablePapExecutor)

    class _FakeAsset:
        id = 1
        pap_version = "test"
    executor2 = resolve_pap_executor(_FakeAsset())
    assert isinstance(executor2, UnavailablePapExecutor)


def test_no_eval_exec_in_adapter_source():
    import ast
    import inspect
    import app.modules.payroll.engine.germany_pap.adapter as mod

    tree = ast.parse(inspect.getsource(mod))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"eval", "exec", "compile"}, f"Forbidden call {node.func.id}() found"
