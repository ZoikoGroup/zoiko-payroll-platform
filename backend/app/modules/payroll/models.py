"""
modules/payroll/models.py
-------------------------
SQLAlchemy ORM models for the Zoiko Payroll module.

Tables:
  - PayrollEmployee           → payroll's own employee master data (multi-tenant, org-scoped;
                                 intentionally NOT linked to app.modules.employee.Employee,
                                 which is the separate HR/auth login record)
  - EmployeeStatutoryProfile   → effective-dated history of one employee's jurisdiction-specific
                                 statutory facts (tax class, church tax, care-insurance status, ...) —
                                 distinct from PayrollEmployee's own mutable, non-dated fields
  - PapAlgorithmAsset          → versioned, source-hashed, immutable-once-published container for the
                                 German BMF PAP wage-tax algorithm — container/evidence only, no
                                 execution logic (see engine/countries/germany.py, unchanged)
  - GermanyHealthFund          → effective-dated Krankenkasse (health fund) Zusatzbeitrag rate registry —
                                 configuration only, no GKV contribution is calculated anywhere from it
  - GermanyContributionCeiling → effective-dated, branch-aware (GKV/PV vs RV/ALV) contribution ceiling
                                 registry — configuration only, no contribution is calculated from it
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
    # Canada-specific consumer today (CPP/QPP's age 18/70 mandatory
    # contribution window, ZP-TAX-CA-2026-001 §10 — see
    # engine/countries/canada.py's _is_age_gated_cpp_stopped), but a
    # generically useful HR fact, not a Canada-only field — NULL for
    # every employee until entered, same as date_of_joining before it.
    date_of_birth    = Column(Date, nullable=True)
    # India Gratuity Phase 2 (ZP-TAX-IN-2026-27-001 §11) — NULL for every
    # employee until entered; the gratuity liability calculator (india.py's
    # calculate_gratuity) requires both this and date_of_joining to compute
    # completed service, and stays uncomputable without either.
    date_of_leaving  = Column(Date, nullable=True)
    # India Maharashtra Professional Tax Phase 3 (ZP-TAX-IN-2026-27-001
    # §13.2) — a genuine legal fact Maharashtra's PT brackets are
    # differentiated by (real statute, not a proxy for anything else).
    # NULL for every employee until entered, same convention as
    # date_of_leaving above.
    gender           = Column(String(20), nullable=True)
    # India Old Regime senior/super-senior basic-exemption bands
    # (ZP-TAX-IN-2026-27-001 §4.1/§4.2 — "senior-citizen basic exemption
    # is resident-specific") — "RESIDENT" | "NON_RESIDENT" | NULL. NULL
    # (every employee today) resolves identically to NON_RESIDENT: the
    # document's own instruction is to use the ordinary non-senior bands
    # whenever residency isn't affirmatively RESIDENT, never to guess.
    # Combined with date_of_birth (already generically available above)
    # in india.py's _resolve_old_regime_age_category, gated on
    # shared._IN_OLD_REGIME_AGE_BANDS_ENABLED_COUNTRIES.
    tax_residency_status = Column(String(20), nullable=True)
    # UK Directors NIC Phase 2 (ZP-TAX-UK-2026-27-001 §9.2 — "Do not
    # process a director as an ordinary employee solely because the same
    # percentage rates apply"). False/NULL for every employee until
    # entered — no behavior changes for anyone until both are set AND
    # engine/countries/uk.py's calculate() actually branches on them.
    is_director        = Column(Boolean, nullable=True, default=False, server_default="false")
    director_ni_method = Column(String(20), nullable=True)  # "ANNUAL" | "ALTERNATIVE"
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

    # US-specific: Form W-4 filing status ("SINGLE"/"MFJ"/"MFS"/"HOH") and
    # form vintage ("PRE_2020"/"2020_PLUS"). NULL for every non-US employee.
    # A real, engine-read column — distinct from the pre-existing
    # compliance_fields["w4_filing_status"] JSON entry, which the engine
    # never consumed (see employee_validation.py's FIELD_COLUMN_MAP for the
    # mapping that keeps the two in sync going forward).
    w4_filing_status = Column(String(20), nullable=True)
    w4_form_vintage  = Column(String(10), nullable=True)

    # Canada-specific: TD1 federal total claim amount. NULL for every
    # non-CA employee, and for CA employees until explicitly set — the
    # engine falls back to the standard income-tapered BPAF (Phase 2)
    # when unset, matching ZP-TAX-CA-2026-001 §6's "Federal TD1 default:
    # Dynamic BPAF. If no TD1 is on file, follow T4127 default logic."
    # Distinct from the pre-existing compliance_fields["td1_claim_amount"]
    # JSON entry (already collected via the employee form/
    # CAEmployeeValidation) which the engine never consumed until now —
    # same class of dead-plumbing gap already closed for US w4_filing_status
    # and UK tax_code (see employee_validation.py's FIELD_COLUMN_MAP).
    td1_claim_amount = Column(Numeric(12, 2), nullable=True)
    # Canada-specific: provincial/territorial TD1 claim amount — an
    # employee's own filed override of their province's dynamic
    # provincial_bpa, mirroring how td1_claim_amount above already
    # overrides the federal BPAF (ZP-TAX-CA-2026-001 §18: "Provincial/
    # territorial TD1... claim amount/code"). NULL (every employee today)
    # means "no provincial TD1 on file" — falls back to the province's
    # own provincial_bpa exactly as before this column existed. Never
    # applies to a Quebec employee (Quebec has its own TP-1015.3-V claim
    # below, a legally distinct declaration, not this same field reused).
    provincial_td1_claim_amount = Column(Numeric(12, 2), nullable=True)
    # Quebec-specific: TP-1015.3-V personal tax credit amount — Quebec's
    # own employee declaration, legally distinct from federal TD1 per
    # ZP-TAX-CA-2026-001 §18 ("maintain separately from federal TD1").
    # NULL means "no TP-1015.3-V on file" — falls back to the canonical
    # quebec_bpa exactly as before this column existed.
    qc_tp1015_claim_amount = Column(Numeric(12, 2), nullable=True)

    # Canada-specific: TD1X employee-requested additional per-pay-period
    # withholding — additive on top of the statutory calculation, never
    # overwriting it (ZP-TAX-CA-2026-001 §18). NULL means "none requested."
    td1_additional_tax = Column(Numeric(12, 2), nullable=True)
    # Canada-specific: labour-sponsored funds tax credit (LCF, §6) —
    # the employee's declared LSVCC share purchase amount for the year;
    # the federal credit itself is min(this * 15%, $750), computed in
    # engine/countries/canada.py, gated on shared._CA_LSVCC_CREDIT_
    # ENABLED_COUNTRIES. NULL means "no LSVCC purchase declared."
    lsvcc_investment_amount = Column(Numeric(12, 2), nullable=True)
    # Canada-specific: CPT30 CPP/QPP election — "ACTIVE" (default
    # behavior, contribute normally) or "STOPPED" (eligible age-65-69
    # retirement-pension recipient has filed to stop CPP/QPP withholding).
    # NULL/"ACTIVE" changes nothing from today's behavior. Age-based
    # automatic start (18) / stop (70) is now ALSO modeled, separately,
    # via date_of_birth (see engine/countries/canada.py's
    # _is_age_gated_cpp_stopped) — this column still only ever reflects
    # an explicit employee election, never an inferred one.
    cpp_qpp_election_status = Column(String(20), nullable=True)
    cpp_election_effective_date = Column(Date, nullable=True)

    # Canada-specific: full-time remote-work "reasonable attachment" to an
    # employer establishment in a specific province, per
    # ZP-TAX-CA-2026-001 §5 step 4 — an employee working from home whose
    # POE should still resolve to the employer's establishment province,
    # not wherever they happen to be sitting. NULL/False means "no remote
    # agreement on file," same as every employee today; work_state (or
    # the org fallback) resolves POE exactly as it already does.
    # Multi-establishment time-weighting (§5 steps 2-3) is now modeled
    # separately, in the EmployeeEstablishment child table below — an
    # employee with fewer than two active rows there is unaffected by it.
    remote_work_agreement = Column(Boolean, default=False, nullable=False, server_default="false")
    remote_attachment_province = Column(String(10), nullable=True)
    remote_agreement_effective_from = Column(Date, nullable=True)

    # US-specific (but named generically in case another jurisdiction ever
    # needs the same resident/work split): the state the employee is a tax
    # RESIDENT of, as distinct from work_state above (where they physically
    # perform services). NULL means "same as work_state" — the pre-existing,
    # only-ever-had-one-state behavior. Only meaningfully different from
    # work_state for a genuine multi-state commuter (see reciprocity fields
    # below).
    residence_state  = Column(String(100), nullable=True)
    # Whether a reciprocity certificate (e.g. NJ-165) is on file for this
    # employee's resident/work state pair, and when it expires. False/NULL
    # for every employee today — reciprocity suppression only ever applies
    # when this is explicitly set. See reciprocity_resolver.py.
    reciprocity_certificate_on_file   = Column(Boolean, default=False, nullable=False, server_default="false")
    reciprocity_certificate_expiry    = Column(Date, nullable=True)

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
    # UK only: a Postgraduate Loan repaid CONCURRENTLY with an
    # undergraduate plan (ZP-TAX-UK-2026-27-001 §10.2's own worked
    # example: Plan 5 + Postgraduate = two separate deduction lines).
    # Distinct from study_loan_plan=="UK_POSTGRAD" (a standalone
    # Postgraduate-only employee, already fully handled by the existing
    # single-field mechanism) — uk.py's calculate() must never apply both
    # at once for the same employee. Defaults False so no existing
    # employee's calculation changes.
    has_postgrad_loan  = Column(Boolean, nullable=False, default=False, server_default="false")

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


# ── Employee Statutory Profile (effective-dated) ────────────────────────
# PayrollEmployee's own jurisdiction-related columns above (tax_regime,
# tax_code, w4_filing_status, church_tax_liable, ...) are plain mutable
# fields with no history — fine for a value that's read "as of right now,"
# wrong for anything a payroll engine must resolve "as of the payroll date
# being calculated" (e.g. a German employee's tax class changing mid-year
# must not retroactively change an already-run March payslip). This table
# is that second axis of versioning: one row per (employee, effective
# period), never updated in place — a change is always a new row, closing
# the previous one's effective_to. Deliberately NOT reusing JurisdictionPack
# (that table describes a JURISDICTION's rules; this describes ONE
# EMPLOYEE's own statutory facts within a jurisdiction) and deliberately
# NOT storing anything the payroll engine calculates (tax owed, contribution
# amounts, ...) — see PHASE_2_EMPLOYEE_STATUTORY_PROFILE.md §7.
#
# Columns are grouped generic-first, then per-jurisdiction (currently only
# Germany, prefixed `de_` — same additive-nullable-column convention
# PayrollEmployee already uses for tax_code/ni_category (UK) and
# w4_filing_status (US): a field only a Germany-aware caller ever reads,
# NULL and inert for every other country's employees).
class EmployeeStatutoryProfile(Base):
    """One effective-dated version of an employee's statutory facts.

    Resolution: given (employee_id, payroll_date), the applicable row is
    the one whose [effective_from, effective_to] window contains
    payroll_date (effective_to IS NULL meaning "still current") — see
    service.resolve_employee_statutory_profile(). Overlap between two rows
    for the same employee is rejected at write time (service layer, same
    pattern JurisdictionPack's Active-pack overlap guard already uses —
    see service._validate_statutory_profile_period), not enforced via a
    DB-level exclusion constraint, for consistency with how this module
    already handles this class of problem and because the SQLite dev
    fallback (see database.py) has no equivalent to Postgres EXCLUDE/GIST
    constraints. The one thing enforced at the DB level (see __table_args__
    below) is that at most one row per employee may be open-ended
    (effective_to IS NULL) at a time — the cheap, common-case guard against
    an accidental duplicate "current" row.
    """
    __tablename__ = "payroll_employee_statutory_profiles"

    id              = Column(Integer, primary_key=True, index=True)
    employee_id     = Column(Integer, ForeignKey("payroll_employees.id"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    # Which jurisdiction's rules this row's attributes are interpreted
    # under — same 2-letter convention as PayrollEmployee.country_code.
    # Not necessarily identical to the employee's CURRENT country_code:
    # a historical row keeps the jurisdiction that was actually in force
    # for that period, even if the employee later transferred countries.
    country_code    = Column(String(2), nullable=False)

    effective_from  = Column(Date, nullable=False)
    effective_to    = Column(Date, nullable=True)   # NULL = open-ended / current

    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), onupdate=func.now())
    created_by_id   = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Why this version was recorded (e.g. "ELStAM change list 2026-07",
    # "Employee reported new child") — mirrors TaxConfigurationAudit.reason's
    # role, kept on the row itself (not only the audit log) since it's part
    # of the statutory record's own evidence, not just a change-log entry.
    reason          = Column(Text, nullable=True)

    # ── Germany (DE) statutory attributes ────────────────────────────────
    # Every field below maps to a named Germany 2026 spec requirement
    # (ZP-TAX-DE-2026-001) — see PHASE_2_EMPLOYEE_STATUTORY_PROFILE.md §5
    # for the field-by-field citation. NULL for every non-German employee
    # and for a German employee before this data has been captured; no
    # calculation reads these yet (Lohnsteuer/PAP/GKV/PV/RV/ALV/Minijob/
    # Midijob remain out of scope for this phase).
    de_tax_class                     = Column(String(4), nullable=True)   # STKL: I|II|III|IV|V|VI (spec §6)
    de_factor                        = Column(Numeric(6, 4), nullable=True)  # AF/F, class IV only (spec §5, §6)
    de_church_tax_liable             = Column(Boolean, nullable=True)     # spec §8
    de_church_tax_land               = Column(String(6), nullable=True)   # e.g. "DE-BY" (spec §3, §8)
    # Phase 8AM — required to correctly apply a documented sub-Land
    # church-tax exception (spec §8's own "preserve documented
    # denomination/location exceptions such as the Roman Catholic
    # treatment in Bad Wimpfen" instruction, which names BOTH a
    # denomination and a location as the deciding factors — neither of
    # which the pre-existing de_church_tax_liable/de_church_tax_land
    # fields alone can represent). Both nullable/free-text: NULL means
    # "not recorded" for every row created before this phase (identical
    # to how de_main_employment was introduced), never an assumption.
    # ROMAN_CATHOLIC|EVANGELICAL|OTHER — no enumerated value set is
    # defined in the supplied documentation beyond the one denomination
    # the Bad Wimpfen exception itself names, so this is free text, not
    # an invented exhaustive enum.
    de_church_tax_denomination       = Column(String(30), nullable=True)
    # The postal code of the employee's church-tax-relevant residence —
    # the exact, deterministic key the verified Bad Wimpfen exception
    # (PLZ 74206) is keyed by. Deliberately a NEW, church-tax-specific
    # field rather than reusing PayrollEmployee.work_locality (a
    # generic, unvalidated free-text field used for other purposes,
    # e.g. locality-based US tax resolution — conflating the two would
    # risk an unrelated locality entry accidentally matching or missing
    # a church-tax exception).
    de_church_tax_municipality_postal_code = Column(String(10), nullable=True)
    de_child_count                   = Column(Integer, nullable=True)     # qualifying children, PVA (spec §10)
    de_childless                     = Column(Boolean, nullable=True)     # PVZ care-insurance surcharge flag (spec §10)
    de_saxony                        = Column(Boolean, nullable=True)     # PVS (spec §10)
    de_health_insurance_status       = Column(String(10), nullable=True)  # PUBLIC|PRIVATE, PKV marker (spec §5)
    # Membership identifier only — NOT a rate. The Krankenkasse's own
    # supplementary rate belongs to the (not-yet-built, see Phase 1 §20)
    # Health Fund Registry; this column just records which fund the
    # employee belongs to during this period. A plain string for now
    # (no registry table exists yet to foreign-key against) — see
    # PHASE_2_EMPLOYEE_STATUTORY_PROFILE.md §14 "Remaining Gaps".
    de_health_fund_code              = Column(String(50), nullable=True)
    # Phase 8W — employer's selected U1 tariff identifier at this employee's
    # health fund (e.g. "U1_50", "U1_70", "U1_80"). Resolved against the
    # GermanyHealthFundU1Tariff child table for the employee's fund + pay
    # period. NULL = no U1 tariff selected (calculation engine treats as
    # NOT_CONFIGURED, same as the pre-Phase-8W u1_rate_pct=None behavior).
    # This is an EMPLOYER-level selection recorded per-employee for
    # resolution convenience — the same tariff applies to all employees at
    # the same employer+fund combination.
    de_u1_tariff_id                 = Column(String(50), nullable=True)
    de_pension_insurance_exempt      = Column(Boolean, nullable=True)     # KRV marker (spec §5)
    de_unemployment_insurance_exempt = Column(Boolean, nullable=True)     # ALV precaution marker (spec §5)
    # REGULAR|MINIJOB|MIDIJOB — selects the calculation path a future
    # Germany engine phase would dispatch on (spec §12, §13, DE-D07).
    de_employment_classification     = Column(String(10), nullable=True)
    de_elstam_source                 = Column(String(20), nullable=True)  # ELSTAM|FALLBACK_CERTIFICATE (spec §6)
    de_elstam_fallback_reason        = Column(Text, nullable=True)        # required evidence when source=FALLBACK_CERTIFICATE (spec §6)
    # True only when this employee is employed "zu ihrer Berufsausbildung"
    # (an Ausbildungsvertrag, Praktikum zur Berufsausbildung, or duales
    # Studium) — §20 Abs. 2a Satz 9 SGB IV explicitly excludes this group
    # from the Übergangsbereich (Midijob) regardless of earnings,
    # confirmed by BSG ruling 15.07.2009 (Phase 8L). NOT a general
    # "part-time"/"low-pay" flag — its only statutory effect is this one
    # exclusion (see validate_classification_against_vocational_training
    # in germany_pap/core.py).
    de_vocational_trainee            = Column(Boolean, nullable=True)

    # ── Phase 8N: ELStAM / employee-withholding-state completion ────────
    # Every field below maps to a named PAP input the spec's §5 table
    # lists but Phase 7 left hardcoded to 0 (see PapInputContract's own
    # field_sources() docstring, now updated) — added only once a real,
    # nullable, backward-compatible column exists to source them from.
    # NULL means "not captured" (identical to the pre-8N behavior of
    # always feeding the PAP a zero for these), never a fabricated value.

    # ZKF OVERRIDE — spec §5/§6. Phase 8K disclosed that de_child_count
    # doubles as both the PV child-category source AND the PAP ZKF source
    # for the ordinary case (a plain integer count, no split-custody
    # half-allowance) — a correct simplification for that case, NOT a
    # universal equivalence. This column is the escape hatch for the
    # documented edge case Phase 8K left out of scope: a genuinely
    # split-custody employee's ZKF (which can be a half-integer, e.g. 0.5
    # per child) is recorded HERE, distinct from de_child_count (which
    # keeps driving the PV branch, per §10, untouched). NULL (the default,
    # identical to every existing row) means "ZKF is not a special case —
    # keep deriving it from de_child_count exactly as before."
    de_zkf_override                  = Column(Numeric(4, 2), nullable=True)

    # ELStAM allowance / add-back amounts — spec §5's JFREIB/LZZFREIB/
    # JHINZU/LZZHINZU PAP inputs, §6's "Allowance / add-back" ELStAM
    # attribute row. Stored as euros (matching every other monetary column
    # on this table), converted to cents only at the PAP-input boundary
    # (build_pap_input), mirroring how gross_monthly is handled. Spec
    # states no derivation relationship between the annual (J-) and
    # period (LZZ-) figures — both are independently ELStAM-supplied, so
    # neither is computed from the other here.
    de_jfreib                        = Column(Numeric(10, 2), nullable=True)   # JFREIB — annual allowance
    de_lzzfreib                      = Column(Numeric(10, 2), nullable=True)   # LZZFREIB — period allowance
    de_jhinzu                        = Column(Numeric(10, 2), nullable=True)   # JHINZU — annual add-back
    de_lzzhinzu                      = Column(Numeric(10, 2), nullable=True)   # LZZHINZU — period add-back

    # 2026 ELStAM private health/care insurance values — spec §6 "2026
    # ELStAM CHANGE": "From January 1, 2026 the ELStAM dataset includes
    # private health and private mandatory long-term-care contribution
    # information." PKPV/PKPVAGZ are monthly amounts (spec §5's own PAP
    # input table: "monthly value" for both). Never used to derive a GKV/PV
    # contribution — these are PAP-side tax allowances for an employee's
    # own private premium, not a statutory GKV/PV deduction this engine
    # computes (see calculate_gkv's PRIVATE-status docstring for the
    # analogous, already-established distinction).
    de_pkpv                          = Column(Numeric(10, 2), nullable=True)   # PKPV — private basic health/care premium (monthly)
    de_pkpvagz                       = Column(Numeric(10, 2), nullable=True)   # PKPVAGZ — tax-free employer subsidy (monthly)

    # Main vs secondary employment — spec §6: "Enrollment request must
    # identify first/main or additional employment." True = main/first
    # employment; False = secondary/additional (tax class VI territory,
    # per §6's own tax-class table); NULL = not recorded (identical to
    # every existing row's prior behavior — this attribute did not exist
    # before, so no assumption is retrofitted onto historical rows). Not a
    # PAP input field itself (the PAP input contract has no dedicated
    # "main/secondary" field — that relationship is already fully encoded
    # via tax class, confirmed Phase 8K) — this column exists for the
    # ELStAM enrollment/employment-relationship record-keeping and audit
    # trail the spec requires, and for the advisory tax-class-VI
    # consistency check in germany_pap/core.py.
    de_main_employment                = Column(Boolean, nullable=True)

    # ELStAM structured-import provenance — spec §7 (this phase's import
    # boundary). Meaningful only when de_elstam_source == "ELSTAM"; NULL
    # for every row entered before this phase and for FALLBACK_CERTIFICATE
    # rows (which cite de_elstam_fallback_reason instead). Distinct from
    # GermanyElstamImportAttempt's own id (below) — that table logs every
    # ATTEMPT, including rejected ones that never reach this table at all;
    # these two columns are just this row's own denormalized provenance,
    # for a quick read without a join.
    de_elstam_schema_version          = Column(String(30), nullable=True)
    de_elstam_import_reference        = Column(String(100), nullable=True)

    # ── Phase 8AB: Overtime/shift-premium Grundlohn source (spec-adjacent —
    # §3b EStG / §1 SvEV, Phase 8Z; ARCHITECTURE_D, Phase 8AA) ────────────
    # The approved product decision (Phase 8AB): Zoiko uses an EXPLICIT,
    # per-employee, effective-dated hourly Grundlohn — never derived. This
    # column is deliberately the ONLY thing this phase adds: no overtime
    # work-record table, no premium-category registry, no calculation. NULL
    # (the default, identical to every other Germany field's "not yet
    # captured" convention on this table) means the employee's Grundlohn is
    # simply not on file yet — a future overtime-calculation phase (8AC+)
    # must treat that as NOT_CONFIGURED, never silently derive one from
    # ctc/basic/hra/pay_frequency/standard hours or any other formula (the
    # Phase 8AA report's own explicit prohibition — no /160, /173, /30, no
    # 8-hours/day assumption). Numeric(10,2) matches every other monetary
    # column on this table (de_jfreib et al.) — no new precision convention
    # invented. This column is NOT yet read by any calculation code
    # anywhere (confirmed by this phase's own regression tests) — it only
    # establishes the source of truth for a later phase to consume.
    de_grundlohn_hourly               = Column(Numeric(10, 2), nullable=True)

    __table_args__ = (
        Index("ix_statutory_profile_employee_period", "employee_id", "effective_from"),
        Index("ix_statutory_profile_org", "organization_id"),
        Index(
            "uq_statutory_profile_one_open_per_employee",
            "employee_id",
            unique=True,
            postgresql_where=text("effective_to IS NULL"),
            sqlite_where=text("effective_to IS NULL"),
        ),
    )

    def __repr__(self):
        return (
            f"<EmployeeStatutoryProfile id={self.id} employee_id={self.employee_id} "
            f"country={self.country_code} from={self.effective_from} to={self.effective_to}>"
        )


# ── Germany: ELStAM change-list batch (Phase 8N, spec §6 "Change lists") ──
# Records that a monthly ELStAM change list was RECEIVED for this
# organization — metadata only. Does NOT poll ELSTER (no live connector
# exists anywhere in this codebase — see engine/germany_pap/elstam.py) and
# does NOT auto-apply attribute changes to any employee (this phase's own
# explicit "do not fabricate change-list payloads" instruction) — an
# individual employee's actual attribute change is recorded separately via
# GermanyElstamImportAttempt (below), which may optionally cite this
# batch's id once someone has manually validated and entered the real
# content of the change list.
class GermanyElstamChangeListBatch(Base):
    """One received ELStAM change-list batch record."""
    __tablename__ = "payroll_germany_elstam_change_list_batches"

    id              = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    batch_reference    = Column(String(100), nullable=False)
    # How this batch entered the system — spec gives no enumerated set, so
    # free text (matching GermanyHealthFund.member_applicability's own
    # "concept named, no vocabulary given" treatment), defaulting to the
    # only value this phase's own architecture actually produces.
    source             = Column(String(50), nullable=False, default="MANUAL_UPLOAD", server_default="MANUAL_UPLOAD")
    received_at        = Column(DateTime(timezone=True), nullable=False)
    effective_date      = Column(Date, nullable=False)
    # "Employee/authorization scope" (spec §8) — free text, same reasoning
    # as `source` above; no employee-list fan-out is modeled (would risk
    # fabricating which employees/attributes actually changed).
    scope_description   = Column(Text, nullable=True)

    # RECEIVED | VALIDATED | APPLIED | REJECTED — spec §8's own named
    # states ("processing status", "validation result").
    processing_status  = Column(String(20), nullable=False, default="RECEIVED", server_default="RECEIVED")
    validation_result   = Column(JSON, nullable=True)

    created_by_id       = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    updated_at          = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return (
            f"<GermanyElstamChangeListBatch id={self.id} ref={self.batch_reference!r} "
            f"status={self.processing_status}>"
        )


# ── Germany: ELStAM structured-import audit log (Phase 8N, spec §7) ──────
# Audits EVERY attempt to import a structured ELStAM payload for one
# employee — successful (APPLIED) or rejected (REJECTED). Necessary
# because a rejected attempt, by construction, never creates an
# EmployeeStatutoryProfile row at all (validation runs before insert) — so
# without this table, a rejected import would leave no trace whatsoever,
# and the spec's own "validation errors"/"audit event" requirements (§7)
# would be unmet. `payload` is always caller-supplied structured data,
# shaped like EmployeeStatutoryProfileCreate — nothing in this table (or
# anywhere this phase touches) calls ELSTER/BZSt.
class GermanyElstamImportAttempt(Base):
    """One attempt (successful or rejected) to import a structured ELStAM
    payload for one employee."""
    __tablename__ = "payroll_germany_elstam_import_attempts"

    id              = Column(Integer, primary_key=True, index=True)
    employee_id     = Column(Integer, ForeignKey("payroll_employees.id"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    schema_version      = Column(String(30), nullable=False)
    import_reference     = Column(String(100), nullable=True)
    change_list_batch_id = Column(
        Integer, ForeignKey("payroll_germany_elstam_change_list_batches.id"), nullable=True, index=True,
    )

    # The submitted payload, verbatim (JSON) — never a raw Steuer-ID (this
    # table only ever receives the same field set EmployeeStatutoryProfileCreate
    # already accepts, which has no Steuer-ID column to begin with).
    payload             = Column(JSON, nullable=False)

    # APPLIED | REJECTED — deliberately binary (unlike the change-list
    # batch's 4-state lifecycle above): an import attempt either produced a
    # new EmployeeStatutoryProfile version or it did not; there is no
    # intermediate DRAFT/REVIEW state for a single-employee import.
    validation_status              = Column(String(20), nullable=False)
    validation_errors               = Column(JSON, nullable=True)
    applied_statutory_profile_id    = Column(
        Integer, ForeignKey("payroll_employee_statutory_profiles.id"), nullable=True,
    )

    imported_at     = Column(DateTime(timezone=True), server_default=func.now())
    created_by_id   = Column(Integer, ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        Index("ix_elstam_import_attempt_employee", "employee_id", "imported_at"),
    )

    def __repr__(self):
        return (
            f"<GermanyElstamImportAttempt id={self.id} employee_id={self.employee_id} "
            f"status={self.validation_status}>"
        )


class EmployeeEstablishment(Base):
    """ZP-TAX-CA-2026-001 §5 steps 2-3 — true multi-establishment POE: an
    employee who physically reports to MORE THAN ONE employer
    establishment resolves to whichever they spend the most time at,
    tie-broken by whichever they most recently worked. This is the
    "materially larger feature left for a later decision" flagged in
    PayrollEmployee.remote_work_agreement's own docstring, now built.

    Deliberately modeled as a STANDING recurring time-allocation pattern
    (e.g. "60% of working time at ON, 40% at QC"), not a per-pay-period
    timesheet — this codebase has no attendance/timesheet system for any
    country, and building one is a separate, materially larger
    initiative. Same declarative-fact shape as TD1/remote_work_agreement:
    entered once, read on every payslip until changed.

    An employee with FEWER than two active rows here is completely
    unaffected — POE resolution falls through to the existing
    work_state/remote_attachment/payroll-fallback chain exactly as
    before this table existed (see service.py's
    _resolve_ca_multi_establishment_poe/_resolve_ca_poe_with_source).
    Purely additive: no existing employee has any row here."""
    __tablename__ = "payroll_employee_establishments"

    id                   = Column(Integer, primary_key=True, index=True)
    employee_id          = Column(Integer, ForeignKey("payroll_employees.id"), nullable=False, index=True)
    province             = Column(String(10), nullable=False)
    # % of working time spent at this establishment (0-100). Only the
    # RELATIVE ordering across one employee's own rows matters for
    # resolution — rows for one employee need not sum to exactly 100.
    time_allocation_pct  = Column(Numeric(5, 2), nullable=False)
    # Tie-break input per §5 step 3's "most recently worked" — NULL is
    # treated as never-worked (loses every tie against a real date).
    last_worked_date     = Column(Date, nullable=True)
    is_active            = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at           = Column(DateTime(timezone=True), server_default=func.now())
    updated_at           = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<EmployeeEstablishment emp={self.employee_id} province={self.province} pct={self.time_allocation_pct}>"


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
    # Same immutability contract as tax_rule_snapshot above, for YTD-based
    # caps (Canada CPP/CPP2/EI today) instead of rate/slab values: freezes
    # the before/after cumulative figures this payslip actually consumed
    # per component, e.g. {"cpp": {"ytd_before": "71100.00", "ytd_after":
    # "79100.00"}, "cpp2": {...}, "ei": {...}, "cpp_basic_exemption": {...}}.
    # NULL for every payslip generated before this column existed, and for
    # every country/employee where YTD accumulation isn't wired/enabled —
    # see engine/countries/shared.py's _YTD_ACCUMULATOR_ENABLED_COUNTRIES.
    ytd_snapshot        = Column(JSON, nullable=True)
    # Canada: the province-of-employment result AND the machine-readable
    # reason code that produced it (ZP-TAX-CA-2026-001 CA-D03/AC-07 —
    # "persist resolver inputs... reason code"), e.g. {"poe_result": "ON",
    # "poe_reason": "PHYSICAL_SINGLE"}. Previously computed by
    # _resolve_ca_poe_with_source and immediately discarded (see
    # _resolve_country_aware_state) — never persisted anywhere. NULL for
    # every non-CA payslip and for CA payslips generated before this
    # column existed.
    poe_snapshot        = Column(JSON, nullable=True)

    # Germany (Phase 7, ZP-TAX-DE-2026-001) — the analogous freeze for the
    # Germany statutory calculation path, which does not go through
    # JurisdictionPack/tax_rule_snapshot above (Germany has no Active
    # canonical pack — see docs/PHASE_5_..._REPORT.md §3). `employee_statutory_profile_id`
    # points at the exact EmployeeStatutoryProfile version (Phase 2) that
    # was in effect when this payslip was generated — a future edit/new
    # version of that profile MUST NOT change this payslip's figures, the
    # same immutability guarantee tax_policy_pack_id already gives every
    # other country. `germany_calculation_snapshot` is the actual resolved
    # values (PAP version/hash, health-fund rate, ceiling ids, PV
    # configuration id, per-branch RV/ALV/GKV/PV amounts, calculation
    # status/trace) — not just a set of foreign keys, so the payslip
    # remains reproducible even if every one of those rows is later
    # superseded. NULL for every non-German payslip and for every German
    # payslip generated before this column existed (none exist yet — see
    # Phase 7 report §18, the registries were empty in every environment
    # this phase touched).
    employee_statutory_profile_id = Column(Integer, ForeignKey("payroll_employee_statutory_profiles.id"), nullable=True, index=True)
    germany_calculation_snapshot  = Column(JSON, nullable=True)

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
    # India Labour Welfare Fund Phase 3b (ZP-TAX-IN-2026-27-001 §15) — a
    # genuinely SEPARATE state-specific annual contribution, not a
    # breakdown of anything above. Zero on every payslip until Tax Ops
    # configures BOTH the amount and the deduction month for that state —
    # no hardcoded fallback (see india.py's calculate()).
    employee_lwf      = Column(Numeric(12, 2), default=0, server_default="0")
    employer_lwf       = Column(Numeric(12, 2), default=0, server_default="0")
    tds               = Column(Numeric(12, 2), default=0)   # income tax withheld — INCLUDES surcharge/cess below, not additional to them
    # India: monthly breakdown of what's already folded into `tds` above —
    # informational only, never summed again into total_deductions.
    surcharge         = Column(Numeric(12, 2), default=0, server_default="0")
    cess              = Column(Numeric(12, 2), default=0, server_default="0")
    # US-specific
    social_security   = Column(Numeric(12, 2), default=0)
    medicare          = Column(Numeric(12, 2), default=0)
    # US: federal/state/local income tax, broken out separately. Previously
    # engine/countries/us.py folded state (and now local) tax straight into
    # `tds` with no distinct field — the payslip/Payroll Register literally
    # could not show a US employee their state or local withholding
    # separately, and one report even read a borrowed India field
    # (professional_tax) for "State Tax," which US never populated, always
    # showing $0 regardless of what was actually withheld. `tds` is kept,
    # computed as the sum of these three, for backward compatibility with
    # any existing code/report that still sums it directly.
    federal_income_tax = Column(Numeric(12, 2), default=0, server_default="0")
    state_income_tax   = Column(Numeric(12, 2), default=0, server_default="0")
    local_tax           = Column(Numeric(12, 2), default=0, server_default="0")
    # US: state-level statutory payroll program (California SDI first) —
    # its own line, distinct from state_income_tax, since it's a separate
    # statutory deduction category, not part of income-tax withholding.
    state_disability_insurance = Column(Numeric(12, 2), default=0, server_default="0")
    # US: every OTHER state-level statutory payroll program beyond SDI
    # (Paid Family Leave/Paid Leave/TDI/Universal Paid Leave/WA Cares/
    # NJ's worker UI+DI+workforce-dev+FLI/etc., ZP-TAX-US-2026-001 §5) —
    # one combined employee-side total, computed from however many
    # programs are configured for the employee's state (us.py's own
    # loop). Deliberately ONE field for now rather than one column per
    # program, same "field reuse over new columns, graduate later if a
    # real need for per-component tracking arises" convention this
    # engine already uses for `tds` (see service.py's own comment on it)
    # — each program's own name/rate/amount is still individually
    # auditable via the calculation trace, just not as a separate
    # payslip line yet.
    state_program_deductions = Column(Numeric(12, 2), default=0, server_default="0")
    # UK-specific
    ni_employee       = Column(Numeric(12, 2), default=0)
    # UK/Australia: government study-loan repayment (Student/Postgraduate
    # Loan in the UK, HELP/HECS in Australia) — one shared line, same
    # reasoning as PayrollEmployee.study_loan_plan/study_loan_balance.
    study_loan_deduction = Column(Numeric(12, 2), default=0, server_default="0")
    # UK only: a CONCURRENT Postgraduate Loan deduction, separate from
    # study_loan_deduction above whenever an employee has BOTH an
    # undergraduate plan and PayrollEmployee.has_postgrad_loan set —
    # matches ZP-TAX-UK-2026-27-001 §10.2's own worked example (two
    # separate deduction lines, not one combined figure). Always 0 for a
    # standalone study_loan_plan=="UK_POSTGRAD" employee (that case stays
    # fully represented by study_loan_deduction alone).
    postgrad_loan_deduction = Column(Numeric(12, 2), default=0, server_default="0")
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
    # Canada: CPP/QPP first-layer BASE (4.95%) vs. FIRST-ADDITIONAL
    # (1.00%) breakdown (AC-11) — informational only, like cpp2 above;
    # NOT summed into total_deductions (already folded into
    # social_security). Zero until _CA_CPP_COMPONENT_SPLIT_ENABLED_
    # COUNTRIES is flipped AND cpp_base/cpp_first_additional rows exist.
    cpp_base_amount              = Column(Numeric(12, 2), default=0, server_default="0")
    cpp_first_additional_amount  = Column(Numeric(12, 2), default=0, server_default="0")
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
    # US: State Unemployment Insurance — tenant/employer-specific, resolved
    # from EmployerTaxProfile (agency-assigned rate), NOT from a generic
    # ContributionRate override. Zero until an org has a configured profile.
    employer_sui       = Column(Numeric(12, 2), default=0, server_default="0")
    # US: employer-side counterpart to state_program_deductions above (e.g.
    # DC's Universal Paid Leave is entirely employer-funded). Same
    # one-combined-field convention.
    employer_state_program_contributions = Column(Numeric(12, 2), default=0, server_default="0")
    # Canada: employer-side CPP2/QPP2 — previously entirely unmodeled (only
    # the employee-side cpp2 column above existed); the employer's own
    # second-tier contribution is legally distinct and must be tracked
    # separately, same reasoning as employer_social_security vs.
    # social_security above.
    employer_cpp2      = Column(Numeric(12, 2), default=0, server_default="0")
    # Canada: employer-side counterpart to cpp_base_amount/
    # cpp_first_additional_amount above — same informational contract.
    employer_cpp_base             = Column(Numeric(12, 2), default=0, server_default="0")
    employer_cpp_first_additional = Column(Numeric(12, 2), default=0, server_default="0")
    # Canada: Ontario Employer Health Tax — banded on the ORG's aggregate
    # Ontario remuneration across every employee, not this employee's own
    # pay (ZP-TAX-CA-2026-001 §15/§16). Zero for every non-Ontario payslip
    # and for every payslip until the org-level accumulator rollout
    # switch is enabled — see engine/countries/shared.py's
    # _ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.
    employer_eht       = Column(Numeric(12, 2), default=0, server_default="0")
    # UK: Apprenticeship Levy — same org-level-accumulator-banded contract
    # as employer_eht above (ZP-TAX-UK-2026-27-001 §14).
    employer_apprenticeship_levy = Column(Numeric(12, 2), default=0, server_default="0")
    # Canada: BC EHT, Manitoba HE Levy, NL HAPSET — same org-level-
    # accumulator-banded contract as employer_eht above, one column per
    # levy since each is legally distinct and jurisdiction-exclusive
    # (an employee has at most one of ON/BC/MB/NL work_state).
    employer_bc_eht     = Column(Numeric(12, 2), default=0, server_default="0")
    employer_mb_he_levy = Column(Numeric(12, 2), default=0, server_default="0")
    employer_nl_hapset  = Column(Numeric(12, 2), default=0, server_default="0")
    # Quebec: Health Services Fund (org-level-accumulator-banded sliding
    # rate) and labour standards contribution (per-employee capped, no
    # accumulator) — see engine/countries/canada.py's module docstring.
    employer_qc_hsf               = Column(Numeric(12, 2), default=0, server_default="0")
    employer_qc_labour_standards  = Column(Numeric(12, 2), default=0, server_default="0")
    # India: EPS diversion + residual — purely-informational breakdown of
    # employer_pf above (ZP-TAX-IN-2026-27-001 §9.1/§9.3); employer_eps +
    # employer_pf_residual == employer_pf always, never additional to it.
    employer_eps           = Column(Numeric(12, 2), default=0, server_default="0")
    employer_pf_residual   = Column(Numeric(12, 2), default=0, server_default="0")
    # India: EDLI — a genuinely SEPARATE employer-only statutory liability
    # (§9.1), additional to employer_pf, not a breakdown of it. Zero until
    # Tax Ops configures "edli_rate"/"edli_wage_ceiling" via the Super
    # Admin UI — no hardcoded fallback.
    employer_edli           = Column(Numeric(12, 2), default=0, server_default="0")
    # India: employer NPS contribution deduction (§3.2 — "14% path
    # available under new regime for qualifying employer contribution").
    # A genuinely separate employer-only cost, like EDLI, computed as
    # nps_employer_pct of Basic — no hardcoded fallback, resolves to 0
    # until Tax Ops configures "nps_employer_pct" via the Super Admin UI.
    # Also excluded from taxable salary under the New Regime only — see
    # india.py's _calculate_annual_tax_in.
    employer_nps            = Column(Numeric(12, 2), default=0, server_default="0")

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


# ── Germany: Overtime/Shift-Premium Work Record (Phase 8AC) ──────────────
# The "work performed" FACT layer of Phase 8AA's ARCHITECTURE_D hybrid
# design (docs/PHASE_8AA_..._DATA_MODEL.md §11) — deliberately narrow: it
# records ONLY what was actually worked (date/time/hours), never a
# calculated premium, tax, or social-insurance amount. The four-dimension
# statutory OUTPUT (GermanyOvertimePremiumComponent) and the statutory RATE
# registries (GermanyOvertimePremiumCategory/GermanyOvertimeGrundlohnCap)
# are explicitly NOT built by this phase — see the Phase 8AC report for the
# full rationale. This table is never read by engine/countries/germany.py
# or any other calculation code; ctx.overtime remains untouched for
# Germany.
#
# `source_attendance_id` is a nullable, NON-OWNING reference to
# PayrollAttendanceRecord — attendance stays the system of record for "was
# the employee present," this table becomes the system of record for "was
# any of that time a qualifying overtime/premium window." No field is
# duplicated from attendance (this table derives its own
# start_datetime/end_datetime rather than copying check_in/check_out).
#
# `entry_source` distinguishes ATTENDANCE_DERIVED from MANUAL rows.
# Phase 8AA/8AB both explicitly left the PRECEDENCE between the two
# unresolved as a genuine PRODUCT_DECISION — this model deliberately does
# NOT enforce or infer a winner when both exist for the same employee/date;
# it only guarantees at most one work record per attendance day (the
# `source_attendance_id` uniqueness below), never silently deduplicating or
# preferring one entry_source over another.
class GermanyOvertimeWorkRecord(Base):
    """One raw fact: an employee worked from start_datetime to
    end_datetime on work_date. Carries no premium/tax/SI fields — those
    belong to a future calculation phase's own output table."""
    __tablename__ = "payroll_germany_overtime_work_records"

    id                    = Column(Integer, primary_key=True, index=True)
    organization_id       = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    employee_id           = Column(Integer, ForeignKey("payroll_employees.id"), nullable=False, index=True)

    # Nullable, non-owning — NULL means this record was entered manually
    # with no corresponding attendance day (entry_source == "MANUAL" in
    # that case, though the two are validated together at the service
    # layer, not via a DB constraint).
    source_attendance_id = Column(Integer, ForeignKey("payroll_attendance_records.id"), nullable=True)

    work_date             = Column(Date, nullable=False, index=True)
    # Real DateTime (not separate date+time strings) so an overnight shift
    # crossing midnight (e.g. 22:00-02:00) is unambiguous — end_datetime
    # simply falls on the calendar day after work_date. No timezone/DST
    # classification logic exists yet (Phase 8AA §14 — deferred to the
    # future qualifying-time-window engine, not this phase).
    start_datetime        = Column(DateTime(timezone=True), nullable=False)
    end_datetime           = Column(DateTime(timezone=True), nullable=False)
    hours                  = Column(Numeric(5, 2), nullable=False)

    # ATTENDANCE_DERIVED | MANUAL — see the class-level docstring above.
    entry_source           = Column(String(20), nullable=False)
    # PENDING | APPROVED | REJECTED — an HR/manager sign-off that the hours
    # were legitimately worked. Deliberately a SEPARATE concept from
    # PolicyOvertimeRule (the pre-existing per-org approval-WORKFLOW gate,
    # untouched by this phase) and from any future statutory classification
    # — Phase 8AA §25's own explicit separation of "HR approval" from
    # "statutory taxability."
    hr_approval_status     = Column(String(20), nullable=False, default="PENDING", server_default="PENDING")

    # Phase 8AQ — NULL (no ambiguity) | "AMBIGUOUS_OVERLAP". Set
    # automatically (never chosen by the operator) whenever this record's
    # [start_datetime, end_datetime) interval overlaps another NON-
    # REJECTED work record for the SAME employee, regardless of either
    # record's entry_source (manual vs attendance-derived, or two of the
    # same source — the ambiguity is about physical time overlap, not
    # about which source "should" win, a precedence question this
    # project has repeatedly and deliberately declined to invent — see
    # Phase 8AA §15/§32.2). A record in this state fails closed at
    # classification (service.classify_and_list_germany_overtime_time_segments)
    # — it can never reach wage-tax/SI calculation or payslip attachment
    # while ambiguous. Recomputed (never hand-edited) by
    # service._recompute_germany_overtime_overlap_status whenever a
    # record is created or an approval status changes (rejecting one
    # side of an overlap can resolve it for the other).
    overlap_status          = Column(String(30), nullable=True)

    created_by_id           = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at               = Column(DateTime(timezone=True), server_default=func.now())
    updated_at               = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_germany_overtime_work_record_org_emp_date", "organization_id", "employee_id", "work_date"),
        # At most one work record per attendance day — the duplicate-
        # prevention guard Phase 8AA §14 requires. Does NOT prevent two
        # MANUAL (source_attendance_id IS NULL) records for the same
        # employee/date — deliberately, since deduplicating those requires
        # the precedence decision this phase does not make.
        UniqueConstraint("source_attendance_id", name="uq_germany_overtime_work_record_source_attendance"),
    )

    def __repr__(self):
        return (
            f"<GermanyOvertimeWorkRecord id={self.id} employee_id={self.employee_id} "
            f"work_date={self.work_date} entry_source={self.entry_source}>"
        )


