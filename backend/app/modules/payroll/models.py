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
from app.modules.payroll.bank_routing import resolve_routing


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
    # Phase 8BU: distinct from FAILED — some components genuinely
    # calculated (real, persisted, non-fabricated figures) while at
    # least one OTHER component (typically wage tax) is genuinely
    # unavailable. Never used to imply a complete, payable result — see
    # countries/germany.py's partial-calculation path and
    # service.py's/the frontend's explicit "PARTIALLY CALCULATED, net
    # pay NOT available" handling. `status = Column(String(20), ...)`
    # (models.py) — no DB migration needed, this is a pure application-
    # level enum addition.
    PARTIAL = "Partial"


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


class PayrollScopeStatus(str, enum.Enum):
    """Billing Commercial Layer's BWM scope classification (blueprint §4) —
    orthogonal to EmployeeStatus above, which governs payroll processing
    eligibility, not billing counting. A DRAFT/FUTURE_DATED/VOIDED/TEST/DEMO
    employee is excluded from every Billable Worker Month count outright;
    TERMINATED_ARCHIVE counts only in a month it actually has production
    payslip activity. Read only by billing/bwm.py (via getattr, so a
    database that predates this column keeps working identically to every
    ACTIVE employee) — payroll itself never branches on this value."""
    ACTIVE             = "ACTIVE"
    DRAFT              = "DRAFT"
    FUTURE_DATED       = "FUTURE_DATED"
    VOIDED             = "VOIDED"
    TEST               = "TEST"
    DEMO               = "DEMO"
    TERMINATED_ARCHIVE = "TERMINATED_ARCHIVE"


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
    # US-specific: Form W-4 Step 2 "Multiple Jobs or Spouse Works" checkbox
    # (ZP-TAX-US-2026-001 §3.3, gap-closure Phase 8, 2026-09-12). False for
    # every employee today — engine/countries/us.py falls back to the
    # existing standard (§3.2) bracket table exactly as before this column
    # existed. True switches that employee to the genuinely different,
    # narrower-banded §3.3 table (see hardcoded_defaults.py's
    # "_STEP2"-tagged TaxSlab rows) — a real, higher-withholding
    # calculation, not a cosmetic flag.
    w4_step2_checkbox = Column(Boolean, default=False, nullable=False, server_default="false")

    # US Form W-4 §3.4 controls (ZP-TAX-US-2026-001, gap-closure Plan
    # Phase 2d) — each nullable/False by default and a complete no-op
    # until explicitly entered, same convention as every other field
    # above. w4_allowances_claimed only means anything on the LEGACY
    # (pre-2020) calculation path (see w4_form_vintage above) — a 2020+
    # employee's value here, if any, is simply never read.
    w4_allowances_claimed = Column(Integer, nullable=True)
    is_nonresident_alien = Column(Boolean, default=False, nullable=False, server_default="false")
    # Steps 3/4(c) of the 2020+ Form W-4 — the employee's OWN certified
    # dollar figures, preserved and applied exactly as given, never
    # derived/estimated. Step 3 (dependents credit) is annual and
    # subtracted from the computed annual tax; Step 4(a) (other income)
    # is annual and added to taxable wages; Step 4(c) (extra withholding)
    # is a flat PER-PAY-PERIOD amount added directly to withholding, not
    # annualized.
    w4_dependents_credit_annual = Column(Numeric(12, 2), nullable=True)
    w4_other_income_annual = Column(Numeric(12, 2), nullable=True)
    w4_extra_withholding_per_period = Column(Numeric(12, 2), nullable=True)

    # Connecticut-specific: CT-W4 Withholding Code ("A"/"B"/"C"/"D"/"F") —
    # a genuinely different concept from federal filing status/w4_filing_
    # status above (ZP-TAX-US-2026-001 §4/CT DRS TPG-211, gap-closure
    # Phase 8, 2026-09-12). CT eliminated traditional allowances entirely
    # in favor of this employee-selected code, which drives its own
    # 5-table calculation (exemption/base-tax/phase-out/recapture/credit)
    # — see engine/countries/us.py's _calculate_ct_annual_tax. NULL for
    # every employee today (and for every non-CT employee always) — a CT
    # employee with no code on file resolves to $0 CT withholding,
    # exactly as before this column existed, never a guessed code.
    ct_withholding_code = Column(String(2), nullable=True)

    # New Jersey-specific: NJ-W4 Rate Table letter ("A"/"B"/"C"/"D"/"E") —
    # selected on Form NJ-W4, a genuinely different election from federal
    # filing status (ZP-TAX-US-2026-001 §4/NJ Division of Taxation
    # Tables for Percentage Method of Withholding, gap-closure Phase 8,
    # 2026-09-13). Read directly by engine/countries/us.py's own NJ-
    # specific branch as the bracket-lookup key (see
    # hardcoded_defaults._US_STATE_GRADUATED_TAX_RATES["NJ"]'s own
    # comment). NULL for every employee today — an NJ employee with no
    # rate table on file resolves to $0, never a guessed table.
    nj_rate_table = Column(String(2), nullable=True)

    # Kansas-specific: Form K-4 certified dependent count (Production-
    # Readiness Plan Phase 4, 2026-09-16, KW-100 Rev. 10-24). KW-100's own
    # withholding-allowance formula is: $9,160 (Single/HOH/MFS) or $18,320
    # (MFJ) personal exemption, PLUS $2,320 per this dependent count, PLUS
    # a further flat $2,320 if w4_filing_status == "HOH" — the HOH add-on
    # needs no separate column since w4_filing_status already carries it;
    # only the per-dependent count is a genuinely new fact with no
    # existing home (w4_dependents_credit_annual is a federal Step-3
    # DOLLAR credit subtracted from computed tax, not a headcount, and
    # means something structurally different). NULL for every employee
    # today — engine/countries/us.py's KS-specific deduction function
    # treats NULL as 0 dependents, never a guess.
    ks_k4_dependents = Column(Integer, nullable=True)

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
    # Canada-specific: TD1X's REAL purpose — a commission employee's own
    # estimated annual commission income/expenses, used by CRA's
    # commission formula (§18/§19: "do not convert to ordinary TD1").
    # Previously td1_additional_tax above was the only TD1X-adjacent
    # field, which only covers the flat-additional-withholding half of
    # TD1X, not the actual commission formula (see service.
    # calculate_ca_td1x_commission_withholding, a standalone calculator
    # like the special-payment/retiring-allowance ones, not woven into
    # the regular per-period calculate() path). NULL means "no TD1X
    # commission election on file" — the regular TD1 method applies as
    # today.
    td1x_estimated_annual_commission = Column(Numeric(12, 2), nullable=True)
    td1x_estimated_annual_expenses    = Column(Numeric(12, 2), nullable=True)
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
    # City/local-level residence, distinct from residence_state above —
    # gap-closure Level 2 Batch 7, 2026-09-13, added for New York's Yonkers
    # resident surcharge (a city-level resident tax where residence_state
    # alone can't distinguish a Yonkers resident from any other NY
    # resident, since Yonkers is inside NY like every other NY city). NULL
    # for every employee before this existed and for every non-Yonkers
    # employee today — completely additive, no existing calculation reads
    # this until an employee's own value is explicitly set.
    residence_locality = Column(String(100), nullable=True)
    # Whether a reciprocity certificate (e.g. NJ-165) is on file for this
    # employee's resident/work state pair, and when it expires. False/NULL
    # for every employee today — reciprocity suppression only ever applies
    # when this is explicitly set. See reciprocity_resolver.py.
    reciprocity_certificate_on_file   = Column(Boolean, default=False, nullable=False, server_default="false")
    reciprocity_certificate_expiry    = Column(Date, nullable=True)

    # Pennsylvania Act 32 Residency Certification Form (DCED-CLGS-32-6,
    # ZP-TAX-US-2026-001 §7.1, gap-closure Plan Phase 3) — pure
    # recordkeeping, mirroring reciprocity_certificate_on_file/expiry
    # above exactly. Deliberately NOT read anywhere in
    # engine/countries/us.py: unlike reciprocity, PA's own EIT
    # withholding obligation (the "higher of" comparison, see
    # residence_locality/residence_locality_rate) applies regardless of
    # whether this form is on file — the form verifies the employee's
    # address, it does not gate the calculation. False/None for every
    # employee today; the actual PSD-code addresses already live in the
    # existing generic residence_locality/work_locality fields above —
    # this only tracks whether the certification itself was collected.
    residency_certification_on_file  = Column(Boolean, default=False, nullable=False, server_default="false")
    residency_certification_date     = Column(Date, nullable=True)

    # Named generically in case another jurisdiction ever needs the same
    # "employee elects their own withholding percentage" shape (same
    # naming precedent as residence_state above). First consumer: Arizona
    # Form A-4 (ZP-TAX-US-2026-001 §4 Matrix) — AZ's statutory range is
    # 0.5%-3.5%, employee-elected; the engine previously always applied
    # the document's own no-A-4-on-file default of 2.0% to every AZ
    # employee regardless of what they actually elected. NULL (every
    # employee today) means "no election on file" — engine/countries/
    # us.py falls back to the existing 2.0% AZ default exactly as before
    # this column existed, so no existing calculation changes just
    # because this field now exists. Range validation (0.5-3.5 for AZ)
    # lives in employee_validation.py, not here, same pattern as every
    # other jurisdiction-specific field's validation.
    state_income_tax_election_pct = Column(Numeric(5, 2), nullable=True)

    # Generic across every country (not UK-only) — "Monthly"/"Weekly"/
    # "Fortnightly"/"FourWeekly". Defaults to "Monthly" so every existing
    # employee's numbers are completely unaffected; only engine/countries/
    # uk.py currently varies its calculation by this field.
    pay_frequency    = Column(String(20), nullable=False, default="Monthly", server_default="Monthly")

    # Australia-specific declarations driving ATO Schedule 1/8 scale
    # selection (ZP-TAX-AU-2026-27-001 §5.1/§14). NULL for every non-AU
    # employee, and for AU employees until explicitly entered. Unset
    # au_tfn_status resolves through the ORDINARY Scale 1/2 path (as if a
    # TFN were on file) — same "unset means the standard path, not the
    # most punitive edge case" convention UK's unset tax_code (falls back
    # to standard personal allowance, not an emergency code) already
    # uses. Scale 4's drastic 47%/45% flat withholding applies ONLY when
    # this is EXPLICITLY set to "NOT_PROVIDED" — a real recorded fact,
    # never inferred from absence. au_tax_free_threshold_claimed below is
    # the one field that DOES default conservatively (unclaimed = higher
    # withholding) since that mirrors the TFN declaration form's own
    # default position.
    au_tfn_status = Column(String(20), nullable=True)  # "PROVIDED" | "NOT_PROVIDED" | "EXEMPTION"
    # "RESIDENT" | "FOREIGN_RESIDENT" | "WORKING_HOLIDAY_MAKER" — selects
    # Schedule 1 Scale 2/1 vs Scale 3 vs the WHM schedule, and Schedule 8's
    # RESIDENT/FOREIGN coefficient family. Distinct from the generic
    # tax_residency_status column above (India old-regime age bands only).
    au_residency_status = Column(String(25), nullable=True)
    # Scale 1 (not claimed) vs Scale 2 (claimed) — also doubles as
    # Schedule 8's own threshold_claim_state per §8's STSL contract
    # ("Tax-free threshold claimed OR foreign resident" is one coefficient
    # family, driven by this same flag together with au_residency_status).
    au_tax_free_threshold_claimed = Column(Boolean, nullable=True)
    # "FULL" | "HALF" — selects Schedule 1 Scale 5/6 in place of the
    # ordinary Scale 1/2. NULL = standard Medicare Levy (no exemption).
    au_medicare_levy_exemption = Column(String(10), nullable=True)
    # ATO-authorised upward/downward withholding variation (§14's
    # "Withholding declaration"), applied only where the variation is on
    # file — never inferred. NULL means no variation.
    au_withholding_variation_pct = Column(Numeric(5, 2), nullable=True)
    # §7's own "Extra-pay calendar" control — set only when an org
    # explicitly identifies a specific income year as landing this
    # employee's pay cycle on the 53rd weekly pay or 27th fortnightly pay
    # (a rare calendar-alignment fact, never inferred from pay_date
    # arithmetic here). NULL (the ordinary 52/26-pay calendar) is the
    # default and unaffected behavior for every employee today.
    au_extra_pay_calendar = Column(String(20), nullable=True)  # "53_WEEK" | "27_FORTNIGHT"
    # §5 step 4's SAPTO declaration (Phase 10, 2026-09-17) — a self-
    # declared seniors/pensioners category, entirely separate from
    # au_tax_free_threshold_claimed. NULL means no SAPTO applies (LITO,
    # by contrast, applies automatically to every resident and needs no
    # declaration column at all). Only "SINGLE" resolves to a real offset
    # today — see engine/countries/australia.py's own docstring for why
    # "COUPLE"/"ILLNESS_SEPARATED_COUPLE" stay at $0 pending confirmed
    # ATO data (two independent lookups of the published figures for
    # those two categories specifically produced conflicting thresholds).
    au_sapto_category = Column(String(30), nullable=True)  # "SINGLE" | "COUPLE" | "ILLNESS_SEPARATED_COUPLE"

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

    # UK RTI (ZP-TAX-UK-2026-27-001 §18 gap-closure Part 9, 2026-09-09) —
    # a Full Payment Submission's Employee Details section requires a
    # home address (mandatory for a new starter with no NINO match) and,
    # for a new starter, one of HMRC's own starter-declaration codes
    # (A/B/C — "this is my first job since last 6 April" / "I have
    # another job" / etc.). No other feature in this codebase needed an
    # employee's home address before — NULL for every employee until
    # entered, same "no behavior changes until explicitly set" convention
    # as every other field in this section. Not UK-only by name (a home
    # address is generically useful HR data) but no other country's
    # calculation reads these today.
    address_line1     = Column(String(200), nullable=True)
    address_line2     = Column(String(200), nullable=True)
    address_town      = Column(String(100), nullable=True)
    address_county    = Column(String(100), nullable=True)
    address_postcode  = Column(String(20), nullable=True)
    starter_declaration = Column(String(1), nullable=True)  # A | B | C

    # Billing Commercial Layer (blueprint §4 BWM) scope classification —
    # see PayrollScopeStatus above. NULL for every employee until billing's
    # admin tooling sets it; NULL and ACTIVE both mean "ordinary in-scope
    # employment relationship, counted normally" (see billing/bwm.py's
    # _resolve_inclusion). Nullable String rather than a native Enum column
    # so this stays a purely additive, non-breaking change to an existing
    # table (see migrations/sync_schema.py) and so a value payroll doesn't
    # recognize never raises here — only billing/bwm.py interprets it.
    payroll_scope_status = Column(String(30), nullable=True, index=True)

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

    @property
    def routing(self) -> list:
        """Multi-jurisdiction routing block (ZP-MJR-2026-001): the
        jurisdiction-correct list of [{key,label,value}] for this employee,
        consumed by the additive EmployeeResponse.routing field. India reads
        the dedicated `ifsc` column; every other country reads its codes
        from compliance_fields (the same source the payslip snapshot uses).
        Returns [] when the employee's country is unknown."""
        return resolve_routing(self)


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

    # ── Ireland (IE) statutory attributes (ZP-IE-ENG-001 §12) ────────────
    # EmployeeIrelandProfile's employee-OWNED facts. Deliberately NOT here:
    # the RPN snapshot (its own table — authority-supplied and immutable per
    # IE-022/IE-045), MyFutureFund status (its own table — NAERSA-owned per
    # IE-018/IE-030), and the RPN-derived credits/bands/LPT (IE-004: never
    # admin-typed). What lives here is exactly what the employer legitimately
    # records about the worker and must be able to evidence. NULL everywhere
    # for every non-Irish employee.
    ie_ppsn                    = Column(String(15), nullable=True)   # 7 digits, optional trailing letter
    # The employer's own Revenue registration reference for this worker —
    # distinct from the org's PAYE/ROS registration numbers.
    ie_employer_reference      = Column(String(32), nullable=True)
    ie_revenue_employment_id   = Column(String(64), nullable=True)
    # A0 | AX | AL | A1 only (IE-001/IE-016: the certified launch cohort).
    # A value outside that set must be rejected at the validation layer, not
    # coerced here, so an uncertified class can never reach the engine.
    ie_prsi_class              = Column(String(10), nullable=True)
    ie_prsi_exemption_reference = Column(String(64), nullable=True)
    # Standard | Reduced | Exempt. USC has its OWN accumulator and rate
    # bands (IE-009/IE-010) and must never be inferred from PAYE treatment.
    ie_usc_status              = Column(String(20), nullable=True)
    # Occupational pension/PRSA scheme — represented SEPARATELY from
    # MyFutureFund (IE-021): an auto-enrolment exemption is proved by
    # citing a real scheme, not by a bare checkbox.
    ie_pension_scheme_reference = Column(String(64), nullable=True)
    ie_pension_qualifying_exemption_reference = Column(String(64), nullable=True)
    ie_pension_qualifying_exemption_effective_from = Column(Date, nullable=True)
    # Working-hours evidence for the minimum-wage check. IE-035 forbids
    # deriving this from a salary divided by a generic 40-hour week, so it
    # is captured contractually and the engine BLOCKS without it.
    ie_contracted_weekly_hours = Column(Numeric(5, 2), nullable=True)
    # NONE | ERO | SEO. A sector wage order selects a certified sectoral rate
    # instead of the national minimum wage; ERO/SEO BLOCK until that
    # certified content exists (§11 gates sectoral rates explicitly).
    ie_sector_wage_order       = Column(String(10), nullable=True)
    # Emergency basis needs a reason AND the week counter (IE-008/IE-031);
    # neither may be inferred, so both are recorded explicitly.
    ie_emergency_reason        = Column(Text, nullable=True)
    ie_emergency_week          = Column(Integer, nullable=True)

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

    __table_args__ = (
        # Phase 8BE — idempotency guard. Before this, resubmitting the same
        # batch_reference for the same organization silently created a
        # second row (no dedup check existed anywhere on this path); the
        # DB-level constraint makes a duplicate resubmission fail loudly
        # and immediately, and create_elstam_change_list_batch() (service.py)
        # turns that IntegrityError into a clear BadRequestException instead
        # of a raw 500. Scoped per-organization (not global) since two
        # different organizations may legitimately receive a change list
        # using the same reference scheme from their own payroll provider.
        UniqueConstraint(
            "organization_id", "batch_reference",
            name="uq_germany_elstam_change_list_batch_org_ref",
        ),
    )

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


