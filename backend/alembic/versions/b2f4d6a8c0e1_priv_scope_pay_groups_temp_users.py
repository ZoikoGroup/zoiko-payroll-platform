"""privacy scope model: roles, temporary users, pay groups, user scope (ZP-PRIV A.1 / C.1 / D.2)

Revision ID: b2f4d6a8c0e1
Revises: a7c3e91f2b60
Create Date: 2026-10-19

* userrole enum: SUPPORT_OPERATOR, PLATFORM_SECURITY, SUPPORT_TEMP (EMPLOYEE
  already exists in the baseline type). Values are added outside the
  migration transaction (ALTER TYPE ... ADD VALUE cannot be used in the
  same transaction that adds it).
* users: access_expires_at, is_temporary, support_grant_id,
  self_service_employee_id.
* pay_groups, user_scope_assignments (new).
* payroll_employees: legal_entity_id, pay_group_id.

Backfill (conservative, no guessing):
  * every organization gets one default pay group "Default"; every employee
    of that organization is placed in it;
  * legal_entity_id is set ONLY where the organization has exactly one
    legal entity. An organization with none or several keeps NULL — a
    scoped payroll admin then cannot see those workers until an org admin
    assigns them (fail closed); org admins see them as before.
No legal entity is created: legal entities count against the plan's
max_entities limit, so inventing one could put a tenant over its limit.
"""

import sqlalchemy as sa
from alembic import op

revision = "b2f4d6a8c0e1"
down_revision = "a7c3e91f2b60"
branch_labels = None
depends_on = None

_NEW_ROLES = ("SUPPORT_OPERATOR", "PLATFORM_SECURITY", "SUPPORT_TEMP")


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        with op.get_context().autocommit_block():
            for value in _NEW_ROLES + ("EMPLOYEE",):
                op.execute(f"ALTER TYPE userrole ADD VALUE IF NOT EXISTS '{value}'")

    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("access_expires_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("is_temporary", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("support_grant_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("self_service_employee_id", sa.Integer(), nullable=True))
    op.create_index("ix_users_support_grant_id", "users", ["support_grant_id"])

    op.create_table(
        "pay_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("legal_entity_id", sa.Integer(),
                  sa.ForeignKey("legal_entities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "name", name="uq_pay_groups_org_name"),
    )
    op.create_index("ix_pay_groups_organization_id", "pay_groups", ["organization_id"])
    op.create_index("ix_pay_groups_legal_entity_id", "pay_groups", ["legal_entity_id"])

    op.create_table(
        "user_scope_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.Integer(),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("legal_entity_id", sa.Integer(),
                  sa.ForeignKey("legal_entities.id", ondelete="CASCADE"), nullable=True),
        sa.Column("pay_group_id", sa.Integer(),
                  sa.ForeignKey("pay_groups.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "(legal_entity_id IS NOT NULL AND pay_group_id IS NULL) OR "
            "(legal_entity_id IS NULL AND pay_group_id IS NOT NULL)",
            name="ck_user_scope_exactly_one_target",
        ),
        sa.UniqueConstraint("user_id", "legal_entity_id", "pay_group_id", name="uq_user_scope_target"),
    )
    for col in ("user_id", "organization_id", "legal_entity_id", "pay_group_id"):
        op.create_index(f"ix_user_scope_assignments_{col}", "user_scope_assignments", [col])

    with op.batch_alter_table("payroll_employees") as batch:
        batch.add_column(sa.Column("legal_entity_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("pay_group_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_payroll_employees_legal_entity", "legal_entities",
                                 ["legal_entity_id"], ["id"], ondelete="SET NULL")
        batch.create_foreign_key("fk_payroll_employees_pay_group", "pay_groups",
                                 ["pay_group_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_payroll_employees_legal_entity_id", "payroll_employees", ["legal_entity_id"])
    op.create_index("ix_payroll_employees_pay_group_id", "payroll_employees", ["pay_group_id"])

    # ── Backfill ────────────────────────────────────────────────────────────
    op.execute("""
        INSERT INTO pay_groups (organization_id, name, is_default, is_active, created_at, updated_at)
        SELECT o.id, 'Default', true, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM organizations o
        WHERE NOT EXISTS (SELECT 1 FROM pay_groups g WHERE g.organization_id = o.id AND g.is_default = true)
    """)
    op.execute("""
        UPDATE payroll_employees SET pay_group_id = (
            SELECT g.id FROM pay_groups g
            WHERE g.organization_id = payroll_employees.organization_id AND g.is_default = true
        )
        WHERE pay_group_id IS NULL
    """)
    op.execute("""
        UPDATE payroll_employees SET legal_entity_id = (
            SELECT MIN(le.id) FROM legal_entities le
            WHERE le.organization_id = payroll_employees.organization_id
        )
        WHERE legal_entity_id IS NULL
          AND (SELECT COUNT(*) FROM legal_entities le2
               WHERE le2.organization_id = payroll_employees.organization_id) = 1
    """)


def downgrade() -> None:
    op.drop_index("ix_payroll_employees_pay_group_id", table_name="payroll_employees")
    op.drop_index("ix_payroll_employees_legal_entity_id", table_name="payroll_employees")
    with op.batch_alter_table("payroll_employees") as batch:
        batch.drop_constraint("fk_payroll_employees_pay_group", type_="foreignkey")
        batch.drop_constraint("fk_payroll_employees_legal_entity", type_="foreignkey")
        batch.drop_column("pay_group_id")
        batch.drop_column("legal_entity_id")
    for col in ("pay_group_id", "legal_entity_id", "organization_id", "user_id"):
        op.drop_index(f"ix_user_scope_assignments_{col}", table_name="user_scope_assignments")
    op.drop_table("user_scope_assignments")
    op.drop_index("ix_pay_groups_legal_entity_id", table_name="pay_groups")
    op.drop_index("ix_pay_groups_organization_id", table_name="pay_groups")
    op.drop_table("pay_groups")
    op.drop_index("ix_users_support_grant_id", table_name="users")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("self_service_employee_id")
        batch.drop_column("support_grant_id")
        batch.drop_column("is_temporary")
        batch.drop_column("access_expires_at")
    # Enum values cannot be removed from a PostgreSQL type; they stay unused.
