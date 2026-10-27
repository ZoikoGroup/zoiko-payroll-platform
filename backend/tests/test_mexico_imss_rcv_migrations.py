"""Mexico completion A18 migration c7d2e9a4f1b6 (mx_imss_rcv_authority_m19) — widens
the CHECK constraint ck_mx_liability_authority to admit IMSS_RCV. No table or
column is created.

SQLite (always): guarded, idempotent upgrade / downgrade; rows kept; an IMSS_RCV
row is refused before and accepted after; downgrade refuses while one exists.

PostgreSQL (MX_PG6_TEST_URL → a THROWAWAY database on 127.0.0.1, else skipped):
  - in flight (DDL applied, not committed): ACCESS EXCLUSIVE on
    payroll_mx_authority_liabilities only; organizations still readable;
  - a reader holding that table makes the upgrade fail fast (~5 s) with nothing
    applied; a re-run completes;
  - the table keeps its row-level-security policy;
  - the real CLI (env.py) and check_schema_drift pass."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import sqlalchemy as sa

REVISION, PARENT = "c7d2e9a4f1b6", "b9f3d5a1c7e2"
BACKEND = Path(__file__).resolve().parents[1]
TABLE = "payroll_mx_authority_liabilities"


def _module():
    import importlib.util

    path = next((BACKEND / "alembic" / "versions").glob(f"{REVISION}_*.py"))
    spec = importlib.util.spec_from_file_location("mx_imss_rcv_authority_m19", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rls():
    import importlib.util

    path = BACKEND / "alembic" / "versions" / "d7f9b1c3e5a6_postgres_row_level_security.py"
    spec = importlib.util.spec_from_file_location("zp_rls_m19", path)
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


def _definition(engine):
    for c in sa.inspect(engine).get_check_constraints(TABLE):
        if c.get("name") == "ck_mx_liability_authority":
            return c.get("sqltext") or ""
    return None


def _org(engine):
    from sqlalchemy.orm import Session

    from app.modules.organizations.models import Organization

    with Session(engine) as s:
        org = Organization(organization_name="o", organization_code="M19O", workspace_type="EVALUATION")
        s.add(org)
        s.commit()
        return org.id


def _insert(engine, org_id, authority, period="2026-06"):
    with engine.begin() as c:
        if engine.dialect.name == "postgresql":
            c.execute(sa.text("SELECT set_config('app.rls_mode', 'system', true)"))
        c.execute(sa.text(f"INSERT INTO {TABLE} (organization_id, authority, scope_key, period_key, sequence, "
                          "amount, status, idempotency_key) VALUES (:o, :a, 'REG:1', :p, 1, 10, 'ACCRUED', :k)"),
                  {"o": org_id, "a": authority, "p": period, "k": f"m19:{authority}:{period}"})


def _rows(engine):
    with engine.connect() as c:
        if engine.dialect.name == "postgresql":
            c.execute(sa.text("SELECT set_config('app.rls_mode', 'system', false)"))
        return c.execute(sa.text(f"SELECT id, authority, period_key, amount FROM {TABLE} ORDER BY id")).fetchall()


def test_revision_links():
    mod = _module()
    assert (mod.revision, mod.down_revision) == (REVISION, PARENT)
    assert mod.NEW_COLUMNS == () and "IMSS_RCV" in mod.NEW and "IMSS_RCV" not in mod.OLD


@pytest.fixture()
def sqlite_engine(tmp_path):
    import app.modules.payroll.models  # noqa: F401
    from app.database import Base

    eng = sa.create_engine(f"sqlite:///{tmp_path / 'm19.db'}")
    Base.metadata.create_all(eng)
    _run(eng, "downgrade")
    return eng


def test_sqlite_upgrade_downgrade_idempotent_rows_kept(sqlite_engine):
    eng = sqlite_engine
    assert "IMSS_RCV" not in _definition(eng)
    org = _org(eng)
    _insert(eng, org, "IMSS")
    with pytest.raises(sa.exc.IntegrityError):
        _insert(eng, org, "IMSS_RCV", "2026-07")                    # refused before the upgrade
    before = _rows(eng)
    for _ in range(2):
        _run(eng, "upgrade")
    assert "IMSS_RCV" in _definition(eng) and _rows(eng) == before
    _insert(eng, org, "IMSS_RCV", "2026-07")                        # accepted after
    with pytest.raises(sa.exc.IntegrityError):
        _insert(eng, org, "OTHER", "2026-08")                       # still a closed list
    with pytest.raises(RuntimeError, match="IMSS_RCV liabilities exist"):
        _run(eng, "downgrade")
    with eng.begin() as c:
        c.execute(sa.text(f"DELETE FROM {TABLE} WHERE authority = 'IMSS_RCV'"))
    for _ in range(2):
        _run(eng, "downgrade")
    assert "IMSS_RCV" not in _definition(eng) and _rows(eng) == before


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
    org = _org(eng)
    _insert(eng, org, "IMSS")
    with eng.begin() as c:
        c.execute(sa.text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        c.execute(sa.text("DELETE FROM alembic_version"))
        c.execute(sa.text(f"INSERT INTO alembic_version VALUES ('{PARENT}')"))
    yield eng
    eng.dispose()


def _policy(engine):
    with engine.connect() as c:
        return c.execute(sa.text("SELECT policyname, qual FROM pg_policies WHERE tablename = :t"), {"t": TABLE}).all()


@pg
def test_pg_lock_mode_in_flight_only_the_liability_table(pg_engine):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    eng = pg_engine
    policy, before = _policy(eng), _rows(eng)
    conn = eng.connect()
    tx = conn.begin()
    started = time.perf_counter()
    with Operations.context(MigrationContext.configure(conn)):
        _module().upgrade()
    with eng.connect() as probe:
        modes = probe.execute(sa.text(
            "SELECT c.relname, l.mode FROM pg_locks l JOIN pg_class c ON c.oid = l.relation "
            "WHERE c.relkind = 'r' AND l.granted AND l.pid <> pg_backend_pid() ORDER BY 1, 2")).fetchall()
        probe.execute(sa.text("SET statement_timeout = '1000ms'"))
        probe.execute(sa.text("SELECT set_config('app.rls_mode', 'system', true)"))
        readable = probe.execute(sa.text("SELECT count(*) FROM organizations")).scalar()
        probe.rollback()
    tx.rollback()
    conn.close()
    held_ms = round((time.perf_counter() - started) * 1000, 2)
    print(f"\nMEASURED in flight: locks = {[tuple(m) for m in modes]}; readable = {readable}; ~{held_ms} ms")
    assert {r for r, m in modes if m == "AccessExclusiveLock"} == {TABLE}
    assert readable == 1
    assert "IMSS_RCV" not in _definition(eng)                      # rolled back: nothing applied
    _run(eng, "upgrade")
    assert "IMSS_RCV" in _definition(eng) and _policy(eng) == policy and _rows(eng) == before


@pg
def test_pg_a_reader_on_the_liability_table_makes_it_fail_fast(pg_engine):
    eng = pg_engine
    holder = eng.connect()
    tx = holder.begin()
    holder.execute(sa.text("SELECT set_config('app.rls_mode', 'system', true)"))
    holder.execute(sa.text(f"SELECT count(*) FROM {TABLE}")).scalar()          # an in-flight read
    started = time.monotonic()
    with pytest.raises(sa.exc.OperationalError, match="lock timeout"):
        _run(eng, "upgrade")
    elapsed = time.monotonic() - started
    tx.rollback()
    holder.close()
    print(f"\nMEASURED: with a reader on {TABLE} the upgrade gave up after {elapsed:.2f} s")
    assert 4 <= elapsed < 15 and "IMSS_RCV" not in _definition(eng)
    _run(eng, "upgrade")
    assert "IMSS_RCV" in _definition(eng)


@pg
def test_pg_real_cli_path_and_schema_drift(pg_engine):
    env = {**os.environ, "PAYROLL_DATABASE_URL": PG_URL, "DATABASE_URL": PG_URL, "PYTHONIOENCODING": "utf-8",
           "PAYROLL_DB_SSL_MODE": "disable"}
    up = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env,
                        capture_output=True, text=True, timeout=120)
    assert up.returncode == 0, up.stderr[-2000:]
    drift = subprocess.run([sys.executable, "-m", "scripts.check_schema_drift"], cwd=BACKEND, env=env,
                           capture_output=True, text=True, timeout=120)
    assert drift.returncode == 0, drift.stdout[-2000:] + drift.stderr[-2000:]