# ── Germany: ELSTER certificate configuration (Phase 8BF) ────────────────
# Per-organization record of WHETHER a real ELSTER organizational
# certificate has been configured — NEVER the certificate/private key
# material itself. `certificate_reference` is a pointer into an external
# secret store (the organization's own key-management system / HSM /
# vault path) — this table's entire purpose is to answer "has a human
# configured a real certificate reference yet", never to hold the secret.
# Storing an actual private key or PIN in this (or any) application
# database row would be a real security defect; this design avoids that
# category of defect entirely by construction, mirroring how
# PapAlgorithmAsset never stores the BMF's actual XML bytes in a way that
# could be mistaken for a secret and how ELStAM's own boundary
# (engine/germany_pap/elstam.py) never accepts a live BZSt credential.
class GermanyElsterCertificateConfig(Base):
    """Whether this organization has a configured ELSTER organizational
    certificate reference. is_configured is the ONLY field
    resolve_elster_transmitter() (engine/germany_elster.py) ever reads —
    and even when True, no transmitter implementation exists yet (see that
    module's own docstring), so configuring a reference here does not by
    itself unblock transmission."""
    __tablename__ = "payroll_germany_elster_certificate_configs"

    id              = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, unique=True, index=True)

    is_configured        = Column(Boolean, nullable=False, default=False, server_default="false")
    certificate_reference = Column(String(200), nullable=True)
    reference_description  = Column(Text, nullable=True)

    configured_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    configured_at    = Column(DateTime(timezone=True), nullable=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    updated_at       = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<GermanyElsterCertificateConfig organization_id={self.organization_id} configured={self.is_configured}>"


# ── Germany: ELSTER transmission record (Phase 8BF) ───────────────────────
# One attempt to prepare/transmit a Lohnsteuer-Anmeldung-shaped filing via
# ELSTER. The state machine below is INTENTIONALLY bounded to the states
# this codebase can actually reach today (DRAFT -> VALIDATED ->
# BLOCKED_EXTERNAL) — REJECTED/ACKNOWLEDGED exist in the vocabulary for a
# future phase that implements a real transmitter, but no code path in
# this phase ever sets them; setting them without a real ELSTER response
# would be exactly the kind of fabricated external result this project's
# governing rules forbid. `payload_summary` deliberately holds only
# non-sensitive structural metadata (period, transmission type, a
# reference id) — never the actual filing content — since this table's
# purpose is transmission-attempt audit, not a second copy of statutory
# data that already lives on the payslip/payroll-run records it derives
# from.
class GermanyElsterTransmission(Base):
    __tablename__ = "payroll_germany_elster_transmissions"

    id              = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    # e.g. "LOHNSTEUER_ANMELDUNG" — free text, spec gives no enumerated set
    # for this phase (same "concept named, no vocabulary given" treatment
    # as GermanyElstamChangeListBatch.source).
    transmission_type = Column(String(50), nullable=False)
    period_start      = Column(Date, nullable=False)
    period_end        = Column(Date, nullable=False)
    payload_summary   = Column(JSON, nullable=True)

    # DRAFT | VALIDATED | BLOCKED_EXTERNAL | QUEUED | TRANSMITTED |
    # ACKNOWLEDGED | REJECTED — see class docstring: only the first three
    # are ever reached by this phase's code.
    status            = Column(String(20), nullable=False, default="DRAFT", server_default="DRAFT")
    validation_errors = Column(JSON, nullable=True)
    blocked_reason    = Column(Text, nullable=True)

    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_germany_elster_transmission_org_period", "organization_id", "period_start"),
    )

    def __repr__(self):
        return (
            f"<GermanyElsterTransmission id={self.id} organization_id={self.organization_id} "
            f"type={self.transmission_type!r} status={self.status}>"
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

    RESOLVED (ZP-TAX-AU-2026-27-001 §25 "Calculation Trace — Minimum
    Audit Payload", 2026-09-17): `au_calculation_trace` below is a
    deliberately AU-SCOPED JSON column (Option A of the two architecture
    choices raised in the 2026-09-16/17 gap analysis — a platform-wide
    `PayrollCalculationTrace` table was the alternative, explicitly
    declined for now), chosen because AU's own §25 requirement is the
    only one currently forcing this decision and a generic table can
    still be introduced later without migrating this column's data (the
    JSON shape would simply become that table's own payload). No other
    country gets a trace column from this change.
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
    # France (ZP-FR-ENG-001) — frozen France result: the three nets
    # (FR-042), PAS provenance (FR-010), the base-to-contribution trace
    # (FR-040), RGDU and `ytd_after` — the RGDU/CSG accumulator state the
    # NEXT period's calculation reads back (FR-023). NULL for non-France.
    fr_calculation_snapshot       = Column(JSON, nullable=True)

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

    # Loss-of-pay proration transparency. total_working_days is the actual
    # calendar length of the run's pay period (28/29/30/31 for a calendar
    # month — the engine mirrors it from PayrollResult.calendar_days);
    # payable_days additionally excludes any day the employee's attendance
    # record is "absent" or "leave" with leave_type = "unpaid" (or NULL for
    # legacy rows), so total_working_days − payable_days == unpaid days.
    # Paid / sick / casual leaves do NOT reduce payable_days.
    # basic/hra/special_allowance above are the full monthly amounts
    # actually paid (per-day salary always divides by the 30-day basis);
    # these two columns record the payable-day breakdown so a payslip is
    # self-explanatory without recomputing it.
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
    # Germany: Solidaritätszuschlag (Soli) — informational, computed monthly
    # from an executed BMF PAP run and NEVER summed into total_deductions/
    # net_pay (it is already folded into the persisted `tds` = Lohnsteuer +
    # Soli, exactly like Canada's cpp_base/cpp_first_additional note they're
    # not re-summed). Zero for every non-DE payslip and for every German
    # payslip until a real PUBLISHED PapAlgorithmAsset computes it.
    soli              = Column(Numeric(12, 2), default=0, server_default="0")
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
    # UK: Automatic Enrolment assessment (ZP-TAX-UK-2026-27-001 §13 gap-
    # closure Part 3) — "ELIGIBLE_JOBHOLDER"/"NON_ELIGIBLE_JOBHOLDER"/
    # "ENTITLED_WORKER", or NULL (dormant switch, or no date_of_birth on
    # record). Purely informational — never affects employee_pension/
    # employer_pension above.
    auto_enrolment_status = Column(String(30), nullable=True)
    # UK: HMRC tax week (1-53) / tax month (1-12) this payslip falls in
    # (ZP-TAX-UK-2026-27-001 §18.1 gap-closure Part 6) — pure calendar
    # metadata, no rollout switch (computed whenever pay_date is known).
    tax_week = Column(Integer, nullable=True)
    tax_month = Column(Integer, nullable=True)
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
    # Australia: state/territory employer payroll tax (ZP-TAX-AU-2026-27-001
    # §14-18, Phase 4) — same org-level-accumulator-banded contract as
    # employer_eht above, one column across all 8 jurisdictions (an
    # employee has at most one work_state, same reasoning as
    # PayrollContext.au_state_payroll_tax_ytd_remuneration_before's own
    # single-shared-field docstring). AU-D05: an employer-liability figure
    # only, never subtracted from net_pay.
    employer_payroll_tax          = Column(Numeric(12, 2), default=0, server_default="0")
    # Australia: child support/garnishee statutory deductions (§19,
    # Phase 5) — a real EMPLOYEE deduction, summed into
    # total_employee_deductions/net_pay (unlike employer_payroll_tax
    # above). Per-order breakdown is NOT separately persisted here —
    # available live via the /au/court-orders/calculate endpoint and
    # CourtOrderedDeduction.total_amount_collected's own running total,
    # same "total only, no frozen snapshot" scope as every other
    # non-YTD-accumulator-backed deduction on this table.
    au_statutory_deductions_total = Column(Numeric(12, 2), default=0, server_default="0")
    # Australia: workers compensation premium (§18 employer overlay, Phase
    # 9 follow-up, 2026-09-17) — same employer-liability-only contract as
    # employer_payroll_tax above (AU-D05), a completely separate figure
    # from state payroll tax (different rate, different authority, no
    # YTD/telescoping — a flat rate on this period's own wages).
    au_workers_compensation_premium = Column(Numeric(12, 2), default=0, server_default="0")
    # Australia: §25 "Calculation Trace — Minimum Audit Payload" (Phase 9
    # follow-up, 2026-09-17). AU-only JSON payload recording HOW each AU
    # statutory figure on this payslip was derived — Schedule 1 scale/
    # weekly-x/coefficient-a/coefficient-b/pre-rounding-y for PAYG,
    # Schedule 8's own equivalent for STSL, the MLS threshold/rate/annual-
    # gross test, which Super Guarantee method applied (YTD-capped vs
    # annualized-estimate) with the MCB figures used, and the state
    # payroll-tax state/threshold/taper/charity-exemption facts — see
    # engine/countries/australia.py's calculate() for exactly what it
    # writes. Nullable/None for any payslip computed before this field
    # existed or where a given component didn't run (e.g. no STSL
    # obligation) — never backfilled or inferred after the fact, same
    # "real figures only, no reconstruction" discipline as every other
    # audit-trail field in this codebase.
    au_calculation_trace = Column(JSON, nullable=True)
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
    # CALCULATED (gross + SI + wage-tax/Soli/Kirchensteuer deltas all
    #   genuinely computed, via the same internal §32a/§39b calculator the
    #   base payslip itself used) |
    # PARTIAL (gross + SI + wage-tax/Soli genuinely computed, but this
    #   employee's Kirchensteuer specifically is unavailable on the base
    #   payslip — see Phase 8BU's church-tax-Land-unresolved PARTIAL path —
    #   so only that one component's delta stays an explicit, flagged 0) |
    # BLOCKED (gross + SI deltas applied; the base payslip's own wage tax
    #   was never computed via the internal calculator — e.g. no
    #   germany_calculation_snapshot at all, or it used a different/future
    #   PAP version this delta logic doesn't know how to extend — so NO
    #   wage-tax/Soli/Kirchensteuer delta can be safely derived) |
    # REVERSED (attached then detached — deltas nulled, PayslipItem
    #   returned to pre-attach state).
    # Phase 8BV's PARTIAL_WAGE_TAX_PENDING_PAP is retired (no payslip was
    # ever persisted with that historical value across a schema/data
    # migration boundary — every attach until Phase 8BW ran through the
    # unconditional wage_tax_delta=0 branch, so no backfill is needed).
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
    applied_gross_delta = Column(Numeric(12, 2), nullable=True)
    applied_pf_delta    = Column(Numeric(12, 2), nullable=True)
    applied_esi_delta   = Column(Numeric(12, 2), nullable=True)
    # Phase 8BW: previously wage tax had no dedicated column at all (always
    # 0, represented only by financial_integration_status). Now genuinely
    # computed via a marginal T2-T1 delta on the SAME zvE base the base
    # payslip's own Lohnsteuer used (see _compute_overtime_financial_delta).
    # applied_wage_tax_delta -> PayslipItem.tds (which already combines
    # Lohnsteuer+Soli, matching the engine's own field-reuse convention).
    # applied_soli_delta -> PayslipItem.soli (informational, separate
    # column) AND folded into applied_wage_tax_delta's contribution to tds.
    # applied_church_tax_delta -> PayslipItem.church_tax. All three are 0
    # (never NULL once attached) when financial_integration_status is
    # BLOCKED, and applied_church_tax_delta specifically is 0 when the
    # employee isn't church-tax-liable (a real zero) OR when PARTIAL (an
    # explicitly-flagged unavailable zero — see financial_integration_status
    # above, never conflated with the real-zero case).
    applied_wage_tax_delta   = Column(Numeric(12, 2), nullable=True)
    applied_soli_delta       = Column(Numeric(12, 2), nullable=True)
    applied_church_tax_delta = Column(Numeric(12, 2), nullable=True)

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
    # Widened from Numeric(10,2) to Numeric(14,2) 2026-09-17 — found via
    # LIVE data entry: NT's payroll-tax high-rate group-wage threshold is
    # $100,000,000, which overflows Numeric(10,2)'s 8-digit-before-decimal
    # ceiling. Matches TaxSlab.min_amount/max_amount's own Numeric(14,2)
    # precision for consistency — same numeric-overflow bug class this
    # project has hit before on CA/US builds; never caught by pytest,
    # which never round-trips a value through the real DB column.
    flat_amount          = Column(Numeric(14, 2), nullable=True)  # for flat components like PT
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

    # Per-rule-family effective dating (ZP-TAX-UK-2026-27-001 §3.2 gap-
    # closure Part 1A, 2026-09-09) — a rule family like National Minimum
    # Wage (effective 1 April) or Advisory Fuel Rates (effective 1 June,
    # then quarterly) needs its OWN effective window distinct from the
    # tax_year pack's 6 April window. NULL (every row today) means "use
    # the parent JurisdictionPack's own effective_from/effective_to" —
    # completely additive; only enforced by tax_resolver.py's
    # resolve_tax_configuration (the canonical-pack path, which already
    # takes a payroll_date). The legacy per-org get_contribution_rates
    # path has no date parameter at all and does not consult these —
    # a deliberately scoped-down first pass, not an oversight.
    effective_from        = Column(Date, nullable=True)
    effective_to          = Column(Date, nullable=True)

    # Per-rule evidence (ZP-TAX-UK-2026-27-001 §4.2 gap-closure Part 1B,
    # 2026-09-09) — until now, SourceArtifact could only be linked to a
    # whole JurisdictionPack (or a handful of US-specific side tables),
    # never to one individual rate row, even though §4.2 requires evidence
    # PER PUBLISHED RULE. Reuses the existing SourceArtifact table — no
    # new table needed, just this FK. NULL for every row today.
    source_document_id   = Column(Integer, ForeignKey("payroll_source_artifacts.id"), nullable=True)

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
    # Widened from VARCHAR(20) to VARCHAR(30) 2026-09-17 — found via LIVE
    # data entry (never caught by pytest, which builds in-memory dataclass
    # contexts that never touch this column): AU's own Schedule 8 family
    # name "STSL_CLAIMED_OR_FOREIGN" is 24 characters, silently truncated
    # to a StringDataRightTruncation error on insert. Same VARCHAR-limit
    # bug class this project has hit before on CA/US builds.
    filing_status         = Column(String(30), nullable=True)

    # MARGINAL_RATE (default, existing brackets) | FLAT_RATE | FIXED_PLUS_MARGINAL
    # | FORMULA | TABLE_LOOKUP | CONTRIBUTION | PT_FLAT | AU_PAYG_COEFFICIENT |
    # AU_STSL_COEFFICIENT | AU_EXTRA_PAY_WITHHOLDING | AU_LITO_OFFSET |
    # AU_SAPTO_OFFSET | AU_SCHEDULE3_COEFFICIENT. Only FORMULA rows use formula_expression instead
    # of min/max/rate_pct — e.g. Germany's Lohnsteuer, which isn't a clean
    # bracket table. Existing bracket rows for every country default to
    # MARGINAL_RATE, so no calculator changes are required until a row
    # actually opts into FORMULA. PT_FLAT rows (India's state-level
    # Professional Tax, bracketed by gross salary, not a percentage) use
    # flat_amount instead of rate_pct — rate_pct stays 0.00 (still NOT
    # NULL) on those rows, simply unread by the engine.
    # AU_PAYG_COEFFICIENT/AU_STSL_COEFFICIENT (ZP-TAX-AU-2026-27-001 §5/§8):
    # a genuinely different shape from every other rule_type — the ATO's
    # Schedule 1/8 formula is y = a·x − b evaluated against a
    # PERIOD-frequency weekly-equivalent x (not annual income), selected by
    # BAND (not a cumulative marginal-bracket sum). Reuses this table's
    # existing columns for the two coefficients rather than a new table:
    # min_amount/max_amount hold the weekly-x band boundaries (exactly like
    # every other bracket row), rate_pct holds coefficient `a`, flat_amount
    # holds coefficient `b` (the same column PT_FLAT uses, mutually
    # exclusive rule_types so no conflict), and filing_status holds the
    # Scale identifier ("SCALE_1".."SCALE_6") for AU_PAYG_COEFFICIENT or the
    # declaration-state family ("STSL_CLAIMED_OR_FOREIGN"/"STSL_NOT_CLAIMED")
    # for AU_STSL_COEFFICIENT — the same "repurpose an existing generic
    # column per rule_type" convention India's PT_FLAT/gender and US's
    # filing_status already use. See engine/countries/australia.py's
    # _resolve_au_coefficient_band.
    # AU_EXTRA_PAY_WITHHOLDING (ZP-TAX-AU-2026-27-001 §7's "Extra-pay
    # calendar" table): a flat top-up on top of the ordinary Schedule 1
    # result, not a formula — min_amount/max_amount hold the period
    # earnings band (in the pay-frequency-appropriate figure, e.g. weekly
    # or fortnightly gross, NOT the Schedule 1 weekly-x conversion), and
    # flat_amount (same column PT_FLAT/AU_STSL_COEFFICIENT's `b` use)
    # holds the additional withholding dollar amount for that band.
    # filing_status holds which calendar this row belongs to
    # ("53_WEEK"/"27_FORTNIGHT"). rate_pct stays 0.00 (unread) on these
    # rows, same convention PT_FLAT already established.
    # Widened from VARCHAR(20) to VARCHAR(30) 2026-09-17 — found via LIVE
    # data entry (never caught by pytest, which builds in-memory dataclass
    # contexts that never touch this column): "AU_EXTRA_PAY_WITHHOLDING"
    # is 25 characters, silently truncated to a StringDataRightTruncation
    # error on insert. Same VARCHAR-limit bug class as filing_status above.
    # AU_LITO_OFFSET/AU_SAPTO_OFFSET (ZP-TAX-AU-2026-27-001 §5 step 4,
    # Phase 10 2026-09-17): a shading-out offset band, ANCHORED AT THE
    # BAND'S OWN min_amount rather than at 0 (unlike AU_PAYG_COEFFICIENT's
    # y=a·x−b) — offset = flat_amount − rate_pct% × (annual_income −
    # min_amount), floored at $0. min_amount/max_amount hold the annual
    # taxable-income band, rate_pct the phase-out rate, flat_amount the
    # band's own base offset dollar figure (same column reuse convention
    # as every other AU rule_type above), and filing_status holds "LITO"
    # for AU_LITO_OFFSET or the SAPTO category ("SINGLE"/"COUPLE"/
    # "ILLNESS_SEPARATED_COUPLE") for AU_SAPTO_OFFSET — see
    # engine/countries/australia.py's _calculate_au_income_tax_offset.
    # AU_SCHEDULE3_COEFFICIENT (Phase 12, 2026-09-17, NAT 1023 entertainers):
    # identical shape/column mapping to AU_PAYG_COEFFICIENT (y=a·x−b on a
    # weekly-equivalent x), a separate rule_type only because Schedule 3's
    # own bands are genuinely different numbers from Schedule 1's — never
    # read by the ordinary PAYG scale lookup. filing_status holds
    # "SCHEDULE3_THRESHOLD_CLAIMED"/"SCHEDULE3_NO_THRESHOLD" — the no-TFN
    # and foreign-resident cases skip this table entirely (flat rate / own
    # hardcoded weekly scale — see calculate_au_schedule3_entertainer_
    # withholding).
    rule_type             = Column(String(30), nullable=False, default="MARGINAL_RATE", server_default="MARGINAL_RATE")
    formula_expression    = Column(Text, nullable=True)
    # PT_FLAT only: the fixed monthly deduction for this gross-income
    # bracket, and an optional override for whichever month absorbs the
    # annual-cap rounding (e.g. many states adjust February so 11×monthly +
    # this equals the statutory annual ceiling). Null for every other
    # rule_type — additive, no existing row's behavior changes.
    flat_amount           = Column(Numeric(10, 2), nullable=True)
    adjustment_amount     = Column(Numeric(10, 2), nullable=True)
    # PT_FLAT only (ZP-TAX-IN-2026-27-001 §12.1's state_rule schema field
    # of the same name): which income figure this bracket's min_amount/
    # max_amount are measured against. NULL/"MONTHLY_WAGE" (every existing
    # PT_FLAT row, e.g. Telangana) means "and above" — engine/countries/
    # india.py's exact existing behavior — is unaffected;
    # "HALF_YEAR_INCOME" (Greater Chennai Corporation's local schedule,
    # §14.1) matches an average half-yearly income instead. "ANNUAL_SALARY"/
    # "OTHER" are recognized per the document's own enum but have no
    # sourced India state using them yet — reserved, not implemented.
    assessment_basis      = Column(String(20), nullable=True)
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

    # Per-rule-family effective dating — same rationale/scope as
    # ContributionRate.effective_from/effective_to above (ZP-TAX-UK-2026-
    # 27-001 §3.2 gap-closure Part 1A, 2026-09-09). NULL means "use the
    # parent JurisdictionPack's window"; only enforced by tax_resolver.py's
    # canonical-pack resolution path.
    effective_from        = Column(Date, nullable=True)
    effective_to          = Column(Date, nullable=True)

    # Per-rule evidence — same rationale as ContributionRate.
    # source_document_id above (ZP-TAX-UK-2026-27-001 §4.2 gap-closure
    # Part 1B, 2026-09-09). NULL for every row today.
    source_document_id   = Column(Integer, ForeignKey("payroll_source_artifacts.id"), nullable=True)

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
    # UK RTI (ZP-TAX-UK-2026-27-001 §18 gap-closure Part 9, 2026-09-09) —
    # every FPS/EPS's Employer Details section requires both identifiers;
    # neither is the same as employer_id/tax_no above (those are the
    # jurisdiction-generic registration fields every country's Compliance
    # Details form already collects). NULL for every org until entered —
    # no UI sets these yet, same disclosed "no admin surface yet" pattern
    # as bc_eht_employer_classification/connected_group_code elsewhere.
    paye_reference             = Column(String(20), nullable=True)
    accounts_office_reference  = Column(String(20), nullable=True)
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

    # Australia regional-employer payroll-tax eligibility (VIC regional
    # rate, QLD regional discount, ZP-TAX-AU-2026-27-001 §17) — same
    # disclosed "no UI yet" gap as bc_eht_employer_classification/
    # qc_hsf_employer_category above; NULL is treated as ordinary
    # (metropolitan) status. Cross-org grouping/DGE aggregation for state
    # payroll-tax thresholds reuses Organization.connected_group_code
    # (the same field UK's Apprenticeship Levy sharing and Canada's
    # associated-employer-group mechanism already use) rather than a new
    # AU-specific group column.
    au_payroll_tax_regional_status = Column(String(20), nullable=True)
    # §18 "Charity / public-benefit exemptions" employer overlay — "requires
    # authority/legal eligibility and often applies only to qualifying
    # wages/activities." The ELIGIBILITY DETERMINATION itself is a human/
    # legal judgment call this codebase cannot make (no computable test is
    # given anywhere in the source document — same reasoning SA's reduced-
    # rate band raises rather than guesses for); this column only stores
    # that determination once a human has made it (Tax Ops data entry
    # against a real authority ruling, same evidentiary footing as
    # EmployerTaxProfile's own EMPLOYER_NOTICE rows), and
    # calculate_au_state_payroll_tax short-circuits to $0 while it's True.
    # NULL/False (every org today) is ordinary (not exempt) — ordinary
    # calculation is completely unaffected. The document's own "often
    # applies only to qualifying wages/activities" nuance (a PARTIAL
    # exemption scoped to specific activities) is NOT modeled — this is a
    # deliberate, disclosed simplification to a whole-org binary exemption,
    # since no wage/activity-level qualification rule is given either.
    au_payroll_tax_charity_exempt = Column(Boolean, nullable=True)

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
    # Tax packs: Draft | In Review | QA | Approved | Active | Deprecated |
    # Retired — per spec Section 5/17. POLICY packs use only "Draft" |
    # "Active" (see set_jurisdiction_pack_status: any other status on a
    # policy pack is rejected) — policy lifecycle intentionally has no
    # approval/review stage.

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


class PackHotfixActivation(Base):
    """A record of an emergency hotfix activation of a JurisdictionPack —
    Super Admin UI Part 11 (§19, 2026-09-09). The normal path
    (set_jurisdiction_pack_status) refuses to activate a pack without a
    distinct approver (maker-checker). Hotfix mode deliberately bypasses
    that single gate for a genuine production emergency (e.g. a live
    statutory bug actively producing wrong payslips) — but ONLY that one
    gate: every other guard (date-range overlap, inverted dates) still
    applies unchanged. In exchange, hotfix mode REQUIRES a mandatory
    incident reference and justification, and ALWAYS creates this row,
    flagged for mandatory retrospective review — the accountability
    maker-checker would normally have provided is deferred to an
    after-the-fact human review, never silently skipped."""
    __tablename__ = "payroll_pack_hotfix_activations"

    id                  = Column(Integer, primary_key=True, index=True)
    jurisdiction_pack_id = Column(Integer, ForeignKey("payroll_jurisdiction_packs.id"), nullable=False, index=True)

    incident_id         = Column(String(100), nullable=False)
    justification        = Column(Text, nullable=False)

    activated_by_id      = Column(Integer, ForeignKey("users.id"), nullable=True)
    activated_at         = Column(DateTime(timezone=True), server_default=func.now())

    # Mandatory retrospective review — never auto-closes itself.
    reviewed             = Column(Boolean, nullable=False, default=False, server_default="false")
    reviewed_by_id       = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at          = Column(DateTime(timezone=True), nullable=True)
    review_notes         = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_pack_hotfix_pack", "jurisdiction_pack_id"),
        Index("ix_pack_hotfix_unreviewed", "reviewed"),
    )

    def __repr__(self):
        return f"<PackHotfixActivation pack={self.jurisdiction_pack_id} incident={self.incident_id} reviewed={self.reviewed}>"


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
    entity_type    = Column(String(50), nullable=False)    # "jurisdiction_pack" | "tax_slab" | "contribution_rate" | ...
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

    # NULLABLE since ZP-TAX-UK-2026-27-001 §18 gap-closure Part 9
    # (2026-09-09) — every report type before RTI was tied to exactly one
    # finalized PayrollRun, but a P45/P60 is per-EMPLOYEE (triggered by a
    # leaving date / tax-year end, not a specific run) and an EPS is
    # per-PERIOD at the whole-employer level (an employer can file an EPS
    # for a period with zero payroll runs at all — e.g. "no employees
    # paid this period"). Every report generated before this column was
    # widened has this set exactly as before; only the new non-run-based
    # generators ever leave it NULL.
    payroll_run_id = Column(Integer, ForeignKey("payroll_runs.id"), nullable=True, index=True)
    # Set only for a per-employee report (P45/P60) — lets a caller filter
    # "all reports for this employee" without parsing scope_key. NULL for
    # every run-based and period-based report.
    employee_id    = Column(Integer, ForeignKey("payroll_employees.id"), nullable=True, index=True)
    # Set only when payroll_run_id is NULL — the uniqueness key for a
    # non-run-based report ("EMPLOYEE:<id>" for P45/P60, "PERIOD:<tax_
    # year>:<period_key>" for EPS), since the existing (org, run,
    # template) uniqueness below can't express "one Generated P60 per
    # employee per tax year" or "one Generated EPS per employer per
    # period." NULL for every run-based report — completely unaffected.
    scope_key      = Column(String(100), nullable=True)

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
            postgresql_where=text("status = 'Generated' AND payroll_run_id IS NOT NULL"),
            sqlite_where=text("status = 'Generated' AND payroll_run_id IS NOT NULL"),
        ),
        # The non-run-based counterpart (Part 9, 2026-09-09) — one
        # Generated row per (org, template, scope_key) at a time, exactly
        # mirroring the run-based index above but keyed by scope_key
        # instead of payroll_run_id.
        Index(
            "uq_generated_report_org_scope_template_active",
            "organization_id", "scope_key", "report_template_id",
            unique=True,
            postgresql_where=text("status = 'Generated' AND scope_key IS NOT NULL"),
            sqlite_where=text("status = 'Generated' AND scope_key IS NOT NULL"),
        ),
    )

    def __repr__(self):
        return f"<GeneratedReport org={self.organization_id} run={self.payroll_run_id} scope={self.scope_key} template={self.report_template_id} status={self.status}>"


