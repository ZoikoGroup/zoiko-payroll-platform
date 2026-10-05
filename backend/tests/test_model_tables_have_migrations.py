"""
tests/test_model_tables_have_migrations.py
------------------------------------------
Every SQLAlchemy model table must be created by some Alembic migration in
alembic/versions/. Found necessary when the France compliance tables
(payroll_fr_*) shipped in a commit whose migration file was never added to
git: the service tests use `Base.metadata.create_all` on SQLite, so they
passed, while every real environment (where startup create_all is skipped
once a `users` table exists) answered each France request with a missing-
table error.

LEGACY_TABLES_WITHOUT_CREATE_TABLE are the tables that predate this check
and are not created by a literal `op.create_table("<name>")` call; the list
may only shrink. A NEW table must ship with its migration.
"""
import importlib
import pkgutil
import re
from pathlib import Path

LEGACY_TABLES_WITHOUT_CREATE_TABLE = {
    "assisted_access_audit_events",
    "assisted_access_sessions",
    "payroll_employee_pretax_elections",
    "payroll_policy_allowance_components",
    "payroll_tax_configuration_audit",
    "payroll_taxability_rules",
    "payslip_allowance_items",
}

_VERSIONS_DIR = Path(__file__).resolve().parent.parent / "alembic" / "versions"


def _tables_created_by_migrations():
    created = set()
    for path in _VERSIONS_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        created |= set(re.findall(r"create_table\(\s*['\"]([A-Za-z0-9_]+)['\"]", text))
    return created


def _tables_dropped_by_migrations():
    dropped = set()
    for path in _VERSIONS_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        dropped |= set(re.findall(r"drop_table\(\s*['\"]([A-Za-z0-9_]+)['\"]", text))
    return dropped


def _model_tables():
    from app.database import Base
    import app.modules as modules_pkg

    for mod in pkgutil.walk_packages(modules_pkg.__path__, "app.modules."):
        if mod.name.endswith(".models"):
            importlib.import_module(mod.name)
    return set(Base.metadata.tables)


def test_every_model_table_has_a_create_table_migration():
    missing = _model_tables() - _tables_created_by_migrations() - LEGACY_TABLES_WITHOUT_CREATE_TABLE
    assert not missing, (
        "Model tables with no Alembic create_table migration (add a migration "
        f"under alembic/versions/ and commit it): {sorted(missing)}"
    )


def test_france_compliance_tables_are_migrated():
    created = _tables_created_by_migrations()
    for table in (
        "payroll_fr_employer_profiles",
        "payroll_fr_establishment_rate_packs",
        "payroll_fr_pas_rates",
        "payroll_fr_dsn_submissions",
        "payroll_fr_dsn_outbox_items",
    ):
        assert table in created, table


def test_ireland_payroll_tables_are_migrated():
    """Same gap-closure as the France assertion above, for ZP-IE-ENG-001.

    Three Ireland tables survive the 2026-09-28 refactor (7 -> 3) and each must
    still ship with its create_table migration, or every real environment
    answers each Ireland request with a missing-table error while the
    SQLite-backed service tests pass.
    """
    created = _tables_created_by_migrations()
    for table in (
        "payroll_ie_rpn_snapshots",
        "payroll_ie_myfuturefund_statuses",
        "payroll_ie_statutory_sick_leave_records",
    ):
        assert table in created, table


def test_dropped_ireland_tables_are_actually_dropped_by_a_migration():
    """The four removed tables must be dropped by a real Alembic revision.

    This is the counterpart to the assertion above and it matters more than it
    looks. models.py no longer declares these tables, and the service tests
    build their schema with Base.metadata.create_all — so if a refactor
    removed a model but forgot the migration, every test would still pass
    while every already-deployed database kept carrying four dead tables
    forever. Nothing else in the suite can catch that.
    """
    dropped = _tables_dropped_by_migrations()
    for table in (
        "payroll_ie_employer_profiles",
        "payroll_ie_revenue_submissions",
        "payroll_ie_revenue_monthly_returns",
        "payroll_ie_ytd_accumulators",
    ):
        assert table in dropped, (
            f"{table} has no drop_table migration: the model is gone but a real "
            f"database would still be carrying the table"
        )


def test_dropped_ireland_tables_are_not_still_declared_as_models():
    """Belt and braces: a dropped table must not reappear as a model."""
    live = _model_tables()
    for table in (
        "payroll_ie_employer_profiles",
        "payroll_ie_revenue_submissions",
        "payroll_ie_revenue_monthly_returns",
        "payroll_ie_ytd_accumulators",
    ):
        assert table not in live, f"{table} is dropped but is still a declared model"


def test_ireland_statutory_profile_columns_are_migrated():
    """EmployeeIrelandProfile is an Ireland block of columns on the existing
    effective-dated payroll_employee_statutory_profiles table (that table
    already provides the per-country effective dating §12 needs), so the
    parity check is an add_column rather than a create_table."""
    versions = _VERSIONS_DIR / "b1c2d3e4f5a6_add_ireland_payroll_tables.py"
    text = versions.read_text(encoding="utf-8", errors="ignore")
    for column in (
        "ie_ppsn",
        "ie_employer_reference",
        "ie_revenue_employment_id",
        "ie_prsi_class",
        "ie_prsi_exemption_reference",
        "ie_usc_status",
        "ie_pension_scheme_reference",
        "ie_pension_qualifying_exemption_reference",
        "ie_pension_qualifying_exemption_effective_from",
        "ie_contracted_weekly_hours",
        "ie_sector_wage_order",
        "ie_emergency_reason",
        "ie_emergency_week",
    ):
        assert f"add_column('payroll_employee_statutory_profiles'" in text
        assert f"sa.Column('{column}'" in text, column
        # Also present in downgrade, so the migration is genuinely reversible.
        assert text.count(f"sa.Column('{column}'") >= 1
        assert f"drop_column('payroll_employee_statutory_profiles', '{column}')" in text, column


def test_ireland_migration_is_additive_and_reversible():
    """The migration must not alter, drop or retype any pre-existing
    column/table: it only creates new tables and adds nullable columns, so
    it is backward compatible for every other jurisdiction. And every
    created table must be dropped again in downgrade()."""
    text = (
        _VERSIONS_DIR / "b1c2d3e4f5a6_add_ireland_payroll_tables.py"
    ).read_text(encoding="utf-8", errors="ignore")
    assert "op.drop_column(" not in text.split("def downgrade")[0]
    assert "op.alter_column(" not in text
    assert "op.drop_table(" not in text.split("def downgrade")[0]
    for table in (
        "payroll_ie_employer_profiles",
        "payroll_ie_rpn_snapshots",
        "payroll_ie_myfuturefund_statuses",
        "payroll_ie_ytd_accumulators",
        "payroll_ie_revenue_submissions",
        "payroll_ie_revenue_monthly_returns",
    ):
        assert f"drop_table('{table}')" in text, table
