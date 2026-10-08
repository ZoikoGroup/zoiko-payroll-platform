"""Switzerland schema contract (CH) — migration 3baddbaa011a vs the ORM.

The migration and app/modules/payroll/models.py are two separate declarations of
the same schema, and this codebase has been burned by them drifting: a column
added to the model but not the migration exists in the developer's SQLite (fresh
databases go through Base.metadata.create_all) and is missing in production
(migrated databases go through Alembic). The failure is silent until the code
path that reads the column runs against a real migrated database.

So this module INTROSPECTs both sides and compares them, rather than restating
either as a literal. The migration is executed for real against an in-memory
SQLite connection — not parsed as text — so the columns being compared are the
ones the migration genuinely creates. The full-metadata test at the bottom runs
the complete lifecycle the CH data model is deployed under: create_all (fresh
dev database) -> stamp the previous head -> upgrade this revision -> downgrade,
all against in-memory SQLite only.
"""
import importlib.util
import re
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.modules.payroll.models import (
    ChAbsenceBenefitEvent,
    ChElmSubmission,
    ChEntityProfile,
    ChFamilyAllowanceEntitlement,
    ChQstTariffFile,
    ChQstTariffRow,
    ChSchemeProfile,
    CollectiveAgreement,
    EmployeeStatutoryProfile,
    PayslipItem,
    TaxabilityRule,
)

MIGRATION_FILENAME = "3baddbaa011a_add_switzerland_jurisdiction_support.py"
MIGRATION_REVISION = "3baddbaa011a"
MIGRATION_PARENT = "d7e6f5a4b3c2"
BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = BACKEND_ROOT / "alembic" / "versions" / MIGRATION_FILENAME

PROFILE_TABLE = "payroll_employee_statutory_profiles"
AGREEMENT_TABLE = "payroll_collective_agreements"
TAXABILITY_TABLE = "payroll_taxability_rules"
PAYSLIP_TABLE = "payslip_items"

# The seven tables this revision alone creates. All model tables must exist in a
# migration verbatim (test_model_tables_have_migrations enforces it textually);
# this module checks the SHAPE of the real migration output against the ORM.
EXPECTED_CH_TABLES = {
    "payroll_ch_scheme_profiles",
    "payroll_ch_entity_profiles",
    "payroll_ch_qst_tariff_files",
    "payroll_ch_qst_tariff_rows",
    "payroll_ch_family_allowance_entitlements",
    "payroll_ch_absence_benefit_events",
    "payroll_ch_elm_submissions",
}

# Columns the model declares that were added by revisions AFTER this one, so
# this module can compare the model against what THIS migration creates.
# CH Step 14 added ChElmSubmission.payload_xml (revision 6b5a4c3d2e1f).
LATER_REVISION_COLUMNS = {"payload_xml"}

# The four ALTERed tables, bare, as the baseline leaves them. The migration's
# ADD COLUMN statements need these to attach to.
ALTERED_TABLES = (
    f"CREATE TABLE {PROFILE_TABLE} (id INTEGER PRIMARY KEY)",
    f"CREATE TABLE {AGREEMENT_TABLE} (id INTEGER PRIMARY KEY)",
    f"CREATE TABLE {TAXABILITY_TABLE} (id INTEGER PRIMARY KEY)",
    f"CREATE TABLE {PAYSLIP_TABLE} (id INTEGER PRIMARY KEY)",
    "CREATE TABLE organizations (id INTEGER PRIMARY KEY)",
    "CREATE TABLE users (id INTEGER PRIMARY KEY)",
    "CREATE TABLE payroll_employees (id INTEGER PRIMARY KEY)",
    "CREATE TABLE payroll_source_artifacts (id INTEGER PRIMARY KEY)",
    "CREATE TABLE statutory_filings (id INTEGER PRIMARY KEY)",
)