class RtiSubmission(Base):
    """Submission-queue/status tracking for a GeneratedReport that is
    itself an HMRC RTI filing (FPS/EPS/P45) — ZP-TAX-UK-2026-27-001 §18.3
    gap-closure Part 9B, 2026-09-09.

    This table is DELIBERATELY a status tracker only — it never actually
    transmits anything to HMRC. Real transmission needs a Government
    Gateway enrolment and digital credentials this codebase has no way
    to obtain; when those exist, the only new work should be wiring a
    real API call into the DRAFT -> SUBMITTED transition below, not a
    redesign of this table. Until then, every transition past READY is
    driven by a human manually filing through HMRC's own tools and then
    recording what happened here — an honest record of real-world state,
    not a working pipeline.
    """
    __tablename__ = "payroll_rti_submissions"

    id                  = Column(Integer, primary_key=True, index=True)
    organization_id     = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    generated_report_id = Column(Integer, ForeignKey("payroll_generated_reports.id"), nullable=False, index=True)

    # FPS | EPS | P45 | STP | SUPERSTREAM — denormalized from the
    # GeneratedReport's own report_type for cheap listing, same
    # convention GeneratedReport itself uses for report_type against
    # ReportTemplate. Widened to Australia's STP/SuperStream (ZP-TAX-AU-
    # 2026-27-001 §12, Phase 9, 2026-09-17) the same way it was already
    # widened to India's forms — see the RTI & Forms summary section
    # below.
    submission_type = Column(String(20), nullable=False)
    # Which authority schema/transport version this specific submission
    # was built against (e.g. "NAT-STP-2026-27" or a SuperStream
    # Contributions Standard version) — independent of the tax-rule
    # package version (tracked instead via GeneratedReport.
    # applicable_tax_pack_version). NULL for every existing UK row
    # (predates this column; RTI's own schema versioning has never been
    # tracked here) and optional going forward — closes AU-AC23/AU-AC24
    # (ZP-TAX-AU-2026-27-001 §12, gap identified 2026-09-16, closed
    # 2026-09-17) without inventing a second, AU-only tracking mechanism.
    schema_version = Column(String(30), nullable=True)

    # DRAFT -> READY -> SUBMITTED -> ACKNOWLEDGED | REJECTED. DRAFT is the
    # state a fresh row starts in; READY means a human has reviewed it and
    # judged it ready to file; SUBMITTED/ACKNOWLEDGED/REJECTED are
    # currently only ever set by a human recording what they did outside
    # this system (see class docstring) — never by an automated call.
    status = Column(String(20), nullable=False, default="DRAFT", server_default="DRAFT")

    # Populated only once a real Government Gateway integration exists —
    # NULL for every row today, by construction (nothing in this codebase
    # can obtain one yet).
    hmrc_correlation_id = Column(String(100), nullable=True)

    submitted_at    = Column(DateTime(timezone=True), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    rejection_reason = Column(Text, nullable=True)

    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_rti_submission_org_status", "organization_id", "status"),
    )

    def __repr__(self):
        return f"<RtiSubmission org={self.organization_id} type={self.submission_type} status={self.status}>"


