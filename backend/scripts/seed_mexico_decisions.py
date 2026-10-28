"""
seed_mexico_decisions.py
------------------------
Mexico final mile X1: load every OPEN decision (docs/mexico/DECISIONS_PENDING.md
D-01 …, gap register C4 / C5 / C12) into the decision register as OPEN records.
Idempotent: a code that already has a record is never touched, whatever its state.

Never runs on deploy. Same strict guard as seed_mexico_canonical_packs: it refuses
unless ZOIKO_ALLOW_NONLOCAL_DB_WRITES=I_UNDERSTAND is set AND the printed target
database is confirmed interactively (type CONFIRM). A non-interactive run is refused.

Usage:
    python -m scripts.seed_mexico_decisions
"""
import os
import sys

from app.database import SessionLocal, initialize_database
from scripts._local_db_guard import describe_target, is_local_database
from scripts.seed_mexico_canonical_packs import _OVERRIDE_ENV, _OVERRIDE_VALUE

NAME = "seed_mexico_decisions"


def _require_confirmed_target() -> None:
    target = describe_target()
    print(f"[{NAME}] TARGET DATABASE: {target or '<not configured>'}")
    if (os.environ.get(_OVERRIDE_ENV) or "").strip() != _OVERRIDE_VALUE:
        print(f"[{NAME}] REFUSING - set {_OVERRIDE_ENV}={_OVERRIDE_VALUE} to proceed (required even for a local "
              f"target).", file=sys.stderr)
        raise SystemExit(2)
    if not is_local_database():
        print(f"[{NAME}] WARNING: the target is NOT a local/isolated database ({target}). Confirm carefully below.",
              file=sys.stderr)
    if not sys.stdin.isatty():
        print(f"[{NAME}] REFUSING - non-interactive run: re-run in an interactive terminal and type CONFIRM.",
              file=sys.stderr)
        raise SystemExit(2)
    print(f"[{NAME}] The target database is printed above. Type CONFIRM to proceed:")
    if sys.stdin.readline().strip() != "CONFIRM":
        print(f"[{NAME}] Not confirmed - aborting.", file=sys.stderr)
        raise SystemExit(2)


def main() -> None:
    from app.modules.payroll import mexico_decision_service

    _require_confirmed_target()
    initialize_database()
    db = SessionLocal()
    try:
        out = mexico_decision_service.seed_decisions(db)
        db.commit()
        print(f"added {len(out['added'])}: {', '.join(out['added']) or '-'}; already recorded: "
              f"{', '.join(out['skipped']) or '-'}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