# ── Germany: Overtime Time-Window Classification (Phase 8AE) ────────────
# CLASSIFICATION result only — see engine/germany_overtime_classifier.py.
# Every segment is a statutory/calendar FACT (which §3b EStG category a
# slice of physical worked time qualifies for), never a monetary amount.
# No premium_amount/grundlohn_used/tax_free_amount/si_*_amount column
# exists here, deliberately — those belong to a future
# GermanyOvertimePremiumComponent (explicitly NOT built this phase).
class GermanyOvertimeTimeSegment(Base):
    """One non-overlapping (per category) physical time slice of a
    GermanyOvertimeWorkRecord, classified against one §3b EStG premium
    category. A single physical time range can produce MORE THAN ONE
    segment row when multiple categories genuinely apply concurrently
    (e.g. Sunday night — one SUNDAY segment and one NIGHT_STANDARD segment,
    both spanning the identical [segment_start, segment_end) — this is
    legal concurrence, not double-counted work: see the classifier
    module's own docstring for the exact non-overlap invariant this
    implies (no two segments of the SAME category may overlap; segments
    of DIFFERENT categories may legitimately share the same time range)."""
    __tablename__ = "payroll_germany_overtime_time_segments"

    id                    = Column(Integer, primary_key=True, index=True)
    work_record_id        = Column(Integer, ForeignKey("payroll_germany_overtime_work_records.id"), nullable=False, index=True)

    segment_start          = Column(DateTime(timezone=True), nullable=False)
    segment_end             = Column(DateTime(timezone=True), nullable=False)
    hours                   = Column(Numeric(6, 4), nullable=False)

    # NIGHT_STANDARD | NIGHT_EXTENDED | SUNDAY | HOLIDAY_STANDARD |
    # HOLIDAY_SPECIAL — the exact Phase 8AD vocabulary, no 6th invented.
    # Always set — this is a statutory/calendar determination independent
    # of whether a GermanyOvertimePremiumCategory row happens to be
    # PUBLISHED yet (see classification_status below).
    premium_category        = Column(String(30), nullable=False, index=True)

    # CONFIGURED | NOT_CONFIGURED — whether a PUBLISHED
    # GermanyOvertimePremiumCategory row existed for this category as of
    # segment_start's local date when this segment was classified. Never
    # silently upgraded to CONFIGURED by a later publication — see
    # category_rule_id below, which freezes the exact row used (or NULL).
    classification_status    = Column(String(20), nullable=False)

    # The exact PUBLISHED GermanyOvertimePremiumCategory row resolved for
    # this segment (frozen — NULL when classification_status is
    # NOT_CONFIGURED). This is the provenance answer to "why was this
    # period classified as NIGHT_STANDARD" — never re-resolved from
    # today's registry state.
    category_rule_id        = Column(Integer, ForeignKey("payroll_germany_overtime_premium_categories.id"), nullable=True)

    # The German local (Europe/Berlin) calendar date this segment falls
    # on — distinct from GermanyOvertimeWorkRecord.work_date (which is
    # operator-entered and may not reflect the correct local date for a
    # segment produced after a midnight crossing).
    work_date_local          = Column(Date, nullable=False, index=True)

    created_at               = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_overtime_time_segment_work_record", "work_record_id"),
        Index("ix_overtime_time_segment_category_date", "premium_category", "work_date_local"),
    )

    def __repr__(self):
        return (
            f"<GermanyOvertimeTimeSegment id={self.id} work_record_id={self.work_record_id} "
            f"category={self.premium_category!r} status={self.classification_status} "
            f"start={self.segment_start} end={self.segment_end}>"
        )


