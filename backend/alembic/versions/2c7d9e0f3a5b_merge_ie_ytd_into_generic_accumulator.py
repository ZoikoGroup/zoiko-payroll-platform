"""merge payroll_ie_ytd_accumulators into payroll_ytd_accumulators (7 IE tables -> 3)

Revision ID: 2c7d9e0f3a5b
Revises: f6b2c4d8e1a3

ZP-IE-ENG-001, 2026-09-28. Ireland's five independent cumulative figures move
off their own payroll_ie_ytd_accumulators table and onto the generic
payroll_ytd_accumulators table the UK and Australia already use, one row per
figure instead of one row with a column per figure:

  ie_usc_payable     -> ytd_taxable_wages    (USC's own payable base, IE-009/010)
  ie_usc_paid        -> ytd_tax_withheld     (USC charged to date)
  ie_prsi_reckonable -> ytd_taxable_wages    (reckonable pay; PRSI has no
                                             employee tax, IE-011/012)
  ie_prsi_weeks      -> ytd_tax_withheld     (contribution weeks to date)
  ie_mff_earnings    -> ytd_taxable_wages    (MyFutureFund earnings, IE-020)
  last_payslip_id    -> last_updated_payslip_id

The dedicated table existed because the old guard test claimed the generic
pair could not express Ireland's figures. That claim did not hold: the
component key carries the meaning, so a reader of ie_prsi_reckonable knows
ytd_taxable_wages is a reckonable total with no employee tax anywhere in it,
without needing a separate column to say so.

What does NOT survive, deliberately:

  mff_threshold_crossed_at_pay_date
      Never read by any code path. IE-020's requirement - record the payroll
      that crossed the annual threshold - is met by data already persisted on
      every payslip: the engine's MyFutureFund block returns threshold,
      earnings_ytd_before and earnings_ytd_after on all three of its branches,
      and _ie_payslip_snapshot stores ie_calculation_trace verbatim. The
      crossing payroll is the payslip where
      earnings_ytd_before < threshold <= earnings_ytd_after. That is a query
      over finalized payslips rather than a mutable running row, so it cannot
      drift out of step with the payslips it describes.

  organization_id
      The generic table has no organization_id because it does not need one:
      the employee FK already fixes the owning org, exactly as it does for UK
      and AU. downgrade() recovers it by joining through payroll_employees.

The copy is a straight per-row value move - no rounding, no re-derivation, no
"correction". Every source row becomes up to five destination rows, written
only where the destination does not already have that (employee, year,
component) so a re-run cannot fan out duplicates. prsi_contribution_weeks_ytd
was Numeric(8,3) and lands in Numeric(14,2); contribution weeks are whole
weeks, so no precision is lost.
"""
from alembic import op
import sqlalchemy as sa

revision: str = '2c7d9e0f3a5b'
down_revision: str = 'f6b2c4d8e1a3'
branch_labels = None
depends_on = None

_SOURCE = "payroll_ie_ytd_accumulators"
_TARGET = "payroll_ytd_accumulators"

# (source column, component key, target column)
_MAP = (
    ("usc_payable_ytd",             "ie_usc_payable",     "ytd_taxable_wages"),
    ("usc_paid_ytd",                "ie_usc_paid",        "ytd_tax_withheld"),
    ("prsi_reckonable_ytd",         "ie_prsi_reckonable", "ytd_taxable_wages"),
    ("prsi_contribution_weeks_ytd", "ie_prsi_weeks",      "ytd_tax_withheld"),
    ("mff_earnings_ytd_before",     "ie_mff_earnings",    "ytd_taxable_wages"),
)

# Every identifier below is a module-level constant written by hand in this
# file, never user input, so direct string interpolation is safe here and
# keeps one statement working identically on SQLite (service tests) and
# Postgres (deployments) - no bindparam dialect differences, no backend-
# specific server defaults, no NOT NULL surprises.
_COMPONENT_LIST = ", ".join("'%s'" % component for _, component, _ in _MAP)


def upgrade():
    bind = op.get_bind()
    if _SOURCE not in set(sa.inspect(bind).get_table_names()):
        return  # never created here; nothing to merge

    for source_col, component, target_col in _MAP:
        payable = "s.%s" % source_col if target_col == "ytd_taxable_wages" else "0"
        withheld = "s.%s" % source_col if target_col == "ytd_tax_withheld" else "0"
        op.execute(sa.text(
            "INSERT INTO {target} (employee_id, tax_year, tax_component, "
            "ytd_taxable_wages, ytd_tax_withheld, last_updated_payslip_id) "
            "SELECT s.employee_id, s.tax_year, '{component}', "
            "{payable}, {withheld}, s.last_payslip_id "
            "FROM {source} s "
            "WHERE NOT EXISTS (SELECT 1 FROM {target} t "
            "WHERE t.employee_id = s.employee_id "
            "AND t.tax_year = s.tax_year "
            "AND t.tax_component = '{component}')"
            .format(target=_TARGET, source=_SOURCE, component=component,
                    payable=payable, withheld=withheld)
        ))

    # Guarded like the sibling migration's index drop: an index already gone
    # by hand must not fail the merge after the data has been copied.
    try:
        indexes = {i["name"] for i in sa.inspect(bind).get_indexes(_SOURCE)}
    except (sa.exc.NoSuchTableError, NotImplementedError):
        indexes = set()
    if "ix_ie_ytd_org_employee" in indexes:
        op.drop_index('ix_ie_ytd_org_employee', table_name=_SOURCE)
    op.drop_table(_SOURCE)


