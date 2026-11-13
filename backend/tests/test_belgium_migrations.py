"""Belgium foundation migration 1d76678ef1a1 (ZP-BE-ENG-001 Phase 2).

Proves on SQLite (and, when ZP_TEST_POSTGRES_URL points at a DISPOSABLE
PostgreSQL, on PostgreSQL too):
  * the row-level-security policy the revision applies to each new table is the
    one d7f9b1c3e5a6's classify() derives from the model schema — TENANT for
    employer registrations and establishment units, WORKER/"org" for the seven
    worker tables;
  * the tables the migration creates have exactly the model's columns and
    indexes, Alembic autogenerate sees no difference, and the two shared
    columns exist on the models and are added literally;
  * it is additive and idempotent: replaying it over the full model schema is a
    no-op, upgrade -> downgrade -> upgrade round-trips, and downgrade removes
    only its own objects;
  * migrations/create_all builds a fresh database containing every new table;
  * the deploy drift filter explains every Belgium object;
  * no statutory number is a CHECK constraint;
  * every vault, employer, unit, profile, schedule, classification,
    declaration and ledger rule (evidence, four-eyes, one-ACTIVE, PRIOR_EMPLOYER
    block, source period, quarter) is enforced by the database.
SYNTHETIC data only."""
import importlib.util
import os
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.pool import StaticPool

BACKEND = Path(__file__).resolve().parents[1]
VERSIONS = BACKEND / "alembic" / "versions"
REVISION = "1d76678ef1a1"
PARENT = "f3a9c1d7e2b4"         # re-chained (merge of origin/main)
FILENAME = f"{REVISION}_be_foundation.py"

TENANT = ("payroll_be_employer_registrations", "payroll_be_establishment_units")
WORKER = (
    "payroll_be_identifier_vault",
    "payroll_be_identifier_access_events",
    "payroll_be_worker_profiles",
    "payroll_be_work_schedules",
    "payroll_be_employment_classifications",
    "payroll_be_declarations",
    "payroll_be_accumulator_entries",
)
NEW_TABLES = TENANT + WORKER
SHARED = {"payslip_items": {"be_calculation_snapshot"}, "payroll_runs": {"be_approval_fingerprint"}}
# Columns a LATER Belgium revision (Block B, 2943a0490b5b be_absence_holiday_payment)
# adds to this revision's tables; tests/test_belgium_block_b_migration.py covers them.
LATER = {"payroll_be_worker_profiles": {"pay_basis"},
         "payroll_be_employment_classifications": {"contract_type", "contract_start_date", "contract_end_date"},
         "payroll_be_employer_registrations": {"onss_special_160_status", "special_160_evidence_ref"}}
LATER_REVISION = "2943a0490b5b"
LATER_TABLES = ("payroll_be_absence_episodes", "payroll_be_holiday_certificates", "payroll_be_payment_batches",
                "payroll_be_payment_items", "payroll_be_component_mappings")
# Tables the Block C revision (8a1f5ef9fa5d be_filing_parallel) creates.
BLOCK_C_TABLES = ("payroll_be_filings", "payroll_be_obligations", "payroll_be_reconciliation_variances",
                  "payroll_be_parallel_imports", "payroll_be_parallel_differences")


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


def _run_later(engine, fn_name):
    module = _load(LATER_REVISION)
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
    for table in NEW_TABLES:
        model_cols = {c.name for c in metadata.tables[table].columns} - LATER.get(table, set())
        assert _cols(engine, table) == model_cols, table
        assert model_indexes[table] <= _indexes(engine, table), table


def test_autogenerate_sees_no_difference_for_belgium(model_engine):
    """Alembic compare_metadata on a database built by the MIGRATION (not the
    models) reports nothing for payroll_be_* or the two shared columns."""
    from alembic.autogenerate import compare_metadata

    engine, metadata = model_engine
    _run(engine, "downgrade")
    _run(engine, "upgrade")
    _run_later(engine, "upgrade")                    # restores the Block B columns on these tables

    def touches_belgium(diff):
        flat = diff if isinstance(diff, tuple) else ()
        text = repr(diff)
        if "payroll_be_" in text:
            return True
        return any(c in text for cols in SHARED.values() for c in cols) and bool(flat or text)

    with engine.connect() as conn:
        diffs = compare_metadata(MigrationContext.configure(conn), metadata)
    flat = []
    for d in diffs:
        flat.extend(d if isinstance(d, list) else [d])
    assert [d for d in flat if touches_belgium(d)] == []


