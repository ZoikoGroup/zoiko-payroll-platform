"""New Zealand Holidays Act migration ac08988ecd3a (ZP-NZ-ENG-001 Phase 5).

Proves, without a PostgreSQL server: the WORKER "org" policy derived by
d7f9b1c3e5a6 for every new table; tables equal to the models; additive and
idempotent both ways; the drift filter explains the tables; and the database
rules for employments, entitlements, decisions, the ledger and leave events
(including that a leave event has no reason column, NZ-023).
"""
import importlib.util
import re
from datetime import date, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.pool import StaticPool

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"
REVISION = "ac08988ecd3a"
PARENT = "0e697c2388bf"
NEW_TABLES = ("payroll_nz_employments", "payroll_nz_public_holiday_decisions", "payroll_nz_leave_entitlements",
              "payroll_nz_gross_earnings_ledger", "payroll_nz_leave_events")


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


def test_tables_match_models(model_engine):
    engine, metadata = model_engine
    model_indexes = {t: _indexes(engine, t) for t in NEW_TABLES}
    with engine.begin() as conn:
        for table in _load()._TABLES:
            conn.execute(sa.text(f'DROP TABLE "{table}"'))
    _run(engine, "upgrade")
    later = {"payroll_nz_leave_events": {"leave_pay_calculation_id"}}          # added by P6 (c6ea8c6c35ce)
    for table in NEW_TABLES:
        assert _cols(engine, table) == {c.name for c in metadata.tables[table].columns} - later.get(table, set()), table
        assert model_indexes[table] <= _indexes(engine, table), table


def test_replay_noop(model_engine):
    engine, _m = model_engine
    before = {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()}
    _run(engine, "upgrade")
    _run(engine, "upgrade")
    assert {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()} == before


def test_downgrade_only_own_tables(model_engine):
    engine, _m = model_engine
    before = set(sa.inspect(engine).get_table_names())
    _run(engine, "downgrade")
    assert before - set(sa.inspect(engine).get_table_names()) == set(NEW_TABLES)
    assert "payroll_nz_accumulator_entries" in sa.inspect(engine).get_table_names()     # P2 untouched
    _run(engine, "downgrade")                                                             # idempotent
    _run(engine, "upgrade")
    assert set(NEW_TABLES) <= set(sa.inspect(engine).get_table_names())


def test_drift_filter_explains():
    import os

    from scripts.drift_pending_filter import pending_objects

    here = os.getcwd()
    os.chdir(VERSIONS.parents[1])
    try:
        tables, columns = pending_objects(PARENT)
    finally:
        os.chdir(here)
    # P6 (c6ea8c6c35ce) and P8 (dd8a60634320) are pending on the same chain.
    assert tables == set(NEW_TABLES) | {"payroll_nz_final_pay_cases", "payroll_nz_leave_pay_calculations",
                                        "payroll_nz_cash_up_requests", "payroll_nz_corrections",
                                        "google_pending", "payroll_nz_filings", "payroll_nz_remittances",
                                        "payroll_nz_remittance_lines", "payroll_nz_settlements",
                                        "payroll_nz_run_exceptions"}
    assert columns == {"payslip_items": {"nz_correction_of_id"}, "payroll_runs": {"nz_run_options"},
                       "payroll_nz_leave_events": {"leave_pay_calculation_id"},
                       "users": {"auth_provider", "google_id", "avatar_url"},
                       "payroll_nz_employer_profiles": {"nz_journal_accounts"}}


def test_single_child_of_foundation():
    module = _load()
    assert (module.revision, module.down_revision) == (REVISION, PARENT)
    text = next(VERSIONS.glob(f"{REVISION}_*.py")).read_text(encoding="utf-8")
    for table in NEW_TABLES:
        assert f'op.create_table(\n            "{table}"' in text, table
    assert "lock_timeout" in text


def test_manifest_line():
    manifest = (VERSIONS.parent / "MIGRATIONS_MANIFEST.txt").read_text(encoding="utf-8")
    assert f"ac08988ecd3a_nz_holidays_act.py|{REVISION}|{PARENT}|" in manifest


def test_no_statutory_number_in_checks():
    text = next(VERSIONS.glob(f"{REVISION}_*.py")).read_text(encoding="utf-8")
    for body in re.findall(r'CheckConstraint\((.*?)name=', text, re.S):
        # sign checks (>= 0 / > 0) only; never a weeks / days / months value
        assert not re.search(r"(?<![\w.])(?!0(?![\w.]))\d", body.replace("12_MONTHS", "")), body


# -- database rules -------------------------------------------------------
def _insert(engine, metadata, table, **values):
    with engine.begin() as conn:
        conn.execute(metadata.tables[table].insert().values(**values))


def _rejects(engine, metadata, table, **values):
    with pytest.raises(sa.exc.IntegrityError):
        _insert(engine, metadata, table, **values)


def _employment(**kw):
    values = dict(organization_id=1, employee_id=1, start_date=date(2025, 5, 12), status="DRAFT")
    values.update(kw)
    return values


def test_payg_needs_basis_and_agreement(model_engine):
    engine, metadata = model_engine
    t = "payroll_nz_employments"
    _rejects(engine, metadata, t, **_employment(payg_eligible=True))
    _rejects(engine, metadata, t, **_employment(payg_eligible=True, payg_basis="IRREGULAR_INTERMITTENT"))
    _rejects(engine, metadata, t, **_employment(payg_basis="CASUAL"))
    _insert(engine, metadata, t, **_employment(payg_eligible=True, payg_basis="IRREGULAR_INTERMITTENT",
                                               payg_agreement_ref="agreement.pdf"))


