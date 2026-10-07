"""
modules/payroll/switzerland_schemas.py
--------------------------------------
Switzerland (CH spec) request schemas and the per-scheme_type validators for
ChSchemeProfile.rules. Every model forbids unknown keys, so a misspelt rule
key is a 422, never a silently ignored setting. Percentages are PERCENT
numbers (4.35 = 4.35 %), amounts are Swiss francs.

The `rules` shapes are the CH Step 5 contract. They describe what an employer's
own scheme documents say (plan regulations, policy schedules, fund rates); no
value here is a statutory default.
"""

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.payroll.engine.countries.switzerland_content import CH_CANTON_CODES, CH_SCHEME_TYPES

Pct = Field(ge=Decimal("0"), le=Decimal("100"))
Amount = Field(ge=Decimal("0"))


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _check_canton(value: Optional[str]) -> Optional[str]:
    if value is not None and value not in CH_CANTON_CODES:
        raise ValueError(f"canton must be one of the CH-XX codes, got {value!r}")
    return value


# ── scheme rules, one model per scheme_type ────────────────────────────

class CompensationOfficeRules(_Strict):
    admin_cost_pct: Decimal = Pct


class FakRules(_Strict):
    employer_pct: Decimal = Pct
    employee_pct: Optional[Decimal] = Field(default=None, ge=Decimal("0"), le=Decimal("100"))


class BvgCoordination(BaseModel):
    # mode-specific keys (e.g. a fixed deduction amount) are plan-defined and
    # kept as given; only the mode itself is constrained here.
    model_config = ConfigDict(extra="allow")
    mode: Literal["STATUTORY", "NONE", "PERCENTAGE", "FIXED"]


class BvgBand(_Strict):
    age_from: int = Field(ge=0, le=120)
    age_to: int = Field(ge=0, le=120)
    salary_from: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    salary_to: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    employee_pct: Optional[Decimal] = Field(default=None, ge=Decimal("0"), le=Decimal("100"))
    employee_amount: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    employer_pct: Optional[Decimal] = Field(default=None, ge=Decimal("0"), le=Decimal("100"))
    employer_amount: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    component: Literal["MANDATORY", "EXTRA_MANDATORY"]

    @model_validator(mode="after")
    def _shape(self):
        if self.age_to < self.age_from:
            raise ValueError(f"age_to {self.age_to} is below age_from {self.age_from}")
        if self.salary_from is not None and self.salary_to is not None and self.salary_to < self.salary_from:
            raise ValueError(f"salary_to {self.salary_to} is below salary_from {self.salary_from}")
        if (self.employee_pct is None) == (self.employee_amount is None):
            raise ValueError("exactly one of employee_pct / employee_amount is required")
        if (self.employer_pct is None) == (self.employer_amount is None):
            raise ValueError("exactly one of employer_pct / employer_amount is required")
        if (self.employee_pct is None) != (self.employer_pct is None):
            raise ValueError("employee and employer shares must use the same basis (both pct or both amount) "
                             "so the employer-share rule can be checked")
        employee = self.employee_pct if self.employee_pct is not None else self.employee_amount
        employer = self.employer_pct if self.employer_pct is not None else self.employer_amount
        # Employer pays at least half of each band (CH Step 5 contract).
        if employer < employee:
            raise ValueError(f"band ages {self.age_from}-{self.age_to} ({self.component}): employer share "
                             f"{employer} is below 50% of the total {employer + employee}")
        return self


class BvgPlanRules(_Strict):
    entry_rules: Dict[str, Any]
    insured_salary_def: str = Field(min_length=1, max_length=500)
    coordination: BvgCoordination
    bands: List[BvgBand] = Field(min_length=1)

    @model_validator(mode="after")
    def _no_overlapping_bands(self):
        def overlap(a_lo, a_hi, b_lo, b_hi):
            return (a_hi is None or b_lo is None or b_lo <= a_hi) and (b_hi is None or a_lo is None or a_lo <= b_hi)

        for i, a in enumerate(self.bands):
            for b in self.bands[i + 1:]:
                if (a.component == b.component and overlap(a.age_from, a.age_to, b.age_from, b.age_to)
                        and overlap(a.salary_from, a.salary_to, b.salary_from, b.salary_to)):
                    raise ValueError(f"{a.component} bands ages {a.age_from}-{a.age_to} and {b.age_from}-{b.age_to} "
                                     "overlap on the same salary range")
        return self


