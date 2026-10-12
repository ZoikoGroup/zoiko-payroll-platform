"""tests/test_ie_ytd_accumulator_merge_migration.py
--------------------------------------------------
ZP-IE-ENG-001, 2026-09-28. Executable proof that merging
payroll_ie_ytd_accumulators into payroll_ytd_accumulators moves every
cumulative figure without losing, rounding or reinterpreting any of it, in
BOTH directions.

Why this file exists at all: this is the only place the refactor's actual data
movement is verified. The service tests build their schema with
Base.metadata.create_all, so they can only ever see the schema as the models
describe it — and after the refactor the models describe only the *destination*.
Nothing else in the suite would notice if the migration copied the wrong column
into the wrong half of the generic pair, dropped a row, or "helpfully" dropped
a second time and destroyed live figures. A five-way fan-out with a reversible
downgrade is exactly the shape of migration that rots silently, so it gets a
test that drives the real migration modules against a real database.

The full revision chain cannot be applied here: the baseline revision
(0b624a4a7481) uses op.create_foreign_key, which the SQLite dialect rejects
outright. So the schema the migrations actually touch is built directly — the
generic table from real model metadata, the legacy Ireland table from the
verbatim DDL of b1c2d3e4f5a6 — and the two new migration modules are driven
through a genuine Alembic Operations context. That exercises the migration SQL
itself, which is the part with no other coverage.
"""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_VERSIONS_DIR = _BACKEND_ROOT / "alembic" / "versions"

_DROP_DEAD = _VERSIONS_DIR / "f6b2c4d8e1a3_drop_dead_ireland_tables.py"
_MERGE_IE = _VERSIONS_DIR / "2c7d9e0f3a5b_merge_ie_ytd_into_generic_accumulator.py"

# Verbatim column shape from b1c2d3e4f5a6 (CURRENT_TIMESTAMP rather than now(),
# which the SQLite dialect has no such function for; the column is not asserted
# on and is never written by the merge).
_LEGACY_IE_DDL = """
CREATE TABLE payroll_ie_ytd_accumulators (
    id INTEGER NOT NULL PRIMARY KEY,
    organization_id INTEGER NOT NULL,
    employee_id INTEGER NOT NULL,
    tax_year VARCHAR(10) NOT NULL,
    usc_payable_ytd NUMERIC(14, 2) NOT NULL DEFAULT '0',
    usc_paid_ytd NUMERIC(14, 2) NOT NULL DEFAULT '0',
    prsi_reckonable_ytd NUMERIC(14, 2) NOT NULL DEFAULT '0',
    prsi_contribution_weeks_ytd NUMERIC(8, 3) NOT NULL DEFAULT '0',
    mff_earnings_ytd_before NUMERIC(14, 2) NOT NULL DEFAULT '0',
    mff_threshold_crossed_at_pay_date DATE,
    last_payslip_id INTEGER,
    updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (employee_id, tax_year)
)"""

_DEAD_TABLES = (
    "payroll_ie_employer_profiles",
    "payroll_ie_revenue_submissions",
    "payroll_ie_revenue_monthly_returns",
)

# The legacy row, and the component rows it must become.
_LEGACY_ROW = {
    "organization_id": 1,
    "employee_id": 1,
    "tax_year": "2026",
    "usc_payable_ytd": 41234.56,
    "usc_paid_ytd": 12345.67,
    "prsi_reckonable_ytd": 38900.11,
    "prsi_contribution_weeks_ytd": 17,
    "mff_earnings_ytd_before": 75000.25,
    "mff_threshold_crossed_at_pay_date": "2026-07-04",
    "last_payslip_id": 900,
}

_EXPECTED_COMPONENTS = {
    "ie_usc_payable": (41234.56, 0, 900),
    "ie_usc_paid": (0, 12345.67, 900),
    "ie_prsi_reckonable": (38900.11, 0, 900),
    "ie_prsi_weeks": (0, 17, 900),
    "ie_mff_earnings": (75000.25, 0, 900),
}

_DROPPED = _DEAD_TABLES + ("payroll_ie_ytd_accumulators",)


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(fn, engine):
    """Call fn() with the migration's module-level `op` proxy bound to engine."""
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            fn()


