"""add jurisdiction_pack_id to germany registries

Revision ID: abaca1105dbb
Revises: 13ce5f1cf7a1
Create Date: 2026-09-17 13:37:33.103045

Phase 8DJ reconciliation note: this migration was originally authored
(Phase 8DI) with `down_revision = fbfe6d7eeb2e`, forking from the same
production head as Phase 8DD's `13ce5f1cf7a1` (payslip_items.soli server
default), built independently in a different disposable worktree. Phase
8DJ re-chains this migration onto `13ce5f1cf7a1` instead — a simple
linear sequence (fbfe6d7eeb2e -> 13ce5f1cf7a1 -> abaca1105dbb) rather than
a merge migration, since these two changes touch entirely disjoint
tables/columns and have no ordering dependency on each other; a linear
chain is the simplest coherent graph that represents both exactly once
with a single head. Revision IDs themselves were not renamed, per
instruction.

Phase 8DI — Germany Compliance Pack functionalization. Adds a single,
additive, nullable `jurisdiction_pack_id` FK column (referencing
payroll_jurisdiction_packs.id) to each of the 9 national Germany
statutory registry tables, so a registry row can OPTIONALLY declare
which Compliance Pack version it belongs to.

NOT included: GermanyAccidentInsuranceProfile — that table is
organization-scoped (per-employer carrier registration), architecturally
closer to employee/org-level configuration than national statutory
configuration, and deliberately excluded from Compliance Pack linkage.

NULL is a fully valid, common value for every existing/legacy row — this
migration changes no data and no existing row's behavior. See
app/modules/payroll/service.py's resolve_applicable_germany_pack() /
_resolve_germany_calc_inputs() for how this column is consumed: only as
an ADDITIVE filter, with a graceful fallback to the pre-8DI unfiltered
effective-dated resolution whenever no matching pack-linked row exists —
confirmed via the full pre-existing ~572-test Germany suite passing
unchanged after this migration was designed.

NOT run against production this phase — disposable/local testing only
(this repo's Base.metadata.create_all() picks the column up directly from
the ORM models for test purposes, without needing this migration applied
at all).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'abaca1105dbb'
down_revision: Union[str, Sequence[str], None] = '13ce5f1cf7a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table_name, short_fk_suffix) — the suffix keeps every constraint name
# under PostgreSQL's 63-character identifier limit (caught by this
# migration's own static --sql validation: the naive "fk_<table>_
# jurisdiction_pack_id" name for the longest table name exceeded it).
_GERMANY_REGISTRY_TABLES = [
    ("payroll_germany_contribution_ceilings", "de_ceilings"),
    ("payroll_germany_pv_configurations", "de_pv_config"),
    ("payroll_germany_health_funds", "de_health_funds"),
    ("payroll_germany_health_fund_u1_tariffs", "de_u1_tariffs"),
    ("payroll_germany_earning_taxability_rules", "de_earning_tax"),
    ("payroll_germany_overtime_premium_categories", "de_ot_premium"),
    ("payroll_germany_overtime_grundlohn_caps", "de_ot_grundlohn"),
    ("payroll_germany_church_tax_exceptions", "de_church_tax"),
    ("payroll_germany_minijob_midijob_parameters", "de_minijob"),
]


def upgrade() -> None:
    """Upgrade schema."""
    for table, suffix in _GERMANY_REGISTRY_TABLES:
        op.add_column(
            table,
            sa.Column("jurisdiction_pack_id", sa.Integer(), nullable=True),
        )
        op.create_foreign_key(
            f"fk_{suffix}_pack_id",
            table, "payroll_jurisdiction_packs",
            ["jurisdiction_pack_id"], ["id"],
        )


def downgrade() -> None:
    """Downgrade schema."""
    for table, suffix in _GERMANY_REGISTRY_TABLES:
        op.drop_constraint(f"fk_{suffix}_pack_id", table, type_="foreignkey")
        op.drop_column(table, "jurisdiction_pack_id")
