"""Italy schema contract (ZP-IT-ENG-001) — migration 7a1b2c3d4e5f vs the ORM.

The migration and app/modules/payroll/models.py are two separate declarations of
the same schema, and this codebase has been burned by them drifting: a column
added to the model but not the migration exists in the developer's SQLite (fresh
databases go through Base.metadata.create_all) and is missing in production
(migrated databases go through Alembic). The failure is silent until the code
path that reads the column runs against a real migrated database.

So this module INTROSPECTs both sides and compares them, rather than restating
either as a literal. The migration is executed for real against an in-memory
SQLite connection — not parsed as text — so the columns being compared are the
ones the migration genuinely creates.
"""
import importlib.util
import re
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.modules.payroll.models import (
    EmployeeStatutoryProfile,
    EmployerItalyProfile,
    ItalyFilingOutboxItem,
    PayslipItem,
)

MIGRATION_FILENAME = "7a1b2c3d4e5f_add_italy_jurisdiction_support.py"
MIGRATION_REVISION = "7a1b2c3d4e5f"
MIGRATION_PARENT = "e8f1a2b3c4d5"
BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = BACKEND_ROOT / "alembic" / "versions" / MIGRATION_FILENAME

PROFILE_TABLE = "payroll_employee_statutory_profiles"
PAYSLIP_TABLE = "payslip_items"
EMPLOYER_TABLE = "payroll_it_employer_profiles"
OUTBOX_TABLE = "payroll_it_filing_outbox_items"


