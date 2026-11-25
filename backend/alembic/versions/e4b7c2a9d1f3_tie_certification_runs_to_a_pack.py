"""tie certification runs to a pack: payroll_test_certification_runs.jurisdiction_pack_id + content_fingerprint

Revision ID: e4b7c2a9d1f3
Revises: b5f3e8a1c6d9
Create Date: 2026-11-25

Belgium's gate G1 and pack activation accepted the latest Belgian certification run of ANY pack, recorded at
any time. A run now records the pack it certified (jurisdiction_pack_id) and a SHA-256 fingerprint of that
pack's content at run time (content_fingerprint); a run only counts for the same pack while the fingerprint
still matches (belgium_golden.be_certification_for).

Both columns are nullable and added only: no existing run row is altered or deleted. Existing runs keep NULL
in both, so they no longer count for any pack (stricter, never looser) — a new run must be recorded.
"""

import sqlalchemy as sa
from alembic import op

revision = "e4b7c2a9d1f3"
down_revision = "b5f3e8a1c6d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payroll_test_certification_runs",
                  sa.Column("jurisdiction_pack_id", sa.Integer(), nullable=True))
    op.add_column("payroll_test_certification_runs",
                  sa.Column("content_fingerprint", sa.String(length=64), nullable=True))
    op.create_foreign_key("fk_test_cert_run_jurisdiction_pack", "payroll_test_certification_runs",
                          "payroll_jurisdiction_packs", ["jurisdiction_pack_id"], ["id"])
    op.create_index("ix_test_cert_run_pack", "payroll_test_certification_runs", ["jurisdiction_pack_id"])


def downgrade() -> None:
    op.drop_index("ix_test_cert_run_pack", table_name="payroll_test_certification_runs")
    op.drop_constraint("fk_test_cert_run_jurisdiction_pack", "payroll_test_certification_runs", type_="foreignkey")
    op.drop_column("payroll_test_certification_runs", "content_fingerprint")
    op.drop_column("payroll_test_certification_runs", "jurisdiction_pack_id")
