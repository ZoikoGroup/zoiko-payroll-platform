"""
engine/jurisdictions/mexico/isn.py
----------------------------------
State Impuesto Sobre Nóminas (spec §15, MX-045–MX-047): employer tax on the
sum of the period's earnings whose classification includes ISN for the
employee's work state (state override first), at `mx_isn_rate_pct` from that
state's ISN pack — which must be in scope and Active. Anything else BLOCKS.
ISN never changes a federal base (F7).
"""

from __future__ import annotations

from decimal import Decimal

from ...countries import mexico_content as _c
from .content import Content
from .errors import MXBlock

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")


def check_state(work_state: str) -> None:
    if not work_state:
        raise MXBlock("MX_STATE_UNSUPPORTED", "the employee has no work state (MX-038)")
    if work_state not in _c.MX_ISN_STATES_IN_SCOPE:
        raise MXBlock("MX_STATE_UNSUPPORTED", f"work state {work_state} has no ISN pack in this release (MX-045)")


def employer(lines, work_state: str, state_pack) -> dict:
    check_state(work_state)
    if not state_pack or state_pack.get("state") != work_state:
        raise MXBlock("MX_STATE_UNSUPPORTED", f"no ISN pack resolved for {work_state}")
    if state_pack.get("status") != "Active":
        raise MXBlock("MX_ISN_PACK_NOT_ACTIVE", f"the {work_state} ISN pack is {state_pack.get('status')}, not Active")
    content = Content(state_pack.get("rate_map"), [], f"{work_state} ISN pack")
    rate = content.pct("mx_isn_rate_pct")
    included = [l for l in lines if l["isn"]]
    base = sum((l["amount"] for l in included), _ZERO)
    return {"state": work_state, "base": base, "rate_pct": rate * _HUNDRED, "amount": base * rate,
            "codes": [l["code"] for l in included], "pack_id": state_pack.get("pack_id"),
            "pack_version": state_pack.get("version"), "content": content}
