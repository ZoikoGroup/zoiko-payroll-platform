"""Start the backend on the X4 scratch DB. Usage: python serve_x4.py on|off
(MX_TENANT_ONBOARDING_ENABLED for this process only)."""
import os
import sys
from pathlib import Path

url = os.environ.get("PAYROLL_DATABASE_URL", "")
assert url.startswith("sqlite:///") and "scratchpad" in url, f"refusing non-scratch database: {url!r}"
os.environ["PAYROLL_CORS_ORIGINS"] = "http://127.0.0.1:4173"      # the vite preview origin, this process only
BACKEND = Path(r"D:\zoiko_payroll_platform\Zoiko-payroll-platform\backend")
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(BACKEND)

import x4_patches  # noqa: E402

x4_patches.apply(sys.argv[1])

import uvicorn  # noqa: E402

from app.main import app  # noqa: E402

uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
