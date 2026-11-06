"""Poland migrations after the foundation (ZP-PL-ENG-001 P6 e11c2c36df17, P8
e75b9219e1f8, P9 e7ec6c1933b4): the same contract as 1ee3bbde33bb — RLS as
classify() derives it, tables exactly the models, idempotent replay, downgrade
removes only its own tables, literal names, manifest entry, single-child chain."""
import re

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.pool import StaticPool

from tests.test_poland_migrations import (VERSIONS, _CaptureBind, _cols, _indexes, _load, _metadata, _policies,
                                          classified)  # noqa: F401  (pytest fixture)

REVISIONS = [
    # (revision, parent, file suffix, TENANT tables, WORKER tables)
    ("e11c2c36df17", "1ee3bbde33bb", "pl_incapacity_episodes", (), ("payroll_pl_incapacity_episodes",)),
    ("e75b9219e1f8", "e11c2c36df17", "pl_filing_settlement",
     ("payroll_pl_filings", "payroll_pl_settlements", "payroll_pl_reconciliation_variances"), ()),
    ("e7ec6c1933b4", "e75b9219e1f8", "pl_parallel_cycles", ("payroll_pl_parallel_imports",),
     ("payroll_pl_parallel_differences",)),
]
IDS = [r[0] for r in REVISIONS]


@pytest.fixture()
def model_engine():
    metadata = _metadata()
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    metadata.create_all(engine)
    yield engine, metadata
    engine.dispose()


def _run(engine, revision, fn_name):
    module = _load(revision)
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            getattr(module, fn_name)()


@pytest.mark.parametrize("revision, parent, suffix, tenant, worker", REVISIONS, ids=IDS)
def test_rls_matches_classify_and_is_emitted(classified, revision, parent, suffix, tenant, worker):
    rls, classified_worker, classified_tenant = classified
    for table in tenant:
        assert table in classified_tenant and table not in classified_worker, table
    for table in worker:
        assert classified_worker.get(table) == "org" and table not in classified_tenant, table
    bind = _CaptureBind()
    _load(revision)._rls_for_new_tables(bind)
    want = {t: " ".join(rls._TENANT_PREDICATE.split()) for t in tenant}
    want.update({t: " ".join(rls._worker_predicate("org").split()) for t in worker})
    assert _policies(bind.sql) == want


@pytest.mark.parametrize("revision, parent, suffix, tenant, worker", REVISIONS, ids=IDS)
def test_tables_match_models_replay_and_downgrade(model_engine, revision, parent, suffix, tenant, worker):
    engine, metadata = model_engine
    tables = tenant + worker
    model_indexes = {t: _indexes(engine, t) for t in tables}
    before = {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()}
    _run(engine, revision, "upgrade")                                        # replay over the model schema
    assert {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()} == before
    _run(engine, revision, "downgrade")
    assert set(before) - set(sa.inspect(engine).get_table_names()) == set(tables)
    _run(engine, revision, "upgrade")
    for table in tables:
        assert _cols(engine, table) == {c.name for c in metadata.tables[table].columns}, table
        assert model_indexes[table] <= _indexes(engine, table), table


@pytest.mark.parametrize("revision, parent, suffix, tenant, worker", REVISIONS, ids=IDS)
def test_chain_literal_names_and_manifest(revision, parent, suffix, tenant, worker):
    module = _load(revision)
    assert (module.revision, module.down_revision) == (revision, parent)
    children = [p.name for p in VERSIONS.glob("*.py")
                if re.search(rf'down_revision[^\n]*"{parent}"', p.read_text(encoding="utf-8"))]
    assert children == [f"{revision}_{suffix}.py"]
    text = (VERSIONS / f"{revision}_{suffix}.py").read_text(encoding="utf-8")
    for table in tenant + worker:
        assert f'op.create_table(\n            "{table}"' in text, table
    assert "lock_timeout" in text
    manifest = (VERSIONS.parent / "MIGRATIONS_MANIFEST.txt").read_text(encoding="utf-8")
    assert f"{revision}_{suffix}.py|{revision}|{parent}|" in manifest