def test_shared_columns_exist_on_the_models_and_are_added_literally():
    metadata = _metadata()
    for table, columns in SHARED.items():
        assert columns <= {c.name for c in metadata.tables[table].columns}, table
    text = (VERSIONS / FILENAME).read_text(encoding="utf-8")
    assert 'op.add_column("payslip_items", sa.Column("be_calculation_snapshot"' in text
    assert 'op.add_column("payroll_runs", sa.Column("be_approval_fingerprint"' in text


def test_no_be_columns_on_employees_or_statutory_profiles():
    """D2: Belgian facts live only in payroll_be_* tables."""
    metadata = _metadata()
    for table in ("payroll_employees", "payroll_employee_statutory_profiles"):
        assert not [c.name for c in metadata.tables[table].columns if c.name.startswith("be_")], table


def test_replay_over_the_full_model_schema_is_a_no_op(model_engine):
    engine, _metadata_ = model_engine
    before = {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()}
    _run(engine, "upgrade")
    _run(engine, "upgrade")
    assert {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()} == before


def test_upgrade_downgrade_upgrade_round_trip_removes_only_its_own_objects(model_engine):
    engine, _metadata_ = model_engine
    tables_before = set(sa.inspect(engine).get_table_names())
    _run(engine, "downgrade")
    tables_after = set(sa.inspect(engine).get_table_names())
    assert tables_before - tables_after == set(NEW_TABLES)
    for table, columns in SHARED.items():
        assert not columns & _cols(engine, table)
    assert {"pl_calculation_snapshot", "nz_calculation_snapshot"} <= _cols(engine, "payslip_items")  # neighbours
    assert {"pl_approval_fingerprint", "nz_approval_fingerprint"} <= _cols(engine, "payroll_runs")
    _run(engine, "downgrade")                                                   # idempotent both ways
    _run(engine, "upgrade")
    assert set(NEW_TABLES) <= set(sa.inspect(engine).get_table_names())
    for table, columns in SHARED.items():
        assert columns <= _cols(engine, table)
    assert set(sa.inspect(engine).get_table_names()) == tables_before


def test_create_all_builds_a_fresh_database_with_every_belgian_table(tmp_path):
    """migrations/create_all against a throwaway SQLite file (subprocess, so the
    app's global engine is bound to that file and never to backend/.env)."""
    target = tmp_path / "fresh.db"
    env = dict(os.environ, PAYROLL_DATABASE_URL=f"sqlite:///{target.as_posix()}")
    done = subprocess.run([sys.executable, "-m", "migrations.create_all.create_all"], cwd=BACKEND, env=env,
                          capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-2000:]
    engine = sa.create_engine(f"sqlite:///{target.as_posix()}")
    try:
        tables = set(sa.inspect(engine).get_table_names())
        assert set(NEW_TABLES) <= tables
        for table, columns in SHARED.items():
            assert columns <= _cols(engine, table)
    finally:
        engine.dispose()


def test_deploy_drift_filter_explains_every_be_object():
    from scripts.drift_pending_filter import pending_objects

    here = os.getcwd()
    os.chdir(BACKEND)
    try:
        tables, columns = pending_objects(PARENT)
    finally:
        os.chdir(here)
    # Everything since this revision's parent: its own objects plus Block B's
    # (tables, and the Block B columns on this revision's tables).
    assert tables == set(NEW_TABLES) | set(LATER_TABLES) | set(BLOCK_C_TABLES)
    assert {t: c for t, c in columns.items() if t in SHARED} == SHARED
    assert {t: c for t, c in columns.items() if t not in SHARED} in ({}, LATER)


def test_revision_is_the_single_child_of_the_previous_head():
    module = _load()
    assert (module.revision, module.down_revision) == (REVISION, PARENT)
    children = [p.name for p in VERSIONS.glob("*.py")
                if re.search(rf'down_revision[^\n]*"{PARENT}"', p.read_text(encoding="utf-8"))]
    assert children == [FILENAME]


