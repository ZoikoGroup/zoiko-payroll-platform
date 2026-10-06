"""Italy F24 causale catalog + F24 line idempotency

Revision ID: c9d8e7f6a5b4
Revises: cd62503afe26
Create Date: 2026-10-05 00:00:00.000000

ZP-IT-ENG-001 section 16 / IT-043 / IT-046, phase 3A. Two changes, both
additive:

  payroll_it_f24_causales
      The governed (section, component) -> F24 causale mapping. IT-046 requires
      every derived F24 line to carry a real "codice tributo / causale", and
      IT-043 forbids inventing one. The causali live in the Agenzia delle
      Entrate catalogs, so the mapping is authored as governed data rather than
      hardcoded - and it is seeded EMPTY on purpose. A populated catalog is a
      data-governance task with real legal consequences, and shipping guessed
      causali into a payment instruction would be worse than shipping nothing.

  payroll_it_f24_lines uq_it_f24_line_identity
      Idempotency for the derivation. Without it, rebuilding the same period's
      lines from the same committed run would append a second copy of the same
      liability, which is precisely the double-payment risk IT-044 exists to
      prevent. Keyed on (organization, run, section, tax_code, region, comune,
      period) - the full identity of one payable line.

Deliberately scoped to payability only. This revision adds NO transport: no
Agenzia delle Entrate call, no F24 file generation. The existing
payroll_it_filing_outbox_items queue (IT-044/IT-048) is the only delivery path,
and IT-045 keeps an accepted filing separate from a settled payment.

Every operation is guarded (skipped when its object already exists), matching
the pattern adopted after the 2026-09-29 deploy failed on a table an unmerged
branch had already created.

Re-parented onto cd62503afe26 (Hong Kong) when venu merged main (2026-10-06):
917a54ed2347 -> cd62503afe26 -> c9d8e7f6a5b4 -> d7e6f5a4b3c2. Both Italy revisions
were only ever on venu (never on a deployed database), so re-parenting removes
the fork without a merge migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9d8e7f6a5b4'
down_revision: Union[str, Sequence[str], None] = 'cd62503afe26'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CAUSALE_TABLE = 'payroll_it_f24_causales'
LINE_TABLE = 'payroll_it_f24_lines'
LINE_UNIQUE = 'uq_it_f24_line_identity'


def _has_table(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_unique(name):
    if not _has_table(LINE_TABLE):
        return False
    inspector = sa.inspect(op.get_bind())
    return any(c.get('name') == name for c in inspector.get_unique_constraints(LINE_TABLE))


def upgrade() -> None:
    # NOTE: the table name is spelled out literally rather than interpolated from
    # CAUSALE_TABLE. tests/test_model_tables_have_migrations.py discovers created
    # tables with a textual scan for create_table('name'), so a name hidden behind
    # a variable is indistinguishable from a table that was never migrated -
    # which is exactly the France payroll_fr_* bug that guard was written for.
    if not _has_table(CAUSALE_TABLE):
        op.create_table(
            'payroll_it_f24_causales',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'),
                      nullable=False, index=True),
            # ERARIO | INPS | REGIONI | ENTI_LOCALI | INAIL
            sa.Column('section', sa.String(20), nullable=False),
            # The payslip snapshot path this causale settles, e.g. "inps.employer".
            sa.Column('component_key', sa.String(40), nullable=False),
            # The real codice tributo / causale - never synthesised (IT-043).
            sa.Column('tax_code', sa.String(10), nullable=False),
            # REGIONI / ENTI_LOCALI split the same causale per authority, so a
            # line without both codes is not payable.
            sa.Column('requires_region', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('requires_comune', sa.Boolean(), nullable=False, server_default=sa.false()),
            # An offset line (wedge recovery, municipal credit) is shown on its
            # own DEBIT/CREDIT line rather than netted away (IT-046).
            sa.Column('direction', sa.String(10), nullable=False, server_default='DEBIT'),
            sa.Column('effective_from', sa.Date(), nullable=False),
            sa.Column('effective_to', sa.Date(), nullable=True),
            sa.Column('source_document_id', sa.Integer(),
                      sa.ForeignKey('payroll_source_artifacts.id'), nullable=True),
            # Draft until a distinct approver confirms the code is real.
            sa.Column('status', sa.String(20), nullable=False, server_default='Draft'),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint('organization_id', 'section', 'component_key',
                                'effective_from', name='uq_it_f24_causale_component_from'),
        )

    if not _has_unique(LINE_UNIQUE):
        # SQLite cannot ALTER TABLE ... ADD CONSTRAINT, so batch_alter_table
        # rebuilds the table there; Postgres takes the direct path.
        columns = ['organization_id', 'payroll_run_id', 'section', 'tax_code',
                   'region_code', 'comune_code', 'reference_period']
        if op.get_bind().dialect.name == 'sqlite':
            with op.batch_alter_table(LINE_TABLE) as batch:
                batch.create_unique_constraint(LINE_UNIQUE, columns)
        else:
            op.create_unique_constraint(LINE_UNIQUE, LINE_TABLE, columns)


def downgrade() -> None:
    if _has_unique(LINE_UNIQUE):
        columns = ['organization_id', 'payroll_run_id', 'section', 'tax_code',
                   'region_code', 'comune_code', 'reference_period']
        if op.get_bind().dialect.name == 'sqlite':
            with op.batch_alter_table(LINE_TABLE) as batch:
                batch.drop_constraint(LINE_UNIQUE, type_='unique')
        else:
            op.drop_constraint(LINE_UNIQUE, LINE_TABLE, type_='unique')
    if _has_table(CAUSALE_TABLE):
        op.drop_table('payroll_it_f24_causales')
