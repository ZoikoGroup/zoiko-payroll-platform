"""
modules/payroll/models.py
-------------------------
SQLAlchemy ORM models for the Zoiko Payroll module.

Tables:
  - PayrollEmployee           → payroll's own employee master data (multi-tenant, org-scoped;
                                 intentionally NOT linked to app.modules.employee.Employee,
                                 which is the separate HR/auth login record)
  - PayrollRun                → a single payroll processing run (e.g. "Jun 1-15, 2026")
  - PayslipItem               → individual salary components per employee per run
  - ContributionRate           → statutory contribution rates (PF/ESI/PT/TDS) shown in Compliance
  - TaxSlab                    → income tax slab table shown in Compliance
  - CompanyComplianceDetails   → one row per organization; company/compliance profile
  - PayrollActivityLog         → audit trail feeding the dashboard "Recent activity" feed

NOTE: created_by / approved_by / actor_id below reference the platform-wide
`users` table (modules/auth User) since those track which logged-in *user*
performed an action, not a payroll employee record.
"""

import enum
from sqlalchemy import (
    Column, Integer, String, Date, DateTime, Boolean,
    ForeignKey, Text, Numeric, UniqueConstraint, Index, JSON, text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


# ── Enums ──────────────────────────────────────────────────────────────
# NOTE: Enum *values* intentionally match the exact strings the frontend
# lifecycle UI expects (RunsTable.jsx / RunDetailPage.jsx `lifecycleSteps`),
# so API responses can be consumed with zero client-side mapping.

class PayrollStatus(str, enum.Enum):
    DRAFT       = "Draft"
    REVIEW      = "Review"
    APPROVED    = "Approved"
    AUTHORIZED  = "Authorized"
    PAID        = "Paid"
    CLOSED      = "Closed"


# Order matters — used to compute "next status" when a run is approved/advanced.
PAYROLL_STATUS_ORDER = [
    PayrollStatus.DRAFT,
    PayrollStatus.REVIEW,
    PayrollStatus.APPROVED,
    PayrollStatus.AUTHORIZED,
    PayrollStatus.PAID,
    PayrollStatus.CLOSED,
]


class PayslipStatus(str, enum.Enum):
    PENDING = "Pending"
    PAID    = "Paid"
    FAILED  = "Failed"


class ActivityStatus(str, enum.Enum):
    SUCCESS = "success"
    PENDING = "pending"
    INFO    = "info"


class ComplianceDocumentStatus(str, enum.Enum):
    """Lifecycle of an uploaded compliance document's text/OCR extraction.
    Mirrors the contract payrollService.js / ComplianceDocuments.jsx expect."""
    PROCESSING = "processing"
    PARSED     = "parsed"
    FAILED     = "failed"


class EmploymentType(str, enum.Enum):
    FULL_TIME = "Full-time"
    PART_TIME = "Part-time"
    CONTRACT  = "Contract"
    INTERN    = "Intern"


class EmployeeStatus(str, enum.Enum):
    ACTIVE   = "Active"
    ON_LEAVE = "On Leave"
    INACTIVE = "Inactive"


# ── Payroll Employee ─────────────────────────────────────────────────
# Owned entirely by the payroll module. Deliberately NOT linked to
# app.modules.employee.Employee (that model is the HR/auth login record
# for the whole app). In this multi-tenant setup, an organization may use
# payroll without the HR module, so payroll keeps its own employee master
# data, scoped by organization_id.

class PayrollEmployee(Base):
    __tablename__ = "payroll_employees"

    id               = Column(Integer, primary_key=True, index=True)
    organization_id  = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    employee_code    = Column(String(20), nullable=False)
    legacy_code      = Column(String(20), nullable=True)
    name             = Column(String(200), nullable=False)
    email            = Column(String(255), nullable=True)
    phone            = Column(String(50), nullable=True)

    department       = Column(String(100), nullable=True)   # matches payrollService.js DEPARTMENTS
    designation      = Column(String(100), nullable=True)
    employment_type  = Column(String(50), default=EmploymentType.FULL_TIME.value, nullable=False)
    status           = Column(String(20), default=EmployeeStatus.ACTIVE.value, nullable=False, index=True)

    # State/province the employee actually works in. Distinct from
    # CompanyComplianceDetails.jurisdiction_state, which is a single
    # org-wide default — that default cannot correctly represent an org
    # with employees spread across multiple states (e.g. Professional Tax
    # in India, which is state-specific). When set, this should take
    # precedence over the org-level default in PT calculation.
    work_state       = Column(String(100), nullable=True)
    # Third hierarchy level below work_state (e.g. a city/local body with
    # its own local tax) — null for every employee today; opt-in only.
    work_locality    = Column(String(100), nullable=True)

    date_of_joining  = Column(Date, nullable=True)
    ctc              = Column(Numeric(12, 2), default=0)
    # basic/hra are ANNUAL amounts (matching the ctc convention).
    # The payroll engine divides by 12 to derive monthly values.
    basic            = Column(Numeric(12, 2), nullable=True)
    hra              = Column(Numeric(12, 2), nullable=True)

    bank_name        = Column(String(100), nullable=True)
    bank_account     = Column(String(50), nullable=True)
    pan              = Column(String(20), nullable=True)
    uan              = Column(String(20), nullable=True)
    ifsc             = Column(String(20), nullable=True)

    # Per-employee jurisdiction override for multi-country onboarding. Falls
    # back to CompanyComplianceDetails.jurisdiction_country (via
    # _normalize_country) when unset — same fallback pattern work_state
    # already uses for state-level overrides. See employee_validation.py.
    country_code     = Column(String(2), nullable=True)

    # First-class (indexable/filterable) tax regime — e.g. India's
    # "Old"/"New" regime. Kept as a real column rather than a
    # compliance_fields JSON key because the tax resolver (engine/tax_resolver.py)
    # needs to filter canonical TaxSlab/ContributionRate rows by regime;
    # jurisdictions with no regime concept simply leave this NULL.
    tax_regime       = Column(String(20), nullable=True)

    # UK-specific: HMRC tax code (e.g. "1257L") and NI category letter
    # (e.g. "A"). NULL for every non-UK employee, and for UK employees
    # until explicitly set — the engine falls back to standard
    # assumptions (basic personal allowance, category A) when unset.
    tax_code         = Column(String(20), nullable=True)
    ni_category      = Column(String(5), nullable=True)

    # Generic across every country (not UK-only) — "Monthly"/"Weekly"/
    # "Fortnightly"/"FourWeekly". Defaults to "Monthly" so every existing
    # employee's numbers are completely unaffected; only engine/countries/
    # uk.py currently varies its calculation by this field.
    pay_frequency    = Column(String(20), nullable=False, default="Monthly", server_default="Monthly")

    # Government study-loan repayment, deducted via payroll above an
    # income threshold — the SAME mechanism under different names in the
    # UK (Student/Postgraduate Loan, e.g. "UK_PLAN1".."UK_PLAN5",
    # "UK_POSTGRAD") and Australia (HELP/HECS, e.g. "AU_HELP"). One
    # generic pair reused by both rather than two parallel field sets.
    study_loan_plan    = Column(String(20), nullable=True)
    study_loan_balance = Column(Numeric(12, 2), nullable=True)

    # Germany: whether this employee is liable for Kirchensteuer (church
    # tax) — an opt-in surcharge on income tax. Defaults False so no
    # existing employee's calculation changes.
    church_tax_liable = Column(Boolean, default=False, nullable=False, server_default="false")

    # Non-India statutory/bank identifiers (SSN, NINO, TFN, SIN, Steuer-ID,
    # IBAN, etc. — see employee_validation.py for the field set per
    # country). India keeps its own dedicated pan/uan/ifsc columns above
    # rather than duplicating them in here, since those already hold real
    # production data. Deliberately a SEPARATE column from custom_fields:
    # custom_fields is admin-defined free-form data (PayrollCustomFieldDefinition);
    # this is system-governed, regex-validated compliance data, and keeping
    # them apart avoids a key collision between the two.
    compliance_fields = Column(JSON, default=dict, nullable=False, server_default="{}")

    # Org-defined extra fields (see PayrollCustomFieldDefinition) — a JSON
    # bag of {field_key: value} rather than real columns, since the field
    # set itself is defined at runtime by admins, not at migration time.
    custom_fields    = Column(JSON, default=dict, nullable=False, server_default="{}")

    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    updated_at       = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("organization_id", "employee_code", name="uq_payroll_employee_org_code"),
        Index("ix_payroll_employees_org_status", "organization_id", "status"),
    )

    def __repr__(self):
        return f"<PayrollEmployee id={self.id} code={self.employee_code} status={self.status}>"