class UvgRiskClass(_Strict):
    code: str = Field(min_length=1, max_length=20)
    bu_employer_pct: Decimal = Pct
    nbu_pct: Decimal = Pct
    nbu_employee_share_pct: Decimal = Pct


class UvgPolicyRules(_Strict):
    insurer: str = Field(min_length=1, max_length=200)
    risk_classes: List[UvgRiskClass] = Field(min_length=1)

    @field_validator("risk_classes")
    @classmethod
    def _unique_codes(cls, value):
        codes = [r.code for r in value]
        if len(codes) != len(set(codes)):
            raise ValueError("risk class codes must be unique")
        return value


class KtgPolicyRules(_Strict):
    rate_pct: Decimal = Pct
    employee_share_pct: Decimal = Pct
    base_def: str = Field(min_length=1, max_length=500)


SCHEME_RULE_MODELS = {
    "COMPENSATION_OFFICE": CompensationOfficeRules,
    "FAK": FakRules,
    "BVG_PLAN": BvgPlanRules,
    "UVG_POLICY": UvgPolicyRules,
    "KTG_POLICY": KtgPolicyRules,
}
assert set(SCHEME_RULE_MODELS) == set(CH_SCHEME_TYPES)


def validate_scheme_rules(scheme_type: str, rules: dict) -> dict:
    """The rules normalised to JSON (Decimals as strings, None keys dropped),
    or ValueError/ValidationError naming what is wrong."""
    model = SCHEME_RULE_MODELS.get(scheme_type)
    if model is None:
        raise ValueError(f"scheme_type must be one of {list(CH_SCHEME_TYPES)}")
    return model.model_validate(rules or {}).model_dump(mode="json", exclude_none=True)


# ── request bodies ──────────────────────────────────────────────────────

class ChSchemeCreate(_Strict):
    schemeType: Literal["COMPENSATION_OFFICE", "FAK", "BVG_PLAN", "UVG_POLICY", "KTG_POLICY"]
    schemeCode: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(default="1.0", min_length=1, max_length=20)
    authorityIdentifier: Optional[str] = Field(default=None, max_length=50)
    canton: Optional[str] = None
    rules: Dict[str, Any]
    effectiveFrom: date
    effectiveTo: Optional[date] = None
    sourceDocumentId: Optional[int] = None
    reason: Optional[str] = Field(default=None, max_length=500)

    _canton = field_validator("canton")(classmethod(lambda cls, v: _check_canton(v)))


