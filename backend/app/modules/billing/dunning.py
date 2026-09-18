"""
modules/billing/dunning.py
----------------------------
Commercial Billing & Subscription Operating Standard Part 9 (blocker #17):
"An automated failed-payment rule must never terminate an already
authorized in-flight pay cycle without the defined governance path."

Builds on BillingDunningState (models.py) and its DunningStage enum —
both pre-existing in this codebase, previously unused (no code ever
created a BillingDunningState row). One row per org, advanced by
run_dunning_sweep() on a timer (billing/scheduler.py), at most one stage
per sweep, based on how long the subscription has been PAST_DUE:

    RETRY -> RESTRICT_EXPANSION -> RESTRICT_NEW_RUN -> READ_ONLY

  RETRY               fully permissive — Stripe's own smart-retry window.
  RESTRICT_EXPANSION  blocks growth actions (new legal entities, new
                       jurisdictions) but payroll keeps running normally.
  RESTRICT_NEW_RUN    also blocks creating a NEW payroll run — existing
                       runs may still be advanced/completed.
  READ_ONLY           full write lockout, same shape as trial GRACE_READONLY.

The day-thresholds below (app/config.py) are PLACEHOLDER defaults, not a
confirmed Finance decision — the prompt this was built from is explicit:
"confirm exact timing with Finance, don't invent silently." Named,
overridable settings (not a magic number buried here) is how that's
honored: approving the real cadence is a config change, not a code change.

Design rules (mirroring trial_lifecycle.py's discipline):
  - Never changes BillingSubscription.status — only billing/router.py's
    webhook handlers do that.
  - invoice.paid resets the org's BillingDunningState back to RETRY
    (there is no "no dunning" stage in the enum — RETRY is Stripe's own
    baseline retry state, functionally "nothing restricted yet") the
    instant it fires, regardless of current stage.
  - Audit-first: every stage transition records a BillingCommercialAuditEvent.
  - The safety guarantee itself is structural, not sweep-dependent: it
    comes from which routes carry entitlements.require_not_dunning_
    restricted() at all (only new-run creation and new-entity/jurisdiction
    creation; never the run-advance/complete endpoint) — see
    entitlements.has_in_flight_authorized_run(). Completing an
    already-authorized run is never blocked, at ANY dunning stage.
  - `in_flight_run_guard` is a second, belt-and-suspenders layer on top of
    that: the sweep itself refuses to advance an org's stage past
    RESTRICT_EXPANSION while has_in_flight_authorized_run() is True, and
    sets this column so a Super Admin can see an org is correctly
    protected rather than mistakenly unrestricted (blocker #17's own
    wording). This means an org with a genuinely in-flight authorized run
    never even reaches RESTRICT_NEW_RUN/READ_ONLY while that run is
    outstanding — re-checked every sweep, so the freeze lifts the moment
    the guard condition clears.
"""

import logging
from datetime import datetime

from app.config import settings
from app.modules.billing.entitlements import has_in_flight_authorized_run
from app.modules.billing.models import BillingCommercialAuditEvent, BillingDunningState, BillingSubscription, DunningStage, SubscriptionStatus

logger = logging.getLogger("zoiko_payroll.billing.dunning")

_STAGE_ORDER = [
    DunningStage.RETRY.value,
    DunningStage.RESTRICT_EXPANSION.value,
    DunningStage.RESTRICT_NEW_RUN.value,
    DunningStage.READ_ONLY.value,
]


def _now() -> datetime:
    return datetime.utcnow()


def _target_stage_for_elapsed(days_elapsed: float) -> str:
    """Pure function: which stage a PAST_DUE subscription should be at,
    given how many days it's been PAST_DUE."""
    if days_elapsed >= settings.DUNNING_SUSPEND_AFTER_DAYS:
        return DunningStage.READ_ONLY.value
    if days_elapsed >= settings.DUNNING_RESTRICT_AFTER_DAYS:
        return DunningStage.RESTRICT_NEW_RUN.value
    if days_elapsed >= settings.DUNNING_WARN_AFTER_DAYS:
        return DunningStage.RESTRICT_EXPANSION.value
    return DunningStage.RETRY.value


