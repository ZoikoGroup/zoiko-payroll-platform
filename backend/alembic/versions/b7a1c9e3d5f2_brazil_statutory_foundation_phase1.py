"""brazil_statutory_foundation_phase1

Revision ID: b7a1c9e3d5f2
Revises: 8b2f6d4e1a93
Create Date: 2026-10-15

Foundation tables for Brazil (CLT) Payroll (ZP-BR-ENG-001), Phase 0:
1. payroll_br_employer_profiles (CNPJ root, tax classification, CNAE, CPRB, eSocial S-1.3)
2. payroll_br_establishments (establishment CNPJ, RAT, FAP, FPAS, third-party rates)
3. payroll_br_rubrics (eSocial Table 03 nature and multi-dimensional statutory incidence)
4. payroll_br_statutory_profiles (employee contract, CBO, category, dependants, Vale-Transporte)
5. br_* statutory snapshot columns + br_calculation_snapshot on payslip_items

Every CHECK / UNIQUE constraint and index here matches models.py exactly
(index names are SQLAlchemy's index=True defaults, ix_<table>_<column>).
Boolean defaults use sa.false() — an integer default is rejected by Postgres.
No row is written: the tables stay empty until Brazil onboarding (Phase 3).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7a1c9e3d5f2"
down_revision: Union[str, Sequence[str], None] = "8b2f6d4e1a93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BR_PAYSLIP_AMOUNT_COLUMNS = (
    "br_base_inss", "br_inss_employee", "br_base_irrf", "br_irrf", "br_irrf_reduction",
    "br_salario_familia", "br_vale_transporte_deduction", "br_base_fgts", "br_fgts_deposit",
    "br_cpp_employer", "br_rat_adjusted", "br_third_parties",
)


def _table_exists(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _column_exists(table_name: str, col_name: str) -> bool:
    return col_name in [c["name"] for c in sa.inspect(op.get_bind()).get_columns(table_name)]


def _index(table: str, column: str) -> None:
    op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    # 1. payroll_br_employer_profiles
    if not _table_exists("payroll_br_employer_profiles"):
        op.create_table(
            "payroll_br_employer_profiles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("cnpj_root", sa.String(8), nullable=False),
            sa.Column("legal_name", sa.String(255), nullable=False),
            sa.Column("trade_name", sa.String(255), nullable=True),
            sa.Column("tax_classification", sa.String(2), nullable=False),
            sa.Column("cnae_preponderant", sa.String(7), nullable=False),
            sa.Column("cprb_opted", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("cprb_rate_pct", sa.Numeric(5, 2), nullable=True),
            sa.Column("esocial_environment", sa.String(25), nullable=False, server_default="RESTRICTED_PRODUCTION"),
            sa.Column("esocial_active_version", sa.String(10), nullable=False, server_default="S-1.3"),
            sa.Column("esocial_cert_alias", sa.String(255), nullable=True),
            sa.Column("contact_name", sa.String(120), nullable=False),
            sa.Column("contact_cpf", sa.String(11), nullable=False),
            sa.Column("contact_email", sa.String(120), nullable=False),
            sa.Column("contact_phone", sa.String(20), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("organization_id", name="uq_br_employer_org"),
            sa.CheckConstraint("esocial_environment IN ('PRODUCTION', 'RESTRICTED_PRODUCTION')",
                               name="ck_br_employer_env"),
            sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'SUSPENDED')", name="ck_br_employer_status"),
        )
        _index("payroll_br_employer_profiles", "id")
        _index("payroll_br_employer_profiles", "organization_id")

    # 2. payroll_br_establishments
    if not _table_exists("payroll_br_establishments"):
        op.create_table(
            "payroll_br_establishments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("employer_profile_id", sa.Integer(),
                      sa.ForeignKey("payroll_br_employer_profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("cnpj", sa.String(14), nullable=False),
            sa.Column("establishment_name", sa.String(255), nullable=False),
            sa.Column("is_headquarters", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("cnae", sa.String(7), nullable=False),
            sa.Column("rat_pct", sa.Numeric(4, 2), nullable=False),
            sa.Column("fap_factor", sa.Numeric(5, 4), nullable=False, server_default="1.0000"),
            sa.Column("fpas_code", sa.String(3), nullable=False),
            sa.Column("third_party_code", sa.String(4), nullable=False),
            sa.Column("third_party_pct", sa.Numeric(5, 2), nullable=False),
            sa.Column("lotacao_code", sa.String(30), nullable=False),
            sa.Column("postal_code", sa.String(8), nullable=False),
            sa.Column("street_address", sa.String(255), nullable=False),
            sa.Column("neighborhood", sa.String(100), nullable=False),
            sa.Column("city_ibge_code", sa.String(7), nullable=False),
            sa.Column("state_uf", sa.String(2), nullable=False),
            sa.Column("judicial_process_id", sa.String(50), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("employer_profile_id", "cnpj", name="uq_br_establishment_employer_cnpj"),
            sa.CheckConstraint("rat_pct IN (1.00, 2.00, 3.00)", name="ck_br_establishment_rat"),
            sa.CheckConstraint("fap_factor >= 0.5000 AND fap_factor <= 2.0000", name="ck_br_establishment_fap"),
        )
        _index("payroll_br_establishments", "id")
        _index("payroll_br_establishments", "employer_profile_id")
        _index("payroll_br_establishments", "cnpj")

    # 3. payroll_br_rubrics
    if not _table_exists("payroll_br_rubrics"):
        op.create_table(
            "payroll_br_rubrics",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("rubric_code", sa.String(30), nullable=False),
            sa.Column("rubric_name", sa.String(255), nullable=False),
            sa.Column("nature_code", sa.String(4), nullable=False),
            sa.Column("rubric_type", sa.String(15), nullable=False),
            sa.Column("cod_inc_cp", sa.String(2), nullable=False),
            sa.Column("cod_inc_irrf", sa.String(2), nullable=False),
            sa.Column("cod_inc_fgts", sa.String(2), nullable=False),
            sa.Column("is_system_standard", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("version", sa.SmallInteger(), nullable=False, server_default="1"),
            sa.Column("valid_from", sa.Date(), nullable=False),
            sa.Column("valid_to", sa.Date(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("organization_id", "rubric_code", "version", name="uq_br_rubric_org_code_ver"),
            sa.CheckConstraint("rubric_type IN ('EARNING', 'DEDUCTION', 'INFORMATIONAL')", name="ck_br_rubric_type"),
        )
        _index("payroll_br_rubrics", "id")
        _index("payroll_br_rubrics", "organization_id")
        op.create_index("ix_br_rubric_lookup", "payroll_br_rubrics", ["organization_id", "rubric_code", "valid_from"])

    # 4. payroll_br_statutory_profiles
    if not _table_exists("payroll_br_statutory_profiles"):
        op.create_table(
            "payroll_br_statutory_profiles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("employee_id", sa.Integer(), sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("establishment_id", sa.Integer(),
                      sa.ForeignKey("payroll_br_establishments.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("effective_from", sa.Date(), nullable=False),
            sa.Column("effective_to", sa.Date(), nullable=True),
            sa.Column("esocial_category", sa.String(3), nullable=False, server_default="101"),
            sa.Column("cbo_code", sa.String(6), nullable=False),
            sa.Column("contract_type", sa.String(20), nullable=False, server_default="INDEFINITE"),
            sa.Column("weekly_hours", sa.Numeric(4, 2), nullable=False, server_default="44.00"),
            sa.Column("concurrent_inss_flag", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("concurrent_inss_base_external", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
            sa.Column("concurrent_inss_deducted_external", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
            sa.Column("irrf_dependents_count", sa.SmallInteger(), nullable=False, server_default="0"),
            sa.Column("salario_familia_dependents_count", sa.SmallInteger(), nullable=False, server_default="0"),
            sa.Column("simplified_irrf_opt_out", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("alimony_deduction_fixed", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
            sa.Column("alimony_deduction_pct", sa.Numeric(5, 2), nullable=False, server_default="0.00"),
            sa.Column("vale_transporte_elected", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("vale_transporte_daily_cost", sa.Numeric(8, 2), nullable=False, server_default="0.00"),
            sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.CheckConstraint("contract_type IN ('INDEFINITE', 'DETERMINED', 'INTERMITTENT')",
                               name="ck_br_contract_type"),
            sa.CheckConstraint("esocial_category IN ('101', '103')", name="ck_br_stat_profile_category"),
            sa.CheckConstraint("weekly_hours > 0 AND weekly_hours <= 44", name="ck_br_stat_profile_weekly_hours"),
            sa.CheckConstraint("status IN ('ACTIVE', 'ON_LEAVE', 'TERMINATED')", name="ck_br_stat_profile_status"),
        )
        _index("payroll_br_statutory_profiles", "id")
        _index("payroll_br_statutory_profiles", "employee_id")
        _index("payroll_br_statutory_profiles", "establishment_id")
        op.create_index("ix_br_stat_profile_emp_dates", "payroll_br_statutory_profiles",
                        ["employee_id", "effective_from", "effective_to"])

    # 5. payslip_items: flat br_* amounts + the frozen BR calculation snapshot
    for col_name in _BR_PAYSLIP_AMOUNT_COLUMNS:
        if not _column_exists("payslip_items", col_name):
            op.add_column("payslip_items", sa.Column(col_name, sa.Numeric(12, 2), nullable=True, server_default="0"))
    if not _column_exists("payslip_items", "br_calculation_snapshot"):
        json_type = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")
        op.add_column("payslip_items", sa.Column("br_calculation_snapshot", json_type, nullable=True))


def downgrade() -> None:
    # Each step is guarded so a partly-applied upgrade still downgrades cleanly.
    for col_name in ("br_calculation_snapshot",) + _BR_PAYSLIP_AMOUNT_COLUMNS:
        if _column_exists("payslip_items", col_name):
            op.drop_column("payslip_items", col_name)
    for table in ("payroll_br_statutory_profiles", "payroll_br_rubrics",
                  "payroll_br_establishments", "payroll_br_employer_profiles"):
        if _table_exists(table):
            op.drop_table(table)  # its indexes and constraints go with it
