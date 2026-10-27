"""South Africa foundation migration 447f57564983 (ZP-ZA-ENG-001 Phase 2).

Proves, without a PostgreSQL server:
  * the row-level-security policy the revision applies to each new table is
    the one d7f9b1c3e5a6's classify() derives from the model schema (the
    br_employer_m2 pattern) — TENANT for employer registrations / SARS
    artefacts, WORKER/"org" for directives / the ETI ledger;
  * the tables the migration creates have exactly the model's columns, and
    every za_* column the models add to shared tables is added by it;
  * it is additive and idempotent: replaying it over the full model schema
    is a no-op, and downgrade removes only its own objects.
"ZA" is South Africa ("SA" is Saudi Arabia).
"""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.pool import StaticPool

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"
REVISION = "447f57564983"

TENANT = ("payroll_za_employer_registrations", "payroll_za_sars_artifacts")
WORKER_ORG = ("payroll_za_tax_directives", "payroll_za_eti_ledger")
NEW_TABLES = TENANT + WORKER_ORG
# Phase 8 (c15d5b87d6f5): SARS payments + approved reconciliation variances, both TENANT.
P8_REVISION = "c15d5b87d6f5"
P8_TABLES = ("payroll_za_sars_payments", "payroll_za_reconciliation_variances")


def _load(prefix):
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


# ── row-level security ──────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def classified():
    metadata = _metadata()
    rls = _load("d7f9b1c3e5a6")
    cols, fks = {}, {}
    for name, table in metadata.tables.items():
        cols[name] = {c.name for c in table.columns}
        fks[name] = {fk.column.table.name for fk in table.foreign_keys}
    rls._schema = lambda bind: (cols, fks, set(metadata.tables))
    worker, tenant = rls.classify(None)
    return rls, worker, set(tenant)


class _CaptureBind:
    class dialect:
        name = "postgresql"

    def __init__(self):
        self.sql = []

    def execute(self, clause, *a, **k):
        self.sql.append(" ".join(str(clause).split()))


def _policies(statements):
    out = {}
    for s in statements:
        if s.startswith("CREATE POLICY"):
            table = s.split(' ON "', 1)[1].split('"', 1)[0]
            out[table] = s.split(" USING ", 1)[1].split(" WITH CHECK ", 1)[0]
    return out


def test_classify_agrees_with_the_policies_the_revision_applies(classified):
    _rls, worker, tenant = classified
    for table in TENANT:
        assert table in tenant and table not in worker, table
    for table in WORKER_ORG:
        assert worker.get(table) == "org", table


def test_every_south_africa_table_has_a_policy_source(classified):
    _rls, worker, tenant = classified
    za = {t for t in set(worker) | tenant if t.startswith("payroll_za_")}
    assert za == set(NEW_TABLES) | set(P8_TABLES)


def test_revision_emits_the_derived_policy(classified):
    rls = classified[0]
    bind = _CaptureBind()
    _load(REVISION)._rls_for_new_tables(bind)
    want = {t: " ".join(rls._TENANT_PREDICATE.split()) for t in TENANT}
    want.update({t: " ".join(rls._worker_predicate("org").split()) for t in WORKER_ORG})
    assert _policies(bind.sql) == want
    for table in NEW_TABLES:
        assert f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY' in bind.sql
        assert f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY' in bind.sql


# ── migration ↔ model contract (SQLite) ─────────────────────────────────────
@pytest.fixture()
def model_engine():
    metadata = _metadata()
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                              poolclass=StaticPool)
    metadata.create_all(engine)
    yield engine, metadata
    engine.dispose()


def _run(engine, fn_name, revision=REVISION):
    module = _load(revision)
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            getattr(module, fn_name)()


def _cols(engine, table):
    return {c["name"] for c in sa.inspect(engine).get_columns(table)}


def test_new_tables_match_the_models_exactly(model_engine):
    engine, metadata = model_engine
    with engine.begin() as conn:
        for table in NEW_TABLES:
            conn.execute(sa.text(f'DROP TABLE "{table}"'))
    _run(engine, "upgrade")
    for table in NEW_TABLES:
        assert _cols(engine, table) == {c.name for c in metadata.tables[table].columns}, table


