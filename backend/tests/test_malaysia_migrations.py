"""Malaysia foundation migration 13574b996ccf (ZP-MY-ENG-001 Phase 2).

Proves, without a PostgreSQL server:
  * the row-level-security policy the revision applies to each new table is the
    one d7f9b1c3e5a6's classify() derives from the model schema — TENANT for
    employer registrations, WORKER/"org" for the six employee tables;
  * built FROM THE MIGRATION (not from the models), the tables have exactly the
    models' columns and indexes, every CHECK rule works on real rows, and the
    shared columns are added literally;
  * it is additive and idempotent: replaying it is a no-op, downgrade removes
    only its own objects;
  * the deploy drift filter explains every Malaysia object; the manifest and
    the single-child chain hold; no statutory number is a CHECK constraint.
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

REVISION, PARENT, SUFFIX = "13574b996ccf", "f3a9c1d7e2b4", "my_foundation"   # re-parented 2026-11-12
TENANT = ("payroll_my_employer_registrations",)
WORKER = ("payroll_my_identifier_vault", "payroll_my_identifier_access_events", "payroll_my_worker_profiles",
          "payroll_my_work_assignments", "payroll_my_tax_declarations", "payroll_my_accumulator_entries")
NEW_TABLES = TENANT + WORKER
SHARED = {"payslip_items": {"my_calculation_snapshot"}, "payroll_runs": {"my_approval_fingerprint"}}


def _run(engine, fn_name):
    module = _load(REVISION)
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            getattr(module, fn_name)()


@pytest.fixture()
def migrated():
    """The full model schema, then THIS revision's objects rebuilt by the migration."""
    metadata = _metadata()
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                              poolclass=StaticPool)
    metadata.create_all(engine)
    model_indexes = {t: _indexes(engine, t) for t in NEW_TABLES}
    _run(engine, "downgrade")
    _run(engine, "upgrade")
    with engine.begin() as conn:
        conn.execute(sa.text("PRAGMA foreign_keys=OFF"))
    yield engine, metadata, model_indexes
    engine.dispose()


# ── row-level security ─────────────────────────────────────────────────────
def test_rls_matches_classify_and_is_emitted(classified):
    rls, worker, tenant = classified
    for table in TENANT:
        assert table in tenant and table not in worker, table
    for table in WORKER:
        assert worker.get(table) == "org" and table not in tenant, table
    bind = _CaptureBind()
    _load(REVISION)._rls_for_new_tables(bind)
    want = {t: " ".join(rls._TENANT_PREDICATE.split()) for t in TENANT}
    want.update({t: " ".join(rls._worker_predicate("org").split()) for t in WORKER})
    assert _policies(bind.sql) == want


# ── migration <-> model contract (built by the migration) ───────────────────
def test_tables_built_by_the_migration_match_the_models(migrated):
    engine, metadata, model_indexes = migrated
    for table in NEW_TABLES:
        assert _cols(engine, table) == {c.name for c in metadata.tables[table].columns}, table
        assert model_indexes[table] <= _indexes(engine, table), table
    for table, columns in SHARED.items():
        assert columns <= _cols(engine, table)
        assert columns <= {c.name for c in metadata.tables[table].columns}


def test_replay_is_a_no_op_and_downgrade_removes_only_its_own_objects(migrated):
    engine, _metadata_, _ = migrated
    before = {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()}
    _run(engine, "upgrade")
    assert {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()} == before
    _run(engine, "downgrade")
    assert set(before) - set(sa.inspect(engine).get_table_names()) == set(NEW_TABLES)
    for table, columns in SHARED.items():
        assert not columns & _cols(engine, table)
    assert {"pl_calculation_snapshot", "nz_calculation_snapshot"} <= _cols(engine, "payslip_items")   # neighbours


def test_literal_names_manifest_chain_and_lock_timeout():
    module = _load(REVISION)
    assert (module.revision, module.down_revision) == (REVISION, PARENT)
    children = [p.name for p in VERSIONS.glob("*.py")
                if re.search(rf'down_revision[^\n]*"{PARENT}"', p.read_text(encoding="utf-8"))]
    assert children == [f"{REVISION}_{SUFFIX}.py"]
    text = (VERSIONS / f"{REVISION}_{SUFFIX}.py").read_text(encoding="utf-8")
    for table in NEW_TABLES:
        assert f'op.create_table(\n            "{table}"' in text, table
    assert 'op.add_column("payslip_items", sa.Column("my_calculation_snapshot"' in text
    assert 'op.add_column("payroll_runs", sa.Column("my_approval_fingerprint"' in text
    assert "lock_timeout" in text
    manifest = (VERSIONS.parent / "MIGRATIONS_MANIFEST.txt").read_text(encoding="utf-8")
    assert f"{REVISION}_{SUFFIX}.py|{REVISION}|{PARENT}|" in manifest


