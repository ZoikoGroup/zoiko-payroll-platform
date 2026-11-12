"""New Zealand filing / remittance migration dd8a60634320 (ZP-NZ-ENG-001 Phase 8).

TENANT RLS for filings, remittances and settlements and WORKER "org" RLS for
remittance lines and run exceptions, as d7f9b1c3e5a6 classifies them; tables
and the added column equal the models; additive and idempotent both ways; the
drift filter explains everything; and the database enforces one filing
version per payday, one remittance per period, one line per payslip, and
never a minimum-wage exception approval (D-P8-1)."""
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
REVISION = "dd8a60634320"
PARENT = "5739c5ccf50c"   # main's merge of Google OAuth and NZ P6
TENANT = ("payroll_nz_filings", "payroll_nz_remittances", "payroll_nz_settlements")
WORKER = ("payroll_nz_remittance_lines", "payroll_nz_run_exceptions")
NEW_TABLES = TENANT + WORKER
SHARED = {"payroll_nz_employer_profiles": {"nz_journal_accounts"}}


# Mexico m21 (efc56f3235e2, sweep S1) is the head after this chain: its columns are pending too.
MX_M21 = {"payroll_mx_terminations": {"indemnity_daily_salary", "indemnity_salary_evidence_ref"},
          "payroll_mx_labor_policies": {"hourly_rate_daily_hours", "special_pay_withholding_method"},
          "payroll_employee_statutory_profiles": {"mx_union_member", "mx_sdi_operator_entered", "mx_sdi_evidence_ref"}}


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
    assert "payroll_nz_corrections" in sa.inspect(engine).get_table_names()          # P6 untouched


def test_drift_filter_explains():
    import os

    from scripts.drift_pending_filter import pending_objects

    here = os.getcwd()
    os.chdir(VERSIONS.parents[1])
    try:
        tables, columns = pending_objects(PARENT)
    finally:
        os.chdir(here)
    # P9 (a8cde2482ef0) and Poland P2 (1ee3bbde33bb) are pending on the same chain.
    assert tables == set(NEW_TABLES) | {"payroll_nz_parallel_imports", "payroll_nz_parallel_differences",
                                        "payroll_pl_identifier_vault", "payroll_pl_identifier_access_events",
                                        "payroll_pl_employer_registrations", "payroll_pl_worker_profiles",
                                        "payroll_pl_declarations", "payroll_pl_ppk_participations",
                                        "payroll_pl_accumulator_entries",
                                        "payroll_pl_incapacity_episodes",  # + Poland P6 (e11c2c36df17)
                                        "payroll_pl_filings", "payroll_pl_settlements",
                                        "payroll_pl_reconciliation_variances",  # + Poland P8 (e75b9219e1f8)
                                        "payroll_pl_parallel_imports",
                                        "payroll_pl_parallel_differences",  # + Poland P9 (e7ec6c1933b4)
                                        "payroll_be_identifier_vault", "payroll_be_identifier_access_events",
                                        "payroll_be_employer_registrations", "payroll_be_establishment_units",
                                        "payroll_be_worker_profiles", "payroll_be_work_schedules",
                                        "payroll_be_employment_classifications", "payroll_be_declarations",
                                        "payroll_be_accumulator_entries"}  # + Belgium P2 (1d76678ef1a1)
    pl_shared = {"payslip_items": {"pl_calculation_snapshot", "be_calculation_snapshot"},  # + Belgium P2
                 "payroll_runs": {"pl_approval_fingerprint", "be_approval_fingerprint"}}
    assert columns == {**{t: SHARED.get(t, set()) | pl_shared.get(t, set()) for t in {*SHARED, *pl_shared}}, **MX_M21}


