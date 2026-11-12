"""Belgium Block B migration 2943a0490b5b be_absence_holiday_payment.

The same contract as the Phase 2 foundation (tests/test_belgium_migrations.py):
RLS as d7f9b1c3e5a6's classify() derives it, new tables exactly the models,
autogenerate no-diff, idempotent replay, upgrade / downgrade / upgrade round
trip removing only its own objects, literal names, manifest entry, single child,
single head, no statutory number in a CHECK — plus every new CHECK and the
decision columns (G-22 pay basis, G-23 contract, G-25 1.60% status) enforced by
the database. SYNTHETIC data only."""
import re
from datetime import date

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.pool import StaticPool

from tests.test_belgium_migrations import (BACKEND, VERSIONS, _CaptureBind, _cols, _indexes, _load, _metadata,
                                           _policies, classified)  # noqa: F401  (pytest fixture)

REVISION = "2943a0490b5b"
PARENT = "1d76678ef1a1"
FILENAME = f"{REVISION}_be_absence_holiday_payment.py"
TENANT = ("payroll_be_payment_batches", "payroll_be_component_mappings")
WORKER = ("payroll_be_absence_episodes", "payroll_be_holiday_certificates", "payroll_be_payment_items")
NEW_TABLES = TENANT + WORKER
# Tables the LATER Block C revision (8a1f5ef9fa5d be_filing_parallel) creates;
# tests/test_belgium_block_c_migration.py covers them.
LATER_REVISION = "8a1f5ef9fa5d"
LATER_TABLES = ("payroll_be_filings", "payroll_be_obligations", "payroll_be_reconciliation_variances",
                "payroll_be_parallel_imports", "payroll_be_parallel_differences")
COLUMNS = {"payroll_be_worker_profiles": {"pay_basis"},
           "payroll_be_employment_classifications": {"contract_type", "contract_start_date", "contract_end_date"},
           "payroll_be_employer_registrations": {"onss_special_160_status", "special_160_evidence_ref"}}


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
def test_new_tables_and_columns_match_the_models_exactly(model_engine):
    engine, metadata = model_engine
    model_indexes = {t: _indexes(engine, t) for t in NEW_TABLES}
    _run(engine, "downgrade")
    for table, columns in COLUMNS.items():
        assert not columns & _cols(engine, table), table
    _run(engine, "upgrade")
    for table in NEW_TABLES:
        assert _cols(engine, table) == {c.name for c in metadata.tables[table].columns}, table
        assert model_indexes[table] <= _indexes(engine, table), table
    for table, columns in COLUMNS.items():
        assert columns <= _cols(engine, table), table


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
    assert {"residency", "worker_category"} <= _cols(engine, "payroll_be_worker_profiles")      # neighbours stay
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
    assert tables == set(NEW_TABLES) | set(LATER_TABLES)
    assert columns == COLUMNS


def test_revision_is_the_single_child_of_its_parent():
    module = _load(REVISION)
    assert (module.revision, module.down_revision) == (REVISION, PARENT)
    children = [p.name for p in VERSIONS.glob("*.py")
                if re.search(rf'down_revision[^\n]*"{PARENT}"', p.read_text(encoding="utf-8"))]
    assert children == [FILENAME]


def test_the_only_child_is_the_block_c_revision():
    """The single-head check moved to tests/test_belgium_block_c_migration.py when
    Block C chained 8a1f5ef9fa5d onto this revision."""
    children = [p.name for p in VERSIONS.glob("*.py")
                if re.search(rf'down_revision[^\n]*"{REVISION}"', p.read_text(encoding="utf-8"))]
    assert children == [f"{LATER_REVISION}_be_filing_parallel.py"]


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


