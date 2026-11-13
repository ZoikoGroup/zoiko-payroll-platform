"""Belgium Block C migration 8a1f5ef9fa5d be_filing_parallel.

The same contract as the Phase 2 and Block B revisions: RLS as d7f9b1c3e5a6's
classify() derives it, new tables exactly the models, autogenerate no-diff,
idempotent replay, upgrade / downgrade / upgrade round trip removing only its
own objects, literal names, manifest entry, single child, single head, no
statutory number in a CHECK — plus every new CHECK enforced by the database
(filing state machine and four-eyes, correction lineage, obligation
acceptance apart from settlement, variance four-eyes, parallel cycles).
SYNTHETIC data only."""
import re
from datetime import date

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.pool import StaticPool

from tests.test_belgium_migrations import (BACKEND, PG_URL, VERSIONS, _CaptureBind, _cols, _indexes, _load,
                                           _metadata, _policies, classified, pg_round_trip)  # noqa: F401  (pytest fixture)

REVISION = "8a1f5ef9fa5d"
PARENT = "2943a0490b5b"
FILENAME = f"{REVISION}_be_filing_parallel.py"
TENANT = ("payroll_be_filings", "payroll_be_obligations", "payroll_be_reconciliation_variances",
          "payroll_be_parallel_imports")
WORKER = ("payroll_be_parallel_differences",)
NEW_TABLES = TENANT + WORKER


@pytest.fixture()
def model_engine():
    metadata = _metadata()
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    metadata.create_all(engine)
    yield engine, metadata
    engine.dispose()


def _run(engine, fn_name, revision=REVISION):
    module = _load(revision)
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            getattr(module, fn_name)()


# -- row-level security -----------------------------------------------------
def test_classify_agrees_with_the_policies_the_revision_applies(classified):
    _rls, worker, tenant = classified
    for table in TENANT:
        assert table in tenant and table not in worker, table
    for table in WORKER:
        assert worker.get(table) == "org" and table not in tenant, table


def test_revision_emits_the_derived_policy_on_its_own_tables_only(classified):
    rls = classified[0]
    bind = _CaptureBind()
    _load(REVISION)._rls_for_new_tables(bind)
    want = {t: " ".join(rls._TENANT_PREDICATE.split()) for t in TENANT}
    want.update({t: " ".join(rls._worker_predicate("org").split()) for t in WORKER})
    assert _policies(bind.sql) == want


# -- migration <-> model contract ------------------------------------------
def test_new_tables_match_the_models_exactly(model_engine):
    engine, metadata = model_engine
    model_indexes = {t: _indexes(engine, t) for t in NEW_TABLES}
    _run(engine, "downgrade")
    for table in NEW_TABLES:
        assert table not in sa.inspect(engine).get_table_names(), table
    _run(engine, "upgrade")
    for table in NEW_TABLES:
        assert _cols(engine, table) == {c.name for c in metadata.tables[table].columns}, table
        assert model_indexes[table] <= _indexes(engine, table), table


def test_autogenerate_sees_no_difference_for_belgium(model_engine):
    from alembic.autogenerate import compare_metadata

    engine, metadata = model_engine
    _run(engine, "downgrade")
    _run(engine, "upgrade")
    with engine.connect() as conn:
        diffs = compare_metadata(MigrationContext.configure(conn), metadata)
    flat = []
    for d in diffs:
        flat.extend(d if isinstance(d, list) else [d])
    assert [d for d in flat if "payroll_be_" in repr(d)] == []


def test_replay_over_the_full_model_schema_is_a_no_op(model_engine):
    engine, _m = model_engine
    before = {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()}
    _run(engine, "upgrade")
    _run(engine, "upgrade")
    assert {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()} == before


def test_round_trip_removes_only_its_own_objects(model_engine):
    engine, _m = model_engine
    tables_before = set(sa.inspect(engine).get_table_names())
    _run(engine, "downgrade")
    assert tables_before - set(sa.inspect(engine).get_table_names()) == set(NEW_TABLES)
    _run(engine, "downgrade")                                                                     # idempotent
    _run(engine, "upgrade")
    assert set(sa.inspect(engine).get_table_names()) == tables_before