@pytest.fixture
def legacy_db():
    """A database in the pre-refactor state: the legacy Ireland table with one
    fully-populated row, the three empty dead tables, and a pre-existing
    non-Ireland accumulator row that the merge must not touch."""
    from app.modules.payroll.models import PayrollYtdAccumulator

    engine = sa.create_engine("sqlite://")
    with engine.begin() as c:
        c.execute(sa.text(_LEGACY_IE_DDL))
        c.execute(sa.text(
            "CREATE INDEX ix_ie_ytd_org_employee ON payroll_ie_ytd_accumulators "
            "(organization_id, employee_id)"
        ))
        for table in _DEAD_TABLES:
            c.execute(sa.text("CREATE TABLE %s (id INTEGER NOT NULL PRIMARY KEY)" % table))
        PayrollYtdAccumulator.__table__.create(c)
        c.execute(sa.text("CREATE TABLE organizations (id INTEGER NOT NULL PRIMARY KEY)"))
        c.execute(sa.text(
            "CREATE TABLE payroll_employees (id INTEGER NOT NULL PRIMARY KEY, "
            "organization_id INTEGER NOT NULL)"
        ))
        c.execute(sa.text("CREATE TABLE payslip_items (id INTEGER NOT NULL PRIMARY KEY)"))
        c.execute(sa.text("INSERT INTO organizations (id) VALUES (1)"))
        c.execute(sa.text("INSERT INTO payroll_employees (id, organization_id) VALUES (1, 1)"))
        c.execute(sa.text("INSERT INTO payslip_items (id) VALUES (900)"))
        c.execute(sa.text(
            "INSERT INTO payroll_ie_ytd_accumulators (organization_id, employee_id, tax_year, "
            "usc_payable_ytd, usc_paid_ytd, prsi_reckonable_ytd, "
            "prsi_contribution_weeks_ytd, mff_earnings_ytd_before, "
            "mff_threshold_crossed_at_pay_date, last_payslip_id) VALUES "
            "(1, 1, '2026', 41234.56, 12345.67, 38900.11, 17, 75000.25, '2026-07-04', 900)"
        ))
        # A UK accumulator row: the merge must neither read nor delete it.
        c.execute(sa.text(
            "INSERT INTO payroll_ytd_accumulators (employee_id, tax_year, tax_component, "
            "ytd_taxable_wages, ytd_tax_withheld, last_updated_payslip_id) "
            "VALUES (1, 'UK-TY-2025-26', 'student_loan', 1234.00, 0, NULL)"
        ))
    return engine


def test_merge_preserves_every_cumulative_figure(legacy_db):
    _run(_load(_MERGE_IE, "mig_merge").upgrade, legacy_db)

    with legacy_db.connect() as c:
        rows = c.execute(sa.text(
            "SELECT tax_component, ytd_taxable_wages, ytd_tax_withheld, "
            "last_updated_payslip_id FROM payroll_ytd_accumulators "
            "WHERE employee_id = 1 AND tax_year = '2026'"
        )).all()

    got = {r[0]: (r[1], r[2], r[3]) for r in rows}
    assert got == _EXPECTED_COMPONENTS, (
        "every Ireland figure must land in the right half of the generic pair; "
        f"got {got}"
    )


def test_merge_drops_the_legacy_table_and_leaves_other_countries_alone(legacy_db):
    _run(_load(_MERGE_IE, "mig_merge").upgrade, legacy_db)

    assert "payroll_ie_ytd_accumulators" not in set(sa.inspect(legacy_db).get_table_names())
    with legacy_db.connect() as c:
        uk = c.execute(sa.text(
            "SELECT ytd_taxable_wages FROM payroll_ytd_accumulators "
            "WHERE tax_component = 'student_loan'"
        )).scalar()
    assert uk == 1234.00, "the merge must not touch another jurisdiction's rows"


def test_merge_is_idempotent(legacy_db):
    """Re-running must not fan out duplicate component rows, and must not
    crash on a database where the source table is already gone."""
    module = _load(_MERGE_IE, "mig_merge")
    _run(module.upgrade, legacy_db)
    _run(module.upgrade, legacy_db)

    with legacy_db.connect() as c:
        n = c.execute(sa.text(
            "SELECT COUNT(*) FROM payroll_ytd_accumulators "
            "WHERE tax_component LIKE 'ie\\_%' ESCAPE '\\'"
        )).scalar()
    assert n == len(_EXPECTED_COMPONENTS), f"re-run produced {n} Ireland component rows"