class TestCertificationRun(Base):
    """One execution of the HMRC golden-test harness (Part 10) —
    Super Admin UI Part 11's "Test Certification" tab (§19, 2026-09-09)
    reads this table for pass/fail history rather than reading raw pytest
    output, which isn't persisted or queryable anywhere. `real_case_count`
    is tracked SEPARATELY from `total_cases`/`passed_cases` so the UI can
    honestly show "0 real HMRC cases" instead of implying certification
    happened when it structurally couldn't (see tests/hmrc_golden's own
    package docstring — Part 10 is blocked on real HMRC files)."""
    __tablename__ = "payroll_test_certification_runs"

    id                = Column(Integer, primary_key=True, index=True)
    run_at            = Column(DateTime(timezone=True), server_default=func.now())
    triggered_by_id   = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Generalized to Canada (gap-closure Phase 8, 2026-09-11) — every row
    # before this column existed was implicitly UK (the harness's only
    # jurisdiction at the time), so it defaults to "UK" rather than NULL,
    # keeping every existing run's history correctly labeled.
    jurisdiction_country = Column(String(10), nullable=False, default="UK", server_default="UK")

    real_case_count   = Column(Integer, nullable=False, default=0)
    total_cases       = Column(Integer, nullable=False, default=0)
    passed_cases      = Column(Integer, nullable=False, default=0)
    failed_cases      = Column(Integer, nullable=False, default=0)

    # PASS | FAIL | NO_REAL_CASES — NO_REAL_CASES (real_case_count == 0)
    # is deliberately NOT the same as PASS: an empty real-case set proves
    # nothing about correctness, and the UI must never conflate the two.
    status            = Column(String(20), nullable=False)

    failure_details   = Column(JSON, nullable=True)  # [{"case": "...", "field": "...", "expected": ..., "actual": ...}, ...]

    __table_args__ = (
        Index("ix_test_cert_run_at", "run_at"),
    )

    def __repr__(self):
        return f"<TestCertificationRun id={self.id} status={self.status} real_cases={self.real_case_count}>"


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

    # UK statutory leave wiring (ZP-TAX-UK-2026-27-001 §11/§12 gap-closure
    # Part 7A, 2026-09-09) — set only when leave_type is one of the 6
    # statutory business-language values (maternity/paternity/adoption/
    # sharedParental/bereavement/neonatal) AND the rollout switch is on.
    # statutory_pay_type is the matching HMRC code (SMP/SPP/SAP/SHPP/SPBP/
    # SNCP) uk.py's calculate_statutory_family_pay() actually expects.
    # AWE and the total are computed ONCE at approval time and frozen here
    # — never recomputed later, so a subsequent payslip correction that
    # would shift a live AWE calculation can never retroactively change
    # what was already promised/paid for this claim. total_amount stays
    # NULL (not 0) when the underlying calculation failed closed (e.g.
    # insufficient pay history for AWE, or an unconfigured rate) —
    # statutory_pay_note carries the reason either way.
    statutory_pay_type       = Column(String(10), nullable=True)
    statutory_awe_snapshot   = Column(Numeric(12, 2), nullable=True)
    statutory_pay_total_amount = Column(Numeric(12, 2), nullable=True)
    statutory_pay_note       = Column(String(255), nullable=True)

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
    # Reviewer independence (ZP-TAX-US-2026-001 §14.2 "independent
    # reviewer", gap-closure Plan Phase 4) — unlike JurisdictionPack
    # (which already has created_by_id/updated_by_id and a real
    # maker!=checker gate), this table previously had NO way to even
    # detect the same person creating and "reviewing" their own source
    # artifact. Nullable — every artifact created before this field
    # existed has no creator on record, so mark_source_artifact_reviewed
    # only enforces the independence check when this IS set.
    created_by_id         = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Real preserved-file storage (ZP-TAX-US-2026-001 §14.2's "source URL
    # and/or preserved file", gap-closure Plan Phase 4) — reuses the SAME
    # app.core.object_storage abstraction org logos already use (local
    # disk by default; transparently switches to GCS if
    # PAYROLL_GCS_BUCKET is ever configured, no code change needed here).
    # `file_path` is the storage REFERENCE (a local path or a gs:// URI),
    # never a web-servable URL directly — see the dedicated download
    # endpoint. checksum_sha256 above is computed FROM this file's actual
    # bytes at upload time (service.upload_source_artifact_file) — real
    # and verifiable, unlike a hand-typed value.
    file_path             = Column(String(500), nullable=True)
    original_filename     = Column(String(255), nullable=True)
    content_type          = Column(String(100), nullable=True)
    file_size_bytes       = Column(Integer, nullable=True)

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

    # Phase 8DI — additive, nullable link to the Germany Compliance Pack
    # version (payroll_jurisdiction_packs, pack_type="tax", jurisdiction_
    # country="DE") this row was seeded/published under. NULL is valid
    # and preserves exact pre-8DI behavior (existing effective-dated
    # PUBLISHED-status resolution, no pack involved at all) — see
    # service.py's resolve_applicable_germany_pack()/_resolve_germany_
    # calc_inputs() for how this becomes an ADDITIVE filter only when a
    # pack applies to the payroll date; it never narrows or replaces the
    # existing effective-dating/status logic on its own.
    jurisdiction_pack_id = Column(Integer, ForeignKey("payroll_jurisdiction_packs.id"), nullable=True)

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

    # Phase 8DI — additive, nullable link to the Germany Compliance Pack
    # version (payroll_jurisdiction_packs, pack_type="tax", jurisdiction_
    # country="DE") this row was seeded/published under. NULL is valid
    # and preserves exact pre-8DI behavior (existing effective-dated
    # PUBLISHED-status resolution, no pack involved at all) — see
    # service.py's resolve_applicable_germany_pack()/_resolve_germany_
    # calc_inputs() for how this becomes an ADDITIVE filter only when a
    # pack applies to the payroll date; it never narrows or replaces the
    # existing effective-dating/status logic on its own.
    jurisdiction_pack_id = Column(Integer, ForeignKey("payroll_jurisdiction_packs.id"), nullable=True)

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
# SUPERSEDED (Phase 7, re-confirmed Phase 8BE): the "germany.py does NOT
# read from this table" sentence above was accurate at Phase 5 but is
# now stale — Phase 7 wired both branches in for real. germany.py resolves
# and traces RV_ALV and GKV_PV ceilings independently from THIS table
# (see germany.py's ceiling resolution around the RV/ALV and GKV/PV
# calculation calls, and service.py's resolve_germany_contribution_ceiling
# branch parameter) — the "single shared ContributionRate ceiling" read
# this paragraph describes is the pre-Phase-7 state, not current
# behavior. Left here rather than rewritten so the phase history stays
# legible; do not cite this paragraph alone as current production status.
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

    # Phase 8DI — additive, nullable link to the Germany Compliance Pack
    # version (payroll_jurisdiction_packs, pack_type="tax", jurisdiction_
    # country="DE") this row was seeded/published under. NULL is valid
    # and preserves exact pre-8DI behavior (existing effective-dated
    # PUBLISHED-status resolution, no pack involved at all) — see
    # service.py's resolve_applicable_germany_pack()/_resolve_germany_
    # calc_inputs() for how this becomes an ADDITIVE filter only when a
    # pack applies to the payroll date; it never narrows or replaces the
    # existing effective-dating/status logic on its own.
    jurisdiction_pack_id = Column(Integer, ForeignKey("payroll_jurisdiction_packs.id"), nullable=True)

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


# ── Germany: Minijob / Midijob statutory parameters (Phase 8BK) ─────────
# Phase 8BJ found that, unlike RV/ALV/GKV (which already resolve through
# the canonical JurisdictionPack/rate_map mechanism once wired in — see
# that phase's report) and PV (already effective-dated via
# GermanyPvConfiguration above), Minijob's own flat statutory rates and
# Midijob's own sliding-scale formula coefficients were, and remained,
# plain hardcoded Python constants (hardcoded_defaults.py) with NO
# effective dating and NO override mechanism at all — not even the
# weaker rate_map fallback pattern RV/ALV/GKV had before Phase 8BJ.
#
# Deliberately NOT routed through ContributionRate/rate_map: this
# codebase's own pre-existing comment (engine/germany_pap/core.py, the
# "Minijob / Midijob" section header) records that Minijob/Midijob were
# intentionally kept OFF the canonical-pack/rate_map indirection because
# the supplied 2026 documentation gives these as fixed statutory
# percentages/coefficients, not DB-overridable canonical rates for an
# ORGANIZATION to opt into — introducing that indirection here would
# invent an org-override mechanism the statute doesn't describe. That
# reasoning is preserved, not overridden, by this table: there is no
# organization_id column here (mirroring GermanyContributionCeiling/
# GermanyHealthFund/GermanyPvConfiguration above, none of which have one
# either) — every row is a global, federal statutory fact, never a
# tenant-configurable value, and no request payload/API caller can set
# or influence one (Super-Admin-only write path, see service.py).
#
# Deliberately NOT folded into GermanyPvConfiguration or a per-concept
# table: these 13 parameters don't share a single natural keyed identity
# the way PV's (child_category, is_saxony) pair does — they're a flat
# list of independent federal constants (a threshold, several flat
# rates, four formula coefficients), so a generic parameter_code + value
# shape (mirroring the column list this phase's own brief specifies)
# is the correct minimal shape, not one bespoke column per value.
class GermanyMinijobMidijobParameter(Base):
    """One effective-dated version of one Minijob/Midijob statutory
    parameter (a threshold, a flat contribution rate, or a Midijob
    formula coefficient) — see MINIJOB_MIDIJOB_PARAMETER_CODES in
    service.py for the closed vocabulary of valid `parameter_code`
    values and what each one feeds into."""
    __tablename__ = "payroll_germany_minijob_midijob_parameters"

    id                    = Column(Integer, primary_key=True, index=True)

    # Closed vocabulary, validated in the service layer (see
    # service._GERMANY_MINIJOB_MIDIJOB_PARAMETER_CODES) — same convention
    # as GermanyContributionCeiling.branch above, not a DB CHECK
    # constraint.
    parameter_code        = Column(String(50), nullable=False, index=True)

    # High-precision Decimal: Midijob's own formula coefficients are
    # published to 10 decimal places (e.g. 291.8744452399) — a coarser
    # column would silently truncate them and drift the Midijob
    # Übergangsbereich calculation away from the officially published
    # coefficient. Every parameter_code, including plain percentages and
    # the EUR threshold, uses this same column (the "value_type" column
    # below records what the number MEANS, not a different storage
    # shape).
    value                  = Column(Numeric(24, 10), nullable=False)

    # "PERCENTAGE" | "EUR_THRESHOLD" | "COEFFICIENT_MULTIPLIER" |
    # "COEFFICIENT_SUBTRAHEND" — documents what `value` represents (a
    # percentage point figure, a Euro amount, or one of the two distinct
    # roles a Midijob formula coefficient can play) so a caller/UI never
    # has to infer it from the parameter_code string alone.
    value_type             = Column(String(30), nullable=False)

    label                  = Column(String(150), nullable=False)

    effective_from         = Column(Date, nullable=False)
    effective_to           = Column(Date, nullable=True)   # NULL = open-ended / current

    # DRAFT | VERIFIED | APPROVED | PUBLISHED | SUPERSEDED — identical
    # vocabulary/lifecycle to every sibling Germany registry above.
    status                 = Column(String(20), nullable=False, default="DRAFT", server_default="DRAFT")

    # Evidence — same SourceArtifact convention as every sibling registry.
    # Nullable because a parameter can be entered as DRAFT before its
    # source citation is attached, exactly like the others; PUBLISHing
    # still requires appropriate evidence per the same service-layer gate
    # pattern used elsewhere (see set_health_fund_status's own
    # requirement for a bound source, mirrored here).
    authority_source_id    = Column(Integer, ForeignKey("payroll_source_artifacts.id"), nullable=True)

    # Phase 8DI — additive, nullable link to the Germany Compliance Pack
    # version (payroll_jurisdiction_packs, pack_type="tax", jurisdiction_
    # country="DE") this row was seeded/published under. NULL is valid
    # and preserves exact pre-8DI behavior (existing effective-dated
    # PUBLISHED-status resolution, no pack involved at all) — see
    # service.py's resolve_applicable_germany_pack()/_resolve_germany_
    # calc_inputs() for how this becomes an ADDITIVE filter only when a
    # pack applies to the payroll date; it never narrows or replaces the
    # existing effective-dating/status logic on its own.
    jurisdiction_pack_id = Column(Integer, ForeignKey("payroll_jurisdiction_packs.id"), nullable=True)

    created_by_id          = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by_id          = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_by_id         = Column(Integer, ForeignKey("users.id"), nullable=True)
    previous_version_id    = Column(Integer, ForeignKey("payroll_germany_minijob_midijob_parameters.id"), nullable=True)

    created_at             = Column(DateTime(timezone=True), server_default=func.now())
    updated_at             = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_minijob_midijob_parameter_code_period", "parameter_code", "effective_from"),
        # Same "at most one open-ended row per identity" guard as every
        # sibling registry — full overlap prevention across ALL rows
        # (open or closed) for a parameter_code is enforced at the
        # service layer (see _validate_minijob_midijob_parameter_no_overlap),
        # same reasoning as GermanyContributionCeiling's identical guard.
        Index(
            "uq_minijob_midijob_parameter_one_open_period",
            "parameter_code",
            unique=True,
            postgresql_where=text("effective_to IS NULL"),
            sqlite_where=text("effective_to IS NULL"),
        ),
    )

    def __repr__(self):
        return (
            f"<GermanyMinijobMidijobParameter id={self.id} parameter_code={self.parameter_code!r} "
            f"value={self.value} status={self.status}>"
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

    # Phase 8DI — additive, nullable link to the Germany Compliance Pack
    # version (payroll_jurisdiction_packs, pack_type="tax", jurisdiction_
    # country="DE") this row was seeded/published under. NULL is valid
    # and preserves exact pre-8DI behavior (existing effective-dated
    # PUBLISHED-status resolution, no pack involved at all) — see
    # service.py's resolve_applicable_germany_pack()/_resolve_germany_
    # calc_inputs() for how this becomes an ADDITIVE filter only when a
    # pack applies to the payroll date; it never narrows or replaces the
    # existing effective-dating/status logic on its own.
    jurisdiction_pack_id = Column(Integer, ForeignKey("payroll_jurisdiction_packs.id"), nullable=True)

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

    # Phase 8DI — additive, nullable link to the Germany Compliance Pack
    # version (payroll_jurisdiction_packs, pack_type="tax", jurisdiction_
    # country="DE") this row was seeded/published under. NULL is valid
    # and preserves exact pre-8DI behavior (existing effective-dated
    # PUBLISHED-status resolution, no pack involved at all) — see
    # service.py's resolve_applicable_germany_pack()/_resolve_germany_
    # calc_inputs() for how this becomes an ADDITIVE filter only when a
    # pack applies to the payroll date; it never narrows or replaces the
    # existing effective-dating/status logic on its own.
    jurisdiction_pack_id = Column(Integer, ForeignKey("payroll_jurisdiction_packs.id"), nullable=True)

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

    # Phase 8DI — additive, nullable link to the Germany Compliance Pack
    # version (payroll_jurisdiction_packs, pack_type="tax", jurisdiction_
    # country="DE") this row was seeded/published under. NULL is valid
    # and preserves exact pre-8DI behavior (existing effective-dated
    # PUBLISHED-status resolution, no pack involved at all) — see
    # service.py's resolve_applicable_germany_pack()/_resolve_germany_
    # calc_inputs() for how this becomes an ADDITIVE filter only when a
    # pack applies to the payroll date; it never narrows or replaces the
    # existing effective-dating/status logic on its own.
    jurisdiction_pack_id = Column(Integer, ForeignKey("payroll_jurisdiction_packs.id"), nullable=True)

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

    # Phase 8DI — additive, nullable link to the Germany Compliance Pack
    # version (payroll_jurisdiction_packs, pack_type="tax", jurisdiction_
    # country="DE") this row was seeded/published under. NULL is valid
    # and preserves exact pre-8DI behavior (existing effective-dated
    # PUBLISHED-status resolution, no pack involved at all) — see
    # service.py's resolve_applicable_germany_pack()/_resolve_germany_
    # calc_inputs() for how this becomes an ADDITIVE filter only when a
    # pack applies to the payroll date; it never narrows or replaces the
    # existing effective-dating/status logic on its own.
    jurisdiction_pack_id = Column(Integer, ForeignKey("payroll_jurisdiction_packs.id"), nullable=True)

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
    locality_type         = Column(String(30), nullable=False)   # COUNTY | MUNICIPAL | SCHOOL_DISTRICT | PSD_EIT_LST | OH_MUNI_CREDIT
    locality_name         = Column(String(200), nullable=True)
    resident_rate_pct     = Column(Numeric(6, 4), nullable=True)
    nonresident_rate_pct  = Column(Numeric(6, 4), nullable=True)
    flat_amount           = Column(Numeric(12, 2), nullable=True)   # for LST-style flat local taxes
    tax_collector_id      = Column(String(100), nullable=True)      # remittance routing destination
    # Tiered/progressive local tax (Production-Readiness Plan Phase 4,
    # 2026-09-15) — for the handful of localities (Maryland's Anne
    # Arundel/Frederick counties, New York City) whose own published rate
    # is a real marginal bracket table, not a single flat percentage.
    # {"SINGLE": {"deduction": N, "brackets": [{"min","max","rate"}, ...]},
    # "MFJ": {...}} — see engine/countries/us.py's _tiered_locality_tax
    # for how this is consumed; None (every locality before this column
    # existed, and every ordinary flat-rate locality since) is a complete
    # no-op, resident_rate_pct/nonresident_rate_pct/flat_amount still
    # drive calculation exactly as before.
    bracket_schedule      = Column(JSON, nullable=True)
    # PA Local Services Tax (LST) low-income exemption threshold —
    # Production-Readiness Plan Phase 4, 2026-09-16. Only meaningful when
    # locality_type == "PSD_EIT_LST" and flat_amount is also set (flat_amount
    # there means the LST annual fee, not a replacement for the EIT rate —
    # see engine/countries/us.py's own local-tax block). An employee whose
    # annual gross is below this threshold owes $0 LST; None means no
    # exemption is configured (LST applies to every income level), never a
    # guessed default. Real published examples: Pittsburgh/Allentown use
    # $12,000 (PA's statewide-default floor for any LST over $10/year),
    # Harrisburg uses $24,500 (an Act 47 distressed-city exception).
    lst_exemption_threshold = Column(Numeric(12, 2), nullable=True)

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

    # Phase 8DI — additive, nullable link to the Germany Compliance Pack
    # version (payroll_jurisdiction_packs, pack_type="tax", jurisdiction_
    # country="DE") this row was seeded/published under. NULL is valid
    # and preserves exact pre-8DI behavior (existing effective-dated
    # PUBLISHED-status resolution, no pack involved at all) — see
    # service.py's resolve_applicable_germany_pack()/_resolve_germany_
    # calc_inputs() for how this becomes an ADDITIVE filter only when a
    # pack applies to the payroll date; it never narrows or replaces the
    # existing effective-dating/status logic on its own.
    jurisdiction_pack_id = Column(Integer, ForeignKey("payroll_jurisdiction_packs.id"), nullable=True)

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


class StateLocalProgramReadiness(Base):
    """ZP-TAX-IN-2026-27-001 §16's "India state/local readiness registry" —
    one row per (state/UT, optional local authority, statutory program),
    even when the applicable status is NOT_APPLICABLE or SOURCE_REQUIRED
    ("This prevents silent gaps when a tenant adds a work location").

    Platform-wide by construction (jurisdiction_country, not IN-only) even
    though every row seeded so far is India's, matching this schema's
    existing country-generic convention (TaxabilityRule/SourceArtifact
    above). Deliberately INFORMATIONAL/admin-facing only in this pass —
    no calculation or onboarding path reads legal_status to block
    anything yet (same dormant-registry convention as
    _VALIDATION_ENABLED_COUNTRIES in engine/countries/shared.py: fail-
    closed ENFORCEMENT is a separate, deliberate decision from having the
    registry data exist)."""
    __tablename__ = "payroll_state_local_program_readiness"

    id                        = Column(Integer, primary_key=True, index=True)
    jurisdiction_country      = Column(String(10), nullable=False)
    jurisdiction_state        = Column(String(100), nullable=False)
    # NULL = state-level row (e.g. Karnataka STATE_PT); set = a specific
    # local authority's own row (e.g. Chennai's LOCAL_PT), same null-means-
    # broader-scope convention as ContributionRate/TaxSlab.jurisdiction_locality.
    jurisdiction_locality     = Column(String(100), nullable=True)
    program                   = Column(String(30), nullable=False)   # STATE_PT | LOCAL_PT | LWF | OTHER_STATE_PAYROLL
    legal_status              = Column(String(20), nullable=False, default="SOURCE_REQUIRED", server_default="SOURCE_REQUIRED")  # APPLICABLE | NOT_APPLICABLE | SOURCE_REQUIRED
    local_authority_required  = Column(Boolean, nullable=False, default=False, server_default="false")
    registration_required     = Column(Boolean, nullable=False, default=False, server_default="false")
    source_document_id        = Column(Integer, ForeignKey("payroll_source_artifacts.id"), nullable=True)
    notes                     = Column(String(500), nullable=True)
    created_at                = Column(DateTime(timezone=True), server_default=func.now())
    updated_at                = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint(
            "jurisdiction_country", "jurisdiction_state", "jurisdiction_locality", "program",
            name="uq_state_local_program_readiness_scope",
        ),
    )

    def __repr__(self):
        locality = f"/{self.jurisdiction_locality}" if self.jurisdiction_locality else ""
        return f"<StateLocalProgramReadiness {self.jurisdiction_country}-{self.jurisdiction_state}{locality} {self.program}={self.legal_status}>"


