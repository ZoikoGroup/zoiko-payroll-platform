"""BR Phase 4b migration br_employee_m3 (b9f3a7c2e5d1), mirroring
test_mexico_employee_migrations.py.

  - payroll_employee_statutory_profiles + 10 nullable br_* columns and one
    nullable FK to the Phase 3 Brazil establishment table (ON DELETE SET NULL).
  - payroll_br_concurrent_inss_declarations / _alimony_orders /
    _vale_transporte_elections  new tables.
  - payroll_br_statutory_profiles  dropped (facts move to the shared br_* block).

SQLite (dev/test): idempotent up/down, every br_* column nullable with no
default, the legacy table gone after upgrade and NOT recreated by downgrade, and
unrelated country profile rows left untouched. PostgreSQL (throwaway server via
BR_PG_TEST_URL): one ADD COLUMN statement with the FK NOT VALID, then a separate
VALIDATE, no DEFAULT (no rewrite) — plus the lock_timeout fail-fast guard.
"""
import os
import importlib.util
import time
from pathlib import Path

import pytest
import sqlalchemy as sa

REVISION = "b9f3a7c2e5d1"
PROFILE = "payroll_employee_statutory_profiles"
LEGACY = "payroll_br_statutory_profiles"
CHILD_TABLES = ("payroll_br_concurrent_inss_declarations", "payroll_br_alimony_orders",
                "payroll_br_vale_transporte_elections")
BR_COLUMNS = 10