# ── Germany: Overtime WAGE-TAX Calculation Result (Phase 8AF) ───────────
# One row per PHYSICAL time range (grouping the 1 or 2 GermanyOvertimeTimeSegment
# rows that share that identical [segment_start, segment_end) — see
# engine/germany_overtime_wage_tax.py's own module docstring for the full
# §3b EStG / R 3b LStR verification and the exact concurrence rule this
# implements). WAGE TAX ONLY — no social-insurance field exists anywhere
# on this table; §1 SvEV / the SOCIAL_INSURANCE Grundlohn cap are never
# read by the code that populates it. Not a GermanyOvertimePremiumComponent
# (explicitly deferred to Phase 8AH) and not a payslip line — this is a
# calculation-preview/domain result, not a finalized payroll amount.
class GermanyOvertimeWageTaxResult(Base):
    __tablename__ = "payroll_germany_overtime_wage_tax_results"

    id                    = Column(Integer, primary_key=True, index=True)
    organization_id       = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    work_record_id        = Column(Integer, ForeignKey("payroll_germany_overtime_work_records.id"), nullable=False, index=True)

    segment_start          = Column(DateTime(timezone=True), nullable=False)
    segment_end             = Column(DateTime(timezone=True), nullable=False)
    work_date_local          = Column(Date, nullable=False, index=True)
    qualifying_hours          = Column(Numeric(6, 4), nullable=False)

    # Frozen inputs — never re-derived from today's EmployeeStatutoryProfile
    # or registry state once written (historical reproducibility).
    actual_grundlohn_hourly   = Column(Numeric(10, 2), nullable=True)   # NULL when calculation_status != CALCULATED
    tax_grundlohn_hourly      = Column(Numeric(10, 2), nullable=True)   # actual, capped at the resolved WAGE_TAX ceiling
    grundlohn_cap_rule_id     = Column(Integer, ForeignKey("payroll_germany_overtime_grundlohn_caps.id"), nullable=True)

    # Primary category (always set when CALCULATED) and, ONLY for the one
    # verified concurrence case (night + Sunday/holiday, R 3b Abs. 3 Satz 2
    # LStH — see module docstring), the second, concurrently-applicable
    # category whose rate was added to the primary's. NULL for every other
    # combination — those fail closed (STATUTORY_RULE_UNRESOLVED) instead.
    primary_category_code     = Column(String(30), nullable=True)
    primary_category_rule_id  = Column(Integer, ForeignKey("payroll_germany_overtime_premium_categories.id"), nullable=True)
    concurrent_category_code   = Column(String(30), nullable=True)
    concurrent_category_rule_id = Column(Integer, ForeignKey("payroll_germany_overtime_premium_categories.id"), nullable=True)
    combined_tax_free_pct       = Column(Numeric(6, 2), nullable=True)  # single rate, or the verified R 3b sum

    # Outputs. gross_qualifying_premium_amount is the STATUTORY-RATE
    # premium computed at the employee's ACTUAL (uncapped) Grundlohn — see
    # the module docstring's explicit disclosure of why this is an
    # engineering interpretation, not a directly-quoted statutory formula,
    # since no actual-premium-PAID amount exists anywhere in this codebase.
    gross_qualifying_premium_amount = Column(Numeric(12, 2), nullable=True)
    tax_free_premium_amount          = Column(Numeric(12, 2), nullable=True)
    taxable_premium_amount           = Column(Numeric(12, 2), nullable=True)

    # CALCULATED | NOT_CONFIGURED | STATUTORY_RULE_UNRESOLVED | INSUFFICIENT_DATA
    calculation_status        = Column(String(30), nullable=False)
    calculation_note           = Column(Text, nullable=True)

    created_by_id               = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at                   = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_overtime_wage_tax_result_work_record", "work_record_id"),
        Index("ix_overtime_wage_tax_result_org_date", "organization_id", "work_date_local"),
    )

    def __repr__(self):
        return (
            f"<GermanyOvertimeWageTaxResult id={self.id} work_record_id={self.work_record_id} "
            f"status={self.calculation_status} tax_free={self.tax_free_premium_amount}>"
        )


# ── Germany: Overtime SOCIAL-INSURANCE Calculation Result (Phase 8AG) ───
# One row per PHYSICAL time range — same grouping/shape as
# GermanyOvertimeWageTaxResult (Phase 8AF), but COMPLETELY INDEPENDENT: no
# code path shares a row or a cap between the two. See
# engine/germany_overtime_social_insurance.py's own module docstring for
# the full §1 SvEV verification. SOCIAL INSURANCE ONLY — no wage-tax field
# exists on this table; the WAGE_TAX Grundlohn cap is never read by the
# code that populates it. Applies uniformly to GKV/PV/RV/ALV (verified
# this phase — §1 Abs. 2 SvEV explicitly carves out ONLY Unfallversicherung/
# Seefahrt as different, confirming by contrast that GKV/PV/RV/ALV are NOT
# differentiated from one another); Unfallversicherung itself is out of
# this table's scope (handled, unrelated, by the existing EmployerTaxProfile
# mechanism). Not a GermanyOvertimePremiumComponent (Phase 8AH) and not a
# payslip line.
class GermanyOvertimeSocialInsuranceResult(Base):
    __tablename__ = "payroll_germany_overtime_social_insurance_results"

    id                    = Column(Integer, primary_key=True, index=True)
    organization_id       = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    work_record_id        = Column(Integer, ForeignKey("payroll_germany_overtime_work_records.id"), nullable=False, index=True)

    segment_start          = Column(DateTime(timezone=True), nullable=False)
    segment_end             = Column(DateTime(timezone=True), nullable=False)
    work_date_local          = Column(Date, nullable=False, index=True)
    qualifying_hours          = Column(Numeric(6, 4), nullable=False)

    # Frozen inputs — independently resolved from Phase 8AF's wage-tax
    # path (no shared row, no shared cap row).
    actual_grundlohn_hourly   = Column(Numeric(10, 2), nullable=True)
    si_grundlohn_hourly        = Column(Numeric(10, 2), nullable=True)   # actual, capped at the resolved SOCIAL_INSURANCE ceiling
    si_cap_rule_id              = Column(Integer, ForeignKey("payroll_germany_overtime_grundlohn_caps.id"), nullable=True)

    primary_category_code     = Column(String(30), nullable=True)
    primary_category_rule_id  = Column(Integer, ForeignKey("payroll_germany_overtime_premium_categories.id"), nullable=True)
    concurrent_category_code   = Column(String(30), nullable=True)
    concurrent_category_rule_id = Column(Integer, ForeignKey("payroll_germany_overtime_premium_categories.id"), nullable=True)
    combined_premium_pct        = Column(Numeric(6, 2), nullable=True)

    # Applies uniformly to these branches (verified §1 Abs. 2 SvEV
    # contrast — see module docstring); a documented, explicit marker
    # rather than 4 redundant near-duplicate status columns, since no
    # source establishes any difference AMONG these four.
    applicable_si_branches       = Column(String(30), nullable=True, default="GKV_PV_RV_ALV")

    gross_qualifying_premium_amount = Column(Numeric(12, 2), nullable=True)
    si_free_premium_amount           = Column(Numeric(12, 2), nullable=True)
    si_contributory_premium_amount   = Column(Numeric(12, 2), nullable=True)

    # CALCULATED | NOT_CONFIGURED | STATUTORY_RULE_UNRESOLVED | INSUFFICIENT_DATA
    calculation_status        = Column(String(30), nullable=False)
    calculation_note           = Column(Text, nullable=True)

    created_by_id               = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at                   = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_overtime_si_result_work_record", "work_record_id"),
        Index("ix_overtime_si_result_org_date", "organization_id", "work_date_local"),
    )

    def __repr__(self):
        return (
            f"<GermanyOvertimeSocialInsuranceResult id={self.id} work_record_id={self.work_record_id} "
            f"status={self.calculation_status} si_free={self.si_free_premium_amount}>"
        )