def test_shared_table_columns_match_the_models(model_engine):
    _engine, metadata = model_engine
    module = _load(REVISION)
    profile_model = {c.name for c in metadata.tables["payroll_employee_statutory_profiles"].columns
                     if c.name.startswith("za_")}
    assert profile_model == {name for name, _type in module._PROFILE_COLUMNS}
    assert {c.name for c in metadata.tables["payslip_items"].columns if c.name.startswith("za_")} == \
        {"za_calculation_snapshot"}
    assert {c.name for c in metadata.tables["payroll_runs"].columns if c.name.startswith("za_")} == \
        {"za_approval_fingerprint"}


def test_replay_over_the_full_model_schema_is_a_no_op(model_engine):
    engine, _metadata_ = model_engine
    before = {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()}
    _run(engine, "upgrade")
    _run(engine, "upgrade")
    assert {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()} == before


def test_downgrade_removes_only_its_own_objects(model_engine):
    engine, _metadata_ = model_engine
    tables_before = set(sa.inspect(engine).get_table_names())
    _run(engine, "downgrade")
    tables_after = set(sa.inspect(engine).get_table_names())
    assert tables_before - tables_after == set(NEW_TABLES)
    assert not any(c.startswith("za_") for c in _cols(engine, "payroll_employee_statutory_profiles"))
    assert "za_calculation_snapshot" not in _cols(engine, "payslip_items")
    assert "za_approval_fingerprint" not in _cols(engine, "payroll_runs")
    assert "br_cbo_code" in _cols(engine, "payroll_employee_statutory_profiles")   # neighbours untouched


def test_deploy_drift_filter_explains_every_za_object():
    """scripts/drift_pending_filter reads migration sources as TEXT for the
    deploy self-heal: every ZA table and column must be a literal it can see,
    on the right table, or a real deploy refuses them as unexplained drift."""
    import os

    from scripts.drift_pending_filter import pending_objects

    module = _load(REVISION)
    here = os.getcwd()
    os.chdir(VERSIONS.parents[1])
    try:
        tables, columns = pending_objects("c7d2e9a4f1b6")
    finally:
        os.chdir(here)
    assert tables == set(NEW_TABLES) | set(P8_TABLES)
    assert columns["payroll_employee_statutory_profiles"] == {name for name, _t in module._PROFILE_COLUMNS}
    assert columns["payslip_items"] == {"za_calculation_snapshot"}
    assert columns["payroll_runs"] == {"za_approval_fingerprint"}


def test_revision_is_a_single_child_of_the_previous_head():
    module = _load(REVISION)
    assert (module.revision, module.down_revision) == (REVISION, "c7d2e9a4f1b6")


# ── Phase 8: c15d5b87d6f5 (SARS payments, reconciliation variances) ─────────
def test_p8_tables_are_tenant_and_the_revision_emits_the_tenant_policy(classified):
    rls, worker, tenant = classified
    for table in P8_TABLES:
        assert table in tenant and table not in worker, table
    bind = _CaptureBind()
    _load(P8_REVISION)._rls_for_new_tables(bind)
    assert _policies(bind.sql) == {t: " ".join(rls._TENANT_PREDICATE.split()) for t in P8_TABLES}
    for table in P8_TABLES:
        assert f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY' in bind.sql


def test_p8_tables_match_the_models_replay_and_downgrade(model_engine):
    engine, metadata = model_engine
    with engine.begin() as conn:
        for table in P8_TABLES:
            conn.execute(sa.text(f'DROP TABLE "{table}"'))
    _run(engine, "upgrade", P8_REVISION)
    for table in P8_TABLES:
        assert _cols(engine, table) == {c.name for c in metadata.tables[table].columns}, table
    before = set(sa.inspect(engine).get_table_names())
    _run(engine, "upgrade", P8_REVISION)                                  # replay: no-op
    assert set(sa.inspect(engine).get_table_names()) == before
    _run(engine, "downgrade", P8_REVISION)
    assert before - set(sa.inspect(engine).get_table_names()) == set(P8_TABLES)


def test_p8_revision_is_the_single_child_of_the_za_foundation():
    module = _load(P8_REVISION)
    assert (module.revision, module.down_revision) == (P8_REVISION, REVISION)