def _load_migration():
    """Load the revision file by path. It cannot be imported as
    alembic.versions.<name> because `alembic` resolves to the installed package,
    not this project's migrations directory."""
    spec = importlib.util.spec_from_file_location(
        "switzerland_migration_under_test", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_migration(steps):
    """Execute the migration's given steps against a real in-memory SQLite
    database and return a plain-dict snapshot of the resulting schema.

    The ALTERed tables are pre-created with a bare id so their ADD COLUMN
    statements have something to attach to, which is what the baseline migration
    leaves behind.

    The schema is copied into plain dicts rather than returning the Inspector,
    because an Inspector is bound to a live connection and the caller needs the
    schema after the connection has been released.
    """
    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        connection.begin()
        for statement in ALTERED_TABLES:
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


def _assert_columns_match(from_migration, from_model, context):
    assert set(from_model) - set(from_migration) == set(), (
        f"{context}: model declares columns the migration never creates: "
        f"{sorted(set(from_model) - set(from_migration))}")
    assert set(from_migration) - set(from_model) == set(), (
        f"{context}: migration has columns the model does not declare: "
        f"{sorted(set(from_migration) - set(from_model))}")

    for name, column in from_model.items():
        migrated_column = from_migration[name]
        assert str(_type_of(column)) == str(_type_of(migrated_column)), (
            f"{context}.{name}: model {_type_of(column)} vs migration "
            f"{_type_of(migrated_column)}")
        assert _nullable_of(column) == _nullable_of(migrated_column), (
            f"{context}.{name} nullability differs between model and migration")
        assert _length_of(column) == _length_of(migrated_column), (
            f"{context}.{name} length differs between model and migration")


# ── 1. the seven new tables ──────────────────────────────────────────────────
@pytest.mark.parametrize("table,model", [
    ("payroll_ch_scheme_profiles", ChSchemeProfile),
    ("payroll_ch_entity_profiles", ChEntityProfile),
    ("payroll_ch_qst_tariff_files", ChQstTariffFile),
    ("payroll_ch_qst_tariff_rows", ChQstTariffRow),
    ("payroll_ch_family_allowance_entitlements", ChFamilyAllowanceEntitlement),
    ("payroll_ch_absence_benefit_events", ChAbsenceBenefitEvent),
    ("payroll_ch_elm_submissions", ChElmSubmission),
])
def test_new_table_matches_the_model_column_for_column(migrated, table, model):
    """Every column the model declares must exist in the migrated table with the
    same type and nullability. A missing column is the create_all-vs-Alembic
    split; a wrong length is a PostgreSQL truncation waiting to happen."""
    from_model = {n: c for n, c in _model_columns(model).items()
                  if n not in LATER_REVISION_COLUMNS}
    _assert_columns_match(
        _migrated_columns(migrated, table), from_model, model.__name__)


def test_migration_adds_exactly_the_declared_ch_tables(migrated):
    """Guards the opposite direction: a stray table in the migration would be
    created in production and never in a fresh dev database."""
    tables = migrated["tables"]
    assert EXPECTED_CH_TABLES <= tables
    assert not [t for t in tables if t.startswith("payroll_ch_")
                and t not in EXPECTED_CH_TABLES]


# ── 2. the ALTERed tables ────────────────────────────────────────────────────
def test_employee_profile_ch_additions_match_the_model(migrated):
    """The 29 worker-owned ch_* facts. This is the comparison the create_all /
    Alembic split actually breaks: a fresh dev database gets these from the model
    and a migrated one from this revision."""
    from_migration = _migrated_columns(migrated, PROFILE_TABLE)
    from_model = _model_columns(EmployeeStatutoryProfile)

    ch_in_migration = {n for n in from_migration if n.startswith("ch_")}
    ch_in_model = {n for n in from_model if n.startswith("ch_")} - LATER_REVISION_COLUMNS

    assert ch_in_model == ch_in_migration
    assert len(ch_in_model) == 29, (
        f"expected the 29 ch_* facts, found {sorted(ch_in_model)}")

    for name in sorted(ch_in_model):
        _assert_columns_match(
            {name: from_migration[name]}, {name: from_model[name]}, PROFILE_TABLE)


def test_collective_agreement_jurisdiction_state_matches_the_model(migrated):
    from_migration = _migrated_columns(migrated, AGREEMENT_TABLE)
    column = _model_columns(CollectiveAgreement)["jurisdiction_state"]
    assert "jurisdiction_state" in from_migration
    assert str(_type_of(column)) == str(_type_of(from_migration["jurisdiction_state"]))
    assert _nullable_of(column) is True
    assert _length_of(column) == 100


def test_taxability_rule_additions_match_the_model(migrated):
    """The approval-gated lifecycle columns (choice of words in the spec:
    treatment / status / source_document_id / approved_by_id / created_by_id)."""
    from_migration = _migrated_columns(migrated, TAXABILITY_TABLE)
    from_model = _model_columns(TaxabilityRule)

    additions = {"treatment", "status", "source_document_id", "approved_by_id", "created_by_id"}
    assert additions <= set(from_migration)
    for name in sorted(additions):
        _assert_columns_match(
            {name: from_migration[name]}, {name: from_model[name]}, TAXABILITY_TABLE)


def test_payslip_snapshot_column_matches_the_model(migrated):
    from_migration = _migrated_columns(migrated, PAYSLIP_TABLE)
    assert "ch_calculation_snapshot" in from_migration
    column = _model_columns(PayslipItem)["ch_calculation_snapshot"]
    assert str(_type_of(column)) == str(_type_of(from_migration["ch_calculation_snapshot"]))
    assert _nullable_of(column) is True


def test_no_ch_column_is_created_with_a_non_nullable_constraint(migrated):
    """Every worker-owned fact is optional. A ch_* column that cannot be null
    would lock every non-Swiss employee's row out of the table, so the
    constraint is asserted rather than assumed."""
    for name, column in _migrated_columns(migrated, PROFILE_TABLE).items():
        if name.startswith("ch_"):
            assert column["nullable"] is True, f"{name} is NOT NULL"


# ── 3. column widths, asserted against real Swiss values ─────────────────────
def test_string_column_widths_fit_real_swiss_values():
    """Every ch_* String is sized for a real value that must fit, read from the
    model rather than hardcoded so the guard works if a width is ever
    corrected."""
    from_model = _model_columns(EmployeeStatutoryProfile)

    cases = [
        ("ch_work_canton", "ZH"),
        ("ch_residence_canton", "GR"),
        ("ch_qst_canton", "LU"),
        ("ch_residence_country", "AT"),
        ("ch_nationality", "FR"),
        ("ch_permit_type", "L"),
        ("ch_ahv_number", "756.1234.5678.97"),
        ("ch_ahv_status", "DECEASED"),
        ("ch_qst_subject", "REVIEW_REQUIRED"),
        ("ch_qst_tariff_code", "T1"),
        ("ch_marital_status", "MARRIED"),
        ("ch_uvg_risk_class", "RISK_CLASS_40"),
        ("ch_occupation", "SOFTWARE_ENGINEER"),
        ("ch_grade", "SENIOR"),
    ]
    for name, sample in cases:
        limit = _length_of(from_model[name])
        assert limit is not None, f"{name} is not a String column"
        assert len(sample) <= limit, (
            f"{name} is String({limit}) and cannot hold {sample!r} "
            f"({len(sample)} chars)")


# ── 4. unique constraints the CH schema depends on ──────────────────────────
def test_scheme_profile_is_unique_per_scope_and_version(migrated):
    """One (org-or-catalog, scheme_type, scheme_code) may have any number of
    VERSIONS but never two rows claiming the same version."""
    assert ("organization_id", "scheme_type", "scheme_code", "version") in \
        _unique_column_sets(migrated, "payroll_ch_scheme_profiles")


def test_entity_profile_is_one_per_organization(migrated):
    """What 3baddbaa011a itself creates. NOTE: 376bb8637603 (CH Step 5)
    replaces this with UNIQUE (organization_id, effective_from) — the profile
    is versioned, and the service keeps versions non-overlapping so the
    compensation office / FAK assignment is still unambiguous on any date
    (see test_switzerland_api.py's migration tests)."""
    assert ("organization_id",) in _unique_column_sets(migrated, "payroll_ch_entity_profiles")


def test_qst_tariff_file_is_unique_per_canton_and_sha(migrated):
    """Re-importing the same file bytes is an idempotent no-op, never a second
    row."""
    assert ("canton", "file_sha256") in \
        _unique_column_sets(migrated, "payroll_ch_qst_tariff_files")


def test_elm_idempotency_key_is_unique_in_the_migration(migrated):
    """An uncertain ELM transport must never be resent blindly, so the key that
    identifies one submission has to be unique in the DATABASE, not only in
    application code."""
    table = "payroll_ch_elm_submissions"
    assert _migrated_columns(migrated, table)["idempotency_key"]["nullable"] is False
    assert ("idempotency_key",) in _unique_column_sets(migrated, table), (
        f"idempotency_key is not unique; unique column sets found: "
        f"{_unique_column_sets(migrated, table)}")


# ── 5. revision wiring ───────────────────────────────────────────────────────
def test_revision_is_a_single_head_on_top_of_italy_lul():
    """The migration must chain onto the Italy LUL head so a deployed database
    has a single linear history. A typo in down_revision silently creates a
    second head, and `alembic upgrade head` then fails at deploy time."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(MIGRATION_REVISION)
    assert revision.down_revision == MIGRATION_PARENT
    assert len(script.get_heads()) == 1


# ── 6. downgrade restores the pre-migration shape ────────────────────────────
def test_downgrade_removes_exactly_what_upgrade_added(migrated):
    """A downgrade that leaves something behind makes the next upgrade fail on
    the idempotency guards, which is how the 2026-09-29 deploy broke."""
    snapshot = _run_migration(["upgrade", "downgrade"])
    assert not [t for t in EXPECTED_CH_TABLES if t in snapshot["tables"]]
    assert not [n for n in snapshot["columns"][PROFILE_TABLE] if n.startswith("ch_")]
    assert not [n for n in snapshot["columns"][TAXABILITY_TABLE]
                if n in ("treatment", "status", "source_document_id", "approved_by_id", "created_by_id")]
    assert "jurisdiction_state" not in snapshot["columns"][AGREEMENT_TABLE]
    assert "ch_calculation_snapshot" not in snapshot["columns"][PAYSLIP_TABLE]


def test_upgrade_is_idempotent():
    """Re-running upgrade() against an already-migrated database must be a no-op.
    The production incident this guards is an unmerged branch having already
    applied part of the schema."""
    snapshot = _run_migration(["upgrade", "upgrade"])
    assert EXPECTED_CH_TABLES <= snapshot["tables"]
    assert sorted(n for n in snapshot["columns"][PROFILE_TABLE]
                  if n.startswith("ch_")) == sorted(
        n for n in _model_columns(EmployeeStatutoryProfile)
        if n.startswith("ch_") and n not in LATER_REVISION_COLUMNS)
    # Running it a third time must not accumulate duplicates either.
    third = _run_migration(["upgrade", "upgrade", "upgrade"])
    assert sorted(third["columns"][PROFILE_TABLE]) == sorted(
        snapshot["columns"][PROFILE_TABLE])


def test_full_metadata_create_all_then_stamp_then_upgrade_then_downgrade():
    """The full deployment lifecycle, in-memory SQLite only: a fresh dev
    database (Base.metadata.create_all), stamped at the previous head, upgraded
    through this revision, then downgraded. Guards must make the upgrade a no-op
    on a database create_all already brought fully to the new shape, and the
    downgrade must remove only this revision's objects, leaving the pre-existing
    columns intact."""
    from app.database import Base

    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with engine.connect() as connection:
        connection.begin()
        connection.execute(sa.text(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(
            sa.text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
            {"v": MIGRATION_PARENT})

        module = _load_migration()
        context = MigrationContext.configure(connection)
        original_op = module.op
        module.op = Operations(context)
        try:
            module.upgrade()
            # The upgrade on a create_all'd database is entirely guarded — no
            # object may be duplicated or altered.
            module.downgrade()
        finally:
            module.op = original_op

        inspector = sa.inspect(connection)
        tables = set(inspector.get_table_names())
        columns = {c["name"] for c in inspector.get_columns(PROFILE_TABLE)}

    assert not (EXPECTED_CH_TABLES & tables)
    assert not any(n.startswith("ch_") for n in columns)
    # Pre-existing employee-profile columns survive the downgrade untouched —
    # the batch rebuild must not drop anything it did not add.
    assert {"id", "employee_id", "country_code", "it_termination_reason"} <= columns
    for table_name in (AGREEMENT_TABLE, TAXABILITY_TABLE, PAYSLIP_TABLE):
        assert table_name in tables


def test_migration_header_documents_its_own_column_count():
    """The revision docstring must stay honest about how many employee ch_*
    columns it adds — it is the only description a future migration author
    reads."""
    source = _load_migration().__doc__ or ""
    match = re.search(r"(\d+)\s+nullable\s+ch_\*\s+columns", source)
    if match:
        assert int(match.group(1)) == 29, (
            f"docstring claims {match.group(1)} ch_* columns; the migration "
            f"adds 29")