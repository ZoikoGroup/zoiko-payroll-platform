"""add switzerland jurisdiction support

Revision ID: 3baddbaa011a
Revises: d7e6f5a4b3c2
Create Date: 2026-10-06 00:00:00.000000

Switzerland (CH) jurisdiction data model — the CH equipment layer only: no
calculation or engine code changes anywhere. Strictly ADDITIVE, matching the
7a1b2c3d4e5f Italy precedent: no existing column or table is altered or
dropped, and every new column is nullable so every pre-existing row keeps its
exact current behavior.

Chains directly off d7e6f5a4b3c2 (the single current head, confirmed by
`alembic heads`), so the graph stays linear with one head.

What this revision adds:

1. Seven new CH tables
      payroll_ch_scheme_profiles            — authority scheme registry
      payroll_ch_entity_profiles            — 1:1 org-level CH employer profile
      payroll_ch_qst_tariff_files           — canonical (per-canton) QST tariff files
      payroll_ch_qst_tariff_rows            — one bracket row per tariff file
      payroll_ch_family_allowance_entitlements — per-child FAK entitlement decision
      payroll_ch_absence_benefit_events     — daily-allowance events (CO/KTG/UVG/...)
      payroll_ch_elm_submissions            — idempotent ELM submission envelopes

2. 29 nullable ch_* columns on payroll_employee_statutory_profiles
   (§employee onboarding): work/residence/QST canton, residence country,
   nationality, permit type, cross-border flag, AHV number/status, ALV
   liability, weekly hours, multiple-employment facts, QST subject +
   tariff code, marital/household facts, church tax, the BVG/UVG/KTG scheme
   assignments (FK -> payroll_ch_scheme_profiles), UVG risk class, contract
   end, wage-floor agreement (FK -> payroll_collective_agreements), occupation,
   grade, experience years and evidence reference.

3. Four additive columns on payroll_taxability_rules
   (treatment / status / source_document_id / approved_by_id / created_by_id —
   five), the approval-gated alteration lifecycle the CH QST overlay uses.

4. jur jurisdiction_state on payroll_collective_agreements — NULL = the row's
   existing country-wide scope; set (e.g. "ZH") = cantonal scope, so a
   cantonal wage-floor agreement is a CollectiveAgreement row like any other.

5. payslip_items.ch_calculation_snapshot JSON — the frozen CH calc snapshot,
   same one-JSON-column-per-country precedent as germany_/fr_/ie_/se_/it_.

Every operation is guarded (skipped when its object already exists), matching
the pattern adopted after the 2026-09-29 deploy failed on a table an unmerged
branch had already created. New-table create statements keep their literal
`op.create_table('<name>', ...)` calls because test_model_tables_have_migrations
and deploy_migrate.sh's stamp walk discover schema by textual scan.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3baddbaa011a'
down_revision: Union[str, Sequence[str], None] = 'd7e6f5a4b3c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Idempotency guards (same pattern as 7a1b2c3d4e5f) ────────────────────────
def _has_table(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table, column):
    return _has_table(table) and column in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _add_column(table, column):
    if _has_column(table, column.name):
        return
    if column.foreign_keys and op.get_bind().dialect.name == "sqlite":
        # SQLite cannot ADD a foreign-keyed column in place and this project's
        # dev/test setup does not enforce foreign keys, so the dev fallback gets
        # the plain column; PostgreSQL keeps the FK.
        op.add_column(table, sa.Column(column.name, column.type, nullable=column.nullable))
    else:
        op.add_column(table, column)


def _drop_column(table, column_name):
    if not _has_column(table, column_name):
        return
    if op.get_bind().dialect.name == "sqlite":
        # SQLite cannot DROP a foreign-keyed column in place; batch mode
        # rebuilds the table. PostgreSQL drops directly.
        with op.batch_alter_table(table) as batch:
            batch.drop_column(column_name)
    else:
        op.drop_column(table, column_name)


def _drop_table(name):
    if _has_table(name):
        op.drop_table(name)


# Every ch_* column added to payroll_employee_statutory_profiles, in the order
# they are added. Kept as one list so upgrade() and downgrade() cannot drift.
CH_PROFILE_COLUMNS = (
    sa.Column('ch_work_canton', sa.String(5), nullable=True),
    sa.Column('ch_residence_canton', sa.String(5), nullable=True),
    sa.Column('ch_qst_canton', sa.String(5), nullable=True),
    sa.Column('ch_residence_country', sa.String(2), nullable=True),
    sa.Column('ch_nationality', sa.String(2), nullable=True),
    sa.Column('ch_permit_type', sa.String(10), nullable=True),
    sa.Column('ch_cross_border', sa.Boolean(), nullable=True),
    sa.Column('ch_ahv_number', sa.String(16), nullable=True),
    sa.Column('ch_ahv_status', sa.String(30), nullable=True),
    sa.Column('ch_alv_subject', sa.Boolean(), nullable=True),
    sa.Column('ch_weekly_hours', sa.Numeric(5, 2), nullable=True),
    sa.Column('ch_multiple_employment', sa.Boolean(), nullable=True),
    sa.Column('ch_other_employment_pct', sa.Numeric(5, 2), nullable=True),
    sa.Column('ch_qst_subject', sa.String(20), nullable=True),
    sa.Column('ch_qst_tariff_code', sa.String(10), nullable=True),
    sa.Column('ch_marital_status', sa.String(20), nullable=True),
    sa.Column('ch_spouse_employed', sa.Boolean(), nullable=True),
    sa.Column('ch_children_count', sa.Integer(), nullable=True),
    sa.Column('ch_church_tax', sa.Boolean(), nullable=True),
    sa.Column('ch_bvg_plan_scheme_id', sa.Integer(),
              sa.ForeignKey('payroll_ch_scheme_profiles.id'), nullable=True),
    sa.Column('ch_uvg_policy_scheme_id', sa.Integer(),
              sa.ForeignKey('payroll_ch_scheme_profiles.id'), nullable=True),
    sa.Column('ch_ktg_policy_scheme_id', sa.Integer(),
              sa.ForeignKey('payroll_ch_scheme_profiles.id'), nullable=True),
    sa.Column('ch_uvg_risk_class', sa.String(20), nullable=True),
    sa.Column('ch_contract_end', sa.Date(), nullable=True),
    sa.Column('ch_wage_floor_agreement_id', sa.Integer(),
              sa.ForeignKey('payroll_collective_agreements.id'), nullable=True),
    sa.Column('ch_occupation', sa.String(100), nullable=True),
    sa.Column('ch_grade', sa.String(50), nullable=True),
    sa.Column('ch_experience_years', sa.Numeric(4, 1), nullable=True),
    sa.Column('ch_evidence_document_id', sa.Integer(),
              sa.ForeignKey('payroll_source_artifacts.id'), nullable=True),
)


def upgrade() -> None:
    """Upgrade schema."""

    # ── 1. Authority scheme registry ─────────────────────────────────────────
    # organization_id NULL = platform catalog DEFINITION (Super Admin); set =
    # that employer's ASSIGNMENT of it (same null-means-platform convention as
    # CollectiveAgreement / TaxabilityRule).
    if not _has_table('payroll_ch_scheme_profiles'):
        op.create_table(
            'payroll_ch_scheme_profiles',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'),
                      nullable=True, index=True),
            # COMPENSATION_OFFICE | FAK | BVG_PLAN | UVG_POLICY | KTG_POLICY
            sa.Column('scheme_type', sa.String(30), nullable=False),
            sa.Column('scheme_code', sa.String(50), nullable=False),
            sa.Column('name', sa.String(200), nullable=False),
            sa.Column('authority_identifier', sa.String(50), nullable=True),
            sa.Column('canton', sa.String(5), nullable=True),
            sa.Column('rules', sa.JSON(), nullable=True),
            sa.Column('rules_sha256', sa.String(64), nullable=True),
            sa.Column('version', sa.String(20), nullable=False, server_default='1.0'),
            # DRAFT | APPROVED | LIVE | RETIRED
            sa.Column('status', sa.String(20), nullable=False, server_default='DRAFT'),
            sa.Column('effective_from', sa.Date(), nullable=False),
            sa.Column('effective_to', sa.Date(), nullable=True),
            sa.Column('previous_version_id', sa.Integer(),
                      sa.ForeignKey('payroll_ch_scheme_profiles.id'), nullable=True),
            sa.Column('source_document_id', sa.Integer(),
                      sa.ForeignKey('payroll_source_artifacts.id'), nullable=True),
            sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('activated_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
            sa.UniqueConstraint('organization_id', 'scheme_type', 'scheme_code', 'version',
                                name='uq_ch_scheme_profile_scope_version'),
        )

    # ── 2. 1:1 org-level CH employer profile ────────────────────────────────
    # readiness_status recomputed by the service evaluator, never hand-set —
    # same discipline as EmployerFranceProfile.readiness_status.
    if not _has_table('payroll_ch_entity_profiles'):
        op.create_table(
            'payroll_ch_entity_profiles',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'),
                      nullable=False, unique=True, index=True),
            sa.Column('uid', sa.String(15), nullable=True),
            sa.Column('seat_canton', sa.String(5), nullable=True),
            sa.Column('canton_registrations', sa.JSON(), nullable=True),
            sa.Column('compensation_office_scheme_id', sa.Integer(),
                      sa.ForeignKey('payroll_ch_scheme_profiles.id'), nullable=True),
            sa.Column('fak_scheme_id', sa.Integer(),
                      sa.ForeignKey('payroll_ch_scheme_profiles.id'), nullable=True),
            sa.Column('effective_from', sa.Date(), nullable=False),
            sa.Column('effective_to', sa.Date(), nullable=True),
            sa.Column('previous_version_id', sa.Integer(),
                      sa.ForeignKey('payroll_ch_entity_profiles.id'), nullable=True),
            # NOT_READY | READY | LIVE
            sa.Column('readiness_status', sa.String(30), nullable=False,
                      server_default='NOT_READY'),
            sa.Column('readiness_evidence', sa.JSON(), nullable=True),
            sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        )

    # ── 3. QST tariff files + bracket rows ──────────────────────────────────
    if not _has_table('payroll_ch_qst_tariff_files'):
        op.create_table(
            'payroll_ch_qst_tariff_files',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('canton', sa.String(5), nullable=False),
            sa.Column('tax_year', sa.Integer(), nullable=True),
            sa.Column('format_version', sa.String(30), nullable=True),
            sa.Column('publication_date', sa.Date(), nullable=True),
            sa.Column('effective_from', sa.Date(), nullable=True),
            sa.Column('effective_to', sa.Date(), nullable=True),
            sa.Column('source_document_id', sa.Integer(),
                      sa.ForeignKey('payroll_source_artifacts.id'), nullable=True),
            sa.Column('file_sha256', sa.String(64), nullable=False),
            sa.Column('row_count', sa.Integer(), nullable=True),
            # IMPORTED | VALIDATED | APPROVED | ACTIVE | SUPERSEDED | REJECTED
            sa.Column('status', sa.String(20), nullable=False, server_default='IMPORTED'),
            sa.Column('supersedes_id', sa.Integer(),
                      sa.ForeignKey('payroll_ch_qst_tariff_files.id'), nullable=True),
            sa.Column('imported_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('imported_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('activated_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('validation_report', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
            sa.UniqueConstraint('canton', 'file_sha256', name='uq_ch_qst_tariff_file_canton_sha'),
        )

    if not _has_table('payroll_ch_qst_tariff_rows'):
        op.create_table(
            'payroll_ch_qst_tariff_rows',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('tariff_file_id', sa.Integer(),
                      sa.ForeignKey('payroll_ch_qst_tariff_files.id'), nullable=False, index=True),
            sa.Column('tariff_code', sa.String(10), nullable=False),
            sa.Column('children', sa.SmallInteger(), nullable=True),
            sa.Column('church_tax', sa.Boolean(), nullable=True),
            sa.Column('income_from', sa.Numeric(12, 2), nullable=True),
            sa.Column('income_to', sa.Numeric(12, 2), nullable=True),
            sa.Column('rate_pct', sa.Numeric(7, 4), nullable=True),
            sa.Column('min_tax', sa.Numeric(10, 2), nullable=True),
            sa.Column('raw_record', sa.String(200), nullable=True),
            sa.Index('ix_ch_qst_tariff_row_bracket',
                     'tariff_file_id', 'tariff_code', 'children', 'income_from'),
        )

    # ── 4. Family-allowance entitlements ────────────────────────────────────
    if not _has_table('payroll_ch_family_allowance_entitlements'):
        op.create_table(
            'payroll_ch_family_allowance_entitlements',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'),
                      nullable=False, index=True),
            sa.Column('employee_id', sa.Integer(), sa.ForeignKey('payroll_employees.id'),
                      nullable=False, index=True),
            sa.Column('child_reference', sa.String(50), nullable=True),
            sa.Column('child_birth_date', sa.Date(), nullable=True),
            # CHILD | EDUCATION | BIRTH | ADOPTION
            sa.Column('allowance_type', sa.String(30), nullable=False),
            sa.Column('training_status', sa.String(30), nullable=True),
            # PRIMARY | DIFFERENTIAL
            sa.Column('entitlement_basis', sa.String(20), nullable=False,
                      server_default='PRIMARY'),
            sa.Column('precedence_evidence', sa.JSON(), nullable=True),
            sa.Column('canton', sa.String(5), nullable=True),
            sa.Column('fak_scheme_id', sa.Integer(),
                      sa.ForeignKey('payroll_ch_scheme_profiles.id'), nullable=True),
            sa.Column('period_from', sa.Date(), nullable=True),
            sa.Column('period_to', sa.Date(), nullable=True),
            # REQUESTED | APPROVED | REJECTED | ENDED
            sa.Column('status', sa.String(20), nullable=False, server_default='REQUESTED'),
            sa.Column('fund_decision_reference', sa.String(100), nullable=True),
            sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('source_document_id', sa.Integer(),
                      sa.ForeignKey('payroll_source_artifacts.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        )

    # ── 5. Absence-benefit events ───────────────────────────────────────────
    # evidence_document_id is a REFERENCE only — deliberately no medical content
    # (same discipline as SwedenSickEpisode.medical_certificate_ref).
    if not _has_table('payroll_ch_absence_benefit_events'):
        op.create_table(
            'payroll_ch_absence_benefit_events',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'),
                      nullable=False, index=True),
            sa.Column('employee_id', sa.Integer(), sa.ForeignKey('payroll_employees.id'),
                      nullable=False, index=True),
            # MATERNITY | OTHER_PARENT | ADOPTION | ILLNESS_CO | ILLNESS_KTG |
            # ACCIDENT_UVG | PREGNANCY_PROTECTION
            sa.Column('event_type', sa.String(30), nullable=False),
            sa.Column('period_from', sa.Date(), nullable=False),
            sa.Column('period_to', sa.Date(), nullable=True),
            sa.Column('daily_allowance_rate', sa.Numeric(10, 2), nullable=True),
            sa.Column('insured_salary_basis', sa.Numeric(14, 2), nullable=True),
            sa.Column('insurer_claim_reference', sa.String(100), nullable=True),
            sa.Column('benefit_amount_expected', sa.Numeric(14, 2), nullable=True),
            sa.Column('benefit_amount_received', sa.Numeric(14, 2), nullable=True),
            sa.Column('employer_topup_amount', sa.Numeric(14, 2), nullable=True),
            sa.Column('status', sa.String(20), nullable=False, server_default='OPEN'),
            sa.Column('evidence_document_id', sa.Integer(),
                      sa.ForeignKey('payroll_source_artifacts.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
            sa.Index('ix_ch_absence_benefit_event_emp', 'employee_id', 'period_from'),
        )

    # ── 6. ELM submission envelopes ─────────────────────────────────────────
    # idempotency_key is UNIQUE so an uncertain transport can never be resent
    # blindly; payload referenced by payload_ref + payload_sha256, never copied.
    if not _has_table('payroll_ch_elm_submissions'):
        op.create_table(
            'payroll_ch_elm_submissions',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'),
                      nullable=False, index=True),
            sa.Column('statutory_filing_id', sa.Integer(),
                      sa.ForeignKey('statutory_filings.id'), nullable=True),
            # QST | AHV | FAK | UVG | UVGZ | KTG | BFS
            sa.Column('domain', sa.String(20), nullable=False),
            sa.Column('receiver_id', sa.String(50), nullable=True),
            sa.Column('canton', sa.String(5), nullable=True),
            sa.Column('schema_version', sa.String(30), nullable=True),
            sa.Column('period_key', sa.String(50), nullable=True),
            sa.Column('payload_sha256', sa.String(64), nullable=True),
            sa.Column('payload_ref', sa.String(255), nullable=True),
            sa.Column('transport_status', sa.String(30), nullable=True),
            sa.Column('receiver_validation_status', sa.String(30), nullable=True),
            sa.Column('authority_ack_status', sa.String(30), nullable=True),
            sa.Column('settlement_status', sa.String(30), nullable=True),
            sa.Column('receipt_reference', sa.String(100), nullable=True),
            sa.Column('rejection_detail', sa.JSON(), nullable=True),
            sa.Column('correction_of_id', sa.Integer(),
                      sa.ForeignKey('payroll_ch_elm_submissions.id'), nullable=True),
            sa.Column('idempotency_key', sa.String(64), nullable=False, unique=True),
            sa.Column('actor_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('correlation_id', sa.String(64), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
            sa.Index('ix_ch_elm_submission_org_domain', 'organization_id', 'domain', 'period_key'),
        )

    # ── 7. Employee statutory profile: worker-owned ch_* facts ──────────────
    for column in CH_PROFILE_COLUMNS:
        _add_column('payroll_employee_statutory_profiles', column)

    # ── 8. Collective agreement: nullable canton-level scope ────────────────
    _add_column('payroll_collective_agreements',
                sa.Column('jurisdiction_state', sa.String(100), nullable=True))

    # ── 9. Taxability rule: approval-gated alteration lifecycle ─────────────
    for column in (
        sa.Column('treatment', sa.String(30), nullable=True),
        sa.Column('status', sa.String(20), nullable=True),
        sa.Column('source_document_id', sa.Integer(),
                  sa.ForeignKey('payroll_source_artifacts.id'), nullable=True),
        sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
    ):
        _add_column('payroll_taxability_rules', column)

    # ── 10. Payslip: frozen CH calculation snapshot ─────────────────────────
    _add_column('payslip_items', sa.Column('ch_calculation_snapshot', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema - strictly mirrors upgrade(); additive changes only
    mean downgrade is a pure drop of the objects this revision created."""
    _drop_column('payslip_items', 'ch_calculation_snapshot')

    for column in reversed((
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('approved_by_id', sa.Integer(), nullable=True),
        sa.Column('source_document_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(20), nullable=True),
        sa.Column('treatment', sa.String(30), nullable=True),
    )):
        _drop_column('payroll_taxability_rules', column.name)

    _drop_column('payroll_collective_agreements', 'jurisdiction_state')

    for column in reversed(CH_PROFILE_COLUMNS):
        _drop_column('payroll_employee_statutory_profiles', column.name)

    _drop_table('payroll_ch_elm_submissions')
    _drop_table('payroll_ch_absence_benefit_events')
    _drop_table('payroll_ch_family_allowance_entitlements')
    _drop_table('payroll_ch_qst_tariff_rows')
    _drop_table('payroll_ch_qst_tariff_files')
    _drop_table('payroll_ch_entity_profiles')
    _drop_table('payroll_ch_scheme_profiles')