"""New Zealand parallel-cycle migration a8cde2482ef0 (ZP-NZ-ENG-001 Phase 9).

TENANT RLS for imports and WORKER "org" RLS for differences, as d7f9b1c3e5a6
classifies them; tables equal the models; additive and idempotent both ways;
the drift filter explains everything; and the database enforces the
concepts, the explanation and the four-eyes acceptance."""
import importlib.util
import re
from datetime import date
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.pool import StaticPool

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"
REVISION = "a8cde2482ef0"
PARENT = "dd8a60634320"
TENANT = ("payroll_nz_parallel_imports",)
WORKER = ("payroll_nz_parallel_differences",)
NEW_TABLES = TENANT + WORKER


def _load(prefix=REVISION):
    path = next(VERSIONS.glob(f"{prefix}_*.py"))
    spec = importlib.util.spec_from_file_location(f"rev_{prefix}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _metadata():
    from app.database import Base
    import app.modules.organizations.models  # noqa: F401
    import app.modules.auth.models  # noqa: F401
    import app.modules.payroll.models  # noqa: F401
    import app.modules.billing.models  # noqa: F401
    import app.modules.communications.models  # noqa: F401
    return Base.metadata


class _CaptureBind:
    class dialect:
        name = "postgresql"

    def __init__(self):
        self.sql = []

    def execute(self, clause, *a, **k):
        self.sql.append(" ".join(str(clause).split()))


def test_rls_policies_derived():
    metadata = _metadata()
    rls = _load("d7f9b1c3e5a6")
    cols = {n: {c.name for c in t.columns} for n, t in metadata.tables.items()}
    fks = {n: {fk.column.table.name for fk in t.foreign_keys} for n, t in metadata.tables.items()}
    rls._schema = lambda bind: (cols, fks, set(metadata.tables))
    worker, tenant = rls.classify(None)
    for table in TENANT:
        assert table in set(tenant) and table not in worker, table
    for table in WORKER:
        assert worker.get(table) == "org" and table not in set(tenant), table
    bind = _CaptureBind()
    _load()._rls_for_new_tables(bind)
    want_worker = " ".join(rls._worker_predicate("org").split())
    want_tenant = " ".join(rls._TENANT_PREDICATE.split())
    policies = {s.split(' ON "', 1)[1].split('"', 1)[0]: s.split(" USING ", 1)[1].split(" WITH CHECK ", 1)[0]
                for s in bind.sql if s.startswith("CREATE POLICY")}
    assert policies == {**{t: want_tenant for t in TENANT}, **{t: want_worker for t in WORKER}}


@pytest.fixture()
def model_engine():
    metadata = _metadata()
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                              poolclass=StaticPool)
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(sa.text("PRAGMA foreign_keys=OFF"))
    yield engine, metadata
    engine.dispose()


def _run(engine, fn_name):
    module = _load()
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            getattr(module, fn_name)()


def _cols(engine, table):
    return {c["name"] for c in sa.inspect(engine).get_columns(table)}


def _indexes(engine, table):
    return {i["name"] for i in sa.inspect(engine).get_indexes(table)}


def test_tables_match_models(model_engine):
    engine, metadata = model_engine
    model_indexes = {t: _indexes(engine, t) for t in NEW_TABLES}
    _run(engine, "downgrade")
    assert not set(NEW_TABLES) & set(sa.inspect(engine).get_table_names())
    _run(engine, "upgrade")
    for table in NEW_TABLES:
        assert _cols(engine, table) == {c.name for c in metadata.tables[table].columns}, table
        assert model_indexes[table] <= _indexes(engine, table), table


def test_replay_noop_and_downgrade_only_own_objects(model_engine):
    engine, _m = model_engine
    before = {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()}
    _run(engine, "upgrade")
    assert {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()} == before
    _run(engine, "downgrade")
    _run(engine, "downgrade")
    assert set(before) - set(sa.inspect(engine).get_table_names()) == set(NEW_TABLES)
    assert "payroll_nz_filings" in sa.inspect(engine).get_table_names()              # P8 untouched