def _module():
    path = next((Path(__file__).resolve().parents[1] / "alembic" / "versions").glob(f"{REVISION}_*.py"))
    spec = importlib.util.spec_from_file_location("br_employee_m3", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(conn, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    with Operations.context(MigrationContext.configure(conn)):
        getattr(_module(), fn)()


def _seed_other_countries(engine):
    """An NL and an HK statutory profile row that must survive untouched. The
    profile rows go in raw SQL, because the profile model already carries the
    br_* columns this test removes first."""
    from sqlalchemy.orm import Session

    from app.modules.organizations.models import Organization
    from app.modules.payroll.models import PayrollEmployee

    with Session(engine) as s:
        org = Organization(organization_name="o", organization_code="M3B", workspace_type="EVALUATION")
        s.add(org)
        s.flush()
        emps = [PayrollEmployee(organization_id=org.id, employee_code=f"E{i}", name="x", country_code=cc)
                for i, cc in ((1, "NL"), (2, "HK"))]
        s.add_all(emps)
        s.flush()
        ids = [(e.id, e.country_code) for e in emps]
        org_id = org.id
        s.commit()
    with engine.begin() as c:
        for emp_id, cc in ids:
            c.execute(sa.text("INSERT INTO payroll_employee_statutory_profiles (employee_id, organization_id, "
                              "country_code, effective_from) VALUES (:e, :o, :cc, '2026-01-01')"),
                      {"e": emp_id, "o": org_id, "cc": cc})


def _profile_rows(engine):
    with engine.connect() as c:
        return c.execute(sa.text("SELECT id, country_code, effective_from FROM payroll_employee_statutory_profiles "
                                 "ORDER BY id")).fetchall()


def _br_columns(engine):
    return {col["name"]: col for col in sa.inspect(engine).get_columns(PROFILE) if col["name"].startswith("br_")}


def _tables(engine):
    return set(sa.inspect(engine).get_table_names())


def test_revision_links():
    mod = _module()
    assert (mod.revision, mod.down_revision) == (REVISION, "64424fd61652")
    assert len(mod._COLUMNS) == BR_COLUMNS
    assert mod._FKS == (("fk_br_profile_establishment", "br_establishment_id", "payroll_br_establishments"),)


# ── SQLite ────────────────────────────────────────────────────────────────

@pytest.fixture()
def sqlite_engine(tmp_path):
    import app.modules.payroll.models  # noqa: F401
    from app.database import Base

    eng = sa.create_engine(f"sqlite:///{tmp_path / 'm3b.db'}")
    Base.metadata.create_all(eng)
    with eng.begin() as c:
        _run(c, "downgrade")                                            # back to the pre-m3 schema
        c.execute(sa.text(f"CREATE TABLE {LEGACY} (id INTEGER PRIMARY KEY)"))   # the legacy table this revision drops
    return eng


def test_sqlite_upgrade_downgrade_idempotent_and_other_rows_untouched(sqlite_engine):
    eng = sqlite_engine
    assert not _br_columns(eng) and not (_tables(eng) & set(CHILD_TABLES)) and LEGACY in _tables(eng)
    _seed_other_countries(eng)
    before = _profile_rows(eng)
    for _ in range(2):
        with eng.begin() as c:
            _run(c, "upgrade")
    cols = _br_columns(eng)
    assert len(cols) == BR_COLUMNS
    assert all(col["nullable"] and col.get("default") is None for col in cols.values())
    assert set(CHILD_TABLES) <= _tables(eng)
    assert LEGACY not in _tables(eng)                                  # dropped, facts moved to the shared block
    assert _profile_rows(eng) == before
    with eng.connect() as c:
        assert c.execute(sa.text("SELECT count(*) FROM payroll_employee_statutory_profiles "
                                 "WHERE br_esocial_category IS NOT NULL OR br_establishment_id IS NOT NULL")).scalar() == 0
    for _ in range(2):
        with eng.begin() as c:
            _run(c, "downgrade")
    assert not _br_columns(eng) and not (_tables(eng) & set(CHILD_TABLES))
    assert LEGACY not in _tables(eng)                                  # not recreated by downgrade
    assert _profile_rows(eng) == before


# ── PostgreSQL (throwaway server only) ────────────────────────────────────

PG_URL = os.getenv("BR_PG_TEST_URL")
pg = pytest.mark.skipif(not PG_URL, reason="BR_PG_TEST_URL not set (throwaway PostgreSQL only)")


@pytest.fixture()
def pg_engine():
    import app.modules.payroll.models  # noqa: F401
    from app.database import Base

    assert "br4b" in PG_URL and "127.0.0.1" in PG_URL, "refusing a non-throwaway PostgreSQL URL"
    eng = sa.create_engine(PG_URL)
    with eng.begin() as c:
        c.execute(sa.text("DROP SCHEMA public CASCADE"))
        c.execute(sa.text("CREATE SCHEMA public"))
    Base.metadata.create_all(eng)
    with eng.begin() as c:
        _run(c, "downgrade")
        c.execute(sa.text(f"CREATE TABLE {LEGACY} (id SERIAL PRIMARY KEY)"))
    _seed_other_countries(eng)
    yield eng
    eng.dispose()


@pg
def test_pg_emits_exactly_the_approved_locking_plan(pg_engine):
    eng = pg_engine
    before = _profile_rows(eng)
    statements = []

    @sa.event.listens_for(eng, "before_cursor_execute")
    def _capture(conn, cursor, statement, params, context, executemany):
        statements.append(" ".join(statement.split()))

    with eng.begin() as c:
        _run(c, "upgrade")
    sa.event.remove(eng, "before_cursor_execute", _capture)
    on_profile = [s for s in statements if PROFILE in s and not s.upper().startswith("SELECT")]
    assert "SET LOCAL lock_timeout = '5s'" in statements
    assert statements.index("SET LOCAL lock_timeout = '5s'") < statements.index(on_profile[0])
    alters = [s for s in on_profile if s.startswith(f"ALTER TABLE {PROFILE} ADD COLUMN")]
    assert len(alters) == 1, alters                                    # ONE statement for every column
    assert alters[0].count("ADD COLUMN") == BR_COLUMNS and alters[0].count("NOT VALID") == 1
    validates = [s for s in on_profile if "VALIDATE CONSTRAINT" in s]
    assert validates == [f"ALTER TABLE {PROFILE} VALIDATE CONSTRAINT fk_br_profile_establishment"]
    assert not [s for s in on_profile if "DEFAULT" in s]               # no default → no table rewrite
    with eng.connect() as c:
        valid = dict(c.execute(sa.text("SELECT conname, convalidated FROM pg_constraint WHERE conname = "
                                       "'fk_br_profile_establishment'")).fetchall())
    assert valid == {"fk_br_profile_establishment": True}
    assert _profile_rows(eng) == before and len(_br_columns(eng)) == BR_COLUMNS
    assert set(CHILD_TABLES) <= _tables(eng) and LEGACY not in _tables(eng)
    with eng.begin() as c:                                             # re-run is a no-op
        _run(c, "upgrade")
    with eng.begin() as c:
        _run(c, "downgrade")
    assert not _br_columns(eng) and not (_tables(eng) & set(CHILD_TABLES))
    assert _profile_rows(eng) == before


@pg
def test_pg_a_held_lock_makes_the_migration_fail_fast(pg_engine):
    eng = pg_engine
    holder = eng.connect()
    tx = holder.begin()
    holder.execute(sa.text(f"LOCK TABLE {PROFILE} IN ACCESS SHARE MODE"))   # e.g. a long-running payroll read
    started = time.monotonic()
    with pytest.raises(sa.exc.OperationalError, match="lock timeout"):
        with eng.begin() as c:
            _run(c, "upgrade")
    elapsed = time.monotonic() - started
    tx.rollback()
    holder.close()
    assert 4 <= elapsed < 15, elapsed                                  # waited ~5 s, then gave up
    assert not _br_columns(eng)                                        # nothing half-applied