def test_deploy_drift_filter_explains_every_object():
    import os

    from scripts.drift_pending_filter import pending_objects

    here = os.getcwd()
    os.chdir(BACKEND)
    try:
        tables, columns = pending_objects(PARENT)
    finally:
        os.chdir(here)
    assert tables == set(NEW_TABLES) | {"payroll_mx_document_access_events"}
    assert all(t.startswith("payroll_mx_") for t in columns)


def test_revision_is_the_single_child_and_the_single_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    module = _load(REVISION)
    assert (module.revision, module.down_revision) == (REVISION, PARENT)
    children = [p.name for p in VERSIONS.glob("*.py")
                if re.search(rf'down_revision[^\n]*"{PARENT}"', p.read_text(encoding="utf-8"))]
    assert children == [FILENAME]
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    assert list(script.get_heads()) == ["4de7c091ab32"]


def test_names_are_literal_and_the_migration_is_in_the_manifest():
    text = (VERSIONS / FILENAME).read_text(encoding="utf-8")
    for table in NEW_TABLES:
        assert f'op.create_table(\n            "{table}"' in text, table
    manifest = (VERSIONS.parent / "MIGRATIONS_MANIFEST.txt").read_text(encoding="utf-8")
    assert f"{FILENAME}|{REVISION}|{PARENT}|" in manifest


def test_no_statutory_number_is_a_check_constraint():
    source = (VERSIONS / FILENAME).read_text(encoding="utf-8")
    checks = re.findall(r'CheckConstraint\((.*?)name=', source, re.S)
    assert checks
    for body in checks:
        assert not re.search(r"\d+\.\d+", body), body
        assert set(re.findall(r"\b\d+\b", body)) <= {"0"}, body


def test_vocabularies_match_models_and_migration():
    from app.modules.payroll import models

    module = _load(REVISION)
    assert module.AUTHORITIES == models._BE_FILING_AUTHORITIES
    assert module.FORMS == models._BE_FILING_FORMS
    assert module.KINDS == models._BE_FILING_KINDS
    assert module.FILING_STATUSES == models._BE_FILING_STATUSES
    assert module.OBLIGATION_TYPES == models._BE_OBLIGATION_TYPES
    assert module.OBLIGATION_STATUSES == models._BE_OBLIGATION_STATUSES
    assert module.ACCEPTANCE_STATES == models._BE_ACCEPTANCE_STATES
    assert module.VARIANCE_KINDS == models._BE_VARIANCE_KINDS
    assert module.CONCEPTS == models._BE_PARALLEL_CONCEPTS


def test_no_schema_version_or_date_is_a_vocabulary():
    """The DmfA schema version and the authority calendar are content rows
    (BE-034 / BE-035), never a CHECK list."""
    source = (VERSIONS / FILENAME).read_text(encoding="utf-8")
    assert "2026/" not in source.split('"""', 2)[2]


# -- database rules ---------------------------------------------------------
def _insert(engine, metadata, table, **values):
    with engine.begin() as conn:
        conn.execute(metadata.tables[table].insert().values(**values))


def _rejects(engine, metadata, table, **values):
    with pytest.raises(sa.exc.IntegrityError):
        _insert(engine, metadata, table, **values)


def _filing(key, **over):
    base = dict(organization_id=1, authority="ONSS", form_code="DMFA", period_key="2026Q3", payload={},
                payload_hash="a" * 64, idempotency_key=key, status="DRAFT", created_by_id=1)
    base.update(over)
    return base


def test_filing_rules(model_engine):
    engine, metadata = model_engine
    t = "payroll_be_filings"
    _insert(engine, metadata, t, **_filing("k1"))
    _rejects(engine, metadata, t, **_filing("k1"))                                          # idempotency key
    _rejects(engine, metadata, t, **_filing("k2", authority="RSZ"))
    _rejects(engine, metadata, t, **_filing("k3", form_code="DRS"))
    _rejects(engine, metadata, t, **_filing("k4", status="SENT"))
    _rejects(engine, metadata, t, **_filing("k5", kind="CORRECTION"))                      # corrects nothing
    _insert(engine, metadata, t, **_filing("k6", kind="CORRECTION", corrects_id=1))
    _rejects(engine, metadata, t, **_filing("k7", status="APPROVED", schema_version="S"))  # no approver
    _rejects(engine, metadata, t, **_filing("k8", status="APPROVED", schema_version="S", approved_by_id=1))
    _rejects(engine, metadata, t, **_filing("k9", status="APPROVED", approved_by_id=2))    # no schema version
    _insert(engine, metadata, t, **_filing("k10", status="APPROVED", schema_version="S", approved_by_id=2))
    _rejects(engine, metadata, t, **_filing("k11", status="ACCEPTED", schema_version="S", approved_by_id=2))
    _insert(engine, metadata, t, **_filing("k12", status="ACCEPTED", schema_version="S", approved_by_id=2,
                                           submission_ref="TEST-REF"))


