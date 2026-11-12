"""
payroll/mexico_two_person.py
----------------------------
Mexico engineering sweep S1: the governance decisions as configuration —
D-26 (general availability), D-27 (retiring Active content) and D-28 (each
organisation-side configuration item). While a decision is unanswered, or is
answered SINGLE, the action runs as today. Answered FOUR_EYES, an action runs
only when a SECOND, different person repeats the identical change:

  1st call   records a PROPOSED audit row (who, what, a hash of the change) and
             is refused with MX_FOUR_EYES_PROPOSED — nothing else changes;
  2nd call   by a different person, for the same change within 7 days, records
             CONFIRMED (pointing at the proposal) and lets the action run.

The same person repeating it is refused (MX_FOUR_EYES_REQUIRED). No new table:
the proposal is a TaxConfigurationAudit row, so it is audited like every change.

D-28 also offers FOUR_EYES_WHEN_LIVE: single-person until the organisation is
live, four-eyes after. "Live" is read as: the organisation has a payroll run
that has been APPROVED (or gone further) — the first point at which its
configuration has decided real pay. The brief does not define "live"; this
reading is stated in the decision's configuration so the owner sees it.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException

PROPOSAL_DAYS = 7
MODES = ("SINGLE", "FOUR_EYES", "FOUR_EYES_WHEN_LIVE")
LIVE_RUN_STATUSES = ("Approved", "Authorized", "Paid", "Closed")


def organization_is_live(db: Session, organization_id: Optional[int]) -> bool:
    """Has this organisation a payroll run APPROVED or beyond (FOUR_EYES_WHEN_LIVE)?"""
    from app.modules.payroll.models import PayrollRun

    if organization_id is None:
        return True                                 # unknown organisation: the stricter reading
    return db.query(PayrollRun.id).filter(PayrollRun.organization_id == organization_id,
                                          PayrollRun.status.in_(LIVE_RUN_STATUSES)).first() is not None


def mode(db: Session, decision: str, part: Optional[str] = None) -> str:
    """SINGLE unless the register answers FOUR_EYES (for `part`, if the decision has parts)."""
    from app.modules.payroll import mexico_decision_config
    from app.modules.payroll.engine.jurisdictions.mexico.decisions import switch

    with mexico_decision_config.applying(db):
        answer = switch(decision)
    if isinstance(answer, dict):
        answer = answer.get(part)
    return answer or "SINGLE"


def _digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def require(db: Session, *, decision: str, part: Optional[str] = None, action: str, entity_type: str,
            entity_id: int, actor_id: Optional[int], payload: dict, second: str,
            organization_id: Optional[int] = None) -> None:
    """Return to let the action run; raise (after recording a proposal) when a
    second person must confirm the same change first."""
    from app.modules.payroll.models import TaxConfigurationAudit as A
    from app.modules.payroll.service import record_tax_audit

    chosen = mode(db, decision, part)
    if chosen == "FOUR_EYES_WHEN_LIVE" and not organization_is_live(db, organization_id):
        return
    if chosen not in ("FOUR_EYES", "FOUR_EYES_WHEN_LIVE"):
        return
    if actor_id is None:
        raise BadRequestException(f"MX_FOUR_EYES_REQUIRED: {action} needs an identified person ({decision} four-eyes)")
    digest = _digest(payload)
    since = datetime.now(timezone.utc) - timedelta(days=PROPOSAL_DAYS)
    proposed, confirmed = f"{action}:proposed", f"{action}:confirmed"
    rows = (db.query(A).filter(A.entity_type == entity_type, A.entity_id == entity_id,
                               A.action.in_((proposed, confirmed))).order_by(A.id.desc()).all())
    used = {(r.new_value or {}).get("proposal") for r in rows if r.action == confirmed}
    pending = next((r for r in rows if r.action == proposed and (r.new_value or {}).get("digest") == digest
                    and r.id not in used and _aware(r.created_at) >= since), None)
    if pending is None:
        record_tax_audit(db, actor_id=actor_id, action=proposed, entity_type=entity_type, entity_id=entity_id,
                         new_value={"digest": digest, "decision": decision, "part": part, "change": payload},
                         reason=f"{decision} four-eyes: proposed")
        db.commit()
        raise BadRequestException(f"MX_FOUR_EYES_PROPOSED: recorded — {second} must confirm the same change within "
                                  f"{PROPOSAL_DAYS} days ({decision} answered four-eyes)")
    if pending.actor_id == actor_id:
        raise BadRequestException(f"MX_FOUR_EYES_REQUIRED: you proposed this change — {second} must confirm it "
                                  f"({decision} four-eyes)")
    record_tax_audit(db, actor_id=actor_id, action=confirmed, entity_type=entity_type, entity_id=entity_id,
                     new_value={"proposal": pending.id, "digest": digest, "decision": decision, "part": part},
                     reason=f"{decision} four-eyes: confirmed",
                     auto_commit=False)                       # commits with the action: a failed action keeps the proposal


def _aware(value):
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
