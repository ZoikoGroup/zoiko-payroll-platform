"""A development process refuses to start against the production database host.

app/config.py runs the guard at import time, so each case imports it in a fresh
interpreter with its own environment. Importing the config never opens a
database connection.
"""

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
PROD_URL = "postgresql+psycopg://someone:not-a-real-password@34.88.166.225:5432/zoiko_payroll"
LOCAL_URL = "postgresql+psycopg://payroll_dev:x@127.0.0.1:5433/zoiko_payroll_dev"


def _import_config(**env):
    full = {k: v for k, v in os.environ.items() if k not in {"ENVIRONMENT", "APP_ENV", "DEBUG"}}
    full.update({"PAYROLL_SECRET_KEY": "a-real-looking-test-secret-0123456789", **env})
    # Run outside backend/ so backend/.env can't supply DEBUG or the URL.
    return subprocess.run([sys.executable, "-c", "import app.config"], cwd=BACKEND.parent,
                          env={**full, "PYTHONPATH": str(BACKEND)}, capture_output=True, text=True)


def test_development_process_refuses_the_production_database():
    for env in ({"DEBUG": "true"}, {"ENVIRONMENT": "development"}):
        result = _import_config(PAYROLL_DATABASE_URL=PROD_URL, **env)
        assert result.returncode != 0, env
        assert "PRODUCTION database host (34.88.166.225)" in result.stderr


def test_production_process_may_use_it_and_development_may_use_a_local_database():
    assert _import_config(PAYROLL_DATABASE_URL=PROD_URL, ENVIRONMENT="production").returncode == 0
    assert _import_config(PAYROLL_DATABASE_URL=LOCAL_URL, DEBUG="true").returncode == 0


def test_the_production_host_list_is_configurable():
    other = PROD_URL.replace("34.88.166.225", "db.prod.example")
    assert _import_config(PAYROLL_DATABASE_URL=other, DEBUG="true").returncode == 0
    blocked = _import_config(PAYROLL_DATABASE_URL=other, DEBUG="true",
                             PRODUCTION_DATABASE_HOSTS="34.88.166.225, DB.prod.example")
    assert blocked.returncode != 0 and "db.prod.example" in blocked.stderr