# ── Germany: Overtime Premium Component (Phase 8AH) ─────────────────────
# "What the calculation produced" (Phase 8AA/8AH's own design-principle
# separation — see this phase's report §6): one row per PHYSICAL time
# range, COMBINING the already-independently-verified
# GermanyOvertimeWageTaxResult (Phase 8AF) and GermanyOvertimeSocialInsuranceResult
# (Phase 8AG) rows for that same range into a single presentable,
# four-dimension output unit. Never recomputes either calculation; only
# joins the two existing results by (work_record_id, segment_start,
# segment_end) and reconciles their independently-derived gross amounts
# (which must agree, since both read the same underlying facts — see
# germany_overtime_social_insurance.py's own docstring — a genuine
# disagreement is a defect, not a value judgement, hence AMOUNT_MISMATCH
# fails closed rather than picking one arbitrarily).
#
# Attachment to a real payslip line (payslip_allowance_item_id) is an
# EXPLICIT, separate operator action (see
# service.attach_germany_overtime_premium_component_to_payslip) — never
# automatic during payroll-run generation. This is a deliberate scope
# boundary, not an oversight: automatic inclusion would require resolving
# two product decisions this project has repeatedly, explicitly left open
# (GermanyOvertimeWorkRecord manual-vs-attendance-derived source
# precedence — Phase 8AC; and whether inclusion should be automatic vs.
# opt-in at all), and a component may only be attached once
# hr_approval_status=APPROVED on its work record — the natural,
# already-existing use of that field's own stated purpose (Phase 8AC:
# "an HR/manager sign-off that the hours were legitimately worked"), not
# a newly-invented business rule. See Phase 8AH's report for the full
# reasoning.
class GermanyOvertimePremiumComponent(Base):
    __tablename__ = "payroll_germany_overtime_premium_components"

    id                    = Column(Integer, primary_key=True, index=True)
    organization_id       = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    work_record_id        = Column(Integer, ForeignKey("payroll_germany_overtime_work_records.id"), nullable=False, index=True)

    segment_start   = Column(DateTime(timezone=True), nullable=False)
    segment_end     = Column(DateTime(timezone=True), nullable=False)
    work_date_local = Column(Date, nullable=False, index=True)
    qualifying_hours = Column(Numeric(6, 4), nullable=False)

    # Pointers to the two independent calculation results this component
    # combines — either may be NULL (see combination_status below); never
    # a third, separately-computed value.
    wage_tax_result_id          = Column(Integer, ForeignKey("payroll_germany_overtime_wage_tax_results.id"), nullable=True)
    social_insurance_result_id  = Column(Integer, ForeignKey("payroll_germany_overtime_social_insurance_results.id"), nullable=True)

    # COMPLETE (both CALCULATED, gross amounts reconciled) |
    # PARTIAL_WAGE_TAX_ONLY | PARTIAL_SOCIAL_INSURANCE_ONLY |
    # AMOUNT_MISMATCH (both CALCULATED but gross amounts disagree beyond
    # rounding — fails closed, never silently picks one) | NONE (neither
    # dimension CALCULATED yet).
    combination_status = Column(String(30), nullable=False)
    calculation_note    = Column(Text, nullable=True)

    # Four-dimension output — NEVER collapsed into one "taxable" field
    # (Phase 8AH §8). gross_premium_amount is only populated for COMPLETE/
    # PARTIAL_* (never for AMOUNT_MISMATCH or NONE — no guessing).
    gross_premium_amount   = Column(Numeric(12, 2), nullable=True)
    wage_tax_free_amount   = Column(Numeric(12, 2), nullable=True)
    wage_taxable_amount    = Column(Numeric(12, 2), nullable=True)
    si_exempt_amount       = Column(Numeric(12, 2), nullable=True)
    si_contributory_amount = Column(Numeric(12, 2), nullable=True)

    # Phase 8AQ — explicit tri-state, the authoritative "is this
    # component's amount currently on a payslip" signal. NEVER_ATTACHED
    # is the only state build_germany_overtime_premium_components() may
    # delete-and-recreate on rebuild (Phase 8AH §22, extended Phase 8AQ):
    # both ATTACHED and DETACHED are historical facts — a component that
    # was ever attached is frozen forever, exactly like one still
    # attached, so a detach can never be silently erased by a later
    # rebuild. payslip_allowance_item_id/attached_at/attached_by_id are
    # therefore an append-only "most recent attach" record — Phase 8AQ's
    # detach action does NOT null them out (that would make a detached
    # row indistinguishable from a never-attached, rebuildable one); only
    # attachment_status/detached_at/detached_by_id change on detach.
    attachment_status = Column(String(20), nullable=False, default="NEVER_ATTACHED", server_default="NEVER_ATTACHED")
    payslip_allowance_item_id = Column(Integer, ForeignKey("payslip_allowance_items.id"), nullable=True)
    attached_at               = Column(DateTime(timezone=True), nullable=True)
    attached_by_id            = Column(Integer, ForeignKey("users.id"), nullable=True)
    detached_at               = Column(DateTime(timezone=True), nullable=True)
    detached_by_id            = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Phase 8AR — Germany overtime NET-PAY INTEGRATION. Forensic finding:
    # attach previously never touched PayslipItem.gross_pay/pf/esi/net_pay
    # at all — only a separate PayslipAllowanceItem line. RV/ALV/GKV/PV
    # (mapped onto PayslipItem.pf/esi, spec's own field reuse — see
    # engine/countries/germany.py's own `return dict(employee_pf=employee_rv,
    # employee_esi=employee_alv+employee_gkv+employee_pv, ...)`) are
    # statutorily independent of the BMF PAP wage-tax engine and are
    # therefore SAFELY, correctly computable today; wage tax (and
    # therefore a fully correct net_pay) is NOT, because PAP remains
    # unconditionally BLOCKED_EXTERNAL (proven live this phase) — seeing
    # this financial-integration status is how an operator/API caller
    # tells the two apart, never by guessing from silence.
    # NOT_INTEGRATED (default; never attached) |
    # PARTIAL_WAGE_TAX_PENDING_PAP (gross + SI deltas applied; wage-tax
    #   delta uncomputable while PAP is BLOCKED_EXTERNAL) |
    # REVERSED (attached then detached — deltas nulled, PayslipItem
    #   returned to pre-attach state).
    financial_integration_status = Column(String(40), nullable=False, default="NOT_INTEGRATED", server_default="NOT_INTEGRATED")
    # The EXACT deltas actually applied to the PayslipItem at attach time —
    # stored (never recomputed from current registries) so detach reverses
    # precisely what was applied, immune to any registry change in between
    # (Phase 8AQ's own effective-dating/immutability discipline, applied
    # here to a financial delta instead of a statutory registry row).
    # applied_pf_delta  = RV (Rentenversicherung) employee contribution
    #                     delta → PayslipItem.pf.
    # applied_esi_delta = ALV + GKV employee contribution delta
    #                     → PayslipItem.esi (PV excluded — config-dependent).
    # Wage-tax delta has no dedicated column (it is 0 while PAP is
    # BLOCKED_EXTERNAL); it is represented by financial_integration_status
    # plus the germany_calculation_snapshot/audit trace.
    applied_gross_delta = Column(Numeric(12, 2), nullable=True)
    applied_pf_delta    = Column(Numeric(12, 2), nullable=True)
    applied_esi_delta   = Column(Numeric(12, 2), nullable=True)

    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # One component per physical time range per work record — the
        # natural uniqueness boundary (Phase 8AH §21), matching Phase
        # 8AE/8AF/8AG's own per-physical-range grouping.
        # One component per physical time range per work record — the
        # natural uniqueness boundary (Phase 8AH §21), matching Phase
        # 8AE/8AF/8AG's own per-physical-range grouping. Note:
        # payslip_allowance_item_id is deliberately NOT unique — several
        # components (e.g. two different overtime days in the same
        # payroll period) may legitimately roll up into the SAME payslip
        # line (see service.attach_germany_overtime_premium_component_to_payslip's
        # own docstring); double-attachment of a SINGLE component is
        # prevented by that function's own payslip_allowance_item_id-is-
        # already-set check, not by a DB constraint on the target.
        UniqueConstraint(
            "work_record_id", "segment_start", "segment_end",
            name="uq_overtime_premium_component_work_record_range",
        ),
        Index("ix_overtime_premium_component_work_record", "work_record_id"),
        Index("ix_overtime_premium_component_org_date", "organization_id", "work_date_local"),
    )

    def __repr__(self):
        return (
            f"<GermanyOvertimePremiumComponent id={self.id} work_record_id={self.work_record_id} "
            f"status={self.combination_status} gross={self.gross_premium_amount}>"
        )


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

    # Widened from String(20) to String(50) — several Canada employer-levy
    # component keys (e.g. "bc_eht_charity_exemption_threshold", 34 chars)
    # exceeded the original limit, discovered when live data entry via the
    # Super Admin API failed with a DB-level StringDataRightTruncation
    # error. The shorter keys below ("pf" | "esi" | "pt" | "tds" | "cpp" |
    # ...) still fit comfortably.
    component_key        = Column(String(50), nullable=False)
    label                = Column(String(100), nullable=False)  # → r.label
    employee_share       = Column(String(50), nullable=False)   # → r.employee (display string)
    employer_share       = Column(String(50), nullable=False)   # → r.employer (display string)
    total                = Column(String(50), nullable=False)   # → r.total (display string)

    # Widened from Numeric(6,4) to Numeric(7,4) — ZP-TAX-UK-2026-27-001's
    # small-employer Statutory Family Pay recovery rate is 109% (employers
    # recover MORE than they paid out), which exceeded the original
    # column's ~99.9999% ceiling. See migration f4a5b6c7d8e9.
    employee_rate_pct    = Column(Numeric(7, 4), nullable=True)  # e.g. 0.1200 for 12%
    employer_rate_pct    = Column(Numeric(7, 4), nullable=True)
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
    # US-specific (but not US-only by construction — any country whose tax
    # law varies by filing/marital status could use it): "SINGLE" | "MFJ" |
    # "MFS" | "HOH", or NULL meaning "applies regardless of filing status" —
    # NULL is the value on every row that existed before this column, so
    # India/UK/every other jurisdiction's resolution is completely
    # unaffected. Only a row explicitly tagged with a filing_status is
    # preferred over a NULL row for an employee with a matching
    # w4_filing_status (see engine/countries/shared.py:_calculate_annual_tax
    # and resolve_jurisdiction_parameter).
    filing_status         = Column(String(20), nullable=True)
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
            # own, same as before. filing_status added the same way for
            # the same reason (e.g. Single/MFJ/HoH additional-Medicare
            # threshold rows coexisting) — a NULL-filing-status row's
            # uniqueness is completely unaffected by rows that do set one.
            "uq_contribution_rate_org_country_component",
            "organization_id", "jurisdiction_country", "component_key", "tax_regime", "filing_status",
            unique=True,
            postgresql_where=text("organization_id IS NOT NULL"),
            sqlite_where=text("organization_id IS NOT NULL"),
        ),
        Index(
            "uq_contribution_rate_canonical_country_state_component",
            "jurisdiction_country", "jurisdiction_state", "component_key", "tax_regime", "filing_status",
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
    # Widened from Numeric(5,2) to Numeric(6,4) — matching
    # ContributionRate.employee_rate_pct/employer_rate_pct's precision.
    # Found live: Ontario EHT's real 2026 band rates (e.g. 1.101%,
    # 1.223%, 1.465%) need 3 decimal places and were silently truncated
    # to 2 (1.10%, 1.22%, 1.47%) by the old Numeric(5,2) column — the
    # API accepted the PUT with no error, so this went unnoticed until
    # the response was read back and compared against the source values.
    rate_pct             = Column(Numeric(6, 4), nullable=False)   # e.g. 5.0000 for 5%
    # Was String(20) — sized for short values like "5%"/"Nil". Widened for
    # NI_BAND rows, whose label is a real descriptive name (e.g. "Main Rate
    # Band (PT to UEL)") rather than a short percentage — see migration
    # 048c9fc1d64f.
    rate_label           = Column(String(150), nullable=False)     # → s.rate, e.g. "5%" or "Nil"
    tax_formula          = Column(String(150), nullable=False)     # → s.tax, display text
    sort_order           = Column(Integer, default=0)

    jurisdiction_country = Column(String(10), nullable=False, server_default="IN", default="IN")
    jurisdiction_state    = Column(String(100), nullable=True)   # null = country-level
    jurisdiction_locality = Column(String(100), nullable=True)   # null = state-level (or country-level if state is also null)
    tax_regime            = Column(String(20), nullable=True)
    # Same convention/reasoning as ContributionRate.filing_status above —
    # NULL (every pre-existing row) means "applies regardless of filing
    # status," so India/UK/existing-US bracket resolution is unaffected.
    # engine/countries/shared.py:_calculate_annual_tax prefers a row whose
    # filing_status matches the employee's over a NULL row when both exist.
    filing_status         = Column(String(20), nullable=True)

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
    # Widened alongside rate_pct above, same reasoning/precedent.
    employer_rate_pct     = Column(Numeric(6, 4), nullable=True)
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

    # BC Employer Health Tax ordinary vs. registered-charity/nonprofit
    # classification (ZP-TAX-CA-2026-001 §15/AC-20) — "CHARITY_NONPROFIT"
    # selects BC's charity thresholds/rates in engine/countries/canada.py;
    # NULL/anything else is treated as ordinary. No Compliance Details UI
    # sets this field yet — a disclosed, known gap; every org defaults to
    # ordinary until either a UI is built or it's set directly.
    bc_eht_employer_classification = Column(String(20), nullable=True)

    # Quebec HSF employer category — GENERAL | PRIMARY_MANUFACTURING |
    # PUBLIC_SECTOR (ZP-TAX-CA-2026-001 §13) — same disclosed "no UI yet"
    # gap as bc_eht_employer_classification above; NULL is treated as
    # GENERAL, the most common case.
    qc_hsf_employer_category = Column(String(30), nullable=True)

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

    # Evidence chain for this pack's rates (agency, title, URL, checksum,
    # retrieved date, reviewer — see SourceArtifact below). NULL for every
    # existing pack; only enforced (see service.py's Active-transition
    # gate) for packs where the enforcing jurisdiction opts in.
    source_document_id  = Column(Integer, ForeignKey("payroll_source_artifacts.id"), nullable=True)

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


# ── Report Templates (Super Admin-authored; jurisdiction-wide, NOT
# org-scoped — same "describes a jurisdiction, reused by every org in it"
# philosophy as JurisdictionPack) ────────────────────────────────────────
# Lifecycle is deliberately its own vocabulary (Draft -> Review -> Approved
# -> Published -> Active -> Superseded), NOT JurisdictionPack's
# (Draft|In Review|QA|Approved|Active|Deprecated|Retired) — a report
# template has a genuine "Published but not yet the live version" state
# (reviewable/assignable, but not the one Organizations resolve against)
# that JurisdictionPack's lifecycle has no equivalent for.
class ReportTemplate(Base):
    """Versioned identity/metadata for a jurisdiction-specific statutory
    report template (e.g. India's Salary TDS Report, UK's P60). Super
    Admin authors and publishes these; Organizations only ever consume the
    Active version for their jurisdiction/report/tax year — they never
    edit a template directly."""
    __tablename__ = "payroll_report_templates"

    id = Column(Integer, primary_key=True, index=True)

    template_key = Column(String(100), nullable=False)   # e.g. "IN-TDS-SALARY"
    name         = Column(String(200), nullable=False)   # "Salary TDS Report"
    report_type  = Column(String(50), nullable=False)    # "TDS" | "P60" | "941" | ... — open, not a DB enum

    jurisdiction_country  = Column(String(100), nullable=False)
    jurisdiction_state    = Column(String(100), nullable=True)   # null = country-level template
    jurisdiction_locality = Column(String(100), nullable=True)

    reporting_year = Column(String(20), nullable=False)   # e.g. "2026-27" or "2026"
    version        = Column(String(20), nullable=False, default="1.0")
    status         = Column(String(20), nullable=False, default="Draft")
    # Draft | Review | Approved | Published | Active | Superseded.

    description           = Column(Text, nullable=True)
    regulatory_authority   = Column(String(200), nullable=True)
    effective_from         = Column(Date, nullable=True)
    effective_to           = Column(Date, nullable=True)
    change_summary         = Column(Text, nullable=True)
    source_references      = Column(Text, nullable=True)

    # "AGGREGATE" (one document for the whole run — e.g. Form 138, an
    # EPS/FPS-style employer summary) | "PER_EMPLOYEE" (one document per
    # employee — e.g. Form 130, P60). Drives which PDF renderer and
    # download shape (single file vs ZIP) a generated report uses; does
    # NOT change generation or the rendered_data snapshot shape itself.
    document_scope = Column(String(20), nullable=False, default="AGGREGATE")

    # Evidence chain for the actual government form/publication this
    # template is based on — reuses SourceArtifact verbatim (same FK
    # pattern as LocalityDataset.source_document_id), never a parallel
    # evidence system. source_references above stays free-text citation;
    # this is the real, hash-verified link.
    source_document_id = Column(Integer, ForeignKey("payroll_source_artifacts.id"), nullable=True)

    # Absolute currency tolerance for the generation-time reconciliation
    # check (see generate_report_from_template) — NULL means exact match
    # is required.
    reconciliation_tolerance = Column(Numeric(12, 2), nullable=True)

    approved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_by_id  = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by_id  = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Self-reference so a new version can point back at what it replaced —
    # same "never overwrite, chain instead" convention as
    # JurisdictionPack.previous_version_id.
    previous_version_id = Column(Integer, ForeignKey("payroll_report_templates.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("template_key", "version", name="uq_report_template_key_version"),
        Index(
            "ix_report_templates_jurisdiction_year_type",
            "jurisdiction_country", "jurisdiction_state", "reporting_year", "report_type",
        ),
    )

    def __repr__(self):
        return f"<ReportTemplate {self.template_key} v{self.version} status={self.status}>"


class ReportTemplateComponent(Base):
    """One section of a ReportTemplate (Employer Info, Earnings, Tax, ...).
    A real child table, not a JSON blob, because the set of components is
    admin-defined per template and each one needs to be individually
    orderable/deletable/referenced by its own fields — the same reasoning
    PayslipAllowanceItem uses for admin-defined allowance rows, rather
    than the fixed-key-bag reasoning behind policy_defaults-style JSON
    columns."""
    __tablename__ = "payroll_report_template_components"

    id = Column(Integer, primary_key=True, index=True)
    report_template_id = Column(Integer, ForeignKey("payroll_report_templates.id"), nullable=False, index=True)

    component_key       = Column(String(50), nullable=False)   # "employer_info" | "earnings" | "tax" | ...
    label                = Column(String(150), nullable=False)
    component_category   = Column(String(30), nullable=False, default="standard")  # "standard" | "jurisdiction_specific" — descriptive only
    sort_order            = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("report_template_id", "component_key", name="uq_report_component_template_key"),
    )


class ReportTemplateComponentField(Base):
    """One field within a ReportTemplateComponent. `source_column` is
    validated at upsert time (service.py's upsert_report_field) against
    _REPORT_FIELD_ALLOWED_COLUMNS — a real column on PayslipItem/PayrollRun/
    CompanyComplianceDetails, never a free-typed/fabricated value."""
    __tablename__ = "payroll_report_template_component_fields"

    id = Column(Integer, primary_key=True, index=True)
    component_id = Column(Integer, ForeignKey("payroll_report_template_components.id"), nullable=False, index=True)

    field_key  = Column(String(50), nullable=False)    # "pf_employee", "gross_pay", "employer_name"
    label      = Column(String(150), nullable=False)
    field_type = Column(String(20), nullable=False)     # percentage | currency | date | boolean | enum | text | tax-bracket-table

    data_source_kind = Column(String(20), nullable=False)   # PAYSLIP_ITEM | PAYROLL_RUN | EMPLOYER_PROFILE
    source_column     = Column(String(50), nullable=False)
    aggregation        = Column(String(20), nullable=True)   # NULL | SUM_RUN | SUM_YTD — only meaningful for numeric PAYSLIP_ITEM columns

    enum_values  = Column(JSON, nullable=True)   # only used when field_type == "enum"
    format_hint  = Column(String(50), nullable=True)
    is_required  = Column(Boolean, nullable=False, default=False)
    sort_order   = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("component_id", "field_key", name="uq_report_field_component_key"),
    )


