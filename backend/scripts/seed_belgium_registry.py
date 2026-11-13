"""
scripts/seed_belgium_registry.py
--------------------------------
Belgium (ZP-BE-ENG-001 Phase 1): ensures Belgium's jurisdiction_service_registry
row exists as PLANNED, so the existing onboarding gate
(tax_resolver.get_jurisdiction_onboarding_block_reason) refuses Belgium with a
clean message.

Idempotent and create-only: an existing BE row is NEVER changed (its
availability moves only through the governed service_registry_transition
hook, which refuses AVAILABLE until release gates G1-G7 are met).

Usage (local / isolated database only — enforced by _local_db_guard):
    python -m scripts.seed_belgium_registry
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, initialize_database  # noqa: E402
from app.modules.payroll import belgium_service  # noqa: E402
from scripts._local_db_guard import assert_local_database  # noqa: E402


def seed_belgium_registry(db) -> str:
    """The BE registry row's availability after seeding (PLANNED when created
    here; whatever it already was otherwise)."""
    return belgium_service.ensure_be_service_registry_row(db)


def main() -> None:
    assert_local_database("seed_belgium_registry")
    initialize_database()
    db = SessionLocal()
    try:
        availability = seed_belgium_registry(db)
        db.commit()
        print(f"Belgium service registry row: availability={availability}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