class SalaryTdsDeclaration(Base):
    """ZP-TAX-IN-2026-27-001 §6.2 Form 122 — an employee's own versioned
    declaration of prior-employer salary/TDS, other specified income, and
    house-property loss for one tax year (§6.1 step 4's "employee-
    provided other-employer salary / eligible other income / house-
    property loss and tax already deducted"). Feeds the salary TDS
    projection (engine/countries/india.py) once Approved — see
    service.py's get_india_salary_tds_inputs.

    A NEW declaration is a new row, never an edit — the prior Approved
    row (if any) is marked Superseded, matching this schema's existing
    immutable-versioning convention (JurisdictionPack, ReportTemplate,
    StatutoryFilingCalendar)."""
    __tablename__ = "payroll_salary_tds_declarations"

    id              = Column(Integer, primary_key=True, index=True)
    employee_id     = Column(Integer, ForeignKey("payroll_employees.id"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    tax_year        = Column(String(20), nullable=False)   # "2026-27"

    prior_employer_salary       = Column(Numeric(14, 2), nullable=False, default=0)
    prior_employer_tds_deducted = Column(Numeric(14, 2), nullable=False, default=0)
    other_income                = Column(Numeric(14, 2), nullable=False, default=0)
    house_property_loss         = Column(Numeric(14, 2), nullable=False, default=0)

    status         = Column(String(20), nullable=False, default="Draft")  # Draft | Submitted | Approved | Superseded
    submitted_at   = Column(DateTime(timezone=True), nullable=True)
    approved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at    = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<SalaryTdsDeclaration employee={self.employee_id} year={self.tax_year} status={self.status}>"


class SalaryTdsClaim(Base):
    """ZP-TAX-IN-2026-27-001 §6.2 Form 124 — one employee claim/evidence
    row for a Chapter VIII deduction or exemption used to estimate salary
    TDS (successor workflow to the old Form 12BB). §4.2: "Accept only
    claim types valid for old-regime payroll TDS... source-driven caps
    and eligibility" — the document names no per-claim-type ceiling
    itself (unlike the standard-deduction/rebate/PF figures elsewhere in
    this pack), so this build sums Approved claims uncapped rather than
    inventing a threshold; a real per-type cap can be layered in once a
    certified source gives one, the same fail-closed-not-guessed
    convention as every other unsourced figure in this codebase.

    evidence_reference is free text (a receipt number/description), not
    an uploaded file — no file-storage capability exists in this build."""
    __tablename__ = "payroll_salary_tds_claims"

    id              = Column(Integer, primary_key=True, index=True)
    employee_id     = Column(Integer, ForeignKey("payroll_employees.id"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    tax_year        = Column(String(20), nullable=False)

    claim_type         = Column(String(50), nullable=False)   # "SECTION_80C" | "HRA_EXEMPTION" | "HOME_LOAN_INTEREST" | "LTA" | "OTHER"
    claimed_amount      = Column(Numeric(14, 2), nullable=False)
    evidence_reference  = Column(String(300), nullable=True)

    status            = Column(String(20), nullable=False, default="Draft")  # Draft | Submitted | Approved | Rejected | Superseded
    rejection_reason  = Column(String(300), nullable=True)
    approved_by_id    = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at       = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<SalaryTdsClaim employee={self.employee_id} type={self.claim_type} status={self.status}>"


class EmployeeBenefitValuation(Base):
    """ZP-TAX-IN-2026-27-001 §6.2/§7 Form 123 — the employer's own
    recorded taxable value of a perquisite/profit-in-lieu-of-salary
    benefit for one employee (car, accommodation, stock benefit,
    employer-paid obligation, ...).

    DISCLOSED SCOPE: this document gives no perquisite VALUATION FORMULA
    (car/accommodation/ESOP valuation rules are notified separately and
    are not in this pack) — Zoiko does not compute a perquisite's taxable
    value here; the organization enters its own already-determined value,
    which then feeds Form 123 generation and both regimes' salary TDS
    projection (perquisites are salary income under both regimes, unlike
    Chapter VIII claims, which are Old-regime only)."""
    __tablename__ = "payroll_employee_benefit_valuations"

    id              = Column(Integer, primary_key=True, index=True)
    employee_id     = Column(Integer, ForeignKey("payroll_employees.id"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    tax_year        = Column(String(20), nullable=False)

    benefit_type   = Column(String(50), nullable=False)   # "CAR" | "ACCOMMODATION" | "STOCK_BENEFIT" | "EMPLOYER_PAID_OBLIGATION" | "OTHER"
    description    = Column(String(300), nullable=True)
    taxable_value  = Column(Numeric(14, 2), nullable=False)

    status     = Column(String(20), nullable=False, default="Draft")   # Draft | Issued | Superseded
    issued_at  = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<EmployeeBenefitValuation employee={self.employee_id} type={self.benefit_type} status={self.status}>"


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


class PayrollNiReliefFact(Base):
    """UK National Insurance category relief eligibility evidence
    (ZP-TAX-UK-2026-27-001 §9.1/§9.3 gap-closure Part 2, 2026-09-09) —
    "Relief eligibility is not a rate toggle... Store the eligibility
    evidence and relief start/end separately from the NI category
    letter; category changes must be effective-dated and auditable."

    One row per qualifying fact (a Freeport/Investment Zone site
    assignment, a veteran's qualifying 12-month window, an apprenticeship
    program enrolment) — deliberately its OWN table rather than more
    columns on PayrollEmployee, since an employee can accumulate several
    of these over time (e.g. a Freeport assignment that later ends, then
    years later becomes a qualifying veteran) and each needs its own
    audit trail, not an overwritable single field. Read by
    engine/countries/uk.py's derive_ni_category() via
    service.py's _load_uk_ni_relief_facts loader — never written to by
    the engine itself.

    Empty table = no fact recorded for anyone = the NI category always
    falls back to PayrollEmployee.ni_category exactly as today, even once
    the consuming switch (_UK_DERIVE_NI_CATEGORY_ENABLED_COUNTRIES) is on."""
    __tablename__ = "payroll_ni_relief_facts"

    id                = Column(Integer, primary_key=True, index=True)
    employee_id       = Column(Integer, ForeignKey("payroll_employees.id"), nullable=False, index=True)
    # FREEPORT | INVESTMENT_ZONE | VETERAN | APPRENTICE — deliberately NOT
    # including the married-women/widows reduced-rate election (B/E/I) or
    # the "already paying NI elsewhere" deferment categories (D/J/K/L/Z):
    # both require an HMRC-issued certificate (CA4139/CA2700) that is a
    # historical election, not a derivable fact — those categories stay
    # manual-only, same "never guess" discipline as every other UK figure.
    relief_type       = Column(String(20), nullable=False)
    # Free-text evidence reference — a Freeport/IZ site name or reference
    # number, or a note about the qualifying event (e.g. "left Royal Navy
    # 2026-03-01"). Not a foreign key to a separate "sites" table: no
    # other feature in this codebase yet needs to enumerate registered
    # Freeport/IZ sites as first-class entities, so a free-text evidence
    # field is the minimum honest representation, not a placeholder for
    # a table this pass doesn't otherwise need.
    reference         = Column(String(200), nullable=True)
    effective_from    = Column(Date, nullable=False)
    effective_to      = Column(Date, nullable=True)
    created_by_id     = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at        = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<PayrollNiReliefFact employee={self.employee_id} type={self.relief_type}>"


class CourtOrderedDeduction(Base):
    """A court-ordered payroll deduction (ZP-TAX-UK-2026-27-001 §17
    gap-closure Part 8, 2026-09-09) — England & Wales Attachment of
    Earnings Orders, Scottish arrestments, and Northern Ireland's own
    equivalent orders. One row per order; an employee can have several
    concurrent orders, distinguished by `priority` (lower = deducted
    first) exactly as §17 requires.

    `jurisdiction` says which of engine/countries/uk.py's THREE
    deliberately-separate calculation functions applies — the document
    is explicit that Scotland's arrestment rules must NOT be computed
    with England & Wales's AEO logic, so this is a dispatch key, never a
    cosmetic label.

    The fixed_* columns are order-specific overrides: when the issuing
    court specifies its own rate/amount/protected-earnings figure
    directly on the order (rather than "use the standard published
    table"), that value ALWAYS takes precedence over any generic banded
    rate (§17's own instruction) — NULL means "use the standard table
    for this order_type," never a guessed default.
    """
    __tablename__ = "payroll_court_ordered_deductions"

    id                = Column(Integer, primary_key=True, index=True)
    organization_id   = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    employee_id       = Column(Integer, ForeignKey("payroll_employees.id"), nullable=False, index=True)

    # ENGLAND_WALES | SCOTLAND | NORTHERN_IRELAND.
    jurisdiction      = Column(String(20), nullable=False)
    # Free-text, not an enum — the recognized set differs per
    # jurisdiction (e.g. England & Wales: AEO_PRIORITY/AEO_NON_PRIORITY/
    # COUNCIL_TAX_AEO; Scotland: EARNINGS_ARRESTMENT/CURRENT_MAINTENANCE_
    # ARRESTMENT/CONJOINED_ARRESTMENT) and may need to grow without a
    # migration.
    order_type        = Column(String(40), nullable=False)

    court_reference   = Column(String(100), nullable=True)
    issue_date        = Column(Date, nullable=True)
    start_date        = Column(Date, nullable=False)
    end_date          = Column(Date, nullable=True)

    # Lower number = higher priority when more than one order is active
    # for this employee at once. NULL = unspecified (treated as lowest
    # priority — deducted last — by the resolver, never guessed as "most
    # important").
    priority          = Column(Integer, nullable=True)

    fixed_deduction_rate_pct   = Column(Numeric(6, 3), nullable=True)
    fixed_deduction_amount     = Column(Numeric(12, 2), nullable=True)
    protected_earnings_amount  = Column(Numeric(12, 2), nullable=True)

    # Running totals against a fixed total-debt order (e.g. a Council
    # Tax AEO for a specific arrears amount) — both nullable: an
    # open-ended order (ongoing maintenance) has no total to collect.
    total_amount_to_collect    = Column(Numeric(12, 2), nullable=True)
    total_amount_collected     = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")

    status            = Column(String(20), nullable=False, default="active", server_default="active")  # active / completed / cancelled

    created_by_id     = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at        = Column(DateTime(timezone=True), server_default=func.now())
    updated_at        = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_court_order_employee", "employee_id"),
        Index("ix_court_order_org_status", "organization_id", "status"),
    )

    def __repr__(self):
        return f"<CourtOrderedDeduction employee={self.employee_id} jurisdiction={self.jurisdiction} type={self.order_type}>"


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
    # Widened from String(10) 2026-09-09 (UK gap-closure Phase 6 audit):
    # "US-CY-2026"/"CA-CY-2026" both fit 10 chars, but _uk_tax_year()'s own
    # "UK-TY-2026-27" format (service.py) is 13 chars — would have raised
    # a hard Postgres "value too long" error on the very first real UK
    # director payslip once _YTD_ACCUMULATOR_ENABLED_COUNTRIES included
    # "UK" (Phase 3). Found before ever hitting a real database — this
    # table (see migration note below) had never been written to in
    # production for ANY country until that switch flipped.
    tax_year                  = Column(String(20), nullable=False)   # "US-CY-2026" / "UK-TY-2026-27"
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
    # Widened from String(10) 2026-09-09 — same "UK-TY-2026-27" (13 chars)
    # overflow risk as PayrollYtdAccumulator.tax_year above; this table's
    # own switch (_ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES) also newly
    # includes "UK" as of Phase 3.
    tax_year                  = Column(String(20), nullable=False)   # "CA-CY-2026" / "UK-TY-2026-27"
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


class NewHireReport(Base):
    """US New Hire Reporting compliance tracking (Production-Readiness
    Plan Phase 5) — the one genuinely NEW concept in that phase, unlike
    W-2/941/940 which are all report-GENERATION against payroll already
    run. Every state requires an employer to report a new hire to a state
    registry within a short window (commonly ~20 days, but this genuinely
    varies by state — some states count from hire date, others from first
    day of work, and the exact number of days is not modeled per state
    here). One row per employee hire event, auto-created for every new US
    employee (see service.create_employee) — NOT backfilled for employees
    that existed before this feature shipped, since guessing whether an
    old hire was already reported would be worse than simply not tracking
    it. `due_date` is a SUGGESTED deadline (hire_date + a configurable
    default of 20 days), deliberately editable by an Org Admin who knows
    their state's actual requirement — never presented as an authoritative
    legal deadline."""
    __tablename__ = "payroll_new_hire_reports"

    id               = Column(Integer, primary_key=True, index=True)
    organization_id  = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    employee_id      = Column(Integer, ForeignKey("payroll_employees.id"), nullable=False, index=True)

    work_state       = Column(String(100), nullable=True)   # snapshot at creation — the employee's own work_state may change later
    hire_date        = Column(Date, nullable=False)
    due_date         = Column(Date, nullable=False)
    status           = Column(String(20), nullable=False, default="Pending", server_default="Pending")   # Pending | Filed
    filed_date       = Column(Date, nullable=True)
    filed_by_id      = Column(Integer, ForeignKey("users.id"), nullable=True)
    notes            = Column(Text, nullable=True)

    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    updated_at       = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<NewHireReport employee={self.employee_id} due={self.due_date} status={self.status}>"


class PRWithholdingCertificate(Base):
    """Puerto Rico Form 499 R-4/R-4.1 (ZP-PR-ENG-001 PR-005) — an
    employee's own versioned Puerto Rico withholding exemption
    certificate: personal exemption, dependents, deduction allowance, an
    optional married-computation election, a Military Spouses Residency
    Relief Act (MSRRA) election, and additional withholding. A NEW
    certificate is a new row, never an edit — the prior Approved row (if
    any) is marked Superseded on approval, the exact same immutable-
    versioning convention as SalaryTdsDeclaration/JurisdictionPack/
    ReportTemplate (create Draft -> submit -> approve, see
    service.create_pr_withholding_certificate/submit_.../approve_...).

    PR-006: an employee with no Approved certificate on file gets the
    current default treatment (engine/countries/puerto_rico.py's
    _PR_PERSONAL_EXEMPTION constant) — never a guessed certificate; see
    service.get_pr_certificate_inputs, whose empty-dict return for that
    case is what makes puerto_rico.py fall back to the engine default.

    Not tax-year-scoped (unlike India's SalaryTdsDeclaration) — the real
    Form 499 R-4/R-4.1 stays in effect until the employee files a new one,
    it does not expire at year-end."""
    __tablename__ = "payroll_pr_withholding_certificates"

    id              = Column(Integer, primary_key=True, index=True)
    employee_id     = Column(Integer, ForeignKey("payroll_employees.id"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    personal_exemption_amount         = Column(Numeric(12, 2), nullable=False, default=0)
    dependents_count                  = Column(Integer, nullable=False, default=0)
    dependent_exemption_per_dependent = Column(Numeric(12, 2), nullable=False, default=0)
    deduction_allowance_amount        = Column(Numeric(12, 2), nullable=False, default=0)
    optional_married_computation      = Column(Boolean, nullable=False, default=False)
    # MSRRA: a validly-elected, supported claim routes to specialist
    # validation per PR-005/PR §3's own table — this engine only records
    # the election and, once Approved, suppresses Puerto Rico wage
    # withholding for that employee (see puerto_rico.py's own comment);
    # it does not independently verify MSRRA eligibility.
    msrra_election                    = Column(Boolean, nullable=False, default=False)
    additional_withholding_amount     = Column(Numeric(12, 2), nullable=False, default=0)

    status         = Column(String(20), nullable=False, default="Draft")  # Draft | Submitted | Approved | Superseded
    submitted_at   = Column(DateTime(timezone=True), nullable=True)
    approved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at    = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<PRWithholdingCertificate employee={self.employee_id} status={self.status}>"


class SuperGuaranteeLiability(Base):
    """Australia Payday Super (ZP-TAX-AU-2026-27-001 §10, Payday Super
    Phase 2, 2026-09-16) — the one genuinely NEW concept that phase
    introduces: from 1 July 2026, Superannuation Guarantee is a discrete
    PER-PAYDAY payment obligation with its own fund-receipt deadline and
    exception state, not merely a payslip line item. Deliberately NOT a
    retrofit of RtiSubmission (a report-SUBMISSION tracker keyed to a
    GeneratedReport, with no deadline/SLA concept at all) or
    EmployerTaxProfile/PayrollYtdAccumulator (rates and running totals,
    not discrete payment events) — this is the first table in the schema
    that models "one payment obligation per payday, with an external
    fund-receipt deadline and retry/exception state."

    One row per (employee, payslip) — created only for a REAL persisted
    payslip (see service.create_au_sg_liability), never for a preview,
    mirroring PayrollYtdAccumulator's own "written only by real payslip
    generation" discipline. `fund_receipt_deadline` is pay_date + 7
    business days per §10's own control table, unless a statutory
    extension applies (`deadline_extended_to`, NULL by default). This
    table is a status tracker only — like RtiSubmission, it never
    actually transmits a SuperStream contribution message; when a real
    SuperStream/clearing-house integration exists, the only new work
    should be wiring a real API call into the SUBMITTED transition below,
    not a redesign of this table.

    RESOLVED GAP (AU-AC23/AU-AC24, identified 2026-09-16, closed Phase 9
    2026-09-17): §12 requires each STP submission and SuperStream message
    to record its own schema/transport version, independently of the tax-
    rule package version. Rather than add AU-only version columns HERE,
    this is tracked on RtiSubmission.schema_version instead — the actual
    STP/SuperStream SUBMISSION record (see service.generate_report_from_
    template + the seeded "AU-STP" ReportTemplate, and RtiSubmission's
    own widened submission_type set) is a distinct GeneratedReport/
    RtiSubmission pair per payroll run, not a field on this per-payday
    liability table. This table's own status/deadline fields remain the
    correct home for the underlying SG obligation; the submission
    artifact's schema version belongs with the submission, not the
    liability it reports on."""
    __tablename__ = "payroll_super_guarantee_liabilities"

    id                    = Column(Integer, primary_key=True, index=True)
    organization_id       = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    employee_id           = Column(Integer, ForeignKey("payroll_employees.id"), nullable=False, index=True)
    payslip_item_id       = Column(Integer, ForeignKey("payslip_items.id"), nullable=True, index=True)

    pay_date              = Column(Date, nullable=False)
    qualifying_earnings   = Column(Numeric(14, 2), nullable=False)
    sg_rate_pct           = Column(Numeric(6, 4), nullable=False)
    sg_amount             = Column(Numeric(12, 2), nullable=False)
    # Snapshot of this employee's cumulative AU-financial-year qualifying
    # earnings AFTER this payday (see PayrollYtdAccumulator's
    # "au_sg_qualifying_earnings" component) — preserved here even though
    # it is also the accumulator's own running value, so a later
    # accumulator correction can never silently rewrite what THIS
    # liability event actually reported at the time.
    ytd_qualifying_earnings_after = Column(Numeric(14, 2), nullable=True)
    mcb_reached           = Column(Boolean, nullable=False, default=False, server_default="false")

    # PENDING -> SUBMITTED -> RECEIVED | FAILED | EXCEPTION. PENDING is the
    # state a fresh row starts in (liability recorded, no payment/
    # transport action taken yet — see class docstring on why this stays
    # a status tracker); RECEIVED/FAILED/EXCEPTION are set only by a human
    # recording what a real clearing-house/fund confirmed, never inferred.
    status                = Column(String(20), nullable=False, default="PENDING", server_default="PENDING")
    fund_receipt_deadline = Column(Date, nullable=False)
    # Statutory extension per §10's own "unless an extended timeframe
    # applies" — NULL means the ordinary 7-business-day deadline above
    # stands unmodified.
    deadline_extended_to  = Column(Date, nullable=True)
    submitted_at          = Column(DateTime(timezone=True), nullable=True)
    received_at           = Column(DateTime(timezone=True), nullable=True)
    exception_reason      = Column(Text, nullable=True)

    created_at            = Column(DateTime(timezone=True), server_default=func.now())
    updated_at            = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<SuperGuaranteeLiability employee={self.employee_id} pay_date={self.pay_date} status={self.status}>"


class StatutoryFiling(Base):
    """Cross-jurisdiction statutory-filing status tracker, one row per
    (organization, jurisdiction, filing type, period).

    The persisted "did we actually file it" model behind the Super Admin
    Filings & Remittances page. Germany already tracks its wage-tax filings
    through GermanyElsterTransmission (real ELSTER transport state) — rows
    here are how every other jurisdiction (Australia GST/BAS, India
    TDS/GST, …) records filing status, and how a manual override/adjourned
    record can exist alongside an ELSTER transmission. The dashboard merges
    both sources per org (see
    modules/super_admin/command_center_router.py's _load_org_filing_coverage).

    Status vocabulary is deliberately the filing WORKFLOW, not a transport
    state machine: an ELSTER transmission moves DRAFT/VALIDATED/QUEUED/
    TRANSMITTED/ACKNOWLEDGED because ELSTER is a live wire; for a manual
    filing the only states that matter to an admin are not-started /
    in-progress / filed / overdue / blocked. No status here is inferred
    from a missing signal — a human records what actually happened, and
    BY_DEFAULT the page treats an org with no row as "no filing record
    yet", never as filed (see the endpoint's empty-state handling).
    """
    __tablename__ = "statutory_filings"

    id              = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    jurisdiction    = Column(String(10), nullable=False, index=True)  # "AU" / "IN" / "DE" / …
    filing_type     = Column(String(50), nullable=False, default="")  # "GST" / "BAS" / "TDS" / …
    period_label    = Column(String(50), nullable=False, default="")  # "Q2 2026 — Apr–Jun"
    period_start    = Column(Date, nullable=True)
    period_end      = Column(Date, nullable=True)

    # NOT_STARTED -> IN_PROGRESS -> FILED | OVERDUE | BLOCKED.
    status          = Column(String(20), nullable=False, default="NOT_STARTED", server_default="NOT_STARTED")
    # Required context when status == "BLOCKED" (why it cannot proceed); the
    # dashboard surfaces it in the Blocked Reason column, same as ELSTER.
    blocked_reason  = Column(String(300), nullable=True)
    # When the filing was actually lodged — informational; the dashboard's
    # "Updated" timestamp reflects the row's own updated_at.
    submitted_at    = Column(DateTime(timezone=True), nullable=True)

    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        # One filing per (org, jurisdiction, type, period) — an admin entry
        # upserts into the period's existing row instead of stacking dupes.
        UniqueConstraint(
            "organization_id", "jurisdiction", "filing_type", "period_label",
            name="uq_statutory_filing_per_period",
        ),
    )

    def __repr__(self):
        return f"<StatutoryFiling org={self.organization_id} {self.jurisdiction} {self.filing_type} {self.period_label} {self.status}>"


# ── France (ZP-FR-ENG-001, 2026-09-24) ─────────────────────────────────────
# France breaks its payroll on a THIRD dimension the generic pack model
# (jurisdiction_country / jurisdiction_state) does not express: the SIRET /
# establishment (FR-002). The four France tables below are therefore
# deliberately NOT re-implementations of the generic pack/rate/slab system —
# statutory rates and tax slabs stay in ContributionRate / TaxSlab / 
# JurisdictionPack exactly like every other country. These tables only cover
# the concepts France mandates that GENERIC infrastructure cannot carry:
#   - EmployerFranceProfile         → org-level SIREN/IDCC/Urssaf/DSN/PAS/effectif
#   - FranceEstablishmentRatePack  → SIRET-scoped AT/MP + versement mobilité + effectif
#   - FrancePASRate                → authority-supplied DGFiP PAS rate (CRM ingestion)
#   - FranceDsnSubmission/Outbox   → P26V01 outbox lifecycle (durable, idempotent)
# Precedent for dedicated country extension tables: the Germany family
# (GermanyElsterTransmission, GermanyElstamChangeListBatch, …).

class EmployerFranceProfile(Base):
    """1:1 org-level France employer profile. Carries the governed annual
    effectif with threshold history (FR-015/FR-036), IDCC scope (FR-035),
    the Urssaf/DSN collector identity + filing due-date class (5th M+1 for
    50+, 15th M+1 otherwise — FR §10), the DGFiP PAS collector identity, and
    the evidence-driven readiness gate (FR-034). SIRET-scoped things live on
    FranceEstablishmentRatePack, not here — one row per SIRET."""
    __tablename__ = "payroll_fr_employer_profiles"

    id              = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, unique=True, index=True)

    siren          = Column(String(9), nullable=False)
    legal_name     = Column(String(200), nullable=True)
    legal_form     = Column(String(50), nullable=True)
    # Convention collective / IDCC — mandatory or explicitly "unknown under
    # review" (FR-035); never silently defaults to Code du travail floor.
    idcc           = Column(String(20), nullable=True)
    # APPLICABLE | NOT_APPLICABLE | UNDER_REVIEW — FR-035's explicit
    # "unknown under review" state, so an empty idcc is never ambiguous.
    idcc_status    = Column(String(20), nullable=True)
    address        = Column(Text, nullable=True)             # panel A
    payroll_contact = Column(String(200), nullable=True)     # panel A

    # Urssaf / DSN (FR §11 panel C)
    urssaf_account         = Column(String(50), nullable=True)
    dsn_declarant          = Column(String(50), nullable=True)
    filing_due_date_class  = Column(String(20), nullable=False, default="M15", server_default="M15")
    #     "M5" (50+ employees: 5th M+1) | "M15" (<50: 15th M+1) |
    #     "DEFERRED_M15" (50+ on deferred payroll, 15th rule)
    payment_mandate_ref    = Column(String(100), nullable=True)

    # DGFiP PAS (FR §11 panel D) — authority rate exchange, never admin-edited
    pas_collector_identity = Column(String(100), nullable=True)
    pas_crm_status         = Column(String(20), nullable=False, default="NOT_CONNECTED", server_default="NOT_CONNECTED")
    #     NOT_CONNECTED | CONNECTED | RATE_EXCHANGE_OK | STALE

    # Governed annual effectif + threshold history (FR-015/FR-036) — JSON
    # {year: {"value": n, "source": ..., "validatedAt": ...}, ...}; used for
    # FNAL/CFP/apprenticeship/versement mobilité 11+/50+ predicates.
    effectif_state    = Column(JSON, nullable=True)

    # Evidence-driven launch gate H (FR §11): RulePack/DSN/rates/benefits/
    # bank/labor/parallel-run evidence bundle.
    readiness_status  = Column(String(30), nullable=False, default="NOT_READY", server_default="NOT_READY")
    #     NOT_READY | READY | LIVE
    readiness_evidence = Column(JSON, nullable=True)

    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<EmployerFranceProfile org={self.organization_id} siren={self.siren} readiness={self.readiness_status}>"


class FranceEstablishment(Base):
    """An employer's SIRET establishment registry (FR §11 panel B, FR-002).
    AT/MP and versement mobilité rate-pack periods attach to it
    (FranceEstablishmentRatePack.establishment_id). Deactivated, never
    deleted — historical rate packs and DSN filings keep referring to it."""
    __tablename__ = "payroll_fr_establishments"

    id                  = Column(Integer, primary_key=True, index=True)
    organization_id     = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    employer_profile_id = Column(Integer, ForeignKey("payroll_fr_employer_profiles.id"), nullable=True)

    siret              = Column(String(14), nullable=False)
    name               = Column(String(200), nullable=True)
    address            = Column(Text, nullable=True)
    commune_insee      = Column(String(10), nullable=True)
    workforce_location = Column(String(200), nullable=True)
    payroll_identifier = Column(String(50), nullable=True)
    is_active          = Column(Boolean, nullable=False, default=True, server_default="true")

    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("organization_id", "siret", name="uq_fr_establishment_org_siret"),
    )

    def __repr__(self):
        return f"<FranceEstablishment org={self.organization_id} siret={self.siret} active={self.is_active}>"


class FranceEstablishmentRatePack(Base):
    """Per-SIRET employer/establishment rate pack (FR-002/FR-013). AT/MP is
    establishment-specific authority data imported by risk decision, never
    generic; versement mobilité/VMRR is location + effectif + threshold
    driven (11+ employee threshold with threshold-neutralization history).
    Each row is effective-dated so January/July rate changes keep full
    history (FR §2/§5/§9)."""
    __tablename__ = "payroll_fr_establishment_rate_packs"

    id                  = Column(Integer, primary_key=True, index=True)
    organization_id     = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    # Optional link to the employer profile; not a hard dependency so a
    # SIRET pack can exist before the full profile row is finalised.
    employer_profile_id = Column(Integer, ForeignKey("payroll_fr_employer_profiles.id"), nullable=True)
    establishment_id    = Column(Integer, ForeignKey("payroll_fr_establishments.id"), nullable=True)

    siret            = Column(String(14), nullable=False)
    commune_insee    = Column(String(10), nullable=True)
    workplace_label  = Column(String(200), nullable=True)

    # AT/MP — authority decision with evidence (FR-013/FR-027)
    at_mp_rate_pct     = Column(Numeric(7, 4), nullable=True)
    at_mp_risk_code    = Column(String(30), nullable=True)
    at_mp_evidence     = Column(Text, nullable=True)
    at_mp_source       = Column(String(120), nullable=True)

    # Versement mobilité / VMRR — location + effectif driven
    vm_rate_pct            = Column(Numeric(7, 4), nullable=True)
    vm_threshold_applies   = Column(Boolean, nullable=True)  # 11+ employee threshold
    vm_threshold_history   = Column(JSON, nullable=True)     # threshold-neutralization history
    vm_source              = Column(String(120), nullable=True)
    vm_evidence            = Column(Text, nullable=True)     # authority evidence, like AT/MP (FR-013)
    ags_special_status     = Column(String(30), nullable=True)  # panel E unemployment/AGS special status

    # Employer-size classes used by FNAL/CFP/apprenticeship predicates
    fnal_class  = Column(String(20), nullable=True)  # "UNDER_50" | "OVER_50"
    cfp_class   = Column(String(20), nullable=True)  # "UNDER_11" | "OVER_11"
    effectif    = Column(Integer, nullable=True)

    effective_from = Column(Date, nullable=False)
    effective_to   = Column(Date, nullable=True)

    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        # Historical rows kept per period (Jan/Jul rate changes).
        UniqueConstraint("organization_id", "siret", "effective_from", name="uq_fr_estab_pack_per_period"),
    )

    def __repr__(self):
        return f"<FranceEstablishmentRatePack org={self.organization_id} siret={self.siret} from={self.effective_from} at_mp={self.at_mp_rate_pct}>"


class FrancePASRate(Base):
    """Prélèvement à la source authority rate (FR-008/FR-010). Personalized
    rates are DGFiP CRM supply, ingested with rate identifier + receipt date
    + legal application window (60 days); NEUTRAL rows come from the
    statutory grid when no personalized rate may be used (employee opt-out /
    new starter). Never an admin-editable percentage — the UI is read-only.
    Corrections link back to the originating period/rate (FR §4) instead of
    retro-applying a newer personalized rate."""
    __tablename__ = "payroll_fr_pas_rates"

    id              = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    employee_id     = Column(Integer, ForeignKey("payroll_employees.id"), nullable=False, index=True)

    # PERSONALIZED | NEUTRAL
    rate_type      = Column(String(20), nullable=False)
    # Personalized authority rate (null for NEUTRAL — the neutral grid is
    # statutory content, resolved by the engine from the payroll date).
    rate_pct       = Column(Numeric(7, 4), nullable=True)
    dgfip_rate_id  = Column(String(100), nullable=True)   # personalized provenance (FR-010)
    crm_reference  = Column(String(100), nullable=True)   # DGFiP CRM message the rate came from
    source         = Column(String(20), nullable=False)   # "CRM" | "NEUTRAL_GRID"
    received_date  = Column(Date, nullable=True)          # CRM receipt date
    effective_from = Column(Date, nullable=False)         # legal application start
    effective_to   = Column(Date, nullable=True)          # end of 60-day window / superseded

    # ACTIVE | PENDING | EXPIRED | STALE
    status = Column(String(20), nullable=False, default="PENDING", server_default="PENDING")

    # Correction lineage — link to the prior rate this row replaces.
    correction_of_id = Column(Integer, ForeignKey("payroll_fr_pas_rates.id"), nullable=True)

    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_fr_pas_rate_org_emp_window", "organization_id", "employee_id", "effective_from"),
    )

    def __repr__(self):
        return f"<FrancePASRate employee={self.employee_id} {self.rate_type} {self.status}>"


class FranceDsnSubmission(Base):
    """One monthly DSN P26V01 submission (FR-030..033). The four lifecycle
    states the spec mandates — transport acknowledgement, business
    acceptance (CRM), anomaly resolution, payment settlement — are SEPARATE
    columns, never one merged status; a correct net-pay calculation is not
    evidence of successful tax reporting (FR-011). Immutable original with
    correction lineage via correction_of_id."""
    __tablename__ = "payroll_fr_dsn_submissions"

    id              = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    dsn_version  = Column(String(20), nullable=False, default="P26V01", server_default="P26V01")
    release_ref  = Column(String(50), nullable=False)   # pinned reference-table release (FR-030)
    payload_hash = Column(String(64), nullable=False)
    period_start = Column(Date, nullable=False)
    period_end   = Column(Date, nullable=False)
    due_date     = Column(Date, nullable=False)

    # DRAFT | VALIDATED | QUEUED | TRANSMITTED | ACKNOWLEDGED |
    # BUSINESS_REJECTED | CRM_RESOLVED | UNKNOWN | SETTLED
    status = Column(String(30), nullable=False, default="DRAFT", server_default="DRAFT")

    validation_errors = Column(JSON, nullable=True)   # pre-submit validator (FR-031)
    blocked_reason    = Column(Text, nullable=True)

    # Separate lifecycle columns (FR-032) — nullable until the signal exists.
    technical_ack     = Column(String(30), nullable=True)
    business_crm      = Column(JSON, nullable=True)   # report/anomaly codes per DSN version
    payment_state     = Column(String(20), nullable=True)  # SEPA/direct-debit, independent of DSN
    submitted_at      = Column(DateTime(timezone=True), nullable=True)
    acknowledged_at   = Column(DateTime(timezone=True), nullable=True)

    # Correction lineage: replaces/regularizes the referenced submission;
    # the prior row is never deleted (FR-033).
    correction_of_id = Column(Integer, ForeignKey("payroll_fr_dsn_submissions.id"), nullable=True)

    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_fr_dsn_org_period", "organization_id", "period_start"),
    )

    def __repr__(self):
        return f"<FranceDsnSubmission org={self.organization_id} {self.period_start} {self.status}>"


class FranceDsnOutboxItem(Base):
    """Durable idempotent outbox record for outbound DSN/payment actions
    (FR-033). A network timeout results in UNKNOWN and reconciliation —
    never blind replay. idempotency_key prevents duplicate transmission when
    a transport success is uncertain."""
    __tablename__ = "payroll_fr_dsn_outbox_items"

    id            = Column(Integer, primary_key=True, index=True)
    submission_id = Column(Integer, ForeignKey("payroll_fr_dsn_submissions.id"), nullable=False, index=True)

    # TRANSMIT | PAS_RATE_EXCHANGE | CRM_CLOSE | CORRECTION
    action          = Column(String(30), nullable=False)
    payload         = Column(JSON, nullable=True)
    idempotency_key = Column(String(64), nullable=False, unique=True)

    # PENDING | SENT | UNKNOWN | ACKNOWLEDGED | FAILED
    status          = Column(String(20), nullable=False, default="PENDING", server_default="PENDING")
    attempts        = Column(Integer, nullable=False, default=0, server_default="0")
    last_error      = Column(Text, nullable=True)
    sent_at         = Column(DateTime(timezone=True), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<FranceDsnOutboxItem submission={self.submission_id} {self.action} {self.status}>"


# ══ Ireland (IE) — ZP-IE-ENG-001 ═══════════════════════════════════════
# Five tables, matching §12's "Ireland-specific minimum" object list. The
# spec's RulePackIE object is NOT a new table: PAYE rates, the Emergency
# basis, USC bands, PRSI rates/thresholds/credit, the minimum wage and their
# effective dates are all already modelled, effective-dated and Super-Admin
# configurable by the generic JurisdictionPack / ContributionRate / TaxSlab
# tables (see jurisdiction.py's IE pack_type wiring). EmployeeIrelandProfile
# is likewise NOT a new table — its employee-owned facts are the Ireland
# block on EmployeeStatutoryProfile above, which already provides the
# effective-dating §12 needs for a PRSI-class or pension-exemption change.


class EmployerIrelandProfile(Base):
    """1:1 org-level Ireland employer profile (§12 EmployerIrelandProfile:
    PAYE registration, ROS cert reference, remitter frequency, bank config,
    supported PRSI scope, MyFutureFund employer status).

    The revenue/gating fields are deliberately explicit rather than derived.
    IE-028 forbids the employer reaching LIVE until the ROS certificate is
    validated, an RPN request succeeds, a submission test path is proven,
    remitter frequency is confirmed and MyFutureFund operating status is
    established — so each of those is its own column a readiness evaluation
    can read without inferring it."""
    __tablename__ = "payroll_ie_employer_profiles"

    id              = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, unique=True, index=True)

    # Revenue registration. Authoritative copy; the generic registration form
    # (CompanyComplianceDetails.tax_identifiers, keyed by the same field keys
    # as jurisdiction.py's IE schema) remains the capture surface, exactly as
    # France keeps siren/siret on EmployerFranceProfile alongside its own.
    paye_registration_number  = Column(String(20), nullable=True)
    prsi_registration_number  = Column(String(20), nullable=True)
    ros_sub_user_reference    = Column(String(64), nullable=True)
    eircode                   = Column(String(10), nullable=True)

    # ROS certificate (IE-028). Status is the authority-reported state, never
    # an admin self-declaration of "working fine".
    ros_certificate_status    = Column(String(30), nullable=False, default="NOT_VALIDATED", server_default="NOT_VALIDATED")
    # NOT_VALIDATED | VALID | EXPIRED | REVOKED
    ros_certificate_reference = Column(String(100), nullable=True)
    ros_certificate_expires_on = Column(Date, nullable=True)

    # Revenue remitter/payment frequency — an employer-level filing fact that
    # drives the submission schedule, confirmed with Revenue (IE-028).
    remitter_frequency        = Column(String(20), nullable=True)
    revenue_collector_identity = Column(String(100), nullable=True)

    # SEPA/domestic Irish bank configuration for employee settlement (IE-041).
    settlement_bank           = Column(String(100), nullable=True)
    settlement_account_iban   = Column(String(34), nullable=True)
    settlement_account_bic    = Column(String(11), nullable=True)
    bank_adapter_version      = Column(String(30), nullable=True)
    bank_cutoff_reference     = Column(String(100), nullable=True)

    # PRSI scope actually enabled for this employer. The certified launch
    # cohort is Class A only (IE-001/IE-016); anything else must stay off
    # rather than be attempted.
    # A_ONLY is the only supported value until a later cohort is certified.
    prsi_scope                = Column(String(30), nullable=False, default="A_ONLY", server_default="A_ONLY")
    prsi_supported_classes    = Column(JSON, nullable=True)   # ["A0","AX","AL","A1"]

    # Employer-side MyFutureFund operating status (IE-018/IE-030) — what the
    # EMPLOYER has established with NAERSA, kept distinct from each
    # employee's own authority status on IrelandMyFutureFundStatus.
    myfuturefund_employer_status = Column(String(30), nullable=False, default="UNKNOWN", server_default="UNKNOWN")
    # UNKNOWN | NOT_OPERATING | OPERATING
    myfuturefund_payment_method = Column(String(50), nullable=True)

    # Evidence-driven launch gate (IE-028). NOT_READY until every predicate
    # above is satisfied; mirrors EmployerFranceProfile.readiness_status.
    readiness_status   = Column(String(30), nullable=False, default="NOT_READY", server_default="NOT_READY")
    # NOT_READY | READY | LIVE
    readiness_evidence = Column(JSON, nullable=True)

    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<EmployerIrelandProfile org={self.organization_id} paye={self.paye_registration_number} readiness={self.readiness_status}>"


class IrelandRpnSnapshot(Base):
    """Immutable frozen Revenue Payroll Notification (§12 RpnSnapshot; IE-005,
    IE-022, IE-045).

    IE-022 forbids the core calculator making live Revenue calls, so the
    snapshot retrieved during preflight IS the calculation input. Every
    historical payroll must be reproducible from the snapshot that was in
    force, which is why this is an append-only content-addressed record and
    not mutable "current RPN" columns on the employee: IE-045 explicitly
    forbids substituting current tax tables into a historical replay.

    raw_hash is the deterministic content hash over the authority response
    (IE-033/IE-047): approval is invalidated by any changed RPN, and the
    golden vectors hash the snapshot, so the exact bytes Revenue returned are
    preserved rather than re-serialized."""
    __tablename__ = "payroll_ie_rpn_snapshots"

    id              = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    employee_id     = Column(Integer, ForeignKey("payroll_employees.id"), nullable=False, index=True)
    # The statutory-profile version this snapshot was resolved against, so a
    # later profile edit can never silently apply to a frozen instruction.
    statutory_profile_id = Column(Integer, ForeignKey("payroll_employee_statutory_profiles.id"), nullable=True)

    rpn_number      = Column(String(50), nullable=False)
    issued_at       = Column(DateTime(timezone=True), nullable=False)
    # The tax year the instruction belongs to. Selected by PAY DATE, never by
    # earning period (IE-006) — income earned in 2025 and paid in 2026 is
    # processed under the 2026 RPN.
    tax_year        = Column(String(10), nullable=False)   # "2026"

    # CUMULATIVE | WEEK_1 | EMERGENCY — Revenue's instruction, never inferred
    # (IE-005/IE-007/IE-008).
    calculation_basis = Column(String(20), nullable=False)
    # PPSN present drives whether Emergency uses the prescribed initial
    # standard-rate treatment or the higher-rate/no-credit one (IE-008).
    ppsn_supplied     = Column(Boolean, nullable=False, default=True, server_default="1")

    # Annual values as issued, preserved for traceability. The engine
    # assesses per-period values derived from these, so BOTH are stored
    # rather than one being recomputed on read (IE-005: preserve annual
    # values for traceability only).
    standard_rate_band        = Column(Numeric(14, 2), nullable=True)
    tax_credit                = Column(Numeric(14, 2), nullable=True)
    standard_rate_band_period = Column(Numeric(14, 2), nullable=True)
    tax_credit_period         = Column(Numeric(14, 2), nullable=True)
    # Cumulative state as at the start of this period, for CUMULATIVE basis.
    previous_taxable_pay_ytd  = Column(Numeric(14, 2), nullable=True)
    previous_pay_ytd          = Column(Numeric(14, 2), nullable=True)
    # Number of pay periods already elapsed in the tax year INCLUDING this
    # one. The cumulative credit position cannot be derived without it, so a
    # snapshot with prior pay but no counter is BLOCKED, not guessed.
    periods_elapsed           = Column(Integer, nullable=True)

    # LPT: deducted only when Revenue instructs it, and always kept separate
    # from PAYE/USC/PRSI (IE-003/IE spec §3).
    lpt_instructed   = Column(Boolean, nullable=False, default=False, server_default="0")
    lpt_rate_pct     = Column(Numeric(5, 2), nullable=True)

    # Emergency-basis weekly credit for a PPSN-supplied employee.
    emergency_tax_credit_weekly = Column(Numeric(10, 2), nullable=True)

    # Deterministic content hash over the authority response (IE-033/IE-047).
    raw_hash         = Column(String(64), nullable=False, index=True)
    # The full response as received, so a disputed payroll can be replayed
    # against exactly what Revenue returned.
    raw_payload      = Column(JSON, nullable=True)
    retrieved_at     = Column(DateTime(timezone=True), server_default=func.now())
    # Staleness is a preflight concern (IE-005/IE-033), recorded so a run can
    # explain WHY a refresh was required.
    is_stale         = Column(Boolean, nullable=False, default=False, server_default="0")

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # One snapshot per (employee, tax year, raw_hash): a refresh that
        # returns byte-identical authority content is a no-op, while any real
        # change is a new immutable row rather than an overwrite.
        UniqueConstraint(
            "employee_id", "tax_year", "raw_hash",
            name="uq_ie_rpn_snapshot_employee_year_hash",
        ),
        Index("ix_ie_rpn_snapshot_org_employee", "organization_id", "employee_id"),
    )

    def __repr__(self):
        return f"<IrelandRpnSnapshot emp={self.employee_id} {self.rpn_number} {self.tax_year} {self.calculation_basis}>"