def _audit(db, organization_id, event_type: str, payload: dict) -> None:
    db.add(
        BillingCommercialAuditEvent(
            organization_id=organization_id,
            actor_user_id=None,
            event_type=event_type,
            payload=payload,
        )
    )


def get_or_create_dunning_state(db, organization_id: int) -> BillingDunningState:
    state = db.query(BillingDunningState).filter(BillingDunningState.organization_id == organization_id).first()
    if state is None:
        state = BillingDunningState(organization_id=organization_id, stage=DunningStage.RETRY.value, entered_at=_now())
        db.add(state)
        db.flush()
    return state


def run_dunning_sweep(db) -> dict:
    """Advance every PAST_DUE subscription's dunning state by at most one
    step per run, per-org fresh transaction, log-and-continue on failure —
    same discipline as trial_lifecycle.run_trial_expiry_sweep. Never
    changes BillingSubscription.status."""
    now = _now()
    scanned = []
    advanced = []

    subs = db.query(BillingSubscription).filter(BillingSubscription.status == SubscriptionStatus.PAST_DUE.value).all()

    for sub in subs:
        scanned.append(sub.organization_id)
        try:
            state = get_or_create_dunning_state(db, sub.organization_id)

            # Re-checked every sweep, so this reflects current reality even
            # if the guard condition has since cleared.
            in_flight = has_in_flight_authorized_run(db, sub.organization_id)
            state.in_flight_run_guard = in_flight

            days_elapsed = (now - state.entered_at).total_seconds() / 86400
            target_stage = _target_stage_for_elapsed(days_elapsed)
            current_index = _STAGE_ORDER.index(state.stage) if state.stage in _STAGE_ORDER else 0
            target_index = _STAGE_ORDER.index(target_stage)

            next_stage_index = current_index + 1
            would_pass_restrict_expansion = next_stage_index >= _STAGE_ORDER.index(DunningStage.RESTRICT_NEW_RUN.value)

            if target_index > current_index and in_flight and would_pass_restrict_expansion:
                # Blocker #17's critical guard: never advance an org past
                # RESTRICT_EXPANSION while it has a PayrollRun already
                # APPROVED/AUTHORIZED with a pay_date that hasn't passed —
                # advancing further would put a real, in-flight pay cycle at
                # risk of write restrictions, even though completing it is
                # separately never blocked (see module docstring). Frozen
                # here, not silently dropped: audited so it's visible.
                _audit(
                    db, sub.organization_id, "DUNNING_STAGE_ADVANCE_PAUSED_IN_FLIGHT_RUN",
                    {"subscription_id": sub.id, "stage": state.stage, "days_past_due": round(days_elapsed, 2)},
                )
                db.add(state)
                db.commit()
            elif target_index > current_index:
                # Advance exactly one stage at a time — never leap past an
                # intermediate stage even if elapsed time would justify it.
                next_stage = _STAGE_ORDER[current_index + 1]
                previous_stage = state.stage
                state.stage = next_stage
                db.add(state)
                _audit(
                    db, sub.organization_id, "DUNNING_STAGE_ADVANCED",
                    {"subscription_id": sub.id, "from_stage": previous_stage, "to_stage": next_stage, "days_past_due": round(days_elapsed, 2)},
                )
                db.commit()
                advanced.append({"organization_id": sub.organization_id, "stage": next_stage})
            else:
                db.add(state)
                db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("[dunning-sweep] Failed for organization_id=%s", sub.organization_id)
            db.rollback()

    return {"scanned": scanned, "advanced": advanced}


def reset_dunning(db, organization_id: int, event_type: str = "DUNNING_RESET") -> None:
    """Called from the invoice.paid webhook handler — recovery must reset
    dunning state back to RETRY immediately, regardless of current stage."""
    state = db.query(BillingDunningState).filter(BillingDunningState.organization_id == organization_id).first()
    if state is None:
        return
    if state.stage != DunningStage.RETRY.value:
        _audit(db, organization_id, event_type, {"previous_stage": state.stage})
    state.stage = DunningStage.RETRY.value
    state.entered_at = _now()
    state.in_flight_run_guard = False
    db.add(state)