# ── Payroll Run ────────────────────────────────────────────────────────

class PayrollRun(Base):
    """One payroll cycle (monthly/bi-weekly)."""
    __tablename__ = "payroll_runs"

    id            = Column(Integer, primary_key=True, index=True)
    run_code      = Column(String(30), nullable=True, unique=True)

    # Display fields — map 1:1 onto RunsTable/RunDetailPage props.
    period_label  = Column(String(50), nullable=False)     # → run.period, e.g. "Jun 1-15, 2026"
    period_start  = Column(Date, nullable=False)
    period_end    = Column(Date, nullable=False)
    pay_date      = Column(Date, nullable=False)            # → run.payDate

    status        = Column(String(20), default=PayrollStatus.DRAFT.value, nullable=False, index=True)

    # Aggregates, recomputed whenever payslip items change.
    employee_count               = Column(Integer, default=0)                # → run.employees
    total_gross                  = Column(Numeric(14, 2), default=0)          # → run.gross
    total_deductions             = Column(Numeric(14, 2), default=0)          # → run.deductions (PF+ESI+PT, non-tax)
    total_taxes                  = Column(Numeric(14, 2), default=0)          # → run.taxes (TDS)
    total_employer_contribution  = Column(Numeric(14, 2), default=0)          # → run.employerContribution
    total_net                    = Column(Numeric(14, 2), default=0)          # → run.net

    notes         = Column(Text, nullable=True)
    created_by    = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_by   = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at   = Column(DateTime(timezone=True), nullable=True)
    authorized_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    authorized_at = Column(DateTime(timezone=True), nullable=True)
    paid_by       = Column(Integer, ForeignKey("users.id"), nullable=True)
    processed_at  = Column(DateTime(timezone=True), nullable=True)   # set when the run reaches PAID — doubles as "paid_at"

    # Policy-driven calculation mode snapshot — recorded at run creation time
    # so historical runs always know which mode was active.
    calculation_mode = Column(String(20), nullable=True, default="standard")

    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), onupdate=func.now())

    payslip_items = relationship("PayslipItem", back_populates="payroll_run", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_payroll_runs_org_status", "organization_id", "status"),
        # period_start is the primary filter/order column for the runs list,
        # the dashboard's month-range filters, and the trend chart's window
        # filter — all previously did a full table scan with no supporting
        # index.
        Index("ix_payroll_runs_org_period_start", "organization_id", "period_start"),
    )

    def __repr__(self):
        return f"<PayrollRun id={self.id} period={self.period_label} status={self.status}>"


# ── Payslip Item ───────────────────────────────────────────────────────