class IrelandMyFutureFundStatus(Base):
    """Per-employee MyFutureFund authority status (§12 MyFutureFundStatus;
    IE-018, IE-020, IE-021, IE-030).

    NAERSA is the eligibility authority; payroll applies the notified status
    and never becomes the authority itself. There is deliberately no admin
    "enrol this employee" control anywhere in the codebase (IE-018/IE-021) —
    status rows are written only from a NAERSA notification.

    Effective dating is the whole point: status changes are versioned, so a
    historical payroll replays the status that was notified at the time
    rather than today's."""
    __tablename__ = "payroll_ie_myfuturefund_statuses"

    id              = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    employee_id     = Column(Integer, ForeignKey("payroll_employees.id"), nullable=False, index=True)

    # NOT_ENROLLED | ENROLLED | SELF_EMPLOYED | RETIRED | SUSPENDED | EXEMPT
    status          = Column(String(30), nullable=False)
    # Why this status — the evidence an auditor needs, and the only way to
    # distinguish a genuine occupational-pension/qualifying exemption from an
    # ordinary enrolment (IE-021).
    status_reason   = Column(Text, nullable=True)
    effective_from  = Column(Date, nullable=False)
    effective_to    = Column(Date, nullable=True)   # NULL = current

    # Contribution results as notified/applied. The 0.5% State contribution is
    # administered separately by the State/NAERSA and must never appear as an
    # employee payroll deduction (IE §6) — employee_contribution_pct is
    # therefore the only rate that deducts from pay.
    employee_contribution_pct = Column(Numeric(5, 2), nullable=True)
    employer_contribution_pct = Column(Numeric(5, 2), nullable=True)
    state_contribution_pct    = Column(Numeric(5, 2), nullable=True)
    # The earnings threshold and how the current payroll sits against it
    # (IE-020). The threshold itself is pack content; this records the
    # authority's own threshold state, because the "payroll in which the
    # threshold is exceeded can remain contributable and later payrolls cease"
    # rule must NOT be approximated by capping each payslip at a pro-rata
    # amount locally.
    threshold_state = Column(String(30), nullable=True)
    # BELOW | AT_OR_ABOVE | CEASED
    contributions_ceased = Column(Boolean, nullable=False, default=False, server_default="0")
    ceased_from_pay_date  = Column(Date, nullable=True)

    # Occupational-pension/PRSA exemption evidence, kept separate from the
    # status itself (IE-021) so payroll can always prove WHY an employment is
    # exempt from auto-enrolment.
    exemption_reference    = Column(String(64), nullable=True)
    exemption_effective_from = Column(Date, nullable=True)

    # Authority provenance (IE-030: every authority-derived status must show
    # source, effective date and last refresh).
    source                 = Column(String(30), nullable=False, default="NAERSA_NOTIFICATION", server_default="NAERSA_NOTIFICATION")
    source_notification_hash = Column(String(64), nullable=True)
    last_refreshed_at      = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_ie_mff_emp_effective", "employee_id", "effective_from"),
        Index("ix_ie_mff_org_employee", "organization_id", "employee_id"),
    )

    def __repr__(self):
        return f"<IrelandMyFutureFundStatus emp={self.employee_id} {self.status} from={self.effective_from}>"


