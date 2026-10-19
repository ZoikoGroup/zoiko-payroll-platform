"""Start the backend on the scratch DB with the Phase 7 harness patches.
Usage: python serve.py on|off   (MX_TENANT_ONBOARDING_ENABLED for this process)."""
import os
import sys
from pathlib import Path

url = os.environ.get("PAYROLL_DATABASE_URL", "")
assert url.startswith("sqlite:///") and "scratchpad" in url, f"refusing non-scratch database: {url!r}"
BACKEND = Path(r"D:\zoiko_payroll_platform\Zoiko-payroll-platform\backend")
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(BACKEND)

import patches  # noqa: E402

patches.apply(flag_on=sys.argv[1] == "on")

import uvicorn  # noqa: E402

from app.main import app  # noqa: E402

uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
