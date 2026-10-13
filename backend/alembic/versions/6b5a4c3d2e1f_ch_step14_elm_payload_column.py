"""ch step 14 elm payload column

Revision ID: 6b5a4c3d2e1f
Revises: f898189cb4e3
Create Date: 2026-10-07 00:00:00.000000

CH Step 14 (Reporting): the ELM submission envelope now carries the exact
XML payload body alongside its digest. payroll_ch_elm_submissions gains a
nullable payload_xml TEXT column; existing rows are unaffected (payloads are
recomputed on demand when the column is empty). The column stays nullable so
full authority envelopes (e.g. ISR/assuraces-style attachments) never force a
payload into a relational column.

Guarded like every neighbouring migration: the step is skipped when the
column is already present. Chains directly off f898189cb4e3 (single head).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '6b5a4c3d2e1f'
down_revision: Union[str, Sequence[str], None] = 'f898189cb4e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CH_ELM_TABLE = 'payroll_ch_elm_submissions'
_PAYLOAD_XML_COLUMN = sa.Column('payload_xml', sa.Text(), nullable=True)


def _has_table(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


def _columns(table):
    return {c['name']: c for c in sa.inspect(op.get_bind()).get_columns(table)} if _has_table(table) else {}


def upgrade() -> None:
    if _has_table(CH_ELM_TABLE) and 'payload_xml' not in _columns(CH_ELM_TABLE):
        op.add_column(CH_ELM_TABLE, _PAYLOAD_XML_COLUMN)


def downgrade() -> None:
    if _has_table(CH_ELM_TABLE) and 'payload_xml' in _columns(CH_ELM_TABLE):
        op.drop_column(CH_ELM_TABLE, 'payload_xml')