class PayslipItem(Base):
    """One employee's payslip within a payroll run.

    Employee identity/bank/PAN fields are *snapshotted* at generation time
    (rather than always joined live) so historical payslips stay accurate
    even if the employee's record changes or the employee later leaves —
    this is standard practice for payroll/financial documents.
    """
    __tablename__ = "payslip_items"

    id              = Column(Integer, primary_key=True, index=True)
    payslip_number  = Column(String(30), nullable=True, unique=True)
    payroll_run_id  = Column(Integer, ForeignKey("payroll_runs.id"), nullable=False, index=True)
    employee_id     = Column(Integer, ForeignKey("payroll_employees.id"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    # Snapshot fields (denormalized on purpose).
    employee_name   = Column(String(150), nullable=False)
    department      = Column(String(100), nullable=True)
    designation     = Column(String(100), nullable=True)
    date_of_joining = Column(Date, nullable=True)
    bank_name       = Column(String(100), nullable=True)
    bank_account    = Column(String(50), nullable=True)
    pan             = Column(String(20), nullable=True)
    uan             = Column(String(20), nullable=True)
    ifsc            = Column(String(20), nullable=True)
    # The employee's own jurisdiction at generation time (PayrollEmployee.country_code,
    # falling back to the org default) — snapshotted for the same reason the
    # fields above are: so a payslip's country/labels/currency stay tied to
    # the employee who was actually paid, not to whatever the org's default
    # jurisdiction happens to be when someone later views/exports it. NULL on
    # rows generated before this column existed; callers fall back to the
    # org's current default for those.
    country_code    = Column(String(2), nullable=True)
    # Snapshot of PayrollEmployee.work_state/work_locality at generation
    # time — same reproducibility reasoning as country_code above, just
    # one level (two levels) finer. NULL on payslips generated before
    # these columns existed or where the employee had no region set.
    work_state      = Column(String(100), nullable=True)
    work_locality   = Column(String(100), nullable=True)
    # Snapshot of PayrollEmployee.compliance_fields (SSN, NINO, IBAN, etc. —
    # see employee_validation.py for the full per-country set). pan/uan/ifsc
    # above only ever covered India; every other jurisdiction's identifiers
    # previously never made it onto the payslip at all.
    compliance_fields = Column(JSON, nullable=True)

    # Which exact canonical tax policy version produced this payslip's
    # numbers, frozen at generation time. If Super Admin later edits or
    # supersedes that pack version, this payslip's figures MUST NOT change —
    # tax_rule_snapshot is the actual rate/slab values used (not just a
    # pointer), so the payslip is reproducible even if the pack row itself
    # is later retired. NULL on payslips generated before this column
    # existed or where no canonical tax pack applied.
    tax_policy_pack_id = Column(Integer, ForeignKey("payroll_jurisdiction_packs.id"), nullable=True)
    tax_policy_version  = Column(String(20), nullable=True)
    tax_rule_snapshot   = Column(JSON, nullable=True)

    # Earnings.
    basic_salary      = Column(Numeric(12, 2), default=0)
    hra               = Column(Numeric(12, 2), default=0)
    special_allowance = Column(Numeric(12, 2), default=0)
    overtime          = Column(Numeric(12, 2), default=0)
    # Sum of rewards + bonus + other_compensation recorded on this
    # employee's PayrollAttendanceRecord rows within the run's pay
    # period. Previously this data was captured on the Attendance screen
    # but never reached gross pay — see _sum_attendance_extras in
    # service.py. Kept as its own line item (not folded into
    # special_allowance) so it stays auditable on the payslip.
    additional_compensation = Column(Numeric(12, 2), default=0, server_default="0")
    gross_pay         = Column(Numeric(12, 2), default=0)

    # Loss-of-pay proration transparency. total_working_days excludes
    # weekends within the run's period; payable_days additionally excludes
    # any day the employee's attendance record is "absent" or "leave" with
    # leave_type = "unpaid" (or NULL for legacy rows). Paid / sick / casual
    # leaves do NOT reduce payable_days. basic/hra/special_allowance above
    # are the *prorated* amounts actually paid; these two columns record
    # what the proration factor was, so a payslip is self-explanatory
    # without recomputing it.
    payable_days       = Column(Numeric(5, 2), nullable=True)
    total_working_days = Column(Numeric(5, 2), nullable=True)

    # Fixed 30-Day Payroll Model fields
    unpaid_leave_days  = Column(Integer, nullable=True, server_default="0")
    attendance_deduction = Column(Numeric(12, 2), default=0, server_default="0")
    per_day_salary     = Column(Numeric(12, 2), nullable=True)

    # Statutory deductions (employee side).
    pf                = Column(Numeric(12, 2), default=0)
    esi               = Column(Numeric(12, 2), default=0)
    professional_tax  = Column(Numeric(12, 2), default=0)
    tds               = Column(Numeric(12, 2), default=0)   # income tax withheld — INCLUDES surcharge/cess below, not additional to them
    # India: monthly breakdown of what's already folded into `tds` above —
    # informational only, never summed again into total_deductions.
    surcharge         = Column(Numeric(12, 2), default=0, server_default="0")
    cess              = Column(Numeric(12, 2), default=0, server_default="0")
    # US-specific
    social_security   = Column(Numeric(12, 2), default=0)
    medicare          = Column(Numeric(12, 2), default=0)
    # UK-specific
    ni_employee       = Column(Numeric(12, 2), default=0)
    # UK/Australia: government study-loan repayment (Student/Postgraduate
    # Loan in the UK, HELP/HECS in Australia) — one shared line, same
    # reasoning as PayrollEmployee.study_loan_plan/study_loan_balance.
    study_loan_deduction = Column(Numeric(12, 2), default=0, server_default="0")
    # UK: employee-side Workplace Pension deduction — distinct from
    # employer_pension below. Zero unless an employee pension rate has
    # been explicitly configured (see engine/countries/uk.py).
    employee_pension  = Column(Numeric(12, 2), default=0, server_default="0")
    # Germany: Kirchensteuer (church tax), only nonzero when the employee
    # is flagged church_tax_liable.
    church_tax        = Column(Numeric(12, 2), default=0, server_default="0")
    # Canada: CPP2, the second-tier contribution above the YMPE — its own
    # line rather than folded into social_security, matching how every
    # other country already breaks out multiple named statutory lines.
    cpp2              = Column(Numeric(12, 2), default=0, server_default="0")
    total_deductions  = Column(Numeric(12, 2), default=0)   # all employee deductions, INCLUDING tds — see engine/*.py

    # Employer-side contributions (informational, not deducted from employee).
    employer_pf       = Column(Numeric(12, 2), default=0)
    employer_esi       = Column(Numeric(12, 2), default=0)
    employer_social_security = Column(Numeric(12, 2), default=0)
    employer_medicare  = Column(Numeric(12, 2), default=0)
    employer_pension   = Column(Numeric(12, 2), default=0)
    # UK: employer National Insurance — genuinely absent until now (only
    # employee NI was ever modeled).
    employer_ni        = Column(Numeric(12, 2), default=0, server_default="0")
    # US: FUTA — seeded as a display row since day one but never actually
    # calculated or surfaced anywhere until now.
    employer_futa      = Column(Numeric(12, 2), default=0, server_default="0")

    net_pay           = Column(Numeric(12, 2), default=0)

    status          = Column(String(20), default=PayslipStatus.PENDING.value, nullable=False, index=True)
    paid_at         = Column(DateTime(timezone=True), nullable=True)
    notes           = Column(Text, nullable=True)

    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), onupdate=func.now())

    payroll_run = relationship("PayrollRun", back_populates="payslip_items")
    allowance_items = relationship("PayslipAllowanceItem", back_populates="payslip_item", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("payroll_run_id", "employee_id", name="uq_payslip_run_employee"),
        Index("ix_payslip_items_org_status", "organization_id", "status"),
    )

    def __repr__(self):
        return f"<PayslipItem id={self.id} employee_id={self.employee_id} net={self.net_pay}>"