def test_the_only_child_is_the_block_b_revision():
    """The single-head check moved to tests/test_belgium_block_b_migration.py when
    Block B chained 2943a0490b5b onto this revision."""
    children = [p.name for p in VERSIONS.glob("*.py")
                if re.search(rf'down_revision[^\n]*"{REVISION}"', p.read_text(encoding="utf-8"))]
    assert children == [f"{LATER_REVISION}_be_absence_holiday_payment.py"]


def test_create_table_names_are_literal_in_the_migration():
    text = (VERSIONS / FILENAME).read_text(encoding="utf-8")
    for table in NEW_TABLES:
        assert f'op.create_table(\n            "{table}"' in text, table


def test_migration_is_listed_in_the_manifest():
    manifest = (VERSIONS.parent / "MIGRATIONS_MANIFEST.txt").read_text(encoding="utf-8")
    assert f"{FILENAME}|{REVISION}|{PARENT}|" in manifest


def test_no_statutory_number_is_a_check_constraint():
    """ZP-BE-ENG-001 §3: CHECKs hold enumerations, evidence, date order and
    four-eyes only — never a rate, threshold, band or wage floor (13.07, 24.92,
    108, 5.57, 10.27, 2233.61, 4000, 38, 40 ...)."""
    for source in ((VERSIONS / FILENAME).read_text(encoding="utf-8"),):
        checks = re.findall(r'CheckConstraint\((.*?)name=', source, re.S)
        assert checks
        for body in checks:
            assert not re.search(r"\d+\.\d+", body), body
            # Only 0 (positivity / non-negative) and the quarter range 1..4 appear.
            assert set(re.findall(r"\b\d+\b", body)) <= {"0", "1", "4"}, body


def test_vocabularies_match_between_models_and_migration():
    from app.modules.payroll import models

    module = _load()
    assert module.WORKER_CATEGORIES == models._BE_WORKER_CATEGORIES
    assert module.DECLARATION_TYPES == models._BE_DECLARATION_TYPES
    assert module.ACCUMULATORS == _load(LATER_REVISION).OLD_ACCUMULATORS          # Block B extends the list
    assert models._BE_ACCUMULATORS == _load(LATER_REVISION).NEW_ACCUMULATORS
    assert module.SCHEDULE_REGIMES == models._BE_SCHEDULE_REGIMES
    assert models._BE_IDENTIFIER_TYPES == ("NISS", "BIS", "ONSS")              # no ENTERPRISE (Q3)
    assert {"WITHHOLDING", "WITHHOLDING_EXCEPTIONAL"} <= set(models._BE_ACCUMULATORS)  # BE-011 separate


# -- database rules ---------------------------------------------------------
def _insert(engine, metadata, table, **values):
    with engine.begin() as conn:
        conn.execute(metadata.tables[table].insert().values(**values))


def _rejects(engine, metadata, table, **values):
    with pytest.raises(sa.exc.IntegrityError):
        _insert(engine, metadata, table, **values)


_VAULT = dict(organization_id=1, employee_id=1, subject_type="EMPLOYEE", identifier_type="NISS",
              ciphertext="ciphertext", key_version=1, fingerprint="f" * 64, collected_at=datetime(2026, 11, 11),
              status="ACTIVE")


def test_the_vault_has_no_plaintext_like_column():
    names = {c.name.lower() for c in _metadata().tables["payroll_be_identifier_vault"].columns}
    for forbidden in ("niss", "insz", "bis", "onss", "number", "plaintext", "value", "last4", "digits", "iban"):
        assert forbidden not in names


def test_the_vault_requires_ciphertext_unless_deleted(model_engine):
    engine, metadata = model_engine
    t = "payroll_be_identifier_vault"
    _rejects(engine, metadata, t, **dict(_VAULT, ciphertext=None))
    _insert(engine, metadata, t, **dict(_VAULT, ciphertext=None, status="DELETED", deleted_at=datetime(2026, 11, 11)))
    _insert(engine, metadata, t, **_VAULT)


