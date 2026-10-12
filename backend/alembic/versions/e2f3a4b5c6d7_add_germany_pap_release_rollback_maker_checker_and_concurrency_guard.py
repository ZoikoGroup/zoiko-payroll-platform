"""add germany pap release rollback maker-checker and concurrency guard

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-09-03 00:00:00.000000

Phase 8H (docs/PHASE_8H_GERMANY_PAP_EXTERNAL_EVIDENCE_AND_FINAL_READINESS_REPORT.md).

Additive only, on the existing payroll_germany_pap_releases table
(Phase 8G-1):

1. Two new nullable columns, jurisdiction_country/tax_year, denormalized
   from the bound PapAlgorithmAsset at create_pap_release() time. These
   exist ONLY to let the database itself (not just a service-layer
   SELECT-then-UPDATE check) enforce "at most one ACTIVE release per
   (country, tax_year)" via the new partial unique index below — Phase
   8G-2 found the service-layer-only check shares PapAlgorithmAsset's own
   long-standing PUBLISHED-conflict pattern's theoretical TOCTOU gap under
   true concurrent transactions.

2. A new partial unique index, uq_pap_release_one_active_per_scope, on
   (jurisdiction_country, tax_year) WHERE status = 'ACTIVE' — authored
   with BOTH postgresql_where AND sqlite_where from the start (Phase
   8E-2's own F2 finding: a migration that only carries postgresql_where
   silently becomes a full unique index under SQLite).

3. Four new nullable columns for rollback maker-checker (Phase 8H §13):
   rollback_requested_by_id/_at, rollback_approved_by_id/_at. The
   rollback_requested_by_id != rollback_approved_by_id rule is enforced
   in service.py (approve_pap_rollback), the same "distinct actor"
   pattern already used for release approval and activation — no new
   RBAC role was created.

No existing table/column is altered. No data is migrated. No row is
seeded — the table is empty in every environment (no PapAlgorithmAsset
has ever been published outside a test transaction), so backfilling
jurisdiction_country/tax_year for pre-existing rows is not applicable.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2f3a4b5c6d7'
down_revision: Union[str, Sequence[str], None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('payroll_germany_pap_releases', sa.Column('jurisdiction_country', sa.String(length=10), nullable=True))
    op.add_column('payroll_germany_pap_releases', sa.Column('tax_year', sa.String(length=20), nullable=True))

    op.add_column('payroll_germany_pap_releases', sa.Column('rollback_requested_by_id', sa.Integer(), nullable=True))
    op.add_column('payroll_germany_pap_releases', sa.Column('rollback_requested_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('payroll_germany_pap_releases', sa.Column('rollback_approved_by_id', sa.Integer(), nullable=True))
    op.add_column('payroll_germany_pap_releases', sa.Column('rollback_approved_at', sa.DateTime(timezone=True), nullable=True))

    op.create_foreign_key(
        'fk_pap_release_rollback_requested_by_id', 'payroll_germany_pap_releases', 'users',
        ['rollback_requested_by_id'], ['id'],
    )
    op.create_foreign_key(
        'fk_pap_release_rollback_approved_by_id', 'payroll_germany_pap_releases', 'users',
        ['rollback_approved_by_id'], ['id'],
    )

    op.create_index(
        'uq_pap_release_one_active_per_scope', 'payroll_germany_pap_releases',
        ['jurisdiction_country', 'tax_year'], unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
        sqlite_where=sa.text("status = 'ACTIVE'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        'uq_pap_release_one_active_per_scope', table_name='payroll_germany_pap_releases',
        postgresql_where=sa.text("status = 'ACTIVE'"),
        sqlite_where=sa.text("status = 'ACTIVE'"),
    )
    op.drop_constraint('fk_pap_release_rollback_approved_by_id', 'payroll_germany_pap_releases', type_='foreignkey')
    op.drop_constraint('fk_pap_release_rollback_requested_by_id', 'payroll_germany_pap_releases', type_='foreignkey')
    op.drop_column('payroll_germany_pap_releases', 'rollback_approved_at')
    op.drop_column('payroll_germany_pap_releases', 'rollback_approved_by_id')
    op.drop_column('payroll_germany_pap_releases', 'rollback_requested_at')
    op.drop_column('payroll_germany_pap_releases', 'rollback_requested_by_id')
    op.drop_column('payroll_germany_pap_releases', 'tax_year')
    op.drop_column('payroll_germany_pap_releases', 'jurisdiction_country')
