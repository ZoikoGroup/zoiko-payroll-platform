"""add ie_calculation_snapshot to payslip_items

Revision ID: c7d4e9f1a2b3
Revises: 4b13831d574b

ZP-IE-ENG-001. Purely ADDITIVE and non-destructive:

engine/countries/ireland.py returns the whole Irish statutory breakdown
(ie_paye, ie_usc, ie_employee_prsi, ie_employer_prsi, ie_mff_employee,
ie_lpt, ie_employee_total, the applied RPN's number/snapshot id/raw_hash/
issued_at, the PRSI sub-class, the NAERSA-notified MyFutureFund status and
ie_calculation_trace itself), but PayslipItem had no ie_* columns and
service.py's PayslipItem values-dict mapped none of them — so every one of
those figures was computed and then silently discarded at payslip write
time. Only PAYE (tds), employer PRSI (employer_social_security) and PRSC
(employee_pension / employer_pension) survived, because the engine already
reuses those generic columns.

A Revenue Online System submission needs the per-employee USC / PRSI /
MyFutureFund / LPT breakdown, so it has to be persisted somewhere.

This follows the architecture Germany's `germany_calculation_snapshot` and
France's `fr_calculation_snapshot` already established in this same table —
ONE nullable JSON snapshot column per country, deliberately NOT a dozen
new scalar columns. The PayslipItem docstring records that decision, and
au_calculation_trace is the third precedent. It is the same immutability
contract: the snapshot is written once at generation time and never
re-derived, so a finalized Irish payslip stays reproducible even after
RPN, NAERSA and Revenue content later change.

- Nullable, so every existing row (all countries, all dates) is untouched
  and this is a no-op for non-Irish payslips.
- No backfill, no inference: Irish payslips generated before this column
  existed keep NULL rather than having a snapshot reconstructed for them.
- down_revision is the current head 4b13831d574b, so this is the only
  revision that can be at the tip.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c7d4e9f1a2b3'
down_revision: str = '4b13831d574b'
branch_labels: str = None
depends_on: str = None


def upgrade() -> None:
    op.add_column(
        "payslip_items",
        sa.Column("ie_calculation_snapshot", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("payslip_items", "ie_calculation_snapshot")
