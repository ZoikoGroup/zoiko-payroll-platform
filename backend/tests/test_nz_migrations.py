"""New Zealand foundation migration 0e697c2388bf (ZP-NZ-ENG-001 Phase 2).

Proves, without a PostgreSQL server:
  * the row-level-security policy the revision applies to each new table is
    the one d7f9b1c3e5a6's classify() derives from the model schema — TENANT
    for employer profiles, WORKER/"org" for the seven employee tables;
  * the tables the migration creates have exactly the model's columns, and the
    three shared columns exist on the models and are added literally;
  * it is additive and idempotent: replaying it over the full model schema is
    a no-op, and downgrade removes only its own objects;
  * the deploy drift filter explains every New Zealand object;
  * the vault, employer, tax-profile, KiwiSaver, notice, work-pattern and
    ledger rules are enforced by the database.
"""
import importlib.util
from datetime import date, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.pool import StaticPool

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"
REVISION = "0e697c2388bf"
PARENT = "b8bd939fffca"

TENANT = ("payroll_nz_employer_profiles",)
WORKER = (
    "payroll_nz_ird_vault",
    "payroll_nz_ird_access_events",
    "payroll_nz_employee_tax_profiles",
    "payroll_nz_kiwisaver_elections",
    "payroll_nz_authority_deductions",
    "payroll_nz_work_pattern_versions",
    "payroll_nz_accumulator_entries",
)
NEW_TABLES = TENANT + WORKER
SHARED = {"payslip_items": {"nz_calculation_snapshot"},
          "payroll_runs": {"nz_approval_fingerprint", "nz_payment_kind"}}


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


# -- row-level security -----------------------------------------------------
def test_classify_agrees_with_the_policies_the_revision_applies(classified):
    _rls, worker, tenant = classified
    for table in TENANT:
        assert table in tenant and table not in worker, table
    for table in WORKER:
        assert worker.get(table) == "org" and table not in tenant, table


def test_revision_emits_the_derived_policy(classified):
    rls = classified[0]
    bind = _CaptureBind()
    _load()._rls_for_new_tables(bind)
    want = {t: " ".join(rls._TENANT_PREDICATE.split()) for t in TENANT}
    want.update({t: " ".join(rls._worker_predicate("org").split()) for t in WORKER})
    assert _policies(bind.sql) == want
    for table in NEW_TABLES:
        assert f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY' in bind.sql
        assert f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY' in bind.sql


# -- migration <-> model contract (SQLite) ----------------------------------
@pytest.fixture()
def model_engine():
    metadata = _metadata()
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                              poolclass=StaticPool)
    metadata.create_all(engine)
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


def test_new_tables_match_the_models_exactly(model_engine):
    engine, metadata = model_engine
    model_indexes = {t: _indexes(engine, t) for t in NEW_TABLES}
    with engine.begin() as conn:
        for table in _load()._TABLES:
            conn.execute(sa.text(f'DROP TABLE "{table}"'))
    _run(engine, "upgrade")
    later = {"payroll_nz_employer_profiles": {"nz_journal_accounts"}}   # added by P8 (dd8a60634320)
    for table in NEW_TABLES:
        assert _cols(engine, table) == {c.name for c in metadata.tables[table].columns} - later.get(table, set()),             table
        assert model_indexes[table] <= _indexes(engine, table), table


def test_shared_columns_exist_on_the_models_and_are_added_literally():
    metadata = _metadata()
    for table, columns in SHARED.items():
        assert columns <= {c.name for c in metadata.tables[table].columns}, table
    text = next(VERSIONS.glob(f"{REVISION}_*.py")).read_text(encoding="utf-8")
    assert 'op.add_column("payslip_items", sa.Column("nz_calculation_snapshot"' in text
    assert 'op.add_column("payroll_runs", sa.Column("nz_approval_fingerprint"' in text
    assert 'op.add_column("payroll_runs", sa.Column("nz_payment_kind"' in text


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
    for table, columns in SHARED.items():
        assert not columns & _cols(engine, table)
    assert "jp_calculation_snapshot" in _cols(engine, "payslip_items")     # neighbours untouched
    assert {"jp_approval_fingerprint", "jp_payment_kind"} <= _cols(engine, "payroll_runs")
    _run(engine, "upgrade")
    assert set(NEW_TABLES) <= set(sa.inspect(engine).get_table_names())
    for table, columns in SHARED.items():
        assert columns <= _cols(engine, table)


