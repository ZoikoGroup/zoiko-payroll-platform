"""IR56G departure tax-clearance hold — state machine (ZP-HK-ENG-001 §8, HK-013;
IRD PAM 46(e), SourceArtifact ird_pam46e).

The hold is a LEGAL HOLD STATE, never a deduction or a negative earning: the
held money remains owed to the employee on each payslip (net pay unchanged)
and is traced line by line (payroll_hk_tax_clearance_hold_lines) until released.

Official rule (PAM 46(e)): file IR56G not later than 1 month before the
expected departure date, and "withhold all moneys payable to that employee
for a period of one month from the date of filing the notification or until
the IRD issues a 'letter of release', WHICHEVER IS EARLIER". The spec text
("continues the hold until an IRD letter of release or other certified
release condition") is implemented with the statute's two release
conditions: LETTER_OF_RELEASE and STATUTORY_PERIOD_ELAPSED (one month from
filing). Neither is automatic — release is always an authorised operator
action with evidence, approved by a second person (HK-022 four-eyes).
"""

from datetime import date

from app.modules.payroll.engine.jurisdictions.hong_kong.common import add_months, timing_months

STATES = (
    "INACTIVE", "DEPARTURE_IDENTIFIED", "IR56G_DUE", "IR56G_FILED_HOLD_ACTIVE",
    "LETTER_OF_RELEASE_RECEIVED", "DEPARTURE_CANCELLED_OR_CHANGED", "CASE_CLOSED",
)
# States in which payments are withheld. DEPARTURE_CANCELLED_OR_CHANGED keeps
# holding: a changed departure is re-evaluated, never silently released.
HOLDING_STATES = ("IR56G_FILED_HOLD_ACTIVE", "DEPARTURE_CANCELLED_OR_CHANGED")
# Final-pay completion is blocked while the filing prerequisite is unresolved.
FINAL_PAY_BLOCKING_STATES = ("DEPARTURE_IDENTIFIED", "IR56G_DUE")
TRANSITIONS = {
    "INACTIVE": ("DEPARTURE_IDENTIFIED",),
    "DEPARTURE_IDENTIFIED": ("IR56G_DUE", "IR56G_FILED_HOLD_ACTIVE", "DEPARTURE_CANCELLED_OR_CHANGED"),
    "IR56G_DUE": ("IR56G_FILED_HOLD_ACTIVE", "DEPARTURE_CANCELLED_OR_CHANGED"),
    "IR56G_FILED_HOLD_ACTIVE": ("LETTER_OF_RELEASE_RECEIVED", "DEPARTURE_CANCELLED_OR_CHANGED"),
    "DEPARTURE_CANCELLED_OR_CHANGED": ("IR56G_DUE", "IR56G_FILED_HOLD_ACTIVE", "LETTER_OF_RELEASE_RECEIVED", "CASE_CLOSED"),
    "LETTER_OF_RELEASE_RECEIVED": ("CASE_CLOSED",),
    "CASE_CLOSED": (),
}
RELEASE_BASES = ("LETTER_OF_RELEASE", "STATUTORY_PERIOD_ELAPSED")


def filing_deadline(expected_departure: date, timing: dict) -> date:
    return add_months(expected_departure, -timing_months(timing, "ird_ir56g_months_before"))


def statutory_hold_expiry(filed: date, timing: dict) -> date:
    return add_months(filed, timing_months(timing, "ird_ir56g_hold_months"))


def initial_state(identified_on: date, expected_departure: date, timing: dict) -> str:
    """DEPARTURE_IDENTIFIED, or IR56G_DUE once the filing deadline is at or
    within reach (identified with ≤ 1 month to go)."""
    return "IR56G_DUE" if identified_on >= filing_deadline(expected_departure, timing) else "DEPARTURE_IDENTIFIED"


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, ())


def release_refusal(state: str, basis: str, reference: str, evidence_ref: str, filed: date, on: date,
                    requested_by: int, approved_by: int, timing: dict = None) -> str:
    """None when a release may proceed, else the refusal reason."""
    if state not in HOLDING_STATES:
        return f"no active hold to release (state {state})"
    if basis not in RELEASE_BASES:
        return f"release basis must be one of {', '.join(RELEASE_BASES)}"
    if not evidence_ref:
        return "release requires recorded evidence (the letter of release, or the filing evidence for the elapsed period)"
    if basis == "LETTER_OF_RELEASE" and not reference:
        return "a letter-of-release reference is required"
    if basis == "STATUTORY_PERIOD_ELAPSED":
        if filed is None:
            return "the IR56G filing date is not recorded"
        expiry = statutory_hold_expiry(filed, timing)
        if on < expiry:
            months = timing_months(timing, "ird_ir56g_hold_months")
            return (f"the statutory {months}-month period from filing ({filed}) runs to {expiry} — no letter of "
                    "release recorded")
    if approved_by is None or requested_by is None:
        return "release needs a requester and a distinct approver"
    if approved_by == requested_by:
        return "the approver of a tax-clearance release must differ from the requester (four-eyes)"
    return None
