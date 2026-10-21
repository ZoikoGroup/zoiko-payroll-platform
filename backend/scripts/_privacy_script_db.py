"""
scripts/_privacy_script_db.py
-----------------------------
Shared database selection for the ZP-PRIV operational scripts.

The synthetic session builds a throwaway in-memory SQLite database with the
full schema, so a drill never writes into a real log. The live session uses
the configured PAYROLL_DATABASE_URL and is meant to be run by the platform
security owner on the deployment itself.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def synthetic_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import importlib

    for module in ("app.modules.security.models", "app.modules.support_access.models"):
        importlib.import_module(module)  # register their tables on Base.metadata
    from app.database import Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def live_session():
    from app.database import SessionLocal

    return SessionLocal()


def write_json(path, payload) -> None:
    if path is None:
        print(json.dumps(payload, indent=2))
        return
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"written: {out}")
