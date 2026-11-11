"""mx_decision_inputs_m21: the inputs some decision options read (Mexico sweep S1)

Revision ID: efc56f3235e2
Revises: e7ec6c1933b4
Create Date: 2026-10-28

Mexico engineering sweep S1 (decisions as configuration). Seven NULLABLE columns, each
read only by the option of a decision that needs a per-record figure:
  * payroll_mx_terminations.indemnity_daily_salary / indemnity_salary_evidence_ref —
    D-12 (c): the LFT Art. 89 indemnity salary an operator enters with its evidence;
  * payroll_mx_labor_policies.hourly_rate_daily_hours — D-17 (c): the employer's own
    daily-hours figure the overtime hourly rate is divided by;
  * payroll_mx_labor_policies.special_pay_withholding_method — D-08 PER_EMPLOYER: the
    employer's own choice of withholding method for a special payment in its own run;
  * payroll_employee_statutory_profiles.mx_sdi_operator_entered / mx_sdi_evidence_ref —
    C4 OPERATOR_ENTERED: the CFDI SalarioDiarioIntegrado an operator enters with evidence;
  * payroll_employee_statutory_profiles.mx_union_member — C12: the CFDI Receptor
    Sindicalizado attribute ("Sí" / "No") when C12 answers FROM_PROFILE.
No table is created; no RLS policy changes (no policy names a column).

Merging to main runs this in production. Each ADD COLUMN (nullable, no default) is a
catalog-only change but takes a brief ACCESS EXCLUSIVE lock on its table until the
upgrade transaction commits. Two tables are Mexico's (empty in production while Mexico is
dormant); payroll_employee_statutory_profiles is SHARED by every country, so the revision
runs under SET LOCAL lock_timeout = '5s' and gives up rather than queue behind a writer.
Measured on PostgreSQL 17 in tests/test_mexico_decision_inputs_migrations.py.
Guarded and idempotent; downgrade drops only these columns.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "efc56f3235e2"
down_revision: Union[str, Sequence[str], None] = "e7ec6c1933b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TERMINATIONS = "payroll_mx_terminations"
POLICIES = "payroll_mx_labor_policies"
PROFILES = "payroll_employee_statutory_profiles"
NEW_COLUMNS = ((TERMINATIONS, "indemnity_daily_salary"), (TERMINATIONS, "indemnity_salary_evidence_ref"),
               (POLICIES, "hourly_rate_daily_hours"), (PROFILES, "mx_union_member"),
               (POLICIES, "special_pay_withholding_method"), (PROFILES, "mx_sdi_operator_entered"),
               (PROFILES, "mx_sdi_evidence_ref"))


def _has_column(table, column):
    insp = sa.inspect(op.get_bind())
    return table in insp.get_table_names() and column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    if not _has_column(TERMINATIONS, "indemnity_daily_salary"):
        op.add_column("payroll_mx_terminations", sa.Column("indemnity_daily_salary", sa.Numeric(14, 4), nullable=True))
    if not _has_column(TERMINATIONS, "indemnity_salary_evidence_ref"):
        op.add_column("payroll_mx_terminations",
                      sa.Column("indemnity_salary_evidence_ref", sa.String(300), nullable=True))
    if not _has_column(POLICIES, "hourly_rate_daily_hours"):
        op.add_column("payroll_mx_labor_policies", sa.Column("hourly_rate_daily_hours", sa.Numeric(6, 2), nullable=True))
    if not _has_column(PROFILES, "mx_union_member"):
        op.add_column("payroll_employee_statutory_profiles", sa.Column("mx_union_member", sa.Boolean(), nullable=True))
    if not _has_column(POLICIES, "special_pay_withholding_method"):
        op.add_column("payroll_mx_labor_policies",
                      sa.Column("special_pay_withholding_method", sa.String(20), nullable=True))
    if not _has_column(PROFILES, "mx_sdi_operator_entered"):
        op.add_column("payroll_employee_statutory_profiles",
                      sa.Column("mx_sdi_operator_entered", sa.Numeric(14, 4), nullable=True))
    if not _has_column(PROFILES, "mx_sdi_evidence_ref"):
        op.add_column("payroll_employee_statutory_profiles",
                      sa.Column("mx_sdi_evidence_ref", sa.String(300), nullable=True))


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for table, column in reversed(NEW_COLUMNS):
        if _has_column(table, column):
            with op.batch_alter_table(table) as batch:
                batch.drop_column(column)
