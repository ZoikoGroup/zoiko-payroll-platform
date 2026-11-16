"""Belgium Block M-ECWC migration e9c4b7a2d6f3 be_onss_rate_table.

Four new platform tables exactly the models (codes are TEXT), six new employer-registration columns (facts UNKNOWN by
default), autogenerate no-diff, idempotent replay, a round trip that removes only what it added, the four-eyes and
vocabulary CHECKs in the database, literal names, manifest entry, single child of main's merge e3f9a7c1b5d2 and the single head,
and the deploy drift filter explains every new table and column. SYNTHETIC data only."""
import re

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.pool import StaticPool

from tests.test_belgium_migrations import BACKEND, VERSIONS, _cols, _indexes, _load, _metadata

REVISION = "e9c4b7a2d6f3"
PARENT = "e3f9a7c1b5d2"            # main's merge revision (Mexico + Malaysia + Belgium Block K)
FILENAME = f"{REVISION}_be_onss_rate_table.py"
NEW_TABLES = ("payroll_be_onss_rate_files", "payroll_be_onss_rates", "payroll_be_onss_code_combinations",
              "payroll_be_onss_type_rules")
EMPLOYER = "payroll_be_employer_registrations"
NEW_COLUMNS = {"closure_fund_sector", "closure_fund_sector_evidence_ref", "workforce_class",
               "workforce_class_evidence_ref", "wage_moderation_status", "wage_moderation_evidence_ref"}


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


def test_new_tables_and_columns_match_the_models_exactly(model_engine):
    engine, metadata = model_engine
    model_indexes = {t: _indexes(engine, t) for t in NEW_TABLES}
    _run(engine, "downgrade")
    assert not set(NEW_TABLES) & set(sa.inspect(engine).get_table_names())
    assert not NEW_COLUMNS & _cols(engine, EMPLOYER)
    _run(engine, "upgrade")
    for table in NEW_TABLES:
        assert _cols(engine, table) == {c.name for c in metadata.tables[table].columns}, table
        assert model_indexes[table] <= _indexes(engine, table), table
        assert "organization_id" not in _cols(engine, table)                     # platform-level: no RLS
    assert _cols(engine, EMPLOYER) == {c.name for c in metadata.tables[EMPLOYER].columns}
    types = {c["name"]: c["type"] for t in ("payroll_be_onss_rates", "payroll_be_onss_code_combinations")
             for c in sa.inspect(engine).get_columns(t)}
    for column in ("employer_class", "code", "contribution_type", "worker_code", "contribution_code"):
        assert isinstance(types[column], sa.String), column                        # codes are TEXT, never numbers


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
    watched = NEW_TABLES + tuple(NEW_COLUMNS)
    assert [d for d in flat if any(t in repr(d) for t in watched)] == []


def test_replay_is_a_no_op_and_the_round_trip_removes_only_what_it_added(model_engine):
    engine, _m = model_engine
    before = {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()}
    _run(engine, "upgrade")
    assert {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()} == before
    _run(engine, "downgrade")
    after = {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()}
    assert set(before) - set(after) == set(NEW_TABLES)
    assert before[EMPLOYER] - after[EMPLOYER] == NEW_COLUMNS
    assert {t: c for t, c in after.items() if t != EMPLOYER} == {t: c for t, c in before.items()
                                                                  if t not in NEW_TABLES and t != EMPLOYER}
    _run(engine, "downgrade")                                                     # idempotent
    _run(engine, "upgrade")
    assert {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()} == before


def test_the_database_enforces_four_eyes_and_vocabularies(model_engine):
    engine, _m = model_engine
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO payroll_jurisdiction_packs (id, pack_id, jurisdiction_country, pack_type, "
                             "version, status) VALUES (1, 'BE-TEST', 'BE', 'tax', '1.0', 'Draft')"))
        conn.execute(sa.text("INSERT INTO payroll_source_artifacts (id, agency, title) VALUES (1, 'A', 'T')"))
        conn.execute(sa.text("INSERT INTO payroll_be_onss_rate_files (id, jurisdiction_pack_id, quarter, effective_from, "
                             "effective_to, source_document_id, checksum_sha256, registered_by_id) VALUES "
                             "(1, 1, '20263', '2026-07-01', '2026-09-30', 1, 'x', 7)"))
    bad = (
        # an attestation by the registrar, or without an attester
        "UPDATE payroll_be_onss_rate_files SET status = 'ATTESTED', attested_by_id = 7, attested_at = '2026-11-16'",
        "UPDATE payroll_be_onss_rate_files SET status = 'ATTESTED'",
        # a signed rate row signed by whoever made it live, or unsigned
        "INSERT INTO payroll_be_onss_rates (rate_file_id, employer_class, code_kind, code, contribution_type, status, "
        "marked_live_by_id, signed_by_id, signed_at) VALUES (1, '000', 'CONTRIBUTION', '015', '1', 'SIGNED', 8, 8, "
        "'2026-11-16')",
        "INSERT INTO payroll_be_onss_rates (rate_file_id, employer_class, code_kind, code, contribution_type, status) "
        "VALUES (1, '000', 'CONTRIBUTION', '015', '1', 'SIGNED')",
        "INSERT INTO payroll_be_onss_rates (rate_file_id, employer_class, code_kind, code, contribution_type) "
        "VALUES (1, '000', 'PERSON', '015', '1')",
        "INSERT INTO payroll_be_onss_code_combinations (rate_file_id, employer_class, worker_code, contribution_code, "
        "status) VALUES (1, '000', '015', '809', 'SIGNED')",
        "INSERT INTO payroll_be_onss_type_rules (jurisdiction_pack_id, code, outcome, effective_from, status, "
        "created_by_id, signed_by_id, signed_at) VALUES (1, '809', '0', '2026-01-01', 'SIGNED', 9, 9, '2026-11-16')",
    )
    for sql in bad:
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
    for column in NEW_COLUMNS:
        assert f'"{column}"' in source, column
    assert not re.search(r"\b\d+\.\d+\b", source.split('"""', 2)[2])           # no statutory number
    manifest = (BACKEND / "alembic" / "MIGRATIONS_MANIFEST.txt").read_text(encoding="utf-8")
    assert f"{FILENAME}|{REVISION}|{PARENT}|" in manifest
    children = [p.name for p in VERSIONS.glob("*.py")
                if re.search(rf'down_revision[^\n]*"{PARENT}"', p.read_text(encoding="utf-8"))]
    assert children == [FILENAME]
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    assert script.get_heads() == [REVISION]


def test_the_deploy_drift_filter_explains_every_new_table_and_column():
    import os

    from scripts.drift_pending_filter import pending_objects

    here = os.getcwd()
    os.chdir(BACKEND)
    try:
        tables, columns = pending_objects(PARENT)
    finally:
        os.chdir(here)
    assert tables == set(NEW_TABLES)
    assert set(columns.get(EMPLOYER, ())) == NEW_COLUMNS