class IrelandYtdAccumulator(Base):
    """Running year-to-date state for Ireland's INDEPENDENT statutory bases
    (IE-009/IE-010/IE-032/IE-039).

    A dedicated table rather than the generic PayrollYtdAccumulator because
    that table's single (taxable_wages, tax_withheld) pair is a poor fit:
    USC needs a payable base AND a paid figure, PRSI has no employee tax at
    all (only a reckonable-pay total), and MyFutureFund has an earnings
    threshold state. Overloading one column pair to carry a bare reckonable
    total would make the stored meaning ambiguous.

    PREVIEW MUST NOT WRITE HERE (IE-032) — only COMMIT advances these.
    IE-039 requires commits that can affect cumulative PAYE/USC or the annual
    MyFutureFund threshold to be serialised, so a second commit can never
    consume stale year-to-date values; the service layer takes a row lock
    before reading and writing."""
    __tablename__ = "payroll_ie_ytd_accumulators"

    id              = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    employee_id     = Column(Integer, ForeignKey("payroll_employees.id"), nullable=False, index=True)
    # Selected by PAY DATE (IE-006), so a run straddling new year resets to a
    # fresh row rather than carrying the prior year's totals.
    tax_year        = Column(String(10), nullable=False)   # "2026"

    # USC — its own base and its own accumulator, never assumed equal to the
    # PAYE base (IE-009/IE-010).
    usc_payable_ytd  = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    usc_paid_ytd     = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")

    # PRSI — contribution weeks and the annual reckonable-pay ceiling are
    # separate concerns; the weekly rate bands are applied per period, but
    # the accumulated reckonable figure is what a threshold test reads.
    prsi_reckonable_ytd = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    prsi_contribution_weeks_ytd = Column(Numeric(8, 3), nullable=False, default=0, server_default="0")

    # MyFutureFund annual threshold state (IE-020). Earnings accumulated
    # BEFORE the current period; the payroll in which the threshold is
    # exceeded may remain contributable, so the service layer records
    # crossed_at_pay_date rather than re-deriving it from this figure alone.
    mff_earnings_ytd_before = Column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    mff_threshold_crossed_at_pay_date = Column(Date, nullable=True)

    last_payslip_id  = Column(Integer, ForeignKey("payslip_items.id"), nullable=True)
    updated_at       = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("employee_id", "tax_year", name="uq_ie_ytd_accumulator_employee_year"),
        Index("ix_ie_ytd_org_employee", "organization_id", "employee_id"),
    )

    def __repr__(self):
        return f"<IrelandYtdAccumulator emp={self.employee_id} {self.tax_year} usc_paid={self.usc_paid_ytd}>"