def test_deploy_drift_filter_explains_every_nz_object():
    import os

    from scripts.drift_pending_filter import pending_objects

    here = os.getcwd()
    os.chdir(VERSIONS.parents[1])
    try:
        tables, columns = pending_objects(PARENT)
    finally:
        os.chdir(here)
    # P5 (ac08988ecd3a) and P6 (c6ea8c6c35ce) are pending on the same chain.
    assert tables - set(NEW_TABLES) == {"payroll_nz_employments", "payroll_nz_public_holiday_decisions",
                                        "payroll_nz_leave_entitlements", "payroll_nz_gross_earnings_ledger",
                                        "payroll_nz_leave_events", "payroll_nz_final_pay_cases",
                                        "payroll_nz_leave_pay_calculations", "payroll_nz_cash_up_requests",
                                        "payroll_nz_corrections", "google_pending", "payroll_nz_filings",
                                        "payroll_nz_remittances", "payroll_nz_remittance_lines",
                                        "payroll_nz_settlements", "payroll_nz_run_exceptions",
                                        "payroll_nz_parallel_imports", "payroll_nz_parallel_differences",
                                        # Poland P2 (1ee3bbde33bb) on the same chain.
                                        "payroll_pl_identifier_vault", "payroll_pl_identifier_access_events",
                                        "payroll_pl_employer_registrations", "payroll_pl_worker_profiles",
                                        "payroll_pl_declarations", "payroll_pl_ppk_participations",
                                        "payroll_pl_accumulator_entries",
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
                                        "payroll_my_clearance_hold_lines"}  # + Malaysia P7 (5f314f975ac3)
    assert set(NEW_TABLES) <= tables
    for table, names in SHARED.items():
        assert names <= columns[table], table
    assert columns["users"] == {"auth_provider", "google_id", "avatar_url"}


def test_revision_is_a_single_child_of_the_previous_head():
    module = _load()
    assert (module.revision, module.down_revision) == (REVISION, PARENT)


def test_create_table_names_are_literal_in_the_migration():
    text = next(VERSIONS.glob(f"{REVISION}_*.py")).read_text(encoding="utf-8")
    for table in NEW_TABLES:
        assert f'op.create_table(\n            "{table}"' in text, table


def test_migration_is_listed_in_the_manifest():
    manifest = (VERSIONS.parent / "MIGRATIONS_MANIFEST.txt").read_text(encoding="utf-8")
    assert f"0e697c2388bf_nz_foundation.py|{REVISION}|{PARENT}|" in manifest


def test_no_statutory_number_is_a_check_constraint():
    """Spec production safety rule: CHECKs hold enumerations and date order
    only — never a rate, threshold or wage floor."""
    import re

    text = next(VERSIONS.glob(f"{REVISION}_*.py")).read_text(encoding="utf-8")
    checks = re.findall(r'CheckConstraint\((.*?)name=', text, re.S)
    for body in checks:
        assert not re.search(r"\d+\.\d+|\b(?:15600|156641|24128|23\.95|500000)\b", body), body


# -- vault rules ------------------------------------------------------------
_VAULT = dict(organization_id=1, employee_id=1, subject_type="EMPLOYEE", ciphertext="ciphertext",
              key_version=1, fingerprint="f" * 64, collected_at=datetime(2026, 4, 1), status="ACTIVE")


def _insert(engine, metadata, table, **values):
    with engine.begin() as conn:
        conn.execute(metadata.tables[table].insert().values(**values))


def _rejects(engine, metadata, table, **values):
    with pytest.raises(sa.exc.IntegrityError):
        _insert(engine, metadata, table, **values)


def test_the_vault_has_no_plaintext_like_column():
    names = {c.name.lower() for c in _metadata().tables["payroll_nz_ird_vault"].columns}
    for forbidden in ("ird_number", "number", "plaintext", "last3", "last_three", "last4", "digits"):
        assert forbidden not in names


def test_the_vault_requires_ciphertext_unless_deleted(model_engine):
    engine, metadata = model_engine
    _rejects(engine, metadata, "payroll_nz_ird_vault", **dict(_VAULT, ciphertext=None))
    _insert(engine, metadata, "payroll_nz_ird_vault", **_VAULT)


