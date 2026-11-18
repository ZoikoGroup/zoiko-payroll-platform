"""report_template_content_editor: payroll_report_templates.content_editor_id

Revision ID: d7a3f1c9e5b2
Revises: c3e8a1d5f7b2
Create Date: 2026-11-18

MAKER-CHECKER CHANGE — requires ZP-PRIV review (Rugvedh) before merge.

The report-template four-eyes rules compared the approver with updated_by_id, which every STATUS change overwrote.
An approver who clicked Published became the "editor", so approver == editor refused Active for everyone (the
Published trap). This adds the last CONTENT editor (metadata, components, fields); status changes and Approve never
set it, and service.report_template_four_eyes_refusal reads it.

Additive only: one nullable column (FK users, ON DELETE SET NULL). Backfill from the AUDIT LOG only — never from
updated_by_id (on the trapped rows that is the approver who clicked Published): per template, the actor of its
LATEST content-change audit row (payroll_tax_configuration_audit: report_template create / update / new_version other
than the "Approver set" row, or any report_template_component / report_template_field row). That actor is NULL when
the seed wrote the content (seed_statutory_report_templates runs with actor None); a template with no content-change
row at all is the seed's too: NULL. NULL = no human content editor, so no Super Admin is "the author".
No status is changed: activation stays a manual, four-eyes step.
Rows already filled are left alone (idempotent). Literal names, lock_timeout; the downgrade drops only this column.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d7a3f1c9e5b2"
down_revision: Union[str, Sequence[str], None] = "c3e8a1d5f7b2"   # tax_slabs.tax_regime VARCHAR(40)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "payroll_report_templates"
COLUMN = "content_editor_id"
FK = "fk_report_templates_content_editor_id_users"
AUDIT = "payroll_tax_configuration_audit"

_CONTENT_AUDIT = (
    f"a.entity_id = {TABLE}.id AND ("
    " a.entity_type IN ('report_template_component', 'report_template_field')"
    " OR (a.entity_type = 'report_template' AND a.action IN ('create', 'update', 'new_version')"
    "     AND (a.reason IS NULL OR a.reason <> 'Approver set')))"
)


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _has_table(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table, column):
    return _has_table(table) and column in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    if not _has_table(TABLE):
        return
    if not _has_column(TABLE, COLUMN):
        if _postgres():
            op.add_column(TABLE, sa.Column(COLUMN, sa.Integer(), nullable=True))
            op.create_foreign_key(FK, TABLE, "users", [COLUMN], ["id"], ondelete="SET NULL")
        else:   # SQLite: no ALTER ADD CONSTRAINT; the column alone (create_all builds the FK for new databases)
            op.add_column(TABLE, sa.Column(COLUMN, sa.Integer(), nullable=True))
    if not _has_table(AUDIT):
        return   # no audit log: nothing to derive from; NULL = no human content editor
    # The latest content change's actor (NULL when the seed wrote it, or when there is none).
    op.get_bind().execute(sa.text(
        f"UPDATE {TABLE} SET {COLUMN} = ("
        f" SELECT a.actor_id FROM {AUDIT} a WHERE {_CONTENT_AUDIT}"
        f" ORDER BY a.created_at DESC, a.id DESC LIMIT 1)"
        f" WHERE {COLUMN} IS NULL"
    ))


def downgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    if not _has_column(TABLE, COLUMN):
        return
    if _postgres():
        fks = {fk["name"] for fk in sa.inspect(op.get_bind()).get_foreign_keys(TABLE)}
        if FK in fks:
            op.drop_constraint(FK, TABLE, type_="foreignkey")
        op.drop_column(TABLE, COLUMN)
    else:
        with op.batch_alter_table(TABLE) as batch:
            batch.drop_column(COLUMN)
