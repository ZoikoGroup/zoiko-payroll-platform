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
    # Canada TD1X employee-requested additional per-pay-period
    # withholding — additive on top of tds, never touching the statutory
    # base calculation. None/0 for every employee until explicitly set.
    td1_additional_tax: Decimal = None
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

    # Canada: cumulative YTD figures AFTER this period, for service.py to
    # persist into PayrollYtdAccumulator/PayslipItem.ytd_snapshot without
    # recomputing. None (every country/employee until YTD is wired) means
    # "not applicable" — see PayrollContext's matching ytd_* fields above.
    ytd_pensionable_earnings: Decimal = None
    ytd_cpp2_pensionable_earnings: Decimal = None
    ytd_insurable_earnings: Decimal = None
    ytd_basic_exemption_used: Decimal = None

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
    # US: State Unemployment Insurance, tenant/employer-specific (see
    # EmployerTaxProfile). Zero until an org has a configured profile —
    # every other country's output is unaffected.
    employer_sui: Decimal = Decimal("0")
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