def test_the_vault_subject_matches_its_identifier(model_engine):
    engine, metadata = model_engine
    t = "payroll_be_identifier_vault"
    employer = dict(_VAULT, subject_type="EMPLOYER", employee_id=None, identifier_type="ONSS")
    _rejects(engine, metadata, t, **dict(_VAULT, employee_id=None))                     # employee row needs employee
    _rejects(engine, metadata, t, **dict(_VAULT, identifier_type="ONSS"))               # ONSS is employer-only
    _rejects(engine, metadata, t, **dict(_VAULT, identifier_type="ENTERPRISE"))         # never a vault type
    _rejects(engine, metadata, t, **dict(employer, identifier_type="NISS"))             # employer NISS
    _rejects(engine, metadata, t, **dict(employer, identifier_type="BIS"))
    _rejects(engine, metadata, t, **dict(employer, identifier_type="ENTERPRISE"))       # ONSS only for employers
    _rejects(engine, metadata, t, **dict(employer, employee_id=1))
    _rejects(engine, metadata, t, **dict(_VAULT, subject_type="WORKER"))
    _rejects(engine, metadata, t, **dict(_VAULT, status="REVOKED"))
    _insert(engine, metadata, t, **employer)
    _insert(engine, metadata, t, **dict(_VAULT, identifier_type="BIS", fingerprint="a" * 64))


def test_the_vault_allows_one_active_identifier_per_type_and_no_duplicates(model_engine):
    engine, metadata = model_engine
    t = "payroll_be_identifier_vault"
    _insert(engine, metadata, t, **_VAULT)
    _rejects(engine, metadata, t, **dict(_VAULT, fingerprint="e" * 64))          # second active NISS
    _rejects(engine, metadata, t, **dict(_VAULT, employee_id=2))                 # same NISS, other employee
    _insert(engine, metadata, t, **dict(_VAULT, employee_id=2, fingerprint="e" * 64))
    _insert(engine, metadata, t, **dict(_VAULT, status="DELETED"))               # history kept


def test_access_events_action_vocabulary(model_engine):
    engine, metadata = model_engine
    t = "payroll_be_identifier_access_events"
    _rejects(engine, metadata, t, organization_id=1, action="PEEK")
    _insert(engine, metadata, t, organization_id=1, action="REVEAL_REQUESTED")


def _employer(**overrides):
    values = dict(organization_id=1, effective_from=date(2026, 1, 1), legal_name="Synthetic BV",
                  enterprise_number="0123456789", status="DRAFT")
    values.update(overrides)
    return values


def test_employer_registration_rules(model_engine):
    engine, metadata = model_engine
    t = "payroll_be_employer_registrations"
    _insert(engine, metadata, t, **_employer())                                  # category unknown is storable
    _rejects(engine, metadata, t, **_employer(legal_language="EN"))
    _rejects(engine, metadata, t, **_employer(verification_state="PENDING"))
    _rejects(engine, metadata, t, **_employer(status="LIVE"))
    _rejects(engine, metadata, t, **_employer(effective_to=date(2025, 12, 31)))
    # Four-eyes: ACTIVE without an approver, and ACTIVE approved by its creator, are refused.
    _rejects(engine, metadata, t, **_employer(status="ACTIVE"))
    _rejects(engine, metadata, t, **_employer(status="ACTIVE", created_by_id=7, approved_by_id=7))
    _insert(engine, metadata, t, **_employer(status="ACTIVE", created_by_id=7, approved_by_id=8,
                                             legal_language="NL"))
    _rejects(engine, metadata, t, **_employer(status="ACTIVE", created_by_id=7, approved_by_id=8))  # one per org
    _insert(engine, metadata, t, **_employer(status="ACTIVE", created_by_id=7, approved_by_id=8,
                                             effective_to=date(2026, 6, 30)))                         # closed: fine
    _insert(engine, metadata, t, **_employer(status="ACTIVE", created_by_id=7, approved_by_id=8, legal_entity_id=5))
    _rejects(engine, metadata, t, **_employer(status="ACTIVE", created_by_id=7, approved_by_id=8, legal_entity_id=5))
    _insert(engine, metadata, t, **_employer(status="SUPERSEDED"))


