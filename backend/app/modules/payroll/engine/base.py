"""
modules/payroll/engine/base
---------------------------
Core data structures and abstract strategy interface for the payroll engine.

All payroll strategies receive a ``PayrollContext`` and return a
``PayrollResult``.  The context carries the employee's salary components,
attendance-derived unpaid leave count, and the country-specific rate/slab
configuration needed for statutory deductions.

Fixed 30-Day Payroll Model (applies to ALL strategies):
    PAYROLL_DAYS = 30
    Per Day Salary = Monthly Gross / 30
    Attendance Deduction = Unpaid Leave Days × Per Day Salary
    Payable Days = 30 − Unpaid Leave Days
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

PAYROLL_DAYS = 30


def _round2(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class PayrollContext:
    """Immutable input bundle for a single-employee payroll calculation."""

    # Salary components (monthly)
    gross: Decimal
    basic: Decimal
    hra: Decimal = Decimal("0")
    special_allowance: Decimal = Decimal("0")
    overtime: Decimal = Decimal("0")
    additional_compensation: Decimal = Decimal("0")

    # Attendance (fixed 30-day model)
    unpaid_leave_days: int = 0
    payroll_days: int = PAYROLL_DAYS

    # Country / compliance
    country: str = "IN"
    rate_map: dict = field(default_factory=dict)   # component_key → ContributionRate
    slabs: list = field(default_factory=list)       # list[TaxSlab], country/national-level

    # Region (state/province/devolved-nation) — the employee's own
    # PayrollEmployee.work_state, threaded through so a country
    # calculator can resolve region-specific rules (India's
    # state-specific Professional Tax, US state income tax, Scotland's
    # own UK tax bands) without needing DB access itself. Empty/None
    # means "no region resolved" — every existing calculation is
    # unaffected until a calculator explicitly reads these.
    work_state: str = None
    state_rate_map: dict = field(default_factory=dict)   # component_key → ContributionRate, state-scoped
    state_slabs: list = field(default_factory=list)        # list[TaxSlab], state-scoped

    # US: tenant-specific, agency-assigned rates (SUI and similar) for this
    # employee's org+jurisdiction — component_code → EmployerTaxProfile.
    # Empty dict (every employee today) means "no such profile configured,"
    # NOT "assume the state default" — engine/countries/us.py treats an
    # absent SUI profile as simply not calculating SUI at all, since
    # inferring a rate would violate the standard's "never infer an
    # experience rate" rule.
    employer_tax_profiles: dict = field(default_factory=dict)

    # US: cross-state reciprocity (see service.py's _resolve_us_reciprocity).
    # False/empty for every employee today (no employee has a distinct
    # residence_state from work_state, and the ReciprocityRule table is
    # empty until Tax Ops configures a real agreement) — when True,
    # engine/countries/us.py taxes the RESIDENT state (these two fields)
    # instead of the work state (state_rate_map/state_slabs above).
    reciprocity_suppresses_work_state: bool = False
    resident_state_rate_map: dict = field(default_factory=dict)
    resident_state_slabs: list = field(default_factory=list)

    # US: manually-entered local (county/municipal/school-district) tax
    # rate for this employee's work_locality — see service.py's
    # get_locality_rate. None for every employee today (no employee has
    # work_locality set through any admin-facing UI... until now — see
    # countryFieldSpecs.js's new "Work Locality Code" field).
    locality_rate: object = None

    # Employee tax-profile fields — all opt-in (None/False means "not
    # set," never inferred), threaded from PayrollEmployee so a country
    # calculator can read them without DB access. No existing employee
    # has any of these set, so no existing calculation changes just
    # because these fields now exist.
    tax_code: str = None            # UK HMRC tax code, e.g. "1257L"
    ni_category: str = None         # UK NI category letter, e.g. "A"
    study_loan_plan: str = None     # e.g. "UK_PLAN2", "UK_POSTGRAD", "AU_HELP" — shared UK/AU mechanism
    study_loan_balance: Decimal = None
    church_tax_liable: bool = False  # Germany Kirchensteuer opt-in
    tax_regime: str = None          # India's "Old"/"New" — None means "not set," same as every employee today
    # Generic across every country — "Monthly"/"Weekly"/"Fortnightly"/
    # "FourWeekly". Defaults to "Monthly", matching the existing
    # gross/attendance model every country's calculator already assumes,
    # so no existing calculation changes. Only engine/countries/uk.py
    # currently reads this.
    pay_frequency: str = "Monthly"

    # US Form W-4: filing status ("SINGLE"/"MFJ"/"MFS"/"HOH") and form
    # vintage ("PRE_2020"/"2020_PLUS"). None for every non-US employee, and
    # for US employees until explicitly set — engine/countries/us.py falls
    # back to today's single filing-status-agnostic table/threshold when
    # None, so no existing calculation changes just because these fields
    # now exist.
    w4_filing_status: str = None
    w4_form_vintage: str = None

    # Canada TD1 federal total claim amount. None for every non-CA
    # employee, and for CA employees until explicitly set —
    # engine/countries/canada.py falls back to the dynamic income-tapered
    # BPAF (Phase 2) when None, so no existing calculation changes just
    # because this field now exists.
    td1_claim_amount: Decimal = None
    # Canada provincial/territorial TD1 claim amount — overrides the
    # province's own dynamic provincial_bpa, same "None means no
    # declaration on file" contract as td1_claim_amount above
    # (ZP-TAX-CA-2026-001 §18). Never applies to a Quebec employee — see
    # qc_tp1015_claim_amount below instead.
    provincial_td1_claim_amount: Decimal = None
    # Quebec TP-1015.3-V personal tax credit amount — Quebec's own
    # declaration, legally distinct from federal/provincial TD1
    # (ZP-TAX-CA-2026-001 §18). Overrides the canonical quebec_bpa when set.
    qc_tp1015_claim_amount: Decimal = None
    # Canada TD1X employee-requested additional per-pay-period
    # withholding — additive on top of tds, never touching the statutory
    # base calculation. None/0 for every employee until explicitly set.
    td1_additional_tax: Decimal = None
    # Canada labour-sponsored funds credit (LCF, §6) — the employee's
    # declared LSVCC share purchase amount; None (every employee today)
    # means "no purchase declared," changing nothing from existing
    # behavior. See shared._CA_LSVCC_CREDIT_ENABLED_COUNTRIES and
    # canada.py's _calculate_annual_tax_ca for the dormancy gate.
    lsvcc_investment_amount: Decimal = None
    # Canada CPT30 CPP/QPP election — "STOPPED" suppresses CPP/QPP (and
    # CPP2/QPP2) entirely for this employee; None/"ACTIVE" (every
    # employee today) changes nothing from existing behavior.
    cpp_qpp_election_status: str = None

    # Canada CPP/CPP2/EI (and Quebec QPP/QPP2/QPIP) year-to-date state,
    # as of BEFORE this pay period — read from PayrollYtdAccumulator by
    # service.py's _load_ca_ytd, gated on
    # engine/countries/shared.py's _YTD_ACCUMULATOR_ENABLED_COUNTRIES.
    # None (every employee/country today) means "no YTD wired" —
    # engine/countries/canada.py MUST fall back to its existing
    # current-period-annualized cap logic when None, never treat None as
    # 0. This is the calculation-layer dormancy switch; the rollout set
    # above is the read-layer one.
    ytd_pensionable_earnings: Decimal = None       # CPP/QPP first-layer
    ytd_cpp2_pensionable_earnings: Decimal = None  # CPP2/QPP2
    ytd_insurable_earnings: Decimal = None         # EI/QPIP
    ytd_basic_exemption_used: Decimal = None       # CPP/QPP $3,500 exemption, YTD-consumed

    # Canada: the ORG's (not this employee's own) aggregate Ontario
    # remuneration YTD, as of BEFORE this pay period — read from
    # OrganizationYtdAccumulator by service.py's _load_ca_org_levy_ytd,
    # gated on _ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES. None (every
    # employee/org today) means "not wired" — engine/countries/canada.py
    # MUST resolve Ontario EHT to $0 when None, never treat None as 0.
    on_eht_ytd_remuneration_before: Decimal = None

    # Canada: the same org-level YTD-remuneration contract as
    # on_eht_ytd_remuneration_before above, for BC EHT, Manitoba HE Levy
    # and NL HAPSET respectively — each independently None/wired.
    bc_eht_ytd_remuneration_before: Decimal = None
    mb_he_levy_ytd_remuneration_before: Decimal = None
    nl_hapset_ytd_remuneration_before: Decimal = None
    # BC EHT ordinary vs. registered-charity/nonprofit variant — read
    # from CompanyComplianceDetails.bc_eht_employer_classification.
    # "CHARITY_NONPROFIT" selects the charity thresholds/rates; anything
    # else (including None, the default for every org today — no Super
    # Admin/Org Admin UI sets this yet) is treated as ordinary.
    bc_eht_employer_classification: str = None

    # Quebec Health Services Fund — same org-level-accumulator contract
    # as on_eht_ytd_remuneration_before above.
    qc_hsf_ytd_remuneration_before: Decimal = None
    # GENERAL | PRIMARY_MANUFACTURING | PUBLIC_SECTOR — read from
    # CompanyComplianceDetails.qc_hsf_employer_category. None (no UI sets
    # this yet, same disclosed gap as BC's classification) is treated as
    # GENERAL, the most common case.
    qc_hsf_employer_category: str = None

    # Canada CPP/QPP age-gating (§10: "Age 18"/"Age 70" controls) — the
    # employee's own date of birth, and the pay date to compute their
    # age as of. Both None (every employee/country today, since no
    # PayrollEmployee has ever had a date_of_birth column before this)
    # means age-gating cannot run at all — see
    # shared._CA_AGE_GATED_CPP_ENABLED_COUNTRIES and canada.py's
    # _is_age_gated_cpp_stopped for the dormancy gate and the disclosed
    # simplification (calendar-age comparison, not CRA's more granular
    # month-boundary rule, which the source document itself doesn't
    # spell out precisely).
    date_of_birth: date = None
    pay_date: date = None


@dataclass
class PayrollResult:
    """Output bundle — all figures needed for a PayslipItem and preview."""

    # Attendance
    payroll_days: int = PAYROLL_DAYS
    unpaid_leave_days: int = 0
    payable_days: int = PAYROLL_DAYS
    per_day_salary: Decimal = Decimal("0")
    attendance_deduction: Decimal = Decimal("0")

    # Earnings
    gross: Decimal = Decimal("0")
    basic: Decimal = Decimal("0")
    hra: Decimal = Decimal("0")
    special_allowance: Decimal = Decimal("0")
    overtime: Decimal = Decimal("0")
    additional_compensation: Decimal = Decimal("0")

    # Employee-side deductions
    employee_pf: Decimal = Decimal("0")
    employee_esi: Decimal = Decimal("0")
    professional_tax: Decimal = Decimal("0")
    tds: Decimal = Decimal("0")
    annual_tax: Decimal = Decimal("0")
    # India: monthly breakdown of what's already folded into `tds` above
    # (tds = base tax + surcharge + cess) — informational, never summed
    # again into total_employee_deductions. Zero for every country/employee
    # until india.py explicitly computes them.
    surcharge: Decimal = Decimal("0")
    cess: Decimal = Decimal("0")
    social_security: Decimal = Decimal("0")
    medicare: Decimal = Decimal("0")
    ni_employee: Decimal = Decimal("0")
    # UK/Australia: shared study-loan repayment line (Student/Postgraduate
    # Loan / HELP-HECS). Germany: church tax. Canada: CPP2. Zero unless a
    # country calculator explicitly sets it — no existing country's
    # output changes just because these fields now exist.
    study_loan_deduction: Decimal = Decimal("0")
    church_tax: Decimal = Decimal("0")
    cpp2: Decimal = Decimal("0")
    # Canada: CPP/QPP first-layer BASE (4.95%) vs. FIRST-ADDITIONAL
    # (1.00%) breakdown (AC-11) — PURELY informational, like surcharge/
    # cess above: proportions the already-final social_security amount,
    # never recomputes it. Zero until
    # shared._CA_CPP_COMPONENT_SPLIT_ENABLED_COUNTRIES is flipped AND
    # the two separate rate rows are configured — see
    # engine/countries/canada.py's own comment at the computation site.
    cpp_base_amount: Decimal = Decimal("0")
    cpp_first_additional_amount: Decimal = Decimal("0")

    # Canada: cumulative YTD figures AFTER this period, for service.py to
    # persist into PayrollYtdAccumulator/PayslipItem.ytd_snapshot without
    # recomputing. None (every country/employee until YTD is wired) means
    # "not applicable" — see PayrollContext's matching ytd_* fields above.
    ytd_pensionable_earnings: Decimal = None
    ytd_cpp2_pensionable_earnings: Decimal = None
    ytd_insurable_earnings: Decimal = None
    ytd_basic_exemption_used: Decimal = None

    # Canada: the org's aggregate Ontario remuneration YTD AFTER this
    # period, for service.py to persist into OrganizationYtdAccumulator
    # without recomputing. None unless Ontario EHT was actually wired for
    # this calculation — see PayrollContext.on_eht_ytd_remuneration_before.
    on_eht_ytd_remuneration_after: Decimal = None
    # Canada: the same after-period contract as on_eht_ytd_remuneration_after
    # above, for BC EHT, Manitoba HE Levy and NL HAPSET respectively.
    bc_eht_ytd_remuneration_after: Decimal = None
    mb_he_levy_ytd_remuneration_after: Decimal = None
    nl_hapset_ytd_remuneration_after: Decimal = None
    qc_hsf_ytd_remuneration_after: Decimal = None

    # Employer-side contributions
    employer_pf: Decimal = Decimal("0")
    employer_esi: Decimal = Decimal("0")
    employer_social_security: Decimal = Decimal("0")
    employer_medicare: Decimal = Decimal("0")
    employer_pension: Decimal = Decimal("0")
    employer_ni: Decimal = Decimal("0")
    employer_futa: Decimal = Decimal("0")
    # Canada: employer-side CPP2/QPP2 — see cpp2 above; distinct field
    # because it is NOT an employee deduction and must never be summed
    # into total_employee_deductions (engine/standard.py).
    employer_cpp2: Decimal = Decimal("0")
    # Canada: employer-side counterpart to cpp_base_amount/
    # cpp_first_additional_amount above — same purely-informational
    # contract, proportioning employer_social_security.
    employer_cpp_base: Decimal = Decimal("0")
    employer_cpp_first_additional: Decimal = Decimal("0")
    # US: State Unemployment Insurance, tenant/employer-specific (see
    # EmployerTaxProfile). Zero until an org has a configured profile —
    # every other country's output is unaffected.
    employer_sui: Decimal = Decimal("0")
    # Canada: Ontario Employer Health Tax — banded on the ORG's aggregate
    # Ontario remuneration, not this employee's own pay
    # (ZP-TAX-CA-2026-001 §15/§16). Zero until the org-level accumulator
    # is wired for this calculation (on_eht_ytd_remuneration_before is
    # None otherwise) — see engine/countries/canada.py's calculate().
    employer_eht: Decimal = Decimal("0")
    # Canada: BC EHT, Manitoba HE Levy, NL HAPSET — same org-level-
    # accumulator-banded contract as employer_eht above, each its own
    # independent zero-until-wired field (ZP-TAX-CA-2026-001 §15).
    employer_bc_eht: Decimal = Decimal("0")
    employer_mb_he_levy: Decimal = Decimal("0")
    employer_nl_hapset: Decimal = Decimal("0")
    # Quebec: Health Services Fund (org-level-accumulator-banded, sliding
    # rate) and labour standards contribution (per-employee capped, no
    # accumulator) — see engine/countries/canada.py's module docstring.
    employer_qc_hsf: Decimal = Decimal("0")
    employer_qc_labour_standards: Decimal = Decimal("0")
    # UK: employee-side Workplace Pension deduction — distinct from
    # employer_pension above. Zero unless a country calculator explicitly
    # sets it (only uk.py does, and only when an employee-pension rate is
    # configured) — every other country's output is unaffected.
    employee_pension: Decimal = Decimal("0")

    # US: federal/state/local income tax broken out separately for display/
    # reporting — `tds` above remains the correct COMBINED total actually
    # deducted (federal+state+local), unchanged in meaning; these three are
    # purely additive breakdown fields, the same "informational, never
    # summed again" convention surcharge/cess already use for India. Zero
    # for every other country.
    federal_income_tax: Decimal = Decimal("0")
    state_income_tax: Decimal = Decimal("0")
    local_tax: Decimal = Decimal("0")
    # US: state-level statutory payroll program (California SDI first;
    # see engine/countries/us.py). A real employee-side deduction, NOT
    # part of the informational federal/state/local income-tax breakdown
    # above — it's summed into total_deductions like PF/ESI/professional_tax.
    state_disability_insurance: Decimal = Decimal("0")

    # Totals
    total_deductions: Decimal = Decimal("0")
    net_pay: Decimal = Decimal("0")


class PayrollStrategy(ABC):
    """Abstract base for all payroll calculation strategies.

    New policies are added by implementing this interface and registering
    the class in ``resolver.py``.  The core payroll engine never contains
    hardcoded calculation logic — it delegates entirely to the resolved
    strategy.
    """

    @abstractmethod
    def calculate(self, ctx: PayrollContext) -> PayrollResult:
        """Run the full payroll calculation for one employee.

        Implementations MUST:
        1. Compute attendance deduction using the fixed 30-day model.
        2. Apply policy-specific compliance deductions.
        3. Return a fully-populated PayrollResult.
        """
