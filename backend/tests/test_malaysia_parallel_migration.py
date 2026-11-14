"""Malaysia parallel-cycles migration f793f6074257 (ZP-MY-ENG-001 Phase 10, gate G5).

Built FROM THE MIGRATION: the two tables match the models' columns and
indexes; imports are TENANT and differences WORKER/"org" (d7f9b1c3e5a6
classify); the Malaysian concept list and the four-eyes CHECKs hold on real
rows; replay is a no-op and downgrade removes only its own tables; literal
names, manifest and single-child chain.
"""
import re
from datetime import date, datetime

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from tests.test_poland_migrations import (VERSIONS, _CaptureBind, _cols, _indexes, _load, _metadata, _policies,
                                          classified)  # noqa: F401  (pytest fixture)

REVISION, PARENT, SUFFIX = "f793f6074257", "efdc07f97eb5", "my_parallel_cycles"
TENANT, WORKER = ("payroll_my_parallel_imports",), ("payroll_my_parallel_differences",)
TABLES = TENANT + WORKER


def _run(engine, fn_name):
    module = _load(REVISION)
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            getattr(module, fn_name)()


@pytest.fixture()
def migrated():
    metadata = _metadata()
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                              poolclass=StaticPool)
    metadata.create_all(engine)
    model_indexes = {t: _indexes(engine, t) for t in TABLES}
    _run(engine, "downgrade")
    _run(engine, "upgrade")
    with engine.begin() as conn:
        conn.execute(sa.text("PRAGMA foreign_keys=OFF"))
    yield engine, metadata, model_indexes
    engine.dispose()


def test_rls_matches_classify_and_is_emitted(classified):
    rls, worker, tenant = classified
    assert TENANT[0] in tenant and worker.get(WORKER[0]) == "org"
    bind = _CaptureBind()
    _load(REVISION)._rls_for_new_tables(bind)
    assert _policies(bind.sql) == {TENANT[0]: " ".join(rls._TENANT_PREDICATE.split()),
                                   WORKER[0]: " ".join(rls._worker_predicate("org").split())}


def test_tables_built_by_the_migration_match_the_models(migrated):
    engine, metadata, model_indexes = migrated
    for table in TABLES:
        assert _cols(engine, table) == {c.name for c in metadata.tables[table].columns}, table
        assert model_indexes[table] <= _indexes(engine, table), table


def _insert(conn, table, **values):
    conn.execute(sa.text(f"INSERT INTO {table} ({', '.join(values)}) VALUES ({', '.join(':' + k for k in values)})"),
                 values)


def test_concepts_and_four_eyes(migrated):
    engine, *_ = migrated
    with engine.connect() as conn:
        _insert(conn, TENANT[0], organization_id=1, run_id=1, pay_date=date(2026, 3, 31), cycle_month=date(2026, 3, 1),
                source_name="Incumbent", file_hash="h" * 64, row_count=1, matched_count=1, unmatched_count=0,
                column_map="{}", status="OPEN", created_by_id=1, created_at=datetime(2026, 4, 1))
        with pytest.raises(IntegrityError):
            _insert(conn, TENANT[0], organization_id=1, run_id=2, pay_date=date(2026, 3, 31),
                    cycle_month=date(2026, 3, 1), source_name="x", file_hash="g" * 64, row_count=1, matched_count=1,
                    unmatched_count=0, column_map="{}", status="ACCEPTED", created_by_id=1, approved_by_id=1,
                    created_at=datetime(2026, 4, 1))
        base = dict(organization_id=1, import_id=1, employee_id=1, incumbent_amount=1, zoiko_amount=2, difference=1,
                    status="OPEN", created_at=datetime(2026, 4, 1))
        for n, concept in enumerate(("pcb", "epf_employee", "socso_employer", "hrd_levy")):
            _insert(conn, WORKER[0], **{**base, "employee_id": n + 1, "concept": concept})
        with pytest.raises(IntegrityError):
            _insert(conn, WORKER[0], **{**base, "employee_id": 9, "concept": "pit_advance"})
        with pytest.raises(IntegrityError):
            _insert(conn, WORKER[0], **{**base, "employee_id": 10, "concept": "pcb", "status": "ACCEPTED",
                                        "explanation": "x", "explained_by_id": 1, "approved_by_id": 1})


def test_replay_downgrade_chain_and_manifest(migrated):
    engine, *_ = migrated
    before = {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()}
    _run(engine, "upgrade")
    assert {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()} == before
    _run(engine, "downgrade")
    assert set(before) - set(sa.inspect(engine).get_table_names()) == set(TABLES)
    module = _load(REVISION)
    assert (module.revision, module.down_revision) == (REVISION, PARENT)
    children = [p.name for p in VERSIONS.glob("*.py")
                if re.search(rf'down_revision[^\n]*"{PARENT}"', p.read_text(encoding="utf-8"))]
    assert children == [f"{REVISION}_{SUFFIX}.py"]
    text = (VERSIONS / f"{REVISION}_{SUFFIX}.py").read_text(encoding="utf-8")
    assert all(f'op.create_table(\n            "{t}"' in text for t in TABLES) and "lock_timeout" in text
    manifest = (VERSIONS.parent / "MIGRATIONS_MANIFEST.txt").read_text(encoding="utf-8")
    assert f"{REVISION}_{SUFFIX}.py|{REVISION}|{PARENT}|" in manifest