# Per-payslip breakdown of the org's dynamic, Super-Admin-defined allowance
# components (see policy/models.py's PolicyAllowanceComponent) — a real
# child table rather than fixed columns on PayslipItem because the set of
# component names is admin-defined and unbounded (a new named allowance
# must not require a schema migration). `special_allowance` on PayslipItem
# above stays the final residual (gross - basic - hra - sum(these items)),
# unchanged in spirit from before this table existed — it's simply computed
# after these named slices are carved out too.
class PayslipAllowanceItem(Base):
    __tablename__ = "payslip_allowance_items"

    id              = Column(Integer, primary_key=True, index=True)
    payslip_item_id = Column(Integer, ForeignKey("payslip_items.id"), nullable=False, index=True)

    key    = Column(String(50), nullable=False)    # matches PolicyAllowanceComponent.key
    label  = Column(String(100), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False, default=0)

    payslip_item = relationship("PayslipItem", back_populates="allowance_items")

    __table_args__ = (
        UniqueConstraint("payslip_item_id", "key", name="uq_payslip_allowance_item_key"),
    )


# ── Payroll Attendance Records ─────────────────────────────────────────
# Tracks daily attendance + compensation (rewards, bonus) per employee.
# Used by the Attendance & Compensation page in the payroll frontend.

class PayrollAttendanceRecord(Base):
    __tablename__ = "payroll_attendance_records"

    id                = Column(Integer, primary_key=True, index=True)
    batch_code        = Column(String(30), nullable=True)
    organization_id   = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    employee_id       = Column(Integer, ForeignKey("payroll_employees.id"), nullable=False, index=True)

    date              = Column(Date, nullable=False, index=True)
    check_in          = Column(String(10), nullable=True)    # "09:00"
    check_out         = Column(String(10), nullable=True)    # "18:00"
    status            = Column(String(20), default="present", nullable=False)  # present / absent / leave
    leave_type        = Column(String(20), nullable=True)  # None when status != "leave"; otherwise: unpaid / paid / sick / casual
    hours             = Column(String(10), nullable=True)    # "8" or "8.5"

    rewards           = Column(Numeric(12, 2), default=0)
    bonus             = Column(Numeric(12, 2), default=0)
    other_compensation = Column(Numeric(12, 2), default=0)

    notes             = Column(Text, nullable=True)

    # Link to PayrollLeaveRequest when status == "leave"
    leave_request_id  = Column(Integer, ForeignKey("payroll_leave_requests.id"), nullable=True, index=True)
    is_half_day       = Column(Boolean, default=False, nullable=False)

    created_at        = Column(DateTime(timezone=True), server_default=func.now())
    updated_at        = Column(DateTime(timezone=True), onupdate=func.now())

    leave_request     = relationship("PayrollLeaveRequest", foreign_keys=[leave_request_id])

    __table_args__ = (
        Index("ix_payroll_attendance_org_date", "organization_id", "date"),
        Index("ix_payroll_attendance_emp_date", "employee_id", "date"),
    )

    def __repr__(self):
        return f"<PayrollAttendanceRecord id={self.id} emp={self.employee_id} date={self.date} status={self.status}>"


# ── Company Holiday Calendar ─────────────────────────────────────────────
# Shared source of truth for "is this a working day", used by
# service._count_unpaid_leave_days (Fixed 30-Day Payroll Model) and intended to also back the
# Attendance/Leave pages' holiday displays, so all three agree on the same
# calendar instead of each maintaining their own.

class PayrollHoliday(Base):
    __tablename__ = "payroll_holidays"

    id              = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    date            = Column(Date, nullable=False)
    name            = Column(String(200), nullable=True)
    # 2-letter jurisdiction code (IN/US/UK/AU/DE/CA) this holiday belongs to.
    # Needed so an Enterprise org with more than one onboarded jurisdiction
    # can hold two different countries' holidays without colliding on the
    # same calendar date — see _seed_holidays_for_country in service.py.
    country         = Column(String(10), nullable=True)
    # "National" for seeded jurisdiction defaults, "Company" for
    # admin-added holidays. Kept as a real column (rather than guessed
    # client-side) so future categories (Regional/Branch/Optional) don't
    # need another migration.
    category        = Column(String(30), nullable=True, default="National")

    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("organization_id", "country", "date", name="uq_payroll_holiday_org_country_date"),
        Index("ix_payroll_holidays_org_date", "organization_id", "date"),
    )


# ── Compliance: Contribution Rates ────────────────────────────────────

