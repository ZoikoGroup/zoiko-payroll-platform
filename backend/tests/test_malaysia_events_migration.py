"""Malaysia events / clearance-holds migration 5f314f975ac3 (ZP-MY-ENG-001 Phase 7).

Built FROM THE MIGRATION (not the models): the three WORKER tables match the
models' columns and indexes, every CHECK rule works on real rows (submission
four-eyes, cancellation reason, clearance only for CP22A / CP21, release
four-eyes, one open hold per employee, one line per payslip); the policy is
d7f9b1c3e5a6's WORKER/"org"; replay is a no-op and downgrade removes only its
own tables; literal names, manifest and single-child chain; no statutory
number in a CHECK constraint (due dates / hold maximum are signed content).
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

REVISION, PARENT, SUFFIX = "5f314f975ac3", "13574b996ccf", "my_events_holds"
WORKER = ("payroll_my_employer_events", "payroll_my_clearance_holds", "payroll_my_clearance_hold_lines")


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
    model_indexes = {t: _indexes(engine, t) for t in WORKER}
    _run(engine, "downgrade")
    _run(engine, "upgrade")
    with engine.begin() as conn:
        conn.execute(sa.text("PRAGMA foreign_keys=OFF"))
    yield engine, metadata, model_indexes
    engine.dispose()


def test_rls_matches_classify_and_is_emitted(classified):
    rls, worker, tenant = classified
    for table in WORKER:
        assert worker.get(table) == "org" and table not in tenant, table
    bind = _CaptureBind()
    _load(REVISION)._rls_for_new_tables(bind)
    assert _policies(bind.sql) == {t: " ".join(rls._worker_predicate("org").split()) for t in WORKER}


def test_tables_built_by_the_migration_match_the_models(migrated):
    engine, metadata, model_indexes = migrated
    for table in WORKER:
        assert _cols(engine, table) == {c.name for c in metadata.tables[table].columns}, table
        assert model_indexes[table] <= _indexes(engine, table), table


def _insert(conn, table, **values):
    conn.execute(sa.text(f"INSERT INTO {table} ({', '.join(values)}) VALUES ({', '.join(':' + k for k in values)})"),
                 values)


def _event(**over):
    values = dict(organization_id=1, employee_id=1, event_type="CP22A", event_date=date(2026, 6, 30),
                  status="OPEN", clearance_required=True, created_by_id=1, created_at=datetime(2026, 5, 1))
    values.update(over)
    return values


@pytest.mark.parametrize("over, ok", [
    ({}, True),
    ({"event_type": "CP22", "clearance_required": True}, False),            # clearance only CP22A / CP21
    ({"status": "SUBMITTED"}, False),                                        # needs receipt + evidence + 2nd person
    ({"status": "SUBMITTED", "submitted_on": date(2026, 5, 2), "receipt_ref": "R1", "evidence_ref": "e",
      "approved_by_id": 1}, False),                                          # same person
    ({"status": "SUBMITTED", "submitted_on": date(2026, 5, 2), "receipt_ref": "R1", "evidence_ref": "e",
      "approved_by_id": 2}, True),
    ({"status": "CANCELLED"}, False),
    ({"status": "CANCELLED", "cancel_reason": "stayed"}, True),
    ({"event_type": "CP23"}, False),
])
def test_event_checks(migrated, over, ok):
    engine, *_ = migrated
    with engine.connect() as conn:
        if ok:
            _insert(conn, "payroll_my_employer_events", **_event(**over))
        else:
            with pytest.raises(IntegrityError):
                _insert(conn, "payroll_my_employer_events", **_event(**over))


def _hold(**over):
    values = dict(organization_id=1, employee_id=1, event_id=1, opened_on=date(2026, 6, 1),
                  hold_until=date(2026, 8, 30), state="HELD", created_by_id=1, created_at=datetime(2026, 6, 1))
    values.update(over)
    return values


@pytest.mark.parametrize("over, ok", [
    ({}, True),
    ({"hold_until": date(2026, 5, 1)}, False),
    ({"state": "RELEASE_REQUESTED"}, False),                                  # needs reference + evidence + requester
    ({"state": "RELEASED", "release_reference": "HASiL letter", "release_evidence_ref": "scan",
      "release_requested_by_id": 1, "released_by_id": 1, "released_at": datetime(2026, 7, 1)}, False),
    ({"state": "RELEASED", "release_reference": "HASiL letter", "release_evidence_ref": "scan",
      "release_requested_by_id": 1, "released_by_id": 2, "released_at": datetime(2026, 7, 1)}, True),
    ({"state": "PAID_OUT"}, False),
])
def test_hold_checks(migrated, over, ok):
    engine, *_ = migrated
    with engine.connect() as conn:
        if ok:
            _insert(conn, "payroll_my_clearance_holds", **_hold(**over))
        else:
            with pytest.raises(IntegrityError):
                _insert(conn, "payroll_my_clearance_holds", **_hold(**over))


def test_one_open_hold_per_employee_and_one_line_per_payslip(migrated):
    engine, *_ = migrated
    with engine.connect() as conn:
        _insert(conn, "payroll_my_clearance_holds", **_hold())
        with pytest.raises(IntegrityError):
            _insert(conn, "payroll_my_clearance_holds", **_hold())
        _insert(conn, "payroll_my_clearance_holds", **_hold(state="LAPSED"))          # closed holds do not count
        line = dict(organization_id=1, employee_id=1, hold_id=1, payslip_item_id=7, amount=100,
                    status="HELD", created_at=datetime(2026, 6, 30))
        _insert(conn, "payroll_my_clearance_hold_lines", **line)
        with pytest.raises(IntegrityError):
            _insert(conn, "payroll_my_clearance_hold_lines", **line)
        with pytest.raises(IntegrityError):
            _insert(conn, "payroll_my_clearance_hold_lines", **{**line, "payslip_item_id": 8, "amount": -1})


def test_replay_is_a_no_op_and_downgrade_removes_only_its_own_tables(migrated):
    engine, *_ = migrated
    before = {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()}
    _run(engine, "upgrade")
    assert {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()} == before
    _run(engine, "downgrade")
    assert set(before) - set(sa.inspect(engine).get_table_names()) == set(WORKER)
    assert "payroll_my_worker_profiles" in sa.inspect(engine).get_table_names()       # P2 untouched


def test_literal_names_manifest_chain_and_lock_timeout():
    module = _load(REVISION)
    assert (module.revision, module.down_revision) == (REVISION, PARENT)
    children = [p.name for p in VERSIONS.glob("*.py")
                if re.search(rf'down_revision[^\n]*"{PARENT}"', p.read_text(encoding="utf-8"))]
    assert children == [f"{REVISION}_{SUFFIX}.py"]
    text = (VERSIONS / f"{REVISION}_{SUFFIX}.py").read_text(encoding="utf-8")
    for table in WORKER:
        assert f'op.create_table(\n            "{table}"' in text, table
    assert "lock_timeout" in text
    manifest = (VERSIONS.parent / "MIGRATIONS_MANIFEST.txt").read_text(encoding="utf-8")
    assert f"{REVISION}_{SUFFIX}.py|{REVISION}|{PARENT}|" in manifest


def test_no_statutory_number_is_a_check_constraint():
    text = (VERSIONS / f"{REVISION}_{SUFFIX}.py").read_text(encoding="utf-8")
    checks = re.findall(r'CheckConstraint\((?:f)?"([^"]*)"', text)
    for value in ("30", "90", "60"):
        assert not any(re.search(rf"\b{value}\b", c) for c in checks), value
