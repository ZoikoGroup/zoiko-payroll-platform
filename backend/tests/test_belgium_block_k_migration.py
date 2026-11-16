"""Belgium Block K migration b7e4c2a9d5f1 be_gate_evidence_decisions.

New tables exactly the models, autogenerate no-diff, idempotent replay, round trip removing only its own two tables,
literal names, manifest entry, single child of main's merge head cf348b09db2b and the single head, the deploy drift
filter explains both tables, and the four-eyes CHECKs hold in the database. No organisation column, so no RLS policy
(like payroll_source_artifacts). SYNTHETIC data only."""
import re

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.pool import StaticPool

from tests.test_belgium_migrations import BACKEND, VERSIONS, _cols, _indexes, _load, _metadata

REVISION = "b7e4c2a9d5f1"
PARENT = "cf348b09db2b"
FILENAME = f"{REVISION}_be_gate_evidence_decisions.py"
NEW_TABLES = ("payroll_be_gate_evidence", "payroll_be_decisions")


@pytest.fixture()
def model_engine():
    metadata = _metadata()
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    metadata.create_all(engine)
    yield engine, metadata
    engine.dispose()


def _run(engine, fn_name):
    module = _load(REVISION)
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            getattr(module, fn_name)()


def test_new_tables_match_the_models_exactly(model_engine):
    engine, metadata = model_engine
    model_indexes = {t: _indexes(engine, t) for t in NEW_TABLES}
    _run(engine, "downgrade")
    assert not set(NEW_TABLES) & set(sa.inspect(engine).get_table_names())
    _run(engine, "upgrade")
    for table in NEW_TABLES:
        assert _cols(engine, table) == {c.name for c in metadata.tables[table].columns}, table
        assert model_indexes[table] <= _indexes(engine, table), table
        assert "organization_id" not in _cols(engine, table)                     # platform-level: no RLS


def test_autogenerate_sees_no_difference(model_engine):
    from alembic.autogenerate import compare_metadata

    engine, metadata = model_engine
    _run(engine, "downgrade")
    _run(engine, "upgrade")
    with engine.connect() as conn:
        diffs = compare_metadata(MigrationContext.configure(conn), metadata)
    flat = []
    for d in diffs:
        flat.extend(d if isinstance(d, list) else [d])
    assert [d for d in flat if any(t in repr(d) for t in NEW_TABLES)] == []


def test_replay_is_a_no_op_and_the_round_trip_removes_only_its_own_tables(model_engine):
    engine, _m = model_engine
    before = {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()}
    _run(engine, "upgrade")
    assert {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()} == before
    _run(engine, "downgrade")
    assert set(before) - set(sa.inspect(engine).get_table_names()) == set(NEW_TABLES)
    _run(engine, "downgrade")                                                     # idempotent
    _run(engine, "upgrade")
    assert set(sa.inspect(engine).get_table_names()) == set(before)


def test_the_database_enforces_four_eyes(model_engine):
    engine, _m = model_engine
    for sql in ("INSERT INTO payroll_be_gate_evidence (gate, evidence_type, reference, status, recorded_by_id, "
                "decided_by_id, decided_at) VALUES ('G3', 'BE-CONNECTIVITY-DMFA', 'x', 'ACCEPTED', NULL, NULL, NULL)",
                "INSERT INTO payroll_be_gate_evidence (gate, evidence_type, reference) VALUES ('G9', 'X', 'x')",
                "INSERT INTO payroll_be_decisions (gap_key, proposal_text, status) VALUES ('G-01', 'p', 'DECIDED')",
                "INSERT INTO payroll_be_decisions (gap_key, proposal_text, status, decided_value, decided_by_id, "
                "decided_at) VALUES ('G-01', 'p', 'SUPERSEDED', 'v', NULL, NULL)"):
        with pytest.raises(sa.exc.IntegrityError):
            with engine.begin() as conn:
                conn.execute(sa.text(sql))


def test_literal_names_manifest_single_child_and_single_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    module = _load(REVISION)
    assert (module.revision, module.down_revision) == (REVISION, PARENT)
    source = (VERSIONS / FILENAME).read_text(encoding="utf-8")
    for table in NEW_TABLES:
        assert f'op.create_table(\n            "{table}"' in source, table
    assert not re.search(r"\b\d+\.\d+\b", source.split('"""', 2)[2])           # no statutory number
    manifest = (BACKEND / "alembic" / "MIGRATIONS_MANIFEST.txt").read_text(encoding="utf-8")
    assert f"{FILENAME}|{REVISION}|{PARENT}|" in manifest
    children = [p.name for p in VERSIONS.glob("*.py")
                if re.search(rf'down_revision[^\n]*"{PARENT}"', p.read_text(encoding="utf-8"))]
    assert children == [FILENAME]
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    # Block M-ECWC (e9c4b7a2d6f3) is the single child of this revision and the head.
    assert script.get_heads() == ["e9c4b7a2d6f3"]
    assert script.get_revision("e9c4b7a2d6f3").down_revision == REVISION


def test_the_deploy_drift_filter_explains_both_tables():
    import os

    from scripts.drift_pending_filter import pending_objects

    here = os.getcwd()
    os.chdir(BACKEND)
    try:
        tables, columns = pending_objects(PARENT)
        later_tables, later_columns = pending_objects(REVISION)       # Block M-ECWC and after: its own tests
    finally:
        os.chdir(here)
    assert tables - later_tables == set(NEW_TABLES)
    assert {t: c - later_columns.get(t, set()) for t, c in columns.items() if c - later_columns.get(t, set())} == {}
