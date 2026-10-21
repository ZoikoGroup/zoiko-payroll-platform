"""PostgreSQL row-level security on every tenant and worker table (ZP-PRIV C.2)

Revision ID: d7f9b1c3e5a6
Revises: c5e7a9b1d3f4
Create Date: 2026-10-19

The application pushes its request context into every transaction
(core/authz/tenant_context.py, SET LOCAL via set_config(..., true)):

  app.rls_mode   'tenant' | 'platform' | 'platform_aggregate' | 'system'
  app.tenant_id  the organization of a tenant principal

Tables are derived from the live schema (never a hand-picked list):

  worker tables  payroll_employees, payslip_items, and every table with an
                 employee_id / payroll_employee_id / payslip_item_id column or
                 a foreign key to one of those two tables
  tenant tables  every other table with an organization_id column

Policies (ENABLE + FORCE, so the table owner is bound too):

  worker   visible in 'system' and 'platform_aggregate' modes, otherwise only
           to a 'tenant' context of the same organization. A 'platform'
           context (Super Admin, support operators) sees NO worker row.
           Tables without organization_id inherit isolation through their
           employee / payslip parent (itself RLS-protected).
  tenant   visible in 'system' / 'platform' / 'platform_aggregate' modes,
           platform-global rows (organization_id IS NULL) to everyone, and
           otherwise only a 'tenant' context's own organization.

A connection that sets no mode at all (raw psql, a forgotten code path) sees
NOTHING in either class. Migrations run with app.rls_mode='system'
(alembic/env.py).

Operational requirement (cannot be done from a migration): the application
must connect as a role that is NOT superuser and has NOBYPASSRLS, otherwise
PostgreSQL skips these policies. See docs/privacy/rls_runbook.md; the app
logs a CRITICAL warning at startup when its role bypasses RLS
(DB_RLS_REQUIRE_ENFORCED=true turns that into a refusal to start).
"""

import sqlalchemy as sa
from alembic import op

revision = "d7f9b1c3e5a6"
down_revision = "c5e7a9b1d3f4"
branch_labels = None
depends_on = None


def _sql(bind, statement: str) -> None:
    """Run one DDL statement. sa.text() escapes the % in plpgsql bodies for
    the psycopg2 driver (exec_driver_sql would treat it as a parameter)."""
    bind.execute(sa.text(statement))

POLICY = "zoiko_rls"
_WORKER_ROOTS = ("payroll_employees", "payslip_items")
_WORKER_COLUMNS = ("employee_id", "payroll_employee_id", "payslip_item_id")
_SKIP = {"alembic_version"}


def _schema(bind):
    cols = {}
    for table, column in bind.execute(sa.text(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema()"
    )):
        cols.setdefault(table, set()).add(column)
    fks = {}
    for table, ref in bind.execute(sa.text(
        "SELECT tc.table_name, ccu.table_name FROM information_schema.table_constraints tc "
        "JOIN information_schema.constraint_column_usage ccu "
        "  ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema "
        "WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = current_schema()"
    )):
        fks.setdefault(table, set()).add(ref)
    base_tables = {r[0] for r in bind.execute(sa.text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'"
    ))}
    return cols, fks, base_tables


def classify(bind):
    cols, fks, base = _schema(bind)
    worker, tenant = {}, []
    for table in sorted(base - _SKIP):
        c = cols.get(table, set())
        refs = fks.get(table, set())
        if table in _WORKER_ROOTS or c & set(_WORKER_COLUMNS) or refs & set(_WORKER_ROOTS):
            if "organization_id" in c:
                worker[table] = "org"
            elif "employee_id" in c:
                worker[table] = "employee"
            elif "payroll_employee_id" in c:
                worker[table] = "payroll_employee"
            elif "payslip_item_id" in c:
                worker[table] = "payslip"
            else:
                worker[table] = "none"
        elif "organization_id" in c:
            tenant.append(table)
    return worker, tenant


_WORKER_ALLOWED = "zoiko_rls_mode() IN ('system', 'platform_aggregate')"
_TENANT_MODE = "zoiko_rls_mode() = 'tenant'"