class IrelandRevenueSubmission(Base):
    """Append-only record of one payroll line item reported to Revenue
    (§12 RevenueSubmission; IE-038, IE-044).

    IE-038 makes corrections APPEND-ONLY: the original calculation and the
    original Revenue line item are preserved, and a correction references its
    predecessor through previous_line_item_id rather than overwriting it. A
    reporting correction is deliberately distinguishable from an economic
    over/underpayment (IE-040) via correction_kind.

    A timeout is recorded as UNKNOWN and reconciled — never blind-replayed
    (IE-044). payload_hash plus the RPN snapshot id together reproduce the
    exact submission for a historical audit."""
    __tablename__ = "payroll_ie_revenue_submissions"

    id              = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    run_id          = Column(Integer, ForeignKey("payroll_runs.id"), nullable=False, index=True)
    employee_id     = Column(Integer, ForeignKey("payroll_employees.id"), nullable=False, index=True)
    payslip_id      = Column(Integer, ForeignKey("payslip_items.id"), nullable=True, index=True)

    # Revenue's own identifier for the reported line item.
    line_item_id      = Column(String(50), nullable=True)
    previous_line_item_id = Column(String(50), nullable=True)
    rpn_snapshot_id   = Column(Integer, ForeignKey("payroll_ie_rpn_snapshots.id"), nullable=True)

    # ORIGINAL | REPORTING_CORRECTION | ECONOMIC_CORRECTION (IE-038/IE-040).
    correction_kind   = Column(String(30), nullable=False, default="ORIGINAL", server_default="ORIGINAL")
    period_start      = Column(Date, nullable=False)
    period_end        = Column(Date, nullable=False)
    pay_date          = Column(Date, nullable=False)

    # The amount actually reported, kept alongside the calculated figures so
    # a correction can explain a difference rather than only restate it.
    reported_gross    = Column(Numeric(14, 2), nullable=True)
    reported_paye     = Column(Numeric(14, 2), nullable=True)
    reported_prsi_employee = Column(Numeric(14, 2), nullable=True)
    reported_prsi_employer = Column(Numeric(14, 2), nullable=True)

    payload      = Column(JSON, nullable=True)
    payload_hash = Column(String(64), nullable=False)

    # SENT | ACKNOWLEDGED | REJECTED | UNKNOWN
    status           = Column(String(20), nullable=False, default="PENDING", server_default="PENDING")
    sent_at          = Column(DateTime(timezone=True), nullable=True)
    acknowledged_at  = Column(DateTime(timezone=True), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    # Set when status is UNKNOWN: what still has to be reconciled with
    # Revenue before any replay is safe (IE-044).
    reconciliation_note = Column(Text, nullable=True)
    idempotency_key  = Column(String(64), nullable=False, unique=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_ie_revsub_org_period", "organization_id", "period_start"),
    )

    def __repr__(self):
        return f"<IrelandRevenueSubmission org={self.organization_id} {self.period_start} {self.status}>"


class IrelandRevenueMonthlyReturn(Base):
    """One Revenue monthly return / statement period (§12
    RevenueMonthlyReturn) and its reconciliation.

    A versioned, append-only statement record: accepted/deemed date and the
    reconciled liability are stored so a later version supersedes rather than
    overwrites, and the parallel-run evidence IE-048 requires (no unexplained
    employee-level difference) can be reconstructed afterwards."""
    __tablename__ = "payroll_ie_revenue_monthly_returns"

    id              = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    statement_period_start = Column(Date, nullable=False)
    statement_period_end   = Column(Date, nullable=False)
    # Monotonic per (org, period): a restatement adds a version, it never
    # edits the version Revenue already accepted.
    version              = Column(Integer, nullable=False, default=1, server_default="1")

    # DRAFT | SUBMITTED | ACCEPTED | DEEMED_ACCEPTED | REJECTED
    status               = Column(String(30), nullable=False, default="DRAFT", server_default="DRAFT")
    submitted_at         = Column(DateTime(timezone=True), nullable=True)
    accepted_at          = Column(DateTime(timezone=True), nullable=True)
    deemed_accepted_at    = Column(DateTime(timezone=True), nullable=True)
    rejection_reason     = Column(Text, nullable=True)

    # Reconciled liability as returned by Revenue, alongside what Zoiko
    # calculated, so a difference is visible rather than silently absorbed.
    calculated_liability  = Column(Numeric(14, 2), nullable=True)
    revenue_liability     = Column(Numeric(14, 2), nullable=True)
    reconciled_at         = Column(DateTime(timezone=True), nullable=True)
    reconciliation_notes  = Column(Text, nullable=True)
    reconciliation_state  = Column(JSON, nullable=True)

    payload_hash = Column(String(64), nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "statement_period_start", "statement_period_end", "version",
            name="uq_ie_monthly_return_org_period_version",
        ),
        Index("ix_ie_monthly_return_org_period", "organization_id", "statement_period_start"),
    )

    def __repr__(self):
        return f"<IrelandRevenueMonthlyReturn org={self.organization_id} {self.statement_period_start} v{self.version} {self.status}>"