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
# Phase 9 (3880223bfaa0): approved result overrides (WORKER "org") + nullable columns.
P9_REVISION = "3880223bfaa0"
P9_TABLES = ("payroll_za_payroll_overrides",)
# Phase 10 (67c8d7454716): G6 parallel cycles - imports TENANT, differences WORKER "org".
P10_REVISION = "67c8d7454716"
P10_TENANT = ("payroll_za_parallel_imports",)
P10_WORKER = ("payroll_za_parallel_differences",)
P10_TABLES = P10_TENANT + P10_WORKER
P9_COLUMNS = {"payroll_court_ordered_deductions": {"za_authority_type", "za_evidence_ref"},
              "payroll_za_employer_registrations": {"za_journal_accounts"}}
# Japan foundation (f686d5128f8a) is also pending from c7d2e9a4f1b6.
JP_TABLES = {"payroll_jp_employer_registrations", "payroll_jp_my_number_vault",
             "payroll_jp_my_number_access_events", "payroll_jp_worker_tax_profiles",
             "payroll_jp_social_insurance_enrollments", "payroll_jp_social_insurance_events",
             "payroll_jp_employment_insurance_profiles", "payroll_jp_resident_tax_assessments",
             # Japan P6 (a7c4e9d1b2f8, a1a748b50902).
             "payroll_jp_work_conditions", "payroll_jp_attendance_approvals",
             # Japan P8 (41a1fafbbfdc).
             "payroll_jp_run_exceptions", "payroll_jp_obligations",
             "payroll_jp_yea_declarations", "payroll_jp_yea_cases",
             # Japan P9 (b8bd939fffca).
             "payroll_jp_parallel_imports", "payroll_jp_parallel_differences"}
# New Zealand foundation (0e697c2388bf) is pending on top of Japan P9.
NZ_TABLES = {"payroll_nz_employer_profiles", "payroll_nz_ird_vault", "payroll_nz_ird_access_events",
             "payroll_nz_employee_tax_profiles", "payroll_nz_kiwisaver_elections",
             "payroll_nz_authority_deductions", "payroll_nz_work_pattern_versions",
             "payroll_nz_accumulator_entries",
             # New Zealand P8 (dd8a60634320).
             "payroll_nz_filings", "payroll_nz_remittances", "payroll_nz_remittance_lines",
             "payroll_nz_settlements", "payroll_nz_run_exceptions",
             # New Zealand P9 (a8cde2482ef0).
             "payroll_nz_parallel_imports", "payroll_nz_parallel_differences",
             # New Zealand P6 (c6ea8c6c35ce).
             "payroll_nz_final_pay_cases", "payroll_nz_leave_pay_calculations",
             "payroll_nz_cash_up_requests", "payroll_nz_corrections",
             # New Zealand P5 (ac08988ecd3a).
             "payroll_nz_employments", "payroll_nz_public_holiday_decisions", "payroll_nz_leave_entitlements",
             "payroll_nz_gross_earnings_ledger", "payroll_nz_leave_events",
             # Poland P2 (1ee3bbde33bb) is pending on top of New Zealand P9.
             "payroll_pl_identifier_vault", "payroll_pl_identifier_access_events",
             "payroll_pl_employer_registrations", "payroll_pl_worker_profiles", "payroll_pl_declarations",
             "payroll_pl_ppk_participations", "payroll_pl_accumulator_entries",
                                        "payroll_pl_incapacity_episodes",  # + Poland P6 (e11c2c36df17)
                                        "payroll_pl_filings", "payroll_pl_settlements",
                                        "payroll_pl_reconciliation_variances",  # + Poland P8 (e75b9219e1f8)
                                        "payroll_pl_parallel_imports",
                                        "payroll_pl_parallel_differences",  # + Poland P9 (e7ec6c1933b4)
                                        "payroll_my_identifier_vault", "payroll_my_identifier_access_events",
                                        "payroll_my_employer_registrations", "payroll_my_worker_profiles",
                                        "payroll_my_work_assignments", "payroll_my_tax_declarations",
                                        "payroll_my_accumulator_entries",  # + Malaysia P2 (13574b996ccf)
                                        "payroll_my_employer_events", "payroll_my_clearance_holds",
                                        "payroll_my_clearance_hold_lines",  # + Malaysia P7 (5f314f975ac3)
                                        "payroll_my_filings", "payroll_my_settlements", "payroll_my_reconciliation_variances",  # + Malaysia P9 (efdc07f97eb5)
                                        "payroll_my_parallel_imports", "payroll_my_parallel_differences",  # + Malaysia P10 (f793f6074257)
                                        "payroll_be_identifier_vault", "payroll_be_identifier_access_events",
                                        "payroll_be_employer_registrations", "payroll_be_establishment_units",
                                        "payroll_be_worker_profiles", "payroll_be_work_schedules",
                                        "payroll_be_employment_classifications", "payroll_be_declarations",
                                        "payroll_be_accumulator_entries",  # + Belgium P2 (1d76678ef1a1)
                                        "payroll_be_absence_episodes", "payroll_be_holiday_certificates", "payroll_be_payment_batches", "payroll_be_payment_items", "payroll_be_component_mappings", "payroll_be_filings", "payroll_be_obligations", "payroll_be_reconciliation_variances", "payroll_be_parallel_imports", "payroll_be_parallel_differences", "payroll_payslip_templates", "payroll_payslip_template_versions", "payroll_payslip_template_assignments"}  # + Belgium Block B (2943a0490b5b) + Block C (8a1f5ef9fa5d)


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
    assert za == set(NEW_TABLES) | set(P8_TABLES) | set(P9_TABLES) | set(P10_TABLES)


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
        later = P9_COLUMNS.get(table, set())                    # added by Phase 9's own revision
        assert _cols(engine, table) == {c.name for c in metadata.tables[table].columns} - later, table


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
    # Mexico m20 (d3f8b2a6c1e9) also grows from c7d2e9a4f1b6 (joined by merge 92c67cab49fc).
    mexico_m20 = {"payroll_mx_decisions", "payroll_mx_parallel_imports", "payroll_mx_parallel_differences"}
    # The country entitlement ledger (b4d6f8a0c2e3) and Japan Phase 2 are pending from here too.
    google_tables = {"google_pending"}
    google_columns = {"auth_provider", "google_id", "avatar_url"}
    assert tables == (set(NEW_TABLES) | set(P8_TABLES) | set(P9_TABLES) | set(P10_TABLES)
                      | mexico_m20 | {"organization_jurisdictions"} | JP_TABLES | NZ_TABLES | google_tables)
    assert columns["users"] == google_columns
    for table, names in P9_COLUMNS.items():
        assert columns[table] == names, table
    # Mexico m21 (efc56f3235e2) adds three columns on the same table after this chain.
    assert columns["payroll_employee_statutory_profiles"] - {"mx_union_member", "mx_sdi_operator_entered",
                                                             "mx_sdi_evidence_ref"} == {name for name, _t in module._PROFILE_COLUMNS}
    assert columns["payslip_items"] == {"za_calculation_snapshot", "jp_calculation_snapshot",
                                        "nz_calculation_snapshot", "nz_correction_of_id", "pl_calculation_snapshot",
                                        "be_calculation_snapshot", "my_calculation_snapshot", "template_version_id"}  # + Belgium P2
    assert columns["payroll_runs"] == {"za_approval_fingerprint", "jp_approval_fingerprint",
                                       "jp_payment_kind", "nz_approval_fingerprint", "nz_payment_kind",
                                       "nz_run_options", "pl_approval_fingerprint", "my_approval_fingerprint", "be_approval_fingerprint"}


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


