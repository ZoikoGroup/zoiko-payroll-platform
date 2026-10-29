"""Start the backend on the scratch DB for the completion W4/W5 browser check
(Mexico onboarding flag OFF, as in production)."""
import os
import sys
from pathlib import Path

url = os.environ.get("PAYROLL_DATABASE_URL", "")
assert url.startswith("sqlite:///") and "scratchpad" in url, f"refusing non-scratch database: {url!r}"
os.environ["PAYROLL_CORS_ORIGINS"] = "http://127.0.0.1:4173"      # the vite preview origin, this process only
BACKEND = Path(r"D:\zoiko_payroll_platform\Zoiko-payroll-platform\backend")
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from sqlalchemy import event  # noqa: E402

from app.database import engine  # noqa: E402


@event.listens_for(engine, "connect")
def _advisory_lock_stub(dbapi_conn, _record):     # SQLite has no pg_advisory_xact_lock
    dbapi_conn.create_function("pg_advisory_xact_lock", 1, lambda key: 1)


import uvicorn  # noqa: E402

from app.main import app  # noqa: E402

uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
