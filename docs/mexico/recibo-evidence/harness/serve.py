"""Backend on the Recibo scratch DB (see setup_db.py). Mexico is opened for
this process only the way the tests open it (flag + registry AVAILABLE), and
the stamped XML is read from the same local store the setup wrote."""
import os
import sys
from pathlib import Path

url = os.environ.get("PAYROLL_DATABASE_URL", "")
assert url.startswith("sqlite:///") and "scratchpad" in url, f"refusing non-scratch database: {url!r}"
FILES = Path(os.environ["RECIBO_FILES"])
os.environ["UPLOAD_BASE_DIR"] = str(FILES / "uploads")
os.environ["PAYROLL_STORAGE_BACKEND"] = "local"
os.environ["PAYROLL_CORS_ORIGINS"] = "http://127.0.0.1:5174"
BACKEND = Path(__file__).resolve().parents[4] / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from sqlalchemy import event  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import engine  # noqa: E402
from app.modules.payroll import mexico_dormancy  # noqa: E402


@event.listens_for(engine, "connect")
def _advisory_lock_stub(dbapi_conn, _record):     # SQLite has no pg_advisory_xact_lock
    dbapi_conn.create_function("pg_advisory_xact_lock", 1, lambda key: 1)


settings.MX_TENANT_ONBOARDING_ENABLED = True
mexico_dormancy.registry_available = lambda db: True

import uvicorn  # noqa: E402

from app.main import app  # noqa: E402
from app.modules.billing.entitlements import require_active_subscription  # noqa: E402

# The SYNTHETIC organisations have no subscription; the tests' client
# (tests/test_hong_kong_governance._http) overrides this same gate.
app.dependency_overrides[require_active_subscription] = lambda: None

uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