# ── Phase 9: 3880223bfaa0 (overrides, ZA deduction authority, journal accounts) ──
def test_p9_overrides_table_is_worker_org_and_the_revision_emits_that_policy(classified):
    rls, worker, tenant = classified
    for table in P9_TABLES:
        assert worker.get(table) == "org" and table not in tenant, table
    bind = _CaptureBind()
    _load(P9_REVISION)._rls_for_new_tables(bind)
    assert _policies(bind.sql) == {t: " ".join(rls._worker_predicate("org").split()) for t in P9_TABLES}
    for table in P9_TABLES:
        assert f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY' in bind.sql


def test_p9_matches_the_models_replays_and_downgrades(model_engine):
    engine, metadata = model_engine
    with engine.begin() as conn:
        for table in P9_TABLES:
            conn.execute(sa.text(f'DROP TABLE "{table}"'))
    _run(engine, "downgrade", P9_REVISION)                               # drops the shared columns too
    for table, names in P9_COLUMNS.items():
        assert not names & _cols(engine, table), table
    _run(engine, "upgrade", P9_REVISION)
    for table in P9_TABLES:
        assert _cols(engine, table) == {c.name for c in metadata.tables[table].columns}, table
    for table, names in P9_COLUMNS.items():
        assert names <= _cols(engine, table) and names <= {c.name for c in metadata.tables[table].columns}
    before = {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()}
    _run(engine, "upgrade", P9_REVISION)                                  # replay: no-op
    assert {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()} == before
    _run(engine, "downgrade", P9_REVISION)
    assert set(before) - set(sa.inspect(engine).get_table_names()) == set(P9_TABLES)
    assert "court_reference" in _cols(engine, "payroll_court_ordered_deductions")   # neighbours untouched


def test_p9_revision_is_the_single_child_of_the_za_p8_mexico_m20_merge():
    module = _load(P9_REVISION)
    assert (module.revision, module.down_revision) == (P9_REVISION, "92c67cab49fc")
    assert tuple(_load("92c67cab49fc").down_revision) == (P8_REVISION, "d3f8b2a6c1e9")


# ── Phase 10: 67c8d7454716 (G6 parallel payroll cycles) ─────────────────────
def test_p10_tables_get_the_policy_classify_derives(classified):
    rls, worker, tenant = classified
    for table in P10_TENANT:
        assert table in tenant and table not in worker, table
    for table in P10_WORKER:
        assert worker.get(table) == "org" and table not in tenant, table
    bind = _CaptureBind()
    _load(P10_REVISION)._rls_for_new_tables(bind)
    want = {t: " ".join(rls._TENANT_PREDICATE.split()) for t in P10_TENANT}
    want.update({t: " ".join(rls._worker_predicate("org").split()) for t in P10_WORKER})
    assert _policies(bind.sql) == want
    for table in P10_TABLES:
        assert f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY' in bind.sql


def test_p10_matches_the_models_replays_and_downgrades(model_engine):
    engine, metadata = model_engine
    with engine.begin() as conn:
        for table in reversed(P10_TABLES):
            conn.execute(sa.text(f'DROP TABLE "{table}"'))
    _run(engine, "upgrade", P10_REVISION)
    for table in P10_TABLES:
        assert _cols(engine, table) == {c.name for c in metadata.tables[table].columns}, table
    before = {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()}
    _run(engine, "upgrade", P10_REVISION)                                 # replay: no-op
    assert {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()} == before
    _run(engine, "downgrade", P10_REVISION)
    assert set(before) - set(sa.inspect(engine).get_table_names()) == set(P10_TABLES)


def test_p10_revision_is_the_single_child_of_phase_9():
    module = _load(P10_REVISION)
    assert (module.revision, module.down_revision) == (P10_REVISION, P9_REVISION)
