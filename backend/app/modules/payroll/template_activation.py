"""Structured report-template activation results.

A refusal is the governance MESSAGE (exactly the text the status change raises)
plus what kind of blocker it is and, where the rule names one, its release
gate. Every check of the report-template lifecycle and every country
``template_activation_refusal`` hook returns either None (allowed) or an
``ActivationRefusal``.

``ActivationRefusal`` is a ``str`` subclass on purpose: the hooks' contract was
"return the refusal message or None", and every caller (the status change,
tests, country modules) compares, tests membership in or raises that string —
all of which keep working unchanged. The structure rides along as attributes,
so nothing has to guess a gate or kind from the wording.

No database access and no imports from the payroll service here, so every
country module can import it.
"""
from typing import Optional

# Blocker kinds (stable codes the UI keys off).
TRANSITION = "transition"            # the lifecycle does not allow this move from the current status
FOUR_EYES = "four_eyes"              # maker-checker: approval missing / self-approval / approver activating
JURISDICTION_GATE = "jurisdiction_gate"  # the country's own activation gate (evidence, schemas, certification)
NOT_BUILT = "not_built"              # the country's report templates are not built yet (scaffolding)
CONFLICT = "conflict"                # another version is already Active for the same slot
UNKNOWN_STATUS = "unknown_status"    # the requested status does not exist

BLOCKER_KINDS = (TRANSITION, FOUR_EYES, JURISDICTION_GATE, NOT_BUILT, CONFLICT, UNKNOWN_STATUS)

# Country hooks. REFUSAL_HOOK is the gate the status change applies. A country
# whose gate reads tenant data (Mexico's payslip proof) also declares
# READINESS_HOOK — the same gate minus that part — and DEFERRED_HOOK, the
# checks it leaves to the real activation. Every other country's readiness uses
# REFUSAL_HOOK itself, so the rules exist once.
REFUSAL_HOOK = "template_activation_refusal"
READINESS_HOOK = "template_activation_readiness"
DEFERRED_HOOK = "template_activation_deferred_checks"


class ActivationRefusal(str):
    """A refusal message that also carries ``blocker_kind`` and ``gate``.

    Compares, hashes and formats exactly like the plain message."""

    blocker_kind: str
    gate: Optional[str]

    def __new__(cls, message: str, blocker_kind: str, gate: Optional[str] = None):
        if blocker_kind not in BLOCKER_KINDS:
            raise ValueError(f"unknown blocker kind {blocker_kind!r}")
        obj = super().__new__(cls, message)
        obj.blocker_kind = blocker_kind
        obj.gate = gate
        return obj

    def as_result(self) -> dict:
        return {"allowed": False, "message": str(self), "blockerKind": self.blocker_kind, "gate": self.gate}


ALLOWED = {"allowed": True, "message": None, "blockerKind": None, "gate": None}


def as_result(refusal, default_kind: str = JURISDICTION_GATE) -> dict:
    """{allowed, message, blockerKind, gate} for a check's return value: None /
    "" = allowed; an ActivationRefusal keeps its own kind and gate; any other
    string (a hook not yet returning structure) is reported with `default_kind`
    and no gate — never a kind or gate guessed from its wording."""
    if not refusal:
        return dict(ALLOWED)
    if isinstance(refusal, ActivationRefusal):
        return refusal.as_result()
    return {"allowed": False, "message": str(refusal), "blockerKind": default_kind, "gate": None}
