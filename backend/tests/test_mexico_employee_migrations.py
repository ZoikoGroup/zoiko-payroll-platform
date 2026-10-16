"""Mexico Phase 4b migration mx_employee_m3 (8b2f6d4e1a93) on the SHARED
statutory-profile table.

SQLite (always): guarded, idempotent upgrade/downgrade; every new column
nullable with no default; other countries' profile rows untouched.

PostgreSQL (when MX_PG_TEST_URL points at a THROWAWAY database — skipped
otherwise, e.g. in CI): the statements actually emitted are captured and
must be exactly the approved plan — `SET LOCAL lock_timeout = '5s'`, ONE
`ALTER TABLE … ADD COLUMN …` with both FKs `NOT VALID`, then one
`VALIDATE CONSTRAINT` per FK — and a held lock makes the migration fail
fast (lock_timeout) instead of queueing."""

import os
import re
import time

import pytest
import sqlalchemy as sa

REVISION = "8b2f6d4e1a93"
PROFILE = "payroll_employee_statutory_profiles"
MX_COLUMNS = 24


def _module():
    import importlib.util
    from pathlib import Path

    path = next((Path(__file__).resolve().parents[1] / "alembic" / "versions").glob(f"{REVISION}_*.py"))
    spec = importlib.util.spec_from_file_location("mx_employee_m3", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(conn, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    with Operations.context(MigrationContext.configure(conn)):
        getattr(_module(), fn)()


def _seed_other_countries(engine):
    """An NL and an HK statutory profile row that must survive untouched.
    Organisation and employees through the ORM (model defaults apply); the
    profile rows in raw SQL, because the profile model already carries the
    mx_* columns this test removes first."""
    from sqlalchemy.orm import Session

    from app.modules.organizations.models import Organization
    from app.modules.payroll.models import PayrollEmployee

    with Session(engine) as s:
        org = Organization(organization_name="o", organization_code="M3O", workspace_type="EVALUATION")
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


def _mx_columns(engine):
    return {col["name"]: col for col in sa.inspect(engine).get_columns(PROFILE) if col["name"].startswith("mx_")}


def test_revision_links():
    mod = _module()
    assert (mod.revision, mod.down_revision) == (REVISION, "6e4a1d9c3f27")
    assert len(mod._COLUMNS) == MX_COLUMNS


# ── SQLite ────────────────────────────────────────────────────────────────

@pytest.fixture()
def sqlite_engine(tmp_path):
    import app.modules.payroll.models  # noqa: F401
    from app.database import Base

    eng = sa.create_engine(f"sqlite:///{tmp_path / 'm3.db'}")
    Base.metadata.create_all(eng)
    with eng.begin() as c:                                              # start from the pre-m3 schema
        _run(c, "downgrade")
    return eng


def test_sqlite_upgrade_downgrade_idempotent_and_other_rows_untouched(sqlite_engine):
    eng = sqlite_engine
    assert not _mx_columns(eng) and "payroll_mx_infonavit_notices" not in sa.inspect(eng).get_table_names()
    _seed_other_countries(eng)
    before = _profile_rows(eng)
    for _ in range(2):
        with eng.begin() as c:
            _run(c, "upgrade")
    cols = _mx_columns(eng)
    assert len(cols) == MX_COLUMNS
    assert all(col["nullable"] and col.get("default") is None for col in cols.values())
    assert "payroll_mx_infonavit_notices" in sa.inspect(eng).get_table_names()
    assert _profile_rows(eng) == before
    with eng.connect() as c:
        assert c.execute(sa.text("SELECT count(*) FROM payroll_employee_statutory_profiles "
                                 "WHERE mx_curp_token IS NOT NULL OR mx_work_state IS NOT NULL")).scalar() == 0
    for _ in range(2):
        with eng.begin() as c:
            _run(c, "downgrade")
    assert not _mx_columns(eng) and _profile_rows(eng) == before


# ── PostgreSQL (throwaway server only) ────────────────────────────────────

PG_URL = os.getenv("MX_PG_TEST_URL")
pg = pytest.mark.skipif(not PG_URL, reason="MX_PG_TEST_URL not set (throwaway PostgreSQL only)")


@pytest.fixture()
def pg_engine():
    import app.modules.payroll.models  # noqa: F401
    from app.database import Base

    assert "mx4b" in PG_URL and "127.0.0.1" in PG_URL, "refusing a non-throwaway PostgreSQL URL"
    eng = sa.create_engine(PG_URL)
    with eng.begin() as c:
        c.execute(sa.text("DROP SCHEMA public CASCADE"))
        c.execute(sa.text("CREATE SCHEMA public"))
    Base.metadata.create_all(eng)
    with eng.begin() as c:
        _run(c, "downgrade")
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
    assert len(alters) == 1, alters                                       # ONE statement for every column
    assert alters[0].count("ADD COLUMN") == MX_COLUMNS and alters[0].count("NOT VALID") == 2
    validates = [s for s in on_profile if "VALIDATE CONSTRAINT" in s]
    assert validates == [f"ALTER TABLE {PROFILE} VALIDATE CONSTRAINT fk_statutory_profile_mx_establishment",
                         f"ALTER TABLE {PROFILE} VALIDATE CONSTRAINT fk_statutory_profile_mx_imss_registration"]
    assert not [s for s in on_profile if re.search(r"\bDEFAULT\b", s)]    # no default → no table rewrite
    with eng.connect() as c:
        valid = dict(c.execute(sa.text("SELECT conname, convalidated FROM pg_constraint WHERE conname LIKE "
                                       "'fk_statutory_profile_mx_%'")).fetchall())
    assert valid == {"fk_statutory_profile_mx_establishment": True, "fk_statutory_profile_mx_imss_registration": True}
    assert _profile_rows(eng) == before and len(_mx_columns(eng)) == MX_COLUMNS
    with eng.begin() as c:                                                 # re-run is a no-op
        _run(c, "upgrade")
    with eng.begin() as c:
        _run(c, "downgrade")
    assert not _mx_columns(eng) and _profile_rows(eng) == before


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
    assert 4 <= elapsed < 15, elapsed                                      # waited ~5 s, then gave up
    assert not _mx_columns(eng)                                            # nothing half-applied