class ContributionRate(Base):
    """Statutory contribution rate row (PF / ESI / PT / TDS) shown in
    Compliance > Contribution Rates. `employee_rate_pct` / `employer_rate_pct`
    are the actual numeric rates used by payslip generation; `*_share`
    columns are the human-readable display strings the table renders.

    A row with `organization_id IS NULL` is a CANONICAL, Super-Admin-owned
    value linked to a `JurisdictionPack` (pack_type="tax") via
    `jurisdiction_pack_id` — the single government-mandated source of truth.
    A row with `organization_id` set is that org's own synced copy (see
    `sync_org_rates_from_canonical` in service.py), which is what
    `get_contribution_rates()`/the calculation engine actually reads — this
    keeps the engine's read path unchanged while moving *authorship* of the
    canonical values to Super Admin only. Deliberately not a separate
    `ContributionRule` table — same shape, just a nullable owner.
    """
    __tablename__ = "payroll_contribution_rates"

    id               = Column(Integer, primary_key=True, index=True)
    organization_id  = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)

    component_key        = Column(String(20), nullable=False)   # "pf" | "esi" | "pt" | "tds"
    label                = Column(String(100), nullable=False)  # → r.label
    employee_share       = Column(String(50), nullable=False)   # → r.employee (display string)
    employer_share       = Column(String(50), nullable=False)   # → r.employer (display string)
    total                = Column(String(50), nullable=False)   # → r.total (display string)

    employee_rate_pct    = Column(Numeric(6, 4), nullable=True)  # e.g. 0.1200 for 12%
    employer_rate_pct    = Column(Numeric(6, 4), nullable=True)
    flat_amount          = Column(Numeric(10, 2), nullable=True)  # for flat components like PT
    # One generic slot for a non-numeric configuration value (UK pension
    # calculation basis "QUALIFYING_EARNINGS"/"BASIC_PAY"/"PENSIONABLE_EARNINGS",
    # auto-enrolment "true"/"false") — reuses this table's existing
    # row-per-component_key convention instead of a new table. Null for
    # every existing row.
    text_value           = Column(String(50), nullable=True)

    jurisdiction_country = Column(String(10), nullable=False, server_default="IN", default="IN")
    # Null = country-level, matching the convention JurisdictionPack/
    # GlobalStatutoryRate already use for optional state/province scoping.
    jurisdiction_state    = Column(String(100), nullable=True)
    # Third hierarchy level below state (e.g. a city/local body) — null
    # for every row today; a genuine locality-scoped rate is opt-in, never
    # required. Mirrors jurisdiction_state's own null-means-broader-scope
    # convention one level down.
    jurisdiction_locality = Column(String(100), nullable=True)
    tax_regime            = Column(String(20), nullable=True)
    # Which canonical tax pack version this row was authored under/synced
    # from. NULL on org-scoped rows created before this column existed.
    jurisdiction_pack_id  = Column(Integer, ForeignKey("payroll_jurisdiction_packs.id"), nullable=True)

    sort_order           = Column(Integer, default=0)
    created_at           = Column(DateTime(timezone=True), server_default=func.now())
    updated_at           = Column(DateTime(timezone=True), onupdate=func.now())

    # Plain UniqueConstraint replaced with two partial unique indexes —
    # Postgres treats every NULL as distinct, so a single constraint
    # including a nullable organization_id would not prevent duplicate
    # canonical (organization_id IS NULL) rows. Same pattern as
    # GlobalStatutoryRate (super_admin/models.py).
    __table_args__ = (
        # sqlite_where mirrors postgresql_where so the SQLite dev/test
        # fallback (database.py's resolve_database_url) enforces the same
        # partial-uniqueness semantics as production Postgres — without it,
        # SQLite silently drops the WHERE clause and applies each index
        # unconditionally, which would wrongly forbid two different orgs
        # from sharing a canonical (org_id-less) country/component/regime
        # combination — the normal case.
        Index(
            # tax_regime included so an org can hold BOTH regimes' rows
            # for the same component_key side by side (e.g. two
            # rebate_87a_limit rows, tagged "Old" and "New") — added for
            # the Tax Parameters feature; a regime-agnostic row
            # (tax_regime NULL) is still unique per component_key on its
            # own, same as before.
            "uq_contribution_rate_org_country_component",
            "organization_id", "jurisdiction_country", "component_key", "tax_regime",
            unique=True,
            postgresql_where=text("organization_id IS NOT NULL"),
            sqlite_where=text("organization_id IS NOT NULL"),
        ),
        Index(
            "uq_contribution_rate_canonical_country_state_component",
            "jurisdiction_country", "jurisdiction_state", "component_key", "tax_regime",
            unique=True,
            postgresql_where=text("organization_id IS NULL"),
            sqlite_where=text("organization_id IS NULL"),
        ),
    )


# ── Compliance: Tax Slabs ──────────────────────────────────────────────

class TaxSlab(Base):
    """One income tax slab row shown in Compliance > Tax Slabs.

    Same canonical/org-scoped split as ContributionRate above:
    `organization_id IS NULL` = Super-Admin-owned canonical row linked to a
    `JurisdictionPack` (pack_type="tax"); `organization_id` set = an org's
    synced copy, which is what the engine actually reads. Deliberately not
    a separate `TaxBracket` table.
    """
    __tablename__ = "payroll_tax_slabs"

    id               = Column(Integer, primary_key=True, index=True)
    organization_id  = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)

    min_amount           = Column(Numeric(14, 2), nullable=False)
    max_amount           = Column(Numeric(14, 2), nullable=True)   # null = "and above"
    rate_pct             = Column(Numeric(5, 2), nullable=False)   # e.g. 5.00 for 5%
    rate_label           = Column(String(20), nullable=False)      # → s.rate, e.g. "5%" or "Nil"
    tax_formula          = Column(String(150), nullable=False)     # → s.tax, display text
    sort_order           = Column(Integer, default=0)

    jurisdiction_country = Column(String(10), nullable=False, server_default="IN", default="IN")
    jurisdiction_state    = Column(String(100), nullable=True)   # null = country-level
    jurisdiction_locality = Column(String(100), nullable=True)   # null = state-level (or country-level if state is also null)
    tax_regime            = Column(String(20), nullable=True)

    # MARGINAL_RATE (default, existing brackets) | FLAT_RATE | FIXED_PLUS_MARGINAL
    # | FORMULA | TABLE_LOOKUP | CONTRIBUTION | PT_FLAT. Only FORMULA rows use
    # formula_expression instead of min/max/rate_pct — e.g. Germany's
    # Lohnsteuer, which isn't a clean bracket table. Existing bracket rows
    # for every country default to MARGINAL_RATE, so no calculator changes
    # are required until a row actually opts into FORMULA. PT_FLAT rows
    # (India's state-level Professional Tax, bracketed by gross salary, not
    # a percentage) use flat_amount instead of rate_pct — rate_pct stays
    # 0.00 (still NOT NULL) on those rows, simply unread by the engine.
    rule_type             = Column(String(20), nullable=False, default="MARGINAL_RATE", server_default="MARGINAL_RATE")
    formula_expression    = Column(Text, nullable=True)
    # PT_FLAT only: the fixed monthly deduction for this gross-income
    # bracket, and an optional override for whichever month absorbs the
    # annual-cap rounding (e.g. many states adjust February so 11×monthly +
    # this equals the statutory annual ceiling). Null for every other
    # rule_type — additive, no existing row's behavior changes.
    flat_amount           = Column(Numeric(10, 2), nullable=True)
    adjustment_amount     = Column(Numeric(10, 2), nullable=True)
    # NI_BAND only (UK National Insurance categories): which NI category
    # letter ("A"/"B"/"C"/"H"/"M") this band applies to, and the employer
    # rate for this band — `rate_pct` above doubles as the EMPLOYEE rate
    # for NI_BAND rows. min_amount/max_amount are this band's threshold
    # range, exactly like every other bracket row. Null for every other
    # rule_type.
    ni_category           = Column(String(2), nullable=True)
    employer_rate_pct     = Column(Numeric(5, 2), nullable=True)
    # Which canonical tax pack version this row was authored under/synced from.
    jurisdiction_pack_id  = Column(Integer, ForeignKey("payroll_jurisdiction_packs.id"), nullable=True)

    created_at           = Column(DateTime(timezone=True), server_default=func.now())
    updated_at           = Column(DateTime(timezone=True), onupdate=func.now())


# ── Compliance: Company Details ────────────────────────────────────────

