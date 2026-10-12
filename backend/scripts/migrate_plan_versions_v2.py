"""
scripts/migrate_plan_versions_v2.py
-------------------------------------
Publishes corrected v2 plan versions for CORE and PROFESSIONAL, matching
the Plan Entitlement spec's tier matrix, and migrates every existing
BillingSubscription off the old (now RETIRED) version onto the new one.

Why a new version instead of editing the old one: BillingPlanVersion is
immutable once PUBLISHED (plan_catalog.add_entitlement_flag enforces this).
Professional's v1 was seeded with max_entities=1 (a placeholder, not the
spec's final number) and is missing multi_entity/multi_currency/api_access/
assist flags entirely as *explicit* off-flags; Core's v1 has the right
numeric caps but under the wrong key for schedules (max_payroll_schedules
instead of the canonical max_schedules — see billing/feature_keys.py) and
is also missing the explicit boolean-off flags. Both need a new version.

Idempotent: for each plan, if the currently-published version already
carries every target flag with the target value, this script leaves it
alone and does not create a redundant v3.

Usage:
    python -m scripts.migrate_plan_versions_v2
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, initialize_database
from app.modules.auth.models import User, UserRole
from app.modules.billing import plan_catalog
from app.modules.billing.feature_keys import (
    API_ACCESS,
    ASSIST,
    MAX_BWM,
    MAX_ENTITIES,
    MAX_JURISDICTIONS,
    MAX_SCHEDULES,
    MULTI_CURRENCY,
    MULTI_ENTITY,
    PAYROLL_RUNS,
)
from app.modules.billing.models import BillingCommercialAuditEvent, BillingPlan, BillingSubscription, PlanCode

# None = boolean/unlimited "on" (see BillingEntitlementFlag docstring);
# 0 = explicitly off. Matches the vocabulary already established by
# scripts/seed_core_plan.py / seed_professional_plan.py.
TARGET_FLAGS = {
    PlanCode.CORE.value: {
        PAYROLL_RUNS: None,
        MAX_ENTITIES: 1,
        MAX_JURISDICTIONS: 1,
        MAX_SCHEDULES: 2,
        MAX_BWM: 50,
        MULTI_ENTITY: 0,
        MULTI_CURRENCY: 0,
        API_ACCESS: 0,
        ASSIST: 0,
    },
    PlanCode.PROFESSIONAL.value: {
        PAYROLL_RUNS: None,
        MAX_ENTITIES: 3,
        MAX_JURISDICTIONS: 3,
        MAX_SCHEDULES: 10,
        MAX_BWM: 250,
        MULTI_ENTITY: None,
        MULTI_CURRENCY: None,
        API_ACCESS: None,
        ASSIST: None,
    },
}

SCALE_LIMIT_KEYS = (MAX_ENTITIES, MAX_JURISDICTIONS, MAX_SCHEDULES, MAX_BWM)


def _actor_user_id(db) -> int:
    actor = db.query(User).filter(User.role == UserRole.SUPER_ADMIN).order_by(User.id).first()
    return actor.id if actor is not None else None


def _version_matches_target(db, version, target_flags: dict) -> bool:
    current = plan_catalog.list_entitlement_flags(db, version.id)
    return all(current.get(key) == value for key, value in target_flags.items())


def _migrate_plan(db, plan_code: str, actor_user_id: int) -> None:
    target_flags = TARGET_FLAGS[plan_code]

    old_version = plan_catalog.get_published_plan_version(db, plan_code)
    if old_version is not None and _version_matches_target(db, old_version, target_flags):
        print(f"{plan_code}: published version already matches target flags — nothing to do.")
        return

    plan = db.query(BillingPlan).filter(BillingPlan.code == plan_code).first()
    if plan is None:
        print(f"{plan_code}: no BillingPlan row exists yet — run the seed script for it first.")
        return

    new_version = plan_catalog.create_plan_version(
        db,
        plan_id=plan.id,
        feature_set={"features": list(target_flags)},
        scale_limits={key: target_flags[key] for key in SCALE_LIMIT_KEYS},
        actor_user_id=actor_user_id,
    )
    print(f"{plan_code}: created plan_version_id={new_version.id} version={new_version.version} (DRAFT)")

    for feature_key, limit_value in target_flags.items():
        plan_catalog.add_entitlement_flag(
            db, plan_version_id=new_version.id, feature_key=feature_key,
            limit_value=limit_value, actor_user_id=actor_user_id,
        )

    plan_catalog.approve_plan_version(db, new_version.id, actor_user_id=actor_user_id)
    published = plan_catalog.publish_plan_version(db, new_version.id, published_by_user_id=actor_user_id)
    print(f"{plan_code}: published plan_version_id={published.id}")

    if old_version is not None:
        plan_catalog.retire_plan_version(db, old_version.id, actor_user_id=actor_user_id)
        print(f"{plan_code}: retired old plan_version_id={old_version.id} (version={old_version.version})")

        _migrate_subscriptions(db, old_version.id, published.id, actor_user_id)


def _migrate_subscriptions(db, old_version_id: int, new_version_id: int, actor_user_id: int) -> None:
    """Move every BillingSubscription off old_version_id onto new_version_id
    in one transaction, auditing each org individually so the trail shows
    exactly who moved and when — not just an aggregate count."""
    subs = db.query(BillingSubscription).filter(BillingSubscription.plan_version_id == old_version_id).all()
    if not subs:
        print(f"  no subscriptions pointed at plan_version_id={old_version_id}.")
        return

    for sub in subs:
        sub.plan_version_id = new_version_id
        db.add(sub)
        db.add(
            BillingCommercialAuditEvent(
                organization_id=sub.organization_id,
                actor_user_id=actor_user_id,
                event_type="PLAN_VERSION_MIGRATED",
                payload={
                    "subscription_id": sub.id,
                    "old_plan_version_id": old_version_id,
                    "new_plan_version_id": new_version_id,
                },
            )
        )
    db.commit()
    print(f"  migrated {len(subs)} subscription(s) from plan_version_id={old_version_id} to {new_version_id}.")


def main() -> None:
    initialize_database()
    db = SessionLocal()
    try:
        actor_user_id = _actor_user_id(db)
        for plan_code in (PlanCode.CORE.value, PlanCode.PROFESSIONAL.value):
            _migrate_plan(db, plan_code, actor_user_id)
        print("Done.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