def test_no_statutory_number_is_a_check_constraint():
    text = (VERSIONS / f"{REVISION}_{SUFFIX}.py").read_text(encoding="utf-8")
    checks = re.findall(r'CheckConstraint\((?:f)?"([^"]*)"', text)
    for value in ("1700", "5000", "6000", "20000", "4000", "45", "98", "0.2", "0.75", "11", "13"):
        assert not any(re.search(rf"\b{re.escape(value)}\b", c) for c in checks), value


def test_vocabularies_match_the_content_module():
    from app.modules.payroll.engine.countries import malaysia_content as c

    m = _load(REVISION)
    assert m.TERRITORIES == c.TERRITORIES and m.HOLIDAY_STATES == c.HOLIDAY_STATES
    assert m.EPF_MEMBER_CLASSES == c.EPF_MEMBER_CLASSES and m.SOCSO_CATEGORIES == c.SOCSO_CATEGORIES
    assert m.EIS_STATES == c.EIS_STATES and m.HRD_CATEGORIES == c.HRD_CATEGORIES
    assert m.DECLARATION_TYPES == c.DECLARATION_TYPES and m.ACCUMULATORS == c.ACCUMULATORS
    assert m.WORK_PASS_TYPES == c.WORK_PASS_TYPES and m.CITIZENSHIP == c.CITIZENSHIP
    assert "SABAH" in m.TERRITORIES and "LABUAN" not in m.TERRITORIES


# ── database rules on tables built by the migration ─────────────────────────
NOW = datetime(2026, 3, 1, 9, 0)


def _insert(engine, table, **values):
    cols = ", ".join(values)
    marks = ", ".join(f":{k}" for k in values)
    with engine.begin() as conn:
        conn.execute(sa.text(f'INSERT INTO "{table}" ({cols}) VALUES ({marks})'), values)


def _refused(engine, table, **values):
    with pytest.raises(IntegrityError):
        _insert(engine, table, **values)


BASE = {"organization_id": 1, "created_at": NOW}


def test_vault_rules(migrated):
    engine = migrated[0]
    row = {**BASE, "employee_id": 1, "identifier_type": "NRIC", "ciphertext": "c", "key_version": 1,
           "fingerprint": "f" * 64, "collected_at": NOW, "status": "ACTIVE", "purpose": "PAYROLL_STATUTORY"}
    _insert(engine, "payroll_my_identifier_vault", **row)
    _refused(engine, "payroll_my_identifier_vault", **{**row, "fingerprint": "e" * 64})      # one ACTIVE per type
    _refused(engine, "payroll_my_identifier_vault", **{**row, "employee_id": 2})            # duplicate fingerprint
    _refused(engine, "payroll_my_identifier_vault", **{**row, "identifier_type": "PESEL", "employee_id": 3})
    _refused(engine, "payroll_my_identifier_vault", **{**row, "employee_id": 4, "fingerprint": "d" * 64,
                                                       "ciphertext": None})
    _insert(engine, "payroll_my_identifier_vault", **{**row, "employee_id": 5, "fingerprint": "b" * 64,
                                                      "ciphertext": None, "deleted_at": NOW, "status": "DELETED"})


def test_employer_registration_rules(migrated):
    engine = migrated[0]
    row = {**BASE, "effective_from": date(2026, 1, 1), "legal_name": "Syarikat Contoh Sdn Bhd",
           "hasil_employer_no": "E1234567890", "hrd_category": "NOT_REGISTERED", "status": "DRAFT",
           "verification_state": "UNVERIFIED"}
    _insert(engine, "payroll_my_employer_registrations", **row)
    _refused(engine, "payroll_my_employer_registrations", **{**row, "hrd_category": "HEADCOUNT_10"})
    _refused(engine, "payroll_my_employer_registrations", **{**row, "hrd_category": "COMPULSORY"})   # no evidence
    _insert(engine, "payroll_my_employer_registrations", **{**row, "hrd_category": "COMPULSORY",
                                                            "hrd_registration_no": "123456",
                                                            "hrd_category_from": date(2025, 1, 1),
                                                            "hrd_category_evidence_ref": "HRD Corp letter"})
    _refused(engine, "payroll_my_employer_registrations", **{**row, "status": "ACTIVE", "created_by_id": 1,
                                                             "approved_by_id": 1})                    # four-eyes
    _refused(engine, "payroll_my_employer_registrations", **{**row, "effective_to": date(2025, 12, 31)})


