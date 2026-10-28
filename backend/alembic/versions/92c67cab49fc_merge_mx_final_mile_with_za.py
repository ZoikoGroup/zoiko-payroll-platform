"""merge Mexico final mile m20 (d3f8b2a6c1e9) with South Africa Phase 8 (c15d5b87d6f5)

Revision ID: 92c67cab49fc
Revises: c15d5b87d6f5, d3f8b2a6c1e9
Create Date: 2026-10-28

Both chains grow from c7d2e9a4f1b6 (Mexico mx_imss_rcv_authority_m19, production
since PR #136):

  c7d2e9a4f1b6 -> d3f8b2a6c1e9 (Mexico final mile: decisions, parallel imports,
                  parallel differences)
  c7d2e9a4f1b6 -> 447f57564983 -> c15d5b87d6f5 (South Africa foundation and
                  Phase 8, venu)

PR #138 merged both into main, leaving two heads: its deploy (run 40628518029)
failed at the test stage, and the backend was never deployed, so neither chain is
applied anywhere. A merge revision (rather than re-parenting either chain) leaves
both authors' files untouched.

Nothing to do on upgrade or downgrade. Each chain creates its own tables and puts
row-level security on them itself (d3f8b2a6c1e9 on payroll_mx_parallel_imports /
payroll_mx_parallel_differences; 447f57564983 and c15d5b87d6f5 on their
payroll_za_* tables); neither creates a table the other must protect.
"""

revision = "92c67cab49fc"
down_revision = ("c15d5b87d6f5", "d3f8b2a6c1e9")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