def _versioned(engine, metadata, table, base):
    """The three _be_versioned_checks on any versioned table."""
    _rejects(engine, metadata, table, **dict(base, status="LIVE"))
    _rejects(engine, metadata, table, **dict(base, effective_to=date(2025, 12, 31)))
    _rejects(engine, metadata, table, **dict(base, status="ACTIVE"))
    _rejects(engine, metadata, table, **dict(base, status="ACTIVE", created_by_id=3, approved_by_id=3))


def test_establishment_unit_rules(model_engine):
    engine, metadata = model_engine
    _insert(engine, metadata, "payroll_be_employer_registrations", **_employer())
    t = "payroll_be_establishment_units"
    base = dict(organization_id=1, registration_id=1, unit_number="2000000001", name="Synthetic site",
                effective_from=date(2026, 1, 1), status="DRAFT")
    _versioned(engine, metadata, t, base)
    active = dict(base, status="ACTIVE", created_by_id=3, approved_by_id=4)
    _insert(engine, metadata, t, **active)
    _rejects(engine, metadata, t, **active)                                      # one ACTIVE open per unit number
    _insert(engine, metadata, t, **dict(active, effective_to=date(2026, 6, 30)))  # closed rows do not count
    _insert(engine, metadata, t, **dict(active, unit_number="2000000002"))


def _profile(**overrides):
    values = dict(organization_id=1, employee_id=1, effective_from=date(2026, 1, 1), worker_category="EMPLOYEE",
                  status="DRAFT")
    values.update(overrides)
    return values


def test_worker_profile_rules(model_engine):
    engine, metadata = model_engine
    t = "payroll_be_worker_profiles"
    _insert(engine, metadata, t, **_profile())
    _rejects(engine, metadata, t, **_profile(worker_category="WHITE_COLLAR"))
    _rejects(engine, metadata, t, **_profile(residency="EXPAT"))
    _versioned(engine, metadata, t, _profile())
    active = _profile(status="ACTIVE", created_by_id=3, approved_by_id=4)
    _insert(engine, metadata, t, **active)
    _rejects(engine, metadata, t, **dict(active, worker_category="MANUAL"))    # A3: one ACTIVE open per employee
    _insert(engine, metadata, t, **dict(active, effective_to=date(2026, 3, 31)))
    _insert(engine, metadata, t, **dict(active, employee_id=2))
    for category in ("MANUAL", "APPRENTICE", "STUDENT", "FLEXI", "OCCASIONAL", "OTHER"):
        _insert(engine, metadata, t, **_profile(worker_category=category))


def test_work_schedule_rules(model_engine):
    engine, metadata = model_engine
    t = "payroll_be_work_schedules"
    base = dict(organization_id=1, employee_id=1, regime="EFFECTIVE", weekly_hours=30,
                effective_from=date(2026, 1, 1), status="DRAFT")
    _insert(engine, metadata, t, **base)
    _insert(engine, metadata, t, **dict(base, regime="AVERAGE"))
    _rejects(engine, metadata, t, **dict(base, regime="FLEX"))
    _rejects(engine, metadata, t, **dict(base, weekly_hours=0))
    _rejects(engine, metadata, t, **dict(base, weekly_hours=-1))
    _versioned(engine, metadata, t, base)


def test_employment_classification_rules(model_engine):
    engine, metadata = model_engine
    t = "payroll_be_employment_classifications"
    base = dict(organization_id=1, employee_id=1, employment_line="LINE-1", effective_from=date(2026, 1, 1),
                status="DRAFT")
    _insert(engine, metadata, t, **base)                                         # JC unknown is storable
    _rejects(engine, metadata, t, **dict(base, seniority_months=-1))
    _versioned(engine, metadata, t, base)
    active = dict(base, status="ACTIVE", created_by_id=3, approved_by_id=4)
    _insert(engine, metadata, t, **active)
    _rejects(engine, metadata, t, **active)                                      # one ACTIVE open per line
    _insert(engine, metadata, t, **dict(active, employment_line="LINE-2"))
    _insert(engine, metadata, t, **dict(active, effective_to=date(2026, 6, 30)))


def _declaration(**overrides):
    values = dict(organization_id=1, employee_id=1, effective_from=date(2026, 1, 1),
                  declaration_type="FAMILY_SITUATION", received_at=datetime(2025, 12, 20), source_channel="PAPER",
                  evidence_ref="scan-1", status="RECEIVED")
    values.update(overrides)
    return values


