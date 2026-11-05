"""New Zealand leave-pay migration c6ea8c6c35ce (ZP-NZ-ENG-001 Phase 6).

WORKER "org" RLS derived by d7f9b1c3e5a6; tables and the three added columns
equal the models; additive and idempotent both ways; the drift filter explains
everything; and the database enforces the calculation, cash-up, final-pay and
correction rules."""
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
REVISION = "c6ea8c6c35ce"
PARENT = "ac08988ecd3a"
NEW_TABLES = ("payroll_nz_final_pay_cases", "payroll_nz_leave_pay_calculations", "payroll_nz_cash_up_requests",
              "payroll_nz_corrections")
SHARED = {"payslip_items": {"nz_correction_of_id"}, "payroll_runs": {"nz_run_options"},
          "payroll_nz_leave_events": {"leave_pay_calculation_id"}}


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
    for table in NEW_TABLES:
        assert worker.get(table) == "org" and table not in set(tenant), table
    bind = _CaptureBind()
    _load()._rls_for_new_tables(bind)
    want = " ".join(rls._worker_predicate("org").split())
    policies = {s.split(' ON "', 1)[1].split('"', 1)[0]: s.split(" USING ", 1)[1].split(" WITH CHECK ", 1)[0]
                for s in bind.sql if s.startswith("CREATE POLICY")}
    assert policies == {t: want for t in NEW_TABLES}


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


def test_tables_and_columns_match_models(model_engine):
    engine, metadata = model_engine
    model_indexes = {t: _indexes(engine, t) for t in NEW_TABLES}
    _run(engine, "downgrade")
    for table, names in SHARED.items():
        assert not names & _cols(engine, table), table
    _run(engine, "upgrade")
    for table in NEW_TABLES:
        assert _cols(engine, table) == {c.name for c in metadata.tables[table].columns}, table
        assert model_indexes[table] <= _indexes(engine, table), table
    for table, names in SHARED.items():
        assert names <= _cols(engine, table) and names <= {c.name for c in metadata.tables[table].columns}


def test_replay_noop_and_downgrade_only_own_objects(model_engine):
    engine, _m = model_engine
    before = {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()}
    _run(engine, "upgrade")
    assert {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()} == before
    _run(engine, "downgrade")
    _run(engine, "downgrade")
    assert set(before) - set(sa.inspect(engine).get_table_names()) == set(NEW_TABLES)
    assert "payroll_nz_leave_events" in sa.inspect(engine).get_table_names()          # P5 untouched


def test_drift_filter_explains():
    import os

    from scripts.drift_pending_filter import pending_objects

    here = os.getcwd()
    os.chdir(VERSIONS.parents[1])
    try:
        tables, columns = pending_objects(PARENT)
    finally:
        os.chdir(here)
    # P8 (dd8a60634320) is pending on the same chain.
    assert tables == set(NEW_TABLES) | {"payroll_nz_filings", "payroll_nz_remittances", "payroll_nz_remittance_lines", "payroll_nz_settlements", "payroll_nz_run_exceptions"}
    assert columns == {**SHARED, "payroll_nz_employer_profiles": {"nz_journal_accounts"}}


def test_single_child_literal_and_manifest():
    module = _load()
    assert (module.revision, module.down_revision) == (REVISION, PARENT)
    text = next(VERSIONS.glob(f"{REVISION}_*.py")).read_text(encoding="utf-8")
    for table in NEW_TABLES:
        assert f'op.create_table(\n            "{table}"' in text, table
    for table, names in SHARED.items():
        for name in names:
            assert f'op.add_column("{table}", sa.Column("{name}"' in text
    manifest = (VERSIONS.parent / "MIGRATIONS_MANIFEST.txt").read_text(encoding="utf-8")
    assert f"c6ea8c6c35ce_nz_leave_pay.py|{REVISION}|{PARENT}|" in manifest


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


def _calc(**kw):
    values = dict(organization_id=1, employee_id=1, employment_id=1, pay_on=date(2026, 6, 1),
                  purpose="ANNUAL_LEAVE", method_pair="OWP_AWE", candidate_a_name="OWP", candidate_a_amount=1200,
                  candidate_b_name="AWE", candidate_b_amount=1300, chosen="AWE", statutory_reason="greater of",
                  units=1, unit="WEEKS", rate_amount=1300, amount=1300, inputs={}, pack_hash="a" * 64)
    values.update(kw)
    return values


def test_chosen_must_be_a_candidate(model_engine):
    engine, metadata = model_engine
    t = "payroll_nz_leave_pay_calculations"
    _rejects(engine, metadata, t, **_calc(chosen="RDP"))
    _rejects(engine, metadata, t, **_calc(amount=-1))
    _rejects(engine, metadata, t, **_calc(purpose="FAMILY_VIOLENCE"))                    # must be restricted
    _insert(engine, metadata, t, **_calc(leave_event_id=5))
    _rejects(engine, metadata, t, **_calc(leave_event_id=5))                             # one live per event
    _insert(engine, metadata, t, **_calc(leave_event_id=5, status="VOID"))
    _insert(engine, metadata, t, **_calc(method_pair="PCT_GROSS", chosen="PCT", unit="AMOUNT",
                                         candidate_a_name=None, candidate_b_name=None))


def test_cash_up_one_open_per_entitlement(model_engine):
    engine, metadata = model_engine
    t = "payroll_nz_cash_up_requests"
    row = dict(organization_id=1, employee_id=1, employment_id=1, entitlement_id=3, requested_on=date(2026, 6, 1),
               written_request_ref="letter.pdf", weeks=1)
    _rejects(engine, metadata, t, **dict(row, weeks=0))
    _insert(engine, metadata, t, **row)
    _rejects(engine, metadata, t, **row)
    _insert(engine, metadata, t, **dict(row, status="REJECTED"))


def test_one_final_case_per_employment(model_engine):
    engine, metadata = model_engine
    t = "payroll_nz_final_pay_cases"
    row = dict(organization_id=1, employee_id=1, employment_id=1, termination_date=date(2026, 10, 15),
               termination_reason="RESIGNED")
    _insert(engine, metadata, t, **row)
    _rejects(engine, metadata, t, **row)
    _insert(engine, metadata, t, **dict(row, status="CANCELLED"))


def test_original_payslip_restrict_on_delete():
    table = _metadata().tables["payroll_nz_corrections"]
    fk = next(iter(table.c.original_payslip_item_id.foreign_keys))
    assert fk.ondelete == "RESTRICT" and not table.c.original_payslip_item_id.nullable
    text = next(VERSIONS.glob(f"{REVISION}_*.py")).read_text(encoding="utf-8")
    assert 'sa.ForeignKey("payslip_items.id", ondelete="RESTRICT")' in text