class GeneratedReport(Base):
    """An immutable, organization-scoped output artifact: the result of
    rendering a specific ReportTemplate version against a specific
    PayrollRun. Freezes template_version + a full rendered_data snapshot
    (mirrors PayslipItem.tax_policy_version + tax_rule_snapshot) so a
    later template edit/republish can never retroactively change a
    historical report."""
    __tablename__ = "payroll_generated_reports"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    report_template_id = Column(Integer, ForeignKey("payroll_report_templates.id"), nullable=False, index=True)
    template_version    = Column(String(20), nullable=False)   # snapshotted at generation time
    report_type          = Column(String(50), nullable=False)   # denormalized from template, for cheap listing

    payroll_run_id = Column(Integer, ForeignKey("payroll_runs.id"), nullable=False, index=True)

    jurisdiction_country = Column(String(100), nullable=False)
    jurisdiction_state    = Column(String(100), nullable=True)
    reporting_year         = Column(String(20), nullable=False)
    reporting_period        = Column(String(50), nullable=True)   # denormalized from PayrollRun.period_label at generation time

    applicable_tax_pack_id      = Column(Integer, ForeignKey("payroll_jurisdiction_packs.id"), nullable=True)
    applicable_tax_pack_version = Column(String(20), nullable=True)

    status = Column(String(20), nullable=False, default="Generated")  # Generated | Superseded | Void

    generated_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    generated_at    = Column(DateTime(timezone=True), server_default=func.now())

    rendered_data  = Column(JSON, nullable=False)   # frozen template-structure + resolved values
    reconciliation = Column(JSON, nullable=True)    # frozen rendering-consistency check, computed at generation time
    notes          = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_generated_reports_org_run", "organization_id", "payroll_run_id"),
        Index("ix_generated_reports_template", "report_template_id"),
        # Only one "live" generated report per (org, run, template) at a
        # time — regenerating flips the old row to Superseded rather than
        # deleting/overwriting it, so history is preserved (same NULL-safe
        # partial-unique-index pattern as ContributionRate).
        Index(
            "uq_generated_report_org_run_template_active",
            "organization_id", "payroll_run_id", "report_template_id",
            unique=True,
            postgresql_where=text("status = 'Generated'"),
            sqlite_where=text("status = 'Generated'"),
        ),
    )

    def __repr__(self):
        return f"<GeneratedReport org={self.organization_id} run={self.payroll_run_id} template={self.report_template_id} status={self.status}>"


# ── Statutory Filing Calendar (jurisdiction-wide; Super Admin-authored) ──
# A genuinely new concept in this codebase — no due-date/deadline table
# existed anywhere before this. Modeled after SourceArtifact/
# JurisdictionPack's established idioms (status lifecycle string,
# previous_version_id self-FK so a corrected due date is a new version
# rather than an edited one, own source_document_id link so the calendar
# itself is evidence-backed) rather than inventing new conventions.
class StatutoryFilingCalendar(Base):
    """One row per filing obligation within a reporting period (e.g.
    India Form 138's Q1 due 31 Jul 2026) for a jurisdiction + report type.
    Never hardcoded in application/frontend code — Organizations read this
    table to know when a report is actually due."""
    __tablename__ = "payroll_statutory_filing_calendar"

    id = Column(Integer, primary_key=True, index=True)

    jurisdiction_country  = Column(String(100), nullable=False)
    jurisdiction_state    = Column(String(100), nullable=True)   # null = country-level
    report_type           = Column(String(50), nullable=False)   # "TDS" | "P60" | ... — matches ReportTemplate.report_type
    reporting_year        = Column(String(20), nullable=False)

    period_key    = Column(String(20), nullable=False)    # "Q1", "Q2", "ANNUAL", ...
    period_label  = Column(String(100), nullable=False)   # "April-June"
    due_date      = Column(Date, nullable=False)

    status = Column(String(20), nullable=False, default="Draft")
    # Draft | Approved | Active | Superseded — same vocabulary as ReportTemplate.

    source_document_id  = Column(Integer, ForeignKey("payroll_source_artifacts.id"), nullable=True)
    previous_version_id = Column(Integer, ForeignKey("payroll_statutory_filing_calendar.id"), nullable=True)

    approved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_by_id  = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by_id  = Column(Integer, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # No DB-level UniqueConstraint on (jurisdiction, report_type, year,
    # period) — a corrected due date is a NEW row (chained via
    # previous_version_id), so multiple rows for the same period are
    # expected over time. "Only one Active row per period" is enforced in
    # the service layer (mirrors set_report_template_status's overlap
    # guard), matching JurisdictionPack's own established pattern rather
    # than a DB constraint that can't distinguish current-vs-historical.
    __table_args__ = (
        Index(
            "ix_filing_calendar_lookup",
            "jurisdiction_country", "jurisdiction_state", "report_type", "reporting_year",
        ),
    )

    def __repr__(self):
        return f"<StatutoryFilingCalendar {self.jurisdiction_country} {self.report_type} {self.period_key} due={self.due_date}>"


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


# ── US Jurisdiction: Source Evidence, Locality, Employer Overlay,     ────
# ── Taxability Matrix, Reciprocity, YTD Accumulation                  ────
# All new, purely additive tables — no existing table/column above is
# altered. Introduced to close the gaps documented in
# docs/ZoikoPayroll_US_Architecture_Gap_Analysis.md against
# ZP-TAX-US-2026-001. Every FK from these tables INTO the existing schema
# is nullable on the existing side (e.g. JurisdictionPack.source_document_id),
# so India/UK and any pre-existing US rows are completely unaffected by
# these tables simply existing and being empty.

class SourceArtifact(Base):
    """The standard's §14.2 minimum source record — one row per official
    publication a statutory value was taken from. Referenced by
    JurisdictionPack, LocalityDataset, EmployerTaxProfile, and
    ReciprocityRule via a nullable FK; nothing requires it to be set today,
    but the Active-transition gate (service.py) can require it per-pack."""
    __tablename__ = "payroll_source_artifacts"

    id                    = Column(Integer, primary_key=True, index=True)
    agency                = Column(String(200), nullable=False)   # "IRS", "California EDD"
    title                 = Column(String(300), nullable=False)   # "Publication 15-T (2026)"
    form_number           = Column(String(50), nullable=True)
    source_url            = Column(String(500), nullable=True)
    publication_date      = Column(Date, nullable=True)
    retrieved_at          = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    checksum_sha256       = Column(String(64), nullable=True)
    reviewer_id           = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewer_approved_at  = Column(DateTime(timezone=True), nullable=True)
    superseded_by_id      = Column(Integer, ForeignKey("payroll_source_artifacts.id"), nullable=True)
    created_at            = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<SourceArtifact id={self.id} agency={self.agency} title={self.title!r}>"


# ── Germany: BMF PAP Algorithm Asset (ZP-TAX-DE-2026-001 §5, §17, §18) ────
# The versioned, source-hashed, immutable-once-published container for the
# official BMF "Programmablaufplan" (PAP) — the machine-readable wage-tax
# calculation authority Germany's spec requires production withholding to
# be based on (DE-D01: "Do not derive payroll tax solely from annual §32a
# bands"). This phase builds ONLY the container/lifecycle/evidence
# foundation — no PAP execution logic exists anywhere in this codebase as
# of this table's creation; germany.py's calculator is unchanged and does
# not read from this table.
#
# Deliberately its own table, NOT a JurisdictionPack row and NOT a
# TaxSlab.rule_type="FORMULA" row — see
# docs/PHASE_3_GERMANY_PAP_ALGORITHM_ASSET.md §11/§12 for why: a PAP asset
# represents a versioned ALGORITHM (many inputs, branching, explicit
# rounding rules), not a rate/slab table (JurisdictionPack/ContributionRate/
# TaxSlab's actual shape) and not a single-variable arithmetic expression
# (TaxSlab.FORMULA's actual, deliberately narrow, capability — Phase 1
# confirmed by direct code inspection that it cannot represent PAP's 18-input
# contract, and this table must not be used to route around that limit).
#
# No jurisdiction_state column: the spec is explicit that "the wage-tax
# algorithm remains federal" (§3, "SUBNATIONAL MODEL") — Land-level
# variation (church tax, PV/Saxony) belongs to OTHER entities, never to the
# PAP asset itself.
class PapAlgorithmAsset(Base):
    """One effective-dated, source-hashed version of the German BMF PAP.

    Status vocabulary is Germany-specific (DRAFT/REVIEW/APPROVED/PUBLISHED/
    SUPERSEDED), taken directly from the spec's own Super Admin wireframe
    (§18 "Germany Overview" and §11's Health-Fund Registry row use this
    exact five-state vocabulary) — NOT JurisdictionPack's vocabulary
    (Draft|In Review|QA|Approved|Active|Deprecated|Retired), which belongs
    to a different, already-shipped entity. The underlying LIFECYCLE
    BEHAVIOR (edit-lock once published, maker-checker before publication,
    "new version" instead of in-place correction, only one currently-
    published version per scope) is reused from JurisdictionPack's proven
    pattern — see service.py's PAP functions, which mirror
    _require_editable_pack/set_jurisdiction_pack_status's logic under new
    names for this vocabulary.
    """
    __tablename__ = "payroll_germany_pap_assets"

    id                     = Column(Integer, primary_key=True, index=True)

    jurisdiction_country   = Column(String(10), nullable=False, default="DE", server_default="DE")
    tax_year                = Column(String(20), nullable=False)   # e.g. "2026" (spec DE-D02)
    # e.g. "2026-11-12-final" — the spec's OWN canonical-config example
    # (§17). Never defaulted/seeded by application code: this phase does
    # not invent or ship a real PAP version value (see Phase 3 report §4).
    pap_version              = Column(String(100), nullable=False)

    effective_from           = Column(Date, nullable=False)
    effective_to             = Column(Date, nullable=True)

    status                   = Column(String(20), nullable=False, default="DRAFT", server_default="DRAFT")

    # Evidence chain: the official document this asset was ingested from
    # (reuses SourceArtifact, not a parallel evidence table — see Phase 3
    # report §2). object storage path to the raw ingested bytes, mirroring
    # ComplianceDocument's existing upload pattern (router.py's
    # upload_compliance_document), and the SHA-256 of those exact bytes,
    # computed server-side at ingestion (service.py never accepts a
    # caller-supplied hash for this table — see Phase 3 report §5/§7).
    source_document_id       = Column(Integer, ForeignKey("payroll_source_artifacts.id"), nullable=True)
    source_content_path      = Column(String(500), nullable=True)
    source_content_sha256    = Column(String(64), nullable=True)

    # "Build/Asset Identity" (see this table's own design diagram) — the
    # spec's "normalized/transpiled implementation version" (§5 item 1).
    # Always NULL in this phase: no transpiler/executor exists yet. Reserved
    # for the future phase that actually compiles the PAP into runnable
    # logic; NOT to be confused with pap_version (the BMF's own version
    # label) or source_content_sha256 (the raw document's hash).
    build_identifier          = Column(String(100), nullable=True)

    created_by_id             = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by_id             = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_by_id            = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Version chain — never overwritten, mirrors JurisdictionPack.previous_version_id.
    previous_version_id       = Column(Integer, ForeignKey("payroll_germany_pap_assets.id"), nullable=True)

    created_at                = Column(DateTime(timezone=True), server_default=func.now())
    updated_at                = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        # Duplicate-identity protection (Phase 3 report §9): the same
        # (country, tax_year, pap_version) triple can exist only once.
        UniqueConstraint(
            "jurisdiction_country", "tax_year", "pap_version",
            name="uq_pap_asset_country_year_version",
        ),
        Index("ix_pap_asset_country_year_status", "jurisdiction_country", "tax_year", "status"),
        # DB-level backstop (defense in depth alongside the service-layer
        # check in create/publish) for "only one PUBLISHED asset per
        # (country, tax_year) at a time" — same partial-unique-index
        # technique as EmployeeStatutoryProfile's one-open-row guard.
        Index(
            "uq_pap_asset_one_published_per_year",
            "jurisdiction_country", "tax_year",
            unique=True,
            postgresql_where=text("status = 'PUBLISHED'"),
            sqlite_where=text("status = 'PUBLISHED'"),
        ),
    )

    def __repr__(self):
        return (
            f"<PapAlgorithmAsset id={self.id} country={self.jurisdiction_country} "
            f"tax_year={self.tax_year} version={self.pap_version!r} status={self.status}>"
        )


# ── Germany: BMF PAP Production Release Governance (Phase 8G-1) ──────────
# Deliberately a SEPARATE table from PapAlgorithmAsset, not new columns/
# states bolted onto it. "This statutory document is a correct, approved,
# published asset" (PapAlgorithmAsset's own DRAFT/REVIEW/APPROVED/
# PUBLISHED/SUPERSEDED lifecycle, frozen since Phase 3) and "this asset is
# authorized to actually run in Zoiko's production Germany payroll" are
# different questions, decided by different evidence (source finality,
# commercial/licensing authorization, golden-vector certification bound to
# this exact hash, security certification, a distinct release approval,
# and a distinct activation authorization) and, in the licensing/finality
# case, by people outside engineering entirely. Conflating them would let
# "PUBLISHED" alone imply "safe to activate," which is exactly what Phase
# 8D/8F's standing production gates forbid. One release row exists per
# PapAlgorithmAsset (1:1) and is created only when someone deliberately
# starts a release attempt for that asset — never automatically.
#
# Every gate/evidence field below defaults to the unsatisfied/false/OPEN/
# PENDING state. Nothing in this schema, and no seed/migration data, ever
# sets one of these to a "satisfied" value — that only happens through an
# explicit, actor-attributed service-layer action, and real licensing/
# finality evidence must originate outside engineering (see
# docs/PHASE_8G_1_GERMANY_PAP_RELEASE_GOVERNANCE_IMPLEMENTATION_REPORT.md).
#
# Reaching status=="ACTIVE" on this table does NOT change, and cannot
# change, resolve_pap_executor()'s behavior — germany_pap/core.py is not
# imported by this module and is not modified by Phase 8G-1. Wiring this
# gate into resolve_pap_executor() is an explicit, separate, future-phase
# decision, not taken here.

