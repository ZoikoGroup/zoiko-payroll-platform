"""hong kong architecture convergence and workflow uniqueness

Revision ID: 2d0cdeeeecc4
Revises: cd62503afe26
Create Date: 2026-10-05

Hong Kong architecture convergence (2026-10-05). Brings the objects
cd62503afe26 created (already in production, NOT modified here) onto the
platform's naming and shared-capability conventions, then adds the workflow
uniqueness guarantees:

1. Table renames — HK statutory tables follow payroll_<country>_* (same as
   payroll_it_* / payroll_fr_* / payroll_ie_*): hkg_<name> -> payroll_hk_<name>.
   Retention, legal hold and the personal-data access log are SHARED platform
   capabilities (retention_service): hkg_retention_policies ->
   payroll_retention_policies, hkg_legal_holds -> payroll_legal_holds,
   hkg_access_events -> payroll_personal_data_access_events, each gaining a
   jurisdiction_country column (existing rows are Hong Kong's: 'HK').
   Indexes, constraints and (PostgreSQL) sequences are renamed with them.
2. Column renames — HK columns follow the two-letter country prefix of it_* /
   de_* / se_* / ie_* / au_*: the 24 hkg_* statutory-profile columns and
   payslip_items.hkg_calculation_trace -> hk_*.
3. Workflow uniqueness — partial unique indexes so the tenant workflows that
   used check-then-insert cannot create duplicates under concurrency:
     uq_payroll_hk_tax_clearance_hold_open  one open IR56G case per employee
     uq_payroll_hk_ird_event_case           one IR56E / IR56F per event (originals)
     uq_payroll_hk_ird_annual_ir56b         one live original IR56B per employee / year
     uq_payroll_hk_ird_annual_bir56a        one live original BIR56A per organisation / year
     uq_payroll_hk_ird_open_replacement     one open replacement per filed case
     uq_payroll_hk_empf_open_batch          one live unsubmitted eMPF batch per period

Data: no row is deleted or rewritten except the jurisdiction_country backfill
('HK') of the three shared tables. Fail-closed: before any unique index is
created, rows that would violate it are counted and the upgrade refuses
(RuntimeError naming the index) — duplicates must be resolved by a person.
Idempotent in both directions (each step checks the current schema first), so
upgrade -> downgrade -> upgrade is safe, including on a dev database already
synced by create_all. PostgreSQL renames indexes / constraints / sequences in
place; SQLite (dev / tests only) recreates renamed indexes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2d0cdeeeecc4'
down_revision: Union[str, Sequence[str], None] = 'cd62503afe26'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (old table, new table) — literal pairs, so the rename chain is auditable
# (tests/test_model_tables_have_migrations.py follows them back to the
# create_table in cd62503afe26).
_TABLE_RENAMES = (
    ('hkg_work_hours', 'payroll_hk_work_hours'),
    ('hkg_ird_reporting_cases', 'payroll_hk_ird_reporting_cases'),
    ('hkg_tax_clearance_holds', 'payroll_hk_tax_clearance_holds'),
    ('hkg_tax_clearance_hold_lines', 'payroll_hk_tax_clearance_hold_lines'),
    ('hkg_average_wage_snapshots', 'payroll_hk_average_wage_snapshots'),
    ('hkg_termination_results', 'payroll_hk_termination_results'),
    ('hkg_empf_submissions', 'payroll_hk_empf_submissions'),
    ('hkg_payslip_corrections', 'payroll_hk_payslip_corrections'),
    ('hkg_ird_software_approvals', 'payroll_hk_ird_software_approvals'),
    ('hkg_empf_configurations', 'payroll_hk_empf_configurations'),
    # shared platform records governance (retention_service)
    ('hkg_retention_policies', 'payroll_retention_policies'),
    ('hkg_legal_holds', 'payroll_legal_holds'),
    ('hkg_access_events', 'payroll_personal_data_access_events'),
)
_SHARED_TABLES = dict(_TABLE_RENAMES[-3:])

_PROFILE_TABLE = 'payroll_employee_statutory_profiles'
_PROFILE_COLUMNS = (
    'employment_relationship', 'identity_document_type', 'identity_token', 'residency_status', 'visa_type',
    'entered_for_employment', 'permission_to_stay_until', 'overseas_scheme_member', 'mpf_exemption_code',
    'mpf_exemption_reason', 'mpf_exemption_evidence_ref', 'mpf_scheme_ref', 'employment_continuity_start',
    'pay_basis', 'contractual_weekly_hours', 'likely_chargeable', 'arrival_date', 'expected_departure_date',
    'frequent_travel_exempt', 'termination_date', 'termination_reason', 'pre_transition_monthly_wage',
    'pre_transition_wage_basis', 'pre_transition_evidence_ref',
)
_COLUMN_RENAMES = tuple((_PROFILE_TABLE, f'hkg_{c}', f'hk_{c}') for c in _PROFILE_COLUMNS) + (
    ('payslip_items', 'hkg_calculation_trace', 'hk_calculation_trace'),
)

_OPEN_REPLACEMENT = ("amends_case_id IS NOT NULL AND status NOT IN "
                     "('FILED', 'ACCEPTED', 'ACKNOWLEDGED', 'AMENDED', 'CANCELLED', 'SUPPRESSED')")
# (index name, table, columns, partial predicate)
_UNIQUE_INDEXES = (
    ('uq_payroll_hk_tax_clearance_hold_open', 'payroll_hk_tax_clearance_holds', ('organization_id', 'employee_id'),
     "state <> 'CASE_CLOSED'"),
    ('uq_payroll_hk_ird_event_case', 'payroll_hk_ird_reporting_cases',
     ('organization_id', 'employee_id', 'form_type', 'event_date'),
     "form_type IN ('IR56E', 'IR56F') AND amends_case_id IS NULL"),
    ('uq_payroll_hk_ird_annual_ir56b', 'payroll_hk_ird_reporting_cases',
     ('organization_id', 'employee_id', 'year_of_assessment'),
     "form_type = 'IR56B' AND amends_case_id IS NULL AND status NOT IN ('AMENDED', 'CANCELLED')"),
    ('uq_payroll_hk_ird_annual_bir56a', 'payroll_hk_ird_reporting_cases', ('organization_id', 'year_of_assessment'),
     "form_type = 'BIR56A' AND amends_case_id IS NULL AND status NOT IN ('AMENDED', 'CANCELLED')"),
    ('uq_payroll_hk_ird_open_replacement', 'payroll_hk_ird_reporting_cases', ('amends_case_id',), _OPEN_REPLACEMENT),
    ('uq_payroll_hk_empf_open_batch', 'payroll_hk_empf_submissions', ('organization_id', 'contribution_period'),
     "status IN ('PREPARED', 'VALIDATED')"),
)


def _bind():
    return op.get_bind()


def _pg() -> bool:
    return _bind().dialect.name == 'postgresql'


def _tables() -> set:
    return set(sa.inspect(_bind()).get_table_names())


def _columns(table: str) -> set:
    return {c['name'] for c in sa.inspect(_bind()).get_columns(table)} if table in _tables() else set()


def _indexes(table: str) -> set:
    return {ix['name'] for ix in sa.inspect(_bind()).get_indexes(table)} if table in _tables() else set()


def _renamed(name: str, old_table: str, new_table: str) -> str:
    """The convention name of an index / constraint / sequence after the table rename."""
    if old_table in name:
        return name.replace(old_table, new_table)
    if new_table.startswith('payroll_hk_') and 'hkg_' in name:        # upgrade: ix_hkg_ird_case_lookup, uq_hkg_*
        return name.replace('hkg_', 'payroll_hk_')
    if new_table.startswith('hkg_') and 'payroll_hk_' in name:         # downgrade: back to cd62503afe26's names
        return name.replace('payroll_hk_', 'hkg_')
    return name


def _rename_objects(old_table: str, new_table: str, table_now: str) -> None:
    """Rename the indexes / constraints / sequence of `table_now` (already
    renamed) from names derived from old_table to names derived from new_table."""
    bind = _bind()
    if _pg():
        for (con,) in bind.execute(sa.text(
                "SELECT conname FROM pg_constraint WHERE conrelid = to_regclass(:t)"), {"t": table_now}).fetchall():
            target = _renamed(con, old_table, new_table)
            if target != con:
                op.execute(f'ALTER TABLE "{table_now}" RENAME CONSTRAINT "{con}" TO "{target}"')
        for (ix,) in bind.execute(sa.text(
                "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema() AND tablename = :t"),
                {"t": table_now}).fetchall():
            target = _renamed(ix, old_table, new_table)
            if target != ix:
                op.execute(f'ALTER INDEX "{ix}" RENAME TO "{target}"')
        seq = bind.execute(sa.text("SELECT pg_get_serial_sequence(:t, 'id')"), {"t": table_now}).scalar()
        if seq:
            short = seq.split('.')[-1].strip('"')
            target = _renamed(short, old_table, new_table)
            if target != short:
                op.execute(f'ALTER SEQUENCE {seq} RENAME TO "{target}"')
    else:
        for name, sql in bind.execute(sa.text(
                "SELECT name, sql FROM sqlite_master WHERE type = 'index' AND tbl_name = :t AND sql IS NOT NULL"),
                {"t": table_now}).fetchall():
            target = _renamed(name, old_table, new_table)
            if target != name:
                op.execute(f'DROP INDEX "{name}"')
                op.execute(sql.replace(f'"{name}"', f'"{target}"', 1).replace(f' {name} ', f' {target} ', 1))


def _rename_table(old: str, new: str) -> None:
    tables = _tables()
    if old in tables and new not in tables:
        op.rename_table(old, new)
    if new in _tables():
        _rename_objects(old, new, new)


def _rename_column(table: str, old: str, new: str) -> None:
    cols = _columns(table)
    if old in cols and new not in cols:
        op.execute(f'ALTER TABLE "{table}" RENAME COLUMN "{old}" TO "{new}"')


def upgrade() -> None:
    tables = _tables()
    missing = [old for old, new in _TABLE_RENAMES if old not in tables and new not in tables]
    if missing:
        raise RuntimeError(f"{', '.join(missing)} missing — cd62503afe26 must be applied first")
    # 1. tables (+ their indexes / constraints / sequences)
    for old, new in _TABLE_RENAMES:
        _rename_table(old, new)
    # 2. columns
    for table, old, new in _COLUMN_RENAMES:
        _rename_column(table, old, new)
    # 3. shared tables become jurisdiction-aware (existing rows were Hong Kong's)
    for table in _SHARED_TABLES.values():
        if 'jurisdiction_country' not in _columns(table):
            op.add_column(table, sa.Column('jurisdiction_country', sa.String(2), nullable=False, server_default='HK'))
            if _pg():
                op.alter_column(table, 'jurisdiction_country', server_default=None)
        ix = f'ix_{table}_jurisdiction_country'
        if ix not in _indexes(table):
            op.create_index(ix, table, ['jurisdiction_country'], unique=False)
    # 4. workflow uniqueness (fail closed on existing duplicates)
    bind = _bind()
    pending = []
    for name, table, cols, where in _UNIQUE_INDEXES:
        if name in _indexes(table):
            continue
        group = ", ".join(cols)
        duplicates = bind.execute(sa.text(
            f"SELECT count(*) FROM (SELECT {group} FROM {table} WHERE {where} "
            f"GROUP BY {group} HAVING count(*) > 1) d")).scalar()
        if duplicates:
            raise RuntimeError(
                f"{name}: {duplicates} duplicate group(s) already exist in {table} for ({group}) WHERE {where} — "
                "refusing to create the unique index. Resolve the duplicates (no rows are changed by this migration).")
        pending.append((name, table, cols, where))
    for name, table, cols, where in pending:
        op.create_index(name, table, list(cols), unique=True,
                        postgresql_where=sa.text(where), sqlite_where=sa.text(where))


def downgrade() -> None:
    for name, table, _cols, _where in reversed(_UNIQUE_INDEXES):
        if name in _indexes(table):
            op.drop_index(name, table_name=table)
    for table in _SHARED_TABLES.values():
        ix = f'ix_{table}_jurisdiction_country'
        if ix in _indexes(table):
            op.drop_index(ix, table_name=table)
        if 'jurisdiction_country' in _columns(table):
            op.drop_column(table, 'jurisdiction_country')
    for table, old, new in reversed(_COLUMN_RENAMES):
        _rename_column(table, new, old)
    for old, new in reversed(_TABLE_RENAMES):
        tables = _tables()
        if new in tables and old not in tables:
            op.rename_table(new, old)
        if old in _tables():
            _rename_objects(new, old, old)
