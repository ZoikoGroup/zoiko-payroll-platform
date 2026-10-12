"""
scripts/seed_core_plan.py
--------------------------
Seed the CORE plan catalog entry + one published plan version, the same
way scripts/seed_professional_plan.py seeds PROFESSIONAL. Once published,
POST /billing/checkout works for plan_code="CORE" with no other backend
changes — that endpoint already resolves any plan_code generically via
plan_catalog.get_published_plan_version.

Idempotent: if a PUBLISHED CORE version already exists, it is left
untouched and the script exits without writing anything.

Usage:
    python -m scripts.seed_core_plan
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, initialize_database
from app.modules.auth.models import User, UserRole
from app.modules.billing import plan_catalog
from app.modules.billing.models import PlanCode, PlanVersionStatus


# Core is the deliberately-limited entry tier (Plan Entitlement spec tier
# matrix): single-entity, single-jurisdiction, no multi-entity/multi-currency/
# API access. Those three capabilities are simply never added as entitlement
# flags below — app/modules/billing/entitlements.py._resolve_entitlement
# already treats "no flag row for this feature_key" as not-entitled, the same
# outcome a limit_value=0 flag would produce, so there is no separate "off"
# representation to invent. Only the flags that are actually ON for Core are
# added, mirroring how seed_professional_plan.py only lists flags it adds.
CORE_ON_FLAGS = {
    "payroll_runs": None,                 # on
    "max_entities": 1,
    "max_jurisdictions": 1,
    "max_payroll_schedules": 2,
    "max_billable_worker_months": 50,
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
        code = PlanCode.CORE.value
        existing = plan_catalog.get_published_plan_version(db, code)
        if existing is not None:
            print(
                f"CORE already has a PUBLISHED version "
                f"(plan_version_id={existing.id}, version={existing.version}) — nothing to do."
            )
            return

        actor = _actor_user_id(db)
        plan = plan_catalog.create_plan(db, code, "Core", actor_user_id=actor)
        print(f"Created billing_plans row: id={plan.id} code={plan.code}")

        version = plan_catalog.create_plan_version(
            db,
            plan_id=plan.id,
            feature_set={"features": list(CORE_ON_FLAGS)},
            scale_limits={
                "max_entities": CORE_ON_FLAGS["max_entities"],
                "max_jurisdictions": CORE_ON_FLAGS["max_jurisdictions"],
                "max_payroll_schedules": CORE_ON_FLAGS["max_payroll_schedules"],
                "max_billable_worker_months": CORE_ON_FLAGS["max_billable_worker_months"],
            },
            actor_user_id=actor,
        )
        print(f"Created billing_plan_versions row: id={version.id} version={version.version}")

        for feature_key, limit_value in CORE_ON_FLAGS.items():
            flag = plan_catalog.add_entitlement_flag(
                db,
                plan_version_id=version.id,
                feature_key=feature_key,
                limit_value=limit_value,
                actor_user_id=actor,
            )
            print(f"  entitlement flag: {flag.feature_key} (limit_value={flag.limit_value})")

        plan_catalog.approve_plan_version(db, version.id, actor_user_id=actor)
        published = plan_catalog.publish_plan_version(db, version.id, published_by_user_id=actor)
        print(
            f"Published CORE: plan_version_id={published.id} "
            f"status={published.status} published_at={published.published_at}"
        )
        assert published.status == PlanVersionStatus.PUBLISHED.value
        print("Done.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