def test_the_vault_subject_matches_its_employee(model_engine):
    engine, metadata = model_engine
    _rejects(engine, metadata, "payroll_nz_ird_vault", **dict(_VAULT, employee_id=None))
    _rejects(engine, metadata, "payroll_nz_ird_vault", **dict(_VAULT, subject_type="EMPLOYER"))
    _insert(engine, metadata, "payroll_nz_ird_vault", **dict(_VAULT, subject_type="EMPLOYER", employee_id=None))


def test_the_vault_allows_one_active_row_per_employee_and_no_duplicate_number(model_engine):
    engine, metadata = model_engine
    _insert(engine, metadata, "payroll_nz_ird_vault", **_VAULT)
    _rejects(engine, metadata, "payroll_nz_ird_vault", **dict(_VAULT, fingerprint="e" * 64))
    _rejects(engine, metadata, "payroll_nz_ird_vault", **dict(_VAULT, employee_id=2))      # same number
    _insert(engine, metadata, "payroll_nz_ird_vault", **dict(_VAULT, employee_id=2, fingerprint="e" * 64))
    _insert(engine, metadata, "payroll_nz_ird_vault", **dict(_VAULT, status="DELETED"))   # history kept


# -- employer profile rules -------------------------------------------------
def _employer(**overrides):
    values = dict(organization_id=1, effective_from=date(2026, 4, 1), legal_name="Kiwi Test Ltd",
                  filing_method="PAYDAY_GATEWAY", remittance_class="MONTHLY", status="ACTIVE")
    values.update(overrides)
    return values


def test_only_one_active_employer_profile_per_legal_employer(model_engine):
    engine, metadata = model_engine
    _insert(engine, metadata, "payroll_nz_employer_profiles", **_employer())
    _rejects(engine, metadata, "payroll_nz_employer_profiles", **_employer())
    _insert(engine, metadata, "payroll_nz_employer_profiles", **_employer(status="SUPERSEDED"))


def test_employer_profile_rules(model_engine):
    engine, metadata = model_engine
    _rejects(engine, metadata, "payroll_nz_employer_profiles", **_employer(filing_method="EMAIL"))
    _rejects(engine, metadata, "payroll_nz_employer_profiles", **_employer(remittance_class="WEEKLY"))
    _rejects(engine, metadata, "payroll_nz_employer_profiles", **_employer(timezone="Australia/Sydney"))
    _rejects(engine, metadata, "payroll_nz_employer_profiles", **_employer(connected_business_group_ref="G1"))
    _rejects(engine, metadata, "payroll_nz_employer_profiles",
             **_employer(effective_from=date(2026, 4, 2), effective_to=date(2026, 4, 1)))
    _insert(engine, metadata, "payroll_nz_employer_profiles",
            **_employer(connected_business_group_ref="G1", connected_business_evidence_ref="doc-1"))


# -- tax profile rules ------------------------------------------------------
def _profile(**overrides):
    values = dict(organization_id=1, employee_id=1, effective_from=date(2026, 4, 1), ird_number_state="PENDING",
                  tax_code="M", tax_code_source="IR330_DECLARATION", status="ACTIVE")
    values.update(overrides)
    return values


def test_tax_profile_rules(model_engine):
    engine, metadata = model_engine
    table = "payroll_nz_employee_tax_profiles"
    _rejects(engine, metadata, table, **_profile(tax_code="CAE"))                 # refused code
    _rejects(engine, metadata, table, **_profile(tax_code="XYZ"))                 # never a "closest" code
    _rejects(engine, metadata, table, **_profile(ird_number_state="VALID"))       # VALID needs the vault
    _rejects(engine, metadata, table, **_profile(tax_code="STC"))                 # STC needs a certificate
    _rejects(engine, metadata, table, **_profile(min_wage_category="TRAINING"))   # evidence required
    _rejects(engine, metadata, table, **_profile(sl_certificate_type="SPECIAL_DEDUCTION_RATE",
                                                 sl_certificate_ref="c", sl_certificate_valid_from=date(2026, 4, 1)))
    _insert(engine, metadata, table, **_profile(tax_code="STC", tailored_certificate_ref="cert",
                                               tailored_rate_pct=21, tailored_valid_from=date(2026, 4, 1)))
    _insert(engine, metadata, table, **_profile(tax_code="ME SL", min_wage_category="ADULT"))


# -- KiwiSaver rules --------------------------------------------------------
def _ks(**overrides):
    values = dict(organization_id=1, employee_id=1, effective_from=date(2026, 4, 1),
                  membership_state="CONTRIBUTING", status="ACTIVE")
    values.update(overrides)
    return values