class GermanyPapRelease(Base):
    """Production release/activation governance record for one
    PapAlgorithmAsset. See module-level comment above for why this is a
    separate table from PapAlgorithmAsset's own statutory lifecycle."""
    __tablename__ = "payroll_germany_pap_releases"

    id            = Column(Integer, primary_key=True, index=True)
    pap_asset_id  = Column(Integer, ForeignKey("payroll_germany_pap_assets.id"), nullable=False, unique=True)

    # Denormalized from the bound PapAlgorithmAsset at create_pap_release
    # time (Phase 8H) — never independently settable, never updated after
    # creation (an asset's country/tax_year are themselves immutable post-
    # ingestion). Exists ONLY so the database itself — not just a service-
    # layer SELECT-then-UPDATE check — can enforce "at most one ACTIVE
    # release per (country, tax_year)" via the partial unique index below.
    # Phase 8G-2 found the service-layer-only check shares PapAlgorithmAsset's
    # own long-standing PUBLISHED-conflict pattern (a real, if narrow,
    # TOCTOU gap under true concurrent transactions); this column plus the
    # index closes that gap with an actual database constraint.
    jurisdiction_country  = Column(String(10), nullable=True)
    tax_year               = Column(String(20), nullable=True)

    # Bound at release-record creation time from the asset's OWN
    # source_content_sha256 (never caller-supplied). Re-checked against the
    # asset's LIVE value at every gate evaluation (service.py) — if they
    # ever diverge, the hash gate fails closed; the stored value is never
    # silently re-bound to whatever the asset currently says.
    bound_source_content_sha256 = Column(String(64), nullable=True)

    status = Column(String(30), nullable=False, default="NOT_READY", server_default="NOT_READY")
    # NOT_READY | READY_FOR_RELEASE | RELEASE_APPROVED | ACTIVATION_BLOCKED
    # | ACTIVE | ROLLBACK_REQUESTED | ROLLBACK_APPROVED | ROLLED_BACK

    # ── Source identity / hash evidence ──
    source_identity_verified         = Column(Boolean, nullable=False, default=False, server_default="0")
    source_identity_verified_by_id   = Column(Integer, ForeignKey("users.id"), nullable=True)
    source_identity_verified_at      = Column(DateTime(timezone=True), nullable=True)
    source_identity_notes            = Column(Text, nullable=True)

    source_hash_verified             = Column(Boolean, nullable=False, default=False, server_default="0")
    source_hash_verified_by_id       = Column(Integer, ForeignKey("users.id"), nullable=True)
    source_hash_verified_at          = Column(DateTime(timezone=True), nullable=True)

    # ── Source-finality evidence (independent of the code-level
    # PAP_SOURCE_FINALITY constant in germany_pap/adapter.py, which this
    # table never reads or writes) ──
    source_finality_status           = Column(String(20), nullable=False, default="OPEN", server_default="OPEN")
    # OPEN | VERIFIED | SUPERSEDED | REJECTED
    source_finality_authority        = Column(String(200), nullable=True)
    source_finality_reference        = Column(String(200), nullable=True)
    source_finality_verified_by_id   = Column(Integer, ForeignKey("users.id"), nullable=True)
    source_finality_verified_at      = Column(DateTime(timezone=True), nullable=True)
    source_finality_notes            = Column(Text, nullable=True)

    # ── Licensing / commercial-use authorization evidence ──
    licensing_status                 = Column(String(20), nullable=False, default="PENDING", server_default="PENDING")
    # PENDING | AUTHORIZED | DENIED
    licensing_authority              = Column(String(200), nullable=True)
    licensing_reference              = Column(String(200), nullable=True)
    licensing_authorization_date     = Column(Date, nullable=True)
    licensing_effective_date         = Column(Date, nullable=True)
    licensing_expiry_date            = Column(Date, nullable=True)
    licensing_evidence_location      = Column(String(500), nullable=True)
    licensing_evidence_hash          = Column(String(64), nullable=True)
    licensing_notes                  = Column(Text, nullable=True)
    licensing_recorded_by_id         = Column(Integer, ForeignKey("users.id"), nullable=True)

    # ── Golden-vector certification, bound to this exact source hash —
    # certifying version A's bytes must never be accepted as proof for
    # version B's (service.py rejects a mismatch at write time). ──
    golden_vectors_passed            = Column(Boolean, nullable=False, default=False, server_default="0")
    golden_vectors_source_sha256     = Column(String(64), nullable=True)
    golden_vectors_verified_by_id    = Column(Integer, ForeignKey("users.id"), nullable=True)
    golden_vectors_verified_at       = Column(DateTime(timezone=True), nullable=True)
    golden_vectors_notes             = Column(Text, nullable=True)

    # ── Security certification ──
    security_certified               = Column(Boolean, nullable=False, default=False, server_default="0")
    security_certified_by_id         = Column(Integer, ForeignKey("users.id"), nullable=True)
    security_certified_at            = Column(DateTime(timezone=True), nullable=True)
    security_notes                   = Column(Text, nullable=True)

    # ── Release preparation / approval (maker-checker #1) ──
    prepared_by_id   = Column(Integer, ForeignKey("users.id"), nullable=True)
    prepared_at       = Column(DateTime(timezone=True), nullable=True)
    approved_by_id    = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at       = Column(DateTime(timezone=True), nullable=True)
    rejected_by_id    = Column(Integer, ForeignKey("users.id"), nullable=True)
    rejected_at       = Column(DateTime(timezone=True), nullable=True)
    rejection_reason  = Column(Text, nullable=True)

    # ── Activation (maker-checker #2 — distinct from release approval) ──
    activated_by_id   = Column(Integer, ForeignKey("users.id"), nullable=True)
    activated_at      = Column(DateTime(timezone=True), nullable=True)

    # ── Rollback (Phase 8H: maker-checker #3, distinct from activation) —
    # never deletes/rewrites; see service.request_pap_rollback /
    # approve_pap_rollback / reject_pap_rollback. rollback_requested_by_id
    # must differ from rollback_approved_by_id, enforced in service.py,
    # the same minimum-viable pattern as every other maker-checker gate
    # in this file. ──
    rollback_requested_by_id  = Column(Integer, ForeignKey("users.id"), nullable=True)
    rollback_requested_at      = Column(DateTime(timezone=True), nullable=True)
    rollback_approved_by_id    = Column(Integer, ForeignKey("users.id"), nullable=True)
    rollback_approved_at        = Column(DateTime(timezone=True), nullable=True)
    rolled_back_by_id   = Column(Integer, ForeignKey("users.id"), nullable=True)
    rolled_back_at       = Column(DateTime(timezone=True), nullable=True)
    rollback_reason      = Column(Text, nullable=True)
    previous_release_id  = Column(Integer, ForeignKey("payroll_germany_pap_releases.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_pap_release_status", "status"),
        # DB-level backstop (Phase 8H) for "at most one ACTIVE release per
        # (country, tax_year)" — the exact same partial-unique-index
        # technique as PapAlgorithmAsset's uq_pap_asset_one_published_per_year,
        # with BOTH postgresql_where and sqlite_where from the start (Phase
        # 8E-2's F2 finding: a migration that only carries postgresql_where
        # silently becomes a full unique index under SQLite — this index is
        # authored correctly the first time).
        Index(
            "uq_pap_release_one_active_per_scope",
            "jurisdiction_country", "tax_year",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )

    def __repr__(self):
        return f"<GermanyPapRelease id={self.id} pap_asset_id={self.pap_asset_id} status={self.status}>"


# ── Germany: Krankenkasse (Health Fund) Registry (ZP-TAX-DE-2026-001 §11) ─
# Configuration/registry foundation ONLY — no GKV contribution is
# calculated anywhere in this codebase as a result of this table (see
# docs/PHASE_4_GERMANY_HEALTH_FUND_REGISTRY_REPORT.md §3). Global Germany
# statutory configuration (no organization_id) — the same "describes a
# jurisdiction, not an org" model as JurisdictionPack/PapAlgorithmAsset,
# per this table's own spec section describing it as statutory config, not
# tenant data.
#
# Shape decision (see Phase 4 report §5 for the full reasoning): this is
# NOT modeled after LocalityDataset (a big *batch* import of many unrelated
# locality codes as one versioned unit) despite that being the precedent
# named when this table was requested — nothing in the spec suggests
# Krankenkassen are ingested as one giant batch, and §11's own field list
# (health_fund_id, fund_name, supplementary_rate_pct, effective dates,
# status) describes ONE FUND's OWN rate timeline. That shape — a stable
# identity with an effective-dated version history — is EmployeeStatutory-
# Profile's (Phase 2) shape, not LocalityDataset's or PapAlgorithmAsset's:
# multiple historical/current/future PUBLISHED rows for the SAME
# health_fund_id must all remain independently resolvable by date (spec
# §22: "payroll must resolve exactly one applicable rate per contribution
# period" — a genuine retro/historical-lookup requirement, not just "the
# current rate"), unlike PapAlgorithmAsset's deliberate choice (Phase 3) to
# make only the single currently-PUBLISHED version resolvable. Overlap
# prevention therefore reuses EmployeeStatutoryProfile's general
# range-overlap check (Phase 2 pattern), not PapAlgorithmAsset's
# single-active-slot-with-manual-supersession pattern — while the
# maker-checker / publish gate itself still reuses PapAlgorithmAsset's
# exact "distinct approver required" logic, since that principle is
# identity-shape-independent.
class GermanyHealthFund(Base):
    """One effective-dated version of one Krankenkasse's Zusatzbeitrag
    (supplementary contribution) rate and registry metadata.

    `supplementary_rate_pct` is the FULL applicable rate — spec §11 is
    explicit ("not employee half") and §5's PAP-input table (KVZ) states
    "PAP handles employee/employer split" — so this table deliberately has
    no employee/employer split columns, unlike ContributionRate's
    convention; splitting is the future PAP executor's job, not this
    registry's.
    """
    __tablename__ = "payroll_germany_health_funds"

    id                       = Column(Integer, primary_key=True, index=True)

    # Stable across this fund's own version history — NOT unique alone
    # (multiple effective-dated rows share it by design); see __table_args__.
    health_fund_id           = Column(String(50), nullable=False, index=True)
    fund_name                = Column(String(200), nullable=False)

    # Full Zusatzbeitrag rate (spec §11 "not employee half"). Required:
    # this registry's entire purpose is holding this value — there is no
    # meaningful DRAFT row without one.
    supplementary_rate_pct   = Column(Numeric(6, 4), nullable=False)
    # True only for the statutory national-average reference case (spec's
    # own "AVERAGE RATE WARNING": 2.9% is a designated-case figure, never a
    # silent universal default). Application code must never branch on
    # "no fund resolved, use 2.9%" — see Phase 4 report §3/§22 Q5.
    is_average_rate          = Column(Boolean, nullable=False, default=False, server_default="false")

    # Phase 8U — U1 (sickness reimbursement) / U2 (maternity) levy rates,
    # spec §14/DE-D06: "U1 and U2 are generally health-fund/tariff
    # specific" — each Krankenkasse sets its own U1/U2 percentages for its
    # own insured employers' payroll, the SAME "fund publishes its own
    # rate" shape as supplementary_rate_pct above (not a national/average
    # rate). Both nullable: a fund's own U1/U2 rates are frequently not
    # yet known/published even when its Zusatzbeitrag is — NULL here means
    # exactly that ("not yet configured for this fund"), never 0%; the
    # calculation layer (germany_pap) must treat NULL as NOT_CONFIGURED,
    # never as "this fund charges nothing."
    u1_rate_pct               = Column(Numeric(6, 4), nullable=True)
    u2_rate_pct               = Column(Numeric(6, 4), nullable=True)

    effective_from            = Column(Date, nullable=False)
    effective_to              = Column(Date, nullable=True)   # NULL = open-ended / current

    # DRAFT | VERIFIED | APPROVED | PUBLISHED | SUPERSEDED — this EXACT
    # vocabulary is spec §11's own status row for this registry
    # (deliberately NOT PapAlgorithmAsset's DRAFT/REVIEW/APPROVED/
    # PUBLISHED/SUPERSEDED — "VERIFIED" replaces "REVIEW" here because the
    # supplied documentation says so for this specific table, not because
    # of any general platform convention).
    status                    = Column(String(20), nullable=False, default="DRAFT", server_default="DRAFT")

    # "Employee coverage/membership relation" (spec §11) — the supplied
    # documentation names this concept but defines no enumerated value
    # set, so this is free text, not an invented enum (see Phase 4 report
    # §4 — NOT SPECIFIED IN PROVIDED GERMANY DOCUMENTATION beyond the
    # concept's existence).
    member_applicability      = Column(String(200), nullable=True)
    # "Effective-date and retro rules for fund changes" (spec §11) — same
    # free-text treatment and same limitation as member_applicability.
    payroll_recalc_policy     = Column(String(200), nullable=True)

    # Evidence: reuses SourceArtifact — no separate checksum/hash column
    # exists on this table at all. Unlike PapAlgorithmAsset (which hashes
    # an actual ingested document's bytes), a health-fund rate has no
    # "content" of its own to hash — its integrity comes entirely from
    # citing an existing, independently-created SourceArtifact row (via
    # the existing /compliance/source-artifacts endpoint), never from a
    # caller-supplied value on THIS table. See Phase 4 report §6/§9.
    authority_source_id       = Column(Integer, ForeignKey("payroll_source_artifacts.id"), nullable=True)

    created_by_id             = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by_id             = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_by_id            = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Version chain — never overwritten. Distinct from "another row with a
    # non-overlapping later effective_from," which needs no chain pointer
    # at all (both are simply independently resolvable); this is only set
    # when a row is an explicit correction of another (see SUPERSEDED
    # usage in the Phase 4 report §10).
    previous_version_id       = Column(Integer, ForeignKey("payroll_germany_health_funds.id"), nullable=True)

    created_at                = Column(DateTime(timezone=True), server_default=func.now())
    updated_at                = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_health_fund_id_period", "health_fund_id", "effective_from"),
        # Same partial-unique-index technique as EmployeeStatutoryProfile's
        # one-open-row guard — at most one open-ended (still current) row
        # per fund at a time. Full overlap prevention across ALL rows
        # (open or closed) for a fund is enforced at the service layer
        # (mirroring EmployeeStatutoryProfile's approach), since a general
        # range-overlap DB constraint isn't available consistently across
        # this project's Postgres/SQLite dev-fallback targets.
        Index(
            "uq_health_fund_one_open_period",
            "health_fund_id",
            unique=True,
            postgresql_where=text("effective_to IS NULL"),
            sqlite_where=text("effective_to IS NULL"),
        ),
    )

    def __repr__(self):
        return (
            f"<GermanyHealthFund id={self.id} fund={self.health_fund_id!r} "
            f"rate={self.supplementary_rate_pct} status={self.status}>"
        )


# ── Germany: U1 Tariff (Sickness Reimbursement) (ZP-TAX-DE-2026-001 §14) ──
# Phase 8W. U1 is employer-elected per tariff — each Krankenkasse publishes
# multiple U1 tariff options (different reimbursement percentages and
# corresponding levy rates). The employer selects one tariff for their
# employees at that fund. This child table of GermanyHealthFund stores the
# AVAILABLE tariffs; the employer's SELECTED tariff is recorded on
# EmployeeStatutoryProfile.de_u1_tariff_id.
#
# Pre-Phase 8W behavior: GermanyHealthFund.u1_rate_pct held a single
# nullable rate — NULL meant "not yet configured" and the calculation engine
# treated it as NOT_CONFIGURED. That column is retained for backward
# compatibility but is DEPRECATED in production resolution — the engine now
# resolves from this child table via EmployeeStatutoryProfile.de_u1_tariff_id.
#
# Each row represents one tariff option for one fund in one effective period:
#   (health_fund_id, tariff_identifier, effective_from)
#
# Overlap prevention: two rows for the same fund+tariff must not have
# overlapping effective periods. Different tariffs for the same fund do NOT
# conflict (they represent independent options the employer may choose from).
#
# Lifecycle: DRAFT -> VERIFIED -> APPROVED -> PUBLISHED -> SUPERSEDED,
# identical to GermanyHealthFund and every other Germany registry. Same
# maker-checker enforcement: distinct approver + linked source required
# before PUBLISHED.
class GermanyHealthFundU1Tariff(Base):
    """One effective-dated version of one U1 (sickness reimbursement) tariff
    offered by one Krankenkasse.

    Each Krankenkasse publishes multiple U1 tariff options — the employer
    selects which tariff applies to their employees at that fund. The tariff
    determines both the employer's reimbursement percentage (what the fund
    reimburses for sick pay) and the corresponding levy rate (what the
    employer pays into the U1 fund as a percentage of gross wages).

    `reimbursement_pct` is the percentage of sick-pay costs reimbursed by
    the fund (e.g. 50, 70, 80 for TK). `levy_rate_pct` is the
    corresponding percentage of gross wages the employer pays as a U1 levy
    (e.g. 1.3, 2.1, 3.2 for TK). Both are stored as independently
    ingested statutory values — the levy rate is NOT derived from the
    reimbursement percentage; it is a separate published figure per fund.

    `tariff_identifier` is a stable code for this tariff within the fund's
    own version history (e.g. "U1_50", "U1_70", "U1_80"). Not unique alone
    (multiple effective-dated rows share it); see __table_args__."""
    __tablename__ = "payroll_germany_health_fund_u1_tariffs"

    id                       = Column(Integer, primary_key=True, index=True)

    # FK to GermanyHealthFund — identifies which Krankenkasse this tariff
    # belongs to. Uses the stable health_fund_id code (e.g. "TK"), NOT the
    # auto-increment PK, matching GermanyHealthFund's own identity convention.
    health_fund_id           = Column(String(50), nullable=False, index=True)

    # Stable tariff code within this fund (e.g. "U1_50", "U1_70", "U1_80").
    # Combined with health_fund_id and effective_from to form the effective
    # identity.
    tariff_identifier        = Column(String(50), nullable=False, index=True)

    # Human-readable tariff name (e.g. "50% Erstattungssatz")
    tariff_name              = Column(String(200), nullable=True)

    # Reimbursement percentage — the percentage of sick-pay costs the fund
    # reimburses to the employer (spec §14).
    reimbursement_pct        = Column(Numeric(6, 4), nullable=False)

    # U1 levy rate — the percentage of gross wages the employer pays into
    # the U1 fund (spec §14). This is the rate used in the calculation
    # engine's U1 computation.
    levy_rate_pct            = Column(Numeric(6, 4), nullable=False)

    effective_from           = Column(Date, nullable=False)
    effective_to             = Column(Date, nullable=True)   # NULL = open-ended / current

    # DRAFT | VERIFIED | APPROVED | PUBLISHED | SUPERSEDED — identical
    # vocabulary to GermanyHealthFund (spec §11).
    status                   = Column(String(20), nullable=False, default="DRAFT", server_default="DRAFT")

    # Evidence: reuses SourceArtifact — same pattern as every other Germany
    # registry. The source must specifically establish this tariff's rates,
    # not merely cite the fund generally.
    authority_source_id      = Column(Integer, ForeignKey("payroll_source_artifacts.id"), nullable=True)

    created_by_id            = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by_id            = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_by_id           = Column(Integer, ForeignKey("users.id"), nullable=True)
    previous_version_id      = Column(Integer, ForeignKey("payroll_germany_health_fund_u1_tariffs.id"), nullable=True)

    created_at               = Column(DateTime(timezone=True), server_default=func.now())
    updated_at               = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_u1_tariff_fund_tariff_period", "health_fund_id", "tariff_identifier", "effective_from"),
        # At most one open-ended row per (health_fund_id, tariff_identifier)
        # pair. Full overlap prevention across ALL rows for the same pair is
        # enforced at the service layer (same reasoning as GermanyHealthFund /
        # EmployeeStatutoryProfile).
        Index(
            "uq_u1_tariff_one_open_period",
            "health_fund_id", "tariff_identifier",
            unique=True,
            postgresql_where=text("effective_to IS NULL"),
            sqlite_where=text("effective_to IS NULL"),
        ),
    )

    def __repr__(self):
        return (
            f"<GermanyHealthFundU1Tariff id={self.id} fund={self.health_fund_id!r} "
            f"tariff={self.tariff_identifier!r} levy={self.levy_rate_pct} status={self.status}>"
        )


# ── Germany: Contribution Ceiling Configuration (ZP-TAX-DE-2026-001 §9) ──
# Configuration/registry foundation ONLY — no GKV/PV/RV/ALV contribution is
# calculated anywhere in this codebase as a result of this table (see
# docs/PHASE_5_GERMANY_CONTRIBUTION_CEILING_CONFIGURATION_REPORT.md §15/§24).
#
# Exists because Phase 1 found, and Phase 4 re-confirmed, that
# engine/countries/germany.py reads exactly ONE shared "contribution_ceiling"
# ContributionRate row (component_key="contribution_ceiling") and applies it
# to BOTH its "pension" and "social-insurance" buckets — but spec §9 gives
# TWO independent ceilings: RV/ALV (€8,450/month, €101,400/year) and
# GKV/PV (€5,812.50/month, €69,750/year). This table is the correct,
# branch-aware replacement DATA MODEL for a future calculation phase to
# consume — germany.py's existing single-ceiling read is UNCHANGED and
# does NOT read from this table (deliberately — see the report's
# "Compatibility" section for why the old component_key is left alone
# rather than migrated in this phase).
#
# Deliberately its own table, NOT a new ContributionRate.component_key
# value and NOT a modification to that model — a ContributionRate row is
# one flat/percentage value per jurisdiction with no branch-applicability
# concept of its own; retrofitting branch-awareness onto that shared,
# multi-country model would risk every other country's contribution rows,
# for zero benefit (no other country's ceiling concept needs a "branch"
# dimension). A small, dedicated, additive table is lower-risk and keeps
# Germany's real requirement (two named branches, each independently
# resolvable and historically reproducible) explicit rather than implicit
# in a generic key-value row.
#
# Shape/lifecycle decision: matches GermanyHealthFund (Phase 4), not
# PapAlgorithmAsset (Phase 3) — a contribution branch's ceiling changes
# year over year (or mid-year), and every such period must remain
# independently resolvable for historical/retro payroll (the same
# reasoning Phase 4 documented for health-fund rates), so overlap
# prevention is a full range check across a branch's own version history,
# not a single-active-slot-with-manual-supersession model. Status
# vocabulary is GermanyHealthFund's own spec-given vocabulary
# (DRAFT/VERIFIED/APPROVED/PUBLISHED/SUPERSEDED, spec §11) reused here as
# the closest spec-given vocabulary for this same general "Social
# Insurance rates and ceilings" configuration area (spec §18) — the spec
# gives no separate, distinct vocabulary for contribution ceilings
# specifically (NOT SPECIFIED IN PROVIDED GERMANY DOCUMENTATION beyond
# the general Social Insurance area), so reusing the nearest analogous
# spec-given vocabulary was judged more faithful than either inventing a
# third one or defaulting to PapAlgorithmAsset's "REVIEW"-based vocabulary
# for an unrelated document-asset concept.
class GermanyContributionCeiling(Base):
    """One effective-dated version of one contribution branch's monthly +
    annual contribution assessment ceiling.

    `branch` is one of exactly two values (spec §9 groups four programs
    into two shared-ceiling pairs — "GKV_PV" and "RV_ALV" — no finer
    subdivision is specified anywhere in the supplied documentation, so
    none is modeled). `monthly_ceiling`/`annual_ceiling` are BOTH stored
    as independently-ingested statutory values, never derived from one
    another — spec §9 supplies both explicitly for each branch, and
    deriving one from the other would risk silent drift from the actual
    published figures in a year where the relationship isn't a clean x12
    (2026's own figures happen to be exact multiples: 5,812.50 x 12 =
    69,750.00 and 8,450 x 12 = 101,400 — verified by the boundary tests in
    this phase — but nothing in the architecture assumes this holds for
    every future year)."""
    __tablename__ = "payroll_germany_contribution_ceilings"

    id                    = Column(Integer, primary_key=True, index=True)

    # "GKV_PV" | "RV_ALV" — validated in the service layer (see
    # _GERMANY_CONTRIBUTION_BRANCHES), not a DB CHECK constraint, matching
    # this codebase's existing convention for status/enum-like string
    # columns (e.g. JurisdictionPack.status, TaxSlab.rule_type).
    branch                = Column(String(20), nullable=False, index=True)

    monthly_ceiling        = Column(Numeric(12, 2), nullable=False)
    annual_ceiling         = Column(Numeric(12, 2), nullable=False)

    effective_from         = Column(Date, nullable=False)
    effective_to           = Column(Date, nullable=True)   # NULL = open-ended / current

    # DRAFT | VERIFIED | APPROVED | PUBLISHED | SUPERSEDED — see this
    # table's own header comment for why this (GermanyHealthFund's)
    # vocabulary was reused rather than PapAlgorithmAsset's.
    status                 = Column(String(20), nullable=False, default="DRAFT", server_default="DRAFT")

    # Evidence: reuses SourceArtifact exactly as GermanyHealthFund does —
    # no separate checksum field on this table either (a ceiling figure,
    # like a fund rate, has no "content" of its own to hash; see the
    # Phase 5 report §11 for why this table inherits the same, disclosed
    # limitation as Phase 4's create_source_artifact dependency).
    authority_source_id    = Column(Integer, ForeignKey("payroll_source_artifacts.id"), nullable=True)

    created_by_id          = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by_id          = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_by_id         = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Version chain — reserved for an explicit correction of an
    # erroneously published row (see SUPERSEDED usage in the Phase 5
    # report), not for ordinary year-to-year ceiling changes, which are
    # simply additional independent rows — same convention as
    # GermanyHealthFund.previous_version_id.
    previous_version_id    = Column(Integer, ForeignKey("payroll_germany_contribution_ceilings.id"), nullable=True)

    created_at             = Column(DateTime(timezone=True), server_default=func.now())
    updated_at             = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_contribution_ceiling_branch_period", "branch", "effective_from"),
        # Same partial-unique-index technique as GermanyHealthFund's/
        # EmployeeStatutoryProfile's one-open-row guard — at most one
        # open-ended (still current) row per branch at a time. Full
        # overlap prevention across ALL rows (open or closed) for a
        # branch is enforced at the service layer, same reasoning as
        # those two tables.
        Index(
            "uq_contribution_ceiling_one_open_period",
            "branch",
            unique=True,
            postgresql_where=text("effective_to IS NULL"),
            sqlite_where=text("effective_to IS NULL"),
        ),
    )

    def __repr__(self):
        return (
            f"<GermanyContributionCeiling id={self.id} branch={self.branch!r} "
            f"monthly={self.monthly_ceiling} annual={self.annual_ceiling} status={self.status}>"
        )


