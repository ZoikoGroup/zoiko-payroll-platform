"""
scripts/seed_business_plan.py
------------------------------
Seed the BUSINESS plan catalog entry + one published plan version, mirroring
seed_professional_plan.py's exact structure (idempotency guard, same
create_plan -> create_plan_version -> flag-loop -> approve_plan_version ->
publish_plan_version sequence).

Business is shipped honestly scoped to what's actually enforceable today:
higher scale limits than Professional, plus the same binary capability
flags Core/Professional already use. It does NOT claim SAML SSO, webhooks,
custom/delegated roles, or a custom report builder — none of those
subsystems exist in this codebase yet (confirmed by direct inspection, see
the Phase 2 scoping notes this seed script's own task was split against).
API access is the same "on" flag Professional already has — there is no
limited/full API tiering mechanism to differentiate Business's API access
from Professional's, so this does not imply a real upgrade that doesn't
exist.

Usage:
    python -m scripts.seed_business_plan
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, initialize_database
from app.modules.auth.models import User, UserRole
from app.modules.billing import plan_catalog
from app.modules.billing.feature_keys import (
    API_ACCESS, MAX_BWM, MAX_ENTITIES, MAX_JURISDICTIONS, MAX_SCHEDULES,
    MULTI_CURRENCY, MULTI_ENTITY, PAYROLL_RUNS,
)
from app.modules.billing.models import PlanCode, PlanVersionStatus

# limit_value=None means "on"/unlimited (a numeric key with None is an
# unlimited cap, a boolean key with None is "on" — see entitlements.py's
# _resolve_entitlement); an int marks a numeric cap. MAX_SCHEDULES=None is
# genuinely unlimited: require_scope_limit() already treats None as
# unlimited natively (see its own docstring) — no code change needed, only
# this seed value.
BUSINESS_FEATURE_FLAGS = {
    PAYROLL_RUNS: None,             # on — same as Core/Professional
    MULTI_ENTITY: None,             # on
    MULTI_CURRENCY: None,           # on
    API_ACCESS: None,               # on — same "on" Professional already has; there is
                                     # no limited/full API tiering mechanism yet, so this
                                     # is not actually a capability upgrade over Professional.
    MAX_ENTITIES: 10,
    MAX_JURISDICTIONS: 10,
    MAX_SCHEDULES: None,            # unlimited
    MAX_BWM: 1000,
}

_SCALE_LIMIT_KEYS = (MAX_ENTITIES, MAX_JURISDICTIONS, MAX_SCHEDULES, MAX_BWM)


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
        code = PlanCode.BUSINESS.value
        existing = plan_catalog.get_published_plan_version(db, code)
        if existing is not None:
            print(
                f"BUSINESS already has a PUBLISHED version "
                f"(plan_version_id={existing.id}, version={existing.version}) — nothing to do."
            )
            return

        actor = _actor_user_id(db)
        plan = plan_catalog.create_plan(
            db, code, "Business", actor_user_id=actor
        )
        print(f"Created billing_plans row: id={plan.id} code={plan.code}")

        version = plan_catalog.create_plan_version(
            db,
            plan_id=plan.id,
            feature_set={"features": list(BUSINESS_FEATURE_FLAGS)},
            scale_limits={k: v for k, v in BUSINESS_FEATURE_FLAGS.items() if k in _SCALE_LIMIT_KEYS},
            actor_user_id=actor,
        )
        print(f"Created billing_plan_versions row: id={version.id} version={version.version}")

        for feature_key, limit_value in BUSINESS_FEATURE_FLAGS.items():
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
            f"Published BUSINESS: plan_version_id={published.id} "
            f"status={published.status} published_at={published.published_at}"
        )
        assert published.status == PlanVersionStatus.PUBLISHED.value
        print("Done.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