def test_kiwisaver_states_need_evidence(model_engine):
    engine, metadata = model_engine
    table = "payroll_nz_kiwisaver_elections"
    _rejects(engine, metadata, table, **_ks(membership_state="SAVINGS_SUSPENSION"))         # NZ-009
    _rejects(engine, metadata, table, **_ks(membership_state="OPTED_OUT"))
    _rejects(engine, metadata, table, **_ks(reduction_ref="IRD-1"))                          # no dates
    _rejects(engine, metadata, table, **_ks(settlement_destination="COMPLYING_FUND"))
    _insert(engine, metadata, table, **_ks(membership_state="SAVINGS_SUSPENSION", suspension_ref="IRD-2",
                                          suspension_from=date(2026, 5, 1)))
    _insert(engine, metadata, table, **_ks(employee_rate_pct=3, reduction_ref="IRD-1",
                                          reduction_from=date(2026, 4, 1), reduction_to=date(2027, 3, 31)))


# -- authority notices ------------------------------------------------------
def _notice(version, **overrides):
    values = dict(organization_id=1, employee_id=1, effective_from=date(2026, 4, 1),
                  deduction_type="CHILD_SUPPORT", notice_id="CS-001", issuer="INLAND_REVENUE",
                  received_at=datetime(2026, 3, 20), amount_per_payday=150,
                  protected_earnings_policy="IRD_PROTECTED_NET", file_hash="a" * 64, version=version,
                  status="IMPORTED")
    values.update(overrides)
    return values


def test_a_changed_notice_is_a_new_version_and_a_duplicate_is_rejected(model_engine):
    engine, metadata = model_engine
    table = "payroll_nz_authority_deductions"
    _insert(engine, metadata, table, **_notice(1))
    _insert(engine, metadata, table, **_notice(2))
    _rejects(engine, metadata, table, **_notice(2))
    _rejects(engine, metadata, table, **_notice(3, amount_per_payday=None))
    _rejects(engine, metadata, table, **_notice(3, protected_earnings_policy="COURT_SPECIFIED"))


# -- work pattern -----------------------------------------------------------
def test_work_pattern_shapes(model_engine):
    engine, metadata = model_engine
    table = "payroll_nz_work_pattern_versions"
    base = dict(organization_id=1, employee_id=1, effective_from=date(2026, 4, 1), hours_source="CONTRACT")
    _rejects(engine, metadata, table, **dict(base, pattern_type="FIXED"))
    _rejects(engine, metadata, table, **dict(base, pattern_type="ROSTERED", roster_cycle_weeks=2))
    _insert(engine, metadata, table, **dict(base, pattern_type="FIXED", weekly_schedule={"MON": 8}))
    _insert(engine, metadata, table, **dict(base, pattern_type="VARIABLE", hours_source="TIMESHEET"))


# -- accumulator ledger -----------------------------------------------------
def _entry(**overrides):
    values = dict(organization_id=1, employee_id=1, tax_year="2026-27", obligation="ACC_LIABLE_EARNINGS",
                  pay_date=date(2026, 4, 30), amount=5000, entry_kind="RUN", payslip_item_id=None)
    values.update(overrides)
    return values


def test_a_payslip_posts_each_obligation_once(model_engine):
    engine, metadata = model_engine
    table = "payroll_nz_accumulator_entries"
    with engine.begin() as conn:
        conn.execute(sa.text("PRAGMA foreign_keys=OFF"))
    _rejects(engine, metadata, table, **_entry())                                   # RUN needs a payslip
    _insert(engine, metadata, table, **_entry(payslip_item_id=10))
    _rejects(engine, metadata, table, **_entry(payslip_item_id=10))
    _insert(engine, metadata, table, **_entry(payslip_item_id=10, obligation="PAYE"))


def test_an_opening_balance_needs_evidence_and_a_second_approver(model_engine):
    engine, metadata = model_engine
    table = "payroll_nz_accumulator_entries"
    _rejects(engine, metadata, table, **_entry(entry_kind="OPENING_BALANCE"))
    _rejects(engine, metadata, table, **_entry(entry_kind="OPENING_BALANCE", evidence_ref="incumbent-ytd.pdf"))
    with engine.begin() as conn:
        conn.execute(sa.text("PRAGMA foreign_keys=OFF"))
    _insert(engine, metadata, table, **_entry(entry_kind="OPENING_BALANCE", evidence_ref="incumbent-ytd.pdf",
                                              approved_by_id=7))