class CompanyComplianceDetails(Base):
    """One row per organization holding the company's compliance profile."""
    __tablename__ = "payroll_company_compliance"

    id                    = Column(Integer, primary_key=True, index=True)
    organization_id       = Column(Integer, ForeignKey("organizations.id"), nullable=False, unique=True, index=True)

    name                  = Column(String(200), default="")
    type                  = Column(String(100), default="")
    tax_no                = Column(String(50), default="")
    employer_id           = Column(String(50), default="")  # doubles as "Registration Number" in the UI
    address               = Column(String(300), default="")
    industry              = Column(String(100), default="")
    email                 = Column(String(255), default="")
    phone                 = Column(String(50), default="")
    # Blank, not "India" — this field stores the 2-letter code the Compliance
    # dropdown actually uses ("IN"/"US"/...), and a non-blank-but-unmatched
    # default silently renders as an unselected dropdown (see get_company_details).
    jurisdiction_country  = Column(String(100), default="")
    jurisdiction_state    = Column(String(100), default="")
    compliance_pack       = Column(String(100), default="")
    schedule              = Column(String(100), default="")
    settlement_bank       = Column(String(100), default="")
    settlement_acc        = Column(String(50), default="")
    # Jurisdiction-aware tax/registration identifiers synced from the
    # Organization.tax_identifiers captured at registration (see
    # app/core/jurisdiction.py). Keyed by the same field keys, e.g.
    # {"gstin": "...", "pan": "...", "cin": "..."}. Backfilled once from the
    # org row and then editable/overridable via the Compliance Details tab.
    tax_identifiers       = Column(JSON, nullable=True)

    # Which JurisdictionPack this org is currently using, if any. Nullable —
    # orgs created before this table existed, or orgs in a jurisdiction
    # without a built pack yet, simply have no active pack.
    # TODO: active_pack_id has no ON DELETE behaviour — if a JurisdictionPack
    # row is deleted, this FK silently sets to NULL, leaving the org with no
    # active pack but no error.  Should either CASCADE (and propagate the
    # change to rate_map lookups) or RESTRICT (and prevent pack deletion
    # while any org references it).  Also missing: a relationship() helper
    # so SQLAlchemy can eager-load the pack without a manual join.
    #
    # Known bug: this one FK is shared by both tax packs and policy packs,
    # so assigning one silently drops live-tracking of the other.
    active_pack_id        = Column(Integer, ForeignKey("payroll_jurisdiction_packs.id"), nullable=True)

    # Set the first time an admin explicitly saves Compliance details via
    # update_company_details() — never by get_company_details()'s
    # auto-creation of a blank row on first GET. Doubles as the jurisdiction
    # lock signal: once non-null, jurisdiction_country can no longer be
    # changed through this endpoint (see update_company_details).
    configured_at         = Column(DateTime(timezone=True), nullable=True)

    created_at            = Column(DateTime(timezone=True), server_default=func.now())
    updated_at            = Column(DateTime(timezone=True), onupdate=func.now())

    @property
    def is_configured(self) -> bool:
        """True once an admin has explicitly saved Compliance details at
        least once — see configured_at above."""
        return self.configured_at is not None


# ── Compliance: Jurisdiction Pack ────────────────────────────────────
# Maps to Section 5 ("Pack Identity and Metadata") and Section 19 ("API
# and Data Model Implications") of the Jurisdiction Compliance Pack
# Template. Deliberately keyed by jurisdiction (country + optional state),
# NOT by organization_id — a pack describes a jurisdiction's rules and is
# meant to be reused across every org operating in that jurisdiction, not
# duplicated per company. CompanyComplianceDetails references the pack
# it's currently using via active_pack_id, rather than owning pack data
# itself.
#
# This is a first, intentionally small slice of Section 19's full model
# (Jurisdiction, JurisdictionPack, RuleSet, RuleVersion, SafeExpression,
# Accumulator, CalculationSnapshot, RetroDelta, ActivationGate,
# SourceReference). RuleSet/RuleVersion/SafeExpression/Accumulator are not
# built as separate tables — the actual rule data (contribution rates, tax
# slabs) lives in ContributionRate/TaxSlab, now linked to a pack version via
# jurisdiction_pack_id (see the Global Payroll Tax Engine additions below
# and on those two models).
class JurisdictionPack(Base):
    """Versioned identity/metadata for a jurisdiction compliance pack."""
    __tablename__ = "payroll_jurisdiction_packs"

    id                   = Column(Integer, primary_key=True, index=True)

    pack_id              = Column(String(100), nullable=False)  # e.g. "IN-PAYROLL-2026-V1"
    jurisdiction_country = Column(String(100), nullable=False)
    jurisdiction_state   = Column(String(100), nullable=True)   # null = country-level pack
    jurisdiction_locality = Column(String(100), nullable=True)  # null = state-level (or country-level) pack

    # "tax" | "policy" — keeps Tax and Policy records in this same versioned
    # table (no parallel Tax system) while letting the UI show them as two
    # clearly separate lists instead of one mixed table. Every pre-existing
    # row is a policy pack (policy_defaults is the only thing this table
    # held before "tax" packs existed), so this defaults to "policy" for
    # both new rows and the backfill of old ones.
    pack_type            = Column(String(10), nullable=False, default="policy", server_default="policy")

    version              = Column(String(20), nullable=False, default="1.0")
    status               = Column(String(20), nullable=False, default="Draft")
    # Draft | In Review | QA | Approved | Active | Deprecated | Retired — per spec Section 5/17.

    effective_from       = Column(Date, nullable=True)
    effective_to         = Column(Date, nullable=True)

    compliance_owner     = Column(String(150), default="")
    engineering_owner    = Column(String(150), default="")
    source_references    = Column(Text, default="")

    # ── Super Admin Compliance module additions ──────────────────────────
    # Additive/nullable so existing rows (and the org-scoped Compliance UI
    # that predates these) are unaffected. Applied to the live DB via
    # migrations/sync_schema.py rather than a destructive migration.
    regulatory_authority = Column(String(200), nullable=True)
    compliance_category  = Column(String(100), nullable=True)
    change_summary       = Column(Text, nullable=True)
    next_review_date     = Column(Date, nullable=True)
    created_by_id        = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by_id        = Column(Integer, ForeignKey("users.id"), nullable=True)

    # ── Global Payroll Tax Engine additions (pack_type="tax" packs) ──────
    # Nullable/additive — every existing row (all "policy" packs today) is
    # unaffected. Only tax packs meaningfully set these.
    tax_year             = Column(String(20), nullable=True)   # e.g. "2026-27" or "2026"
    tax_regime           = Column(String(20), nullable=True)   # e.g. India's "Old"/"New"; null where not applicable
    # Which regime's rows/parameters an employee with no explicit
    # PayrollEmployee.tax_regime should be treated as — a DIFFERENT concept
    # from tax_regime above (which tags which single regime this whole
    # pack IS for, used by the canonical pack lookup in engine/tax_resolver.py).
    # A pack can hold BOTH regimes' rows side by side (each row tagged via
    # its own ContributionRate/TaxSlab.tax_regime); this column is just the
    # UI/engine's fallback pick among them. Null = no default set.
    default_tax_regime  = Column(String(20), nullable=True)
    approved_by_id       = Column(Integer, ForeignKey("users.id"), nullable=True)
    currency             = Column(String(10), nullable=True)
    # Self-reference so a new version can point back at what it replaced,
    # without ever deleting/overwriting the prior row — version history
    # stays intact by construction (new row per version).
    previous_version_id  = Column(Integer, ForeignKey("payroll_jurisdiction_packs.id"), nullable=True)

    # Links a sub-jurisdiction pack (e.g. a Scotland tax pack) to the
    # national pack it inherits from for the same tax year (e.g. UK
    # National) — a DIFFERENT relationship from previous_version_id above
    # (which chains versions of the SAME pack over time). Null for every
    # national-level pack, and for every sub-jurisdiction pack that hasn't
    # been explicitly linked yet — the resolver falls back to "the
    # country's Active national pack for this tax year" when unset, so no
    # existing pack's behavior changes just because this column exists.
    parent_pack_id       = Column(Integer, ForeignKey("payroll_jurisdiction_packs.id"), nullable=True)

    # Per-field default values + override permission for the SAME fields
    # payroll/policy/models.py's PayrollPolicy exposes (calculation_mode,
    # employee_categories, overtime_rule) — e.g.
    # {"calculation_mode": {"value": "standard", "allowOverride": false}, ...}.
    # A JSON blob here (not a mirrored set of child tables) matches this
    # module's existing convention for flexible per-field config — see
    # PolicyLeaveRule.config and EnterpriseJurisdiction's *_config columns.
    # NULL/absent-field means "fully overridable", so an org with no pack
    # assigned, or a pack that never sets this, behaves exactly as before
    # this column existed.
    policy_defaults      = Column(JSON, nullable=True)

    created_at           = Column(DateTime(timezone=True), server_default=func.now())
    updated_at           = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("pack_id", "version", name="uq_jurisdiction_pack_id_version"),
        Index("ix_jurisdiction_packs_country_state", "jurisdiction_country", "jurisdiction_state"),
    )

    @property
    def scope_type(self) -> str:
        """Computed, not a stored column — reuses the exact convention
        jurisdiction_state already establishes (null = country-level)
        rather than duplicating it in a second column. "NATIONAL" for a
        country-level pack, "SUB_JURISDICTION" for a state/province/
        devolved-nation pack (e.g. Scotland)."""
        return "NATIONAL" if not self.jurisdiction_state else "SUB_JURISDICTION"