class ChSchemeUpdate(_Strict):
    """Edit of a DRAFT version only. schemeType / schemeCode / version are the
    version's identity and cannot change — create a new version instead."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    authorityIdentifier: Optional[str] = Field(default=None, max_length=50)
    canton: Optional[str] = None
    rules: Optional[Dict[str, Any]] = None
    effectiveFrom: Optional[date] = None
    effectiveTo: Optional[date] = None
    sourceDocumentId: Optional[int] = None
    reason: Optional[str] = Field(default=None, max_length=500)

    _canton = field_validator("canton")(classmethod(lambda cls, v: _check_canton(v)))


class ChReasonBody(_Strict):
    reason: Optional[str] = Field(default=None, max_length=500)


class ChCantonRegistration(_Strict):
    canton: str
    qstDebtorNumber: Optional[str] = Field(default=None, max_length=50)
    reference: Optional[str] = Field(default=None, max_length=100)

    _canton = field_validator("canton")(classmethod(lambda cls, v: _check_canton(v)))


class ChEntityProfileUpsert(_Strict):
    """A new profile version. readiness_* are deliberately absent: readiness
    is derived server-side and a client-sent value is refused (422)."""
    uid: Optional[str] = Field(default=None, max_length=15)
    seatCanton: Optional[str] = None
    cantonRegistrations: List[ChCantonRegistration] = Field(default_factory=list)
    compensationOfficeSchemeId: Optional[int] = None
    fakSchemeId: Optional[int] = None
    effectiveFrom: date
    reason: Optional[str] = Field(default=None, max_length=500)

    _canton = field_validator("seatCanton")(classmethod(lambda cls, v: _check_canton(v)))

    @field_validator("cantonRegistrations")
    @classmethod
    def _unique_cantons(cls, value):
        cantons = [r.canton for r in value]
        if len(cantons) != len(set(cantons)):
            raise ValueError("one registration per canton")
        return value


class ChTaxabilityRuleCreate(_Strict):
    earningType: str = Field(min_length=1, max_length=50)
    taxComponent: str = Field(min_length=1, max_length=30)
    isTaxable: bool
    treatment: Optional[str] = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,29}$")
    jurisdictionState: Optional[str] = None
    effectiveFrom: date
    effectiveTo: Optional[date] = None
    sourceDocumentId: Optional[int] = None
    reason: Optional[str] = Field(default=None, max_length=500)

    _canton = field_validator("jurisdictionState")(classmethod(lambda cls, v: _check_canton(v)))


class ChWageFloorScale(_Strict):
    occupation: Optional[str] = Field(default=None, max_length=100)
    grade: Optional[str] = Field(default=None, max_length=50)
    experience_years_from: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    amount: Decimal = Field(gt=Decimal("0"))


class ChWageFloor(_Strict):
    basis: Literal["HOURLY", "MONTHLY", "ANNUAL"]
    amount: Optional[Decimal] = Field(default=None, gt=Decimal("0"))
    scales: List[ChWageFloorScale] = Field(default_factory=list)

    @model_validator(mode="after")
    def _something_to_apply(self):
        if self.amount is None and not self.scales:
            raise ValueError("a wage floor needs a base amount or at least one scale row")
        return self


class ChWageFloorCreate(_Strict):
    agreementType: Literal["CH_CANTON_MINIMUM", "CH_GAV", "CH_NAV"]
    agreementCode: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(default="1.0", min_length=1, max_length=20)
    jurisdictionState: Optional[str] = None
    employerScope: Optional[str] = None
    employeeGroup: Optional[str] = Field(default=None, max_length=100)
    wageFloor: ChWageFloor
    effectiveFrom: date
    effectiveTo: Optional[date] = None
    sourceDocumentId: Optional[int] = None
    reason: Optional[str] = Field(default=None, max_length=500)

    _canton = field_validator("jurisdictionState")(classmethod(lambda cls, v: _check_canton(v)))

    @model_validator(mode="after")
    def _canton_minimum_needs_a_canton(self):
        if self.agreementType == "CH_CANTON_MINIMUM" and not self.jurisdictionState:
            raise ValueError("a CH_CANTON_MINIMUM wage floor needs jurisdictionState (the canton)")
        if self.effectiveTo is not None and self.effectiveTo < self.effectiveFrom:
            raise ValueError("effectiveTo is before effectiveFrom")
        return self


class ChQstResolveRequest(_Strict):
    """Facts for the advisory QST check (POST /switzerland/qst/resolve)."""
    nationality: Optional[str] = Field(default=None, min_length=2, max_length=2)
    residenceCountry: Optional[str] = Field(default=None, min_length=2, max_length=2)
    permitType: Optional[str] = Field(default=None, max_length=10)
    maritalStatus: Optional[str] = Field(default=None, max_length=20)
    spouseSwissOrPermitC: Optional[bool] = None
    spouseEmployed: Optional[bool] = None
    childrenCount: Optional[int] = Field(default=None, ge=0, le=30)
    churchTax: Optional[bool] = None
    qstCanton: Optional[str] = None
    onDate: Optional[date] = None

    def as_facts(self) -> dict:
        return {"nationality": self.nationality, "residence_country": self.residenceCountry,
                "permit_type": self.permitType, "marital_status": self.maritalStatus,
                "spouse_swiss_or_permit_c": self.spouseSwissOrPermitC, "spouse_employed": self.spouseEmployed,
                "children_count": self.childrenCount, "church_tax": self.churchTax,
                "qst_canton": self.qstCanton, "on_date": self.onDate}


# ── Step 11: family-allowance entitlements + absence-benefit events ──────

class ChFamilyAllowanceCreate(_Strict):
    employeeId: int
    allowanceType: Literal["CHILD", "EDUCATION", "BIRTH", "ADOPTION"]
    childReference: Optional[str] = Field(default=None, max_length=50)
    childBirthDate: Optional[date] = None
    trainingStatus: Optional[str] = Field(default=None, max_length=30)
    entitlementBasis: Literal["PRIMARY", "DIFFERENTIAL"] = "PRIMARY"
    # DIFFERENTIAL only: what the PRIMARY fund elsewhere pays per month — the
    # proof that this employer owes only the difference.
    primaryFundAmount: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    primaryFundReference: Optional[str] = Field(default=None, max_length=100)
    canton: Optional[str] = None
    fakSchemeId: Optional[int] = None
    periodFrom: date
    periodTo: Optional[date] = None
    fundDecisionReference: Optional[str] = Field(default=None, max_length=100)
    sourceDocumentId: Optional[int] = None
    reason: Optional[str] = Field(default=None, max_length=500)

    _canton = field_validator("canton")(classmethod(lambda cls, v: _check_canton(v)))

    @model_validator(mode="after")
    def _shape(self):
        if self.periodTo is not None and self.periodTo < self.periodFrom:
            raise ValueError("periodTo is before periodFrom")
        if self.entitlementBasis == "DIFFERENTIAL" and self.primaryFundAmount is None:
            raise ValueError("a DIFFERENTIAL entitlement needs primaryFundAmount (what the primary fund pays)")
        if self.entitlementBasis == "PRIMARY" and (self.primaryFundAmount is not None or self.primaryFundReference):
            raise ValueError("primaryFundAmount / primaryFundReference apply only to a DIFFERENTIAL entitlement")
        return self


class ChFamilyAllowanceUpdate(_Strict):
    """Edit of a REQUESTED entitlement only (an APPROVED one is the fund's
    decision of record and never edited)."""
    childReference: Optional[str] = Field(default=None, max_length=50)
    childBirthDate: Optional[date] = None
    trainingStatus: Optional[str] = Field(default=None, max_length=30)
    primaryFundAmount: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    primaryFundReference: Optional[str] = Field(default=None, max_length=100)
    canton: Optional[str] = None
    fakSchemeId: Optional[int] = None
    periodFrom: Optional[date] = None
    periodTo: Optional[date] = None
    fundDecisionReference: Optional[str] = Field(default=None, max_length=100)
    sourceDocumentId: Optional[int] = None
    reason: Optional[str] = Field(default=None, max_length=500)

    _canton = field_validator("canton")(classmethod(lambda cls, v: _check_canton(v)))


class ChAbsenceEventCreate(_Strict):
    employeeId: int
    eventType: Literal["MATERNITY", "OTHER_PARENT", "ADOPTION", "ILLNESS_CO", "ILLNESS_KTG", "ACCIDENT_UVG",
                       "PREGNANCY_PROTECTION"]
    periodFrom: date
    periodTo: Optional[date] = None
    dailyAllowanceRate: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    insuredSalaryBasis: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    insurerClaimReference: Optional[str] = Field(default=None, max_length=100)
    benefitAmountExpected: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    benefitAmountReceived: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    employerTopupAmount: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    evidenceDocumentId: Optional[int] = None
    reason: Optional[str] = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _shape(self):
        if self.periodTo is not None and self.periodTo < self.periodFrom:
            raise ValueError("periodTo is before periodFrom")
        if self.eventType in ("ILLNESS_CO", "PREGNANCY_PROTECTION") and self.dailyAllowanceRate is not None:
            raise ValueError(f"{self.eventType} carries no insurer daily allowance")
        return self


class ChAbsenceEventUpdate(_Strict):
    """Edit of an OPEN event; status CLOSED freezes it."""
    periodTo: Optional[date] = None
    dailyAllowanceRate: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    insuredSalaryBasis: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    insurerClaimReference: Optional[str] = Field(default=None, max_length=100)
    benefitAmountExpected: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    benefitAmountReceived: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    employerTopupAmount: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    evidenceDocumentId: Optional[int] = None
    status: Optional[Literal["OPEN", "CLOSED"]] = None
    reason: Optional[str] = Field(default=None, max_length=500)


class ChCalculationPreviewRequest(_Strict):
    """Super Admin preview for one real CH employee (read-only)."""
    organizationId: int
    employeeId: int
    payDate: date
    periodStart: Optional[date] = None
    periodEnd: Optional[date] = None
    # {earning_type: monthly amount}; default {"base_salary": ctc / 12}
    earnings: Optional[Dict[str, Decimal]] = None


class ChCorrectionCreate(_Strict):
    """Append-only correction of a finalized CH payslip (Step 13)."""
    originalPayslipId: int
    reason: str = Field(min_length=3, max_length=500)
    affectedObligations: List[str] = Field(min_length=1)
    # restated inputs only (earnings, worker facts, QST tariff facts) —
    # see switzerland_service.CH_CORRECTABLE_INPUTS
    correctedInputs: Dict[str, Any] = Field(default_factory=dict)
