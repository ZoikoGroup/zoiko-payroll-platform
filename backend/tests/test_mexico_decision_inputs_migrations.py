"""Mexico sweep S1 migration efc56f3235e2 (mx_decision_inputs_m21) — seven nullable
columns on three tables, read by decision options: payroll_mx_terminations.indemnity_daily_salary /
indemnity_salary_evidence_ref (D-12 c), payroll_mx_labor_policies.hourly_rate_daily_hours
(D-17 c) / special_pay_withholding_method (D-08 PER_EMPLOYER),
payroll_employee_statutory_profiles.mx_union_member (C12) / mx_sdi_operator_entered /
mx_sdi_evidence_ref (C4 OPERATOR_ENTERED).

SQLite (always): guarded, idempotent upgrade / downgrade; existing rows kept.

PostgreSQL (MX_PG6_TEST_URL → a THROWAWAY database on 127.0.0.1, else skipped):
  - in flight (DDL applied, not committed): ACCESS EXCLUSIVE on the three tables only,
    organizations / payroll_employees still readable; lock_timeout is 5 s;
  - a reader holding the SHARED statutory-profiles table makes the upgrade fail fast
    (~5 s) with nothing applied; a re-run completes;
  - each table keeps its ZP-PRIV row-level-security policy;
  - the real CLI (env.py) upgrades from 3880223bfaa0 and check_schema_drift passes."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import sqlalchemy as sa

REVISION, PARENT = "efc56f3235e2", "3880223bfaa0"
BACKEND = Path(__file__).resolve().parents[1]
COLUMNS = (("payroll_mx_terminations", "indemnity_daily_salary"),
           ("payroll_mx_terminations", "indemnity_salary_evidence_ref"),
           ("payroll_mx_labor_policies", "hourly_rate_daily_hours"),
           ("payroll_employee_statutory_profiles", "mx_union_member"),
           ("payroll_mx_labor_policies", "special_pay_withholding_method"),
           ("payroll_employee_statutory_profiles", "mx_sdi_operator_entered"),
           ("payroll_employee_statutory_profiles", "mx_sdi_evidence_ref"))
TABLES = {t for t, _ in COLUMNS}
PROFILES = "payroll_employee_statutory_profiles"


def _module():
    import importlib.util

    path = next((BACKEND / "alembic" / "versions").glob(f"{REVISION}_*.py"))
    spec = importlib.util.spec_from_file_location("mx_decision_inputs_m21", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rls():
    import importlib.util

    path = BACKEND / "alembic" / "versions" / "d7f9b1c3e5a6_postgres_row_level_security.py"
    spec = importlib.util.spec_from_file_location("zp_rls_m21", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(engine, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            with ctx.begin_transaction():
                getattr(_module(), fn)()
        if engine.dialect.name != "postgresql":
            conn.commit()


def _present(engine):
    insp = sa.inspect(engine)
    return {(t, c) for t, c in COLUMNS if c in {x["name"] for x in insp.get_columns(t)}}


def _seed(engine):
    from sqlalchemy.orm import Session

    from app.modules.organizations.models import Organization
    from app.modules.payroll.models import PayrollEmployee

    with Session(engine) as s:
        org = Organization(organization_name="o", organization_code="M21O", workspace_type="EVALUATION")
        s.add(org)
        s.flush()
        s.add(PayrollEmployee(organization_id=org.id, employee_code="E1", name="x", country_code="MX"))
        s.commit()


def _rows(engine):
    with engine.connect() as c:
        if engine.dialect.name == "postgresql":
            c.execute(sa.text("SELECT set_config('app.rls_mode', 'system', false)"))
        return c.execute(sa.text("SELECT id, employee_code FROM payroll_employees ORDER BY id")).fetchall()


def test_revision_links():
    mod = _module()
    assert (mod.revision, mod.down_revision) == (REVISION, PARENT)
    assert mod.NEW_COLUMNS == COLUMNS


@pytest.fixture()
def sqlite_engine(tmp_path):
    import app.modules.payroll.models  # noqa: F401
    from app.database import Base

    eng = sa.create_engine(f"sqlite:///{tmp_path / 'm21.db'}")
    Base.metadata.create_all(eng)
    _run(eng, "downgrade")
    return eng


def test_sqlite_upgrade_downgrade_idempotent_rows_kept(sqlite_engine):
    eng = sqlite_engine
    assert _present(eng) == set()
    _seed(eng)
    before = _rows(eng)
    for _ in range(2):
        _run(eng, "upgrade")
    assert _present(eng) == set(COLUMNS) and _rows(eng) == before
    for _ in range(2):
        _run(eng, "downgrade")
    assert _present(eng) == set() and _rows(eng) == before


PG_URL = os.getenv("MX_PG6_TEST_URL")
pg = pytest.mark.skipif(not PG_URL, reason="MX_PG6_TEST_URL not set (throwaway PostgreSQL only)")


@pytest.fixture()
def pg_engine():
    import app.modules.payroll.models  # noqa: F401
    from app.database import Base

    assert "mx6run" in PG_URL and "127.0.0.1" in PG_URL, "refusing a non-throwaway PostgreSQL URL"
    eng = sa.create_engine(PG_URL)
    with eng.begin() as c:
        c.execute(sa.text("DROP SCHEMA public CASCADE"))
        c.execute(sa.text("CREATE SCHEMA public"))
    Base.metadata.create_all(eng)
    _run(eng, "downgrade")
    with eng.begin() as c:                                      # production state: d7f9b1c3e5a6 applied
        _rls().apply_rls(c, unset_mode="system")
    _seed(eng)
    with eng.begin() as c:
        c.execute(sa.text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        c.execute(sa.text("DELETE FROM alembic_version"))
        c.execute(sa.text(f"INSERT INTO alembic_version VALUES ('{PARENT}')"))
    yield eng
    eng.dispose()


def _policies(engine):
    with engine.connect() as c:
        return c.execute(sa.text("SELECT tablename, policyname, qual FROM pg_policies WHERE tablename = ANY(:t) "
                                 "ORDER BY 1, 2"), {"t": sorted(TABLES)}).all()


@pg
def test_pg_lock_mode_in_flight_only_the_three_tables(pg_engine):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    eng = pg_engine
    policies = _policies(eng)
    conn = eng.connect()
    tx = conn.begin()
    started = time.perf_counter()
    with Operations.context(MigrationContext.configure(conn)):
        _module().upgrade()
    timeout = conn.execute(sa.text("SHOW lock_timeout")).scalar()
    with eng.connect() as probe:
        modes = probe.execute(sa.text(
            "SELECT c.relname, l.mode FROM pg_locks l JOIN pg_class c ON c.oid = l.relation "
            "WHERE c.relkind = 'r' AND l.granted AND l.pid <> pg_backend_pid() ORDER BY 1, 2")).fetchall()
        probe.execute(sa.text("SET statement_timeout = '1000ms'"))
        probe.execute(sa.text("SELECT set_config('app.rls_mode', 'system', true)"))
        readable = (probe.execute(sa.text("SELECT count(*) FROM organizations")).scalar(),
                    probe.execute(sa.text("SELECT count(*) FROM payroll_employees")).scalar())
        probe.rollback()
    tx.rollback()
    conn.close()
    held_ms = round((time.perf_counter() - started) * 1000, 2)
    print(f"\nMEASURED in flight: locks = {[tuple(m) for m in modes]}; lock_timeout = {timeout}; "
          f"readable = {readable}; ~{held_ms} ms")
    assert timeout == "5s"
    assert {r for r, m in modes if m == "AccessExclusiveLock"} == TABLES
    assert readable == (1, 1)
    assert _present(eng) == set()                                   # rolled back: nothing applied
    _run(eng, "upgrade")
    assert _present(eng) == set(COLUMNS) and _policies(eng) == policies     # RLS policies unchanged


@pg
def test_pg_a_reader_on_the_shared_profiles_table_makes_it_fail_fast(pg_engine):
    eng = pg_engine
    holder = eng.connect()
    tx = holder.begin()
    holder.execute(sa.text("SELECT set_config('app.rls_mode', 'system', true)"))
    holder.execute(sa.text(f"SELECT count(*) FROM {PROFILES}")).scalar()      # an in-flight read
    started = time.monotonic()
    with pytest.raises(sa.exc.OperationalError, match="lock timeout"):
        _run(eng, "upgrade")
    elapsed = time.monotonic() - started
    tx.rollback()
    holder.close()
    print(f"\nMEASURED: with a reader on {PROFILES} the upgrade gave up after {elapsed:.2f} s")
    assert 4 <= elapsed < 15 and _present(eng) == set()             # one transaction: nothing half-applied
    _run(eng, "upgrade")
    assert _present(eng) == set(COLUMNS)


@pg
def test_pg_real_cli_path_and_schema_drift(pg_engine):
    env = {**os.environ, "PAYROLL_DATABASE_URL": PG_URL, "DATABASE_URL": PG_URL, "PYTHONIOENCODING": "utf-8",
           "PAYROLL_DB_SSL_MODE": "disable"}
    up = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env,
                        capture_output=True, text=True, timeout=120)
    assert up.returncode == 0, up.stderr[-2000:]
    assert _present(pg_engine) == set(COLUMNS)
    drift = subprocess.run([sys.executable, "-m", "scripts.check_schema_drift"], cwd=BACKEND, env=env,
                           capture_output=True, text=True, timeout=120)
    assert drift.returncode == 0, drift.stdout[-2000:] + drift.stderr[-2000:]
