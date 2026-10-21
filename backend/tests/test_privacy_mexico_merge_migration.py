"""The production upgrade path from Rugvedh's ZP-PRIV head e1a3c5e7f9b2 through
a6d2f9c4b8e1 (Mexico M8) → c3e5a7b9d1f4 (merge) → b4d8f2c6a9e3 → c6e1a9d4f2b7 → e7a2c4f9b1d6,
against a database shaped like production (every existing tenant / worker table
already under row-level security) with the live app holding an open read
transaction on "users".

Production deploy 39561229230 (2026-10-21) failed here: c3e5a7b9d1f4 re-ran
apply_rls() over every table and timed out on ALTER TABLE "users" ENABLE ROW
LEVEL SECURITY. The corrected revision touches only the merged-in table.

PostgreSQL only (MX_PG6_TEST_URL → a THROWAWAY database on 127.0.0.1)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa

BACKEND = Path(__file__).resolve().parents[1]
PG_URL = os.getenv("MX_PG6_TEST_URL")
pg = pytest.mark.skipif(not PG_URL, reason="MX_PG6_TEST_URL not set (throwaway PostgreSQL only)")
AFTER_E1A3 = ("payroll_mx_annual_isr_adjustments", "payroll_mx_ptu_allocations", "payroll_mx_ptu_cycles",
              "payroll_mx_terminations", "payroll_mx_vacation_records")


def _rls():
    import importlib.util

    path = BACKEND / "alembic" / "versions" / "d7f9b1c3e5a6_postgres_row_level_security.py"
    spec = importlib.util.spec_from_file_location("zp_rls_merge_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def production_shaped():
    import app.modules.payroll.models  # noqa: F401
    from app.database import Base

    assert "mx6run" in PG_URL and "127.0.0.1" in PG_URL, "refusing a non-throwaway PostgreSQL URL"
    eng = sa.create_engine(PG_URL)
    with eng.begin() as c:
        c.execute(sa.text("DROP SCHEMA public CASCADE"))
        c.execute(sa.text("CREATE SCHEMA public"))
    Base.metadata.create_all(eng)
    with eng.begin() as c:
        for table in AFTER_E1A3:                                    # not in production yet
            c.execute(sa.text(f'DROP TABLE "{table}" CASCADE'))
        _rls().apply_rls(c, unset_mode="system")                    # as scripts/migrate_privacy_rollout.py did
        c.execute(sa.text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        c.execute(sa.text("DELETE FROM alembic_version"))
        c.execute(sa.text("INSERT INTO alembic_version VALUES ('e1a3c5e7f9b2')"))
    yield eng
    eng.dispose()


def _live_reader(eng):
    """An app session idle in a transaction that has read "users"."""
    conn = eng.connect()
    tx = conn.begin()
    conn.execute(sa.text("SELECT set_config('app.rls_mode', 'system', true)"))
    conn.execute(sa.text("SELECT count(*) FROM users")).scalar()
    return conn, tx


@pg
def test_the_old_merge_revision_times_out_on_users_with_a_live_reader(production_shaped):
    """Reproduces the production failure: re-running apply_rls() needs ACCESS
    EXCLUSIVE on "users", which a live reader blocks."""
    eng = production_shaped
    conn, tx = _live_reader(eng)
    try:
        with eng.connect() as mig:
            with mig.begin():
                mig.execute(sa.text("SET LOCAL lock_timeout = '2s'"))
                with pytest.raises(sa.exc.OperationalError, match="lock timeout"):
                    _rls().apply_rls(mig)
    finally:
        tx.rollback()
        conn.close()


@pg
def test_upgrade_from_production_head_succeeds_with_a_live_reader_on_users(production_shaped):
    eng = production_shaped
    with eng.connect() as c:
        users_policy = c.execute(sa.text("SELECT qual FROM pg_policies WHERE tablename = 'users'")).scalars().all()
    conn, tx = _live_reader(eng)
    try:
        env = {**os.environ, "PAYROLL_DATABASE_URL": PG_URL, "DATABASE_URL": PG_URL, "PYTHONIOENCODING": "utf-8",
               "PAYROLL_DB_SSL_MODE": "disable"}
        up = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env,
                            capture_output=True, text=True, timeout=180)
        assert up.returncode == 0, up.stderr[-2500:]
        drift = subprocess.run([sys.executable, "-m", "scripts.check_schema_drift"], cwd=BACKEND, env=env,
                               capture_output=True, text=True, timeout=180)
        assert drift.returncode == 0, drift.stdout[-2000:] + drift.stderr[-2000:]
    finally:
        tx.rollback()
        conn.close()
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    (head,) = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini"))).get_heads()
    with eng.connect() as c:
        assert c.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() == head
        for table in AFTER_E1A3:                                    # every new table protected
            flags = c.execute(sa.text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :t"),
                              {"t": table}).one()
            policies = c.execute(sa.text("SELECT policyname FROM pg_policies WHERE tablename = :t"),
                                 {"t": table}).scalars().all()
            assert tuple(flags) == (True, True) and policies == ["zoiko_rls"], table
        assert c.execute(sa.text("SELECT qual FROM pg_policies WHERE tablename = 'users'")).scalars().all() \
            == users_policy                                         # "users" untouched
        worker, tenant = _rls().classify(c)
    assert worker.get("payroll_mx_vacation_records") == "org"
