"""Malaysia filings / settlements migration efdc07f97eb5 (ZP-MY-ENG-001 Phase 9).

Built FROM THE MIGRATION (not the models): the three TENANT tables match the
models' columns and indexes, the CHECK rules hold on real rows (authority /
form / liability vocabularies, filing four-eyes with an archived schema
version, unique idempotency key, variance four-eyes); the policy is
d7f9b1c3e5a6's TENANT predicate; replay is a no-op and downgrade removes only
its own tables; literal names, manifest and single-child chain.
"""
import re
from datetime import datetime

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from tests.test_poland_migrations import (VERSIONS, _CaptureBind, _cols, _indexes, _load, _metadata, _policies,
                                          classified)  # noqa: F401  (pytest fixture)

REVISION, PARENT, SUFFIX = "efdc07f97eb5", "5f314f975ac3", "my_filing_settlement"
TENANT = ("payroll_my_filings", "payroll_my_settlements", "payroll_my_reconciliation_variances")


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
    model_indexes = {t: _indexes(engine, t) for t in TENANT}
    _run(engine, "downgrade")
    _run(engine, "upgrade")
    with engine.begin() as conn:
        conn.execute(sa.text("PRAGMA foreign_keys=OFF"))
    yield engine, metadata, model_indexes
    engine.dispose()


def test_rls_matches_classify_and_is_emitted(classified):
    rls, worker, tenant = classified
    for table in TENANT:
        assert table in tenant and table not in worker, table
    bind = _CaptureBind()
    _load(REVISION)._rls_for_new_tables(bind)
    assert _policies(bind.sql) == {t: " ".join(rls._TENANT_PREDICATE.split()) for t in TENANT}


def test_tables_built_by_the_migration_match_the_models(migrated):
    engine, metadata, model_indexes = migrated
    for table in TENANT:
        assert _cols(engine, table) == {c.name for c in metadata.tables[table].columns}, table
        assert model_indexes[table] <= _indexes(engine, table), table


def _insert(conn, table, **values):
    conn.execute(sa.text(f"INSERT INTO {table} ({', '.join(values)}) VALUES ({', '.join(':' + k for k in values)})"),
                 values)


def _filing(**over):
    values = dict(organization_id=1, authority="HASIL", form_code="PCB_MONTHLY", period_key="2026-03",
                  kind="ORIGINAL", version=1, payload="{}", payload_hash="h" * 64, idempotency_key="k" * 64,
                  status="DRAFT", created_by_id=1, created_at=datetime(2026, 4, 1))
    values.update(over)
    return values


@pytest.mark.parametrize("over, ok", [
    ({}, True),
    ({"authority": "ZUS"}, False),
    ({"form_code": "DRA"}, False),
    ({"form_code": "PERKESO_EIS_MONTHLY", "authority": "PERKESO"}, True),
    ({"status": "APPROVED", "approved_by_id": 2}, False),                         # no archived schema version
    ({"status": "APPROVED", "approved_by_id": 1, "schema_version": "1.0"}, False),  # same person
    ({"status": "APPROVED", "approved_by_id": 2, "schema_version": "1.0"}, True),
    ({"status": "SUBMITTED", "approved_by_id": 2, "schema_version": "1.0"}, False),  # no submission reference
    ({"kind": "CORRECTION"}, False),                                              # corrects nothing
])
def test_filing_checks(migrated, over, ok):
    engine, *_ = migrated
    with engine.connect() as conn:
        if ok:
            _insert(conn, "payroll_my_filings", **_filing(**over))
        else:
            with pytest.raises(IntegrityError):
                _insert(conn, "payroll_my_filings", **_filing(**over))


def test_idempotency_key_and_settlement_rules(migrated):
    engine, *_ = migrated
    with engine.connect() as conn:
        _insert(conn, "payroll_my_filings", **_filing())
        with pytest.raises(IntegrityError):
            _insert(conn, "payroll_my_filings", **_filing(period_key="2026-04"))     # same idempotency key
        settlement = dict(organization_id=1, liability_type="PERKESO", period_key="2026-03",
                          settlement_key="MY:1:0:PERKESO:2026-03", amount_due=131.2, paid_amount=0, status="DUE",
                          created_at=datetime(2026, 4, 1))
        _insert(conn, "payroll_my_settlements", **settlement)
        for bad in ({"liability_type": "ZUS", "settlement_key": "x1"}, {"amount_due": -1, "settlement_key": "x2"},
                    {"status": "RECONCILED", "settlement_key": "x3"}, {}):
            with pytest.raises(IntegrityError):
                _insert(conn, "payroll_my_settlements", **{**settlement, **bad})
        variance = dict(organization_id=1, settlement_id=1, variance_kind="UNDERPAID", expected_amount=10,
                        actual_amount=5, difference=-5, status="OPEN", raised_by_id=1, created_at=datetime(2026, 4, 2))
        _insert(conn, "payroll_my_reconciliation_variances", **variance)
        with pytest.raises(IntegrityError):
            _insert(conn, "payroll_my_reconciliation_variances",
                    **{**variance, "status": "RESOLVED", "resolution": "ok", "resolved_by_id": 1})


def test_replay_is_a_no_op_and_downgrade_removes_only_its_own_tables(migrated):
    engine, *_ = migrated
    before = {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()}
    _run(engine, "upgrade")
    assert {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()} == before
    _run(engine, "downgrade")
    assert set(before) - set(sa.inspect(engine).get_table_names()) == set(TENANT)
    assert "payroll_my_clearance_holds" in sa.inspect(engine).get_table_names()       # P7 untouched


def test_literal_names_manifest_chain_and_no_statutory_number():
    module = _load(REVISION)
    assert (module.revision, module.down_revision) == (REVISION, PARENT)
    children = [p.name for p in VERSIONS.glob("*.py")
                if re.search(rf'down_revision[^\n]*"{PARENT}"', p.read_text(encoding="utf-8"))]
    assert children == [f"{REVISION}_{SUFFIX}.py"]
    text = (VERSIONS / f"{REVISION}_{SUFFIX}.py").read_text(encoding="utf-8")
    for table in TENANT:
        assert f'op.create_table(\n            "{table}"' in text, table
    assert "lock_timeout" in text
    manifest = (VERSIONS.parent / "MIGRATIONS_MANIFEST.txt").read_text(encoding="utf-8")
    assert f"{REVISION}_{SUFFIX}.py|{REVISION}|{PARENT}|" in manifest
    checks = re.findall(r'CheckConstraint\((?:f)?"([^"]*)"', text)
    for value in ("15", "30", "90", "6000", "1700"):
        assert not any(re.search(rf"\b{value}\b", c) for c in checks), value