def test_single_child_literal_and_manifest():
    module = _load()
    assert (module.revision, module.down_revision) == (REVISION, PARENT)
    text = next(VERSIONS.glob(f"{REVISION}_*.py")).read_text(encoding="utf-8")
    for table in NEW_TABLES:
        assert f'op.create_table(\n            "{table}"' in text, table
    assert 'op.add_column("payroll_nz_employer_profiles", sa.Column("nz_journal_accounts"' in text
    manifest = (VERSIONS.parent / "MIGRATIONS_MANIFEST.txt").read_text(encoding="utf-8")
    assert f"dd8a60634320_nz_filings.py|{REVISION}|{PARENT}|" in manifest


def test_no_statutory_number_in_checks():
    text = next(VERSIONS.glob(f"{REVISION}_*.py")).read_text(encoding="utf-8")
    for body in re.findall(r'CheckConstraint\((.*?)name=', text, re.S):
        assert not re.search(r"(?<![\w.])(?![01](?![\w.]))\d", body), body


def _insert(engine, metadata, table, **values):
    with engine.begin() as conn:
        conn.execute(metadata.tables[table].insert().values(**values))


def _rejects(engine, metadata, table, **values):
    with pytest.raises(sa.exc.IntegrityError):
        _insert(engine, metadata, table, **values)


def test_one_filing_version_per_payday(model_engine):
    engine, metadata = model_engine
    t = "payroll_nz_filings"
    row = dict(organization_id=1, pay_date=date(2026, 10, 9), filing_type="EMPLOYMENT_INFORMATION", run_ids=[1],
               payload={}, payload_hash="a" * 64, channel="PAYDAY_GATEWAY")
    _rejects(engine, metadata, t, **dict(row, channel="EMAIL"))
    _rejects(engine, metadata, t, **dict(row, kind="AMENDMENT"))                         # needs amends_id
    _insert(engine, metadata, t, **row)
    _rejects(engine, metadata, t, **row)                                                 # same version (org)
    _insert(engine, metadata, t, **dict(row, version=2))
    _insert(engine, metadata, t, **dict(row, legal_entity_id=7))
    _rejects(engine, metadata, t, **dict(row, legal_entity_id=7))                        # same version (entity)


def test_one_remittance_per_period_and_one_line_per_payslip(model_engine):
    engine, metadata = model_engine
    t = "payroll_nz_remittances"
    row = dict(organization_id=1, period_start=date(2026, 10, 1), period_end=date(2026, 10, 31),
               remittance_class="MONTHLY", obligation="PAYE", destination="INLAND_REVENUE")
    _rejects(engine, metadata, t, **dict(row, period_end=date(2026, 9, 30)))
    _rejects(engine, metadata, t, **dict(row, obligation="PAYROLL_TAX"))
    _insert(engine, metadata, t, **row)
    _rejects(engine, metadata, t, **row)
    _insert(engine, metadata, t, **dict(row, destination="COMPLYING_FUND", fund_ref="FUND-7"))
    lines = "payroll_nz_remittance_lines"
    line = dict(organization_id=1, remittance_id=1, payslip_item_id=5, amount=10, source="RUN")
    _rejects(engine, metadata, lines, **dict(line, source="CORRECTION"))                  # needs correction_id
    _insert(engine, metadata, lines, **line)
    _rejects(engine, metadata, lines, **line)
    _rejects(engine, metadata, "payroll_nz_settlements", organization_id=1, remittance_id=1,
             paid_on=date(2026, 11, 18), amount=0, payment_reference="IR-1")


def test_minimum_wage_fail_is_never_an_exception_row(model_engine):
    engine, metadata = model_engine
    t = "payroll_nz_run_exceptions"
    row = dict(organization_id=1, employee_id=1, run_id=1, payslip_item_id=2, code="NZ_CS_SHORTFALL",
               run_fingerprint="f" * 64)
    _rejects(engine, metadata, t, **dict(row, code="NZ_MIN_WAGE_FAIL"))
    _insert(engine, metadata, t, **row)
    _rejects(engine, metadata, t, **row)
    _insert(engine, metadata, t, **dict(row, status="REJECTED"))
