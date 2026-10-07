"""Italy 3A F24 causale catalog schema contract — migration c9d8e7f6a5b4.

Same doctrine as tests/test_italy_ledgers_schema_contract.py: the migration is
executed for real against in-memory SQLite and its result is compared, column by
column, with app/modules/payroll/models.py, so the two declarations of the
schema cannot drift apart silently. Nothing here touches a configured database:
alembic/env.py is never loaded.

The distinctive assertion is the negative one. This migration must not ship any
F24 causale. IT-046 requires a real "codice tributo" on every line and IT-043
forbids inventing one, so a test that pins "the catalog creates empty" is the
mechanical guarantee that nobody quietly seeds a plausible-looking guess.
"""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.modules.payroll.models import ItalyF24Causale, ItalyF24Line

REVISION = "c9d8e7f6a5b4"
PARENT = "917a54ed2347"
BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = next((BACKEND_ROOT / "alembic" / "versions").glob(f"{REVISION}_*.py"))
CAUSALE_TABLE = "payroll_it_f24_causales"
LINE_TABLE = "payroll_it_f24_lines"
LINE_UNIQUE_COLUMNS = ("organization_id", "payroll_run_id", "section", "tax_code",
                       "region_code", "comune_code", "reference_period")

# Tables the migration references; pre-created bare, as earlier migrations leave
# them. payroll_it_f24_lines is NOT bare - the migration adds a unique
# constraint to it, so it needs its real columns.
PARENTS = ("organizations", "users", "payroll_source_artifacts",
           "statutory_filings", "payroll_runs", "payroll_employees", "payslip_items")


def _load():
    spec = importlib.util.spec_from_file_location("italy_f24_causale_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_f24_lines(connection):
    # Exactly the shape 917a54ed2347 leaves behind.
    model = ItalyF24Line.__table__
    model.create(connection, checkfirst=True)


def _run(steps):
    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        connection.begin()
        for table in PARENTS:
            connection.execute(sa.text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
        _create_f24_lines(connection)
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
        rows = {}
        if CAUSALE_TABLE in tables:
            rows[CAUSALE_TABLE] = connection.execute(
                sa.text(f"SELECT * FROM {CAUSALE_TABLE}")).fetchall()
        return {
            "tables": tables,
            "columns": {t: {c["name"]: c for c in inspector.get_columns(t)} for t in tables},
            "uniques": {t: {tuple(u["column_names"]) for u in inspector.get_unique_constraints(t)}
                        | {tuple(i["column_names"]) for i in inspector.get_indexes(t) if i.get("unique")}
                        for t in tables},
            "rows": rows,
        }


@pytest.fixture(scope="module")
def migrated():
    return _run(["upgrade"])


def test_new_table_matches_the_model_column_for_column(migrated):
    got = migrated["columns"][CAUSALE_TABLE]
    want = {c.name: c for c in ItalyF24Causale.__table__.columns}
    assert set(got) == set(want), "migration and model columns differ"
    for name, column in want.items():
        assert bool(got[name]["nullable"]) == bool(column.nullable), f"{name} nullability"
        length = getattr(column.type, "length", None)
        if length is not None:
            assert getattr(got[name]["type"], "length", None) == length, f"{name} width"


def test_the_causale_catalog_ships_empty(migrated):
    """IT-043: a causale is a legal code from the Agenzia delle Entrate catalog.

    If this assertion ever fails, someone added seed data to the migration. That
    is not a neutral change: an invented causale renders as a real payable
    instruction, and it is unreviewable once it has driven a payment.
    """
    assert migrated["rows"][CAUSALE_TABLE] == []


def test_line_identity_is_unique_so_rebuilds_cannot_double_pay(migrated):
    """IT-044 exists to prevent paying a liability twice.

    Deriving the same period twice from the same committed run must collapse
    onto one line rather than appending a duplicate, which is what this
    constraint enforces.
    """
    assert LINE_UNIQUE_COLUMNS in migrated["uniques"][LINE_TABLE]


def test_upgrade_twice_is_a_no_op():
    """The 2026-09-29 deploy failed on a table that already existed.

    This migration is guarded in both directions (create_table if absent, the
    constraint only if missing), so a re-run against an already-migrated
    database must be silent rather than raising.
    """
    once, twice = _run(["upgrade"]), _run(["upgrade", "upgrade"])
    assert once["tables"] == twice["tables"]
    assert once["uniques"] == twice["uniques"]


def test_downgrade_removes_exactly_what_upgrade_added(migrated):
    snapshot = _run(["upgrade", "downgrade"])
    assert CAUSALE_TABLE not in snapshot["tables"]
    # The F24 lines table itself must survive; only the constraint goes.
    assert LINE_TABLE in snapshot["tables"]
    assert LINE_UNIQUE_COLUMNS not in snapshot["uniques"][LINE_TABLE]