def _load_migration():
    """Load the revision file by path. It cannot be imported as
    alembic.versions.<name> because `alembic` resolves to the installed package,
    not this project's migrations directory."""
    spec = importlib.util.spec_from_file_location(
        "italy_migration_under_test", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_migration(steps):
    """Execute the migration's given steps against a real in-memory SQLite
    database and return a plain-dict snapshot of the resulting schema.

    The two ALTERed tables are pre-created with a bare id so their ADD COLUMN
    statements have something to attach to, which is what the baseline migration
    leaves behind.

    The schema is copied into plain dicts rather than returning the Inspector,
    because an Inspector is bound to a live connection and the caller needs the
    schema after the connection has been released.
    """
    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        connection.begin()
        for statement in (
            f"CREATE TABLE {PROFILE_TABLE} (id INTEGER PRIMARY KEY)",
            f"CREATE TABLE {PAYSLIP_TABLE} (id INTEGER PRIMARY KEY)",
            "CREATE TABLE organizations (id INTEGER PRIMARY KEY)",
            "CREATE TABLE statutory_filings (id INTEGER PRIMARY KEY)",
        ):
            connection.execute(sa.text(statement))

        module = _load_migration()
        context = MigrationContext.configure(connection)
        original_op = module.op
        module.op = Operations(context)
        try:
            for step in steps:
                getattr(module, step)()
        finally:
            module.op = original_op

        inspector = sa.inspect(connection)
        tables = set(inspector.get_table_names())
        snapshot = {
            "tables": tables,
            "columns": {
                table: {c["name"]: dict(c) for c in inspector.get_columns(table)}
                for table in tables
            },
            "indexes": {
                table: [dict(i) for i in inspector.get_indexes(table)]
                for table in tables
            },
            # A UNIQUE declared inline is reported as a constraint on SQLite and
            # as a unique index on PostgreSQL, so both are collected.
            "unique_constraints": {
                table: [dict(u) for u in inspector.get_unique_constraints(table)]
                for table in tables
            },
        }
    return snapshot


def _unique_column_sets(snapshot, table):
    """Every column set the schema declares unique, however the dialect reports
    it."""
    from_indexes = {tuple(i["column_names"])
                    for i in snapshot["indexes"].get(table, [])
                    if i.get("unique")}
    from_constraints = {tuple(u.get("column_names") or ())
                        for u in snapshot["unique_constraints"].get(table, [])}
    return from_indexes | from_constraints


@pytest.fixture(scope="module")
def migrated():
    """The schema this migration actually produces."""
    return _run_migration(["upgrade"])


def _migrated_columns(snapshot, table):
    return snapshot["columns"][table]


def _model_columns(model):
    return {c.name: c for c in model.__table__.columns}


def _type_of(column):
    return column["type"] if isinstance(column, dict) else column.type


def _length_of(column):
    return getattr(_type_of(column), "length", None)


def _nullable_of(column):
    value = column["nullable"] if isinstance(column, dict) else column.nullable
    return bool(value)


# ── 1. the two new tables ────────────────────────────────────────────────────
@pytest.mark.parametrize("table,model", [
    (EMPLOYER_TABLE, EmployerItalyProfile),
    (OUTBOX_TABLE, ItalyFilingOutboxItem),
])
def test_new_table_matches_the_model_column_for_column(migrated, table, model):
    """Every column the model declares must exist in the migrated table with the
    same type and nullability. A missing column is the create_all-vs-Alembic
    split; a wrong length is a PostgreSQL truncation waiting to happen."""
    from_migration = _migrated_columns(migrated, table)
    from_model = _model_columns(model)

    assert set(from_model) - set(from_migration) == set(), (
        f"{model.__name__} declares columns the migration never creates: "
        f"{sorted(set(from_model) - set(from_migration))}")
    assert set(from_migration) - set(from_model) == set(), (
        f"{table} has columns the model does not declare: "
        f"{sorted(set(from_migration) - set(from_model))}")

    for name, column in from_model.items():
        migrated_column = from_migration[name]
        assert str(_type_of(column)) == str(_type_of(migrated_column)), (
            f"{table}.{name}: model {_type_of(column)} vs migration "
            f"{_type_of(migrated_column)}")
        assert _nullable_of(column) == _nullable_of(migrated_column), (
            f"{table}.{name} nullability differs between model and migration")
        assert _length_of(column) == _length_of(migrated_column), (
            f"{table}.{name} length differs between model and migration")


def test_migration_adds_exactly_the_declared_employer_and_outbox_tables(migrated):
    """Guards the opposite direction: a stray table in the migration would be
    created in production and never in a fresh dev database."""
    tables = migrated["tables"]
    assert EMPLOYER_TABLE in tables
    assert OUTBOX_TABLE in tables
    assert not [t for t in tables if t.startswith("payroll_it_")
                and t not in (EMPLOYER_TABLE, OUTBOX_TABLE)]


# ── 2. the ALTERed tables ────────────────────────────────────────────────────
def test_employee_profile_additions_match_the_model(migrated):
    """The 15 worker-owned it_* facts. This is the comparison the create_all /
    Alembic split actually breaks: a fresh dev database gets these from the model
    and a migrated one from this revision."""
    from_migration = _migrated_columns(migrated, PROFILE_TABLE)
    from_model = _model_columns(EmployeeStatutoryProfile)

    it_in_migration = {n for n in from_migration if n.startswith("it_")}
    it_in_model = {n for n in from_model if n.startswith("it_")}

    assert it_in_model == it_in_migration
    assert len(it_in_model) == 15, (
        f"expected the 15 it_* facts, found {sorted(it_in_model)}")

    for name in sorted(it_in_model):
        column, migrated_column = from_model[name], from_migration[name]
        assert str(_type_of(column)) == str(_type_of(migrated_column)), name
        assert _nullable_of(column) == _nullable_of(migrated_column), name
        assert _length_of(column) == _length_of(migrated_column), name


def test_payslip_snapshot_column_matches_the_model(migrated):
    from_migration = _migrated_columns(migrated, PAYSLIP_TABLE)
    assert "it_calculation_snapshot" in from_migration
    column = _model_columns(PayslipItem)["it_calculation_snapshot"]
    assert str(_type_of(column)) == str(
        _type_of(from_migration["it_calculation_snapshot"]))
    assert _nullable_of(column) is True


def test_no_italy_column_is_created_with_a_non_nullable_constraint(migrated):
    """Every worker-owned fact is optional. An it_* column that cannot be null
    would lock every non-Italian employee's row out of the table, so the
    constraint is asserted rather than assumed."""
    for name, column in _migrated_columns(migrated, PROFILE_TABLE).items():
        if name.startswith("it_"):
            assert column["nullable"] is True, f"{name} is NOT NULL"


# ── 3. column widths, asserted against the real PostgreSQL model lengths ─────
def test_string_column_widths_fit_real_italian_values():
    """The `de_*` block this migration was cloned from used String(10), which
    cannot hold a real Italian value (a CNEL code, a comune name, an INPS
    matricola). Lengths are read from the model rather than hardcoded, so the
    guard keeps working if a width is ever corrected.
    """
    from_model = _model_columns(EmployeeStatutoryProfile)

    # (column, a real value that must fit). CNEL contract codes are the short
    # registry code reported to UniEmens (e.g. H011 = commercio al dettaglio),
    # not the contract's descriptive title — hence the width being ample.
    cases = [
        ("it_cnel_code", "H011"),
        ("it_cnel_level", "LIVELLO_1"),
        ("it_worker_class", "IMPRENDITORE"),
        ("it_contract_type", "DIPENDENTE"),
        ("it_contributory_cap_cohort", "DIRIGENTE"),
        ("it_tfr_destination", "FONDO_PENSIONE"),
        ("it_pension_fund", "FONDOMETROPOLITANO"),
        ("it_tax_domicile_comune", "SANT'AGATA_DE'GOTI"),
        ("it_tax_domicile_region", "Lombardia"),
        ("it_termination_reason", "DIMISSIONI_VOLONTARIE"),
    ]
    for name, sample in cases:
        limit = _length_of(from_model[name])
        assert limit is not None, f"{name} is not a String column"
        assert len(sample) <= limit, (
            f"{name} is String({limit}) and cannot hold {sample!r} "
            f"({len(sample)} chars)")


def test_employer_and_outbox_widths_fit_real_values():
    cases = [
        (EmployerItalyProfile, "matricola_inps", "0123456789"),
        (EmployerItalyProfile, "csc_code", "1011"),
        (EmployerItalyProfile, "ca_code", "AA1H"),
        (EmployerItalyProfile, "ateco_code", "4711D"),
        (EmployerItalyProfile, "inps_office", "MILANO-LEGNANO-COMO"),
        (EmployerItalyProfile, "cnel_code", "H011"),
        (EmployerItalyProfile, "readiness_status", "NOT_READY"),
        (ItalyFilingOutboxItem, "action", "UNIEMENS_TRANSMIT"),
        (ItalyFilingOutboxItem, "status", "ACKNOWLEDGED"),
        (ItalyFilingOutboxItem, "period_key", "2026-06-M"),
    ]
    for model, name, sample in cases:
        limit = _length_of(_model_columns(model)[name])
        assert limit is not None, f"{model.__name__}.{name} is not a String column"
        assert len(sample) <= limit, (
            f"{model.__name__}.{name} is String({limit}) and cannot hold "
            f"{sample!r} ({len(sample)} chars)")


# ── 4. unique constraints the filing contract depends on ────────────────────
def test_outbox_idempotency_key_is_unique_in_the_migration(migrated):
    """§16 IT-048: an uncertain transport must never be resent blindly, so the
    key that identifies one filing attempt has to be unique in the DATABASE, not
    only in application code."""
    assert _migrated_columns(migrated, OUTBOX_TABLE)["idempotency_key"]["nullable"] is False
    assert ("idempotency_key",) in _unique_column_sets(migrated, OUTBOX_TABLE), (
        f"idempotency_key is not unique; unique column sets found: "
        f"{_unique_column_sets(migrated, OUTBOX_TABLE)}")


def test_employer_profile_is_one_per_organization(migrated):
    """A second employer row for one organization would make the CSC/CA that
    selects the INPS matrix row ambiguous."""
    assert ("organization_id",) in _unique_column_sets(migrated, EMPLOYER_TABLE), (
        f"organization_id is not unique; unique column sets found: "
        f"{_unique_column_sets(migrated, EMPLOYER_TABLE)}")


# ── 5. revision wiring ───────────────────────────────────────────────────────
def test_revision_is_a_single_head_on_top_of_sweden():
    """The migration must chain onto the Sweden head so a deployed database has a
    single linear history. A typo in down_revision silently creates a second
    head, and `alembic upgrade head` then fails at deploy time."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from pathlib import Path

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_current_head() == MIGRATION_REVISION
    revision = script.get_revision(MIGRATION_REVISION)
    assert revision.down_revision == MIGRATION_PARENT


# ── 6. downgrade restores the pre-migration shape ─────────────────────────────
def test_downgrade_removes_exactly_what_upgrade_added(migrated):
    """A downgrade that leaves something behind makes the next upgrade fail on
    the idempotency guards, which is how the 2026-09-29 deploy broke."""
    snapshot = _run_migration(["upgrade", "downgrade"])
    assert EMPLOYER_TABLE not in snapshot["tables"]
    assert OUTBOX_TABLE not in snapshot["tables"]
    assert not [n for n in snapshot["columns"][PROFILE_TABLE]
                if n.startswith("it_")]
    assert "it_calculation_snapshot" not in snapshot["columns"][PAYSLIP_TABLE]


def test_upgrade_is_idempotent():
    """Re-running upgrade() against an already-migrated database must be a no-op.
    The production incident this guards is an unmerged branch having already
    applied part of the schema."""
    snapshot = _run_migration(["upgrade", "upgrade"])
    assert EMPLOYER_TABLE in snapshot["tables"]
    assert OUTBOX_TABLE in snapshot["tables"]
    assert sorted(n for n in snapshot["columns"][PROFILE_TABLE]
                  if n.startswith("it_")) == sorted(
        n for n in _model_columns(EmployeeStatutoryProfile) if n.startswith("it_"))
    # Running it a third time must not accumulate duplicates either.
    third = _run_migration(["upgrade", "upgrade", "upgrade"])
    assert sorted(third["columns"][PROFILE_TABLE]) == sorted(
        snapshot["columns"][PROFILE_TABLE])


def test_migration_header_documents_its_own_column_count():
    """The revision was shipped describing 17 employee columns when it adds 15.
    The docstring is the only description a future migration author reads."""
    source = _load_migration().__doc__ or ""
    match = re.search(r"(\d+)\s+(?:nullable\s+)?EmployeeStatutoryProfile\s+columns",
                      source)
    if match:
        assert int(match.group(1)) == 15, (
            f"docstring claims {match.group(1)} columns; the migration adds 15")
