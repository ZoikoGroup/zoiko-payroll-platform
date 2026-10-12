"""add italy jurisdiction support

Revision ID: 7a1b2c3d4e5f
Revises: e8f1a2b3c4d5
Create Date: 2026-10-01 00:00:00.000000

ZP-IT-ENG-001 (Italy Payroll Detailed Engineering Wireframe & Implementation
Specification v1.0, 22 September 2026). Strictly ADDITIVE - no existing column
or table is altered or dropped, and every new column is nullable so every
pre-existing row keeps its exact current behavior.

Chains directly off e8f1a2b3c4d5, which `alembic heads` confirms is the single
current head of the graph (168 revisions, one head). The "multiple heads"
warning carried in older migration docstrings referred to branch points that
have since been merged; there is no ambiguity about where this revision goes.

Deliberately SMALL. Following the precedent documented at models.py:5844-5857
(France) and models.py:6123-6156 (Ireland), Italy does NOT re-implement the
generic statutory-content system. Those two comments record the exact failure
mode this revision avoids: payroll_ie_employer_profiles,
payroll_ie_revenue_submissions and payroll_ie_revenue_monthly_returns were all
"created, migrated and then never read or written by a single line of
application code, and all three were empty" before being removed on 2026-09-28.

So Italy's statutory content is written into the EXISTING generic tables:
  - IRPEF brackets, employee-work deduction tapers and the structural tax-wedge
    bands            -> payroll_tax_slabs (rule_type / formula_expression)
  - 2026 thresholds (EUR 58.13 daily contributory minimum, EUR 56,224 additional
    1% band, EUR 122,295 pensionable maximum, fringe EUR 1,000/2,000, meal
    voucher EUR 10, productivity bonus 1%/EUR 5,000), TFR 1/13.5 and the
    1.5% + 75% ISTAT revaluation, CCNL minimum pay per level
                      -> payroll_contribution_rates (flat_amount / *_rate_pct)
  - Regional addizionale  -> payroll_jurisdiction_packs with
                             jurisdiction_state = 'IT-<REG>' and
                             parent_pack_id -> the national pack (the Germany
                             per-Land pattern, seed_germany_2026_all_jurisdictions.py)
  - Municipal addizionale (~7,900 comuni)
                      -> payroll_locality_datasets + payroll_locality_rates,
                         whose bracket_schedule JSON already carries marginal
                         brackets and whose lst_exemption_threshold carries the
                         statutory exemption threshold. That table exists
                         precisely for "thousands of rows imported as a unit,
                         diffed/staged/approved/activated together, not
                         hand-typed" (models.py:4815-4819).
  - CCNL contracts      -> payroll_collective_agreements, already generic by
                           design ("jurisdiction_country keeps the table generic
                           so DE/UK can later model Tarifvertrag/BOOT the same
                           way", models.py:6594-6595)
  - Employee statutory profile -> the it_* block on
                           payroll_employee_statutory_profiles below
  - Employee year-to-date state (wage-wedge sum/deduction accumulators, the
    additional 1% accumulator, the fringe accumulator, the TFR quota)
                      -> payroll_ytd_accumulators, already unique on
                         (employee_id, tax_year, tax_component) and already
                         switched on per country for UK/IE/AU/CA
  - UniEmens / F24 / LUL / CU / 770 filing status, authority receipts,
    correction lineage and schema versions
                      -> statutory_filings, whose submission_status /
                         receipt_id / correction_reference / schema_version /
                         validation_status columns were added GENERIC and
                         un-prefixed for exactly this ("another country may
                         later reuse them for its own authority receipt flow",
                         models.py:5802-5808)
  - Tesoreria 60-employee prior-year-average-headcount test
                      -> payroll_employer_tax_profiles.covered_employee_count,
                         whose own docstring cites Colorado FAMLI's
                         10-employee threshold as the precedent, and forbids
                         inferring it from payroll history
  - Fringe benefit IRPEF-vs-INPS treatment independence (IT-033)
                      -> payroll_taxability_rules

What this revision adds is therefore ONLY what the generic model cannot carry:

1. payroll_it_employer_profiles
     §17 employer onboarding panels A-F and the §17H/IT-049 launch gate. The
     nearest precedent is EmployerFranceProfile (models.py:5859), which the
     Ireland header comment names as the correct model for a recomputed
     (never hand-set) readiness gate. matricola/CSC/CA/ATECO/PAT/codice
     autorizzazione are agency-assigned facts WITH account numbers and an
     evidence trail, so per payroll_employer_tax_profiles' own definition they
     go on EmployerTaxProfile rows rather than being crammed in here; the
     codes kept here are the ones the readiness evaluator itself must read.

2. payroll_it_filing_outbox_items
     §15/IT-044 (an idempotent outbox built from COMMITTED payroll, never a
     live transmit from the calculator) and §16/IT-048 (a timeout produces
     UNKNOWN plus reconciliation, blind resend is prohibited). Modelled on
     FranceDsnOutboxItem (models.py:6094-6120), which already carries
     idempotency_key UNIQUE and the PENDING/SENT/UNKNOWN/ACKNOWLEDGED/FAILED
     vocabulary those requirements describe. Kept as its own table rather than
     folded into the French one: that table is FR-prefixed and holds live
     French rows, and the same header comment records "Precedent for
     dedicated country extension tables".

3. Fifteen nullable it_* columns on payroll_employee_statutory_profiles
     §18 employee onboarding. Sized String(20)/String(30) after auditing every
     proposed value against the real column type length; deliberately NOT copied
     from the de_* block, which is String(10) and has repeatedly proven too
     narrow (payroll_tax_slabs.filing_status was widened 20->30 for exactly
     this reason in 518b8d4a5e46, and its docstring records that pytest never
     caught it because the in-memory test contexts never touch that column).

4. One nullable JSON snapshot column on payslip_items (it_calculation_snapshot,
     §19) - the same "one JSON snapshot per country" pattern as
     germany_/fr_/ie_/se_.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7a1b2c3d4e5f'
down_revision: Union[str, Sequence[str], None] = 'e8f1a2b3c4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Idempotency guards (same pattern as e8f1a2b3c4d5 / 74aeb450aeee) ────────
# The 2026-09-29 deploy failed because an unmerged branch had already run part
# of a schema against production. Every operation below is skipped when its
# object already exists (or, for a drop, is already gone). A pre-existing
# object with the wrong SHAPE is not papered over: scripts.check_schema_drift
# runs right after the upgrade and fails the deploy before the restart.
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


# Every it_* column added to payroll_employee_statutory_profiles, in the order
# they are added. Kept as one list so upgrade() and downgrade() cannot drift.
# Sized from the Phase 0 audit against real Italian values, not from the de_*
# block's String(10).
IT_PROFILE_COLUMNS = (
    # §9 CCNL — the wage-compliance gate. No statutory minimum wage exists, so
    # the applicable CNEL contract/level IS the minimum-pay control (IT-025).
    sa.Column('it_cnel_code', sa.String(20), nullable=True),
    sa.Column('it_cnel_level', sa.String(20), nullable=True),
    # §7 INPS worker classification. IT-002: an unsupported combination must
    # BLOCK, never fall back to a generic rate.
    sa.Column('it_worker_class', sa.String(30), nullable=True),
    sa.Column('it_contract_type', sa.String(30), nullable=True),
    sa.Column('it_cigs_applies', sa.Boolean(), nullable=True),
    # §6 contributory cap. IT-017: only cap when cohort evidence exists; income
    # above EUR 122,295 alone is never sufficient reason to cap ordinary FPLD.
    sa.Column('it_contributory_cap_cohort', sa.String(20), nullable=True),
    sa.Column('it_employer_contrib_opted', sa.Boolean(), nullable=True),
    # §13 TFR destination. An election, not a running total - the quota itself
    # is a payroll_ytd_accumulators row. IT-038: changing destination must not
    # erase accrued entitlement history.
    sa.Column('it_tfr_destination', sa.String(30), nullable=True),
    sa.Column('it_pension_fund', sa.String(30), nullable=True),
    sa.Column('it_tfr_destination_from', sa.Date(), nullable=True),
    # §5 TAX DOMICILE, deliberately separate from work_locality and from
    # residence_locality. IT-013: a remote employee working in Milan but
    # tax-domiciled elsewhere must not inherit Milan's municipal surtax.
    sa.Column('it_tax_domicile_comune', sa.String(20), nullable=True),
    sa.Column('it_tax_domicile_region', sa.String(10), nullable=True),
    sa.Column('it_tax_domicile_from', sa.Date(), nullable=True),
    # §11 fringe. IT-032: the EUR 2,000 child threshold requires the employee's
    # own declaration; HR dependent records alone are insufficient, so this is
    # a flagged employee fact and never inferred.
    sa.Column('it_fringe_child_declared', sa.Boolean(), nullable=True),
    # §22 termination. IT-064: the reason is a legal input that determines
    # notice, employer charge and reporting; operators cannot pick a preferred
    # tax/severance treatment.
    sa.Column('it_termination_reason', sa.String(50), nullable=True),
)


def upgrade() -> None:
    """Upgrade schema."""

    # ── 1. Italy employer profile (§17A-F, §17H launch gate, IT-049) ─────────
    # readiness_status is RECOMPUTED by the service evaluator, never hand-set -
    # same discipline as EmployerFranceProfile.readiness_status.
    if not _has_table('payroll_it_employer_profiles'):
        op.create_table(
            'payroll_it_employer_profiles',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'),
                      nullable=False, unique=True, index=True),
            # §17B INPS
            sa.Column('matricola_inps', sa.String(20), nullable=True),
            sa.Column('csc_code', sa.String(10), nullable=True),
            sa.Column('ca_code', sa.String(10), nullable=True),
            sa.Column('ateco_code', sa.String(10), nullable=True),
            sa.Column('inps_office', sa.String(50), nullable=True),
            # §17D CCNL
            sa.Column('cnel_code', sa.String(20), nullable=True),
            # §17B/C fund + insurance status (standard/special funds, FIS)
            sa.Column('fund_status', sa.JSON(), nullable=True),
            # §17E / IT-040 the Fondo Tesoreria obligation is decided by the
            # PRIOR-CALENDAR-YEAR average workforce, not current headcount.
            sa.Column('prior_year_avg_headcount', sa.Integer(), nullable=True),
            sa.Column('tesoreria_status', sa.String(20), nullable=True),
            # §17F / §17G operating models
            sa.Column('f24_operating_model', sa.String(30), nullable=True),
            sa.Column('lul_method', sa.String(30), nullable=True),
            # §17H single evidence card. NOT_READY until the INPS profile, the
            # INAIL PAT/rate and the applicable CCNL all validate (IT-049).
            sa.Column('readiness_status', sa.String(30), nullable=False,
                      server_default='NOT_READY'),
            sa.Column('readiness_evidence', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        )

    # ── 2. Italy filing outbox (§15 IT-044, §16 IT-048) ─────────────────────
    # idempotency_key is UNIQUE so an uncertain transport can never be resent
    # blindly; status carries UNKNOWN as a first-class outcome, not an error.
    if not _has_table('payroll_it_filing_outbox_items'):
        op.create_table(
            'payroll_it_filing_outbox_items',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'),
                      nullable=False, index=True),
            # UNIEMENS_TRANSMIT | F24_SUBMIT | LUL_REGISTER | CU_TRANSMIT |
            # 770_TRANSMIT | CORRECTION
            sa.Column('action', sa.String(30), nullable=False),
            # Links to statutory_filings, which already holds the filing status,
            # receipt_id, correction_reference, schema_version and
            # validation_status for UniEmens / F24 / LUL / CU / 770.
            sa.Column('statutory_filing_id', sa.Integer(),
                      sa.ForeignKey('statutory_filings.id'), nullable=True, index=True),
            sa.Column('period_key', sa.String(20), nullable=True),
            sa.Column('payload', sa.JSON(), nullable=True),
            sa.Column('idempotency_key', sa.String(64), nullable=False, unique=True),
            # PENDING | SENT | UNKNOWN | ACKNOWLEDGED | FAILED
            sa.Column('status', sa.String(20), nullable=False, server_default='PENDING'),
            sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('last_error', sa.Text(), nullable=True),
            sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        )

    # ── 3. Employee statutory profile: §18 worker-owned facts ──────────────
    for column in IT_PROFILE_COLUMNS:
        _add_column('payroll_employee_statutory_profiles', column)

    # ── 4. Payslip: frozen Italy calculation trace (§19) ────────────────────
    _add_column('payslip_items', sa.Column('it_calculation_snapshot', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema - strictly mirrors upgrade(); additive changes only
    mean downgrade is a pure drop of the objects this revision created."""
    _drop_column('payslip_items', 'it_calculation_snapshot')

    for column in reversed(IT_PROFILE_COLUMNS):
        _drop_column('payroll_employee_statutory_profiles', column.name)

    _drop_table('payroll_it_filing_outbox_items')
    _drop_table('payroll_it_employer_profiles')