# ── Germany: PV (Long-Term Care Insurance) Child/Saxony Configuration ────
# ZP-TAX-DE-2026-001 §10 — Configuration/registry foundation ONLY. No PV
# contribution is calculated anywhere in this codebase as a result of this
# table. The supplied Germany documentation specifies that PV rates are:
#   - child-sensitive (different for childless vs 1..5+ qualifying children)
#   - have different employee/employer allocation in Saxony
#   - subject to the GKV/PV contribution ceiling (Phase 5)
#   - effective-dated statutory configuration
#
# Each row represents one independent PV configuration track identified by:
#   (child_category, is_saxony, effective period)
#
# Overlap prevention: two rows with the same (child_category, is_saxony)
# must not have overlapping effective periods. Independent child-category
# tracks and independent Saxony/non-Saxony tracks do NOT conflict.
#
# Deliberately its own table, NOT a modification to ContributionRate or
# GermanyContributionCeiling — those models have no child-category dimension
# and adding one would risk every other country's contribution rows. A small,
# dedicated, additive table is lower-risk and keeps Germany's real
# requirement (six child categories × two Saxony variants = twelve
# independent rate configurations, each independently resolvable by date)
# explicit rather than implicit.
#
# Shape/lifecycle decision: matches GermanyContributionCeiling (Phase 5) and
# GermanyHealthFund (Phase 4). Same reasoning applies: every PV rate version
# — past, current, or future — must remain independently resolvable for
# historical/retro payroll. Status vocabulary is spec §11's own
# DRAFT/VERIFIED/APPROVED/PUBLISHED/SUPERSEDED, reused here.
#
# Ceiling relationship: this table stores RATES ONLY. The contribution
# ceiling (GKV_PV branch, Phase 5 GermanyContributionCeiling) is resolved
# SEPARATELY by a future calculation engine. No ceiling value is duplicated
# here. See Phase 6 report §14 for the intended future integration.
class GermanyPvConfiguration(Base):
    """One effective-dated version of one child-category × Saxony PV rate
    configuration.

    `child_category` is one of exactly six values specified by the supplied
    Germany documentation: CHILDLESS, 1, 2, 3, 4, 5_PLUS. CHILDLESS is
    explicit (not child_count=0) because the childless rate is materially
    different (higher total rate, different employee/employer allocation).

    All five rate columns are stored independently as explicitly supplied
    statutory values — none is derived from another. This preserves
    statutory evidence rather than assuming arithmetic derivation is always
    safe (the employer rate is identical across all categories in the 2026
    documentation, but this is not architecturally assumed)."""
    __tablename__ = "payroll_germany_pv_configurations"

    id                    = Column(Integer, primary_key=True, index=True)

    # Child category — validated in service layer against
    # _GERMANY_PV_CHILD_CATEGORIES, not a DB CHECK constraint, matching
    # this codebase's convention for enum-like string columns.
    child_category        = Column(String(20), nullable=False, index=True)

    # Saxony applicability — True for Saxony-specific allocation,
    # False for standard (all other German states).
    is_saxony             = Column(Boolean, nullable=False, default=False, server_default="false")

    # Statutory PV rates — all independently preserved (see docstring).
    # Numeric(6,4) matches GermanyHealthFund.supplementary_rate_pct's
    # precision, sufficient for percentage values up to 99.9999%.
    total_rate_pct                    = Column(Numeric(6, 4), nullable=False)
    standard_employee_rate_pct        = Column(Numeric(6, 4), nullable=False)
    employer_rate_pct                 = Column(Numeric(6, 4), nullable=False)
    saxony_employee_rate_pct          = Column(Numeric(6, 4), nullable=False)
    saxony_employer_rate_pct          = Column(Numeric(6, 4), nullable=False)

    effective_from         = Column(Date, nullable=False)
    effective_to           = Column(Date, nullable=True)   # NULL = open-ended / current

    # DRAFT | VERIFIED | APPROVED | PUBLISHED | SUPERSEDED — spec §11's
    # vocabulary, reused identically to GermanyHealthFund/GermanyContributionCeiling.
    status                 = Column(String(20), nullable=False, default="DRAFT", server_default="DRAFT")

    # Evidence: reuses SourceArtifact — same pattern as GermanyHealthFund
    # and GermanyContributionCeiling.
    authority_source_id    = Column(Integer, ForeignKey("payroll_source_artifacts.id"), nullable=True)

    created_by_id          = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by_id          = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_by_id         = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Version chain — reserved for an explicit correction of an
    # erroneously published row (see SUPERSEDED usage in the Phase 6
    # report), not for ordinary year-to-year rate changes, which are
    # simply additional independent rows.
    previous_version_id    = Column(Integer, ForeignKey("payroll_germany_pv_configurations.id"), nullable=True)

    created_at             = Column(DateTime(timezone=True), server_default=func.now())
    updated_at             = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_pv_config_child_saxony_period", "child_category", "is_saxony", "effective_from"),
        # At most one open-ended (still current) row per
        # (child_category, is_saxony) pair. Full overlap prevention
        # across ALL rows for the same pair is enforced at the service
        # layer (same reasoning as GermanyHealthFund /
        # GermanyContributionCeiling / EmployeeStatutoryProfile).
        Index(
            "uq_pv_config_one_open_period",
            "child_category", "is_saxony",
            unique=True,
            postgresql_where=text("effective_to IS NULL"),
            sqlite_where=text("effective_to IS NULL"),
        ),
    )

    def __repr__(self):
        return (
            f"<GermanyPvConfiguration id={self.id} child={self.child_category!r} "
            f"saxony={self.is_saxony} total={self.total_rate_pct} status={self.status}>"
        )


# ── Germany: Earning/Deduction Taxability (ZP-TAX-DE-2026-001 §15) ──────
# Phase 8T. Every Germany earning/deduction type must independently
# declare FOUR dimensions — spec's own "FOUR-DIMENSION TAXABILITY" callout:
# "wage-tax treatment, health/care contribution treatment, pension/
# unemployment treatment, and reporting classification. 'Taxable yes/no'
# is insufficient for German payroll." This is NOT the existing
# TaxabilityRule model (models.py, US-oriented, a single is_taxable
# boolean per (earning_type, tax_component) pair, confirmed unused
# anywhere in this codebase) — that model's shape cannot represent four
# independent, Germany-specific dimensions on one row, and retrofitting it
# would risk every other country's use of that name. A small, dedicated,
# additive table mirrors this module's own established pattern
# (GermanyHealthFund/GermanyContributionCeiling/GermanyPvConfiguration all
# made the identical "own table, not a retrofit" choice for the same
# reason).
#
# `earning_type` values are the exact 9 rows from spec §15's own taxability
# matrix table (REGULAR_SALARY, OVERTIME_SHIFT_PREMIUM, BONUS_ANNUAL_BONUS,
# PENSION_VERSORGUNGSBEZUG, EQUITY_BENEFIT_19A, EXPENSE_REIMBURSEMENT,
# OCCUPATIONAL_PENSION_CONTRIBUTION, GARNISHMENT_ATTACHMENT,
# EMPLOYEE_VOLUNTARY_DEDUCTION) — validated in the service layer against
# _GERMANY_EARNING_TYPES, not a DB CHECK constraint, matching this
# codebase's convention for enum-like string columns. No 10th type is
# invented; if Zoiko later needs an earning type the spec doesn't name,
# that is out of this table's scope until the spec is amended.
class GermanyEarningTaxabilityRule(Base):
    """One effective-dated version of one earning/deduction type's
    four-dimension Germany taxability classification.

    `wage_tax_treatment`, `gkv_pv_treatment`, and `rv_alv_treatment` are
    each one of a small, spec-derived vocabulary (see
    _GERMANY_WAGE_TAX_TREATMENTS / _GERMANY_SI_TREATMENTS in service.py) —
    genuinely independent columns, never collapsed into one taxable/
    non-taxable flag (spec's own explicit prohibition). `reporting_
    classification` is free text: spec names "reporting classification"
    as the fourth dimension but gives no enumerated value set for it
    anywhere (only a free-text "Notes / router" column in the same
    table) — inventing an enum the spec doesn't supply would misrepresent
    an unspecified classification as a settled one."""
    __tablename__ = "payroll_germany_earning_taxability_rules"

    id                       = Column(Integer, primary_key=True, index=True)

    earning_type             = Column(String(50), nullable=False, index=True)

    wage_tax_treatment        = Column(String(30), nullable=False)
    gkv_pv_treatment           = Column(String(40), nullable=False)
    rv_alv_treatment           = Column(String(40), nullable=False)
    reporting_classification  = Column(Text, nullable=True)

    effective_from         = Column(Date, nullable=False)
    effective_to           = Column(Date, nullable=True)   # NULL = open-ended / current

    # DRAFT | VERIFIED | APPROVED | PUBLISHED | SUPERSEDED — spec §11's
    # vocabulary, reused identically to every other Germany registry.
    status                 = Column(String(20), nullable=False, default="DRAFT", server_default="DRAFT")

    # Evidence: reuses SourceArtifact — same pattern as every other
    # Germany registry (Source Lock enforced at the service layer before
    # PUBLISHED, exactly like set_health_fund_status/set_contribution_
    # ceiling_status/set_pv_configuration_status).
    authority_source_id    = Column(Integer, ForeignKey("payroll_source_artifacts.id"), nullable=True)

    created_by_id          = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by_id          = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_by_id         = Column(Integer, ForeignKey("users.id"), nullable=True)
    previous_version_id    = Column(Integer, ForeignKey("payroll_germany_earning_taxability_rules.id"), nullable=True)

    created_at             = Column(DateTime(timezone=True), server_default=func.now())
    updated_at             = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_earning_taxability_type_period", "earning_type", "effective_from"),
        # At most one open-ended (still current) row per earning_type.
        # Full overlap prevention across ALL rows for the same type is
        # enforced at the service layer (same reasoning as every other
        # Germany registry in this module).
        Index(
            "uq_earning_taxability_one_open_period",
            "earning_type",
            unique=True,
            postgresql_where=text("effective_to IS NULL"),
            sqlite_where=text("effective_to IS NULL"),
        ),
    )

    def __repr__(self):
        return (
            f"<GermanyEarningTaxabilityRule id={self.id} earning_type={self.earning_type!r} "
            f"status={self.status}>"
        )


# ── Germany: Overtime/Shift-Premium Statutory Registries (Phase 8AD) ─────
# The two GLOBAL statutory registries from Phase 8AA's ARCHITECTURE_D design
# (docs/PHASE_8AA_..._DATA_MODEL.md §11) — configuration ONLY. Neither table
# is tenant-scoped (no organization_id, exactly like GermanyContributionCeiling/
# GermanyPvConfiguration), neither holds employee data, a calculated amount,
# an overtime work record, or an executable formula. Shape mirrors
# GermanyContributionCeiling exactly (same lifecycle, same overlap/open-row
# guard, same SourceArtifact linkage) — deliberately NOT a new pattern.
# Consumption by the Germany calculation engine is explicitly OUT OF SCOPE
# for this phase (Phase 8AE/8AF/8AG) — engine/countries/germany.py does not
# reference either table.

class GermanyOvertimePremiumCategory(Base):
    """One effective-dated version of one statutory overtime/shift-premium
    category's wage-tax-free percentage (§3b EStG). Exactly the 5 categories
    Phase 8Z's fetched §3b EStG text distinguishes — no 6th invented."""
    __tablename__ = "payroll_germany_overtime_premium_categories"

    id                    = Column(Integer, primary_key=True, index=True)

    # NIGHT_STANDARD | NIGHT_EXTENDED | SUNDAY | HOLIDAY_STANDARD |
    # HOLIDAY_SPECIAL — validated in the service layer (see
    # _GERMANY_OVERTIME_PREMIUM_CATEGORIES), not a DB CHECK constraint,
    # matching this codebase's existing convention for enum-like columns.
    category_code         = Column(String(30), nullable=False, index=True)

    wage_tax_free_pct      = Column(Numeric(6, 2), nullable=False)

    effective_from         = Column(Date, nullable=False)
    effective_to           = Column(Date, nullable=True)   # NULL = open-ended / current

    status                 = Column(String(20), nullable=False, default="DRAFT", server_default="DRAFT")
    authority_source_id    = Column(Integer, ForeignKey("payroll_source_artifacts.id"), nullable=True)

    created_by_id          = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by_id          = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_by_id         = Column(Integer, ForeignKey("users.id"), nullable=True)
    previous_version_id    = Column(Integer, ForeignKey("payroll_germany_overtime_premium_categories.id"), nullable=True)

    created_at             = Column(DateTime(timezone=True), server_default=func.now())
    updated_at             = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_overtime_premium_category_period", "category_code", "effective_from"),
        Index(
            "uq_overtime_premium_category_one_open_period",
            "category_code",
            unique=True,
            postgresql_where=text("effective_to IS NULL"),
            sqlite_where=text("effective_to IS NULL"),
        ),
    )

    def __repr__(self):
        return (
            f"<GermanyOvertimePremiumCategory id={self.id} category_code={self.category_code!r} "
            f"wage_tax_free_pct={self.wage_tax_free_pct} status={self.status}>"
        )


class GermanyOvertimeGrundlohnCap(Base):
    """One effective-dated version of one dimension's statutory hourly
    Grundlohn cap (§3b EStG's €50/hour wage-tax cap; §1 Abs. 1 Satz 1 Nr. 1
    SvEV's €25/hour social-insurance cap). A SEPARATE table from
    GermanyOvertimePremiumCategory — these caps apply uniformly across ALL
    5 premium categories, not per-category (see the Phase 8AA report's own
    rejection of overloading GermanyContributionCeiling for this — same
    accidental shape, genuinely different statutory concept). NEVER an
    employee's actual hourly rate — see EmployeeStatutoryProfile.de_grundlohn_hourly
    (Phase 8AB) for that, a wholly separate column this table must never be
    confused with or fed into directly."""
    __tablename__ = "payroll_germany_overtime_grundlohn_caps"

    id                    = Column(Integer, primary_key=True, index=True)

    # WAGE_TAX | SOCIAL_INSURANCE — validated in the service layer (see
    # _GERMANY_OVERTIME_GRUNDLOHN_DIMENSIONS).
    dimension              = Column(String(20), nullable=False, index=True)

    hourly_cap_amount      = Column(Numeric(10, 2), nullable=False)

    effective_from         = Column(Date, nullable=False)
    effective_to           = Column(Date, nullable=True)   # NULL = open-ended / current

    status                 = Column(String(20), nullable=False, default="DRAFT", server_default="DRAFT")
    authority_source_id    = Column(Integer, ForeignKey("payroll_source_artifacts.id"), nullable=True)

    created_by_id          = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by_id          = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_by_id         = Column(Integer, ForeignKey("users.id"), nullable=True)
    previous_version_id    = Column(Integer, ForeignKey("payroll_germany_overtime_grundlohn_caps.id"), nullable=True)

    created_at             = Column(DateTime(timezone=True), server_default=func.now())
    updated_at             = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_overtime_grundlohn_cap_period", "dimension", "effective_from"),
        Index(
            "uq_overtime_grundlohn_cap_one_open_period",
            "dimension",
            unique=True,
            postgresql_where=text("effective_to IS NULL"),
            sqlite_where=text("effective_to IS NULL"),
        ),
    )

    def __repr__(self):
        return (
            f"<GermanyOvertimeGrundlohnCap id={self.id} dimension={self.dimension!r} "
            f"hourly_cap_amount={self.hourly_cap_amount} status={self.status}>"
        )


class LocalityDataset(Base):
    """A signed, versioned import of official local-tax jurisdiction codes
    (county/municipal/school-district/PSD) for one state — the standard's
    "Locality Dataset Manager" concept. Distinct from a single ContributionRate/
    TaxSlab row because a real locality dataset is thousands of rows imported
    as a unit, diffed/staged/approved/activated together, not hand-typed."""
    __tablename__ = "payroll_locality_datasets"

    id                    = Column(Integer, primary_key=True, index=True)
    jurisdiction_country  = Column(String(10), nullable=False)   # "US"
    jurisdiction_state    = Column(String(100), nullable=False)  # "PA", "OH", "IN"
    version               = Column(String(50), nullable=False)
    status                = Column(String(20), nullable=False, default="Draft", server_default="Draft")
    # Draft | Staged | Active | Retired — mirrors JurisdictionPack's
    # lifecycle vocabulary; only one Active dataset per (country, state)
    # should be enforced at the service layer, same pattern as
    # JurisdictionPack's tax-pack overlap guard.
    source_document_id   = Column(Integer, ForeignKey("payroll_source_artifacts.id"), nullable=True)
    checksum_sha256       = Column(String(64), nullable=True)
    effective_from        = Column(Date, nullable=True)
    effective_to          = Column(Date, nullable=True)
    imported_by_id        = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_by_id         = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at             = Column(DateTime(timezone=True), server_default=func.now())

    rates = relationship("LocalityRate", back_populates="dataset", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<LocalityDataset id={self.id} state={self.jurisdiction_state} v{self.version} status={self.status}>"


class LocalityRate(Base):
    """One local-tax rate row within a LocalityDataset version — e.g. one
    Pennsylvania PSD code's resident/nonresident EIT + LST, or one Ohio
    municipality's income-tax rate."""
    __tablename__ = "payroll_locality_rates"

    id                    = Column(Integer, primary_key=True, index=True)
    locality_dataset_id   = Column(Integer, ForeignKey("payroll_locality_datasets.id"), nullable=False, index=True)
    locality_code         = Column(String(20), nullable=False)   # PA 6-digit PSD code, OH municipality ID, IN county code
    locality_type         = Column(String(30), nullable=False)   # COUNTY | MUNICIPAL | SCHOOL_DISTRICT | PSD_EIT_LST
    locality_name         = Column(String(200), nullable=True)
    resident_rate_pct     = Column(Numeric(6, 4), nullable=True)
    nonresident_rate_pct  = Column(Numeric(6, 4), nullable=True)
    flat_amount           = Column(Numeric(12, 2), nullable=True)   # for LST-style flat local taxes
    tax_collector_id      = Column(String(100), nullable=True)      # remittance routing destination

    dataset = relationship("LocalityDataset", back_populates="rates")

    __table_args__ = (
        UniqueConstraint("locality_dataset_id", "locality_code", name="uq_locality_rate_dataset_code"),
    )

    def __repr__(self):
        return f"<LocalityRate id={self.id} code={self.locality_code} type={self.locality_type}>"


class EmployerTaxProfile(Base):
    """Tenant-specific, agency-assigned rate (State Unemployment Insurance
    and similar experience-rated assessments). Deliberately NOT a
    ContributionRate row: a ContributionRate override is an org's own policy
    choice (e.g. a different PF %), but a SUI rate is a statutory fact
    assigned to this specific employer by a government agency, with its own
    account number and evidence trail — conflating the two would make it
    impossible to tell "the org chose this" from "the state mandated this."
    """
    __tablename__ = "payroll_employer_tax_profiles"

    id                    = Column(Integer, primary_key=True, index=True)
    organization_id       = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    jurisdiction_id        = Column(String(10), nullable=False)   # "US-CA", "US-NJ", "US-DC"
    # "SUI" | "ETT" | "WF" | "JDA" | "FAMLI" | "PFML" | "PAID_LEAVE" (the
    # last three: a headcount-only row for a statutory-rate program whose
    # EMPLOYER share is conditional on this employer's own covered
    # headcount, ZP-TAX-US-2026-001 §5 — e.g. Colorado FAMLI's 10-employee
    # threshold. taxable_wage_base/employer_rate_pct are widened to
    # nullable below specifically so a row can exist for this purpose
    # ALONE, without inventing a meaningless SUI-style rate/wage-base just
    # to satisfy a NOT NULL constraint.
    component_code         = Column(String(20), nullable=False)
    # Widened from NOT NULL: a headcount-only row (see component_code
    # comment above) has neither a real wage base nor an employer-assigned
    # rate — those are looked up from the canonical state-program
    # ContributionRate rows instead (same as every other state program).
    # Every existing SUI-style row keeps its real value; nothing changes
    # for those.
    taxable_wage_base       = Column(Numeric(12, 2), nullable=True)
    # STATE_DEFAULT | NEW_EMPLOYER | EMPLOYER_NOTICE — provenance, per the
    # standard's §6.1: never infer an experience rate from prior payroll
    # deductions, only from an agency-issued notice or the state default.
    rate_source             = Column(String(20), nullable=False, default="STATE_DEFAULT", server_default="STATE_DEFAULT")
    employer_rate_pct       = Column(Numeric(6, 4), nullable=True)
    assessment_rate_pct     = Column(Numeric(6, 4), nullable=True)
    # Headcount-only purpose (see component_code comment above): how many
    # covered individuals this employer has for THIS jurisdiction+program,
    # as of effective_from — the one tenant-specific fact several 2026
    # state programs need (CO FAMLI's 10-employee threshold, Maine PFML's
    # 15, Washington PFML's 50) that no other table captures. Never
    # inferred from headcount/payroll history — a real Tax Ops entry,
    # same "never infer" principle as employer_rate_pct's own provenance
    # rule above. NULL for every existing SUI-style row.
    covered_employee_count  = Column(Integer, nullable=True)
    effective_from          = Column(Date, nullable=False)
    effective_to            = Column(Date, nullable=True)
    agency_account_id       = Column(String(100), nullable=True)   # tenant-specific; treat as sensitive
    source_document_id      = Column(Integer, ForeignKey("payroll_source_artifacts.id"), nullable=True)
    reimbursable_status      = Column(String(20), nullable=False, default="CONTRIBUTORY", server_default="CONTRIBUTORY")
    created_at               = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_employer_tax_profile_org_jur_comp", "organization_id", "jurisdiction_id", "component_code"),
    )

    def __repr__(self):
        return f"<EmployerTaxProfile org={self.organization_id} jur={self.jurisdiction_id} comp={self.component_code}>"