def test_declaration_rules(model_engine):
    engine, metadata = model_engine
    t = "payroll_be_declarations"
    _insert(engine, metadata, t, **_declaration())
    for kind in ("DEPENDANTS", "NON_RESIDENT_STATUS", "WORK_BONUS_FISCAL_ELECTION"):
        _insert(engine, metadata, t, **_declaration(declaration_type=kind))
    _rejects(engine, metadata, t, **_declaration(evidence_ref=None))
    _rejects(engine, metadata, t, **_declaration(declaration_type="PIT2"))
    _rejects(engine, metadata, t, **_declaration(source_channel="EMAIL"))
    _rejects(engine, metadata, t, **_declaration(status="FILED"))
    _rejects(engine, metadata, t, **_declaration(status="APPROVED"))                       # no approver
    _rejects(engine, metadata, t, **_declaration(status="APPROVED", created_by_id=3, approved_by_id=3))
    _insert(engine, metadata, t, **_declaration(status="APPROVED", created_by_id=3, approved_by_id=4))
    _rejects(engine, metadata, t, **_declaration(status="WITHDRAWN"))
    _rejects(engine, metadata, t, **_declaration(status="SUPERSEDED"))
    _rejects(engine, metadata, t, **_declaration(effective_to=date(2025, 12, 31)))


def _entry(**overrides):
    values = dict(organization_id=1, employee_id=1, year=2026, accumulator="ONSS_EMPLOYEE_BASE",
                  pay_date=date(2026, 1, 31), amount=1000, entry_kind="RUN", payslip_item_id=1)
    values.update(overrides)
    return values


def test_ledger_rules(model_engine):
    engine, metadata = model_engine
    t = "payroll_be_accumulator_entries"
    _insert(engine, metadata, t, **_entry(employment_line="LINE-1", quarter=1))
    _rejects(engine, metadata, t, **_entry())                                    # one RUN post per payslip
    _rejects(engine, metadata, t, **_entry(payslip_item_id=None))
    _rejects(engine, metadata, t, **_entry(accumulator="ZUS_CAP_PENSION_BASE", payslip_item_id=2))
    _rejects(engine, metadata, t, **_entry(entry_kind="ADJUSTMENT", payslip_item_id=2))
    # Q2: PRIOR_EMPLOYER is blocked outright, even with evidence and a second approver.
    _rejects(engine, metadata, t, **_entry(entry_kind="PRIOR_EMPLOYER", payslip_item_id=None, evidence_ref="cert",
                                           created_by_id=5, approved_by_id=6))
    # Opening balances: evidence + a different approver.
    opening = dict(entry_kind="OPENING_BALANCE", payslip_item_id=None)
    _rejects(engine, metadata, t, **_entry(**opening))
    _rejects(engine, metadata, t, **_entry(**opening, evidence_ref="import", created_by_id=5, approved_by_id=5))
    _rejects(engine, metadata, t, **_entry(**opening, evidence_ref="import"))
    _insert(engine, metadata, t, **_entry(**opening, evidence_ref="import", created_by_id=5, approved_by_id=6))
    # A correction is a linked compensating entry.
    _rejects(engine, metadata, t, **_entry(entry_kind="CORRECTION", payslip_item_id=None))
    _insert(engine, metadata, t, **_entry(entry_kind="CORRECTION", payslip_item_id=None, reverses_id=1,
                                          amount=-1000))
    # Quarter 1..4 only.
    for bad in (0, 5):
        _rejects(engine, metadata, t, **_entry(quarter=bad, payslip_item_id=10 + bad))
    # A2 (BE-009): source period is a pair, in order.
    _rejects(engine, metadata, t, **_entry(payslip_item_id=20, source_period_start=date(2025, 12, 1)))
    _rejects(engine, metadata, t, **_entry(payslip_item_id=21, source_period_end=date(2025, 12, 31)))
    _rejects(engine, metadata, t, **_entry(payslip_item_id=22, source_period_start=date(2025, 12, 31),
                                           source_period_end=date(2025, 12, 1)))
    _insert(engine, metadata, t, **_entry(payslip_item_id=23, accumulator="WITHHOLDING_EXCEPTIONAL",
                                          source_period_start=date(2025, 12, 1), source_period_end=date(2025, 12, 31)))
    # A1 (BE-017): employment_line is a nullable column for worker-level accumulators.
    _insert(engine, metadata, t, **_entry(payslip_item_id=24, accumulator="WORK_BONUS_FISCAL", employment_line=None))