# ── Tax Configuration Audit ─────────────────────────────────────────────
# One canonical audit trail for every mutation to a Super-Admin-owned
# canonical tax/contribution/pack row. No audit system existed anywhere in
# the codebase prior to this (PayrollActivityLog, above, covers unrelated
# payroll-run activity, not tax configuration) — this is genuinely new,
# not a duplicate of an existing table.
class TaxConfigurationAudit(Base):
    __tablename__ = "payroll_tax_configuration_audit"

    id             = Column(Integer, primary_key=True, index=True)

    actor_id       = Column(Integer, ForeignKey("users.id"), nullable=True)
    action         = Column(String(30), nullable=False)   # "create" | "update" | "status_change" | "delete"
    entity_type    = Column(String(30), nullable=False)    # "jurisdiction_pack" | "tax_slab" | "contribution_rate"
    entity_id      = Column(Integer, nullable=False)

    jurisdiction_pack_id = Column(Integer, ForeignKey("payroll_jurisdiction_packs.id"), nullable=True)
    tax_version           = Column(String(20), nullable=True)
    legal_reference       = Column(String(200), nullable=True)

    old_value      = Column(JSON, nullable=True)
    new_value      = Column(JSON, nullable=True)
    reason         = Column(Text, nullable=True)

    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_tax_audit_entity", "entity_type", "entity_id"),
        Index("ix_tax_audit_pack", "jurisdiction_pack_id"),
    )


class ComplianceDocument(Base):
    """Uploaded compliance documents for payroll (e.g. statutory filings)."""
    __tablename__ = "payroll_compliance_documents"

    id               = Column(Integer, primary_key=True, index=True)
    organization_id  = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    title            = Column(String(200), nullable=False)
    document_type    = Column(String(100), nullable=True)
    category         = Column(String(100), default="other")
    description      = Column(Text, nullable=True)

    file_path        = Column(String(500), nullable=False)
    file_name        = Column(String(255), nullable=False)
    file_size        = Column(Integer, nullable=True)
    mime_type        = Column(String(100), nullable=True)

    uploaded_by      = Column(Integer, ForeignKey("users.id"), nullable=True)
    uploaded_at      = Column(DateTime(timezone=True), server_default=func.now())

    # Jurisdiction this document was uploaded under (e.g. "IN"/"US"/"UK").
    # Used by GET /compliance/documents?country=XX to scope the list per tab.
    country          = Column(String(10), nullable=True, index=True)

    # Extraction lifecycle + result. `extracted_data` holds the same shape
    # the frontend expects under `extracted`:
    #   { contributionRates: [...], taxSlabs: [...], requirements: [...] }
    # so the API response can be handed to normalizeComplianceDocument()
    # with no client-side reshaping.
    status           = Column(String(20), default=ComplianceDocumentStatus.PROCESSING.value, nullable=False)
    extracted_data   = Column(JSON, nullable=True)
    error_message     = Column(Text, nullable=True)

    def __repr__(self):
        return f"<ComplianceDocument id={self.id} title={self.title} status={self.status}>"


# ── Dashboard: Activity Log ────────────────────────────────────────────

# ── Payroll Leave Allocations ────────────────────────────────────────────

class PayrollLeaveAllocation(Base):
    """Per-employee leave allocation (12 types), tracked via a leave_balances JSON column.
    One row per employee per organization; upserted on save."""
    __tablename__ = "payroll_leave_allocations"

    id                  = Column(Integer, primary_key=True, index=True)
    organization_id     = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    employee_id         = Column(Integer, ForeignKey("payroll_employees.id"), nullable=False, index=True)

    leave_balances       = Column(JSON, default=dict, nullable=True)

    period_label        = Column(String(50), nullable=True)
    notes               = Column(Text, nullable=True)

    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    updated_at          = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("organization_id", "employee_id", name="uq_payroll_leave_org_emp"),
        Index("ix_payroll_leave_org", "organization_id"),
    )

    def __repr__(self):
        used_total = sum(b.get("used", 0) for b in (self.leave_balances or {}).values())
        return f"<PayrollLeaveAllocation emp={self.employee_id} used={used_total}>"


