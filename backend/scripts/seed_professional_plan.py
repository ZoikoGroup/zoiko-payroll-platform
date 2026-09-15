"""
scripts/seed_professional_plan.py
---------------------------------
Seed the PROFESSIONAL plan catalog entry + one published plan version so the
trial registration path (register_trial) can attach a
BillingSubscription(TRIALING) to a published BillingPlanVersion.

Idempotent: if a PUBLISHED PROFESSIONAL version already exists, it is left
untouched and the script exits without writing anything.

Usage:
    python -m scripts.seed_professional_plan
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, initialize_database
from app.modules.auth.models import User, UserRole
from app.modules.billing import plan_catalog
from app.modules.billing.models import PlanCode, PlanVersionStatus


# A defensible Phase-0 feature set for the Professional evaluation tier. The
# entitlement check path (app/modules/billing/entitlements.py) queries by
# feature_key against billing_entitlement_flags; limit_value=None marks a
# boolean/unlimited grant, an int marks a numeric cap.
PROFESSIONAL_FEATURE_FLAGS = {
    "payroll_runs": None,          # on
    "multi_entity": None,          # on
    "multi_currency": None,        # on
    "api_access": None,            # on
    "max_entities": 1,             # 1 employing entity
}


def _actor_user_id(db) -> int:
    """Prefer a Super Admin as the audit actor; org admins as fallback."""
    actor = (
        db.query(User)
        .filter(User.role == UserRole.SUPER_ADMIN)
        .order_by(User.id)
        .first()
    )
    if actor is None:
        actor = (
            db.query(User)
            .filter(User.role == UserRole.ORG_ADMIN)
            .order_by(User.id)
            .first()
        )
    return actor.id if actor is not None else None


def main() -> None:
    initialize_database()

    db = SessionLocal()
    try:
        code = PlanCode.PROFESSIONAL.value
        existing = plan_catalog.get_published_plan_version(db, code)
        if existing is not None:
            print(
                f"PROFESSIONAL already has a PUBLISHED version "
                f"(plan_version_id={existing.id}, version={existing.version}) — nothing to do."
            )
            return

        actor = _actor_user_id(db)
        plan = plan_catalog.create_plan(
            db, code, "Professional", actor_user_id=actor
        )
        print(f"Created billing_plans row: id={plan.id} code={plan.code}")

        version = plan_catalog.create_plan_version(
            db,
            plan_id=plan.id,
            feature_set={"features": list(PROFESSIONAL_FEATURE_FLAGS)},
            scale_limits={"max_entities": PROFESSIONAL_FEATURE_FLAGS["max_entities"]},
            actor_user_id=actor,
        )
        print(f"Created billing_plan_versions row: id={version.id} version={version.version}")

        for feature_key, limit_value in PROFESSIONAL_FEATURE_FLAGS.items():
            flag = plan_catalog.add_entitlement_flag(
                db,
                plan_version_id=version.id,
                feature_key=feature_key,
                limit_value=limit_value,
                actor_user_id=actor,
            )
            print(
                f"  entitlement flag: {flag.feature_key} "
                f"(limit_value={flag.limit_value})"
            )

        plan_catalog.approve_plan_version(db, version.id, actor_user_id=actor)
        published = plan_catalog.publish_plan_version(db, version.id, published_by_user_id=actor)
        print(
            f"Published PROFESSIONAL: plan_version_id={published.id} "
            f"status={published.status} published_at={published.published_at}"
        )
        assert published.status == PlanVersionStatus.PUBLISHED.value
        print("Done.")
    finally:
        db.close()


if __name__ == "__main__":
    main()