def test_ledger_lookup_index_includes_the_employment_line():
    index = next(i for i in _metadata().tables["payroll_be_accumulator_entries"].indexes if i.name == "ix_be_accum_lookup")
    assert [c.name for c in index.columns] == ["employee_id", "legal_entity_id", "employment_line", "year",
                                               "accumulator", "pay_date"]


def test_ledger_and_access_events_have_no_updated_at():
    for table in ("payroll_be_accumulator_entries", "payroll_be_identifier_access_events"):
        assert "updated_at" not in {c.name for c in _metadata().tables[table].columns}, table


# -- PostgreSQL round trip (disposable database only) ------------------------
PG_URL = os.environ.get("ZP_TEST_POSTGRES_URL")


def pg_round_trip(revision, new_tables, tenant, worker, columns=None):
    """Schema from the models + d7f9b1c3e5a6's RLS, then `revision`'s
    downgrade -> upgrade -> upgrade (replay) -> downgrade -> upgrade on a real,
    DISPOSABLE PostgreSQL. After each upgrade every table of the revision exists
    with RLS enabled and forced and the zoiko_rls policy present (TENANT /
    WORKER "org" predicate as derived); after each downgrade none of them exists
    and its added columns are gone. Only the revision's OWN objects are checked:
    later Belgium revisions' tables stay. Used by the Phase 2, Block B and
    Block C migration tests (CI privacy-isolation job)."""
    columns = columns or {}
    metadata = _metadata()
    engine = sa.create_engine(PG_URL, connect_args={"sslmode": "disable"} if "sslmode" not in PG_URL else {})
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("DROP SCHEMA public CASCADE"))
            conn.execute(sa.text("CREATE SCHEMA public"))
        metadata.create_all(engine)
        with engine.begin() as conn:
            _load("d7f9b1c3e5a6").apply_rls(conn)

        def step(name):
            with engine.begin() as conn:
                with Operations.context(MigrationContext.configure(conn)):
                    getattr(_load(revision), name)()

        def state():
            with engine.connect() as conn:
                tables = set(sa.inspect(conn).get_table_names())
                rls = {r[0]: (r[1], r[2]) for r in conn.execute(sa.text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname LIKE 'payroll_be_%' AND relkind = 'r'"))}
                policies = {r[0] for r in conn.execute(sa.text(
                    "SELECT tablename FROM pg_policies WHERE policyname = 'zoiko_rls'"))}
                cols = {t: {c["name"] for c in sa.inspect(conn).get_columns(t)} for t in columns}
            return tables, rls, policies, cols

        mine = set(new_tables)
        step("downgrade")
        tables, rls, policies, cols = state()
        assert not mine & tables and not mine & policies
        assert all(not (columns[t] & cols[t]) for t in columns)
        for name in ("upgrade", "upgrade", "downgrade", "upgrade"):
            step(name)
            tables, rls, policies, cols = state()
            if name == "downgrade":
                assert not mine & tables
                continue
            assert mine <= tables
            assert mine <= policies, mine - policies
            assert all(rls[t] == (True, True) for t in mine), rls
            assert all(columns[t] <= cols[t] for t in columns)
        with engine.connect() as conn:
            qual = dict(conn.execute(sa.text(
                "SELECT tablename, qual FROM pg_policies WHERE policyname = 'zoiko_rls' "
                "AND tablename LIKE 'payroll_be_%'")).all())
        assert all("organization_id IS NULL" in qual[t] for t in tenant)            # TENANT predicate
        assert all("organization_id IS NULL" not in qual[t] for t in worker)        # WORKER "org" predicate
    finally:
        engine.dispose()


@pytest.mark.skipif(not PG_URL, reason="ZP_TEST_POSTGRES_URL not set (disposable Postgres only)")
def test_postgres_round_trip_with_row_level_security():
    pg_round_trip(REVISION, NEW_TABLES, TENANT, WORKER, SHARED)