def test_obligation_rules(model_engine):
    engine, metadata = model_engine
    t = "payroll_be_obligations"
    base = dict(organization_id=1, obligation_type="ONSS_QUARTER", period_key="2026Q3", obligation_key="o1",
                amount_due=10)
    _insert(engine, metadata, t, **base)
    with engine.connect() as conn:
        row = conn.execute(sa.text(f"SELECT acceptance_status, status FROM {t}")).one()
    assert tuple(row) == ("NOT_FILED", "DUE")
    _rejects(engine, metadata, t, **base)                                                    # unique key
    _rejects(engine, metadata, t, **dict(base, obligation_key="o2", obligation_type="VAT"))
    _rejects(engine, metadata, t, **dict(base, obligation_key="o3", amount_due=-1))
    _rejects(engine, metadata, t, **dict(base, obligation_key="o4", status="RECONCILED"))
    _rejects(engine, metadata, t, **dict(base, obligation_key="o5", acceptance_status="MAYBE"))
    # accepted but unpaid is a legal, open state (BE-036)
    _insert(engine, metadata, t, **dict(base, obligation_key="o6", acceptance_status="ACCEPTED", status="DUE"))


def test_variance_rules(model_engine):
    engine, metadata = model_engine
    _insert(engine, metadata, "payroll_be_obligations", organization_id=1, obligation_type="WITHHOLDING",
            period_key="2026-09", obligation_key="o1", amount_due=10)
    t = "payroll_be_reconciliation_variances"
    base = dict(organization_id=1, obligation_id=1, variance_kind="UNDERPAID", expected_amount=10, actual_amount=5,
                difference=5, raised_by_id=1)
    _insert(engine, metadata, t, **base)
    _rejects(engine, metadata, t, **dict(base, variance_kind="LOST"))
    _rejects(engine, metadata, t, **dict(base, status="RESOLVED", resolved_by_id=2))        # no resolution
    _rejects(engine, metadata, t, **dict(base, status="RESOLVED", resolved_by_id=1, resolution="ok"))
    _insert(engine, metadata, t, **dict(base, status="RESOLVED", resolved_by_id=2, resolution="paid late"))


def test_parallel_rules(model_engine):
    engine, metadata = model_engine
    t = "payroll_be_parallel_imports"
    base = dict(organization_id=1, pay_date=date(2026, 9, 30), cycle_month=date(2026, 9, 1), source_name="TEST ONLY",
                file_hash="f" * 64, column_map={}, created_by_id=1)
    _insert(engine, metadata, t, **base)
    _rejects(engine, metadata, t, **dict(base, file_hash="g" * 64, status="ACCEPTED", approved_by_id=1))
    _insert(engine, metadata, t, **dict(base, file_hash="h" * 64, status="ACCEPTED", approved_by_id=2))
    d = "payroll_be_parallel_differences"
    diff = dict(organization_id=1, import_id=1, employee_id=1, concept="gross", incumbent_amount=1, zoiko_amount=2,
                difference=1)
    _insert(engine, metadata, d, **diff)
    _rejects(engine, metadata, d, **diff)                                                     # one per concept
    _rejects(engine, metadata, d, **dict(diff, concept="bonus"))
    _rejects(engine, metadata, d, **dict(diff, concept="net", status="EXPLAINED"))           # no explanation
    _rejects(engine, metadata, d, **dict(diff, concept="net", status="ACCEPTED", explanation="x", explained_by_id=1,
                                         approved_by_id=1))
    _insert(engine, metadata, d, **dict(diff, concept="net", status="ACCEPTED", explanation="x", explained_by_id=1,
                                        approved_by_id=2))


@pytest.mark.skipif(not PG_URL, reason="ZP_TEST_POSTGRES_URL not set (disposable Postgres only)")
def test_postgres_round_trip_with_row_level_security():
    """The revision on a real PostgreSQL with row-level security (CI privacy-isolation job)."""
    pg_round_trip(REVISION, NEW_TABLES, TENANT, WORKER)