def test_continuous_needs_evidence(model_engine):
    engine, metadata = model_engine
    t = "payroll_nz_employments"
    _rejects(engine, metadata, t, **_employment(continuity_rule="CONTINUOUS"))
    _rejects(engine, metadata, t, **_employment(continuity_rule="CONTINUOUS", evidence_ref="letter.pdf"))
    _insert(engine, metadata, t, **_employment(continuity_rule="CONTINUOUS", evidence_ref="letter.pdf",
                                               prior_employment_id=99))
    _rejects(engine, metadata, t, **_employment(end_date=date(2025, 5, 1)))


def test_one_active_employment(model_engine):
    engine, metadata = model_engine
    t = "payroll_nz_employments"
    _insert(engine, metadata, t, **_employment(status="ACTIVE"))
    _rejects(engine, metadata, t, **_employment(status="ACTIVE"))
    _insert(engine, metadata, t, **_employment(status="ENDED"))


def _entitlement(**kw):
    values = dict(organization_id=1, employee_id=1, employment_id=1, leave_type="ANNUAL",
                  qualifying_date=date(2026, 5, 12), entitlement_date=date(2026, 5, 12), unit="WEEKS",
                  quantity=4, source="HOLIDAYS_ACT_2003", pack_hash="a" * 64)
    values.update(kw)
    return values


def test_entitlement_balance_cannot_go_negative(model_engine):
    engine, metadata = model_engine
    t = "payroll_nz_leave_entitlements"
    _rejects(engine, metadata, t, **_entitlement(taken=5))
    _rejects(engine, metadata, t, **_entitlement(quantity=-1))
    _rejects(engine, metadata, t, **_entitlement(unit="HOURS"))
    _insert(engine, metadata, t, **_entitlement(taken=2, paid_out=2))
    _rejects(engine, metadata, t, **_entitlement())                          # vests once per date


def test_alternative_needs_decision_and_is_unique(model_engine):
    engine, metadata = model_engine
    t = "payroll_nz_leave_entitlements"
    alt = dict(leave_type="ALTERNATIVE", unit="DAYS", quantity=1, source="PUBLIC_HOLIDAY_WORKED")
    _rejects(engine, metadata, t, **_entitlement(**alt))
    _insert(engine, metadata, t, **_entitlement(**alt, source_decision_id=5))
    _rejects(engine, metadata, t, **_entitlement(**alt, source_decision_id=5,
                                                 entitlement_date=date(2026, 6, 1)))
    _insert(engine, metadata, t, **_entitlement(**alt, source_decision_id=6))   # same date, other decision


def _event(**kw):
    values = dict(organization_id=1, employee_id=1, employment_id=1, leave_type="SICK",
                  start_date=date(2026, 8, 3), end_date=date(2026, 8, 3), quantity=1, unit="DAYS")
    values.update(kw)
    return values


def test_family_violence_event_must_be_restricted(model_engine):
    engine, metadata = model_engine
    t = "payroll_nz_leave_events"
    _rejects(engine, metadata, t, **_event(leave_type="FAMILY_VIOLENCE"))
    _insert(engine, metadata, t, **_event(leave_type="FAMILY_VIOLENCE", restricted=True))
    _rejects(engine, metadata, t, **_event(quantity=0))
    _rejects(engine, metadata, t, **_event(end_date=date(2026, 8, 1)))


def test_no_reason_column_on_events():
    names = {c.name.lower() for c in _metadata().tables["payroll_nz_leave_events"].columns}
    for forbidden in ("reason", "notes", "narrative", "description", "relationship", "comment"):
        assert forbidden not in names


def test_ledger_unique_per_payslip_component(model_engine):
    engine, metadata = model_engine
    t = "payroll_nz_gross_earnings_ledger"
    row = dict(organization_id=1, employee_id=1, payslip_item_id=10, pay_date=date(2026, 4, 30),
               period_start=date(2026, 4, 1), period_end=date(2026, 4, 30), component="SALARY", amount=3000,
               included=True, treatment="INCLUDED", reason="HOLIDAY_GROSS:SALARY INCLUDED")
    _insert(engine, metadata, t, **row)
    _rejects(engine, metadata, t, **row)
    _insert(engine, metadata, t, **dict(row, component="OVERTIME"))
    _rejects(engine, metadata, t, **dict(row, component="BONUS", treatment="MAYBE"))


def test_decision_rules(model_engine):
    engine, metadata = model_engine
    t = "payroll_nz_public_holiday_decisions"
    row = dict(organization_id=1, employee_id=1, employment_id=1, holiday_date=date(2026, 12, 25),
               holiday_name="Christmas Day", otherwise_working_day="YES", owd_basis="FIXED_PATTERN")
    _rejects(engine, metadata, t, **dict(row, owd_basis="OPERATOR_DECISION"))           # needs evidence
    _rejects(engine, metadata, t, **dict(row, worked=True))                             # needs a shift
    _rejects(engine, metadata, t, **dict(row, timezone="Australia/Sydney"))
    _insert(engine, metadata, t, **dict(row, worked=True, shift_start=datetime(2026, 12, 24, 22),
                                        shift_end=datetime(2026, 12, 25, 6), status="APPROVED"))
    _rejects(engine, metadata, t, **dict(row, status="APPROVED"))                       # one approved
    _insert(engine, metadata, t, **dict(row, status="SUPERSEDED"))