def test_worker_profile_rules(migrated):
    engine = migrated[0]
    row = {**BASE, "employee_id": 1, "effective_from": date(2026, 1, 1), "contract_type": "CONTRACT_OF_SERVICE",
           "pay_frequency": "MONTHLY", "tax_residence": "REVIEW_REQUIRED", "status": "DRAFT"}
    _insert(engine, "payroll_my_worker_profiles", **row)
    _insert(engine, "payroll_my_worker_profiles", **{**row, "rest_day": "SUN"})             # the f-string CHECK works
    _refused(engine, "payroll_my_worker_profiles", **{**row, "rest_day": "FUNDAY"})
    _refused(engine, "payroll_my_worker_profiles", **{**row, "tax_residence": "RESIDENT"})  # residence needs evidence
    _insert(engine, "payroll_my_worker_profiles", **{**row, "tax_residence": "RESIDENT",
                                                     "residence_evidence_ref": "182-day test", "residence_from":
                                                     date(2026, 1, 1)})
    _refused(engine, "payroll_my_worker_profiles", **{**row, "citizenship": "NON_CITIZEN"})  # needs a work pass
    _refused(engine, "payroll_my_worker_profiles", **{**row, "citizenship": "NON_CITIZEN", "work_pass_type": "NONE"})
    _insert(engine, "payroll_my_worker_profiles", **{**row, "citizenship": "NON_CITIZEN",
                                                     "work_pass_type": "EMPLOYMENT_PASS"})
    _refused(engine, "payroll_my_worker_profiles", **{**row, "epf_member_class": "FOREIGN"})
    _refused(engine, "payroll_my_worker_profiles", **{**row, "contract_type": "UMOWA_O_PRACE"})
    _refused(engine, "payroll_my_worker_profiles", **{**row, "normal_hours_week": 0})


def test_work_assignment_rules(migrated):
    engine = migrated[0]
    row = {**BASE, "employee_id": 1, "effective_from": date(2026, 1, 1), "labour_territory": "SABAH",
           "holiday_state": "SBH", "assignment_reason": "HIRE", "status": "DRAFT"}
    _insert(engine, "payroll_my_work_assignments", **row)
    _insert(engine, "payroll_my_work_assignments", **{**row, "labour_territory": "PENINSULAR_LABUAN",
                                                      "holiday_state": "LBN"})            # Labuan: Peninsular law
    _refused(engine, "payroll_my_work_assignments", **{**row, "labour_territory": "LABUAN"})
    _refused(engine, "payroll_my_work_assignments", **{**row, "holiday_state": "PENINSULAR"})
    _refused(engine, "payroll_my_work_assignments", **{k: v for k, v in row.items() if k != "holiday_state"})


def test_declaration_and_ledger_rules(migrated):
    engine = migrated[0]
    decl = {**BASE, "employee_id": 1, "effective_from": date(2026, 1, 1), "declaration_type": "TP1",
            "tax_year": 2026, "received_at": NOW, "source_channel": "PAPER", "status": "RECEIVED",
            "evidence_ref": "TP1 form"}
    _insert(engine, "payroll_my_tax_declarations", **decl)
    _insert(engine, "payroll_my_tax_declarations", **{**decl, "declaration_type": "CP38", "source_channel": "AUTHORITY"})
    _refused(engine, "payroll_my_tax_declarations", **{**decl, "declaration_type": "PIT2"})
    _refused(engine, "payroll_my_tax_declarations", **{**decl, "evidence_ref": None})
    _refused(engine, "payroll_my_tax_declarations", **{**decl, "status": "APPROVED", "created_by_id": 1,
                                                       "approved_by_id": 1})
    entry = {**BASE, "employee_id": 1, "year": 2026, "accumulator": "PCB_PAID", "pay_date": date(2026, 3, 31),
             "amount": 100, "entry_kind": "RUN", "payslip_item_id": 1}
    _insert(engine, "payroll_my_accumulator_entries", **entry)
    _refused(engine, "payroll_my_accumulator_entries", **entry)                              # posted once per payslip
    _refused(engine, "payroll_my_accumulator_entries", **{**entry, "accumulator": "ZUS_CAP_PENSION_BASE",
                                                          "payslip_item_id": 2})
    tp3 = {**entry, "entry_kind": "PRIOR_EMPLOYER", "payslip_item_id": None, "accumulator": "PCB_GROSS_NORMAL"}
    _refused(engine, "payroll_my_accumulator_entries", **tp3)                                # needs evidence + 2nd person
    _insert(engine, "payroll_my_accumulator_entries", **{**tp3, "evidence_ref": "TP3", "created_by_id": 1,
                                                         "approved_by_id": 2})
    _refused(engine, "payroll_my_accumulator_entries", **{**tp3, "accumulator": "EPF_EE", "evidence_ref": "TP3",
                                                          "created_by_id": 1, "approved_by_id": 2})