def test_vocabularies_match_models_content_and_migration():
    from app.modules.payroll import models
    from app.modules.payroll.engine.countries import belgium_content as content

    module = _load(REVISION)
    assert module.PAY_BASES == models._BE_PAY_BASES == content.PAY_BASES
    assert module.CONTRACT_TYPES == models._BE_CONTRACT_TYPES == content.CONTRACT_TYPES + ("NOT_SUPPORTED",)
    assert module.SPECIAL_160_STATUSES == models._BE_SPECIAL_160_STATUSES == content.SPECIAL_160_STATUSES
    assert module.ABSENCE_KINDS == models._BE_ABSENCE_KINDS == content.ABSENCE_KINDS
    assert module.COMPONENTS == models._BE_COMPONENTS == content.COMPONENTS
    assert module.NEW_ACCUMULATORS == models._BE_ACCUMULATORS == content.ACCUMULATORS
    assert module.WORKER_CATEGORIES == models._BE_WORKER_CATEGORIES


def test_no_diagnosis_or_medical_column_on_episodes():
    names = {c.name.lower() for c in _metadata().tables["payroll_be_absence_episodes"].columns}
    for forbidden in ("diagnosis", "medical", "illness", "condition", "symptom", "icd"):
        assert not [n for n in names if forbidden in n], forbidden


def test_payment_items_carry_a_token_never_an_account_number():
    names = {c.name.lower() for c in _metadata().tables["payroll_be_payment_items"].columns}
    assert "iban_token" in names and not {"iban", "account_number", "bic"} & names


# -- database rules ---------------------------------------------------------
def _insert(engine, metadata, table, **values):
    with engine.begin() as conn:
        conn.execute(metadata.tables[table].insert().values(**values))


def _rejects(engine, metadata, table, **values):
    with pytest.raises(sa.exc.IntegrityError):
        _insert(engine, metadata, table, **values)


def test_decision_columns_are_checked(model_engine):
    engine, metadata = model_engine
    base_profile = dict(organization_id=1, employee_id=1, effective_from=date(2026, 1, 1), worker_category="EMPLOYEE",
                        status="DRAFT")
    _insert(engine, metadata, "payroll_be_worker_profiles", **base_profile, pay_basis=None)
    _insert(engine, metadata, "payroll_be_worker_profiles", **base_profile, pay_basis="HOURLY")
    _rejects(engine, metadata, "payroll_be_worker_profiles", **base_profile, pay_basis="DAILY")
    line = dict(organization_id=1, employee_id=1, employment_line="MAIN", effective_from=date(2026, 1, 1),
                status="DRAFT")
    _insert(engine, metadata, "payroll_be_employment_classifications", **line, contract_type="FIXED_TERM",
            contract_start_date=date(2026, 1, 1), contract_end_date=date(2026, 6, 30))
    _rejects(engine, metadata, "payroll_be_employment_classifications", **line, contract_type="PERMANENT")
    _rejects(engine, metadata, "payroll_be_employment_classifications", **line, contract_type="INDEFINITE",
             contract_start_date=date(2026, 6, 1), contract_end_date=date(2026, 1, 1))
    employer = dict(organization_id=1, effective_from=date(2026, 1, 1), legal_name="TEST ONLY",
                    enterprise_number="0999999999", status="DRAFT")
    _insert(engine, metadata, "payroll_be_employer_registrations", **employer)
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT onss_special_160_status FROM payroll_be_employer_registrations")
                            ).scalar() == "UNKNOWN"
    _rejects(engine, metadata, "payroll_be_employer_registrations", **employer, onss_special_160_status="MAYBE")


def test_absence_episode_rules(model_engine):
    engine, metadata = model_engine
    t = "payroll_be_absence_episodes"
    base = dict(organization_id=1, employee_id=1, kind="SICKNESS", start_date=date(2026, 3, 2),
                worker_category_at_start="EMPLOYEE", status="DRAFT")
    _insert(engine, metadata, t, **base)
    _rejects(engine, metadata, t, **dict(base, kind="FLU"))
    _rejects(engine, metadata, t, **dict(base, end_date=date(2026, 3, 1)))
    _rejects(engine, metadata, t, **dict(base, status="ACTIVE"))                              # no approver
    _rejects(engine, metadata, t, **dict(base, status="ACTIVE", created_by_id=1, approved_by_id=1))
    _insert(engine, metadata, t, **dict(base, status="ACTIVE", created_by_id=1, approved_by_id=2))
    _rejects(engine, metadata, t, **dict(base, status="CANCELLED"))                          # needs a reason
    _insert(engine, metadata, t, **dict(base, status="CANCELLED", cancelled_reason="entered twice"))