def test_drift_filter_explains():
    import os

    from scripts.drift_pending_filter import pending_objects

    here = os.getcwd()
    os.chdir(VERSIONS.parents[1])
    try:
        tables, columns = pending_objects(PARENT)
    finally:
        os.chdir(here)
    # Poland P2 (1ee3bbde33bb) is pending on the same chain.
    assert tables == set(NEW_TABLES) | {"payroll_pl_identifier_vault", "payroll_pl_identifier_access_events",
                                        "payroll_pl_employer_registrations", "payroll_pl_worker_profiles",
                                        "payroll_pl_declarations", "payroll_pl_ppk_participations",
                                        "payroll_pl_accumulator_entries",
                                        "payroll_pl_incapacity_episodes",  # + Poland P6 (e11c2c36df17)
                                        "payroll_pl_filings", "payroll_pl_settlements",
                                        "payroll_pl_reconciliation_variances",  # + Poland P8 (e75b9219e1f8)
                                        "payroll_pl_parallel_imports",
                                        "payroll_pl_parallel_differences"}  # + Poland P9 (e7ec6c1933b4)
    assert columns == {"payslip_items": {"pl_calculation_snapshot"}, "payroll_runs": {"pl_approval_fingerprint"}}


def test_single_child_literal_and_manifest():
    module = _load()
    assert (module.revision, module.down_revision) == (REVISION, PARENT)
    text = next(VERSIONS.glob(f"{REVISION}_*.py")).read_text(encoding="utf-8")
    for table in NEW_TABLES:
        assert f'op.create_table(\n            "{table}"' in text, table
    manifest = (VERSIONS.parent / "MIGRATIONS_MANIFEST.txt").read_text(encoding="utf-8")
    assert f"a8cde2482ef0_nz_parallel_cycles.py|{REVISION}|{PARENT}|" in manifest


def test_no_statutory_number_in_checks():
    text = next(VERSIONS.glob(f"{REVISION}_*.py")).read_text(encoding="utf-8")
    for body in re.findall(r'CheckConstraint\((.*?)name=', text, re.S):
        assert not re.search(r"(?<![\w.])(?!0(?![\w.]))\d", body), body


def _insert(engine, metadata, table, **values):
    with engine.begin() as conn:
        conn.execute(metadata.tables[table].insert().values(**values))


def _rejects(engine, metadata, table, **values):
    with pytest.raises(sa.exc.IntegrityError):
        _insert(engine, metadata, table, **values)


def test_imports_four_eyes_and_one_live_file(model_engine):
    engine, metadata = model_engine
    t = "payroll_nz_parallel_imports"
    row = dict(organization_id=1, run_id=4, pay_date=date(2026, 10, 9), cycle_month=date(2026, 10, 1),
               source_name="X", file_hash="a" * 64, column_map={}, created_by_id=1)
    _rejects(engine, metadata, t, **dict(row, status="DONE"))
    _rejects(engine, metadata, t, **dict(row, status="ACCEPTED"))                          # no acceptor
    _rejects(engine, metadata, t, **dict(row, status="ACCEPTED", approved_by_id=1))       # self-accepted
    _rejects(engine, metadata, t, **dict(row, row_count=-1))
    _insert(engine, metadata, t, **row)
    _rejects(engine, metadata, t, **row)                                                   # same file twice
    _insert(engine, metadata, t, **dict(row, status="WITHDRAWN"))


def test_differences_concept_explanation_and_four_eyes(model_engine):
    engine, metadata = model_engine
    t = "payroll_nz_parallel_differences"
    row = dict(organization_id=1, import_id=1, employee_id=1, concept="paye_incl_acc", incumbent_amount=1,
               zoiko_amount=2, difference=1)
    _rejects(engine, metadata, t, **dict(row, concept="bonus"))
    _rejects(engine, metadata, t, **dict(row, status="EXPLAINED"))                          # no explanation
    _rejects(engine, metadata, t, **dict(row, status="ACCEPTED", explanation="x", explained_by_id=1,
                                          approved_by_id=1))
    _insert(engine, metadata, t, **row)
    _rejects(engine, metadata, t, **row)                                                   # one per concept
    _insert(engine, metadata, t, **dict(row, concept="net_pay", status="ACCEPTED", explanation="x",
                                        explained_by_id=1, approved_by_id=2))
