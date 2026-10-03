"""Italy P2 ledgers schema contract — migration 917a54ed2347 vs the ORM.

Same doctrine as tests/test_italy_schema_contract.py: the migration is executed
for real against in-memory SQLite and its result is compared, column by
column, with app/modules/payroll/models.py, so the two declarations of the
schema cannot drift apart silently. Nothing here touches a configured
database: alembic/env.py is never loaded.
"""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.modules.payroll.engine.countries import italy_content
from app.modules.payroll.models import (
    EmployeeStatutoryProfile,
    ItalyCcnlLevelTerms,
    ItalyF24Line,
    ItalyLulEntry,
    ItalyTfrLedgerEntry,
    PayrollYtdAccumulator,
)

REVISION = "917a54ed2347"
PARENT = "7a1b2c3d4e5f"
BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = next((BACKEND_ROOT / "alembic" / "versions").glob(f"{REVISION}_*.py"))
PROFILE_TABLE = "payroll_employee_statutory_profiles"
NEW_TABLES = {
    "payroll_it_ccnl_level_terms": ItalyCcnlLevelTerms,
    "payroll_it_tfr_ledger_entries": ItalyTfrLedgerEntry,
    "payroll_it_f24_lines": ItalyF24Line,
    "payroll_it_lul_entries": ItalyLulEntry,
}
# Tables the new ones reference; pre-created bare, as earlier migrations leave them.
PARENTS = ("organizations", "users", "payroll_employees", "payroll_runs", "payslip_items",
           "statutory_filings", "payroll_source_artifacts", "payroll_collective_agreements",
           PROFILE_TABLE)


def _load():
    spec = importlib.util.spec_from_file_location("italy_ledgers_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(steps):
    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        connection.begin()
        for table in PARENTS:
            connection.execute(sa.text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
        module = _load()
        original = module.op
        module.op = Operations(MigrationContext.configure(connection))
        try:
            for step in steps:
                getattr(module, step)()
        finally:
            module.op = original
        inspector = sa.inspect(connection)
        tables = set(inspector.get_table_names())
        return {
            "tables": tables,
            "columns": {t: {c["name"]: c for c in inspector.get_columns(t)} for t in tables},
            "uniques": {t: {tuple(u["column_names"]) for u in inspector.get_unique_constraints(t)}
                        | {tuple(i["column_names"]) for i in inspector.get_indexes(t) if i.get("unique")}
                        for t in tables},
        }


@pytest.fixture(scope="module")
def migrated():
    return _run(["upgrade"])


@pytest.mark.parametrize("table,model", NEW_TABLES.items())
def test_new_table_matches_the_model_column_for_column(migrated, table, model):
    got = migrated["columns"][table]
    want = {c.name: c for c in model.__table__.columns}
    assert set(got) == set(want), f"{table}: migration and model columns differ"
    for name, column in want.items():
        assert bool(got[name]["nullable"]) == bool(column.nullable), f"{table}.{name} nullability"
        length = getattr(column.type, "length", None)
        if length is not None:
            assert getattr(got[name]["type"], "length", None) == length, f"{table}.{name} width"


def test_the_profile_column_matches_the_model(migrated):
    assert "it_contractual_weekly_hours" in migrated["columns"][PROFILE_TABLE]
    assert "it_contractual_weekly_hours" in EmployeeStatutoryProfile.__table__.columns
    assert migrated["columns"][PROFILE_TABLE]["it_contractual_weekly_hours"]["nullable"]


def test_uniqueness_that_makes_the_ledgers_safe_is_in_the_migration(migrated):
    # One accrual per idempotency key; one LUL sequence number per employer;
    # one terms row per level and renewal date.
    assert ("idempotency_key",) in migrated["uniques"]["payroll_it_tfr_ledger_entries"]
    assert ("organization_id", "sequence_number") in migrated["uniques"]["payroll_it_lul_entries"]
    assert ("collective_agreement_id", "level_code", "effective_from") in \
        migrated["uniques"]["payroll_it_ccnl_level_terms"]


def test_upgrade_twice_is_a_no_op():
    """The 2026-09-29 deploy failed on a table that already existed."""
    once, twice = _run(["upgrade"]), _run(["upgrade", "upgrade"])
    assert once["tables"] == twice["tables"]
    assert once["columns"][PROFILE_TABLE].keys() == twice["columns"][PROFILE_TABLE].keys()


def test_downgrade_removes_exactly_what_upgrade_added():
    snapshot = _run(["upgrade", "downgrade"])
    assert not NEW_TABLES.keys() & snapshot["tables"]
    assert "it_contractual_weekly_hours" not in snapshot["columns"][PROFILE_TABLE]


def test_revision_chains_onto_the_italy_engine_migration():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(BACKEND_ROOT / "alembic.ini")))
    assert script.get_revision(REVISION).down_revision == PARENT
    assert REVISION in script.get_heads()


def test_ytd_component_names_fit_the_generic_accumulator():
    width = PayrollYtdAccumulator.__table__.columns["tax_component"].type.length
    assert all(len(key) <= width for key in italy_content.IT_YTD_COMPONENTS)


def test_inail_component_code_fits_the_employer_tax_profile():
    from app.modules.payroll.models import EmployerTaxProfile

    width = EmployerTaxProfile.__table__.columns["component_code"].type.length
    # INAIL voci di tariffa are four digits.
    assert len(italy_content.IT_INAIL_COMPONENT_PREFIX + "0722") <= width


def test_ccnl_level_terms_fit_the_employee_profile_codes():
    """A level code / worker category copied from the profile must never be
    truncated by the terms table, or the lookup silently misses."""
    profile = EmployeeStatutoryProfile.__table__.columns
    terms = ItalyCcnlLevelTerms.__table__.columns
    assert terms["level_code"].type.length >= profile["it_cnel_level"].type.length
    assert terms["worker_category"].type.length >= profile["it_worker_class"].type.length