def test_holiday_certificate_rules(model_engine):
    engine, metadata = model_engine
    t = "payroll_be_holiday_certificates"
    base = dict(organization_id=1, employee_id=1, direction="OUT", service_year=2025, status="DRAFT")
    _insert(engine, metadata, t, **base)
    _rejects(engine, metadata, t, **dict(base, direction="SIDEWAYS"))
    _rejects(engine, metadata, t, **dict(base, direction="IN"))                                 # prior employer
    _insert(engine, metadata, t, **dict(base, direction="IN", prior_employer_ref="TEST ONLY employer"))
    _rejects(engine, metadata, t, **dict(base, simple_pay_amount=-1))
    _rejects(engine, metadata, t, **dict(base, status="APPROVED", created_by_id=1, approved_by_id=1))
    _insert(engine, metadata, t, **dict(base, status="APPROVED", created_by_id=1, approved_by_id=2))


def test_payment_batch_and_item_rules(model_engine):
    engine, metadata = model_engine
    batch = dict(organization_id=1, pain001_sha256="a" * 64, message_id="M1", idempotency_key="k1", status="DRAFT")
    _insert(engine, metadata, "payroll_be_payment_batches", **batch)
    _rejects(engine, metadata, "payroll_be_payment_batches",
             **dict(batch, pain001_sha256="b" * 64, idempotency_key="k2", status="APPROVED"))     # no approver
    _rejects(engine, metadata, "payroll_be_payment_batches",
             **dict(batch, pain001_sha256="c" * 64, idempotency_key="k1"))                        # idempotency key
    item = dict(organization_id=1, batch_id=1, iban_token="tok", amount=1, end_to_end_id="E1")
    _insert(engine, metadata, "payroll_be_payment_items", **item)
    _rejects(engine, metadata, "payroll_be_payment_items", **dict(item, amount=0))
    _rejects(engine, metadata, "payroll_be_payment_items", **dict(item, status="LOST"))


def test_component_mapping_rules(model_engine):
    engine, metadata = model_engine
    t = "payroll_be_component_mappings"
    base = dict(organization_id=1, platform_component_source="POLICY_ALLOWANCE", platform_component_key="transport",
                be_component="REIMBURSEMENT", effective_from=date(2026, 1, 1), status="DRAFT")
    _insert(engine, metadata, t, **base)
    _rejects(engine, metadata, t, **dict(base, be_component="TIPS"))
    _rejects(engine, metadata, t, **dict(base, platform_component_source="SPREADSHEET"))
    active = dict(base, status="ACTIVE", created_by_id=1, approved_by_id=2)
    _insert(engine, metadata, t, **active)
    _rejects(engine, metadata, t, **active)                                       # one ACTIVE open per key


def test_the_ledger_accepts_the_block_b_accumulators(model_engine):
    engine, metadata = model_engine
    for i, name in enumerate(("OVERTIME_HOURS", "COMPENSATORY_REST_HOURS", "HOLIDAY_SIMPLE_PAID",
                              "HOLIDAY_DOUBLE_PAID", "ADDITIONAL_HOLIDAY_ADVANCE", "GUARANTEED_SALARY_DAYS")):
        _insert(engine, metadata, "payroll_be_accumulator_entries", organization_id=1, employee_id=1, year=2026,
                accumulator=name, pay_date=date(2026, 3, 31), amount=1, entry_kind="RUN", payslip_item_id=100 + i)