class PayrollLeaveRequestStatus(str, enum.Enum):
    PENDING  = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class PayrollLeaveRequest(Base):
    """Individual leave request raised by an employee, tracked within the payroll module.
    One row per request; admin reviews (approve/reject) updates status and leave allocation balances."""
    __tablename__ = "payroll_leave_requests"

    id                  = Column(Integer, primary_key=True, index=True)
    request_code        = Column(String(30), nullable=True, unique=True)
    organization_id     = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    employee_id         = Column(Integer, ForeignKey("payroll_employees.id"), nullable=False, index=True)

    leave_type          = Column(String(20), nullable=False)   # paid / unpaid / sick / compOff
    start_date          = Column(Date, nullable=False)
    end_date            = Column(Date, nullable=False)
    days                = Column(Integer, nullable=False, default=1)
    reason              = Column(Text, nullable=True)

    status              = Column(String(20), nullable=False, default="pending")  # pending / approved / rejected
    reviewed_by         = Column(Integer, nullable=True)
    reviewed_at         = Column(DateTime(timezone=True), nullable=True)
    source              = Column(String(20), nullable=False, default="manual")  # manual / email

    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    updated_at          = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_payroll_leave_req_org", "organization_id"),
        Index("ix_payroll_leave_req_status", "organization_id", "status"),
    )

    def __repr__(self):
        return f"<PayrollLeaveRequest emp={self.employee_id} type={self.leave_type} status={self.status}>"


class PayrollActivityLog(Base):
    """Audit-trail entries that back the dashboard 'Recent activity' feed.
    Written by service.py whenever a meaningful payroll action happens
    (run created, run advanced/approved, payslip generated, company
    details updated, etc.) so the dashboard reflects real events instead
    of being derived/faked.
    """
    __tablename__ = "payroll_activity_log"

    id               = Column(Integer, primary_key=True, index=True)
    organization_id  = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    description      = Column(String(300), nullable=False)
    status           = Column(String(20), default=ActivityStatus.INFO.value, nullable=False)
    actor_id         = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now(), index=True)


# ── Employee data-collection forms ("Send Template") ────────────────────
# Lets an admin build a form (standard Employee fields + org-defined custom
# fields), email it to one or more employees as a no-login link, and review
# what they submit before it's applied to PayrollEmployee.

class CustomFieldType(str, enum.Enum):
    TEXT   = "text"
    NUMBER = "number"
    DATE   = "date"
    SELECT = "select"


class PayrollCustomFieldDefinition(Base):
    """An org-defined extra employee field, added via the form builder.
    Once created it applies to every employee in the org (surfaced in
    EmployeeForm/EmployeeTable/EmployeeDetailPanel), not just the form that
    introduced it — values live in PayrollEmployee.custom_fields, keyed by
    field_key."""
    __tablename__ = "payroll_custom_field_definitions"

    id               = Column(Integer, primary_key=True, index=True)
    organization_id  = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    field_key        = Column(String(60), nullable=False)
    label            = Column(String(150), nullable=False)
    field_type       = Column(String(20), default=CustomFieldType.TEXT.value, nullable=False)
    select_options   = Column(JSON, nullable=True)   # list[str], only when field_type == "select"
    created_by       = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("organization_id", "field_key", name="uq_payroll_custom_field_org_key"),
    )

    def __repr__(self):
        return f"<PayrollCustomFieldDefinition {self.field_key} org={self.organization_id}>"


class PayrollUpdateForm(Base):
    """A saved, reusable data-collection form — which standard Employee
    fields it asks for plus any custom fields, sent to employees to fill in
    without logging in."""
    __tablename__ = "payroll_update_forms"

    id               = Column(Integer, primary_key=True, index=True)
    organization_id  = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    name             = Column(String(150), nullable=False)
    # Ordered list of {key, label, type, source: "standard"|"custom", required}
    fields_config    = Column(JSON, nullable=False, default=list)
    created_by       = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<PayrollUpdateForm {self.name} org={self.organization_id}>"


class FormSendStatus(str, enum.Enum):
    SENT      = "sent"
    OPENED    = "opened"
    SUBMITTED = "submitted"
    EXPIRED   = "expired"


class PayrollUpdateFormSend(Base):
    """One outstanding invite for a specific employee to fill in a specific
    form — a single-use secure token, emailed as a link. Not linked to any
    login account since PayrollEmployee records don't have one."""
    __tablename__ = "payroll_update_form_sends"

    id               = Column(Integer, primary_key=True, index=True)
    organization_id  = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    form_id          = Column(Integer, ForeignKey("payroll_update_forms.id"), nullable=False, index=True)
    employee_id      = Column(Integer, ForeignKey("payroll_employees.id"), nullable=False, index=True)
    token            = Column(String(64), nullable=False, unique=True, index=True)
    status           = Column(String(20), default=FormSendStatus.SENT.value, nullable=False)
    sent_at          = Column(DateTime(timezone=True), server_default=func.now())
    opened_at        = Column(DateTime(timezone=True), nullable=True)
    submitted_at     = Column(DateTime(timezone=True), nullable=True)
    expires_at       = Column(DateTime(timezone=True), nullable=False)

    def __repr__(self):
        return f"<PayrollUpdateFormSend emp={self.employee_id} status={self.status}>"


class FormSubmissionStatus(str, enum.Enum):
    PENDING  = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class PayrollUpdateFormSubmission(Base):
    """What an employee submitted via a PayrollUpdateFormSend link, held for
    admin review — nothing here is written to PayrollEmployee until
    approved."""
    __tablename__ = "payroll_update_form_submissions"

    id               = Column(Integer, primary_key=True, index=True)
    organization_id  = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    send_id          = Column(Integer, ForeignKey("payroll_update_form_sends.id"), nullable=False, index=True)
    submitted_data   = Column(JSON, nullable=False)   # {field_key: value}
    status           = Column(String(20), default=FormSubmissionStatus.PENDING.value, nullable=False, index=True)
    reviewed_by      = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at      = Column(DateTime(timezone=True), nullable=True)
    review_notes     = Column(String(300), nullable=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<PayrollUpdateFormSubmission send={self.send_id} status={self.status}>"