class GermanyAccidentInsuranceProfile(Base):
    """Phase 8AJ (2nd pass) — the maker-checker-gated DRAFT/VERIFIED/
    APPROVED/PUBLISHED workflow for one organization's German statutory
    accident insurance (Unfallversicherung), mirroring
    GermanyHealthFund/GermanyContributionCeiling's exact lifecycle
    vocabulary and version-chain shape.

    Deliberately a SEPARATE table from EmployerTaxProfile, not a
    retrofit of it: EmployerTaxProfile is a shared, cross-jurisdiction
    mechanism (built for, and still used unmodified by, US SUI) with no
    lifecycle at all — adding one only for this table's Germany usage
    would inconsistently split its one existing consumer from a second,
    differently-behaved one. Instead, THIS table is the Super-Admin
    maker-checker workspace; publishing a row here (see
    service.set_germany_accident_insurance_profile_status) materializes
    the published values into a real EmployerTaxProfile row — the SAME
    row the Germany engine (engine/countries/germany.py) already reads
    via ctx.employer_tax_profiles["DE_ACCIDENT_INSURANCE"], unchanged.
    No engine code was modified to add this maker-checker layer.

    Organization-scoped (unlike every OTHER Germany registry, all
    global) because accident insurance is carrier/employer-specific by
    statutory design (DE-D06) — there is no national rate to publish
    once for every employer.
    """
    __tablename__ = "payroll_germany_accident_insurance_profiles"

    id                      = Column(Integer, primary_key=True, index=True)
    organization_id         = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    # Berufsgenossenschaft / carrier identity — free text, since no
    # enumerated national list of carriers is defined in the supplied
    # documentation (not invented).
    carrier_name            = Column(String(200), nullable=False)
    # Employer's own membership/reference number with that carrier
    # (Mitgliedsnummer) — sensitive, tenant-specific, same treatment as
    # EmployerTaxProfile.agency_account_id.
    agency_account_id       = Column(String(100), nullable=True)
    # Gefahrtarifstelle / risk classification, when disclosed on the
    # employer's own notice — free text, no invented risk-class enum.
    risk_class_description  = Column(String(200), nullable=True)

    employer_rate_pct       = Column(Numeric(6, 4), nullable=False)
    effective_from          = Column(Date, nullable=False)
    effective_to            = Column(Date, nullable=True)   # NULL = open-ended / current

    # DRAFT | VERIFIED | APPROVED | PUBLISHED | SUPERSEDED — identical
    # vocabulary to GermanyHealthFund/GermanyContributionCeiling.
    status                  = Column(String(20), nullable=False, default="DRAFT", server_default="DRAFT")

    # Evidence: the employer's OWN annual notice (Beitragsbescheid),
    # recorded as a SourceArtifact like every other registry's evidence —
    # required before PUBLISH (see service layer), never optional for a
    # published row.
    authority_source_id     = Column(Integer, ForeignKey("payroll_source_artifacts.id"), nullable=True)

    created_by_id           = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by_id           = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_by_id          = Column(Integer, ForeignKey("users.id"), nullable=True)
    previous_version_id     = Column(Integer, ForeignKey("payroll_germany_accident_insurance_profiles.id"), nullable=True)

    created_at              = Column(DateTime(timezone=True), server_default=func.now())
    updated_at              = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_accident_insurance_profile_org_period", "organization_id", "effective_from"),
        # At most one open-ended (still current) row per organization at
        # a time — same partial-unique-index technique as
        # GermanyHealthFund's uq_health_fund_one_open_period.
        Index(
            "uq_accident_insurance_profile_one_open_period",
            "organization_id",
            unique=True,
            postgresql_where=text("effective_to IS NULL"),
            sqlite_where=text("effective_to IS NULL"),
        ),
    )

    def __repr__(self):
        return (
            f"<GermanyAccidentInsuranceProfile org={self.organization_id} carrier={self.carrier_name} "
            f"status={self.status}>"
        )


class GermanyChurchTaxException(Base):
    """Phase 8AM — a documented, SUB-LAND church-tax exception, additive
    on top of germany_pap.core.CHURCH_TAX_LAND_RATES (the ordinary,
    unchanged, Land-level general rate table).

    The supplied specification (ZP-TAX-DE-2026-001 §8) names exactly one
    concrete example — "preserve documented denomination/location
    exceptions such as the Roman Catholic treatment in Bad Wimpfen" —
    without giving a machine-readable rule (no rate, no scope, no
    schema). Fresh primary-source research this phase established the
    actual legal mechanism: Bad Wimpfen (Baden-Württemberg, postal code
    74206) falls within the Diocese of Mainz's church jurisdiction — an
    enclave of that Rhineland-Palatinate-headquartered diocese inside
    Baden-Württemberg, a consequence of 19th-century territorial
    history — and the Diocese applies ITS OWN 9% Kirchensteuer-Hebesatz
    (matching Rhineland-Palatinate's general rate) even to this BW
    enclave, instead of Baden-Württemberg's own general 8%. Confirmed
    current for 2026 (FinMin Baden-Württemberg Erlass v. 22.5.2026,
    FM3 - S 2442 - 3/38 — reputable professional-tax-publisher
    corroboration of the official circular's own operative text, Tier 2
    evidence per this project's own source hierarchy; NOT a direct
    fetch of the circular/Bundessteuerblatt itself, which is not freely
    accessible — see docs/PHASE_8AM_..._REPORT.md for the full
    evidence chain and this disclosed evidence-tier limitation),
    continuously re-confirmed by the SAME Land in annual circulars since
    the exception's 2016 origin (FinMin. Baden-Württemberg vom
    19.2.2016, BStBl. 2016 I S. 235).

    Deliberately a SEPARATE, additive table rather than a rewrite of
    CHURCH_TAX_LAND_RATES: the 16 general Land rates are already
    correctly Tier-1-sourced (the supplied Zoiko document itself) and
    read by a framework-agnostic, DB-free calculation module
    (germany_pap/core.py) — converting that whole mechanism into a
    database-backed registry would be a disproportionate, high-regression
    -risk rewrite for the sake of one documented exception. Instead, an
    exception row (when PUBLISHED and matching) OVERRIDES the general
    Land rate for the specific (Land, denomination, postal code)
    combination it names; every employee who does NOT match a PUBLISHED
    exception continues to resolve the ordinary, unchanged Land rate —
    proven by this phase's own regression tests.
    """
    __tablename__ = "payroll_germany_church_tax_exceptions"

    id                        = Column(Integer, primary_key=True, index=True)

    # Which Land's general rate this exception overrides — same
    # "DE-<ISO 3166-2>" convention as de_church_tax_land /
    # CHURCH_TAX_LAND_RATES's own keys.
    land_code                 = Column(String(6), nullable=False, index=True)
    # ROMAN_CATHOLIC|EVANGELICAL|OTHER — free text, matching
    # EmployeeStatutoryProfile.de_church_tax_denomination's own
    # documented reasoning (no invented exhaustive enum).
    denomination               = Column(String(30), nullable=False)
    # The deterministic geographic key — Bad Wimpfen's own postal code
    # (74206) for the one exception currently evidenced; a future
    # exception (if ever evidenced) would record its own postal code
    # here, never inferred.
    municipality_postal_code   = Column(String(10), nullable=False)
    # Human-readable description of the exception's legal/administrative
    # basis, for audit/UI display — e.g. "Bad Wimpfen — Diocese of Mainz
    # enclave in Baden-Württemberg".
    scope_description           = Column(String(300), nullable=True)

    exception_rate_pct         = Column(Numeric(5, 2), nullable=False)
    effective_from              = Column(Date, nullable=False)
    effective_to                = Column(Date, nullable=True)   # NULL = open-ended / current

    # DRAFT | VERIFIED | APPROVED | PUBLISHED | SUPERSEDED — identical
    # vocabulary to GermanyHealthFund/GermanyAccidentInsuranceProfile.
    status                      = Column(String(20), nullable=False, default="DRAFT", server_default="DRAFT")

    authority_source_id         = Column(Integer, ForeignKey("payroll_source_artifacts.id"), nullable=True)

    created_by_id                = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by_id                = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_by_id                = Column(Integer, ForeignKey("users.id"), nullable=True)
    previous_version_id           = Column(Integer, ForeignKey("payroll_germany_church_tax_exceptions.id"), nullable=True)

    created_at                    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at                    = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_church_tax_exception_scope", "land_code", "denomination", "municipality_postal_code"),
        # At most one open-ended (still current) row per exact
        # (Land, denomination, postal code) combination at a time — same
        # partial-unique-index technique as every other Germany registry.
        Index(
            "uq_church_tax_exception_one_open_period",
            "land_code", "denomination", "municipality_postal_code",
            unique=True,
            postgresql_where=text("effective_to IS NULL"),
            sqlite_where=text("effective_to IS NULL"),
        ),
    )

    def __repr__(self):
        return (
            f"<GermanyChurchTaxException land={self.land_code} denomination={self.denomination} "
            f"plz={self.municipality_postal_code} rate={self.exception_rate_pct} status={self.status}>"
        )


class TaxabilityRule(Base):
    """Per-earning-type x per-tax-component taxability, effective-dated.
    Platform-wide, not US-only — but every existing earning type/tax
    component combination should be seeded as is_taxable=True (matching
    today's "everything taxes everything" behavior) so no country's
    calculation changes until a genuinely differentiated row (e.g. a 401(k)
    deferral exempt from federal income tax but not from Social Security)
    is explicitly added. NULL organization_id = canonical/platform default."""
    __tablename__ = "payroll_taxability_rules"

    id                     = Column(Integer, primary_key=True, index=True)
    jurisdiction_country   = Column(String(10), nullable=False)
    jurisdiction_state     = Column(String(100), nullable=True)
    earning_type           = Column(String(50), nullable=False)   # "base_salary" | "401k_deferral" | "cafeteria_125" | ...
    tax_component          = Column(String(30), nullable=False)   # "federal_income_tax" | "social_security" | "medicare" | "futa" | "state_income_tax"
    is_taxable             = Column(Boolean, nullable=False, default=True, server_default="true")
    effective_from         = Column(Date, nullable=True)
    effective_to           = Column(Date, nullable=True)
    organization_id        = Column(Integer, ForeignKey("organizations.id"), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "jurisdiction_country", "jurisdiction_state", "earning_type", "tax_component", "organization_id",
            name="uq_taxability_rule_scope",
        ),
    )

    def __repr__(self):
        return f"<TaxabilityRule {self.earning_type}x{self.tax_component}={self.is_taxable}>"


class EmployeePreTaxDeductionElection(Base):
    """An employee's elected pre-tax deduction (401(k) deferral, Section 125
    cafeteria-plan contribution, etc.) — the concrete thing TaxabilityRule
    above needs to exist in order to have anything to apply differentiated
    taxability to. No such concept existed anywhere in the schema before
    this; every earning previously just summed into gross with no
    pre-tax/post-tax distinction at all."""
    __tablename__ = "payroll_employee_pretax_elections"

    id             = Column(Integer, primary_key=True, index=True)
    employee_id    = Column(Integer, ForeignKey("payroll_employees.id"), nullable=False, index=True)
    earning_type   = Column(String(50), nullable=False)   # matches TaxabilityRule.earning_type
    amount         = Column(Numeric(12, 2), nullable=True)
    percent_of_gross = Column(Numeric(6, 4), nullable=True)
    effective_from = Column(Date, nullable=False)
    effective_to   = Column(Date, nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<EmployeePreTaxDeductionElection emp={self.employee_id} type={self.earning_type}>"


class ReciprocityRule(Base):
    """A directional cross-state tax reciprocity agreement (e.g. PA
    resident working in NJ) — per the standard's §8.2, stored as data, not
    embedded in state calculation code. Empty table = no reciprocity
    applied anywhere = today's exact behavior (work_state alone determines
    withholding)."""
    __tablename__ = "payroll_reciprocity_rules"

    id                       = Column(Integer, primary_key=True, index=True)
    resident_jurisdiction    = Column(String(10), nullable=False)   # "US-PA"
    work_jurisdiction        = Column(String(10), nullable=False)   # "US-NJ"
    agreement_type           = Column(String(40), nullable=False, default="RECIPROCAL_WAGE_WITHHOLDING", server_default="RECIPROCAL_WAGE_WITHHOLDING")
    employee_certificate     = Column(String(50), nullable=True)    # "NJ-165"
    certificate_required     = Column(Boolean, nullable=False, default=True, server_default="true")
    result_when_valid        = Column(String(200), nullable=True)
    effective_from           = Column(Date, nullable=False)
    effective_to             = Column(Date, nullable=True)
    source_document_id       = Column(Integer, ForeignKey("payroll_source_artifacts.id"), nullable=True)

    __table_args__ = (
        UniqueConstraint("resident_jurisdiction", "work_jurisdiction", "effective_from", name="uq_reciprocity_pair_effective"),
    )

    def __repr__(self):
        return f"<ReciprocityRule {self.resident_jurisdiction}->{self.work_jurisdiction}>"


class PayrollYtdAccumulator(Base):
    """Running year-to-date taxable-wages/tax-withheld total per employee
    per tax component, for jurisdictions whose statutory caps (Social
    Security wage base, FUTA wage base, Additional Medicare threshold) must
    be resolved against actual cumulative pay-to-date rather than a flat
    current-period-times-twelve estimate. Written only by real payslip
    generation (never by preview), one row per (employee, tax_year,
    component). Empty for every employee until Phase 2 engine wiring reads/
    writes it — until then, calculation behavior is exactly what it is
    today (see engine/countries/us.py)."""
    __tablename__ = "payroll_ytd_accumulators"

    id                        = Column(Integer, primary_key=True, index=True)
    employee_id               = Column(Integer, ForeignKey("payroll_employees.id"), nullable=False, index=True)
    tax_year                  = Column(String(10), nullable=False)   # "US-CY-2026"
    tax_component             = Column(String(30), nullable=False)   # "social_security" | "futa" | "medicare_additional" | ...
    ytd_taxable_wages         = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    ytd_tax_withheld          = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    last_updated_payslip_id   = Column(Integer, ForeignKey("payslip_items.id"), nullable=True)
    updated_at                = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("employee_id", "tax_year", "tax_component", name="uq_ytd_accumulator_employee_year_component"),
    )

    def __repr__(self):
        return f"<PayrollYtdAccumulator emp={self.employee_id} year={self.tax_year} comp={self.tax_component}>"


class OrganizationYtdAccumulator(Base):
    """Running year-to-date AGGREGATE remuneration across every employee
    in an organization, per tax component — the org-level counterpart to
    PayrollYtdAccumulator above, same shape, keyed by organization instead
    of employee. Required for employer payroll levies that band on an
    org's total annual payroll rather than any single employee's pay
    (Ontario/BC EHT, Manitoba HE Levy, NL HAPSET, Quebec HSF —
    ZP-TAX-CA-2026-001 §15/§13) — no such aggregate existed anywhere in
    this schema before (EmployerTaxProfile is a static agency-issued rate
    notice, not a ledger; PayrollRun.total_gross resets every pay period).

    Written only by real payslip generation (never by preview, never by
    regenerate_employee_payslip — see service.py's
    _load_ca_org_levy_ytd/_upsert_ca_org_levy_ytd_accumulator for the
    exact same read-only-on-correction discipline
    PayrollYtdAccumulator's per-employee callers already follow), one row
    per (organization, tax_year, component). Safe under sequential,
    single-transaction per-employee db.flush() within one run-generation
    call exactly as proven for the per-employee accumulator — see
    generate_payslips_for_run's own docstring/comments. Would need
    row-level locking (SELECT ... FOR UPDATE) if payslip generation were
    ever parallelized across sessions; it isn't today.

    Empty for every org until a levy's own rollout switch is enabled —
    until then, calculation behavior is exactly what it is today (no
    Ontario/BC EHT, Manitoba HE Levy, or NL HAPSET is implemented yet)."""
    __tablename__ = "organization_ytd_accumulators"

    id                        = Column(Integer, primary_key=True, index=True)
    organization_id           = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    tax_year                  = Column(String(10), nullable=False)   # "CA-CY-2026"
    tax_component             = Column(String(30), nullable=False)   # "on_eht" | "bc_eht" | "mb_he_levy" | "nl_hapset" | "qc_hsf" | ...
    ytd_taxable_wages         = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    ytd_tax_withheld          = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    last_updated_payslip_id   = Column(Integer, ForeignKey("payslip_items.id"), nullable=True)
    updated_at                = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("organization_id", "tax_year", "tax_component", name="uq_org_ytd_accumulator_org_year_component"),
    )

    def __repr__(self):
        return f"<OrganizationYtdAccumulator org={self.organization_id} year={self.tax_year} comp={self.tax_component}>"