def _worker_predicate(strategy: str) -> str:
    if strategy == "org":
        own = f"({_TENANT_MODE} AND organization_id = zoiko_rls_tenant())"
    elif strategy == "employee":
        own = f"({_TENANT_MODE} AND EXISTS (SELECT 1 FROM payroll_employees e WHERE e.id = employee_id))"
    elif strategy == "payroll_employee":
        own = (f"({_TENANT_MODE} AND EXISTS (SELECT 1 FROM payroll_employees e "
               f"WHERE e.id = payroll_employee_id))")
    elif strategy == "payslip":
        own = f"({_TENANT_MODE} AND EXISTS (SELECT 1 FROM payslip_items p WHERE p.id = payslip_item_id))"
    else:
        own = "false"
    return f"({_WORKER_ALLOWED} OR {own})"


_TENANT_PREDICATE = (
    "(zoiko_rls_mode() IN ('system', 'platform', 'platform_aggregate') "
    "OR organization_id IS NULL "
    f"OR ({_TENANT_MODE} AND organization_id = zoiko_rls_tenant()))"
)


_UNSET_MODES = ("", "system")


def apply_rls(bind, unset_mode: str = "") -> dict:
    """Create the helper functions and the policy on every derived table.
    Plain SQL on ``bind`` (idempotent), shared with the Postgres test suite.

    ``unset_mode`` is the mode a connection gets when it sets no
    ``app.rls_mode`` at all: '' (strict: sees no worker row) or 'system'
    (rollout onto a database whose running app predates RLS and never sets
    the mode). Stored once in zoiko_rls_settings; a later call never
    overwrites it. The application sets the mode on every transaction
    either way (core/authz/tenant_context.py)."""
    if unset_mode not in _UNSET_MODES:
        raise ValueError(f"unset_mode must be one of {_UNSET_MODES}")
    _sql(bind, "CREATE TABLE IF NOT EXISTS zoiko_rls_settings (unset_mode text NOT NULL "
               "CHECK (unset_mode IN ('', 'system')))")
    _sql(bind, f"INSERT INTO zoiko_rls_settings (unset_mode) SELECT '{unset_mode}' "
               "WHERE NOT EXISTS (SELECT 1 FROM zoiko_rls_settings)")
    _sql(bind, """
        CREATE OR REPLACE FUNCTION zoiko_rls_mode() RETURNS text
        LANGUAGE sql STABLE AS $$
            SELECT coalesce(nullif(current_setting('app.rls_mode', true), ''),
                            (SELECT unset_mode FROM zoiko_rls_settings LIMIT 1), '')
        $$;
    """)
    _sql(bind, """
        CREATE OR REPLACE FUNCTION zoiko_rls_tenant() RETURNS integer
        LANGUAGE sql STABLE AS $$ SELECT nullif(current_setting('app.tenant_id', true), '')::integer $$;
    """)
    worker, tenant = classify(bind)
    # Worker parents first: the child policies' EXISTS subqueries read them.
    for table, strategy in sorted(worker.items(), key=lambda kv: kv[0] not in _WORKER_ROOTS):
        predicate = _worker_predicate(strategy)
        _sql(bind, f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        _sql(bind, f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        _sql(bind, f'DROP POLICY IF EXISTS {POLICY} ON "{table}"')
        _sql(bind, f'CREATE POLICY {POLICY} ON "{table}" USING {predicate} WITH CHECK {predicate}')
    for table in tenant:
        _sql(bind, f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        _sql(bind, f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        _sql(bind, f'DROP POLICY IF EXISTS {POLICY} ON "{table}"')
        _sql(bind, f'CREATE POLICY {POLICY} ON "{table}" USING {_TENANT_PREDICATE} '
                             f'WITH CHECK {_TENANT_PREDICATE}')
    return {"worker": sorted(worker), "tenant": tenant}


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite: the ORM guard (tenant_context.py) is the test-path equivalent
    import os

    # scripts/migrate_privacy_rollout.py sets 'system' so app instances still
    # on the previous code keep working; default is strict.
    apply_rls(bind, unset_mode=os.environ.get("ZP_RLS_UNSET_MODE", "").strip().lower())


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    worker, tenant = classify(bind)
    for table in list(worker) + tenant:
        op.execute(f'DROP POLICY IF EXISTS {POLICY} ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    op.execute("DROP FUNCTION IF EXISTS zoiko_rls_tenant()")
    op.execute("DROP FUNCTION IF EXISTS zoiko_rls_mode()")
    op.execute("DROP TABLE IF EXISTS zoiko_rls_settings")
