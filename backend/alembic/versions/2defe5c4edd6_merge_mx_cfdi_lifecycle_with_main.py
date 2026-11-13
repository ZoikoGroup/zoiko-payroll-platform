"""merge Mexico CFDI lifecycle (b5e1c7d9a3f2) with main's Poland / payslip templates chain (f3a9c1d7e2b4)

Revision ID: 2defe5c4edd6
Revises: b5e1c7d9a3f2, f3a9c1d7e2b4
Create Date: 2026-11-12

Both chains grow from a8cde2482ef0 (New Zealand P9 nz_parallel_cycles):

  a8cde2482ef0 -> b5e1c7d9a3f2 (Mexico CFDI lifecycle, rugvedh)
  a8cde2482ef0 -> 1ee3bbde33bb -> e11c2c36df17 -> e75b9219e1f8 -> e7ec6c1933b4
                  (Poland P2 / P6 / P8 / P9) -> efc56f3235e2 (Mexico
                  mx_decision_inputs_m21) -> f3a9c1d7e2b4 (payslip templates, main)

Merging origin/main into rugvedh left two heads. A merge revision (rather than
re-parenting either chain) leaves both authors' files untouched — the same
approach as 92c67cab49fc.

Nothing to do on upgrade or downgrade. Each chain creates its own tables and
columns (payroll_mx_cfdi_* lifecycle on one side; payroll_pl_*, the payslip
template tables and the m21 decision-input columns on the other); neither
creates or alters an object the other touches.
"""

revision = "2defe5c4edd6"
down_revision = ("b5e1c7d9a3f2", "f3a9c1d7e2b4")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