def test_downgrade_restores_every_value(legacy_db):
    module = _load(_MERGE_IE, "mig_merge")
    _run(module.upgrade, legacy_db)
    _run(module.downgrade, legacy_db)

    with legacy_db.connect() as c:
        row = c.execute(sa.text(
            "SELECT organization_id, usc_payable_ytd, usc_paid_ytd, prsi_reckonable_ytd, "
            "prsi_contribution_weeks_ytd, mff_earnings_ytd_before, last_payslip_id "
            "FROM payroll_ie_ytd_accumulators"
        )).one()
        leftover = c.execute(sa.text(
            "SELECT COUNT(*) FROM payroll_ytd_accumulators "
            "WHERE tax_component LIKE 'ie\\_%' ESCAPE '\\'"
        )).scalar()
        uk = c.execute(sa.text(
            "SELECT ytd_taxable_wages FROM payroll_ytd_accumulators "
            "WHERE tax_component = 'student_loan'"
        )).scalar()

    # organization_id is not on the generic table at all; downgrade has to
    # recover it through payroll_employees.
    assert tuple(row) == (
        _LEGACY_ROW["organization_id"],
        _LEGACY_ROW["usc_payable_ytd"],
        _LEGACY_ROW["usc_paid_ytd"],
        _LEGACY_ROW["prsi_reckonable_ytd"],
        _LEGACY_ROW["prsi_contribution_weeks_ytd"],
        _LEGACY_ROW["mff_earnings_ytd_before"],
        _LEGACY_ROW["last_payslip_id"],
    ), f"downgrade lost or mangled a value: {tuple(row)}"
    assert leftover == 0, f"downgrade left {leftover} orphaned Ireland component rows"
    assert uk == 1234.00, "downgrade must not delete another jurisdiction's rows"


def test_downgrade_leaves_the_threshold_date_honestly_null(legacy_db):
    """The old crossing-date column was never read by anything, and the payslip
    evidence that actually records the crossing is still in
    ie_calculation_snapshot. Re-deriving a date from running totals at downgrade
    time would be a guess, so the column comes back NULL rather than invented."""
    module = _load(_MERGE_IE, "mig_merge")
    _run(module.upgrade, legacy_db)
    _run(module.downgrade, legacy_db)

    with legacy_db.connect() as c:
        crossed = c.execute(sa.text(
            "SELECT mff_threshold_crossed_at_pay_date FROM payroll_ie_ytd_accumulators"
        )).scalar()
    assert crossed is None


def test_dead_table_migration_refuses_to_destroy_rows(legacy_db):
    """The three dropped tables are the one place this refactor could lose real
    data. No code path has ever written them, so a non-zero row count means
    something outside this application owns the table, and the migration must
    stop and say so instead of dropping it."""
    with legacy_db.begin() as c:
        c.execute(sa.text("INSERT INTO payroll_ie_revenue_submissions (id) VALUES (1)"))

    with pytest.raises(RuntimeError, match="Cannot drop"):
        _run(_load(_DROP_DEAD, "mig_drop").upgrade, legacy_db)

    names = set(sa.inspect(legacy_db).get_table_names())
    assert "payroll_ie_revenue_submissions" in names, "the table must survive a refused drop"


def test_dead_table_migration_drops_empty_tables_and_is_idempotent(legacy_db):
    module = _load(_DROP_DEAD, "mig_drop")
    _run(module.upgrade, legacy_db)
    names = set(sa.inspect(legacy_db).get_table_names())
    for table in _DEAD_TABLES:
        assert table not in names, table
    # A second run must be a clean no-op rather than a crash, so a partially
    # applied or re-run deployment does not wedge.
    _run(module.upgrade, legacy_db)


def test_dead_table_migration_downgrade_says_it_is_irreversible(legacy_db):
    """Better to refuse than to fabricate a schema shape nobody has ever run."""
    with pytest.raises(RuntimeError, match="Irreversible"):
        _run(_load(_DROP_DEAD, "mig_drop").downgrade, legacy_db)
