"""Phase 8G-1 — Germany BMF PAP production release gate.

Pure evaluation logic, no database access: `service.py` resolves a
`GermanyPapRelease` row (plus its `PapAlgorithmAsset`) into a plain
snapshot dict and calls `evaluate()` here. Kept dependency-free and
directly unit-testable, mirroring this package's own `interpreter.py`
design philosophy (pure functions over an explicit input, no hidden
state).

This module answers exactly one question: "does this specific release
snapshot satisfy every governance gate right now?" It does NOT decide
whether PAP executes in production. `resolve_pap_executor()`
(germany_pap/core.py) is NOT wired to this module in Phase 8G-1 — this
file is not imported by core.py, adapter.py, interpreter.py, or
countries/germany.py, and none of those files import anything from here.
Even a release this module reports fully eligible cannot make
`resolve_pap_executor()` return anything other than `UnavailablePapExecutor`,
because no code path connects them. Wiring them together is an explicit,
separate, future-phase decision (see Phase 8F's own future-activation
contract, steps 13-14), deliberately not taken here.

Fail-closed by construction: any gate name missing from the input
snapshot is treated as unsatisfied (False), never assumed true.
"""
from dataclasses import dataclass
from typing import Dict, Mapping, Tuple

# The eight named dimensions this gate evaluates (§6). Historically
# mislabeled "nine" in Phase 8G-1's own docstring/report and the Super
# Admin UI card title — corrected in Phase 8AN after a forensic audit
# found the phase's own printed REQUIRED_GATES tuple always had 8
# entries; there was never a 9th gate silently dropped, this was a
# miscount at the label level only. Order is the order gates are
# reported in `failed_gates`, not a priority ranking.
REQUIRED_GATES: Tuple[str, ...] = (
    "source_identity_verified",
    "source_hash_verified",
    "source_finality_verified",
    "licensing_authorized",
    "asset_approved",
    "golden_vectors_passed",
    "security_certified",
    "release_approved",
)


@dataclass(frozen=True)
class GateEvaluationResult:
    gates: Dict[str, bool]
    failed_gates: Tuple[str, ...]
    is_activation_eligible: bool


def evaluate(snapshot: Mapping[str, bool]) -> GateEvaluationResult:
    """`snapshot` should carry a bool for each name in REQUIRED_GATES.
    A missing key evaluates to False — the gate never infers satisfaction
    from absence."""
    gates = {name: bool(snapshot.get(name, False)) for name in REQUIRED_GATES}
    failed = tuple(name for name in REQUIRED_GATES if not gates[name])
    return GateEvaluationResult(
        gates=gates,
        failed_gates=failed,
        is_activation_eligible=(len(failed) == 0),
    )
