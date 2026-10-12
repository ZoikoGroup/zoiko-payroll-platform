"""add germany overtime financial integration fields

Revision ID: b4241285b6dd
Revises: 185332840016
Create Date: 2026-09-07 00:00:00.000000

Phase 8CN renumbering note: this revision was originally authored as
`f0a1b2c3d4e5` (Phase 8AR). `origin/main` independently reused that same
12-hex id for an unrelated migration (`add_source_document_id_to_rate_
slab`) and renamed its own copy of this migration to `b4241285b6dd`. This
`nikhil`-only copy is renamed here to `824bb1b61dc2`, a freshly
verified-unique id, and its parent updated to match the sibling rename
(`e9f0a1b2c3d4` -> `cda89a810e94`) — see
docs/GERMANY_2026_8CN_ALEMBIC_COLLISION_RECONCILIATION_REPORT.md. Only
the `revision`/`down_revision` ids and this note changed; `upgrade()`/
`downgrade()` and every other line are unchanged.

Phase 8AR — docs/PHASE_8AR_GERMANY_OVERTIME_NET_PAY_INTEGRATION_REPORT.md.

Additive only: four new columns on the existing
payroll_germany_overtime_premium_components table —
financial_integration_status (NOT NULL, server_default 'NOT_INTEGRATED'),
applied_gross_delta (gross premium delta → PayslipItem.gross_pay),
applied_pf_delta (RV employee contribution delta → PayslipItem.pf),
applied_esi_delta (ALV+GKV employee contribution delta →
PayslipItem.esi) — all nullable Numeric(12,2). No existing column is
altered or dropped. No backfill — every pre-existing row (all from
before this phase, none of which ever touched PayslipItem.gross_pay/
pf/esi at attach time) correctly defaults to NOT_INTEGRATED with NULL
deltas, an accurate description of their actual historical state.
(Wage-tax delta has no dedicated column: it is 0 while PAP is
BLOCKED_EXTERNAL, represented by financial_integration_status and the
germany_calculation_snapshot/audit trace.)

LOCAL/TEST VERIFICATION ONLY per this project's established database-
safety rule — never applied to the shared remote Postgres instance.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4241285b6dd'  # was f0a1b2c3d4e5 on main; renumbered — collided with an unrelated venu-branch migration id
down_revision: Union[str, Sequence[str], None] = '185332840016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'payroll_germany_overtime_premium_components',
        sa.Column('financial_integration_status', sa.String(length=40), nullable=False, server_default='NOT_INTEGRATED'),
    )
    op.add_column(
        'payroll_germany_overtime_premium_components',
        sa.Column('applied_gross_delta', sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        'payroll_germany_overtime_premium_components',
        sa.Column('applied_pf_delta', sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        'payroll_germany_overtime_premium_components',
        sa.Column('applied_esi_delta', sa.Numeric(12, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('payroll_germany_overtime_premium_components', 'applied_esi_delta')
    op.drop_column('payroll_germany_overtime_premium_components', 'applied_pf_delta')
    op.drop_column('payroll_germany_overtime_premium_components', 'applied_gross_delta')
    op.drop_column('payroll_germany_overtime_premium_components', 'financial_integration_status')
