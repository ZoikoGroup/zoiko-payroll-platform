"""payslip_templates: organisation-owned payslip presentation templates

Revision ID: f3a9c1d7e2b4
Revises: e7ec6c1933b4
Create Date: 2026-11-11

Additive only.

  payroll_payslip_templates             an organisation's payslip layout
  payroll_payslip_template_versions     its revisions (Draft -> Active -> Archived)
  payroll_payslip_template_assignments  which published version the org's
      payslips use, per country or for every country ('ALL')
  payslip_items.template_version_id     the version frozen onto a payslip when
      its run is approved (NULL = the standard statutory payslip)

No seed rows: the built-in starter layouts live in code and are copied into an
organisation when it picks one, so nothing here is shared between tenants.

RLS (d7f9b1c3e5a6 classify): all three tables TENANT. PostgreSQL only;
literal names; lock_timeout; idempotent both ways.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f3a9c1d7e2b4"
down_revision: Union[str, Sequence[str], None] = "e7ec6c1933b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TEMPLATES = "payroll_payslip_templates"
VERSIONS = "payroll_payslip_template_versions"
ASSIGNMENTS = "payroll_payslip_template_assignments"

TENANT_TABLES = (TEMPLATES, VERSIONS, ASSIGNMENTS)
_TABLES = (ASSIGNMENTS, VERSIONS, TEMPLATES)   # drop order


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _has_table(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table, name):
    return _has_table(table) and name in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _has_index(table, name):
    return _has_table(table) and name in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def _index(table, name, cols, unique=False):
    if not _has_index(table, name):
        op.create_index(name, table, cols, unique=unique)


def _rls_module():
    path = Path(__file__).with_name("d7f9b1c3e5a6_postgres_row_level_security.py")
    spec = importlib.util.spec_from_file_location("zp_rls_d7f9", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rls_for_new_tables(bind) -> None:
    """Give each table this revision creates the policy d7f9b1c3e5a6 derives."""
    rls = _rls_module()
    for table in TENANT_TABLES:
        predicate = rls._TENANT_PREDICATE
        rls._sql(bind, f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        rls._sql(bind, f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        rls._sql(bind, f'DROP POLICY IF EXISTS {rls.POLICY} ON "{table}"')
        rls._sql(bind, f'CREATE POLICY {rls.POLICY} ON "{table}" USING {predicate} WITH CHECK {predicate}')


def upgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    # 1) payroll_payslip_templates (TENANT)
    if not _has_table(TEMPLATES):
        op.create_table(
            "payroll_payslip_templates",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(),
                      sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("code", sa.String(60), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("jurisdiction_country", sa.String(10), nullable=True),
            sa.Column("source_starter", sa.String(60), nullable=True),
            sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("organization_id", "code", name="uq_payslip_template_org_code"),
        )
    _index(TEMPLATES, f"ix_{TEMPLATES}_id", ["id"])
    _index(TEMPLATES, f"ix_{TEMPLATES}_organization_id", ["organization_id"])

    # 2) payroll_payslip_template_versions (TENANT)
    if not _has_table(VERSIONS):
        op.create_table(
            "payroll_payslip_template_versions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(),
                      sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("template_id", sa.Integer(),
                      sa.ForeignKey(f"{TEMPLATES}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(10), nullable=False, server_default="Draft"),
            sa.Column("html_content", sa.Text(), nullable=False),
            sa.Column("css_content", sa.Text(), nullable=True),
            sa.Column("configuration_json", sa.JSON(), nullable=True),
            sa.Column("change_summary", sa.String(300), nullable=True),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("published_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("template_id", "version_number", name="uq_payslip_template_version"),
            sa.CheckConstraint("status IN ('Draft', 'Active', 'Archived')", name="ck_payslip_template_version_status"),
        )
    _index(VERSIONS, f"ix_{VERSIONS}_id", ["id"])
    _index(VERSIONS, f"ix_{VERSIONS}_organization_id", ["organization_id"])
    _index(VERSIONS, f"ix_{VERSIONS}_template_id", ["template_id"])
    _index(VERSIONS, "ix_payslip_template_version_status", ["template_id", "status"])

    # 3) payroll_payslip_template_assignments (TENANT)
    if not _has_table(ASSIGNMENTS):
        op.create_table(
            "payroll_payslip_template_assignments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(),
                      sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("jurisdiction_country", sa.String(10), nullable=False, server_default="ALL"),
            sa.Column("template_id", sa.Integer(),
                      sa.ForeignKey(f"{TEMPLATES}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("version_id", sa.Integer(),
                      sa.ForeignKey(f"{VERSIONS}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("assigned_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("organization_id", "jurisdiction_country", name="uq_payslip_template_assignment"),
        )
    _index(ASSIGNMENTS, f"ix_{ASSIGNMENTS}_id", ["id"])
    _index(ASSIGNMENTS, f"ix_{ASSIGNMENTS}_organization_id", ["organization_id"])
    _index(ASSIGNMENTS, f"ix_{ASSIGNMENTS}_template_id", ["template_id"])

    # 4) payslip_items.template_version_id
    if _has_table("payslip_items") and not _has_column("payslip_items", "template_version_id"):
        with op.batch_alter_table("payslip_items") as batch:
            batch.add_column(sa.Column("template_version_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                "fk_payslip_items_template_version_id", VERSIONS,
                ["template_version_id"], ["id"], ondelete="SET NULL",
            )
    _index("payslip_items", "ix_payslip_items_template_version_id", ["template_version_id"])

    if _postgres():
        _rls_for_new_tables(op.get_bind())


def downgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    if _has_column("payslip_items", "template_version_id"):
        if _has_index("payslip_items", "ix_payslip_items_template_version_id"):
            op.drop_index("ix_payslip_items_template_version_id", table_name="payslip_items")
        with op.batch_alter_table("payslip_items") as batch:
            if _postgres():
                batch.drop_constraint("fk_payslip_items_template_version_id", type_="foreignkey")
            batch.drop_column("template_version_id")
    for table in _TABLES:
        if _has_table(table):
            op.drop_table(table)
