"""mx_foundation_m1: Mexico earning classifications + CFDI schema releases and catalog entries

Revision ID: 5d2c8f1a7b3e
Revises: f4b8d2a6c9e1
Create Date: 2026-10-15

ZP-MX-ENG-001 Phase 2 (plan v1.1 §5):
  - payroll_mx_earning_classifications  multi-axis classification per earning
    code (MX-005), versioned DRAFT -> ACTIVE -> SUPERSEDED/ARCHIVED (MX-006);
    two partial unique indexes (canonical rows / org rows), as ContributionRate.
  - payroll_mx_cfdi_schema_releases     pinned CFDI 4.0 + Nómina 1.2 release (MX-015).
  - payroll_mx_cfdi_catalog_entries     SAT catalog codes inside a release.

Additive only: three new tables; no existing row or column is touched.
Idempotent from day one (unlike NL m1–m9, repaired by 08f0f142574e): every
create is skipped when its object already exists, every drop when it is gone.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "5d2c8f1a7b3e"
down_revision: Union[str, Sequence[str], None] = "f4b8d2a6c9e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_index(table, name):
    return _has_table(table) and name in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    if not _has_table("payroll_mx_earning_classifications"):
        op.create_table(
            "payroll_mx_earning_classifications",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True),
            sa.Column("earning_code", sa.String(50), nullable=False),
            sa.Column("label", sa.String(200), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("effective_from", sa.Date(), nullable=False),
            sa.Column("effective_to", sa.Date(), nullable=True),
            sa.Column("isr_treatment", sa.String(10), nullable=False),
            sa.Column("isr_exempt_rule_key", sa.String(80), nullable=True),
            sa.Column("sbc_treatment", sa.String(10), nullable=False),
            sa.Column("sbc_exclusion_condition", sa.String(300), nullable=True),
            sa.Column("infonavit_included", sa.Boolean(), nullable=False),
            sa.Column("isn_default_included", sa.Boolean(), nullable=False),
            sa.Column("isn_state_overrides", sa.JSON(), nullable=True),
            sa.Column("ptu_wage_base_included", sa.Boolean(), nullable=False),
            sa.Column("cfdi_node_type", sa.String(12), nullable=False),
            sa.Column("cfdi_concept_code", sa.String(10), nullable=True),
            sa.Column("status", sa.String(12), nullable=False),
            sa.Column("source_document_id", sa.Integer(), sa.ForeignKey("payroll_source_artifacts.id"), nullable=True),
            sa.Column("approved_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("sha256", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("isr_treatment IN ('TAXABLE', 'EXEMPT', 'PARTIAL')", name="ck_mx_earn_isr"),
            sa.CheckConstraint("sbc_treatment IN ('FIXED', 'VARIABLE', 'EXCLUDED')", name="ck_mx_earn_sbc"),
            sa.CheckConstraint("cfdi_node_type IN ('PERCEPCION', 'DEDUCCION', 'OTRO_PAGO', 'SEPARACION')",
                               name="ck_mx_earn_cfdi_node"),
            sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'SUPERSEDED', 'ARCHIVED')", name="ck_mx_earn_status"),
            sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_mx_earn_window"),
        )
    table = "payroll_mx_earning_classifications"
    for name, cols in (("ix_payroll_mx_earning_classifications_id", ["id"]),
                       ("ix_payroll_mx_earning_classifications_organization_id", ["organization_id"]),
                       ("ix_payroll_mx_earning_classifications_earning_code", ["earning_code"]),
                       ("ix_payroll_mx_earning_classifications_effective_from", ["effective_from"]),
                       ("ix_payroll_mx_earning_classifications_effective_to", ["effective_to"]),
                       ("ix_mx_earn_org_code_eff", ["organization_id", "earning_code", "effective_from"])):
        if not _has_index(table, name):
            op.create_index(name, table, cols)
    if not _has_index(table, "uq_mx_earn_canonical_code_eff"):
        op.create_index("uq_mx_earn_canonical_code_eff", table, ["earning_code", "effective_from"], unique=True,
                        postgresql_where=sa.text("organization_id IS NULL"),
                        sqlite_where=sa.text("organization_id IS NULL"))
    if not _has_index(table, "uq_mx_earn_org_code_eff"):
        op.create_index("uq_mx_earn_org_code_eff", table, ["organization_id", "earning_code", "effective_from"],
                        unique=True, postgresql_where=sa.text("organization_id IS NOT NULL"),
                        sqlite_where=sa.text("organization_id IS NOT NULL"))

    if not _has_table("payroll_mx_cfdi_schema_releases"):
        op.create_table(
            "payroll_mx_cfdi_schema_releases",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("cfdi_version", sa.String(10), nullable=False),
            sa.Column("complement_version", sa.String(10), nullable=False),
            sa.Column("revision", sa.String(40), nullable=True),
            sa.Column("xsd_checksum", sa.String(64), nullable=True),
            sa.Column("catalog_release", sa.String(40), nullable=True),
            sa.Column("pac_validation_version", sa.String(40), nullable=True),
            sa.Column("source_document_id", sa.Integer(), sa.ForeignKey("payroll_source_artifacts.id"), nullable=True),
            sa.Column("status", sa.String(12), nullable=False),
            sa.Column("approved_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("status IN ('Draft', 'In Review', 'Approved', 'Active', 'Superseded')",
                               name="ck_mx_cfdi_release_status"),
        )
    if not _has_index("payroll_mx_cfdi_schema_releases", "ix_payroll_mx_cfdi_schema_releases_id"):
        op.create_index("ix_payroll_mx_cfdi_schema_releases_id", "payroll_mx_cfdi_schema_releases", ["id"])

    if not _has_table("payroll_mx_cfdi_catalog_entries"):
        op.create_table(
            "payroll_mx_cfdi_catalog_entries",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("schema_release_id", sa.Integer(),
                      sa.ForeignKey("payroll_mx_cfdi_schema_releases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("catalog_name", sa.String(60), nullable=False),
            sa.Column("code", sa.String(20), nullable=False),
            sa.Column("description", sa.String(500), nullable=False),
            sa.Column("valid_from", sa.Date(), nullable=True),
            sa.Column("valid_to", sa.Date(), nullable=True),
            sa.Column("attributes", sa.JSON(), nullable=True),
            sa.UniqueConstraint("schema_release_id", "catalog_name", "code", "valid_from", name="uq_mx_cfdi_catalog_entry"),
        )
    for name, cols in (("ix_payroll_mx_cfdi_catalog_entries_id", ["id"]),
                       ("ix_payroll_mx_cfdi_catalog_entries_schema_release_id", ["schema_release_id"])):
        if not _has_index("payroll_mx_cfdi_catalog_entries", name):
            op.create_index(name, "payroll_mx_cfdi_catalog_entries", cols)


def downgrade() -> None:
    for table in ("payroll_mx_cfdi_catalog_entries", "payroll_mx_cfdi_schema_releases",
                  "payroll_mx_earning_classifications"):
        if _has_table(table):
            op.drop_table(table)
