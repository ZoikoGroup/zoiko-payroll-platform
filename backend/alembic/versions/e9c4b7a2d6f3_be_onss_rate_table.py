"""be_onss_rate_table: Belgium ONSS rate table (Block M-ECWC)

Revision ID: e9c4b7a2d6f3
Revises: e3f9a7c1b5d2
Create Date: 2026-11-16

ZP-BE-ENG-001 Block M-ECWC. Additive only; nothing existing changes meaning.

New platform tables (no organisation, so no row-level-security policy — like payroll_source_artifacts):
  payroll_be_onss_rate_files         one archived quarterly ONSS DmfA rate file per pack and quarter; registered by
      one Super Admin, ATTESTED authentic (checksum-bound) by another (four-eyes CHECK).
  payroll_be_onss_rates              its records: employer category x code (kind) x ContributionType -> personal /
      employer / wage-moderation / total rate, flat flag, quarterly minimum. REFERENCE by default; the supported
      subset is made PENDING by one Super Admin and SIGNED by another (four-eyes CHECK).
  payroll_be_onss_code_combinations  which contribution codes combine with a worker code (same states).
  payroll_be_onss_type_rules         signed rules selecting a code's ContributionType from the facts (four-eyes).
Every code column is TEXT ("000", "015"), never a number.

New columns on payroll_be_employer_registrations (each UNKNOWN by default, which blocks the rate table):
  closure_fund_sector / workforce_class / wage_moderation_status, each with its *_evidence_ref.

No statutory value appears anywhere. Literal names, lock_timeout, idempotent both ways; the downgrade drops only
what this revision added.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e9c4b7a2d6f3"
down_revision: Union[str, Sequence[str], None] = "e3f9a7c1b5d2"   # main's merge of Mexico + Malaysia with Block K
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FILES = "payroll_be_onss_rate_files"
RATES = "payroll_be_onss_rates"
COMBS = "payroll_be_onss_code_combinations"
RULES = "payroll_be_onss_type_rules"
EMPLOYER = "payroll_be_employer_registrations"
FACTS = (("closure_fund_sector", "closure_fund_sector_evidence_ref",
          ("COMMERCIAL", "NON_COMMERCIAL", "NOT_SUBJECT", "UNKNOWN"), "ck_be_employer_closure_fund_sector"),
         ("workforce_class", "workforce_class_evidence_ref",
          ("UNDER_10", "FROM_10_TO_19", "FROM_20", "UNKNOWN"), "ck_be_employer_workforce_class"),
         ("wage_moderation_status", "wage_moderation_evidence_ref",
          ("APPLIES", "NOT_APPLICABLE", "UNKNOWN"), "ck_be_employer_wage_moderation"))


def _in(values) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _has_table(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table, column):
    return _has_table(table) and column in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _has_index(table, name):
    return _has_table(table) and name in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def _user(name):
    return sa.Column(name, sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


def upgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    if not _has_table(FILES):
        op.create_table(
            "payroll_be_onss_rate_files",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("jurisdiction_pack_id", sa.Integer(),
                      sa.ForeignKey("payroll_jurisdiction_packs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("quarter", sa.String(length=5), nullable=False),
            sa.Column("effective_from", sa.Date(), nullable=False),
            sa.Column("effective_to", sa.Date(), nullable=False),
            sa.Column("source_document_id", sa.Integer(),
                      sa.ForeignKey("payroll_source_artifacts.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
            sa.Column("reference_rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(length=10), nullable=False, server_default="PENDING"),
            _user("registered_by_id"),
            sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            _user("attested_by_id"),
            sa.Column("attested_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("attestation_reason", sa.String(length=300), nullable=True),
            sa.CheckConstraint("status IN ('PENDING', 'ATTESTED', 'REJECTED')", name="ck_be_onss_file_status"),
            sa.CheckConstraint("status = 'PENDING' OR (attested_by_id IS NOT NULL AND attested_at IS NOT NULL AND "
                               "(registered_by_id IS NULL OR attested_by_id <> registered_by_id))",
                               name="ck_be_onss_file_four_eyes"),
            sa.CheckConstraint("effective_to >= effective_from", name="ck_be_onss_file_window"),
            sa.UniqueConstraint("jurisdiction_pack_id", "quarter", name="uq_be_onss_file_pack_quarter"),
        )
    if not _has_index(FILES, "ix_payroll_be_onss_rate_files_id"):
        op.create_index("ix_payroll_be_onss_rate_files_id", "payroll_be_onss_rate_files", ["id"])

    if not _has_table(RATES):
        op.create_table(
            "payroll_be_onss_rates",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("rate_file_id", sa.Integer(),
                      sa.ForeignKey("payroll_be_onss_rate_files.id", ondelete="CASCADE"), nullable=False),
            sa.Column("employer_class", sa.String(length=3), nullable=False),
            sa.Column("code_kind", sa.String(length=12), nullable=False),
            sa.Column("code", sa.String(length=3), nullable=False),
            sa.Column("contribution_type", sa.String(length=1), nullable=False),
            sa.Column("personal_rate", sa.Numeric(12, 6), nullable=True),
            sa.Column("employer_rate", sa.Numeric(12, 6), nullable=True),
            sa.Column("moderation_rate", sa.Numeric(12, 6), nullable=True),
            sa.Column("total_rate", sa.Numeric(12, 6), nullable=True),
            sa.Column("is_flat", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("minimum_flat", sa.Numeric(14, 2), nullable=True),
            sa.Column("file_status", sa.String(length=10), nullable=True),
            sa.Column("status", sa.String(length=10), nullable=False, server_default="REFERENCE"),
            _user("marked_live_by_id"),
            sa.Column("marked_live_at", sa.DateTime(timezone=True), nullable=True),
            _user("signed_by_id"),
            sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("sign_reason", sa.String(length=300), nullable=True),
            sa.CheckConstraint("status IN ('REFERENCE', 'PENDING', 'SIGNED')", name="ck_be_onss_rate_status"),
            sa.CheckConstraint("code_kind IN ('WORKER', 'CONTRIBUTION', 'UNRELATED')",
                               name="ck_be_onss_rate_code_kind"),
            sa.CheckConstraint("status <> 'SIGNED' OR (signed_by_id IS NOT NULL AND signed_at IS NOT NULL AND "
                               "(marked_live_by_id IS NULL OR signed_by_id <> marked_live_by_id))",
                               name="ck_be_onss_rate_four_eyes"),
            sa.UniqueConstraint("rate_file_id", "employer_class", "code_kind", "code", "contribution_type",
                                name="uq_be_onss_rate_key"),
        )
    if not _has_index(RATES, "ix_payroll_be_onss_rates_id"):
        op.create_index("ix_payroll_be_onss_rates_id", "payroll_be_onss_rates", ["id"])
    if not _has_index(RATES, "ix_be_onss_rate_lookup"):
        op.create_index("ix_be_onss_rate_lookup", "payroll_be_onss_rates",
                        ["rate_file_id", "employer_class", "code", "status"])

    if not _has_table(COMBS):
        op.create_table(
            "payroll_be_onss_code_combinations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("rate_file_id", sa.Integer(),
                      sa.ForeignKey("payroll_be_onss_rate_files.id", ondelete="CASCADE"), nullable=False),
            sa.Column("employer_class", sa.String(length=3), nullable=False),
            sa.Column("worker_code", sa.String(length=3), nullable=False),
            sa.Column("contribution_code", sa.String(length=3), nullable=False),
            sa.Column("owedness_code", sa.String(length=1), nullable=True),
            sa.Column("status", sa.String(length=10), nullable=False, server_default="REFERENCE"),
            _user("marked_live_by_id"),
            sa.Column("marked_live_at", sa.DateTime(timezone=True), nullable=True),
            _user("signed_by_id"),
            sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("sign_reason", sa.String(length=300), nullable=True),
            sa.CheckConstraint("status IN ('REFERENCE', 'PENDING', 'SIGNED')", name="ck_be_onss_comb_status"),
            sa.CheckConstraint("status <> 'SIGNED' OR (signed_by_id IS NOT NULL AND signed_at IS NOT NULL AND "
                               "(marked_live_by_id IS NULL OR signed_by_id <> marked_live_by_id))",
                               name="ck_be_onss_comb_four_eyes"),
            sa.UniqueConstraint("rate_file_id", "employer_class", "worker_code", "contribution_code",
                                name="uq_be_onss_comb_key"),
        )
    if not _has_index(COMBS, "ix_payroll_be_onss_code_combinations_id"):
        op.create_index("ix_payroll_be_onss_code_combinations_id", "payroll_be_onss_code_combinations", ["id"])

    if not _has_table(RULES):
        op.create_table(
            "payroll_be_onss_type_rules",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("jurisdiction_pack_id", sa.Integer(),
                      sa.ForeignKey("payroll_jurisdiction_packs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("code", sa.String(length=3), nullable=False),
            sa.Column("pay_basis", sa.String(length=40), nullable=False, server_default="ANY"),
            sa.Column("closure_fund_sector", sa.String(length=60), nullable=False, server_default="ANY"),
            sa.Column("workforce_class", sa.String(length=60), nullable=False, server_default="ANY"),
            sa.Column("wage_moderation", sa.String(length=40), nullable=False, server_default="ANY"),
            sa.Column("outcome", sa.String(length=8), nullable=False),
            sa.Column("effective_from", sa.Date(), nullable=False),
            sa.Column("effective_to", sa.Date(), nullable=True),
            sa.Column("source_document_id", sa.Integer(),
                      sa.ForeignKey("payroll_source_artifacts.id", ondelete="SET NULL"), nullable=True),
            sa.Column("note", sa.String(length=300), nullable=True),
            sa.Column("status", sa.String(length=10), nullable=False, server_default="PENDING"),
            _user("created_by_id"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            _user("signed_by_id"),
            sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("sign_reason", sa.String(length=300), nullable=True),
            sa.CheckConstraint("status IN ('PENDING', 'SIGNED')", name="ck_be_onss_type_rule_status"),
            sa.CheckConstraint("status <> 'SIGNED' OR (signed_by_id IS NOT NULL AND signed_at IS NOT NULL AND "
                               "(created_by_id IS NULL OR signed_by_id <> created_by_id))",
                               name="ck_be_onss_type_rule_four_eyes"),
            sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from",
                               name="ck_be_onss_type_rule_window"),
        )
    if not _has_index(RULES, "ix_payroll_be_onss_type_rules_id"):
        op.create_index("ix_payroll_be_onss_type_rules_id", "payroll_be_onss_type_rules", ["id"])
    if not _has_index(RULES, "ix_be_onss_type_rule_code"):
        op.create_index("ix_be_onss_type_rule_code", "payroll_be_onss_type_rules", ["jurisdiction_pack_id", "code"])

    # Employer facts (each UNKNOWN by default: the rate table blocks until a fact and its evidence are recorded).
    # Literal op.add_column calls (scripts/drift_pending_filter reads them); each CHECK travels with its column.
    if not _has_column(EMPLOYER, "closure_fund_sector"):
        op.add_column("payroll_be_employer_registrations", sa.Column(
            "closure_fund_sector", sa.String(16),
            sa.CheckConstraint(f"closure_fund_sector IN {_in(FACTS[0][2])}", name="ck_be_employer_closure_fund_sector"),
            nullable=False, server_default="UNKNOWN"))
    if not _has_column(EMPLOYER, "closure_fund_sector_evidence_ref"):
        op.add_column("payroll_be_employer_registrations", sa.Column("closure_fund_sector_evidence_ref",
                                                                     sa.String(300), nullable=True))
    if not _has_column(EMPLOYER, "workforce_class"):
        op.add_column("payroll_be_employer_registrations", sa.Column(
            "workforce_class", sa.String(16),
            sa.CheckConstraint(f"workforce_class IN {_in(FACTS[1][2])}", name="ck_be_employer_workforce_class"),
            nullable=False, server_default="UNKNOWN"))
    if not _has_column(EMPLOYER, "workforce_class_evidence_ref"):
        op.add_column("payroll_be_employer_registrations", sa.Column("workforce_class_evidence_ref",
                                                                     sa.String(300), nullable=True))
    if not _has_column(EMPLOYER, "wage_moderation_status"):
        op.add_column("payroll_be_employer_registrations", sa.Column(
            "wage_moderation_status", sa.String(16),
            sa.CheckConstraint(f"wage_moderation_status IN {_in(FACTS[2][2])}", name="ck_be_employer_wage_moderation"),
            nullable=False, server_default="UNKNOWN"))
    if not _has_column(EMPLOYER, "wage_moderation_evidence_ref"):
        op.add_column("payroll_be_employer_registrations", sa.Column("wage_moderation_evidence_ref",
                                                                     sa.String(300), nullable=True))


def downgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    columns = [c for fact in FACTS for c in (fact[1], fact[0]) if _has_column(EMPLOYER, c)]
    if columns:
        if _postgres():
            for column in columns:
                op.drop_column(EMPLOYER, column)
        else:
            # SQLite's table rebuild would otherwise carry a reflected CHECK naming a dropped column.
            reflected = {c.get("name") for c in sa.inspect(op.get_bind()).get_check_constraints(EMPLOYER)}
            with op.batch_alter_table(EMPLOYER) as batch:
                for name in (fact[3] for fact in FACTS):
                    if name in reflected:
                        batch.drop_constraint(name, type_="check")
                for column in columns:
                    batch.drop_column(column)
    for table in (RULES, COMBS, RATES, FILES):
        if _has_table(table):
            op.drop_table(table)