def downgrade():
    """Rebuild the Ireland table from the generic rows and copy the values back.

    Rebuilds only the columns whose values still exist. mff_threshold_crossed_
    at_pay_date is left NULL: it was never read, and re-deriving it here would
    mean inventing a "crossing payroll" from running totals at a moment when
    the payslip evidence that actually records it is still present but not
    being queried. NULL is honest; a guessed date is not.
    """
    bind = op.get_bind()

    if _SOURCE not in set(sa.inspect(bind).get_table_names()):
        op.create_table(
            _SOURCE,
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, index=True),
            sa.Column('employee_id', sa.Integer(), sa.ForeignKey('payroll_employees.id'), nullable=False, index=True),
            sa.Column('tax_year', sa.String(length=10), nullable=False),
            sa.Column('usc_payable_ytd', sa.Numeric(precision=14, scale=2), nullable=False, server_default='0'),
            sa.Column('usc_paid_ytd', sa.Numeric(precision=14, scale=2), nullable=False, server_default='0'),
            sa.Column('prsi_reckonable_ytd', sa.Numeric(precision=14, scale=2), nullable=False, server_default='0'),
            sa.Column('prsi_contribution_weeks_ytd', sa.Numeric(precision=8, scale=3), nullable=False, server_default='0'),
            sa.Column('mff_earnings_ytd_before', sa.Numeric(precision=14, scale=2), nullable=False, server_default='0'),
            sa.Column('mff_threshold_crossed_at_pay_date', sa.Date(), nullable=True),
            sa.Column('last_payslip_id', sa.Integer(), sa.ForeignKey('payslip_items.id'), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint('employee_id', 'tax_year', name='uq_ie_ytd_accumulator_employee_year'),
        )
        op.create_index('ix_ie_ytd_org_employee', _SOURCE, ['organization_id', 'employee_id'])

    # One Ireland row per (employee, tax_year), folding the five component rows
    # back together. organization_id comes via payroll_employees because the
    # generic table never stored it. LEFT JOINs with COALESCE(...,0) rather
    # than INNER JOINs: a half-populated (employee, year) is a state the
    # application cannot produce, but if one ever appeared the honest reading is
    # "these five figures are not yet established", not "this employee has
    # earned nothing all year".
    op.execute(sa.text(
        "INSERT INTO {source} (organization_id, employee_id, tax_year, "
        "usc_payable_ytd, usc_paid_ytd, prsi_reckonable_ytd, "
        "prsi_contribution_weeks_ytd, mff_earnings_ytd_before, "
        "mff_threshold_crossed_at_pay_date, last_payslip_id) "
        "SELECT e.organization_id, u.employee_id, u.tax_year, "
        "COALESCE(usc.ytd_taxable_wages, 0), COALESCE(upd.ytd_tax_withheld, 0), "
        "COALESCE(pr.ytd_taxable_wages, 0), COALESCE(pw.ytd_tax_withheld, 0), "
        "COALESCE(mff.ytd_taxable_wages, 0), NULL, "
        "COALESCE(usc.last_updated_payslip_id, upd.last_updated_payslip_id, "
        "pr.last_updated_payslip_id, pw.last_updated_payslip_id, "
        "mff.last_updated_payslip_id) "
        "FROM (SELECT DISTINCT employee_id, tax_year FROM {target} "
        "WHERE tax_component IN ({components})) u "
        "JOIN payroll_employees e ON e.id = u.employee_id "
        "LEFT JOIN {target} usc ON usc.employee_id = u.employee_id AND usc.tax_year = u.tax_year AND usc.tax_component = 'ie_usc_payable' "
        "LEFT JOIN {target} upd ON upd.employee_id = u.employee_id AND upd.tax_year = u.tax_year AND upd.tax_component = 'ie_usc_paid' "
        "LEFT JOIN {target} pr ON pr.employee_id = u.employee_id AND pr.tax_year = u.tax_year AND pr.tax_component = 'ie_prsi_reckonable' "
        "LEFT JOIN {target} pw ON pw.employee_id = u.employee_id AND pw.tax_year = u.tax_year AND pw.tax_component = 'ie_prsi_weeks' "
        "LEFT JOIN {target} mff ON mff.employee_id = u.employee_id AND mff.tax_year = u.tax_year AND mff.tax_component = 'ie_mff_earnings'"
        .format(source=_SOURCE, target=_TARGET, components=_COMPONENT_LIST)
    ))

    op.execute(sa.text(
        "DELETE FROM {target} WHERE tax_component IN ({components})"
        .format(target=_TARGET, components=_COMPONENT_LIST)
    ))
