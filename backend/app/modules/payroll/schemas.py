"""
modules/payroll/schemas.py
--------------------------
Pydantic schemas for the Zoiko Payroll module.

Response schemas use explicit `validation_alias` / `serialization_alias`
pairs so the JSON returned to the frontend matches the exact field names
already consumed by payrollService.js and the React components
(RunsTable, RunDetailPage, PayslipsPage, ContributionRatesTable,
TaxSlabTable, StatCards, CostTrendChart, RecentActivity, CompliancePage)
with zero client-side mapping.

IMPORTANT: every route that returns one of these models must pass
`response_model_by_alias=True` on the route decorator (see router.py) so
FastAPI serializes using the camelCase aliases instead of the snake_case
Python field names.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional, List, Dict, Annotated, ClassVar
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, BeforeValidator, field_validator, model_validator
from app.modules.payroll.models import PayrollStatus, PayslipStatus, ActivityStatus
from app.modules.payroll.employee_validation import mask_compliance_fields, mask_identifier, mask_routing


def coerce_str(v):
    if v is None:
        return None
    return str(v)


CoercedStr = Annotated[Optional[str], BeforeValidator(coerce_str)]


def coerce_decimal(v):
    # Spreadsheet cells and cleared form fields arrive as "" (not null/absent)
    # — Decimal's validator rejects "" outright, so normalize it to None first.
    if v == "":
        return None
    return v


CoercedDecimal = Annotated[Optional[Decimal], BeforeValidator(coerce_decimal)]


# ── Employees ────────────────────────────────────────────────────────
# Backed by payroll's own PayrollEmployee model (models.py) — fully
# decoupled from app.modules.employee.Employee (the separate HR/auth
# login record). Full CRUD is appropriate here since this is payroll's
# own master data, org-scoped for multi-tenancy.

class EmployeeCreate(BaseModel):
    employee_code:    Optional[str] = None
    name:             Optional[str] = Field(None, validation_alias="name")
    email:            Optional[str] = None
    phone:            Optional[str] = None
    department:       Optional[str] = None
    designation:      Optional[str] = None
    employment_type:  str = Field("Full-time", validation_alias="employmentType")
    status:           str = "Active"
    date_of_joining:  Optional[date] = Field(None, validation_alias="dateOfJoining")
    # Generic HR fact (not Canada-only), currently consumed by CPP/QPP's
    # age 18/70 mandatory contribution window (ZP-TAX-CA-2026-001 §10 —
    # see engine/countries/canada.py's _is_age_gated_cpp_stopped).
    date_of_birth:    Optional[date] = Field(None, validation_alias="dateOfBirth")
    ctc:              Optional[Decimal] = Decimal("0")
    basic:            CoercedDecimal = Field(None, validation_alias="basic")
    hra:              CoercedDecimal = Field(None, validation_alias="hra")
    bank_name:        Optional[str] = Field(None, validation_alias="bankName")
    bank_account:     Optional[str] = Field(None, validation_alias="bankAccountNumber")
    pan:              Optional[str] = Field(None, validation_alias="panNumber")
    uan:              Optional[str] = None
    ifsc:             Optional[str] = Field(None, validation_alias="ifscCode")
    country_code:     Optional[str] = Field(None, validation_alias="countryCode")
    # Canada-specific: labour-sponsored funds tax credit declaration
    # (ZP-TAX-CA-2026-001 §6 — see canada.py's _calculate_lsvcc_credit).
    lsvcc_investment_amount: Optional[Decimal] = Field(None, validation_alias="lsvccInvestmentAmount")
    # Canada-specific: TD1X commission formula inputs (ZP-TAX-CA-2026-001
    # §18/§19 — see service.calculate_ca_td1x_commission_withholding).
    td1x_estimated_annual_commission: Optional[Decimal] = Field(None, validation_alias="td1xEstimatedAnnualCommission")
    td1x_estimated_annual_expenses:   Optional[Decimal] = Field(None, validation_alias="td1xEstimatedAnnualExpenses")
    compliance_fields: Optional[dict] = Field(None, validation_alias="complianceFields")
    # UK RTI (ZP-TAX-UK-2026-27-001 §18 gap-closure Part 9, 2026-09-09).
    address_line1:    Optional[str] = Field(None, validation_alias="addressLine1")
    address_line2:    Optional[str] = Field(None, validation_alias="addressLine2")
    address_town:     Optional[str] = Field(None, validation_alias="addressTown")
    address_county:   Optional[str] = Field(None, validation_alias="addressCounty")
    address_postcode: Optional[str] = Field(None, validation_alias="addressPostcode")
    starter_declaration: Optional[str] = Field(None, validation_alias="starterDeclaration")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class EmployeeUpdate(BaseModel):
    employee_code:    Optional[str] = None
    name:             Optional[str] = Field(None, validation_alias="name")
    email:            Optional[str] = None
    phone:            Optional[str] = None
    department:       Optional[str] = None
    designation:      Optional[str] = None
    employment_type:  Optional[str] = Field(None, validation_alias="employmentType")
    status:           Optional[str] = None
    date_of_joining:  Optional[date] = Field(None, validation_alias="dateOfJoining")
    date_of_birth:    Optional[date] = Field(None, validation_alias="dateOfBirth")
    ctc:              Optional[Decimal] = None
    basic:            CoercedDecimal = Field(None, validation_alias="basic")
    hra:              CoercedDecimal = Field(None, validation_alias="hra")
    bank_name:        Optional[str] = Field(None, validation_alias="bankName")
    bank_account:     Optional[str] = Field(None, validation_alias="bankAccountNumber")
    pan:              Optional[str] = Field(None, validation_alias="panNumber")
    uan:              Optional[str] = None
    ifsc:             Optional[str] = Field(None, validation_alias="ifscCode")
    country_code:     Optional[str] = Field(None, validation_alias="countryCode")
    lsvcc_investment_amount: Optional[Decimal] = Field(None, validation_alias="lsvccInvestmentAmount")
    td1x_estimated_annual_commission: Optional[Decimal] = Field(None, validation_alias="td1xEstimatedAnnualCommission")
    td1x_estimated_annual_expenses:   Optional[Decimal] = Field(None, validation_alias="td1xEstimatedAnnualExpenses")
    compliance_fields: Optional[dict] = Field(None, validation_alias="complianceFields")
    address_line1:    Optional[str] = Field(None, validation_alias="addressLine1")
    address_line2:    Optional[str] = Field(None, validation_alias="addressLine2")
    address_town:     Optional[str] = Field(None, validation_alias="addressTown")
    address_county:   Optional[str] = Field(None, validation_alias="addressCounty")
    address_postcode: Optional[str] = Field(None, validation_alias="addressPostcode")
    starter_declaration: Optional[str] = Field(None, validation_alias="starterDeclaration")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class EmployeeResponse(BaseModel):
    id:              int
    employeeCode:    str = Field(validation_alias="employee_code", serialization_alias="employeeCode")
    legacyCode:      Optional[str] = Field(None, validation_alias="legacy_code", serialization_alias="legacyCode")
    name:            str = Field(validation_alias="name", serialization_alias="name")
    email:           Optional[str] = None
    phone:           Optional[str] = None
    department:      Optional[str] = None
    designation:     Optional[str] = None
    employmentType:  str = Field(validation_alias="employment_type", serialization_alias="employmentType")
    status:          str
    dateOfJoining:   Optional[date] = Field(None, validation_alias="date_of_joining", serialization_alias="dateOfJoining")
    dateOfBirth:     Optional[date] = Field(None, validation_alias="date_of_birth", serialization_alias="dateOfBirth")
    ctc:             Optional[Decimal] = Decimal("0")
    basic:           Optional[Decimal] = Field(None, validation_alias="basic", serialization_alias="basic")
    hra:             Optional[Decimal] = Field(None, validation_alias="hra", serialization_alias="hra")
    bankName:        Optional[str] = Field(None, validation_alias="bank_name", serialization_alias="bankName")
    # Serialized as bankAccountNumber/panNumber to match the field names
    # EmployeeCreate/EmployeeUpdate/BulkEmployeeItem already expect on write —
    # this response previously used shorter names ("bankAccount"/"pan"),
    # so the Edit form (which reads bankAccountNumber/panNumber, matching
    # what it also sends on save) always saw them as blank on load.
    bankAccount:     Optional[str] = Field(None, validation_alias="bank_account", serialization_alias="bankAccountNumber")
    pan:             Optional[str] = Field(None, serialization_alias="panNumber")
    uan:             Optional[str] = None
    ifsc:            Optional[str] = Field(None, serialization_alias="ifscCode")
    countryCode:     Optional[str] = Field(None, validation_alias="country_code", serialization_alias="countryCode")
    lsvccInvestmentAmount: Optional[Decimal] = Field(None, validation_alias="lsvcc_investment_amount", serialization_alias="lsvccInvestmentAmount")
    td1xEstimatedAnnualCommission: Optional[Decimal] = Field(None, validation_alias="td1x_estimated_annual_commission", serialization_alias="td1xEstimatedAnnualCommission")
    td1xEstimatedAnnualExpenses:   Optional[Decimal] = Field(None, validation_alias="td1x_estimated_annual_expenses", serialization_alias="td1xEstimatedAnnualExpenses")
    complianceFields: Optional[dict] = Field(None, validation_alias="compliance_fields", serialization_alias="complianceFields")
    customFields:    Optional[dict] = Field(None, validation_alias="custom_fields", serialization_alias="customFields")
    # Multi-jurisdiction routing (ZP-MJR-2026-001) — additive: ifscCode/
    # complianceFields above are unchanged, `routing` adds the
    # jurisdiction-correct [{key,label,value}] list resolved from the
    # employee's own country (India -> IFSC from the dedicated column;
    # every other country -> its compliance_fields routing codes).
    routing:         Optional[List[dict]] = None
    addressLine1:    Optional[str] = Field(None, validation_alias="address_line1", serialization_alias="addressLine1")
    addressLine2:    Optional[str] = Field(None, validation_alias="address_line2", serialization_alias="addressLine2")
    addressTown:     Optional[str] = Field(None, validation_alias="address_town", serialization_alias="addressTown")
    addressCounty:   Optional[str] = Field(None, validation_alias="address_county", serialization_alias="addressCounty")
    addressPostcode: Optional[str] = Field(None, validation_alias="address_postcode", serialization_alias="addressPostcode")
    starterDeclaration: Optional[str] = Field(None, validation_alias="starter_declaration", serialization_alias="starterDeclaration")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    # Sensitive identifiers (SSN/NINO/TFN/SIN/Steuer-ID/IBAN/NRIC-FIN/…,
    # employee_validation.SENSITIVE_COMPLIANCE_FIELDS) are masked in every
    # response; stored values are untouched and an edit form's round-tripped
    # mask is restored server-side (restore_masked_compliance_fields).
    @field_validator("complianceFields")
    @classmethod
    def _mask_sensitive_compliance_fields(cls, value):
        return mask_compliance_fields(value)

    # Personal account / tax identifiers in top-level columns and the IBAN
    # routing entry — same shared masking (stored values untouched; the
    # edit form's round-tripped mask is restored server-side).
    @field_validator("bankAccount", "pan", "uan")
    @classmethod
    def _mask_sensitive_columns(cls, value):
        return mask_identifier(value) if value else value

    @field_validator("routing")
    @classmethod
    def _mask_routing_account_identifiers(cls, value):
        return mask_routing(value)


# ── Employee Statutory Profile (effective-dated) ─────────────────────────
# See models.EmployeeStatutoryProfile's own docstring. Only a create/append
# schema exists — this table is never updated in place, so there is no
# EmployeeStatutoryProfileUpdate.

class EmployeeStatutoryProfileCreate(BaseModel):
    country_code:    Optional[str] = Field(None, validation_alias="countryCode")
    effective_from:  date = Field(validation_alias="effectiveFrom")
    effective_to:    Optional[date] = Field(None, validation_alias="effectiveTo")
    reason:          Optional[str] = None

    de_tax_class:                     Optional[str] = Field(None, validation_alias="deTaxClass")
    de_factor:                        Optional[Decimal] = Field(None, validation_alias="deFactor")
    de_church_tax_liable:             Optional[bool] = Field(None, validation_alias="deChurchTaxLiable")
    de_church_tax_land:               Optional[str] = Field(None, validation_alias="deChurchTaxLand")
    # Master audit — genuine gap closure: these two columns have existed on
    # the model and been READ by resolve_germany_church_tax_exception's own
    # caller (service.py's _resolve_germany_calc_inputs) since the Bad
    # Wimpfen exception mechanism was built, but were never exposed on
    # EITHER this schema or the Response schema below — meaning no caller,
    # UI or API, could ever set them. Any published church-tax exception
    # (Land + denomination + postal code) was therefore unreachable by
    # every employee, regardless of registry completeness.
    de_church_tax_denomination:       Optional[str] = Field(None, validation_alias="deChurchTaxDenomination")
    de_church_tax_municipality_postal_code: Optional[str] = Field(None, validation_alias="deChurchTaxMunicipalityPostalCode")
    de_child_count:                   Optional[int] = Field(None, validation_alias="deChildCount")
    de_childless:                     Optional[bool] = Field(None, validation_alias="deChildless")
    de_saxony:                        Optional[bool] = Field(None, validation_alias="deSaxony")
    de_health_insurance_status:       Optional[str] = Field(None, validation_alias="deHealthInsuranceStatus")
    de_health_fund_code:              Optional[str] = Field(None, validation_alias="deHealthFundCode")
    de_u1_tariff_id:                  Optional[str] = Field(None, validation_alias="deU1TariffId")
    de_pension_insurance_exempt:      Optional[bool] = Field(None, validation_alias="dePensionInsuranceExempt")
    de_unemployment_insurance_exempt: Optional[bool] = Field(None, validation_alias="deUnemploymentInsuranceExempt")
    de_employment_classification:     Optional[str] = Field(None, validation_alias="deEmploymentClassification")
    de_elstam_source:                 Optional[str] = Field(None, validation_alias="deElstamSource")
    de_elstam_fallback_reason:        Optional[str] = Field(None, validation_alias="deElstamFallbackReason")
    de_vocational_trainee:            Optional[bool] = Field(None, validation_alias="deVocationalTrainee")

    # Phase 8N — ELStAM / employee-withholding-state completion.
    de_zkf_override:                  Optional[Decimal] = Field(None, validation_alias="deZkfOverride")
    de_jfreib:                        Optional[Decimal] = Field(None, validation_alias="deJfreib")
    de_lzzfreib:                      Optional[Decimal] = Field(None, validation_alias="deLzzfreib")
    de_jhinzu:                        Optional[Decimal] = Field(None, validation_alias="deJhinzu")
    de_lzzhinzu:                      Optional[Decimal] = Field(None, validation_alias="deLzzhinzu")
    de_pkpv:                          Optional[Decimal] = Field(None, validation_alias="dePkpv")
    de_pkpvagz:                       Optional[Decimal] = Field(None, validation_alias="dePkpvagz")
    de_main_employment:               Optional[bool] = Field(None, validation_alias="deMainEmployment")
    de_elstam_schema_version:          Optional[str] = Field(None, validation_alias="deElstamSchemaVersion")
    de_elstam_import_reference:       Optional[str] = Field(None, validation_alias="deElstamImportReference")

    # Phase 8AB — explicit, per-employee, effective-dated overtime/premium
    # Grundlohn source (never derived — see models.py's own field docstring).
    de_grundlohn_hourly:               Optional[Decimal] = Field(None, validation_alias="deGrundlohnHourly")

    # Hong Kong (ZP-HK-ENG-001 §3) — worker FACTS only; validated by
    # service._validate_statutory_profile_fields. Fields not sent carry
    # forward from the previous HK version (each version is a full snapshot).
    hk_employment_relationship: Optional[str] = Field(None, validation_alias="hkgEmploymentRelationship")
    hk_identity_document_type: Optional[str] = Field(None, validation_alias="hkgIdentityDocumentType")
    hk_residency_status: Optional[str] = Field(None, validation_alias="hkgResidencyStatus")
    hk_visa_type: Optional[str] = Field(None, validation_alias="hkgVisaType")
    hk_entered_for_employment: Optional[bool] = Field(None, validation_alias="hkgEnteredForEmployment")
    hk_permission_to_stay_until: Optional[date] = Field(None, validation_alias="hkgPermissionToStayUntil")
    hk_overseas_scheme_member: Optional[bool] = Field(None, validation_alias="hkgOverseasSchemeMember")
    hk_mpf_exemption_code: Optional[str] = Field(None, validation_alias="hkgMpfExemptionCode")
    hk_mpf_exemption_reason: Optional[str] = Field(None, validation_alias="hkgMpfExemptionReason")
    hk_mpf_exemption_evidence_ref: Optional[str] = Field(None, validation_alias="hkgMpfExemptionEvidenceRef")
    hk_mpf_scheme_ref: Optional[str] = Field(None, validation_alias="hkgMpfSchemeRef")
    hk_employment_continuity_start: Optional[date] = Field(None, validation_alias="hkgEmploymentContinuityStart")
    hk_pay_basis: Optional[str] = Field(None, validation_alias="hkgPayBasis")
    hk_contractual_weekly_hours: Optional[Decimal] = Field(None, validation_alias="hkgContractualWeeklyHours")
    hk_likely_chargeable: Optional[bool] = Field(None, validation_alias="hkgLikelyChargeable")
    hk_arrival_date: Optional[date] = Field(None, validation_alias="hkgArrivalDate")
    hk_expected_departure_date: Optional[date] = Field(None, validation_alias="hkgExpectedDepartureDate")
    hk_frequent_travel_exempt: Optional[bool] = Field(None, validation_alias="hkgFrequentTravelExempt")
    hk_termination_date: Optional[date] = Field(None, validation_alias="hkgTerminationDate")
    hk_termination_reason: Optional[str] = Field(None, validation_alias="hkgTerminationReason")
    hk_pre_transition_monthly_wage: Optional[Decimal] = Field(None, validation_alias="hkgPreTransitionMonthlyWage")
    hk_pre_transition_wage_basis: Optional[str] = Field(None, validation_alias="hkgPreTransitionWageBasis")
    hk_pre_transition_evidence_ref: Optional[str] = Field(None, validation_alias="hkgPreTransitionEvidenceRef")
    # ── Sweden (ZP-SE-ENG-001 §2/§20/§21) ──────────────────────────────────
    # Applicability-resolver inputs; every one is an employer-recorded FACT,
    # never a calculated result (see models.py EmployeeStatutoryProfile's SE
    # block for the full field-by-field rationale).
    se_tax_status:              Optional[str] = Field(None, validation_alias="seTaxStatus")
    se_income_role:             Optional[str] = Field(None, validation_alias="seIncomeRole")
    se_tax_table:               Optional[str] = Field(None, validation_alias="seTaxTable")
    se_tax_column:              Optional[str] = Field(None, validation_alias="seTaxColumn")
    se_skatteverket_decision_id: Optional[str] = Field(None, validation_alias="seSkatteverketDecisionId")
    se_decision_effective_from: Optional[date] = Field(None, validation_alias="seDecisionEffectiveFrom")
    se_decision_effective_to:   Optional[date] = Field(None, validation_alias="seDecisionEffectiveTo")
    se_decision_override:       Optional[bool] = Field(None, validation_alias="seDecisionOverride")
    se_decision_monthly_withholding: Optional[Decimal] = Field(None, validation_alias="seDecisionMonthlyWithholding")
    se_decision_rate_pct:            Optional[Decimal] = Field(None, validation_alias="seDecisionRatePct")
    se_sink_status:             Optional[str] = Field(None, validation_alias="seSinkStatus")
    se_sink_decision:           Optional[str] = Field(None, validation_alias="seSinkDecision")
    se_residence_municipality:  Optional[str] = Field(None, validation_alias="seResidenceMunicipality")
    se_tax_table_area:          Optional[str] = Field(None, validation_alias="seTaxTableArea")
    se_social_insurance_status: Optional[str] = Field(None, validation_alias="seSocialInsuranceStatus")
    se_foreign_coverage_status: Optional[str] = Field(None, validation_alias="seForeignCoverageStatus")
    se_a1_status:               Optional[str] = Field(None, validation_alias="seA1Status")
    se_agreement_country:       Optional[str] = Field(None, validation_alias="seAgreementCountry")
    se_coverage_start:          Optional[date] = Field(None, validation_alias="seCoverageStart")
    se_coverage_end:            Optional[date] = Field(None, validation_alias="seCoverageEnd")
    se_evidence_document:       Optional[str] = Field(None, validation_alias="seEvidenceDocument")
    se_evidence_validation:     Optional[str] = Field(None, validation_alias="seEvidenceValidation")
    se_cba_status:              Optional[str] = Field(None, validation_alias="seCbaStatus")
    se_cba_id:                  Optional[int] = Field(None, validation_alias="seCbaId")
    se_cba_version:             Optional[str] = Field(None, validation_alias="seCbaVersion")
    se_occupation:              Optional[str] = Field(None, validation_alias="seOccupation")
    se_grade:                   Optional[str] = Field(None, validation_alias="seGrade")
    se_pension_plan:            Optional[str] = Field(None, validation_alias="sePensionPlan")
    se_pension_provider:        Optional[str] = Field(None, validation_alias="sePensionProvider")
    se_employee_pension_share:  Optional[Decimal] = Field(None, validation_alias="seEmployeePensionShare")
    se_employer_pension_share:  Optional[Decimal] = Field(None, validation_alias="seEmployerPensionShare")
    se_payroll_period:          Optional[str] = Field(None, validation_alias="sePayrollPeriod")
    se_agi_reporting_period:    Optional[str] = Field(None, validation_alias="seAgiReportingPeriod")
    se_monthly_gross:           Optional[Decimal] = Field(None, validation_alias="seMonthlyGross")
    se_taxable_benefits:        Optional[Decimal] = Field(None, validation_alias="seTaxableBenefits")
    se_annual_income:           Optional[Decimal] = Field(None, validation_alias="seAnnualIncome")

    # ── Italy (ZP-IT-ENG-001 §18) — worker-owned facts; see models.py's it_*
    # block. Vocabularies are validated by _it_profile_field_errors.
    it_cnel_code:                 Optional[str] = Field(None, validation_alias="itCnelCode")
    it_cnel_level:                Optional[str] = Field(None, validation_alias="itCnelLevel")
    it_worker_class:              Optional[str] = Field(None, validation_alias="itWorkerClass")
    it_contract_type:             Optional[str] = Field(None, validation_alias="itContractType")
    it_cigs_applies:              Optional[bool] = Field(None, validation_alias="itCigsApplies")
    it_contributory_cap_cohort:   Optional[str] = Field(None, validation_alias="itContributoryCapCohort")
    it_employer_contrib_opted:    Optional[bool] = Field(None, validation_alias="itEmployerContribOpted")
    it_tfr_destination:           Optional[str] = Field(None, validation_alias="itTfrDestination")
    it_pension_fund:              Optional[str] = Field(None, validation_alias="itPensionFund")
    it_tfr_destination_from:      Optional[date] = Field(None, validation_alias="itTfrDestinationFrom")
    it_tax_domicile_comune:       Optional[str] = Field(None, validation_alias="itTaxDomicileComune")
    it_tax_domicile_region:       Optional[str] = Field(None, validation_alias="itTaxDomicileRegion")
    it_tax_domicile_from:         Optional[date] = Field(None, validation_alias="itTaxDomicileFrom")
    it_fringe_child_declared:     Optional[bool] = Field(None, validation_alias="itFringeChildDeclared")
    it_contractual_weekly_hours:  Optional[Decimal] = Field(None, validation_alias="itContractualWeeklyHours")
    it_termination_reason:        Optional[str] = Field(None, validation_alias="itTerminationReason")

    # ── Saudi Arabia (ZP-SA-ENG-001 §3/§4) — worker-owned GOSI facts; see
    # models.py's sa_* block. Worker class + cohort are validated by
    # saudi_arabia_service._sa_statutory_profile_errors; fields not sent carry
    # forward from the previous SA version (each version is a full snapshot).
    sa_worker_class:              Optional[str] = Field(None, validation_alias="saWorkerClass")
    sa_cohort:                    Optional[str] = Field(None, validation_alias="saCohort")
    sa_cohort_evidence_ref:       Optional[str] = Field(None, validation_alias="saCohortEvidenceRef")
    sa_cohort_source_document_id: Optional[int] = Field(None, validation_alias="saCohortSourceDocumentId")
    sa_cohort_verified_by_id:     Optional[int] = Field(None, validation_alias="saCohortVerifiedById")
    sa_cohort_verified_at:        Optional[datetime] = Field(None, validation_alias="saCohortVerifiedAt")
    sa_identity_document_type:    Optional[str] = Field(None, validation_alias="saIdentityDocumentType")
    sa_identity_token:            Optional[str] = Field(None, validation_alias="saIdentityToken")
    sa_identity_expiry:           Optional[date] = Field(None, validation_alias="saIdentityExpiry")
    sa_gosi_registration_status:  Optional[str] = Field(None, validation_alias="saGosiRegistrationStatus")
    sa_gosi_registration_date:    Optional[date] = Field(None, validation_alias="saGosiRegistrationDate")
    sa_gosi_registration_token:   Optional[str] = Field(None, validation_alias="saGosiRegistrationToken")
    sa_contributory_wage:         Optional[Decimal] = Field(None, validation_alias="saContributoryWage")
    sa_contributory_wage_effective_from: Optional[date] = Field(None, validation_alias="saContributoryWageEffectiveFrom")
    sa_contributory_wage_gosi_ref: Optional[str] = Field(None, validation_alias="saContributoryWageGosiRef")
    sa_in_kind_housing_value:     Optional[Decimal] = Field(None, validation_alias="saInKindHousingValue")
    sa_contract_type:             Optional[str] = Field(None, validation_alias="saContractType")
    sa_occupation:                Optional[str] = Field(None, validation_alias="saOccupation")
    sa_special_category:          Optional[str] = Field(None, validation_alias="saSpecialCategory")
    sa_reduced_ramadan_hours:     Optional[bool] = Field(None, validation_alias="saReducedRamadanHours")
    sa_service_start_date:        Optional[date] = Field(None, validation_alias="saServiceStartDate")
    sa_eos_exclusions:            Optional[str] = Field(None, validation_alias="saEosExclusions")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class EmployeeStatutoryProfileResponse(BaseModel):
    id:              int
    employeeId:      int = Field(validation_alias="employee_id", serialization_alias="employeeId")
    countryCode:     str = Field(validation_alias="country_code", serialization_alias="countryCode")
    effectiveFrom:   date = Field(validation_alias="effective_from", serialization_alias="effectiveFrom")
    effectiveTo:     Optional[date] = Field(None, validation_alias="effective_to", serialization_alias="effectiveTo")
    createdAt:       Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")
    createdById:     Optional[int] = Field(None, validation_alias="created_by_id", serialization_alias="createdById")
    reason:          Optional[str] = None

    deTaxClass:                     Optional[str] = Field(None, validation_alias="de_tax_class", serialization_alias="deTaxClass")
    deFactor:                       Optional[Decimal] = Field(None, validation_alias="de_factor", serialization_alias="deFactor")
    deChurchTaxLiable:              Optional[bool] = Field(None, validation_alias="de_church_tax_liable", serialization_alias="deChurchTaxLiable")
    deChurchTaxLand:                Optional[str] = Field(None, validation_alias="de_church_tax_land", serialization_alias="deChurchTaxLand")
    deChurchTaxDenomination:        Optional[str] = Field(None, validation_alias="de_church_tax_denomination", serialization_alias="deChurchTaxDenomination")
    deChurchTaxMunicipalityPostalCode: Optional[str] = Field(None, validation_alias="de_church_tax_municipality_postal_code", serialization_alias="deChurchTaxMunicipalityPostalCode")
    deChildCount:                   Optional[int] = Field(None, validation_alias="de_child_count", serialization_alias="deChildCount")
    deChildless:                    Optional[bool] = Field(None, validation_alias="de_childless", serialization_alias="deChildless")
    deSaxony:                       Optional[bool] = Field(None, validation_alias="de_saxony", serialization_alias="deSaxony")
    deHealthInsuranceStatus:        Optional[str] = Field(None, validation_alias="de_health_insurance_status", serialization_alias="deHealthInsuranceStatus")
    deHealthFundCode:               Optional[str] = Field(None, validation_alias="de_health_fund_code", serialization_alias="deHealthFundCode")
    deU1TariffId:                   Optional[str] = Field(None, validation_alias="de_u1_tariff_id", serialization_alias="deU1TariffId")
    dePensionInsuranceExempt:       Optional[bool] = Field(None, validation_alias="de_pension_insurance_exempt", serialization_alias="dePensionInsuranceExempt")
    deUnemploymentInsuranceExempt:  Optional[bool] = Field(None, validation_alias="de_unemployment_insurance_exempt", serialization_alias="deUnemploymentInsuranceExempt")
    deEmploymentClassification:     Optional[str] = Field(None, validation_alias="de_employment_classification", serialization_alias="deEmploymentClassification")
    deElstamSource:                 Optional[str] = Field(None, validation_alias="de_elstam_source", serialization_alias="deElstamSource")
    deElstamFallbackReason:         Optional[str] = Field(None, validation_alias="de_elstam_fallback_reason", serialization_alias="deElstamFallbackReason")
    deVocationalTrainee:            Optional[bool] = Field(None, validation_alias="de_vocational_trainee", serialization_alias="deVocationalTrainee")

    # Phase 8N — ELStAM / employee-withholding-state completion.
    deZkfOverride:                  Optional[Decimal] = Field(None, validation_alias="de_zkf_override", serialization_alias="deZkfOverride")
    deJfreib:                       Optional[Decimal] = Field(None, validation_alias="de_jfreib", serialization_alias="deJfreib")
    deLzzfreib:                     Optional[Decimal] = Field(None, validation_alias="de_lzzfreib", serialization_alias="deLzzfreib")
    deJhinzu:                       Optional[Decimal] = Field(None, validation_alias="de_jhinzu", serialization_alias="deJhinzu")
    deLzzhinzu:                     Optional[Decimal] = Field(None, validation_alias="de_lzzhinzu", serialization_alias="deLzzhinzu")
    dePkpv:                         Optional[Decimal] = Field(None, validation_alias="de_pkpv", serialization_alias="dePkpv")
    dePkpvagz:                      Optional[Decimal] = Field(None, validation_alias="de_pkpvagz", serialization_alias="dePkpvagz")
    deMainEmployment:               Optional[bool] = Field(None, validation_alias="de_main_employment", serialization_alias="deMainEmployment")
    deElstamSchemaVersion:          Optional[str] = Field(None, validation_alias="de_elstam_schema_version", serialization_alias="deElstamSchemaVersion")
    deElstamImportReference:        Optional[str] = Field(None, validation_alias="de_elstam_import_reference", serialization_alias="deElstamImportReference")

    # Phase 8AB — see EmployeeStatutoryProfileCreate's field docstring.
    deGrundlohnHourly:              Optional[Decimal] = Field(None, validation_alias="de_grundlohn_hourly", serialization_alias="deGrundlohnHourly")

    # Hong Kong (ZP-HK-ENG-001 §3). The identity token is never returned.
    hkgEmploymentRelationship: Optional[str] = Field(None, validation_alias="hk_employment_relationship", serialization_alias="hkgEmploymentRelationship")
    hkgIdentityDocumentType: Optional[str] = Field(None, validation_alias="hk_identity_document_type", serialization_alias="hkgIdentityDocumentType")
    hkgResidencyStatus: Optional[str] = Field(None, validation_alias="hk_residency_status", serialization_alias="hkgResidencyStatus")
    hkgVisaType: Optional[str] = Field(None, validation_alias="hk_visa_type", serialization_alias="hkgVisaType")
    hkgEnteredForEmployment: Optional[bool] = Field(None, validation_alias="hk_entered_for_employment", serialization_alias="hkgEnteredForEmployment")
    hkgPermissionToStayUntil: Optional[date] = Field(None, validation_alias="hk_permission_to_stay_until", serialization_alias="hkgPermissionToStayUntil")
    hkgOverseasSchemeMember: Optional[bool] = Field(None, validation_alias="hk_overseas_scheme_member", serialization_alias="hkgOverseasSchemeMember")
    hkgMpfExemptionCode: Optional[str] = Field(None, validation_alias="hk_mpf_exemption_code", serialization_alias="hkgMpfExemptionCode")
    hkgMpfExemptionReason: Optional[str] = Field(None, validation_alias="hk_mpf_exemption_reason", serialization_alias="hkgMpfExemptionReason")
    hkgMpfExemptionEvidenceRef: Optional[str] = Field(None, validation_alias="hk_mpf_exemption_evidence_ref", serialization_alias="hkgMpfExemptionEvidenceRef")
    hkgMpfSchemeRef: Optional[str] = Field(None, validation_alias="hk_mpf_scheme_ref", serialization_alias="hkgMpfSchemeRef")
    hkgEmploymentContinuityStart: Optional[date] = Field(None, validation_alias="hk_employment_continuity_start", serialization_alias="hkgEmploymentContinuityStart")
    hkgPayBasis: Optional[str] = Field(None, validation_alias="hk_pay_basis", serialization_alias="hkgPayBasis")
    hkgContractualWeeklyHours: Optional[Decimal] = Field(None, validation_alias="hk_contractual_weekly_hours", serialization_alias="hkgContractualWeeklyHours")
    hkgLikelyChargeable: Optional[bool] = Field(None, validation_alias="hk_likely_chargeable", serialization_alias="hkgLikelyChargeable")
    hkgArrivalDate: Optional[date] = Field(None, validation_alias="hk_arrival_date", serialization_alias="hkgArrivalDate")
    hkgExpectedDepartureDate: Optional[date] = Field(None, validation_alias="hk_expected_departure_date", serialization_alias="hkgExpectedDepartureDate")
    hkgFrequentTravelExempt: Optional[bool] = Field(None, validation_alias="hk_frequent_travel_exempt", serialization_alias="hkgFrequentTravelExempt")
    hkgTerminationDate: Optional[date] = Field(None, validation_alias="hk_termination_date", serialization_alias="hkgTerminationDate")
    hkgTerminationReason: Optional[str] = Field(None, validation_alias="hk_termination_reason", serialization_alias="hkgTerminationReason")
    hkgPreTransitionMonthlyWage: Optional[Decimal] = Field(None, validation_alias="hk_pre_transition_monthly_wage", serialization_alias="hkgPreTransitionMonthlyWage")
    hkgPreTransitionWageBasis: Optional[str] = Field(None, validation_alias="hk_pre_transition_wage_basis", serialization_alias="hkgPreTransitionWageBasis")
    hkgPreTransitionEvidenceRef: Optional[str] = Field(None, validation_alias="hk_pre_transition_evidence_ref", serialization_alias="hkgPreTransitionEvidenceRef")
    # ── Sweden (ZP-SE-ENG-001 §2/§20/§21) — see Create schema above ────────
    seTaxStatus:              Optional[str] = Field(None, validation_alias="se_tax_status", serialization_alias="seTaxStatus")
    seIncomeRole:             Optional[str] = Field(None, validation_alias="se_income_role", serialization_alias="seIncomeRole")
    seTaxTable:               Optional[str] = Field(None, validation_alias="se_tax_table", serialization_alias="seTaxTable")
    seTaxColumn:              Optional[str] = Field(None, validation_alias="se_tax_column", serialization_alias="seTaxColumn")
    seSkatteverketDecisionId: Optional[str] = Field(None, validation_alias="se_skatteverket_decision_id", serialization_alias="seSkatteverketDecisionId")
    seDecisionEffectiveFrom:   Optional[date] = Field(None, validation_alias="se_decision_effective_from", serialization_alias="seDecisionEffectiveFrom")
    seDecisionEffectiveTo:     Optional[date] = Field(None, validation_alias="se_decision_effective_to", serialization_alias="seDecisionEffectiveTo")
    seDecisionOverride:        Optional[bool] = Field(None, validation_alias="se_decision_override", serialization_alias="seDecisionOverride")
    seDecisionMonthlyWithholding: Optional[Decimal] = Field(None, validation_alias="se_decision_monthly_withholding", serialization_alias="seDecisionMonthlyWithholding")
    seDecisionRatePct:            Optional[Decimal] = Field(None, validation_alias="se_decision_rate_pct", serialization_alias="seDecisionRatePct")
    seSinkStatus:              Optional[str] = Field(None, validation_alias="se_sink_status", serialization_alias="seSinkStatus")
    seSinkDecision:            Optional[str] = Field(None, validation_alias="se_sink_decision", serialization_alias="seSinkDecision")
    seResidenceMunicipality:   Optional[str] = Field(None, validation_alias="se_residence_municipality", serialization_alias="seResidenceMunicipality")
    seTaxTableArea:            Optional[str] = Field(None, validation_alias="se_tax_table_area", serialization_alias="seTaxTableArea")
    seSocialInsuranceStatus:   Optional[str] = Field(None, validation_alias="se_social_insurance_status", serialization_alias="seSocialInsuranceStatus")
    seForeignCoverageStatus:   Optional[str] = Field(None, validation_alias="se_foreign_coverage_status", serialization_alias="seForeignCoverageStatus")
    seA1Status:                Optional[str] = Field(None, validation_alias="se_a1_status", serialization_alias="seA1Status")
    seAgreementCountry:        Optional[str] = Field(None, validation_alias="se_agreement_country", serialization_alias="seAgreementCountry")
    seCoverageStart:           Optional[date] = Field(None, validation_alias="se_coverage_start", serialization_alias="seCoverageStart")
    seCoverageEnd:             Optional[date] = Field(None, validation_alias="se_coverage_end", serialization_alias="seCoverageEnd")
    seEvidenceDocument:        Optional[str] = Field(None, validation_alias="se_evidence_document", serialization_alias="seEvidenceDocument")
    seEvidenceValidation:      Optional[str] = Field(None, validation_alias="se_evidence_validation", serialization_alias="seEvidenceValidation")
    seCbaStatus:               Optional[str] = Field(None, validation_alias="se_cba_status", serialization_alias="seCbaStatus")
    seCbaId:                   Optional[int] = Field(None, validation_alias="se_cba_id", serialization_alias="seCbaId")
    seCbaVersion:              Optional[str] = Field(None, validation_alias="se_cba_version", serialization_alias="seCbaVersion")
    seOccupation:              Optional[str] = Field(None, validation_alias="se_occupation", serialization_alias="seOccupation")
    seGrade:                   Optional[str] = Field(None, validation_alias="se_grade", serialization_alias="seGrade")
    sePensionPlan:             Optional[str] = Field(None, validation_alias="se_pension_plan", serialization_alias="sePensionPlan")
    sePensionProvider:         Optional[str] = Field(None, validation_alias="se_pension_provider", serialization_alias="sePensionProvider")
    seEmployeePensionShare:    Optional[Decimal] = Field(None, validation_alias="se_employee_pension_share", serialization_alias="seEmployeePensionShare")
    seEmployerPensionShare:    Optional[Decimal] = Field(None, validation_alias="se_employer_pension_share", serialization_alias="seEmployerPensionShare")
    sePayrollPeriod:           Optional[str] = Field(None, validation_alias="se_payroll_period", serialization_alias="sePayrollPeriod")
    seAgiReportingPeriod:      Optional[str] = Field(None, validation_alias="se_agi_reporting_period", serialization_alias="seAgiReportingPeriod")
    seMonthlyGross:            Optional[Decimal] = Field(None, validation_alias="se_monthly_gross", serialization_alias="seMonthlyGross")
    seTaxableBenefits:         Optional[Decimal] = Field(None, validation_alias="se_taxable_benefits", serialization_alias="seTaxableBenefits")
    seAnnualIncome:            Optional[Decimal] = Field(None, validation_alias="se_annual_income", serialization_alias="seAnnualIncome")

    # ── Italy (ZP-IT-ENG-001 §18) — see Create schema above ─────────────────
    itCnelCode:                  Optional[str] = Field(None, validation_alias="it_cnel_code", serialization_alias="itCnelCode")
    itCnelLevel:                 Optional[str] = Field(None, validation_alias="it_cnel_level", serialization_alias="itCnelLevel")
    itWorkerClass:               Optional[str] = Field(None, validation_alias="it_worker_class", serialization_alias="itWorkerClass")
    itContractType:              Optional[str] = Field(None, validation_alias="it_contract_type", serialization_alias="itContractType")
    itCigsApplies:               Optional[bool] = Field(None, validation_alias="it_cigs_applies", serialization_alias="itCigsApplies")
    itContributoryCapCohort:     Optional[str] = Field(None, validation_alias="it_contributory_cap_cohort", serialization_alias="itContributoryCapCohort")
    itEmployerContribOpted:      Optional[bool] = Field(None, validation_alias="it_employer_contrib_opted", serialization_alias="itEmployerContribOpted")
    itTfrDestination:            Optional[str] = Field(None, validation_alias="it_tfr_destination", serialization_alias="itTfrDestination")
    itPensionFund:               Optional[str] = Field(None, validation_alias="it_pension_fund", serialization_alias="itPensionFund")
    itTfrDestinationFrom:        Optional[date] = Field(None, validation_alias="it_tfr_destination_from", serialization_alias="itTfrDestinationFrom")
    itTaxDomicileComune:         Optional[str] = Field(None, validation_alias="it_tax_domicile_comune", serialization_alias="itTaxDomicileComune")
    itTaxDomicileRegion:         Optional[str] = Field(None, validation_alias="it_tax_domicile_region", serialization_alias="itTaxDomicileRegion")
    itTaxDomicileFrom:           Optional[date] = Field(None, validation_alias="it_tax_domicile_from", serialization_alias="itTaxDomicileFrom")
    itFringeChildDeclared:       Optional[bool] = Field(None, validation_alias="it_fringe_child_declared", serialization_alias="itFringeChildDeclared")
    itContractualWeeklyHours:    Optional[Decimal] = Field(None, validation_alias="it_contractual_weekly_hours", serialization_alias="itContractualWeeklyHours")
    itTerminationReason:         Optional[str] = Field(None, validation_alias="it_termination_reason", serialization_alias="itTerminationReason")

    # ── Saudi Arabia (ZP-SA-ENG-001 §3/§4) — see Create schema above. The
    # identity token is privileged and is never returned by this response.
    saWorkerClass:              Optional[str] = Field(None, validation_alias="sa_worker_class", serialization_alias="saWorkerClass")
    saCohort:                   Optional[str] = Field(None, validation_alias="sa_cohort", serialization_alias="saCohort")
    saCohortEvidenceRef:        Optional[str] = Field(None, validation_alias="sa_cohort_evidence_ref", serialization_alias="saCohortEvidenceRef")
    saCohortSourceDocumentId:   Optional[int] = Field(None, validation_alias="sa_cohort_source_document_id", serialization_alias="saCohortSourceDocumentId")
    saCohortVerifiedById:       Optional[int] = Field(None, validation_alias="sa_cohort_verified_by_id", serialization_alias="saCohortVerifiedById")
    saCohortVerifiedAt:         Optional[datetime] = Field(None, validation_alias="sa_cohort_verified_at", serialization_alias="saCohortVerifiedAt")
    saIdentityDocumentType:     Optional[str] = Field(None, validation_alias="sa_identity_document_type", serialization_alias="saIdentityDocumentType")
    saIdentityExpiry:           Optional[date] = Field(None, validation_alias="sa_identity_expiry", serialization_alias="saIdentityExpiry")
    saGosiRegistrationStatus:   Optional[str] = Field(None, validation_alias="sa_gosi_registration_status", serialization_alias="saGosiRegistrationStatus")
    saGosiRegistrationDate:     Optional[date] = Field(None, validation_alias="sa_gosi_registration_date", serialization_alias="saGosiRegistrationDate")
    saGosiRegistrationToken:    Optional[str] = Field(None, validation_alias="sa_gosi_registration_token", serialization_alias="saGosiRegistrationToken")
    saContributoryWage:         Optional[Decimal] = Field(None, validation_alias="sa_contributory_wage", serialization_alias="saContributoryWage")
    saContributoryWageEffectiveFrom: Optional[date] = Field(None, validation_alias="sa_contributory_wage_effective_from", serialization_alias="saContributoryWageEffectiveFrom")
    saContributoryWageGosiRef:  Optional[str] = Field(None, validation_alias="sa_contributory_wage_gosi_ref", serialization_alias="saContributoryWageGosiRef")
    saInKindHousingValue:       Optional[Decimal] = Field(None, validation_alias="sa_in_kind_housing_value", serialization_alias="saInKindHousingValue")
    saContractType:             Optional[str] = Field(None, validation_alias="sa_contract_type", serialization_alias="saContractType")
    saOccupation:               Optional[str] = Field(None, validation_alias="sa_occupation", serialization_alias="saOccupation")
    saSpecialCategory:          Optional[str] = Field(None, validation_alias="sa_special_category", serialization_alias="saSpecialCategory")
    saReducedRamadanHours:      Optional[bool] = Field(None, validation_alias="sa_reduced_ramadan_hours", serialization_alias="saReducedRamadanHours")
    saServiceStartDate:         Optional[date] = Field(None, validation_alias="sa_service_start_date", serialization_alias="saServiceStartDate")
    saEosExclusions:            Optional[str] = Field(None, validation_alias="sa_eos_exclusions", serialization_alias="saEosExclusions")

    # Phase 8AK — computed, never stored (see Gate 4's own "do not store
    # derived values as authoritative inputs" instruction). Reuses
    # germany_pap.core.check_main_secondary_employment_consistency
    # verbatim — the SAME advisory check the PAP execution trace already
    # runs (germany.py's _calculate_regular_path/_calculate_midijob_path)
    # — surfaced HERE too so Tax Ops can see it at profile save/read time,
    # not only if/when a full PAP-blocked calculation trace is inspected.
    # None when the combination is unremarkable; never a hard error (spec
    # gives no hard-reject rule for this pairing).
    mainSecondaryConsistencyWarning: Optional[str] = Field(
        None, validation_alias="main_secondary_consistency_warning",
        serialization_alias="mainSecondaryConsistencyWarning",
    )

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Germany overtime/shift-premium work-record (Phase 8AC) — fact capture
# only; no premium/tax/SI fields. See models.py's GermanyOvertimeWorkRecord
# docstring for the full ARCHITECTURE_D rationale (Phase 8AA).

class GermanyOvertimeWorkRecordCreate(BaseModel):
    source_attendance_id: Optional[int] = Field(None, validation_alias="sourceAttendanceId")
    work_date:             date = Field(validation_alias="workDate")
    start_datetime:        datetime = Field(validation_alias="startDatetime")
    end_datetime:          datetime = Field(validation_alias="endDatetime")
    hours:                 Decimal = Field(validation_alias="hours")
    entry_source:          str = Field(validation_alias="entrySource")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class GermanyOvertimeWorkRecordResponse(BaseModel):
    id:                    int
    employeeId:            int = Field(validation_alias="employee_id", serialization_alias="employeeId")
    sourceAttendanceId:    Optional[int] = Field(None, validation_alias="source_attendance_id", serialization_alias="sourceAttendanceId")
    workDate:              date = Field(validation_alias="work_date", serialization_alias="workDate")
    startDatetime:         datetime = Field(validation_alias="start_datetime", serialization_alias="startDatetime")
    endDatetime:           datetime = Field(validation_alias="end_datetime", serialization_alias="endDatetime")
    hours:                 Decimal
    entrySource:           str = Field(validation_alias="entry_source", serialization_alias="entrySource")
    hrApprovalStatus:      str = Field(validation_alias="hr_approval_status", serialization_alias="hrApprovalStatus")
    overlapStatus:         Optional[str] = Field(None, validation_alias="overlap_status", serialization_alias="overlapStatus")
    createdById:           Optional[int] = Field(None, validation_alias="created_by_id", serialization_alias="createdById")
    createdAt:             Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class GermanyOvertimeWorkRecordApprovalUpdate(BaseModel):
    hr_approval_status: str = Field(validation_alias="hrApprovalStatus")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


# ── Germany overtime time-window CLASSIFICATION (Phase 8AE) — read-only.
# Statutory/calendar classification result only; no monetary field.

class GermanyOvertimeTimeSegmentResponse(BaseModel):
    id:                    int
    workRecordId:          int = Field(validation_alias="work_record_id", serialization_alias="workRecordId")
    segmentStart:          datetime = Field(validation_alias="segment_start", serialization_alias="segmentStart")
    segmentEnd:            datetime = Field(validation_alias="segment_end", serialization_alias="segmentEnd")
    hours:                 Decimal
    premiumCategory:       str = Field(validation_alias="premium_category", serialization_alias="premiumCategory")
    classificationStatus:  str = Field(validation_alias="classification_status", serialization_alias="classificationStatus")
    categoryRuleId:        Optional[int] = Field(None, validation_alias="category_rule_id", serialization_alias="categoryRuleId")
    workDateLocal:         date = Field(validation_alias="work_date_local", serialization_alias="workDateLocal")
    createdAt:             Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Germany overtime WAGE-TAX calculation result (Phase 8AF) — read-only.
# WAGE TAX ONLY; no social-insurance field. See models.py's
# GermanyOvertimeWageTaxResult docstring.

class GermanyOvertimeWageTaxResultResponse(BaseModel):
    id:                          int
    workRecordId:                int = Field(validation_alias="work_record_id", serialization_alias="workRecordId")
    segmentStart:                datetime = Field(validation_alias="segment_start", serialization_alias="segmentStart")
    segmentEnd:                  datetime = Field(validation_alias="segment_end", serialization_alias="segmentEnd")
    workDateLocal:               date = Field(validation_alias="work_date_local", serialization_alias="workDateLocal")
    qualifyingHours:              Decimal = Field(validation_alias="qualifying_hours", serialization_alias="qualifyingHours")
    actualGrundlohnHourly:        Optional[Decimal] = Field(None, validation_alias="actual_grundlohn_hourly", serialization_alias="actualGrundlohnHourly")
    taxGrundlohnHourly:           Optional[Decimal] = Field(None, validation_alias="tax_grundlohn_hourly", serialization_alias="taxGrundlohnHourly")
    grundlohnCapRuleId:           Optional[int] = Field(None, validation_alias="grundlohn_cap_rule_id", serialization_alias="grundlohnCapRuleId")
    primaryCategoryCode:          Optional[str] = Field(None, validation_alias="primary_category_code", serialization_alias="primaryCategoryCode")
    primaryCategoryRuleId:        Optional[int] = Field(None, validation_alias="primary_category_rule_id", serialization_alias="primaryCategoryRuleId")
    concurrentCategoryCode:       Optional[str] = Field(None, validation_alias="concurrent_category_code", serialization_alias="concurrentCategoryCode")
    concurrentCategoryRuleId:     Optional[int] = Field(None, validation_alias="concurrent_category_rule_id", serialization_alias="concurrentCategoryRuleId")
    combinedTaxFreePct:           Optional[Decimal] = Field(None, validation_alias="combined_tax_free_pct", serialization_alias="combinedTaxFreePct")
    grossQualifyingPremiumAmount: Optional[Decimal] = Field(None, validation_alias="gross_qualifying_premium_amount", serialization_alias="grossQualifyingPremiumAmount")
    taxFreePremiumAmount:         Optional[Decimal] = Field(None, validation_alias="tax_free_premium_amount", serialization_alias="taxFreePremiumAmount")
    taxablePremiumAmount:         Optional[Decimal] = Field(None, validation_alias="taxable_premium_amount", serialization_alias="taxablePremiumAmount")
    calculationStatus:            str = Field(validation_alias="calculation_status", serialization_alias="calculationStatus")
    calculationNote:              Optional[str] = Field(None, validation_alias="calculation_note", serialization_alias="calculationNote")
    createdAt:                    Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Germany overtime SOCIAL-INSURANCE calculation result (Phase 8AG) —
# read-only. SOCIAL INSURANCE ONLY; no wage-tax field. See models.py's
# GermanyOvertimeSocialInsuranceResult docstring.

class GermanyOvertimeSocialInsuranceResultResponse(BaseModel):
    id:                          int
    workRecordId:                int = Field(validation_alias="work_record_id", serialization_alias="workRecordId")
    segmentStart:                datetime = Field(validation_alias="segment_start", serialization_alias="segmentStart")
    segmentEnd:                  datetime = Field(validation_alias="segment_end", serialization_alias="segmentEnd")
    workDateLocal:               date = Field(validation_alias="work_date_local", serialization_alias="workDateLocal")
    qualifyingHours:              Decimal = Field(validation_alias="qualifying_hours", serialization_alias="qualifyingHours")
    actualGrundlohnHourly:        Optional[Decimal] = Field(None, validation_alias="actual_grundlohn_hourly", serialization_alias="actualGrundlohnHourly")
    siGrundlohnHourly:            Optional[Decimal] = Field(None, validation_alias="si_grundlohn_hourly", serialization_alias="siGrundlohnHourly")
    siCapRuleId:                  Optional[int] = Field(None, validation_alias="si_cap_rule_id", serialization_alias="siCapRuleId")
    primaryCategoryCode:          Optional[str] = Field(None, validation_alias="primary_category_code", serialization_alias="primaryCategoryCode")
    primaryCategoryRuleId:        Optional[int] = Field(None, validation_alias="primary_category_rule_id", serialization_alias="primaryCategoryRuleId")
    concurrentCategoryCode:       Optional[str] = Field(None, validation_alias="concurrent_category_code", serialization_alias="concurrentCategoryCode")
    concurrentCategoryRuleId:     Optional[int] = Field(None, validation_alias="concurrent_category_rule_id", serialization_alias="concurrentCategoryRuleId")
    combinedPremiumPct:           Optional[Decimal] = Field(None, validation_alias="combined_premium_pct", serialization_alias="combinedPremiumPct")
    applicableSiBranches:         Optional[str] = Field(None, validation_alias="applicable_si_branches", serialization_alias="applicableSiBranches")
    grossQualifyingPremiumAmount: Optional[Decimal] = Field(None, validation_alias="gross_qualifying_premium_amount", serialization_alias="grossQualifyingPremiumAmount")
    siFreePremiumAmount:          Optional[Decimal] = Field(None, validation_alias="si_free_premium_amount", serialization_alias="siFreePremiumAmount")
    siContributoryPremiumAmount:  Optional[Decimal] = Field(None, validation_alias="si_contributory_premium_amount", serialization_alias="siContributoryPremiumAmount")
    calculationStatus:            str = Field(validation_alias="calculation_status", serialization_alias="calculationStatus")
    calculationNote:              Optional[str] = Field(None, validation_alias="calculation_note", serialization_alias="calculationNote")
    createdAt:                    Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Germany overtime PREMIUM COMPONENT (Phase 8AH) ──────────────────────

class GermanyOvertimePremiumComponentResponse(BaseModel):
    id:                        int
    workRecordId:              int = Field(validation_alias="work_record_id", serialization_alias="workRecordId")
    segmentStart:              datetime = Field(validation_alias="segment_start", serialization_alias="segmentStart")
    segmentEnd:                datetime = Field(validation_alias="segment_end", serialization_alias="segmentEnd")
    workDateLocal:             date = Field(validation_alias="work_date_local", serialization_alias="workDateLocal")
    qualifyingHours:           Decimal = Field(validation_alias="qualifying_hours", serialization_alias="qualifyingHours")
    wageTaxResultId:           Optional[int] = Field(None, validation_alias="wage_tax_result_id", serialization_alias="wageTaxResultId")
    socialInsuranceResultId:   Optional[int] = Field(None, validation_alias="social_insurance_result_id", serialization_alias="socialInsuranceResultId")
    combinationStatus:         str = Field(validation_alias="combination_status", serialization_alias="combinationStatus")
    calculationNote:           Optional[str] = Field(None, validation_alias="calculation_note", serialization_alias="calculationNote")
    grossPremiumAmount:        Optional[Decimal] = Field(None, validation_alias="gross_premium_amount", serialization_alias="grossPremiumAmount")
    wageTaxFreeAmount:         Optional[Decimal] = Field(None, validation_alias="wage_tax_free_amount", serialization_alias="wageTaxFreeAmount")
    wageTaxableAmount:         Optional[Decimal] = Field(None, validation_alias="wage_taxable_amount", serialization_alias="wageTaxableAmount")
    siExemptAmount:            Optional[Decimal] = Field(None, validation_alias="si_exempt_amount", serialization_alias="siExemptAmount")
    siContributoryAmount:      Optional[Decimal] = Field(None, validation_alias="si_contributory_amount", serialization_alias="siContributoryAmount")
    attachmentStatus:          str = Field("NEVER_ATTACHED", validation_alias="attachment_status", serialization_alias="attachmentStatus")
    payslipAllowanceItemId:    Optional[int] = Field(None, validation_alias="payslip_allowance_item_id", serialization_alias="payslipAllowanceItemId")
    attachedAt:                Optional[datetime] = Field(None, validation_alias="attached_at", serialization_alias="attachedAt")
    attachedById:              Optional[int] = Field(None, validation_alias="attached_by_id", serialization_alias="attachedById")
    detachedAt:                Optional[datetime] = Field(None, validation_alias="detached_at", serialization_alias="detachedAt")
    detachedById:              Optional[int] = Field(None, validation_alias="detached_by_id", serialization_alias="detachedById")
    financialIntegrationStatus: Optional[str] = Field(None, validation_alias="financial_integration_status", serialization_alias="financialIntegrationStatus")
    appliedGrossDelta:         Optional[Decimal] = Field(None, validation_alias="applied_gross_delta", serialization_alias="appliedGrossDelta")
    appliedPfDelta:            Optional[Decimal] = Field(None, validation_alias="applied_pf_delta", serialization_alias="appliedPfDelta")
    appliedEsiDelta:           Optional[Decimal] = Field(None, validation_alias="applied_esi_delta", serialization_alias="appliedEsiDelta")
    # Phase 8BW: previously wage tax had no dedicated applied-delta column
    # at all (always 0, undisclosed beyond financialIntegrationStatus's own
    # "PARTIAL_WAGE_TAX_PENDING_PAP" string) — now genuinely computed via
    # the internal §32a/§39b calculator; see _compute_overtime_financial_delta.
    appliedWageTaxDelta:       Optional[Decimal] = Field(None, validation_alias="applied_wage_tax_delta", serialization_alias="appliedWageTaxDelta")
    appliedSoliDelta:          Optional[Decimal] = Field(None, validation_alias="applied_soli_delta", serialization_alias="appliedSoliDelta")
    appliedChurchTaxDelta:     Optional[Decimal] = Field(None, validation_alias="applied_church_tax_delta", serialization_alias="appliedChurchTaxDelta")
    createdAt:                 Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class GermanyOvertimePremiumComponentAttachRequest(BaseModel):
    payslip_item_id: int = Field(validation_alias="payslipItemId")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class GermanyOvertimePremiumComponentEligibleResponse(GermanyOvertimePremiumComponentResponse):
    """Same shape as GermanyOvertimePremiumComponentResponse, plus the
    employee identity the batch-attach browse endpoint attaches per row
    (service.list_germany_overtime_premium_components_for_batch_attach) —
    never persisted, computed fresh from the same join every call."""
    employeeId:    Optional[int] = Field(None, validation_alias="employee_id", serialization_alias="employeeId")
    employeeName:  Optional[str] = Field(None, validation_alias="employee_name", serialization_alias="employeeName")


# ── Germany overtime premium component BATCH attach (Phase 8AO) ──────────
# Still an explicit, operator-initiated action (never automatic payroll-run
# inclusion) — the caller supplies the exact pairs it wants attached; every
# pair is independently re-validated server-side regardless of what the
# frontend believes about eligibility. See
# service.batch_attach_germany_overtime_premium_components_to_payslips.

class GermanyOvertimePremiumComponentBatchAttachItem(BaseModel):
    component_id:     int = Field(validation_alias="componentId")
    payslip_item_id:  int = Field(validation_alias="payslipItemId")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class GermanyOvertimePremiumComponentBatchAttachRequest(BaseModel):
    items: List[GermanyOvertimePremiumComponentBatchAttachItem] = Field(validation_alias="items")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class GermanyOvertimePremiumComponentBatchAttachResultItem(BaseModel):
    componentId:    int = Field(validation_alias="component_id", serialization_alias="componentId")
    payslipItemId:  int = Field(validation_alias="payslip_item_id", serialization_alias="payslipItemId")
    reason:         Optional[str] = Field(None, validation_alias="reason", serialization_alias="reason")
    component:      Optional[GermanyOvertimePremiumComponentResponse] = Field(
        None, validation_alias="component", serialization_alias="component",
    )

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class GermanyOvertimePremiumComponentBatchAttachResponse(BaseModel):
    attached:         List[GermanyOvertimePremiumComponentBatchAttachResultItem]
    alreadyAttached:   List[GermanyOvertimePremiumComponentBatchAttachResultItem] = Field(validation_alias="already_attached", serialization_alias="alreadyAttached")
    rejected:          List[GermanyOvertimePremiumComponentBatchAttachResultItem]
    invalid:           List[GermanyOvertimePremiumComponentBatchAttachResultItem]
    failed:            List[GermanyOvertimePremiumComponentBatchAttachResultItem]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Germany ELStAM change-list / structured-import boundary (Phase 8N) ──

class GermanyElstamChangeListBatchCreate(BaseModel):
    batch_reference:   str = Field(validation_alias="batchReference")
    source:            Optional[str] = Field("MANUAL_UPLOAD", validation_alias="source")
    received_at:       datetime = Field(validation_alias="receivedAt")
    effective_date:    date = Field(validation_alias="effectiveDate")
    scope_description: Optional[str] = Field(None, validation_alias="scopeDescription")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class GermanyElstamChangeListBatchStatusUpdate(BaseModel):
    status:            str
    validation_result: Optional[dict] = Field(None, validation_alias="validationResult")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


# ── Phase 8BF — ELSTER transmission boundary schemas ──────────────────────

class GermanyElsterCertificateConfigSet(BaseModel):
    certificate_reference:  str = Field(validation_alias="certificateReference")
    reference_description:  Optional[str] = Field(None, validation_alias="referenceDescription")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class GermanyElsterTransmissionCreate(BaseModel):
    transmission_type: str = Field(validation_alias="transmissionType")
    period_start:       date = Field(validation_alias="periodStart")
    period_end:         date = Field(validation_alias="periodEnd")
    payload_summary:    Optional[dict] = Field(None, validation_alias="payloadSummary")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class GermanyElsterCertificateConfigResponse(BaseModel):
    id:                     int
    organizationId:         int = Field(validation_alias="organization_id")
    isConfigured:           bool = Field(validation_alias="is_configured")
    certificateReference:   Optional[str] = Field(None, validation_alias="certificate_reference")
    referenceDescription:   Optional[str] = Field(None, validation_alias="reference_description")
    configuredAt:           Optional[datetime] = Field(None, validation_alias="configured_at")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class GermanyElsterTransmissionResponse(BaseModel):
    id:                int
    organizationId:    int = Field(validation_alias="organization_id")
    transmissionType:  str = Field(validation_alias="transmission_type")
    periodStart:       date = Field(validation_alias="period_start")
    periodEnd:         date = Field(validation_alias="period_end")
    payloadSummary:    Optional[dict] = Field(None, validation_alias="payload_summary")
    status:            str
    validationErrors:  Optional[list] = Field(None, validation_alias="validation_errors")
    blockedReason:     Optional[str] = Field(None, validation_alias="blocked_reason")
    createdAt:         Optional[datetime] = Field(None, validation_alias="created_at")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class GermanyElstamChangeListBatchResponse(BaseModel):
    id:                int
    organizationId:    int = Field(validation_alias="organization_id", serialization_alias="organizationId")
    batchReference:    str = Field(validation_alias="batch_reference", serialization_alias="batchReference")
    source:            str
    receivedAt:        datetime = Field(validation_alias="received_at", serialization_alias="receivedAt")
    effectiveDate:     date = Field(validation_alias="effective_date", serialization_alias="effectiveDate")
    scopeDescription:  Optional[str] = Field(None, validation_alias="scope_description", serialization_alias="scopeDescription")
    processingStatus:  str = Field(validation_alias="processing_status", serialization_alias="processingStatus")
    validationResult:  Optional[dict] = Field(None, validation_alias="validation_result", serialization_alias="validationResult")
    createdAt:         Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class GermanyElstamImportRequest(BaseModel):
    """Phase 8N structured-import boundary. `payload` is caller-supplied
    structured data shaped exactly like a normal statutory-profile write —
    never a live ELSTER/BZSt fetch (see engine/germany_pap/elstam.py for
    why no such connector exists)."""
    schema_version:       str = Field(validation_alias="schemaVersion")
    import_reference:     Optional[str] = Field(None, validation_alias="importReference")
    change_list_batch_id: Optional[int] = Field(None, validation_alias="changeListBatchId")
    payload:              EmployeeStatutoryProfileCreate

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class GermanyElstamImportAttemptResponse(BaseModel):
    id:                          int
    employeeId:                  int = Field(validation_alias="employee_id", serialization_alias="employeeId")
    schemaVersion:               str = Field(validation_alias="schema_version", serialization_alias="schemaVersion")
    importReference:             Optional[str] = Field(None, validation_alias="import_reference", serialization_alias="importReference")
    changeListBatchId:           Optional[int] = Field(None, validation_alias="change_list_batch_id", serialization_alias="changeListBatchId")
    validationStatus:            str = Field(validation_alias="validation_status", serialization_alias="validationStatus")
    validationErrors:            Optional[dict] = Field(None, validation_alias="validation_errors", serialization_alias="validationErrors")
    appliedStatutoryProfileId:   Optional[int] = Field(None, validation_alias="applied_statutory_profile_id", serialization_alias="appliedStatutoryProfileId")
    importedAt:                  Optional[datetime] = Field(None, validation_alias="imported_at", serialization_alias="importedAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class GermanyCalculationPreviewRequest(BaseModel):
    """Phase 7 QA/diagnostic endpoint request — see
    router.germany_calculation_preview / service.preview_germany_calculation.
    Intentionally carries no PAP version, statutory rate, or configuration
    override field — every value the calculation uses is resolved
    server-side from the authoritative registries, never accepted from
    the caller (this phase's explicit security requirement)."""
    employee_id:   int = Field(validation_alias="employeeId")
    payroll_date:  Optional[date] = Field(None, validation_alias="payrollDate")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class BulkEmployeeItem(BaseModel):
    id:                Optional[int] = None  # present only for bulk-update rows; ignored by bulk-create
    name:              Optional[str] = None
    email:             Optional[str] = None
    phone:             CoercedStr = None
    department:        Optional[str] = None
    designation:       Optional[str] = None
    employmentType:    Optional[str] = None
    status:            Optional[str] = None
    dateOfJoining:     CoercedStr = None
    ctc:               Optional[Decimal] = None
    basic:             CoercedDecimal = None
    hra:               CoercedDecimal = None
    bankName:          Optional[str] = None
    bankAccountNumber: CoercedStr = None
    panNumber:         CoercedStr = None
    uan:               CoercedStr = None
    ifscCode:          CoercedStr = None
    countryCode:       Optional[str] = None
    complianceFields:  Optional[dict] = None


class BulkEmployeeRequest(BaseModel):
    employees: List[BulkEmployeeItem]


class BulkDeleteRequest(BaseModel):
    employee_ids: List[int]


class BulkUpsertResponse(BaseModel):
    # The router builds a dict with all four of these keys (see
    # bulk_create_employees in router.py), but this schema previously
    # declared only `message` — FastAPI's response_model strips any key not
    # declared on the model, so `created`/`employees`/`failed` were silently
    # dropped from the actual HTTP response. The frontend's "add the new
    # rows to the list instantly" callback never fired as a result — new
    # employees only appeared after a later refetch (e.g. a page reload).
    message:   str
    created:   int = 0
    employees: List[EmployeeResponse] = []
    failed:    List[dict] = []
    created: int
    employees: List[EmployeeResponse]
    failed: List[dict] = []

    model_config = ConfigDict(populate_by_name=True)


class BulkUpdateResponse(BaseModel):
    message: str
    updated: int
    employees: List[EmployeeResponse]
    failed: List[dict] = []

    model_config = ConfigDict(populate_by_name=True)


# ── Payroll Runs ───────────────────────────────────────────────────────

class PayrollRunCreate(BaseModel):
    period_label: Optional[str] = Field(None, alias="periodLabel", description='Display label, e.g. "Jul 1-15, 2026". Auto-generated from dates if omitted.')
    period_start: date = Field(..., alias="periodStart")
    period_end:   date = Field(..., alias="periodEnd")
    pay_date:     date = Field(..., alias="payDate")
    notes:        Optional[str] = None
    schedule:     Optional[str] = None
    employeeIds:  Optional[List[int]] = None
    totals:       Optional[dict] = None
    calculation_mode: Optional[str] = Field(None, alias="calculationMode",
        description="simple|standard|enterprise — stored on the run for auditing. If omitted, resolved from active policy.")
    # If true (default), payslip items are generated for every Active
    # employee in the org as soon as the run is created.
    auto_generate_payslips: bool = True
    # Proceed despite incomplete attendance — recorded on the run and in the
    # activity log. Ignored when attendance is complete.
    attendance_override_reason: Optional[str] = Field(None, alias="attendanceOverrideReason", max_length=1000)

    model_config = ConfigDict(populate_by_name=True)

    @model_validator(mode="after")
    def _auto_label(self) -> "PayrollRunCreate":
        if not self.period_label and self.period_start and self.period_end:
            from calendar import month_name
            s, e = self.period_start, self.period_end
            if s.month == e.month:
                self.period_label = f"{month_name[s.month][:3]} {s.day}-{e.day}, {s.year}"
            else:
                self.period_label = f"{month_name[s.month][:3]} {s.day} - {month_name[e.month][:3]} {e.day}, {s.year}"
        return self


class PayrollRunUpdate(BaseModel):
    period_label: Optional[str] = None
    period_start: Optional[date] = None
    period_end:   Optional[date] = None
    pay_date:     Optional[date] = None
    notes:        Optional[str] = None


class PayrollRunPreviewRequest(BaseModel):
    employee_ids: List[int] = Field(..., alias="employeeIds", description="Employee IDs to include in preview")
    country: str = Field(default="IN", description="Jurisdiction country code (IN/US/UK)")
    period_start: Optional[date] = Field(None, alias="periodStart",
        description="Optional — if provided, real attendance-recorded rewards/bonus/other compensation for this window are included in the preview.")
    period_end: Optional[date] = Field(None, alias="periodEnd")
    calculation_mode: Optional[str] = Field(None, alias="calculationMode",
        description="simple|standard|enterprise — if omitted, resolved from the org's active policy.")
    model_config = ConfigDict(populate_by_name=True)


class PayrollRunPreviewEmployee(BaseModel):
    employeeId: int
    employeeName: str
    department: Optional[str] = None
    attendanceStatus: str = "active"
    monthlyGross: float
    monthlyTax: float
    monthlyPf: float
    monthlyEsi: float
    monthlyPt: float
    monthlyEmployeeLwf: float = 0.0
    monthlyEmployerLwf: float = 0.0
    monthlySocialSecurity: float = 0.0
    monthlyMedicare: float = 0.0
    monthlyNi: float = 0.0
    # UK: Workplace Pension (employee side) and Student/Postgraduate Loan —
    # both were already being computed and put into this response's dict by
    # service.py, but this schema never declared either field, so FastAPI's
    # response_model filtering silently stripped them before this fix —
    # same "computed but invisible" bug as the persisted-payslip schema.
    monthlyEmployeePension: float = 0.0
    monthlyStudyLoanDeduction: float = 0.0
    # UK: Postgraduate Loan (concurrent with an undergraduate plan) and
    # Apprenticeship Levy — same "computed by service.py, never declared
    # here so response_model filtering silently stripped it" gap as
    # monthlyStudyLoanDeduction above, found 2026-09-09 gap-closure Phase 3.
    monthlyPostgradLoanDeduction: float = 0.0
    monthlyContributions: float
    monthlyNet: float
    employerPf: float = 0.0
    employerEps: float = 0.0
    employerPfResidual: float = 0.0
    employerEdli: float = 0.0
    employerNps: float = 0.0
    employerEsi: float = 0.0
    employerSs: float = 0.0
    employerMedicare: float = 0.0
    employerPension: float = 0.0
    employeePension: float = 0.0
    employerNi: float = 0.0
    employerApprenticeshipLevy: float = 0.0
    autoEnrolmentStatus: Optional[str] = None
    taxWeek: Optional[int] = None
    taxMonth: Optional[int] = None
    taxSlabRate: str = "—"
    payableDays: Optional[float] = None
    totalWorkingDays: Optional[float] = None
    prorated: bool = False
    model_config = ConfigDict(populate_by_name=True)


class PayrollRunPreviewTotals(BaseModel):
    count: int
    totalGross: float
    totalTax: float
    totalContributions: float
    totalNet: float
    model_config = ConfigDict(populate_by_name=True)


class PayrollRunPreviewResponse(BaseModel):
    employees: List[PayrollRunPreviewEmployee]
    totals: PayrollRunPreviewTotals
    calculationMode: Optional[str] = Field(None, alias="calculationMode")
    model_config = ConfigDict(populate_by_name=True)


class PayrollRunResponse(BaseModel):
    id:                    int
    runCode:               Optional[str] = Field(None, validation_alias="run_code", serialization_alias="runCode")
    period:                str     = Field(validation_alias="period_label", serialization_alias="period")
    payDate:               date    = Field(validation_alias="pay_date", serialization_alias="payDate")
    status:                PayrollStatus
    employees:             int     = Field(validation_alias="employee_count", serialization_alias="employees")
    gross:                 Decimal = Field(Decimal("0"), validation_alias="total_gross", serialization_alias="gross")
    deductions:            Decimal = Field(Decimal("0"), validation_alias="total_deductions", serialization_alias="deductions")
    taxes:                 Decimal = Field(Decimal("0"), validation_alias="total_taxes", serialization_alias="taxes")
    employerContribution:  Decimal = Field(Decimal("0"), validation_alias="total_employer_contribution", serialization_alias="employerContribution")
    net:                   Decimal = Field(Decimal("0"), validation_alias="total_net", serialization_alias="net")
    notes:                 Optional[str] = None
    calculationMode:       Optional[str] = Field(None, validation_alias="calculation_mode", serialization_alias="calculationMode")
    createdAt:             datetime = Field(validation_alias="created_at", serialization_alias="createdAt")
    createdBy:             Optional[str] = Field(None, validation_alias="created_by_name", serialization_alias="createdBy")
    approvedBy:            Optional[str] = Field(None, validation_alias="approved_by_name", serialization_alias="approvedBy")
    approvedAt:            Optional[datetime] = Field(None, validation_alias="approved_at", serialization_alias="approvedAt")
    authorizedBy:          Optional[str] = Field(None, validation_alias="authorized_by_name", serialization_alias="authorizedBy")
    authorizedAt:          Optional[datetime] = Field(None, validation_alias="authorized_at", serialization_alias="authorizedAt")
    paidBy:                Optional[str] = Field(None, validation_alias="paid_by_name", serialization_alias="paidBy")
    processedAt:           Optional[datetime] = Field(None, validation_alias="processed_at", serialization_alias="processedAt")
    # Set only when the run was deliberately created with incomplete
    # attendance (see service.enforce_attendance_readiness).
    attendanceOverrideReason: Optional[str] = Field(None, validation_alias="attendance_override_reason", serialization_alias="attendanceOverrideReason")
    attendanceOverrideAt:  Optional[datetime] = Field(None, validation_alias="attendance_override_at", serialization_alias="attendanceOverrideAt")
    approvalStatus:        str = ""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @model_validator(mode="after")
    def _set_approval_status(self):
        approved_states = {
            PayrollStatus.APPROVED, PayrollStatus.AUTHORIZED, PayrollStatus.PAID, PayrollStatus.CLOSED,
        }
        self.approvalStatus = "Approved" if self.status in approved_states else "Pending"
        return self


class GeneratePayslipsRequest(BaseModel):
    """Optional body for POST /runs/{id}/generate-payslips."""
    attendance_override_reason: Optional[str] = Field(None, alias="attendanceOverrideReason", max_length=1000)

    model_config = ConfigDict(populate_by_name=True)


class AttendanceReadinessMissing(BaseModel):
    employeeId:    int
    employeeName:  Optional[str] = None
    employeeCode:  Optional[str] = None
    expectedDays:  int
    recordedDays:  int
    missingDays:   int
    missingDates:  List[str] = Field(default_factory=list)


class AttendanceReadinessResponse(BaseModel):
    """Per-employee attendance coverage for a pay period (see
    service.check_attendance_readiness)."""
    required:            bool
    ready:               bool
    periodStart:         Optional[str] = None
    periodEnd:           Optional[str] = None
    weeklyOffDays:       List[int] = Field(default_factory=list)
    employmentTypes:     Optional[List[str]] = None
    totalEmployees:      int = 0
    exemptEmployees:     int = 0
    completeEmployees:   int = 0
    incompleteEmployees: int = 0
    missing:             List[AttendanceReadinessMissing] = Field(default_factory=list)
    missingTruncated:    bool = False


class AttendanceReadinessRequest(BaseModel):
    period_start: date = Field(..., alias="periodStart")
    period_end:   date = Field(..., alias="periodEnd")
    employee_ids: Optional[List[int]] = Field(None, alias="employeeIds")

    model_config = ConfigDict(populate_by_name=True)


# ── Payslip Items ──────────────────────────────────────────────────────

class PayslipItemCreate(BaseModel):
    """Manually add/override a single employee's payslip within a run.
    (Runs created with auto_generate_payslips=True won't normally need this —
    it exists for corrections, off-cycle additions, or contractors.)
    """
    employee_id:    int
    basic_salary:   Decimal
    hra:            Optional[Decimal] = Decimal("0")
    special_allowance: Optional[Decimal] = Decimal("0")
    overtime:       Optional[Decimal] = Decimal("0")
    notes:          Optional[str] = None


class PayslipItemResponse(BaseModel):
    id:                 int
    payslipNumber:      Optional[str] = Field(None, validation_alias="payslip_number", serialization_alias="payslipNumber")
    employee:           str
    employeeId:         int
    department:         Optional[str] = None
    designation:        Optional[str] = None
    dateOfJoining:      Optional[date] = None
    country:            Optional[str] = None
    workState:          Optional[str] = None
    workLocality:       Optional[str] = None
    period:             str
    payDate:            date
    salary:             Decimal
    basicPay:           Decimal
    hra:                Decimal
    specialAllowance:   Decimal
    allowanceItems:     List[dict] = Field(default_factory=list)
    overtime:           Decimal
    additionalCompensation: Decimal = Decimal("0")
    payableDays:        Optional[Decimal] = None
    totalWorkingDays:   Optional[Decimal] = None
    unpaidLeaveDays:    Optional[int] = None
    attendanceDeduction: Optional[Decimal] = None
    tds:                Decimal
    surcharge:          Decimal = Decimal("0")
    cess:               Decimal = Decimal("0")
    # Germany (Kirchensteuer / church tax) — computed by the Germany engine
    # and persisted on PayslipItem.church_tax, but this schema had no field
    # for it, so FastAPI's response_model filtering stripped the key from
    # every payslip API response. Defaulted to 0 so non-Germany payslips
    # (and pre-existing rows) stay unchanged.
    churchTax:          Decimal = Decimal("0")
    # Germany (Solidaritätszuschlag / Soli) — computed by the Germany engine
    # and persisted on PayslipItem.soli, but absent here (same
    # response_model-stripped defect as churchTax above). Informational
    # only: never summed into tds/totalDeductions/netPay (already folded
    # into `tds`). Defaulted to 0 so non-Germany payslips and pre-existing
    # rows stay unchanged.
    soli:               Decimal = Decimal("0")
    federalIncomeTax:   Decimal = Decimal("0")
    stateIncomeTax:     Decimal = Decimal("0")
    localTax:           Decimal = Decimal("0")
    # US: State Disability Insurance / other state payroll-program employee
    # deductions (e.g. CA SDI, NY/NJ/RI TDI, CT/MA/WA/CO/OR/etc. paid-leave
    # employee share) — computed and persisted since 2026-09 gap-closure but
    # never declared here, so response_model filtering silently stripped
    # them from every payslip API response despite _serialize_payslip
    # already including them (found 2026-09-15 Org Admin visibility audit).
    stateDisabilityInsurance: Decimal = Decimal("0")
    stateProgramDeductions: Decimal = Decimal("0")
    pf:                 Decimal
    esi:                Decimal
    professionalTax:    Decimal
    employeeLwf:        Decimal = Decimal("0")
    employerLwf:        Decimal = Decimal("0")
    socialSecurity:     Decimal = Decimal("0")
    medicare:           Decimal = Decimal("0")
    niEmployee:         Decimal = Decimal("0")
    # UK: Workplace Pension (employee side) and Student/Postgraduate Loan —
    # both correctly computed and persisted on PayslipItem, but previously
    # dropped here (employeePension) or never added at all
    # (studyLoanDeduction), so FastAPI's response_model filtering silently
    # stripped them from every payslip API response before this fix.
    employeePension:    Decimal = Decimal("0")
    studyLoanDeduction: Decimal = Decimal("0")
    # UK: Postgraduate Loan (concurrent with an undergraduate plan) — same
    # "computed and persisted, never declared here" gap as
    # studyLoanDeduction above, found 2026-09-09 gap-closure Phase 3.
    postgradLoanDeduction: Decimal = Decimal("0")
    totalDeductions:    Decimal = Decimal("0")
    employerPf:         Decimal = Decimal("0")
    employerEps:        Decimal = Decimal("0")
    employerPfResidual: Decimal = Decimal("0")
    employerEdli:       Decimal = Decimal("0")
    employerNps:        Decimal = Decimal("0")
    employerEsi:        Decimal = Decimal("0")
    employerSs:         Decimal = Decimal("0")
    employerMedicare:   Decimal = Decimal("0")
    employerPension:    Decimal = Decimal("0")
    # UK: employer-side National Insurance — same "computed, persisted,
    # never serialized" gap as studyLoanDeduction above.
    employerNi:         Decimal = Decimal("0")
    # UK: Apprenticeship Levy — same gap, found 2026-09-09 gap-closure
    # Phase 3 alongside the fix that made this value actually get
    # persisted at all (see _compute_payslip_values).
    employerApprenticeshipLevy: Decimal = Decimal("0")
    # US: employer-side FUTA / SUI / state payroll-program contributions —
    # same "computed+persisted but never declared/serialized" gap as the
    # employee-side fields above; RunDetailPanel's register view is the
    # only place these are meant to surface (never on the employee's own
    # payslip, same policy as employerPf/employerNi/etc.).
    employerFuta:       Decimal = Decimal("0")
    employerSui:        Decimal = Decimal("0")
    employerStateProgramContributions: Decimal = Decimal("0")
    # Australia: state/territory employer payroll tax + workers
    # compensation premium (employer-liability-only, AU-D05) and child
    # support/garnishee (a real employee deduction, §19) — computed and
    # persisted since the 2026-09-17 production-readiness pass but never
    # declared here, so response_model filtering silently stripped them
    # from every AU payslip API response despite genuinely affecting net
    # pay (statutory deductions) or being a real employer cost (payroll
    # tax/workers comp) — same defect class as employerFuta/employerSui
    # above, just never caught for AU specifically until this pass.
    employerPayrollTax: Decimal = Decimal("0")
    auStatutoryDeductionsTotal: Decimal = Decimal("0")
    auWorkersCompensationPremium: Decimal = Decimal("0")
    # Australia: §25 "Calculation Trace — Minimum Audit Payload" — see
    # models.PayslipItem.au_calculation_trace's own docstring. None for
    # every non-AU payslip and for any AU payslip generated before this
    # field existed.
    auCalculationTrace: Optional[dict] = None
    # Hong Kong (ZP-HK-ENG-001): the frozen calculation trace (MPF / SMW / IRD
    # reportable) and the payslip's IR56G legal-hold line, if any.
    hkgCalculationTrace: Optional[dict] = None
    hkTaxClearanceHold: Optional[dict] = None
    # Switzerland: the payslip's ch_calculation_snapshot (lines / totals /
    # trace, read by the statutory trace drawer). _serialize_payslip emits it
    # for CH only; declared here so response_model does not strip it.
    chCalculationSnapshot: Optional[dict] = None
    # UK: Automatic Enrolment assessment (ZP-TAX-UK-2026-27-001 §13
    # gap-closure Part 3, 2026-09-09) — a classification, not a monetary
    # amount; informational only, never affects employeePension/
    # employerPension above.
    autoEnrolmentStatus: Optional[str] = None
    # UK: HMRC tax week (1-53) / tax month (1-12) (ZP-TAX-UK-2026-27-001
    # §7.2/§18.1 gap-closure Part 6) — pure calendar metadata for RTI
    # reporting, never affects any calculation.
    taxWeek: Optional[int] = None
    taxMonth: Optional[int] = None
    netPay:             Decimal
    bankName:           Optional[str] = None
    bankAccount:        Optional[str] = None
    pan:                Optional[str] = None
    uan:                Optional[str] = None
    ifsc:               Optional[str] = None
    # Multi-jurisdiction routing (ZP-MJR-2026-001) — additive: ifsc/
    # complianceFields are unchanged, `routing` adds the
    # jurisdiction-correct [{key,label,value}] list read from the payslip's
    # own snapshot (India -> IFSC; other countries -> their compliance
    # fields), so the frontend can render the correct payment rail and
    # routing code per payslip even for historical runs.
    routing:            Optional[List[dict]] = None
    complianceFields:   Optional[dict] = None
    status:             PayslipStatus
    notes:              Optional[str] = None
    # Phase 8BS: Germany-only — `_serialize_payslip` started emitting these
    # three fields (calculation-mode provenance + block reason), but this
    # response_model would have silently stripped them at the API boundary
    # without a declared field, exactly the same "computed, serialized in
    # the dict, dropped by response_model filtering" defect class as
    # churchTax/soli above. None for every non-Germany payslip.
    calculationMode:      Optional[str] = None
    blockedReasonCode:    Optional[str] = None
    blockedReasonMessage: Optional[str] = None
    # Phase 8BU: PARTIAL-status support — same "declare it or response_model
    # strips it" hazard noted above.
    germanyUnavailableComponents: Optional[list] = None
    calculationStatus:            Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)

    # Same shared masking as EmployeeResponse — the payslip's snapshotted
    # compliance_fields carry the same identifiers.
    @field_validator("complianceFields")
    @classmethod
    def _mask_sensitive_compliance_fields(cls, value):
        return mask_compliance_fields(value)

    # Personal account / tax identifiers in top-level columns and the IBAN
    # routing entry — same shared masking (stored values untouched; the
    # edit form's round-tripped mask is restored server-side).
    @field_validator("bankAccount", "pan", "uan")
    @classmethod
    def _mask_sensitive_columns(cls, value):
        return mask_identifier(value) if value else value

    @field_validator("routing")
    @classmethod
    def _mask_routing_account_identifiers(cls, value):
        return mask_routing(value)


# ── UK Statutory Pay Calculator (ZP-TAX-UK-2026-27-001 §11/§12 gap-────────
# closure Phase 5, 2026-09-09) — an on-demand preview, not a payslip
# mutation, so this deliberately has no "*Create"/persisted-row response
# shape like PayslipItemCreate/PayslipItemResponse above.
class UKStatutoryPayRequest(BaseModel):
    employee_id: int
    # "SSP" or one of SMP/SPP/SAP/SHPP/SPBP/SNCP.
    payment_type: str
    event_start_date: date
    week_number: int = 1
    qualifying_days_in_period: Optional[int] = None
    qualifying_days_per_week: Optional[int] = None
    average_weekly_earnings: Optional[Decimal] = None
    include_employer_recovery: bool = False
    prior_year_total_class1_nic: Optional[Decimal] = None


class UKStatutoryPayEmployerRecovery(BaseModel):
    eligible: bool
    reason: str
    recoveryAmount: Decimal = Field(Decimal("0"), validation_alias="recovery_amount", serialization_alias="recoveryAmount")
    model_config = ConfigDict(populate_by_name=True)


class UKStatutoryPayResponse(BaseModel):
    eligible: bool
    reason: str
    amount: Decimal = Decimal("0")
    averageWeeklyEarnings: Decimal = Field(Decimal("0"), validation_alias="average_weekly_earnings", serialization_alias="averageWeeklyEarnings")
    averageWeeklyEarningsSource: str = Field("supplied", validation_alias="average_weekly_earnings_source", serialization_alias="averageWeeklyEarningsSource")
    employerRecovery: Optional[UKStatutoryPayEmployerRecovery] = Field(None, validation_alias="employer_recovery", serialization_alias="employerRecovery")
    model_config = ConfigDict(populate_by_name=True)


# ── UK Employer Annual Charges — Employment Allowance + Class 1A/1B ──────
# (ZP-TAX-UK-2026-27-001 §9.3/§14 gap-closure Phase 6, 2026-09-09).
# Whole-tax-year, run-independent employer liabilities — see
# service.py's get_uk_employer_charges_summary/calculate_uk_employment_
# allowance/calculate_uk_class_1a_1b_charge.
class UKEmployerChargesSummaryResponse(BaseModel):
    taxYear: str = Field(..., validation_alias="tax_year", serialization_alias="taxYear")
    cumulativeEmployerNi: Decimal = Field(Decimal("0"), validation_alias="cumulative_employer_ni", serialization_alias="cumulativeEmployerNi")
    cumulativeApprenticeshipLevyPayBill: Decimal = Field(Decimal("0"), validation_alias="cumulative_apprenticeship_levy_pay_bill", serialization_alias="cumulativeApprenticeshipLevyPayBill")
    model_config = ConfigDict(populate_by_name=True)


class UKEmploymentAllowanceRequest(BaseModel):
    employer_has_claimed: bool


class UKEmploymentAllowanceResponse(BaseModel):
    eligible: bool
    reason: str
    netLiability: Decimal = Field(Decimal("0"), validation_alias="net_liability", serialization_alias="netLiability")
    allowanceRemaining: Decimal = Field(Decimal("0"), validation_alias="allowance_remaining", serialization_alias="allowanceRemaining")
    cumulativeEmployerNi: Decimal = Field(Decimal("0"), validation_alias="cumulative_employer_ni", serialization_alias="cumulativeEmployerNi")
    taxYear: str = Field("", validation_alias="tax_year", serialization_alias="taxYear")
    # Connected-employer allocation (ZP-TAX-UK-2026-27-001 §14 gap-closure
    # Part 7B, 2026-09-09) — None/equal-to-cumulativeEmployerNi when this
    # org isn't in a connected group (the default, unchanged behavior).
    connectedGroupCode: Optional[str] = Field(None, validation_alias="connected_group_code", serialization_alias="connectedGroupCode")
    groupCumulativeEmployerNi: Decimal = Field(Decimal("0"), validation_alias="group_cumulative_employer_ni", serialization_alias="groupCumulativeEmployerNi")
    model_config = ConfigDict(populate_by_name=True)


class UKClass1A1BRequest(BaseModel):
    # One of BENEFITS / TERMINATION_AWARDS / SPORTING_TESTIMONIAL / PSA.
    charge_type: str
    amount: Decimal


class UKClass1A1BResponse(BaseModel):
    eligible: bool
    reason: str
    chargeAmount: Decimal = Field(Decimal("0"), validation_alias="charge_amount", serialization_alias="chargeAmount")
    model_config = ConfigDict(populate_by_name=True)


# ── UK NI Category relief-eligibility facts (ZP-TAX-UK-2026-27-001 ───────
# §9.1/§9.3 gap-closure Part 2, 2026-09-09) — evidence stored SEPARATELY
# from the NI category letter itself, per §9.3's own instruction.
class UKNiReliefFactCreate(BaseModel):
    # FREEPORT | INVESTMENT_ZONE | VETERAN | APPRENTICE
    relief_type: str
    reference: Optional[str] = None
    effective_from: date
    effective_to: Optional[date] = None


class UKNiReliefFactResponse(BaseModel):
    id: int
    employeeId: int = Field(..., validation_alias="employee_id", serialization_alias="employeeId")
    reliefType: str = Field(..., validation_alias="relief_type", serialization_alias="reliefType")
    reference: Optional[str] = None
    effectiveFrom: date = Field(..., validation_alias="effective_from", serialization_alias="effectiveFrom")
    effectiveTo: Optional[date] = Field(None, validation_alias="effective_to", serialization_alias="effectiveTo")
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── UK Mileage Allowance Payments & Advisory Fuel Rates (§16) ───────────
# gap-closure Part 4, 2026-09-09 — on-demand expense-reimbursement
# calculators, same shape as UKStatutoryPayRequest/Response above.
class UKMileageReimbursementRequest(BaseModel):
    employee_id: int
    vehicle_type: str  # CAR | MOTORCYCLE | CYCLE
    business_miles: Decimal
    claim_date: date
    ytd_business_miles_before: Optional[Decimal] = None


class UKMileageReimbursementResponse(BaseModel):
    eligible: bool
    reason: str
    taxFreeAmount: Decimal = Field(Decimal("0"), validation_alias="tax_free_amount", serialization_alias="taxFreeAmount")
    niFreeAmount: Decimal = Field(Decimal("0"), validation_alias="ni_free_amount", serialization_alias="niFreeAmount")
    model_config = ConfigDict(populate_by_name=True)


class UKAdvisoryFuelRateRequest(BaseModel):
    fuel_type: str  # PETROL | LPG | DIESEL | ELECTRIC
    engine_band: str  # LE_1400 | 1401_2000 | GT_2000 | LE_1600 | 1601_2000 | HOME | PUBLIC
    as_of: Optional[date] = None


class UKAdvisoryFuelRateResponse(BaseModel):
    eligible: bool
    reason: str
    ratePerMile: Decimal = Field(Decimal("0"), validation_alias="rate_per_mile", serialization_alias="ratePerMile")
    model_config = ConfigDict(populate_by_name=True)


# ── UK National Minimum Wage compliance validation (§15) ────────────────
# gap-closure Part 5, 2026-09-09 — a pay-compliance check, not a payroll
# tax. `nmw_countable_pay` is the caller's own already-reduced figure
# (§15's own warning about deductions/accommodation offset complexity).
class UKNmwComplianceRequest(BaseModel):
    employee_id: int
    period_start: date
    period_end: date
    nmw_countable_pay: Decimal


class UKNmwComplianceResponse(BaseModel):
    eligible: bool
    reason: str
    applicableRate: Decimal = Field(Decimal("0"), validation_alias="applicable_rate", serialization_alias="applicableRate")
    effectiveHourlyRate: Decimal = Field(Decimal("0"), validation_alias="effective_hourly_rate", serialization_alias="effectiveHourlyRate")
    compliant: bool = False
    shortfallAmount: Decimal = Field(Decimal("0"), validation_alias="shortfall_amount", serialization_alias="shortfallAmount")
    model_config = ConfigDict(populate_by_name=True)


# ── UK Court-Ordered Deductions (§17 gap-closure Part 8, 2026-09-09) ────
# England & Wales AEOs / Scottish arrestments / Northern Ireland orders.
class UKCourtOrderCreate(BaseModel):
    jurisdiction: str  # ENGLAND_WALES | SCOTLAND | NORTHERN_IRELAND
    order_type: str
    start_date: date
    court_reference: Optional[str] = None
    issue_date: Optional[date] = None
    end_date: Optional[date] = None
    priority: Optional[int] = None
    fixed_deduction_rate_pct: Optional[Decimal] = None
    fixed_deduction_amount: Optional[Decimal] = None
    protected_earnings_amount: Optional[Decimal] = None
    total_amount_to_collect: Optional[Decimal] = None


class UKCourtOrderStatusUpdate(BaseModel):
    status: str  # active | completed | cancelled


class UKCourtOrderResponse(BaseModel):
    id: int
    employeeId: int = Field(..., validation_alias="employee_id", serialization_alias="employeeId")
    jurisdiction: str
    orderType: str = Field(..., validation_alias="order_type", serialization_alias="orderType")
    courtReference: Optional[str] = Field(None, validation_alias="court_reference", serialization_alias="courtReference")
    issueDate: Optional[date] = Field(None, validation_alias="issue_date", serialization_alias="issueDate")
    startDate: date = Field(..., validation_alias="start_date", serialization_alias="startDate")
    endDate: Optional[date] = Field(None, validation_alias="end_date", serialization_alias="endDate")
    priority: Optional[int] = None
    fixedDeductionRatePct: Optional[Decimal] = Field(None, validation_alias="fixed_deduction_rate_pct", serialization_alias="fixedDeductionRatePct")
    fixedDeductionAmount: Optional[Decimal] = Field(None, validation_alias="fixed_deduction_amount", serialization_alias="fixedDeductionAmount")
    protectedEarningsAmount: Optional[Decimal] = Field(None, validation_alias="protected_earnings_amount", serialization_alias="protectedEarningsAmount")
    totalAmountToCollect: Optional[Decimal] = Field(None, validation_alias="total_amount_to_collect", serialization_alias="totalAmountToCollect")
    totalAmountCollected: Decimal = Field(Decimal("0"), validation_alias="total_amount_collected", serialization_alias="totalAmountCollected")
    status: str
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class UKCourtOrderCalculateRequest(BaseModel):
    employee_id: int
    attachable_earnings: Decimal
    pay_frequency: str
    as_of: Optional[date] = None


class UKCourtOrderDeductionEntry(BaseModel):
    orderId: Optional[int] = Field(None, validation_alias="order_id", serialization_alias="orderId")
    eligible: bool
    reason: str
    deductionAmount: Decimal = Field(Decimal("0"), validation_alias="deduction_amount", serialization_alias="deductionAmount")
    model_config = ConfigDict(populate_by_name=True)


class UKCourtOrderCalculateResponse(BaseModel):
    totalDeduction: Decimal = Field(Decimal("0"), validation_alias="total_deduction", serialization_alias="totalDeduction")
    orders: List[UKCourtOrderDeductionEntry] = Field(default_factory=list)
    model_config = ConfigDict(populate_by_name=True)


# Australia child support/garnishee (§19, Phase 5) — reuses UKCourtOrder
# Create/Response/StatusUpdate/DeductionEntry/CalculateResponse directly
# (jurisdiction/order_type were always free-text, not UK-only) rather than
# duplicating them; only the calculate REQUEST differs, since AU has no
# frequency-dependent band table at all and therefore no pay_frequency
# field to require.
class AUCourtOrderCalculateRequest(BaseModel):
    employee_id: int
    attachable_earnings: Decimal
    as_of: Optional[date] = None


# ── India: Gratuity (ZP-TAX-IN-2026-27-001 §11) ─────────────────────────

class GratuityCalculateRequest(BaseModel):
    employee_id: int
    eligibility_event: str = "RESIGNATION"  # RETIREMENT | RESIGNATION | TERMINATION | DEATH | DISABLEMENT | FIXED_TERM_END
    is_fixed_term: bool = False
    date_of_leaving: Optional[date] = None
    last_drawn_monthly_wage: Optional[Decimal] = None


class GratuityCalculateResponse(BaseModel):
    eligible: bool
    reason: str
    gratuityAmount: Decimal = Field(Decimal("0"), validation_alias="gratuity_amount", serialization_alias="gratuityAmount")
    # Section 10(10) income-tax exempt/taxable split — None (not 0) means
    # "not computed," when gratuity_exempt_lim isn't configured (see
    # india.py's calculate_gratuity docstring for the full explanation).
    exemptGratuityAmount: Optional[Decimal] = Field(None, validation_alias="exempt_gratuity_amount", serialization_alias="exemptGratuityAmount")
    taxableGratuityAmount: Optional[Decimal] = Field(None, validation_alias="taxable_gratuity_amount", serialization_alias="taxableGratuityAmount")
    model_config = ConfigDict(populate_by_name=True)


# ── Canada: bonus/retroactive-pay special-payment method ────────────────
# (ZP-TAX-CA-2026-001 §19, gap-closure 2026-09-11) — see service.
# calculate_ca_special_payment_withholding's own docstring for why
# regular_annual_pay is required rather than estimated.
class CASpecialPaymentCalculateRequest(BaseModel):
    employee_id: int
    regular_annual_pay: Decimal
    special_payment_amount: Decimal
    payroll_date: Optional[date] = None


# ── US: supplemental wages flat-rate method ───────────────────────────────
# (ZP-TAX-US-2026-001 §3.1, gap-closure 2026-09-12) — see service.
# calculate_us_supplemental_wage_withholding's own docstring for why
# cytd_supplemental_wages_before is required rather than assumed zero.
class USSupplementalWageCalculateRequest(BaseModel):
    employee_id: int
    supplemental_wage_amount: Decimal
    cytd_supplemental_wages_before: Decimal = Decimal("0")


class USSupplementalWageCalculateResponse(BaseModel):
    supplementalWageAmount: Decimal = Field(validation_alias="supplemental_wage_amount", serialization_alias="supplementalWageAmount")
    cytdSupplementalWagesBefore: Decimal = Field(validation_alias="cytd_supplemental_wages_before", serialization_alias="cytdSupplementalWagesBefore")
    cytdSupplementalWagesAfter: Decimal = Field(validation_alias="cytd_supplemental_wages_after", serialization_alias="cytdSupplementalWagesAfter")
    amountAtFlatRate: Decimal = Field(validation_alias="amount_at_flat_rate", serialization_alias="amountAtFlatRate")
    flatRatePct: Decimal = Field(validation_alias="flat_rate_pct", serialization_alias="flatRatePct")
    amountAtHighRate: Decimal = Field(validation_alias="amount_at_high_rate", serialization_alias="amountAtHighRate")
    highRatePct: Decimal = Field(validation_alias="high_rate_pct", serialization_alias="highRatePct")
    withholdingAtFlatRate: Decimal = Field(validation_alias="withholding_at_flat_rate", serialization_alias="withholdingAtFlatRate")
    withholdingAtHighRate: Decimal = Field(validation_alias="withholding_at_high_rate", serialization_alias="withholdingAtHighRate")
    totalWithholding: Decimal = Field(validation_alias="total_withholding", serialization_alias="totalWithholding")
    model_config = ConfigDict(populate_by_name=True)


# ── US: federal deposit/filing calendar ───────────────────────────────────
# (ZP-TAX-US-2026-001 §3.5, gap-closure 2026-09-12) — org-scoped, no
# employee_id (a federal deposit obligation is the employer's). See
# service.calculate_us_federal_deposit_schedule's own docstring for why
# the three liability figures are required rather than assumed.
class USFederalDepositScheduleRequest(BaseModel):
    lookback_period_liability: Decimal
    payroll_date: date
    accumulated_undeposited_liability: Optional[Decimal] = None
    quarterly_futa_liability: Optional[Decimal] = None


class USFederalDepositScheduleResponse(BaseModel):
    depositorStatus: str = Field(validation_alias="depositor_status", serialization_alias="depositorStatus")
    lookbackPeriodLiability: Decimal = Field(validation_alias="lookback_period_liability", serialization_alias="lookbackPeriodLiability")
    monthlySemiweeklyThreshold: Decimal = Field(validation_alias="monthly_semiweekly_threshold", serialization_alias="monthlySemiweeklyThreshold")
    depositDueDate: date = Field(validation_alias="deposit_due_date", serialization_alias="depositDueDate")
    nextDayRuleTriggered: bool = Field(validation_alias="next_day_rule_triggered", serialization_alias="nextDayRuleTriggered")
    nextDayDepositThreshold: Decimal = Field(validation_alias="next_day_deposit_threshold", serialization_alias="nextDayDepositThreshold")
    nextDayDepositDueDate: Optional[date] = Field(default=None, validation_alias="next_day_deposit_due_date", serialization_alias="nextDayDepositDueDate")
    futaDepositRequired: Optional[bool] = Field(default=None, validation_alias="futa_deposit_required", serialization_alias="futaDepositRequired")
    futaDepositThreshold: Decimal = Field(validation_alias="futa_deposit_threshold", serialization_alias="futaDepositThreshold")
    formW2W3Deadline: date = Field(validation_alias="form_w2_w3_deadline", serialization_alias="formW2W3Deadline")
    model_config = ConfigDict(populate_by_name=True)


class PRDepositScheduleRequest(BaseModel):
    lookback_period_liability: Decimal
    current_quarter_withholding: Decimal
    payroll_date: date
    accumulated_undeposited_liability: Optional[Decimal] = None


class PRDepositScheduleResponse(BaseModel):
    depositorStatus: str = Field(validation_alias="depositor_status", serialization_alias="depositorStatus")
    lookbackPeriodLiability: Decimal = Field(validation_alias="lookback_period_liability", serialization_alias="lookbackPeriodLiability")
    currentQuarterWithholding: Decimal = Field(validation_alias="current_quarter_withholding", serialization_alias="currentQuarterWithholding")
    monthlySemiweeklyThreshold: Decimal = Field(validation_alias="monthly_semiweekly_threshold", serialization_alias="monthlySemiweeklyThreshold")
    quarterlyExceptionThreshold: Decimal = Field(validation_alias="quarterly_exception_threshold", serialization_alias="quarterlyExceptionThreshold")
    depositDueDate: Optional[date] = Field(default=None, validation_alias="deposit_due_date", serialization_alias="depositDueDate")
    nextDayRuleTriggered: bool = Field(validation_alias="next_day_rule_triggered", serialization_alias="nextDayRuleTriggered")
    nextDayDepositThreshold: Decimal = Field(validation_alias="next_day_deposit_threshold", serialization_alias="nextDayDepositThreshold")
    nextDayDepositDueDate: Optional[date] = Field(default=None, validation_alias="next_day_deposit_due_date", serialization_alias="nextDayDepositDueDate")
    form499R2Deadline: date = Field(validation_alias="form_499r2_deadline", serialization_alias="form499R2Deadline")
    model_config = ConfigDict(populate_by_name=True)


class CARetiringAllowanceCalculateRequest(BaseModel):
    employee_id: int
    amount: Decimal
    payroll_date: Optional[date] = None


class CARetiringAllowanceCalculateResponse(BaseModel):
    amount: Decimal = Field(validation_alias="amount", serialization_alias="amount")
    ratePct: Decimal = Field(validation_alias="rate_pct", serialization_alias="ratePct")
    withholding: Decimal = Field(validation_alias="withholding", serialization_alias="withholding")
    configured: bool = Field(validation_alias="configured", serialization_alias="configured")
    model_config = ConfigDict(populate_by_name=True)


class CATd1xCommissionCalculateRequest(BaseModel):
    employee_id: int
    payroll_date: Optional[date] = None
    pay_periods_per_year: int = 12


class CATd1xCommissionCalculateResponse(BaseModel):
    estimatedAnnualCommission: Decimal = Field(validation_alias="estimated_annual_commission", serialization_alias="estimatedAnnualCommission")
    estimatedAnnualExpenses: Decimal = Field(validation_alias="estimated_annual_expenses", serialization_alias="estimatedAnnualExpenses")
    netAnnualCommissionIncome: Decimal = Field(validation_alias="net_annual_commission_income", serialization_alias="netAnnualCommissionIncome")
    federalAnnualTax: Decimal = Field(validation_alias="federal_annual_tax", serialization_alias="federalAnnualTax")
    provincialAnnualTax: Decimal = Field(validation_alias="provincial_annual_tax", serialization_alias="provincialAnnualTax")
    totalAnnualTax: Decimal = Field(validation_alias="total_annual_tax", serialization_alias="totalAnnualTax")
    payPeriodsPerYear: int = Field(validation_alias="pay_periods_per_year", serialization_alias="payPeriodsPerYear")
    perPeriodWithholding: Decimal = Field(validation_alias="per_period_withholding", serialization_alias="perPeriodWithholding")
    isQuebec: bool = Field(validation_alias="is_quebec", serialization_alias="isQuebec")
    model_config = ConfigDict(populate_by_name=True)


class CAWsdrfCalculateRequest(BaseModel):
    period_start: date
    period_end: date
    training_expenditure_override: Optional[Decimal] = None


class CAWsdrfCalculateResponse(BaseModel):
    totalQuebecPayroll: Decimal = Field(validation_alias="total_quebec_payroll", serialization_alias="totalQuebecPayroll")
    wsdrfRatePct: Decimal = Field(validation_alias="wsdrf_rate_pct", serialization_alias="wsdrfRatePct")
    requiredInvestment: Decimal = Field(validation_alias="required_investment", serialization_alias="requiredInvestment")
    trainingExpenditure: Decimal = Field(validation_alias="training_expenditure", serialization_alias="trainingExpenditure")
    shortfall: Decimal = Field(validation_alias="shortfall", serialization_alias="shortfall")
    employeeCount: int = Field(validation_alias="employee_count", serialization_alias="employeeCount")
    model_config = ConfigDict(populate_by_name=True)


class CASpecialPaymentCalculateResponse(BaseModel):
    regularAnnualPay: Decimal = Field(validation_alias="regular_annual_pay", serialization_alias="regularAnnualPay")
    specialPaymentAmount: Decimal = Field(validation_alias="special_payment_amount", serialization_alias="specialPaymentAmount")
    federalTaxBefore: Decimal = Field(validation_alias="federal_tax_before", serialization_alias="federalTaxBefore")
    federalTaxAfter: Decimal = Field(validation_alias="federal_tax_after", serialization_alias="federalTaxAfter")
    provincialTaxBefore: Decimal = Field(validation_alias="provincial_tax_before", serialization_alias="provincialTaxBefore")
    provincialTaxAfter: Decimal = Field(validation_alias="provincial_tax_after", serialization_alias="provincialTaxAfter")
    federalWithholding: Decimal = Field(validation_alias="federal_withholding", serialization_alias="federalWithholding")
    provincialWithholding: Decimal = Field(validation_alias="provincial_withholding", serialization_alias="provincialWithholding")
    totalWithholding: Decimal = Field(validation_alias="total_withholding", serialization_alias="totalWithholding")
    isQuebec: bool = Field(validation_alias="is_quebec", serialization_alias="isQuebec")
    model_config = ConfigDict(populate_by_name=True)


# ── Australia: Schedule 5 back payment/commission/bonus averaging method ──
# (ZP-TAX-AU-2026-27-001 §9, production-readiness fix plan Tier 3.1) — see
# service.calculate_au_employee_schedule5_withholding's own docstring.
class AUSchedule5CalculateRequest(BaseModel):
    employee_id: int
    regular_period_gross: Decimal
    special_payment_amount: Decimal
    payroll_date: Optional[date] = None


class AUSchedule5CalculateResponse(BaseModel):
    regularPeriodGross: Decimal = Field(validation_alias="regular_period_gross", serialization_alias="regularPeriodGross")
    specialPaymentAmount: Decimal = Field(validation_alias="special_payment_amount", serialization_alias="specialPaymentAmount")
    periodsPerYear: int = Field(validation_alias="periods_per_year", serialization_alias="periodsPerYear")
    averagedAmount: Decimal = Field(validation_alias="averaged_amount", serialization_alias="averagedAmount")
    withholdingWithoutPayment: Decimal = Field(validation_alias="withholding_without_payment", serialization_alias="withholdingWithoutPayment")
    withholdingWithAveragedPayment: Decimal = Field(validation_alias="withholding_with_averaged_payment", serialization_alias="withholdingWithAveragedPayment")
    totalWithholding: Decimal = Field(validation_alias="total_withholding", serialization_alias="totalWithholding")
    model_config = ConfigDict(populate_by_name=True)


# ── Australia: Schedule 4 return-to-work payment flat-rate method ────────
# (ZP-TAX-AU-2026-27-001 §9, production-readiness fix plan Tier 3.1) — see
# service.calculate_au_employee_schedule4_withholding's own docstring.
class AUSchedule4CalculateRequest(BaseModel):
    employee_id: int
    payment_amount: Decimal


class AUSchedule4CalculateResponse(BaseModel):
    paymentAmount: Decimal = Field(validation_alias="payment_amount", serialization_alias="paymentAmount")
    tfnStatus: Optional[str] = Field(None, validation_alias="tfn_status", serialization_alias="tfnStatus")
    residencyStatus: Optional[str] = Field(None, validation_alias="residency_status", serialization_alias="residencyStatus")
    withholding: Decimal
    model_config = ConfigDict(populate_by_name=True)


# ── Company Holidays ─────────────────────────────────────────────────────

class HolidayCreate(BaseModel):
    date: date
    name: Optional[str] = None


class BulkHolidayRequest(BaseModel):
    holidays: List[HolidayCreate]


class HolidayResponse(BaseModel):
    id:       int
    date:     date
    name:     Optional[str] = None
    country:  Optional[str] = None
    category: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ── Leave Allocations ─────────────────────────────────────────────────

class LeaveAllocationCreate(BaseModel):
    employeeId:         int = Field(validation_alias="employeeId")
    leaveBalances:      Optional[dict] = Field(default=None, validation_alias="leaveBalances")
    periodLabel:        Optional[str] = Field(None, validation_alias="periodLabel")
    notes:              Optional[str] = Field(None, validation_alias="notes")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class BulkLeaveRequest(BaseModel):
    records: List[LeaveAllocationCreate]


class LeaveAllocationResponse(BaseModel):
    id:                 int
    employeeId:         int     = Field(validation_alias="employee_id", serialization_alias="employeeId")
    leaveBalances:      Optional[dict] = Field(default=None, validation_alias="leave_balances", serialization_alias="leaveBalances")
    periodLabel:        Optional[str] = Field(None, validation_alias="period_label", serialization_alias="periodLabel")
    notes:              Optional[str] = Field(None, validation_alias="notes", serialization_alias="notes")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Leave Requests ────────────────────────────────────────────────────

class PayrollLeaveRequestCreate(BaseModel):
    employeeId:         int = Field(validation_alias="employeeId")
    leaveType:          str = Field(validation_alias="leaveType")
    startDate:          date = Field(validation_alias="startDate")
    endDate:            date = Field(validation_alias="endDate")
    reason:             Optional[str] = None

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class PayrollLeaveRequestUpdate(BaseModel):
    status:             Optional[str] = None   # approved / rejected
    reason:             Optional[str] = None

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class PayrollLeaveRequestResponse(BaseModel):
    id:                 int
    requestCode:        Optional[str] = Field(None, validation_alias="request_code", serialization_alias="requestCode")
    employeeId:         int     = Field(validation_alias="employee_id", serialization_alias="employeeId")
    employeeName:       Optional[str] = Field(None, serialization_alias="employeeName")
    department:         Optional[str] = None
    leaveType:          str     = Field(validation_alias="leave_type", serialization_alias="leaveType")
    startDate:          date    = Field(validation_alias="start_date", serialization_alias="startDate")
    endDate:            date    = Field(validation_alias="end_date", serialization_alias="endDate")
    days:               int
    reason:             Optional[str] = None
    status:             str
    reviewedBy:         Optional[int] = Field(None, validation_alias="reviewed_by", serialization_alias="reviewedBy")
    reviewedAt:         Optional[datetime] = Field(None, validation_alias="reviewed_at", serialization_alias="reviewedAt")
    createdAt:          Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")
    updatedAt:          Optional[datetime] = Field(None, validation_alias="updated_at", serialization_alias="updatedAt")
    linkedAttendanceDates: Optional[List[date]] = Field(None, serialization_alias="linkedAttendanceDates")
    isAutoCreated:      Optional[bool] = Field(False, serialization_alias="isAutoCreated")
    # UK statutory leave wiring (ZP-TAX-UK-2026-27-001 §11 gap-closure
    # Part 7A, 2026-09-09) — populated only for a statutory leave_type
    # once approved with the switch on; NULL otherwise.
    statutoryPayType:      Optional[str] = Field(None, serialization_alias="statutoryPayType")
    statutoryAweSnapshot:  Optional[Decimal] = Field(None, serialization_alias="statutoryAweSnapshot")
    statutoryPayTotalAmount: Optional[Decimal] = Field(None, serialization_alias="statutoryPayTotalAmount")
    statutoryPayNote:      Optional[str] = Field(None, serialization_alias="statutoryPayNote")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Attendance & Compensation ──────────────────────────────────────────
# Backed by PayrollAttendanceRecord (models.py). Frontend sends/receives
# camelCase JSON that maps to snake_case DB columns.

class AttendanceRecordCreate(BaseModel):
    employeeId:         Optional[int] = Field(None, validation_alias="employeeId")
    date:               date
    checkIn:            Optional[str] = Field(None, validation_alias="checkIn")
    checkOut:           Optional[str] = Field(None, validation_alias="checkOut")
    checkInPeriod:      Optional[str] = Field("AM", validation_alias="checkInPeriod")
    checkOutPeriod:     Optional[str] = Field("PM", validation_alias="checkOutPeriod")
    breakMinutes:       Optional[int] = Field(60, validation_alias="breakMinutes")
    status:             str = "present"
    leaveType:          Optional[str] = Field(None, validation_alias="leaveType")
    isHalfDay:          Optional[bool] = Field(False, validation_alias="isHalfDay")
    hours:              Optional[str] = None
    rewards:            Optional[Decimal] = Decimal("0")
    bonus:              Optional[Decimal] = Decimal("0")
    otherCompensation:  Optional[Decimal] = Field(Decimal("0"), validation_alias="otherCompensation")
    notes:              Optional[str] = None
    name:               Optional[str] = None
    department:         Optional[str] = None

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class BulkAttendanceRequest(BaseModel):
    records: List[AttendanceRecordCreate]


class AttendanceRecordResponse(BaseModel):
    id:                 int
    employeeId:         int     = Field(validation_alias="employee_id", serialization_alias="employeeId")
    name:               Optional[str] = None
    department:         Optional[str] = None
    designation:        Optional[str] = None
    date:               date
    checkIn:            Optional[str] = Field(None, validation_alias="check_in", serialization_alias="checkIn")
    checkOut:           Optional[str] = Field(None, validation_alias="check_out", serialization_alias="checkOut")
    status:             str
    leaveType:          Optional[str] = Field(None, validation_alias="leave_type", serialization_alias="leaveType")
    isHalfDay:          bool = Field(False, validation_alias="is_half_day", serialization_alias="isHalfDay")
    leaveRequestId:     Optional[int] = Field(None, validation_alias="leave_request_id", serialization_alias="leaveRequestId")
    hours:              Optional[str] = None
    rewards:            Decimal = Decimal("0")
    bonus:              Decimal = Decimal("0")
    otherCompensation:  Decimal = Field(Decimal("0"), validation_alias="other_compensation", serialization_alias="otherCompensation")
    notes:              Optional[str] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class AttendancePageResponse(BaseModel):
    """One page of attendance records plus the exact total.

    Kept alongside List[AttendanceRecordResponse] rather than replacing it: a
    bare list cannot express "is there more", so a client that pages has to
    infer the end of the data from a short page and re-fetch blindly. hasMore
    is computed server-side by fetching limit+1 rows, so it is exact even when
    rows are inserted between page requests.
    """
    items:  List[AttendanceRecordResponse] = Field(default_factory=list)
    total:  int
    limit:  int
    offset: int
    hasMore: bool = Field(False, serialization_alias="hasMore")
    # Span of the whole filtered set, so a paged client can still report the
    # true date range rather than the range of whichever page it holds.
    firstDate: Optional[date] = Field(None, serialization_alias="firstDate")
    lastDate:  Optional[date] = Field(None, serialization_alias="lastDate")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class EmployeeAttendanceSummaryRow(BaseModel):
    """One employee's aggregated attendance for a range.

    `avgCheckIn`/`avgCheckOut` are the most frequently recorded times, not
    arithmetic means. `avgBreak` is always 0: payroll_attendance_records has no
    break_minutes column, so there is no source for it and the value is not
    invented.
    """
    employeeId:        int
    name:              str
    department:        str = ""
    designation:       str = ""
    totalDays:         int = 0
    present:           int = 0
    absent:            int = 0
    leave:             int = 0
    unpaidLeaves:      int = 0
    paidLeaves:        int = 0
    totalHours:        float = 0.0
    avgCheckIn:        str = ""
    avgCheckOut:       str = ""
    avgBreak:          float = 0.0

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class AttendanceTotals(BaseModel):
    """Org-wide sums across every employee in the filtered set.

    Needed because the Summary tab's stat cards total every employee, while
    the table itself is paged. Summing only the loaded page would under-report
    whenever there is a second page.
    """
    totalDays:    int = 0
    present:      int = 0
    absent:       int = 0
    leave:        int = 0
    unpaidLeaves: int = 0
    paidLeaves:   int = 0

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class EmployeeAttendanceSummaryPageResponse(BaseModel):
    """Paged per-employee aggregates so the Summary tab can page server-side
    instead of downloading every attendance row to count days in the browser."""
    items:  List[EmployeeAttendanceSummaryRow] = Field(default_factory=list)
    total:  int
    limit:  int
    offset: int
    hasMore: bool = Field(False, serialization_alias="hasMore")
    totals: AttendanceTotals = Field(default_factory=AttendanceTotals)

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SkippedRecordDetail(BaseModel):
    rowName:            Optional[str] = Field(None, serialization_alias="rowName")
    rowId:              Optional[int] = Field(None, serialization_alias="rowId")
    reason:             str = ""
    skip_date:          Optional[date] = Field(None, alias="date")

    model_config = ConfigDict(populate_by_name=True)


class BulkAttendanceResponse(BaseModel):
    saved:              int = 0
    skipped:            int = 0
    skippedDetails:     List[SkippedRecordDetail] = Field(default_factory=list, serialization_alias="skippedDetails")
    records:            List[AttendanceRecordResponse] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)


class AttendanceSummaryResponse(BaseModel):
    total:   int
    present: int
    absent:  int
    leave:   int

    model_config = ConfigDict(populate_by_name=True)

# ── Compliance ─────────────────────────────────────────────────────────

class CompanyDetails(BaseModel):
    name:                 str = ""
    type:                 str = ""
    taxNo:                str = Field("", validation_alias="tax_no", serialization_alias="taxNo")
    employerId:           str = Field("", validation_alias="employer_id", serialization_alias="employerId")
    address:              str = ""
    industry:             str = ""
    email:                str = ""
    phone:                str = ""
    jurisdictionCountry:  str = Field("", validation_alias="jurisdiction_country", serialization_alias="jurisdictionCountry")
    jurisdictionState:    str = Field("", validation_alias="jurisdiction_state", serialization_alias="jurisdictionState")
    compliancePack:       str = Field("", validation_alias="compliance_pack", serialization_alias="compliancePack")
    schedule:             str = ""
    settlementBank:       str = Field("", validation_alias="settlement_bank", serialization_alias="settlementBank")
    settlementAcc:        str = Field("", validation_alias="settlement_acc", serialization_alias="settlementAcc")
    # Jurisdiction-aware tax/registration IDs synced from registration (see
    # app/core/jurisdiction.py) and editable/overridable from the Compliance
    # Details tab. Optional dict so legacy rows without it still serialize.
    taxIdentifiers:       Optional[dict] = Field(None, validation_alias="tax_identifiers", serialization_alias="taxIdentifiers")
    configuredAt:         Optional[datetime] = Field(None, validation_alias="configured_at", serialization_alias="configuredAt")
    isConfigured:         bool = Field(False, validation_alias="is_configured", serialization_alias="isConfigured")
    # ZP-TAX-CA-2026-001 §15/AC-20 — "CHARITY_NONPROFIT" or None/anything
    # else (ordinary). Only meaningful for CA/BC orgs; harmless elsewhere.
    bcEhtEmployerClassification: Optional[str] = Field(
        None, validation_alias="bc_eht_employer_classification", serialization_alias="bcEhtEmployerClassification",
    )
    # ZP-TAX-CA-2026-001 §13 — GENERAL | PRIMARY_MANUFACTURING |
    # PUBLIC_SECTOR. Only meaningful for CA/QC orgs; harmless elsewhere.
    qcHsfEmployerCategory: Optional[str] = Field(
        None, validation_alias="qc_hsf_employer_category", serialization_alias="qcHsfEmployerCategory",
    )
    # UK RTI (ZP-TAX-UK-2026-27-001 §18 gap-closure Part 9, 2026-09-09) —
    # only meaningful for UK orgs; harmless elsewhere.
    payeReference: Optional[str] = Field(None, validation_alias="paye_reference", serialization_alias="payeReference")
    accountsOfficeReference: Optional[str] = Field(
        None, validation_alias="accounts_office_reference", serialization_alias="accountsOfficeReference",
    )

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class CompanyDetailsUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    taxNo: Optional[str] = None
    employerId: Optional[str] = None
    address: Optional[str] = None
    industry: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    jurisdictionCountry: Optional[str] = None
    jurisdictionState: Optional[str] = None
    compliancePack: Optional[str] = None
    schedule: Optional[str] = None
    settlementBank: Optional[str] = None
    settlementAcc: Optional[str] = None
    taxIdentifiers: Optional[dict] = None
    bcEhtEmployerClassification: Optional[str] = None
    qcHsfEmployerCategory: Optional[str] = None
    payeReference: Optional[str] = None
    accountsOfficeReference: Optional[str] = None


class ComplianceDataResponse(BaseModel):
    """Shape expected by CompliancePage.jsx: { company, filings }."""
    company: CompanyDetails
    filings: List[dict] = []


class ContributionRateResponse(BaseModel):
    id:       int
    label:    str
    employee: str = Field(validation_alias="employee_share", serialization_alias="employee")
    employer: str = Field(validation_alias="employer_share", serialization_alias="employer")
    total:    str

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class TaxSlabResponse(BaseModel):
    id:   int
    min:  str = ""
    max:  str = ""
    rate: str = Field(validation_alias="rate_label", serialization_alias="rate")
    tax:  str = Field(validation_alias="tax_formula", serialization_alias="tax")
    # The real classification (MARGINAL_RATE | PT_FLAT | NI_BAND | FORMULA |
    # SURCHARGE | ...) — added so org-facing consumers (TaxConfigurationTab.jsx)
    # can filter on the actual row type instead of guessing from the display
    # label. Previously omitted entirely; a 0%-rate MARGINAL_RATE bracket
    # labeled "Nil" was indistinguishable from a flat-amount PT_FLAT bracket
    # without this field.
    ruleType: str = Field(validation_alias="rule_type", serialization_alias="ruleType")
    # Federal (country-level) vs. state-level rows share the same ruleType
    # (MARGINAL_RATE) with nothing else to tell them apart client-side —
    # added so TaxConfigurationTab.jsx's US "State Taxes" item can actually
    # filter to the org's own state instead of being hardcoded to show
    # nothing (found 2026-09-15 Org Admin visibility audit). None = a
    # country-level row (e.g. US Federal, India Central), same convention
    # as the model column itself.
    jurisdictionState: Optional[str] = Field(None, validation_alias="jurisdiction_state", serialization_alias="jurisdictionState")
    # Raw numeric bounds, additive alongside the pre-formatted min/max/rate
    # strings above. Needed so PT_FLAT rows (state Professional Tax — a
    # fixed monthly amount per gross-income bracket, not a percentage) can
    # be rendered as their own business-language table (Gross Income
    # From/To, Monthly PT Amount, Adjustment Month Amount), mirroring
    # Super Admin's CanonicalTaxSlabResponse columns exactly, instead of
    # forcing PT data through the generic Min/Max/Rate table built for
    # percentage brackets. None for every rule_type that doesn't use them.
    minAmount: Optional[Decimal] = Field(None, validation_alias="min_amount", serialization_alias="minAmount")
    maxAmount: Optional[Decimal] = Field(None, validation_alias="max_amount", serialization_alias="maxAmount")
    flatAmount: Optional[Decimal] = Field(None, validation_alias="flat_amount", serialization_alias="flatAmount")
    adjustmentAmount: Optional[Decimal] = Field(None, validation_alias="adjustment_amount", serialization_alias="adjustmentAmount")
    # Sweden (ZP-SE-ENG-001 §7/§8): SE_TAX_TABLE / SE_ONE_TIME_PAYMENT rows
    # carry which table + column they belong to; NULL/omitted everywhere else.
    taxTableNumber: Optional[str] = Field(None, validation_alias="tax_table_number", serialization_alias="taxTableNumber")
    taxColumn: Optional[str] = Field(None, validation_alias="tax_column", serialization_alias="taxColumn")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    # Duplicated from service.py's _get_currency_symbol rather than imported,
    # to avoid a schemas.py <-> service.py circular import for a 6-entry map.
    # Must be ClassVar — a bare class attribute here gets wrapped by Pydantic
    # v2 as a ModelPrivateAttr descriptor (no .get()), which silently turned
    # every /compliance/tax-slabs response into a 500 until this was caught.
    _CURRENCY_SYMBOLS: ClassVar[dict] = {"IN": "₹", "US": "$", "UK": "£", "AU": "A$", "DE": "€", "CA": "C$"}

    @model_validator(mode="before")
    @classmethod
    def _extract_and_format_bounds(cls, values):
        """Read min_amount/max_amount from the model and format as display
        strings using the row's own jurisdiction_country — was hardcoded to
        ₹/Indian digit-grouping regardless of which country the slab actually
        belongs to."""
        if not isinstance(values, dict):
            values = dict(getattr(values, "__dict__", {}))
        raw_min = values.get("min_amount")
        raw_max = values.get("max_amount")
        country = (values.get("jurisdiction_country") or "IN").upper()
        symbol = cls._CURRENCY_SYMBOLS.get(country, "$")

        def _fmt(val):
            if val is None:
                return "Above"
            d = Decimal(str(val))
            if d == Decimal("0"):
                return f"{symbol}0"
            sign = "-" if d < 0 else ""
            d = abs(d)
            s = f"{d:,.0f}"
            if country == "IN":
                # Indian numbering: group last 3, then groups of 2
                parts = s.split(",")
                if len(parts) > 2:
                    # Convert Western grouping (3,3,3) to Indian (3,2,2)
                    last3 = parts[-1]
                    rest = parts[:-1]
                    groups = []
                    while rest:
                        groups.insert(0, rest.pop())
                    if groups:
                        first = groups[0]
                        rest = groups[1:]
                        formatted = first
                        for g in rest:
                            formatted += "," + g
                        formatted += "," + last3
                    else:
                        formatted = last3
                else:
                    formatted = ",".join(parts)
            else:
                formatted = s
            return f"{symbol}{sign}{formatted}"

        if raw_min is not None:
            values["min"] = _fmt(raw_min) if isinstance(raw_min, (int, float, str)) else _fmt(raw_min)
        if raw_max is not None:
            values["max"] = _fmt(raw_max) if isinstance(raw_max, (int, float, str)) else _fmt(raw_max)
        else:
            values["max"] = "Above"
        return values


# ── Compliance: Apply Extracted Rate ────────────────────────────────────
# Backs the "Apply" button added to ComplianceDocuments.jsx's extracted-rate
# preview. `row` intentionally accepts whatever shape the frontend already
# renders (label/employee/employer/total for rates; min/max/rate/tax for
# slabs) rather than a stricter schema, since it's echoing back exactly
# what ComplianceDocumentUpload displayed to the user before they clicked
# Apply — see service.apply_extracted_rate for how each kind is mapped
# onto ContributionRate / TaxSlab.

class ApplyExtractedRateRequest(BaseModel):
    documentId: str
    kind: str  # "contributionRate" | "taxSlab"
    row: dict
    countryCode: str = "IN"


class ApplyExtractedRateResponse(BaseModel):
    applied: bool
    componentKey: Optional[str] = None
    message: str = ""


# ── Compliance: Jurisdiction Pack ────────────────────────────────────────

class JurisdictionPackResponse(BaseModel):
    id:                  int
    packId:              str = Field(validation_alias="pack_id", serialization_alias="packId")
    jurisdictionCountry: str = Field(validation_alias="jurisdiction_country", serialization_alias="jurisdictionCountry")
    jurisdictionState:   Optional[str] = Field(None, validation_alias="jurisdiction_state", serialization_alias="jurisdictionState")
    jurisdictionLocality: Optional[str] = Field(None, validation_alias="jurisdiction_locality", serialization_alias="jurisdictionLocality")
    packType:            str = Field("policy", validation_alias="pack_type", serialization_alias="packType")
    version:             str
    status:              str
    effectiveFrom:       Optional[date] = Field(None, validation_alias="effective_from", serialization_alias="effectiveFrom")
    effectiveTo:         Optional[date] = Field(None, validation_alias="effective_to", serialization_alias="effectiveTo")
    complianceOwner:     Optional[str] = Field(None, validation_alias="compliance_owner", serialization_alias="complianceOwner")
    engineeringOwner:    Optional[str] = Field(None, validation_alias="engineering_owner", serialization_alias="engineeringOwner")
    sourceReferences:    Optional[str] = Field(None, validation_alias="source_references", serialization_alias="sourceReferences")
    regulatoryAuthority: Optional[str] = Field(None, validation_alias="regulatory_authority", serialization_alias="regulatoryAuthority")
    complianceCategory:  Optional[str] = Field(None, validation_alias="compliance_category", serialization_alias="complianceCategory")
    changeSummary:       Optional[str] = Field(None, validation_alias="change_summary", serialization_alias="changeSummary")
    nextReviewDate:      Optional[date] = Field(None, validation_alias="next_review_date", serialization_alias="nextReviewDate")
    policyDefaults:      Optional[dict] = Field(None, validation_alias="policy_defaults", serialization_alias="policyDefaults")
    taxYear:             Optional[str] = Field(None, validation_alias="tax_year", serialization_alias="taxYear")
    taxRegime:           Optional[str] = Field(None, validation_alias="tax_regime", serialization_alias="taxRegime")
    defaultTaxRegime:    Optional[str] = Field(None, validation_alias="default_tax_regime", serialization_alias="defaultTaxRegime")
    approvedById:        Optional[int] = Field(None, validation_alias="approved_by_id", serialization_alias="approvedById")
    currency:            Optional[str] = None
    # §2 SOURCE LOCK ("a published rule version cannot be approved without
    # at least one authoritative source record") — the column has existed
    # since JurisdictionPack was first built (read by set_jurisdiction_
    # pack_status's US-only gate), but was never exposed on either the
    # read or write schema for ANY country until found via AU's own
    # production-readiness pass, 2026-09-17: every pack on the platform
    # had sourceDocumentId silently un-settable through the API.
    sourceDocumentId:    Optional[int] = Field(None, validation_alias="source_document_id", serialization_alias="sourceDocumentId")
    createdById:         Optional[int] = Field(None, validation_alias="created_by_id", serialization_alias="createdById")
    updatedById:         Optional[int] = Field(None, validation_alias="updated_by_id", serialization_alias="updatedById")
    previousVersionId:   Optional[int] = Field(None, validation_alias="previous_version_id", serialization_alias="previousVersionId")
    createdAt:           Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")
    updatedAt:           Optional[datetime] = Field(None, validation_alias="updated_at", serialization_alias="updatedAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Super Admin UI completion (§19 gap-closure Part 11, 2026-09-09) ─────
# Automated Impact Preview, Emergency Hotfix Mode, RTI & Forms summary,
# Test Certification.

class PackImpactOrganizationEntry(BaseModel):
    id: int
    organizationName: str
    organizationCode: str
    optedIntoCanonicalTracking: bool
    activeEmployeeCount: int
    unfinalizedRunCount: int


class JurisdictionPackImpactPreviewResponse(BaseModel):
    packRowId: int
    packId: str
    packVersion: str
    packType: str
    organizations: List[PackImpactOrganizationEntry]
    totalOrganizationsEligible: int
    totalOrganizationsGenuinelyAffected: int
    totalActiveEmployeesAffected: int
    totalUnfinalizedRunsAffected: int


class JurisdictionPackDiffResponse(BaseModel):
    fromPackRowId: int
    fromVersion: str
    toPackRowId: int
    toVersion: str
    contributionRates: dict
    taxSlabs: dict


class PackHotfixActivateRequest(BaseModel):
    incident_id: str
    justification: str


class PackHotfixReviewRequest(BaseModel):
    review_notes: str


class PackHotfixActivationResponse(BaseModel):
    id: int
    jurisdictionPackId: int = Field(..., validation_alias="jurisdiction_pack_id", serialization_alias="jurisdictionPackId")
    incidentId:        str = Field(..., validation_alias="incident_id", serialization_alias="incidentId")
    justification:      str
    activatedById:      Optional[int] = Field(None, validation_alias="activated_by_id", serialization_alias="activatedById")
    activatedAt:        Optional[datetime] = Field(None, validation_alias="activated_at", serialization_alias="activatedAt")
    reviewed:           bool
    reviewedById:       Optional[int] = Field(None, validation_alias="reviewed_by_id", serialization_alias="reviewedById")
    reviewedAt:         Optional[datetime] = Field(None, validation_alias="reviewed_at", serialization_alias="reviewedAt")
    reviewNotes:        Optional[str] = Field(None, validation_alias="review_notes", serialization_alias="reviewNotes")
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class RtiSubmissionEntry(BaseModel):
    id: int
    status: str
    hmrcCorrelationId: Optional[str] = None
    submittedAt: Optional[datetime] = None


class RtiFormsSummaryEntry(BaseModel):
    generatedReportId: int
    organizationId: int
    reportType: str
    templateVersion: str
    reportingYear: str
    reportingPeriod: Optional[str] = None
    status: str
    generatedAt: Optional[datetime] = None
    reconciliationStatus: Optional[str] = None
    submissions: List[RtiSubmissionEntry] = []


class TestCertificationRunRequest(BaseModel):
    jurisdiction_country: str = "UK"


class TestCertificationRunResponse(BaseModel):
    id: int
    runAt: Optional[datetime] = Field(None, validation_alias="run_at", serialization_alias="runAt")
    triggeredById: Optional[int] = Field(None, validation_alias="triggered_by_id", serialization_alias="triggeredById")
    jurisdictionCountry: str = Field("UK", validation_alias="jurisdiction_country", serialization_alias="jurisdictionCountry")
    realCaseCount: int = Field(0, validation_alias="real_case_count", serialization_alias="realCaseCount")
    totalCases: int = Field(0, validation_alias="total_cases", serialization_alias="totalCases")
    passedCases: int = Field(0, validation_alias="passed_cases", serialization_alias="passedCases")
    failedCases: int = Field(0, validation_alias="failed_cases", serialization_alias="failedCases")
    status: str
    failureDetails: Optional[list] = Field(None, validation_alias="failure_details", serialization_alias="failureDetails")
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class JurisdictionPackUpsert(BaseModel):
    # When editing an existing pack in place (not creating a new one, not a
    # new version), the caller passes the row's real database id so the
    # lookup below is by primary key rather than by (packId, version) —
    # the only way packId itself can be safely renamed without orphaning
    # the row's history or its linked canonical rate/slab/audit rows
    # (all of which reference jurisdiction_pack_id, the integer id, never
    # the packId string).
    id: Optional[int] = None
    packId: str
    jurisdictionCountry: str
    jurisdictionState: Optional[str] = None
    jurisdictionLocality: Optional[str] = None
    packType: str = "policy"
    version: str = "1.0"
    status: str = "Draft"
    effectiveFrom: Optional[date] = None
    effectiveTo: Optional[date] = None
    complianceOwner: Optional[str] = None
    engineeringOwner: Optional[str] = None
    sourceReferences: Optional[str] = None
    regulatoryAuthority: Optional[str] = None
    complianceCategory: Optional[str] = None
    changeSummary: Optional[str] = None
    nextReviewDate: Optional[date] = None
    policyDefaults: Optional[dict] = None
    taxYear: Optional[str] = None
    taxRegime: Optional[str] = None
    defaultTaxRegime: Optional[str] = None
    approvedById: Optional[int] = None
    currency: Optional[str] = None
    # §2 SOURCE LOCK — see JurisdictionPackResponse's matching field
    # docstring for why this was missing platform-wide until 2026-09-17.
    sourceDocumentId: Optional[int] = None
    # Free-text "why" for this specific edit — persisted onto the audit
    # row (TaxConfigurationAudit.reason already exists and is already
    # read by the Compliance UI's Audit tab; no form ever offered it
    # until now).
    reason: Optional[str] = None


# ── Report Templates (jurisdiction-wide; Super Admin-authored) ───────────

class ReportTemplateFieldResponse(BaseModel):
    id:             int
    componentId:    int = Field(validation_alias="component_id", serialization_alias="componentId")
    fieldKey:       str = Field(validation_alias="field_key", serialization_alias="fieldKey")
    label:          str
    fieldType:      str = Field(validation_alias="field_type", serialization_alias="fieldType")
    dataSourceKind: str = Field(validation_alias="data_source_kind", serialization_alias="dataSourceKind")
    sourceColumn:   str = Field(validation_alias="source_column", serialization_alias="sourceColumn")
    aggregation:    Optional[str] = None
    enumValues:     Optional[list] = Field(None, validation_alias="enum_values", serialization_alias="enumValues")
    formatHint:     Optional[str] = Field(None, validation_alias="format_hint", serialization_alias="formatHint")
    isRequired:     bool = Field(False, validation_alias="is_required", serialization_alias="isRequired")
    sortOrder:      int = Field(0, validation_alias="sort_order", serialization_alias="sortOrder")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ReportTemplateFieldUpsert(BaseModel):
    id: Optional[int] = None
    fieldKey: str
    label: str
    fieldType: str
    dataSourceKind: str
    sourceColumn: str
    aggregation: Optional[str] = None
    enumValues: Optional[list] = None
    formatHint: Optional[str] = None
    isRequired: bool = False
    sortOrder: int = 0


class ReportTemplateComponentResponse(BaseModel):
    id:                int
    reportTemplateId:  int = Field(validation_alias="report_template_id", serialization_alias="reportTemplateId")
    componentKey:      str = Field(validation_alias="component_key", serialization_alias="componentKey")
    label:             str
    componentCategory: str = Field("standard", validation_alias="component_category", serialization_alias="componentCategory")
    sortOrder:         int = Field(0, validation_alias="sort_order", serialization_alias="sortOrder")
    fields:            List[ReportTemplateFieldResponse] = []

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ReportTemplateComponentUpsert(BaseModel):
    id: Optional[int] = None
    componentKey: str
    label: str
    componentCategory: str = "standard"
    sortOrder: int = 0


class ReportTemplateResponse(BaseModel):
    id:                  int
    templateKey:         str = Field(validation_alias="template_key", serialization_alias="templateKey")
    name:                str
    reportType:          str = Field(validation_alias="report_type", serialization_alias="reportType")
    jurisdictionCountry: str = Field(validation_alias="jurisdiction_country", serialization_alias="jurisdictionCountry")
    jurisdictionState:   Optional[str] = Field(None, validation_alias="jurisdiction_state", serialization_alias="jurisdictionState")
    jurisdictionLocality: Optional[str] = Field(None, validation_alias="jurisdiction_locality", serialization_alias="jurisdictionLocality")
    reportingYear:       str = Field(validation_alias="reporting_year", serialization_alias="reportingYear")
    version:             str
    status:              str
    description:         Optional[str] = None
    regulatoryAuthority: Optional[str] = Field(None, validation_alias="regulatory_authority", serialization_alias="regulatoryAuthority")
    effectiveFrom:       Optional[date] = Field(None, validation_alias="effective_from", serialization_alias="effectiveFrom")
    effectiveTo:         Optional[date] = Field(None, validation_alias="effective_to", serialization_alias="effectiveTo")
    changeSummary:       Optional[str] = Field(None, validation_alias="change_summary", serialization_alias="changeSummary")
    sourceReferences:    Optional[str] = Field(None, validation_alias="source_references", serialization_alias="sourceReferences")
    documentScope:       str = Field("AGGREGATE", validation_alias="document_scope", serialization_alias="documentScope")
    sourceDocumentId:    Optional[int] = Field(None, validation_alias="source_document_id", serialization_alias="sourceDocumentId")
    reconciliationTolerance: Optional[float] = Field(None, validation_alias="reconciliation_tolerance", serialization_alias="reconciliationTolerance")
    approvedById:        Optional[int] = Field(None, validation_alias="approved_by_id", serialization_alias="approvedById")
    createdById:         Optional[int] = Field(None, validation_alias="created_by_id", serialization_alias="createdById")
    updatedById:         Optional[int] = Field(None, validation_alias="updated_by_id", serialization_alias="updatedById")
    previousVersionId:   Optional[int] = Field(None, validation_alias="previous_version_id", serialization_alias="previousVersionId")
    createdAt:           Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")
    updatedAt:           Optional[datetime] = Field(None, validation_alias="updated_at", serialization_alias="updatedAt")
    components:          List[ReportTemplateComponentResponse] = []

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ReportTemplateUpsert(BaseModel):
    id: Optional[int] = None
    templateKey: str
    name: str
    reportType: str
    jurisdictionCountry: str
    jurisdictionState: Optional[str] = None
    jurisdictionLocality: Optional[str] = None
    reportingYear: str
    version: str = "1.0"
    status: str = "Draft"
    description: Optional[str] = None
    regulatoryAuthority: Optional[str] = None
    effectiveFrom: Optional[date] = None
    effectiveTo: Optional[date] = None
    changeSummary: Optional[str] = None
    sourceReferences: Optional[str] = None
    documentScope: str = "AGGREGATE"
    sourceDocumentId: Optional[int] = None
    reconciliationTolerance: Optional[float] = None
    approvedById: Optional[int] = None
    reason: Optional[str] = None


class ReportTemplateStatusUpdate(BaseModel):
    status: str
    reason: Optional[str] = Field(None, max_length=1000)   # recorded in the audit trail (Phase 5.8)


# ── Statutory Filing Calendar (jurisdiction-wide; Super Admin-authored) ──

class FilingCalendarResponse(BaseModel):
    id:                  int
    jurisdictionCountry: str = Field(validation_alias="jurisdiction_country", serialization_alias="jurisdictionCountry")
    jurisdictionState:   Optional[str] = Field(None, validation_alias="jurisdiction_state", serialization_alias="jurisdictionState")
    reportType:          str = Field(validation_alias="report_type", serialization_alias="reportType")
    reportingYear:       str = Field(validation_alias="reporting_year", serialization_alias="reportingYear")
    periodKey:           str = Field(validation_alias="period_key", serialization_alias="periodKey")
    periodLabel:         str = Field(validation_alias="period_label", serialization_alias="periodLabel")
    dueDate:             date = Field(validation_alias="due_date", serialization_alias="dueDate")
    # ZP-SE-ENG-001 §10/§27 — Sweden AGI's separate payment due date + the
    # filing variation (e.g. LARGE_VAT_FILER) that produced these dates.
    # NULL on every pre-existing row (see models.py's docstring).
    paymentDueDate:      Optional[date] = Field(None, validation_alias="payment_due_date", serialization_alias="paymentDueDate")
    variation:           Optional[str] = Field(None, validation_alias="variation", serialization_alias="variation")
    status:              str
    sourceDocumentId:    Optional[int] = Field(None, validation_alias="source_document_id", serialization_alias="sourceDocumentId")
    previousVersionId:   Optional[int] = Field(None, validation_alias="previous_version_id", serialization_alias="previousVersionId")
    approvedById:        Optional[int] = Field(None, validation_alias="approved_by_id", serialization_alias="approvedById")
    createdAt:           Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")
    updatedAt:           Optional[datetime] = Field(None, validation_alias="updated_at", serialization_alias="updatedAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class FilingCalendarUpsert(BaseModel):
    id: Optional[int] = None
    jurisdictionCountry: str
    jurisdictionState: Optional[str] = None
    reportType: str
    reportingYear: str
    periodKey: str
    periodLabel: str
    dueDate: date
    # See FilingCalendarResponse — Sweden AGI §10/§27; optional so every
    # existing country's upsert payload behaves exactly as before.
    paymentDueDate: Optional[date] = None
    variation: Optional[str] = None
    status: str = "Draft"
    sourceDocumentId: Optional[int] = None
    reason: Optional[str] = None


class FilingCalendarStatusUpdate(BaseModel):
    status: str


# ── Statutory Filing (per-org filing-status tracker) ───────────────────────
# The persisted "did we actually file it" record behind the Super Admin
# Filings & Remittances dashboard (command_center_router.py) and any org-facing
# compliance recording UI. One row per (org, jurisdiction, filing type, period).

class StatutoryFilingResponse(BaseModel):
    id:                 int
    organizationId:     int = Field(serialization_alias="organizationId")
    organizationName:   Optional[str] = Field(None, serialization_alias="organizationName")
    jurisdiction:       str
    filingType:         str = Field(serialization_alias="filingType")
    periodLabel:        str = Field(serialization_alias="periodLabel")
    periodStart:        Optional[date] = Field(None, serialization_alias="periodStart")
    periodEnd:          Optional[date] = Field(None, serialization_alias="periodEnd")
    status:             str
    blockedReason:      Optional[str] = Field(None, serialization_alias="blockedReason")
    submittedAt:        Optional[datetime] = Field(None, serialization_alias="submittedAt")
    # ── AGI reporting linkage (ZP-SE-ENG-001 §10/§26) ──────────────────────
    # Generic/nullable — NULL on every pre-existing filing row. AGI's own
    # state machine lives in submissionStatus so the shared `status`
    # vocabulary (NOT_STARTED/IN_PROGRESS/FILED/...) keeps its exact current
    # semantics for the Filings & Remittances dashboard.
    submissionStatus:     Optional[str] = Field(None, serialization_alias="submissionStatus")
    receiptId:            Optional[str] = Field(None, serialization_alias="receiptId")
    correctionReference:  Optional[str] = Field(None, serialization_alias="correctionReference")
    schemaVersion:        Optional[str] = Field(None, serialization_alias="schemaVersion")
    validationStatus:     Optional[str] = Field(None, serialization_alias="validationStatus")
    createdAt:          Optional[datetime] = Field(None, serialization_alias="createdAt")
    updatedAt:          Optional[datetime] = Field(None, serialization_alias="updatedAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class StatutoryFilingUpsert(BaseModel):
    filingType:   str
    periodLabel:  str
    periodStart:  Optional[date] = None
    periodEnd:    Optional[date] = None
    status:       str = "NOT_STARTED"
    blockedReason: Optional[str] = None
    submittedAt:  Optional[datetime] = None
    # See StatutoryFilingResponse — AGI §10/§26, optional/None everywhere else.
    submissionStatus: Optional[str] = None
    receiptId: Optional[str] = None
    correctionReference: Optional[str] = None
    schemaVersion: Optional[str] = None
    validationStatus: Optional[str] = None


class AvailableComponentItem(BaseModel):
    key: str
    label: str


class AvailableDataFieldItem(BaseModel):
    key: str
    label: str
    dataSourceKind: str
    sourceColumn: str
    fieldType: str
    aggregatable: bool = False


class ReportGenerationValidation(BaseModel):
    jurisdictionMatch: bool
    runFinalized: bool
    periodMatch: bool
    templatePublished: bool
    reasons: List[str] = []

    @property
    def passed(self) -> bool:
        return self.jurisdictionMatch and self.runFinalized and self.periodMatch and self.templatePublished


class ApplicableTemplateResponse(BaseModel):
    template: Optional[ReportTemplateResponse] = None
    validation: Optional[ReportGenerationValidation] = None


class GenerateReportRequest(BaseModel):
    reportTemplateId: int
    payrollRunId: int
    reportingPeriod: Optional[str] = None


class GeneratedReportResponse(BaseModel):
    id:                  int
    organizationId:       int = Field(validation_alias="organization_id", serialization_alias="organizationId")
    reportTemplateId:     int = Field(validation_alias="report_template_id", serialization_alias="reportTemplateId")
    templateVersion:      str = Field(validation_alias="template_version", serialization_alias="templateVersion")
    reportType:           str = Field(validation_alias="report_type", serialization_alias="reportType")
    documentScope:        str = Field("AGGREGATE", validation_alias="document_scope", serialization_alias="documentScope")
    # Nullable since ZP-TAX-UK-2026-27-001 §18 gap-closure Part 9
    # (2026-09-09) — a P45/P60/EPS report isn't tied to any PayrollRun
    # (see GeneratedReport.payroll_run_id's own model comment).
    payrollRunId:          Optional[int] = Field(None, validation_alias="payroll_run_id", serialization_alias="payrollRunId")
    employeeId:            Optional[int] = Field(None, validation_alias="employee_id", serialization_alias="employeeId")
    scopeKey:              Optional[str] = Field(None, validation_alias="scope_key", serialization_alias="scopeKey")
    jurisdictionCountry:  str = Field(validation_alias="jurisdiction_country", serialization_alias="jurisdictionCountry")
    jurisdictionState:    Optional[str] = Field(None, validation_alias="jurisdiction_state", serialization_alias="jurisdictionState")
    reportingYear:        str = Field(validation_alias="reporting_year", serialization_alias="reportingYear")
    reportingPeriod:      Optional[str] = Field(None, validation_alias="reporting_period", serialization_alias="reportingPeriod")
    applicableTaxPackId:  Optional[int] = Field(None, validation_alias="applicable_tax_pack_id", serialization_alias="applicableTaxPackId")
    applicableTaxPackVersion: Optional[str] = Field(None, validation_alias="applicable_tax_pack_version", serialization_alias="applicableTaxPackVersion")
    status:               str
    generatedById:         Optional[int] = Field(None, validation_alias="generated_by_id", serialization_alias="generatedById")
    generatedAt:           Optional[datetime] = Field(None, validation_alias="generated_at", serialization_alias="generatedAt")
    renderedData:          dict = Field(validation_alias="rendered_data", serialization_alias="renderedData")
    reconciliation:        Optional[dict] = None
    notes:                 Optional[str] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class VoidGeneratedReportRequest(BaseModel):
    reason: str


# ── UK RTI: P45/P60 + EPS generation, submission tracking ────────────────
# (ZP-TAX-UK-2026-27-001 §18 gap-closure Part 9, 2026-09-09).

class UKEmployeeReportGenerateRequest(BaseModel):
    report_template_id: int
    employee_id: int
    as_of_date: date  # leaving date for a P45, tax-year-end date for a P60


class UKEpsGenerateRequest(BaseModel):
    report_template_id: int
    tax_year: str
    period_key: str
    employer_has_claimed_allowance: bool = False
    no_employees_paid: bool = False
    final_submission: bool = False
    # The employer's own declared SMP/SPP/SAP/ShPP/SPBP/SNCP recovery
    # total for this period (§11.1) — computed via the Statutory Pay
    # Calculator (Part 5/7), then supplied here as a filing declaration.
    total_statutory_pay_recovered: Optional[Decimal] = None
    as_of: Optional[date] = None


class IndiaForm138GenerateRequest(BaseModel):
    report_template_id: int
    reporting_year: str  # e.g. "2026-27" — India's FY
    period_key: str      # "Q1" | "Q2" | "Q3" | "Q4"


class IndiaForm123GenerateRequest(BaseModel):
    report_template_id: int
    employee_id: int
    tax_year: str  # e.g. "2026-27"


class AUSuperstreamGenerateRequest(BaseModel):
    report_template_id: int
    payroll_run_id: int


class AUPayrollTaxReturnGenerateRequest(BaseModel):
    report_template_id: int
    work_state: str  # "NSW" | "VIC" | "QLD" | "WA" | "SA" | "TAS" | "ACT" | "NT"
    period_start: date
    period_end: date


# ── US: Form W-2 (Production-Readiness Plan Phase 5) ────────────────────
class USW2GenerateRequest(BaseModel):
    report_template_id: int
    employee_id: int
    tax_year: str  # e.g. "2026" — a plain calendar year, unlike India's "2026-27"


# ── US: Form 941/940 (Production-Readiness Plan Phase 5) ────────────────
class USForm941GenerateRequest(BaseModel):
    report_template_id: int
    year: int
    quarter: int  # 1-4, standard IRS calendar quarter


class USForm940GenerateRequest(BaseModel):
    report_template_id: int
    year: int


# ── Hong Kong: IRD returns / notifications, eMPF remittance, MPF record
# (ZP-HK-ENG-001 §7, §5, HK-011, HK-010) ─────────────────────────────────
# A Hong Kong year of assessment is "YYYY/YY" and ends 31 March — never a
# calendar year and never a dash, unlike India's "2026-27". A contribution
# period is a plain calendar month, because MPF is contributed monthly.

class HongKongBir56aGenerateRequest(BaseModel):
    report_template_id: int
    year_of_assessment: str  # e.g. "2025/26"


class HongKongIr56bGenerateRequest(BaseModel):
    report_template_id: int
    employee_id: int
    year_of_assessment: str  # e.g. "2025/26"


class HongKongIr56NotificationGenerateRequest(BaseModel):
    report_template_id: int
    case_id: int  # the IR56E / IR56F / IR56G reporting case, which is the source of truth


class HongKongEmpfRemittanceGenerateRequest(BaseModel):
    report_template_id: int
    submission_id: int


class HongKongMpfContributionRecordGenerateRequest(BaseModel):
    report_template_id: int
    employee_id: int
    contribution_period: str  # e.g. "2026-05" — a calendar month


class HongKongTerminationStatementGenerateRequest(BaseModel):
    report_template_id: int
    termination_result_id: int


# ── US: New Hire Reporting (Production-Readiness Plan Phase 5) ──────────
# The one genuinely new concept in this phase — compliance TRACKING, not
# report generation against already-run payroll. See NewHireReport's own
# model docstring for the full "due_date is a suggestion, not a legal
# deadline" reasoning.
class NewHireReportCreate(BaseModel):
    employeeId: int
    hireDate: Optional[date] = None   # defaults to the employee's own date_of_joining, or today
    workState: Optional[str] = None   # defaults to the employee's own work_state
    dueDateDays: Optional[int] = None  # defaults to the platform's 20-day suggestion


class NewHireReportMarkFiledRequest(BaseModel):
    filedDate: Optional[date] = None  # defaults to today
    notes: Optional[str] = None


class NewHireReportResponse(BaseModel):
    id: int
    organizationId: int = Field(validation_alias="organization_id", serialization_alias="organizationId")
    employeeId: int = Field(validation_alias="employee_id", serialization_alias="employeeId")
    employeeName: Optional[str] = None
    workState: Optional[str] = Field(None, validation_alias="work_state", serialization_alias="workState")
    hireDate: date = Field(validation_alias="hire_date", serialization_alias="hireDate")
    dueDate: date = Field(validation_alias="due_date", serialization_alias="dueDate")
    status: str
    filedDate: Optional[date] = Field(None, validation_alias="filed_date", serialization_alias="filedDate")
    filedById: Optional[int] = Field(None, validation_alias="filed_by_id", serialization_alias="filedById")
    notes: Optional[str] = None
    createdAt: Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Canada: T4/RL-1/ROE (per-employee) + PD7A (per-period) generation ───
# (ZP-TAX-CA-2026-001 gap-closure, forms/reports phase). T4/RL-1/ROE reuse
# UKEmployeeReportGenerateRequest as-is (report_template_id/employee_id/
# as_of_date) — see service.generate_uk_employee_report's own docstring
# for why that function was never actually UK-specific. PD7A is genuinely
# period-based across possibly several PayrollRuns (like India's Form
# 138), but CRA remittance periods are monthly/quarterly/threshold-based
# rather than a fixed FY-quarter scheme, so it takes an explicit date
# range instead of a reporting_year/period_key pair.
class CAPd7aGenerateRequest(BaseModel):
    report_template_id: int
    period_start: date
    period_end: date


class GYMonthlyReportGenerateRequest(BaseModel):
    report_template_id: int
    year: int
    month: int  # 1-12


class JMAnnualReportGenerateRequest(BaseModel):
    report_template_id: int
    year: int


class SGAnnualReportGenerateRequest(BaseModel):
    """Singapore IR8A annual data extract — one calendar (income) year."""
    report_template_id: int
    year: int


class SGIr21CaseCreateRequest(BaseModel):
    """Open a Singapore IR21 tax-clearance case (withholding starts at awareDate)."""
    model_config = ConfigDict(populate_by_name=True)
    employee_id: int = Field(validation_alias="employeeId")
    trigger_type: str = Field(validation_alias="triggerType")      # CESSATION | OVERSEAS_POSTING | DEPARTURE
    trigger_date: date = Field(validation_alias="triggerDate")
    aware_date: date = Field(validation_alias="awareDate")


class SGIr21CaseTransitionRequest(BaseModel):
    """One IR21 lifecycle step — the fields each target status needs."""
    model_config = ConfigDict(populate_by_name=True)
    status: str
    filed_date: Optional[date] = Field(None, validation_alias="filedDate")
    filing_reference: Optional[str] = Field(None, validation_alias="filingReference", max_length=100)
    directive_date: Optional[date] = Field(None, validation_alias="directiveDate")
    directive_reference: Optional[str] = Field(None, validation_alias="directiveReference", max_length=100)
    directive_tax_amount: Optional[Decimal] = Field(None, validation_alias="directiveTaxAmount")
    exemption_category: Optional[str] = Field(None, validation_alias="exemptionCategory")
    reason: Optional[str] = None


class SGSalaryDeductionCreate(BaseModel):
    """A Singapore Employment Act salary deduction (MOM category + evidence)."""
    model_config = ConfigDict(populate_by_name=True)
    category: str
    start_date: date = Field(validation_alias="startDate")
    end_date: Optional[date] = Field(None, validation_alias="endDate")
    evidence_ref: str = Field(validation_alias="evidenceRef", max_length=100)
    evidence_date: date = Field(validation_alias="evidenceDate")
    amount: Optional[Decimal] = None
    rate_pct: Optional[Decimal] = Field(None, validation_alias="ratePct")
    total_to_collect: Optional[Decimal] = Field(None, validation_alias="totalToCollect")
    priority: Optional[int] = None


class SGCorrectionRequest(BaseModel):
    """Append-only correction of a finalized Singapore payslip (SG-044)."""
    reason: str = Field(min_length=3, max_length=500)


class SGRestoreFreezeRequest(BaseModel):
    """SG-047 disaster-recovery freeze of external submissions."""
    model_config = ConfigDict(populate_by_name=True)
    restore_point: str = Field(validation_alias="restorePoint", min_length=3, max_length=200)
    # Optional: only SG runs paid on / after this date are put on a bank-export hold.
    restore_date: Optional[date] = Field(None, validation_alias="restoreDate")


class SGBankHoldReleaseRequest(BaseModel):
    """SG-047: the bank reconciliation that releases a post-restore bank-export hold."""
    model_config = ConfigDict(populate_by_name=True)
    reference: str = Field(min_length=3, max_length=100)


class SGCessationRequest(BaseModel):
    """Singapore termination — the last day of employment."""
    model_config = ConfigDict(populate_by_name=True)
    date_of_leaving: date = Field(validation_alias="dateOfLeaving")


class SGCpfEzpayGenerateRequest(BaseModel):
    """Prepare the CPF EZPay contribution file for one CPF wage month."""
    model_config = ConfigDict(populate_by_name=True)
    report_template_id: int = Field(validation_alias="reportTemplateId")
    year: int
    month: int  # 1-12
    advice_code: str = Field("01", validation_alias="adviceCode", pattern=r"^(0[1-9]|[1-9]\d)$")


class SGCpfEzpayTransitionRequest(BaseModel):
    """One CPF EZPay lifecycle step (APPROVED / SUBMITTED / ACCEPTED / REJECTED / UNKNOWN)."""
    model_config = ConfigDict(populate_by_name=True)
    status: str
    reference: Optional[str] = Field(None, max_length=100)
    note: Optional[str] = Field(None, max_length=1000)
    # The authority's own validation / rejection messages, recorded verbatim
    # with a REJECTED / UNKNOWN outcome (IR8A: IRAS; EZPay: CPF Board).
    errors: Optional[List[str]] = None


class SGIr8aModificationCreateRequest(BaseModel):
    """Phase 6.8 (G3): revise or amend an IRAS-acknowledged IR8A extract.
    `method` is REVISION or AMENDMENT (validated, and refusals audited, by
    service.create_sg_ir8a_modification)."""
    model_config = ConfigDict(populate_by_name=True)
    method: str = Field(..., max_length=12)
    reason: Optional[str] = Field(None, max_length=1000)


class SingaporeCalculationPreviewRequest(BaseModel):
    """Read-only Super Admin preview of a Singapore calculation against ONE
    selected pack's canonical rows (any status — so Draft content can be
    tested before approval). Every statutory value is resolved server-side
    from that pack; the request carries only employee facts and wages,
    never a rate. Nothing is persisted."""
    jurisdictionPackId: int
    payDate: date
    gross: Decimal
    additionalWages: Decimal = Decimal("0")
    residencyStatus: Optional[str] = None           # SC | SPR | FOREIGN
    sprEffectiveDate: Optional[date] = None
    contributionArrangement: Optional[str] = None   # GG | FG | FF
    workPass: Optional[str] = None                  # NONE | EP | S_PASS | WORK_PERMIT
    shgFunds: Optional[str] = None                  # NONE | CDAC | "MBMF,SINDA" ...
    dateOfBirth: Optional[date] = None
    dateOfJoining: Optional[date] = None
    dateOfLeaving: Optional[date] = None
    employmentType: Optional[str] = None            # Full-time | Part-time
    employerHiresForeignWorkers: Optional[bool] = None
    ytdOwSubjectBefore: Optional[Decimal] = None
    ytdAwSubjectBefore: Optional[Decimal] = None
    ytdAwPaidBefore: Optional[Decimal] = None
    awLedger: Optional[List[dict]] = None


class RtiSubmissionCreate(BaseModel):
    generated_report_id: int


class RtiSubmissionStatusUpdate(BaseModel):
    status: str  # DRAFT | READY | SUBMITTED | ACKNOWLEDGED | REJECTED
    hmrc_correlation_id: Optional[str] = None
    rejection_reason: Optional[str] = None


class RtiSubmissionResponse(BaseModel):
    id: int
    organizationId:       int = Field(..., validation_alias="organization_id", serialization_alias="organizationId")
    generatedReportId:    int = Field(..., validation_alias="generated_report_id", serialization_alias="generatedReportId")
    submissionType:       str = Field(..., validation_alias="submission_type", serialization_alias="submissionType")
    status:               str
    hmrcCorrelationId:    Optional[str] = Field(None, validation_alias="hmrc_correlation_id", serialization_alias="hmrcCorrelationId")
    submittedAt:          Optional[datetime] = Field(None, validation_alias="submitted_at", serialization_alias="submittedAt")
    acknowledgedAt:       Optional[datetime] = Field(None, validation_alias="acknowledged_at", serialization_alias="acknowledgedAt")
    rejectionReason:      Optional[str] = Field(None, validation_alias="rejection_reason", serialization_alias="rejectionReason")
    createdAt:            Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Canonical Tax Rates (Super Admin-owned; organization_id IS NULL) ─────

class CanonicalTaxSlabUpsert(BaseModel):
    id: Optional[int] = None
    jurisdictionPackId: int
    jurisdictionCountry: str
    jurisdictionState: Optional[str] = None
    jurisdictionLocality: Optional[str] = None
    taxRegime: Optional[str] = None
    # US-specific (NULL/unused by every other jurisdiction): "SINGLE" |
    # "MFJ" | "MFS" | "HOH" — see TaxSlab.filing_status.
    filingStatus: Optional[str] = None
    minAmount: Decimal
    maxAmount: Optional[Decimal] = None
    ratePct: Decimal
    rateLabel: str
    taxFormula: str = ""
    ruleType: str = "MARGINAL_RATE"
    formulaExpression: Optional[str] = None
    # Optional row-level dating inside the pack (e.g. France's 1 May 2026
    # PAS neutral grid). Only applied when the caller actually sends the
    # field, so an edit from a form that doesn't know about dates never
    # wipes a row's existing window.
    effectiveFrom: Optional[date] = None
    effectiveTo: Optional[date] = None
    # PT_FLAT only (India state-level Professional Tax, bracketed by gross
    # salary): a fixed monthly amount instead of a percentage, plus an
    # optional override for whichever month absorbs annual-cap rounding.
    flatAmount: Optional[Decimal] = None
    adjustmentAmount: Optional[Decimal] = None
    # PT_FLAT only (ZP-TAX-IN-2026-27-001 §12.1): which income figure this
    # bracket is measured against — NULL/"MONTHLY_WAGE" (every existing PT
    # state) unchanged; "HALF_YEAR_INCOME" for a local authority assessed
    # half-yearly (e.g. Chennai, §14.1).
    assessmentBasis: Optional[str] = None
    # NI_BAND only (UK National Insurance category bands): which HMRC
    # category letter this band belongs to, and the employer-side rate
    # for the band — ratePct above is always the EMPLOYEE rate. Both
    # already exist as TaxSlab columns; this is the first schema/UI path
    # that can actually set them (previously only reachable by a direct
    # DB write / test fixture).
    niCategory: Optional[str] = None
    employerRatePct: Optional[Decimal] = None
    # SE_TAX_TABLE / SE_ONE_TIME_PAYMENT only (ZP-SE-ENG-001 §7/§8/§10):
    # which Skatteverket tax table ("29".."42") and which tax column this
    # band belongs to. NULL for every other jurisdiction's rows; omitted
    # from a payload = existing value untouched (same convention as
    # effectiveFrom/effectiveTo above).
    taxTableNumber: Optional[str] = None
    taxColumn: Optional[str] = None
    sortOrder: int = 0
    reason: Optional[str] = None


class CanonicalContributionRateUpsert(BaseModel):
    id: Optional[int] = None
    jurisdictionPackId: int
    jurisdictionCountry: str
    jurisdictionState: Optional[str] = None
    jurisdictionLocality: Optional[str] = None
    taxRegime: Optional[str] = None
    # US-specific (NULL/unused by every other jurisdiction): "SINGLE" |
    # "MFJ" | "MFS" | "HOH" — see ContributionRate.filing_status.
    filingStatus: Optional[str] = None
    componentKey: str
    label: str
    employeeSharePct: Optional[Decimal] = None
    employerSharePct: Optional[Decimal] = None
    flatAmount: Optional[Decimal] = None
    textValue: Optional[str] = None
    sortOrder: int = 0
    reason: Optional[str] = None


class CanonicalTaxSlabResponse(BaseModel):
    id: int
    jurisdictionPackId: Optional[int] = Field(None, validation_alias="jurisdiction_pack_id", serialization_alias="jurisdictionPackId")
    jurisdictionCountry: str = Field(validation_alias="jurisdiction_country", serialization_alias="jurisdictionCountry")
    jurisdictionState: Optional[str] = Field(None, validation_alias="jurisdiction_state", serialization_alias="jurisdictionState")
    jurisdictionLocality: Optional[str] = Field(None, validation_alias="jurisdiction_locality", serialization_alias="jurisdictionLocality")
    taxRegime: Optional[str] = Field(None, validation_alias="tax_regime", serialization_alias="taxRegime")
    minAmount: Decimal = Field(validation_alias="min_amount", serialization_alias="minAmount")
    maxAmount: Optional[Decimal] = Field(None, validation_alias="max_amount", serialization_alias="maxAmount")
    ratePct: Decimal = Field(validation_alias="rate_pct", serialization_alias="ratePct")
    rateLabel: str = Field(validation_alias="rate_label", serialization_alias="rateLabel")
    taxFormula: str = Field("", validation_alias="tax_formula", serialization_alias="taxFormula")
    ruleType: str = Field("MARGINAL_RATE", validation_alias="rule_type", serialization_alias="ruleType")
    formulaExpression: Optional[str] = Field(None, validation_alias="formula_expression", serialization_alias="formulaExpression")
    flatAmount: Optional[Decimal] = Field(None, validation_alias="flat_amount", serialization_alias="flatAmount")
    adjustmentAmount: Optional[Decimal] = Field(None, validation_alias="adjustment_amount", serialization_alias="adjustmentAmount")
    assessmentBasis: Optional[str] = Field(None, validation_alias="assessment_basis", serialization_alias="assessmentBasis")
    niCategory: Optional[str] = Field(None, validation_alias="ni_category", serialization_alias="niCategory")
    employerRatePct: Optional[Decimal] = Field(None, validation_alias="employer_rate_pct", serialization_alias="employerRatePct")
    # Sweden (ZP-SE-ENG-001 §7/§8): tax table number + tax column, NULL on
    # every non-Swedish row (see CanonicalTaxSlabUpsert's own docstring).
    taxTableNumber: Optional[str] = Field(None, validation_alias="tax_table_number", serialization_alias="taxTableNumber")
    taxColumn: Optional[str] = Field(None, validation_alias="tax_column", serialization_alias="taxColumn")
    filingStatus: Optional[str] = Field(None, validation_alias="filing_status", serialization_alias="filingStatus")
    sortOrder: int = Field(0, validation_alias="sort_order", serialization_alias="sortOrder")
    # Row-level effective dating / per-row evidence (models.py
    # ContributionRate/TaxSlab.effective_from/effective_to/
    # source_document_id) — read-only, additive; NULL on every row that
    # doesn't set them. Exposed 2026-09-23 so Singapore's LQS 1 Jul 2026
    # boundary renders from data rather than a hardcoded UI date.
    effectiveFrom: Optional[date] = Field(None, validation_alias="effective_from", serialization_alias="effectiveFrom")
    effectiveTo: Optional[date] = Field(None, validation_alias="effective_to", serialization_alias="effectiveTo")
    sourceDocumentId: Optional[int] = Field(None, validation_alias="source_document_id", serialization_alias="sourceDocumentId")

    effectiveFrom: Optional[date] = Field(None, validation_alias="effective_from", serialization_alias="effectiveFrom")
    effectiveTo: Optional[date] = Field(None, validation_alias="effective_to", serialization_alias="effectiveTo")
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class CanonicalContributionRateResponse(BaseModel):
    id: int
    jurisdictionPackId: Optional[int] = Field(None, validation_alias="jurisdiction_pack_id", serialization_alias="jurisdictionPackId")
    jurisdictionCountry: str = Field(validation_alias="jurisdiction_country", serialization_alias="jurisdictionCountry")
    jurisdictionState: Optional[str] = Field(None, validation_alias="jurisdiction_state", serialization_alias="jurisdictionState")
    jurisdictionLocality: Optional[str] = Field(None, validation_alias="jurisdiction_locality", serialization_alias="jurisdictionLocality")
    taxRegime: Optional[str] = Field(None, validation_alias="tax_regime", serialization_alias="taxRegime")
    filingStatus: Optional[str] = Field(None, validation_alias="filing_status", serialization_alias="filingStatus")
    componentKey: str = Field(validation_alias="component_key", serialization_alias="componentKey")
    label: str
    employeeRatePct: Optional[Decimal] = Field(None, validation_alias="employee_rate_pct", serialization_alias="employeeRatePct")
    employerRatePct: Optional[Decimal] = Field(None, validation_alias="employer_rate_pct", serialization_alias="employerRatePct")
    flatAmount: Optional[Decimal] = Field(None, validation_alias="flat_amount", serialization_alias="flatAmount")
    textValue: Optional[str] = Field(None, validation_alias="text_value", serialization_alias="textValue")
    sortOrder: int = Field(0, validation_alias="sort_order", serialization_alias="sortOrder")
    # Row-level effective dating / per-row evidence (models.py
    # ContributionRate/TaxSlab.effective_from/effective_to/
    # source_document_id) — read-only, additive; NULL on every row that
    # doesn't set them. Exposed 2026-09-23 so Singapore's LQS 1 Jul 2026
    # boundary renders from data rather than a hardcoded UI date.
    effectiveFrom: Optional[date] = Field(None, validation_alias="effective_from", serialization_alias="effectiveFrom")
    effectiveTo: Optional[date] = Field(None, validation_alias="effective_to", serialization_alias="effectiveTo")
    sourceDocumentId: Optional[int] = Field(None, validation_alias="source_document_id", serialization_alias="sourceDocumentId")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ActiveTaxConfigurationResponse(BaseModel):
    """Read-only view of whichever tax pack is currently Active for a
    jurisdiction — powers the Statutory Rates page's "Platform Default
    Rates" summary. `pack` is None when no canonical tax pack has been
    configured for this jurisdiction yet (an expected state, not an
    error) — `rates`/`slabs` are then simply empty."""
    pack: Optional[JurisdictionPackResponse] = None
    rates: List[CanonicalContributionRateResponse] = Field(default_factory=list)
    slabs: List[CanonicalTaxSlabResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class TaxConfigurationAuditResponse(BaseModel):
    id: int
    actorId: Optional[int] = Field(None, validation_alias="actor_id", serialization_alias="actorId")
    action: str
    entityType: str = Field(validation_alias="entity_type", serialization_alias="entityType")
    entityId: int = Field(validation_alias="entity_id", serialization_alias="entityId")
    jurisdictionPackId: Optional[int] = Field(None, validation_alias="jurisdiction_pack_id", serialization_alias="jurisdictionPackId")
    taxVersion: Optional[str] = Field(None, validation_alias="tax_version", serialization_alias="taxVersion")
    legalReference: Optional[str] = Field(None, validation_alias="legal_reference", serialization_alias="legalReference")
    oldValue: Optional[dict] = Field(None, validation_alias="old_value", serialization_alias="oldValue")
    newValue: Optional[dict] = Field(None, validation_alias="new_value", serialization_alias="newValue")
    reason: Optional[str] = None
    createdAt: Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── US: Employer-Specific Tax Profile (SUI and similar) ──────────────────
# Tenant-specific, agency-assigned rates — deliberately a separate schema
# family from the canonical Contribution Rate/Tax Slab ones above (see
# EmployerTaxProfile's model docstring): a SUI rate is not a discretionary
# org policy choice, it's a statutory fact assigned by a government agency.

class EmployerTaxProfileUpsert(BaseModel):
    id: Optional[int] = None
    organizationId: int
    jurisdictionId: str          # "US-CA"
    componentCode: str = "SUI"   # "SUI" | "ETT" | "WF" | "JDA" | "FAMLI" | "PFML" | "PAID_LEAVE"
    # Widened to Optional: a headcount-only row (component_code FAMLI/
    # PFML/PAID_LEAVE, ZP-TAX-US-2026-001 §5 build-out) has neither a real
    # SUI-style wage base nor an employer-assigned rate — those programs'
    # statutory rates live in the canonical state-program ContributionRate
    # rows instead, same as every other state program. Every real SUI
    # profile still supplies both, as before.
    taxableWageBase: Optional[Decimal] = None
    rateSource: str = "STATE_DEFAULT"   # STATE_DEFAULT | NEW_EMPLOYER | EMPLOYER_NOTICE
    employerRatePct: Optional[Decimal] = None
    assessmentRatePct: Optional[Decimal] = None
    effectiveFrom: date
    effectiveTo: Optional[date] = None
    agencyAccountId: Optional[str] = None
    reimbursableStatus: str = "CONTRIBUTORY"   # CONTRIBUTORY | REIMBURSING
    sourceDocumentId: Optional[int] = None
    # Headcount-only purpose (see componentCode comment above): how many
    # covered individuals this employer has for this jurisdiction+program
    # as of effectiveFrom. Never inferred — a real Tax Ops entry, same
    # "never infer" principle as employerRatePct's own provenance rule.
    coveredEmployeeCount: Optional[int] = None


class EmployerTaxProfileResponse(BaseModel):
    id: int
    organizationId: int = Field(validation_alias="organization_id", serialization_alias="organizationId")
    jurisdictionId: str = Field(validation_alias="jurisdiction_id", serialization_alias="jurisdictionId")
    componentCode: str = Field(validation_alias="component_code", serialization_alias="componentCode")
    taxableWageBase: Optional[Decimal] = Field(None, validation_alias="taxable_wage_base", serialization_alias="taxableWageBase")
    rateSource: str = Field(validation_alias="rate_source", serialization_alias="rateSource")
    employerRatePct: Optional[Decimal] = Field(None, validation_alias="employer_rate_pct", serialization_alias="employerRatePct")
    assessmentRatePct: Optional[Decimal] = Field(None, validation_alias="assessment_rate_pct", serialization_alias="assessmentRatePct")
    effectiveFrom: date = Field(validation_alias="effective_from", serialization_alias="effectiveFrom")
    effectiveTo: Optional[date] = Field(None, validation_alias="effective_to", serialization_alias="effectiveTo")
    agencyAccountId: Optional[str] = Field(None, validation_alias="agency_account_id", serialization_alias="agencyAccountId")
    reimbursableStatus: str = Field(validation_alias="reimbursable_status", serialization_alias="reimbursableStatus")
    sourceDocumentId: Optional[int] = Field(None, validation_alias="source_document_id", serialization_alias="sourceDocumentId")
    coveredEmployeeCount: Optional[int] = Field(None, validation_alias="covered_employee_count", serialization_alias="coveredEmployeeCount")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── US: Cross-State Reciprocity ───────────────────────────────────────────

class ReciprocityRuleUpsert(BaseModel):
    id: Optional[int] = None
    residentJurisdiction: str   # "US-PA"
    workJurisdiction: str       # "US-NJ"
    agreementType: str = "RECIPROCAL_WAGE_WITHHOLDING"
    employeeCertificate: Optional[str] = None
    certificateRequired: bool = True
    resultWhenValid: Optional[str] = None
    effectiveFrom: date
    effectiveTo: Optional[date] = None
    sourceDocumentId: Optional[int] = None


class ReciprocityRuleResponse(BaseModel):
    id: int
    residentJurisdiction: str = Field(validation_alias="resident_jurisdiction", serialization_alias="residentJurisdiction")
    workJurisdiction: str = Field(validation_alias="work_jurisdiction", serialization_alias="workJurisdiction")
    agreementType: str = Field(validation_alias="agreement_type", serialization_alias="agreementType")
    employeeCertificate: Optional[str] = Field(None, validation_alias="employee_certificate", serialization_alias="employeeCertificate")
    certificateRequired: bool = Field(validation_alias="certificate_required", serialization_alias="certificateRequired")
    resultWhenValid: Optional[str] = Field(None, validation_alias="result_when_valid", serialization_alias="resultWhenValid")
    effectiveFrom: date = Field(validation_alias="effective_from", serialization_alias="effectiveFrom")
    effectiveTo: Optional[date] = Field(None, validation_alias="effective_to", serialization_alias="effectiveTo")
    sourceDocumentId: Optional[int] = Field(None, validation_alias="source_document_id", serialization_alias="sourceDocumentId")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Source Evidence (ZP-TAX-US-2026-001 §14) ──────────────────────────────
# One row per official publication a statutory value was taken from —
# referenced by JurisdictionPack/LocalityDataset/EmployerTaxProfile/
# ReciprocityRule via a nullable FK. Platform-wide, not US-only.

class SourceArtifactCreate(BaseModel):
    agency: str
    title: str
    formNumber: Optional[str] = None
    sourceUrl: Optional[str] = None
    publicationDate: Optional[date] = None
    checksumSha256: Optional[str] = None


class SourceArtifactResponse(BaseModel):
    id: int
    agency: str
    title: str
    formNumber: Optional[str] = Field(None, validation_alias="form_number", serialization_alias="formNumber")
    sourceUrl: Optional[str] = Field(None, validation_alias="source_url", serialization_alias="sourceUrl")
    publicationDate: Optional[date] = Field(None, validation_alias="publication_date", serialization_alias="publicationDate")
    retrievedAt: Optional[datetime] = Field(None, validation_alias="retrieved_at", serialization_alias="retrievedAt")
    checksumSha256: Optional[str] = Field(None, validation_alias="checksum_sha256", serialization_alias="checksumSha256")
    reviewerId: Optional[int] = Field(None, validation_alias="reviewer_id", serialization_alias="reviewerId")
    reviewerApprovedAt: Optional[datetime] = Field(None, validation_alias="reviewer_approved_at", serialization_alias="reviewerApprovedAt")
    originalFilename: Optional[str] = Field(None, validation_alias="original_filename", serialization_alias="originalFilename")
    contentType: Optional[str] = Field(None, validation_alias="content_type", serialization_alias="contentType")
    fileSizeBytes: Optional[int] = Field(None, validation_alias="file_size_bytes", serialization_alias="fileSizeBytes")
    hasFile: bool = False

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Taxability rules (India Code Wages classification, §7/§8) ──────────

class TaxabilityRuleUpsert(BaseModel):
    jurisdictionCountry: str = "IN"
    jurisdictionState: Optional[str] = None
    taxComponent: str = "code_wages"
    earningType: str  # "basic" | "hra" | "special_allowance" | "overtime" | "additional_compensation" | "named_allowances"
    isTaxable: bool
    effectiveFrom: Optional[date] = None
    effectiveTo: Optional[date] = None


class TaxabilityRuleResponse(BaseModel):
    id: int
    jurisdictionCountry: str = Field(..., validation_alias="jurisdiction_country", serialization_alias="jurisdictionCountry")
    jurisdictionState: Optional[str] = Field(None, validation_alias="jurisdiction_state", serialization_alias="jurisdictionState")
    taxComponent: str = Field(..., validation_alias="tax_component", serialization_alias="taxComponent")
    earningType: str = Field(..., validation_alias="earning_type", serialization_alias="earningType")
    isTaxable: bool = Field(..., validation_alias="is_taxable", serialization_alias="isTaxable")
    effectiveFrom: Optional[date] = Field(None, validation_alias="effective_from", serialization_alias="effectiveFrom")
    effectiveTo: Optional[date] = Field(None, validation_alias="effective_to", serialization_alias="effectiveTo")
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── India: state/local statutory readiness registry (§16) ──────────────

class StateLocalProgramReadinessUpsert(BaseModel):
    jurisdictionCountry: str = "IN"
    jurisdictionState: str
    jurisdictionLocality: Optional[str] = None
    program: str  # STATE_PT | LOCAL_PT | LWF | OTHER_STATE_PAYROLL
    legalStatus: str = "SOURCE_REQUIRED"  # APPLICABLE | NOT_APPLICABLE | SOURCE_REQUIRED
    localAuthorityRequired: bool = False
    registrationRequired: bool = False
    sourceDocumentId: Optional[int] = None
    notes: Optional[str] = None


class StateLocalProgramReadinessResponse(BaseModel):
    id: int
    jurisdictionCountry: str = Field(..., validation_alias="jurisdiction_country", serialization_alias="jurisdictionCountry")
    jurisdictionState: str = Field(..., validation_alias="jurisdiction_state", serialization_alias="jurisdictionState")
    jurisdictionLocality: Optional[str] = Field(None, validation_alias="jurisdiction_locality", serialization_alias="jurisdictionLocality")
    program: str
    legalStatus: str = Field(..., validation_alias="legal_status", serialization_alias="legalStatus")
    localAuthorityRequired: bool = Field(False, validation_alias="local_authority_required", serialization_alias="localAuthorityRequired")
    registrationRequired: bool = Field(False, validation_alias="registration_required", serialization_alias="registrationRequired")
    sourceDocumentId: Optional[int] = Field(None, validation_alias="source_document_id", serialization_alias="sourceDocumentId")
    notes: Optional[str] = None
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Germany: BMF PAP Algorithm Asset (ZP-TAX-DE-2026-001 §5, §17, §18) ────
# Container/evidence only — see models.PapAlgorithmAsset's own docstring.
# No "Create" request schema: ingestion is multipart (raw content + form
# fields), handled directly in the router like upload_compliance_document,
# not a JSON body — see router.py.

class PapAlgorithmAssetResponse(BaseModel):
    id:                   int
    jurisdictionCountry:  str = Field(validation_alias="jurisdiction_country", serialization_alias="jurisdictionCountry")
    taxYear:              str = Field(validation_alias="tax_year", serialization_alias="taxYear")
    papVersion:           str = Field(validation_alias="pap_version", serialization_alias="papVersion")
    effectiveFrom:        date = Field(validation_alias="effective_from", serialization_alias="effectiveFrom")
    effectiveTo:          Optional[date] = Field(None, validation_alias="effective_to", serialization_alias="effectiveTo")
    status:               str
    sourceDocumentId:     Optional[int] = Field(None, validation_alias="source_document_id", serialization_alias="sourceDocumentId")
    sourceContentSha256:  Optional[str] = Field(None, validation_alias="source_content_sha256", serialization_alias="sourceContentSha256")
    buildIdentifier:      Optional[str] = Field(None, validation_alias="build_identifier", serialization_alias="buildIdentifier")
    previousVersionId:    Optional[int] = Field(None, validation_alias="previous_version_id", serialization_alias="previousVersionId")
    createdById:          Optional[int] = Field(None, validation_alias="created_by_id", serialization_alias="createdById")
    updatedById:          Optional[int] = Field(None, validation_alias="updated_by_id", serialization_alias="updatedById")
    approvedById:         Optional[int] = Field(None, validation_alias="approved_by_id", serialization_alias="approvedById")
    createdAt:            Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Germany: BMF PAP Production Release Governance (Phase 8G-1) ──────────
# Read-only response model + narrow request bodies for recording external
# evidence. Deliberately no request body accepts a bare "true" for a gate
# dimension without the corresponding evidence fields — see service.py's
# own docstrings for why each of these must be explicit, actor-attributed
# evidence, never a default.

class GermanyPapReleaseResponse(BaseModel):
    id:                          int
    papAssetId:                  int = Field(validation_alias="pap_asset_id", serialization_alias="papAssetId")
    boundSourceContentSha256:    Optional[str] = Field(None, validation_alias="bound_source_content_sha256", serialization_alias="boundSourceContentSha256")
    status:                      str

    sourceIdentityVerified:      bool = Field(validation_alias="source_identity_verified", serialization_alias="sourceIdentityVerified")
    sourceHashVerified:          bool = Field(validation_alias="source_hash_verified", serialization_alias="sourceHashVerified")
    sourceFinalityStatus:        str = Field(validation_alias="source_finality_status", serialization_alias="sourceFinalityStatus")
    licensingStatus:             str = Field(validation_alias="licensing_status", serialization_alias="licensingStatus")
    goldenVectorsPassed:         bool = Field(validation_alias="golden_vectors_passed", serialization_alias="goldenVectorsPassed")
    securityCertified:           bool = Field(validation_alias="security_certified", serialization_alias="securityCertified")

    preparedById:                Optional[int] = Field(None, validation_alias="prepared_by_id", serialization_alias="preparedById")
    approvedById:                Optional[int] = Field(None, validation_alias="approved_by_id", serialization_alias="approvedById")
    activatedById:                Optional[int] = Field(None, validation_alias="activated_by_id", serialization_alias="activatedById")
    rolledBackById:               Optional[int] = Field(None, validation_alias="rolled_back_by_id", serialization_alias="rolledBackById")

    createdAt:                   Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class GermanyPapReleaseGateStatusResponse(BaseModel):
    """Read-only gate-evaluation preview — never mutates state."""
    releaseId:              int
    gates:                  dict
    failedGates:            List[str]
    isActivationEligible:   bool

    model_config = ConfigDict(populate_by_name=True)


class GermanyPapReleaseSourceFinalityUpdate(BaseModel):
    status:      str
    authority:   Optional[str] = None
    reference:   Optional[str] = None
    notes:       Optional[str] = None

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class GermanyPapReleaseLicensingUpdate(BaseModel):
    status:                str
    authority:              Optional[str] = None
    reference:              Optional[str] = None
    authorizationDate:      Optional[date] = Field(None, validation_alias="authorizationDate")
    effectiveDate:          Optional[date] = Field(None, validation_alias="effectiveDate")
    expiryDate:             Optional[date] = Field(None, validation_alias="expiryDate")
    evidenceLocation:       Optional[str] = Field(None, validation_alias="evidenceLocation")
    evidenceHash:           Optional[str] = Field(None, validation_alias="evidenceHash")
    notes:                  Optional[str] = None

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class GermanyPapGoldenVectorPayload(BaseModel):
    """One certified golden vector, submitted with the actual outputs
    produced when it was executed — see
    service.record_pap_release_golden_vectors for why both the vector's
    own classification/hash AND the actual outputs are required (a bare
    hash + free-text note used to be sufficient, which is the Phase 8BG
    defect this schema closes)."""

    vectorId:              str = Field(validation_alias="vectorId")
    sourceDocument:         str = Field(validation_alias="sourceDocument")
    sourcePage:             int = Field(validation_alias="sourcePage")
    sourceHashSha256:       str = Field(validation_alias="sourceHashSha256")
    description:            str = Field(validation_alias="description")
    inputs:                 Dict[str, object] = Field(validation_alias="inputs")
    expectedOutputs:        Dict[str, Decimal] = Field(validation_alias="expectedOutputs")
    sourceClassification:   str = Field(validation_alias="sourceClassification")
    actualOutputs:          Dict[str, Decimal] = Field(validation_alias="actualOutputs")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class GermanyPapReleaseGoldenVectorUpdate(BaseModel):
    sourceSha256:  str = Field(validation_alias="sourceSha256")
    vectors:        List[GermanyPapGoldenVectorPayload] = Field(default_factory=list, validation_alias="vectors")
    notes:          Optional[str] = None

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class GermanyPapReleaseNotesUpdate(BaseModel):
    notes: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class GermanyPapReleaseRejectRequest(BaseModel):
    reason: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class GermanyPapReleaseRollbackRequest(BaseModel):
    reason:             Optional[str] = None
    targetReleaseId:    Optional[int] = Field(None, validation_alias="targetReleaseId")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


# ── Germany: Krankenkasse (Health Fund) Registry (ZP-TAX-DE-2026-001 §11) ─
# Configuration/registry only — see models.GermanyHealthFund's own
# docstring. No "Create" JSON schema needed beyond this plain BaseModel
# (unlike PAP ingestion, there is no file upload here — a health-fund rate
# is a scalar value + a citation, not a document to hash).

class GermanyHealthFundCreate(BaseModel):
    health_fund_id:          str = Field(validation_alias="healthFundId")
    fund_name:               str = Field(validation_alias="fundName")
    supplementary_rate_pct:  Decimal = Field(validation_alias="supplementaryRatePct")
    is_average_rate:         bool = Field(False, validation_alias="isAverageRate")
    u1_rate_pct:             Optional[Decimal] = Field(None, validation_alias="u1RatePct")
    u2_rate_pct:             Optional[Decimal] = Field(None, validation_alias="u2RatePct")
    effective_from:          date = Field(validation_alias="effectiveFrom")
    effective_to:            Optional[date] = Field(None, validation_alias="effectiveTo")
    member_applicability:    Optional[str] = Field(None, validation_alias="memberApplicability")
    payroll_recalc_policy:   Optional[str] = Field(None, validation_alias="payrollRecalcPolicy")
    authority_source_id:     Optional[int] = Field(None, validation_alias="authoritySourceId")
    jurisdiction_pack_id: Optional[int] = Field(None, validation_alias="jurisdictionPackId")  # Phase 8DI

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class GermanyHealthFundResponse(BaseModel):
    id:                   int
    healthFundId:         str = Field(validation_alias="health_fund_id", serialization_alias="healthFundId")
    fundName:             str = Field(validation_alias="fund_name", serialization_alias="fundName")
    supplementaryRatePct: Decimal = Field(validation_alias="supplementary_rate_pct", serialization_alias="supplementaryRatePct")
    isAverageRate:        bool = Field(validation_alias="is_average_rate", serialization_alias="isAverageRate")
    u1RatePct:            Optional[Decimal] = Field(None, validation_alias="u1_rate_pct", serialization_alias="u1RatePct")
    u2RatePct:            Optional[Decimal] = Field(None, validation_alias="u2_rate_pct", serialization_alias="u2RatePct")
    effectiveFrom:        date = Field(validation_alias="effective_from", serialization_alias="effectiveFrom")
    effectiveTo:          Optional[date] = Field(None, validation_alias="effective_to", serialization_alias="effectiveTo")
    status:               str
    memberApplicability:  Optional[str] = Field(None, validation_alias="member_applicability", serialization_alias="memberApplicability")
    payrollRecalcPolicy:  Optional[str] = Field(None, validation_alias="payroll_recalc_policy", serialization_alias="payrollRecalcPolicy")
    authoritySourceId:    Optional[int] = Field(None, validation_alias="authority_source_id", serialization_alias="authoritySourceId")
    previousVersionId:    Optional[int] = Field(None, validation_alias="previous_version_id", serialization_alias="previousVersionId")
    jurisdictionPackId:  Optional[int] = Field(None, validation_alias="jurisdiction_pack_id", serialization_alias="jurisdictionPackId")  # Phase 8DJ
    createdById:          Optional[int] = Field(None, validation_alias="created_by_id", serialization_alias="createdById")
    approvedById:         Optional[int] = Field(None, validation_alias="approved_by_id", serialization_alias="approvedById")
    createdAt:            Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── India: Forms 122/123/124 (§6.2) ─────────────────────────────────────

class SalaryTdsDeclarationCreate(BaseModel):
    employee_id: int
    tax_year: str
    prior_employer_salary: Decimal = Decimal("0")
    prior_employer_tds_deducted: Decimal = Decimal("0")
    other_income: Decimal = Decimal("0")
    house_property_loss: Decimal = Decimal("0")


class SalaryTdsDeclarationResponse(BaseModel):
    id: int
    employeeId: int = Field(..., validation_alias="employee_id", serialization_alias="employeeId")
    taxYear: str = Field(..., validation_alias="tax_year", serialization_alias="taxYear")
    priorEmployerSalary: Decimal = Field(Decimal("0"), validation_alias="prior_employer_salary", serialization_alias="priorEmployerSalary")
    priorEmployerTdsDeducted: Decimal = Field(Decimal("0"), validation_alias="prior_employer_tds_deducted", serialization_alias="priorEmployerTdsDeducted")
    otherIncome: Decimal = Field(Decimal("0"), validation_alias="other_income", serialization_alias="otherIncome")
    housePropertyLoss: Decimal = Field(Decimal("0"), validation_alias="house_property_loss", serialization_alias="housePropertyLoss")
    status: str
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class PRAccrueBonusYearRequest(BaseModel):
    employee_id: int
    as_of_date: date
    wages_this_period: Decimal
    hours_this_period: Decimal


class PRBonusYearTotalsResponse(BaseModel):
    bonusYear: str = Field(..., validation_alias="bonus_year", serialization_alias="bonusYear")
    cumulativeWages: Decimal = Field(..., validation_alias="cumulative_wages", serialization_alias="cumulativeWages")
    cumulativeHours: Decimal = Field(..., validation_alias="cumulative_hours", serialization_alias="cumulativeHours")
    model_config = ConfigDict(populate_by_name=True)


class PRChristmasBonusCalculateRequest(BaseModel):
    employee_id: int
    as_of_date: date
    hired_before_2017: bool
    employer_size_over_threshold: bool
    is_first_year: bool = False


class PRChristmasBonusCalculateResponse(BaseModel):
    eligible: bool
    bonusAmount: Decimal = Field(..., validation_alias="bonus_amount", serialization_alias="bonusAmount")
    dollarCap: Decimal = Field(..., validation_alias="dollar_cap", serialization_alias="dollarCap")
    hoursThreshold: Decimal = Field(..., validation_alias="hours_threshold", serialization_alias="hoursThreshold")
    bonusYear: str = Field(..., validation_alias="bonus_year", serialization_alias="bonusYear")
    cumulativeWages: Decimal = Field(..., validation_alias="cumulative_wages", serialization_alias="cumulativeWages")
    cumulativeHours: Decimal = Field(..., validation_alias="cumulative_hours", serialization_alias="cumulativeHours")
    model_config = ConfigDict(populate_by_name=True)


class PRAccrueMonthlyLeaveRequest(BaseModel):
    employee_id: int
    hired_before_2017: bool
    years_of_service: Decimal = Decimal("0")
    qualifying_small_employer: bool = False
    qualifying_hours_in_month: Decimal
    period_label: Optional[str] = None


class PRWithholdingCertificateCreate(BaseModel):
    employee_id: int
    personal_exemption_amount: Decimal = Decimal("0")
    dependents_count: int = 0
    dependent_exemption_per_dependent: Decimal = Decimal("0")
    deduction_allowance_amount: Decimal = Decimal("0")
    optional_married_computation: bool = False
    msrra_election: bool = False
    additional_withholding_amount: Decimal = Decimal("0")


class PRWithholdingCertificateResponse(BaseModel):
    id: int
    employeeId: int = Field(..., validation_alias="employee_id", serialization_alias="employeeId")
    personalExemptionAmount: Decimal = Field(Decimal("0"), validation_alias="personal_exemption_amount", serialization_alias="personalExemptionAmount")
    dependentsCount: int = Field(0, validation_alias="dependents_count", serialization_alias="dependentsCount")
    dependentExemptionPerDependent: Decimal = Field(Decimal("0"), validation_alias="dependent_exemption_per_dependent", serialization_alias="dependentExemptionPerDependent")
    deductionAllowanceAmount: Decimal = Field(Decimal("0"), validation_alias="deduction_allowance_amount", serialization_alias="deductionAllowanceAmount")
    optionalMarriedComputation: bool = Field(False, validation_alias="optional_married_computation", serialization_alias="optionalMarriedComputation")
    msrraElection: bool = Field(False, validation_alias="msrra_election", serialization_alias="msrraElection")
    additionalWithholdingAmount: Decimal = Field(Decimal("0"), validation_alias="additional_withholding_amount", serialization_alias="additionalWithholdingAmount")
    status: str
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SalaryTdsClaimCreate(BaseModel):
    employee_id: int
    tax_year: str
    claim_type: str
    claimed_amount: Decimal
    evidence_reference: Optional[str] = None


class SalaryTdsClaimResponse(BaseModel):
    id: int
    employeeId: int = Field(..., validation_alias="employee_id", serialization_alias="employeeId")
    taxYear: str = Field(..., validation_alias="tax_year", serialization_alias="taxYear")
    claimType: str = Field(..., validation_alias="claim_type", serialization_alias="claimType")
    claimedAmount: Decimal = Field(..., validation_alias="claimed_amount", serialization_alias="claimedAmount")
    evidenceReference: Optional[str] = Field(None, validation_alias="evidence_reference", serialization_alias="evidenceReference")
    status: str
    rejectionReason: Optional[str] = Field(None, validation_alias="rejection_reason", serialization_alias="rejectionReason")
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SalaryTdsClaimRejectRequest(BaseModel):
    reason: str


class EmployeeBenefitValuationCreate(BaseModel):
    employee_id: int
    tax_year: str
    benefit_type: str
    taxable_value: Decimal
    description: Optional[str] = None


class EmployeeBenefitValuationResponse(BaseModel):
    id: int
    employeeId: int = Field(..., validation_alias="employee_id", serialization_alias="employeeId")
    taxYear: str = Field(..., validation_alias="tax_year", serialization_alias="taxYear")
    benefitType: str = Field(..., validation_alias="benefit_type", serialization_alias="benefitType")
    taxableValue: Decimal = Field(..., validation_alias="taxable_value", serialization_alias="taxableValue")
    description: Optional[str] = None
    status: str
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Germany: Accident Insurance Profile (Phase 8AJ, 2nd pass) ───────────
# Maker-checker workspace for one organization's employer-specific
# accident-insurance configuration — see models.GermanyAccidentInsuranceProfile's
# own docstring for why this is a separate table from EmployerTaxProfile.

class GermanyAccidentInsuranceProfileCreate(BaseModel):
    organization_id:         int = Field(validation_alias="organizationId")
    carrier_name:            str = Field(validation_alias="carrierName")
    agency_account_id:       Optional[str] = Field(None, validation_alias="agencyAccountId")
    risk_class_description:  Optional[str] = Field(None, validation_alias="riskClassDescription")
    employer_rate_pct:       Decimal = Field(validation_alias="employerRatePct")
    effective_from:          date = Field(validation_alias="effectiveFrom")
    effective_to:            Optional[date] = Field(None, validation_alias="effectiveTo")
    authority_source_id:     Optional[int] = Field(None, validation_alias="authoritySourceId")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class GermanyAccidentInsuranceProfileResponse(BaseModel):
    id:                     int
    organizationId:         int = Field(validation_alias="organization_id", serialization_alias="organizationId")
    carrierName:            str = Field(validation_alias="carrier_name", serialization_alias="carrierName")
    agencyAccountId:        Optional[str] = Field(None, validation_alias="agency_account_id", serialization_alias="agencyAccountId")
    riskClassDescription:   Optional[str] = Field(None, validation_alias="risk_class_description", serialization_alias="riskClassDescription")
    employerRatePct:        Decimal = Field(validation_alias="employer_rate_pct", serialization_alias="employerRatePct")
    effectiveFrom:          date = Field(validation_alias="effective_from", serialization_alias="effectiveFrom")
    effectiveTo:            Optional[date] = Field(None, validation_alias="effective_to", serialization_alias="effectiveTo")
    status:                 str
    authoritySourceId:      Optional[int] = Field(None, validation_alias="authority_source_id", serialization_alias="authoritySourceId")
    previousVersionId:      Optional[int] = Field(None, validation_alias="previous_version_id", serialization_alias="previousVersionId")
    createdById:            Optional[int] = Field(None, validation_alias="created_by_id", serialization_alias="createdById")
    approvedById:           Optional[int] = Field(None, validation_alias="approved_by_id", serialization_alias="approvedById")
    createdAt:              Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Germany: Church Tax Exception (Phase 8AM) ───────────────────────────
# Global (no organizationId) — see models.GermanyChurchTaxException's own
# docstring for why: a documented sub-Land exception (e.g. Bad Wimpfen's
# Diocese-of-Mainz enclave) is determined by employee residence/
# denomination, never by employer, so this mirrors GermanyHealthFund's
# global shape, not GermanyAccidentInsuranceProfile's org-scoped one.

class GermanyChurchTaxExceptionCreate(BaseModel):
    land_code:                 str = Field(validation_alias="landCode")
    denomination:               str = Field(validation_alias="denomination")
    municipality_postal_code:   str = Field(validation_alias="municipalityPostalCode")
    scope_description:          Optional[str] = Field(None, validation_alias="scopeDescription")
    exception_rate_pct:          Decimal = Field(validation_alias="exceptionRatePct")
    effective_from:              date = Field(validation_alias="effectiveFrom")
    effective_to:                Optional[date] = Field(None, validation_alias="effectiveTo")
    authority_source_id:         Optional[int] = Field(None, validation_alias="authoritySourceId")
    jurisdiction_pack_id: Optional[int] = Field(None, validation_alias="jurisdictionPackId")  # Phase 8DI

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class GermanyChurchTaxExceptionResponse(BaseModel):
    id:                       int
    landCode:                 str = Field(validation_alias="land_code", serialization_alias="landCode")
    denomination:              str = Field(validation_alias="denomination", serialization_alias="denomination")
    municipalityPostalCode:    str = Field(validation_alias="municipality_postal_code", serialization_alias="municipalityPostalCode")
    scopeDescription:          Optional[str] = Field(None, validation_alias="scope_description", serialization_alias="scopeDescription")
    exceptionRatePct:          Decimal = Field(validation_alias="exception_rate_pct", serialization_alias="exceptionRatePct")
    effectiveFrom:             date = Field(validation_alias="effective_from", serialization_alias="effectiveFrom")
    effectiveTo:               Optional[date] = Field(None, validation_alias="effective_to", serialization_alias="effectiveTo")
    status:                    str
    authoritySourceId:         Optional[int] = Field(None, validation_alias="authority_source_id", serialization_alias="authoritySourceId")
    previousVersionId:         Optional[int] = Field(None, validation_alias="previous_version_id", serialization_alias="previousVersionId")
    jurisdictionPackId:  Optional[int] = Field(None, validation_alias="jurisdiction_pack_id", serialization_alias="jurisdictionPackId")  # Phase 8DJ
    createdById:               Optional[int] = Field(None, validation_alias="created_by_id", serialization_alias="createdById")
    approvedById:              Optional[int] = Field(None, validation_alias="approved_by_id", serialization_alias="approvedById")
    createdAt:                 Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Germany: U1 Tariff (Sickness Reimbursement) (Phase 8W) ─────────────
# Configuration/registry only — see models.GermanyHealthFundU1Tariff's own
# docstring. Plain JSON body (no file upload — like GermanyHealthFund, a
# tariff's value is scalar + citation, not a document to hash).

class GermanyHealthFundU1TariffCreate(BaseModel):
    # Field names are snake_case (matching GermanyHealthFundCreate); the
    # camelCase validation aliases are what the JSON API / frontend sends.
    health_fund_id:          str = Field(validation_alias="healthFundId")
    tariff_identifier:       str = Field(validation_alias="tariffIdentifier")
    tariff_name:             Optional[str] = Field(None, validation_alias="tariffName")
    reimbursement_pct:       Decimal = Field(validation_alias="reimbursementPct")
    levy_rate_pct:           Decimal = Field(validation_alias="levyRatePct")
    effective_from:          date = Field(validation_alias="effectiveFrom")
    effective_to:            Optional[date] = Field(None, validation_alias="effectiveTo")
    authority_source_id:     Optional[int] = Field(None, validation_alias="authoritySourceId")
    jurisdiction_pack_id: Optional[int] = Field(None, validation_alias="jurisdictionPackId")  # Phase 8DI

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class GermanyHealthFundU1TariffResponse(BaseModel):
    id:                    int
    healthFundId:          str = Field(validation_alias="health_fund_id", serialization_alias="healthFundId")
    tariffIdentifier:      str = Field(validation_alias="tariff_identifier", serialization_alias="tariffIdentifier")
    tariffName:            Optional[str] = Field(None, validation_alias="tariff_name", serialization_alias="tariffName")
    reimbursementPct:      Decimal = Field(validation_alias="reimbursement_pct", serialization_alias="reimbursementPct")
    levyRatePct:           Decimal = Field(validation_alias="levy_rate_pct", serialization_alias="levyRatePct")
    effectiveFrom:         date = Field(validation_alias="effective_from", serialization_alias="effectiveFrom")
    effectiveTo:           Optional[date] = Field(None, validation_alias="effective_to", serialization_alias="effectiveTo")
    status:                str
    authoritySourceId:     Optional[int] = Field(None, validation_alias="authority_source_id", serialization_alias="authoritySourceId")
    previousVersionId:     Optional[int] = Field(None, validation_alias="previous_version_id", serialization_alias="previousVersionId")
    jurisdictionPackId:  Optional[int] = Field(None, validation_alias="jurisdiction_pack_id", serialization_alias="jurisdictionPackId")  # Phase 8DJ
    createdById:           Optional[int] = Field(None, validation_alias="created_by_id", serialization_alias="createdById")
    approvedById:          Optional[int] = Field(None, validation_alias="approved_by_id", serialization_alias="approvedById")
    createdAt:             Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Germany: Contribution Ceiling Configuration (ZP-TAX-DE-2026-001 §9) ──
# Configuration/registry only — see models.GermanyContributionCeiling's
# own docstring. Plain JSON body (no file upload — like GermanyHealthFund,
# a ceiling figure has no document content to hash).

class GermanyContributionCeilingCreate(BaseModel):
    branch:            str = Field(validation_alias="branch")
    monthly_ceiling:   Decimal = Field(validation_alias="monthlyCeiling")
    annual_ceiling:    Decimal = Field(validation_alias="annualCeiling")
    effective_from:    date = Field(validation_alias="effectiveFrom")
    effective_to:      Optional[date] = Field(None, validation_alias="effectiveTo")
    authority_source_id: Optional[int] = Field(None, validation_alias="authoritySourceId")
    jurisdiction_pack_id: Optional[int] = Field(None, validation_alias="jurisdictionPackId")  # Phase 8DI

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class GermanyContributionCeilingResponse(BaseModel):
    id:                  int
    branch:              str
    monthlyCeiling:      Decimal = Field(validation_alias="monthly_ceiling", serialization_alias="monthlyCeiling")
    annualCeiling:       Decimal = Field(validation_alias="annual_ceiling", serialization_alias="annualCeiling")
    effectiveFrom:       date = Field(validation_alias="effective_from", serialization_alias="effectiveFrom")
    effectiveTo:         Optional[date] = Field(None, validation_alias="effective_to", serialization_alias="effectiveTo")
    status:              str
    authoritySourceId:   Optional[int] = Field(None, validation_alias="authority_source_id", serialization_alias="authoritySourceId")
    previousVersionId:   Optional[int] = Field(None, validation_alias="previous_version_id", serialization_alias="previousVersionId")
    jurisdictionPackId:  Optional[int] = Field(None, validation_alias="jurisdiction_pack_id", serialization_alias="jurisdictionPackId")  # Phase 8DJ
    createdById:         Optional[int] = Field(None, validation_alias="created_by_id", serialization_alias="createdById")
    approvedById:        Optional[int] = Field(None, validation_alias="approved_by_id", serialization_alias="approvedById")
    createdAt:           Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Germany: Minijob / Midijob statutory parameters (Phase 8BK) ─────────
# Same shape/conventions as GermanyContributionCeilingCreate/Response
# immediately above — see models.GermanyMinijobMidijobParameter's own
# docstring for the closed parameter_code vocabulary.
class GermanyMinijobMidijobParameterCreate(BaseModel):
    parameter_code:    str = Field(validation_alias="parameterCode")
    value:             Decimal = Field(validation_alias="value")
    value_type:        str = Field(validation_alias="valueType")
    label:             str = Field(validation_alias="label")
    effective_from:    date = Field(validation_alias="effectiveFrom")
    effective_to:      Optional[date] = Field(None, validation_alias="effectiveTo")
    authority_source_id: Optional[int] = Field(None, validation_alias="authoritySourceId")
    jurisdiction_pack_id: Optional[int] = Field(None, validation_alias="jurisdictionPackId")  # Phase 8DI

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class GermanyMinijobMidijobParameterResponse(BaseModel):
    id:                  int
    parameterCode:       str = Field(validation_alias="parameter_code", serialization_alias="parameterCode")
    value:               Decimal
    valueType:           str = Field(validation_alias="value_type", serialization_alias="valueType")
    label:               str
    effectiveFrom:       date = Field(validation_alias="effective_from", serialization_alias="effectiveFrom")
    effectiveTo:         Optional[date] = Field(None, validation_alias="effective_to", serialization_alias="effectiveTo")
    status:              str
    authoritySourceId:   Optional[int] = Field(None, validation_alias="authority_source_id", serialization_alias="authoritySourceId")
    previousVersionId:   Optional[int] = Field(None, validation_alias="previous_version_id", serialization_alias="previousVersionId")
    jurisdictionPackId:  Optional[int] = Field(None, validation_alias="jurisdiction_pack_id", serialization_alias="jurisdictionPackId")  # Phase 8DJ
    createdById:         Optional[int] = Field(None, validation_alias="created_by_id", serialization_alias="createdById")
    approvedById:        Optional[int] = Field(None, validation_alias="approved_by_id", serialization_alias="approvedById")
    createdAt:           Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Germany: PV (Long-Term Care Insurance) Child/Saxony Configuration ────
# Configuration/registry only — see models.GermanyPvConfiguration's own
# docstring. Plain JSON body (no file upload — like GermanyHealthFund and
# GermanyContributionCeiling, a PV rate configuration has no document
# content to hash).

class GermanyPvConfigurationCreate(BaseModel):
    child_category:            str = Field(validation_alias="childCategory")
    is_saxony:                 bool = Field(validation_alias="isSaxony")
    total_rate_pct:            Decimal = Field(validation_alias="totalRatePct")
    standard_employee_rate_pct: Decimal = Field(validation_alias="standardEmployeeRatePct")
    employer_rate_pct:         Decimal = Field(validation_alias="employerRatePct")
    saxony_employee_rate_pct:  Decimal = Field(validation_alias="saxonyEmployeeRatePct")
    saxony_employer_rate_pct:  Decimal = Field(validation_alias="saxonyEmployerRatePct")
    effective_from:            date = Field(validation_alias="effectiveFrom")
    effective_to:              Optional[date] = Field(None, validation_alias="effectiveTo")
    authority_source_id:       Optional[int] = Field(None, validation_alias="authoritySourceId")
    jurisdiction_pack_id: Optional[int] = Field(None, validation_alias="jurisdictionPackId")  # Phase 8DI

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class GermanyPvConfigurationResponse(BaseModel):
    id:                          int
    childCategory:               str = Field(validation_alias="child_category", serialization_alias="childCategory")
    isSaxony:                    bool = Field(validation_alias="is_saxony", serialization_alias="isSaxony")
    totalRatePct:                Decimal = Field(validation_alias="total_rate_pct", serialization_alias="totalRatePct")
    standardEmployeeRatePct:     Decimal = Field(validation_alias="standard_employee_rate_pct", serialization_alias="standardEmployeeRatePct")
    employerRatePct:             Decimal = Field(validation_alias="employer_rate_pct", serialization_alias="employerRatePct")
    saxonyEmployeeRatePct:       Decimal = Field(validation_alias="saxony_employee_rate_pct", serialization_alias="saxonyEmployeeRatePct")
    saxonyEmployerRatePct:       Decimal = Field(validation_alias="saxony_employer_rate_pct", serialization_alias="saxonyEmployerRatePct")
    effectiveFrom:               date = Field(validation_alias="effective_from", serialization_alias="effectiveFrom")
    effectiveTo:                 Optional[date] = Field(None, validation_alias="effective_to", serialization_alias="effectiveTo")
    status:                      str
    authoritySourceId:           Optional[int] = Field(None, validation_alias="authority_source_id", serialization_alias="authoritySourceId")
    previousVersionId:           Optional[int] = Field(None, validation_alias="previous_version_id", serialization_alias="previousVersionId")
    jurisdictionPackId:  Optional[int] = Field(None, validation_alias="jurisdiction_pack_id", serialization_alias="jurisdictionPackId")  # Phase 8DJ
    createdById:                 Optional[int] = Field(None, validation_alias="created_by_id", serialization_alias="createdById")
    approvedById:                Optional[int] = Field(None, validation_alias="approved_by_id", serialization_alias="approvedById")
    createdAt:                   Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Germany: Earning/Deduction Taxability (ZP-TAX-DE-2026-001 §15) ──────
# Configuration/registry only — see models.GermanyEarningTaxabilityRule's
# own docstring. Plain JSON body, same pattern as GermanyPvConfiguration.

class GermanyEarningTaxabilityRuleCreate(BaseModel):
    earning_type:              str = Field(validation_alias="earningType")
    wage_tax_treatment:         str = Field(validation_alias="wageTaxTreatment")
    gkv_pv_treatment:           str = Field(validation_alias="gkvPvTreatment")
    rv_alv_treatment:           str = Field(validation_alias="rvAlvTreatment")
    reporting_classification:  Optional[str] = Field(None, validation_alias="reportingClassification")
    effective_from:            date = Field(validation_alias="effectiveFrom")
    effective_to:              Optional[date] = Field(None, validation_alias="effectiveTo")
    authority_source_id:       Optional[int] = Field(None, validation_alias="authoritySourceId")
    jurisdiction_pack_id: Optional[int] = Field(None, validation_alias="jurisdictionPackId")  # Phase 8DI

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class GermanyEarningTaxabilityRuleResponse(BaseModel):
    id:                          int
    earningType:                 str = Field(validation_alias="earning_type", serialization_alias="earningType")
    wageTaxTreatment:             str = Field(validation_alias="wage_tax_treatment", serialization_alias="wageTaxTreatment")
    gkvPvTreatment:               str = Field(validation_alias="gkv_pv_treatment", serialization_alias="gkvPvTreatment")
    rvAlvTreatment:               str = Field(validation_alias="rv_alv_treatment", serialization_alias="rvAlvTreatment")
    reportingClassification:      Optional[str] = Field(None, validation_alias="reporting_classification", serialization_alias="reportingClassification")
    effectiveFrom:                date = Field(validation_alias="effective_from", serialization_alias="effectiveFrom")
    effectiveTo:                  Optional[date] = Field(None, validation_alias="effective_to", serialization_alias="effectiveTo")
    status:                       str
    authoritySourceId:            Optional[int] = Field(None, validation_alias="authority_source_id", serialization_alias="authoritySourceId")
    previousVersionId:            Optional[int] = Field(None, validation_alias="previous_version_id", serialization_alias="previousVersionId")
    jurisdictionPackId:  Optional[int] = Field(None, validation_alias="jurisdiction_pack_id", serialization_alias="jurisdictionPackId")  # Phase 8DJ
    createdById:                  Optional[int] = Field(None, validation_alias="created_by_id", serialization_alias="createdById")
    approvedById:                 Optional[int] = Field(None, validation_alias="approved_by_id", serialization_alias="approvedById")
    createdAt:                    Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Germany: overtime/shift-premium statutory registries (Phase 8AD) ────
# Configuration only — see models.py's GermanyOvertimePremiumCategory /
# GermanyOvertimeGrundlohnCap docstrings for the full rationale.

class GermanyOvertimePremiumCategoryCreate(BaseModel):
    category_code:      str = Field(validation_alias="categoryCode")
    wage_tax_free_pct:  Decimal = Field(validation_alias="wageTaxFreePct")
    effective_from:     date = Field(validation_alias="effectiveFrom")
    effective_to:       Optional[date] = Field(None, validation_alias="effectiveTo")
    authority_source_id: Optional[int] = Field(None, validation_alias="authoritySourceId")
    jurisdiction_pack_id: Optional[int] = Field(None, validation_alias="jurisdictionPackId")  # Phase 8DI

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class GermanyOvertimePremiumCategoryResponse(BaseModel):
    id:                  int
    categoryCode:        str = Field(validation_alias="category_code", serialization_alias="categoryCode")
    wageTaxFreePct:      Decimal = Field(validation_alias="wage_tax_free_pct", serialization_alias="wageTaxFreePct")
    effectiveFrom:       date = Field(validation_alias="effective_from", serialization_alias="effectiveFrom")
    effectiveTo:         Optional[date] = Field(None, validation_alias="effective_to", serialization_alias="effectiveTo")
    status:              str
    authoritySourceId:   Optional[int] = Field(None, validation_alias="authority_source_id", serialization_alias="authoritySourceId")
    previousVersionId:   Optional[int] = Field(None, validation_alias="previous_version_id", serialization_alias="previousVersionId")
    jurisdictionPackId:  Optional[int] = Field(None, validation_alias="jurisdiction_pack_id", serialization_alias="jurisdictionPackId")  # Phase 8DJ
    createdById:         Optional[int] = Field(None, validation_alias="created_by_id", serialization_alias="createdById")
    approvedById:        Optional[int] = Field(None, validation_alias="approved_by_id", serialization_alias="approvedById")
    createdAt:           Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class GermanyOvertimeGrundlohnCapCreate(BaseModel):
    dimension:           str = Field(validation_alias="dimension")
    hourly_cap_amount:   Decimal = Field(validation_alias="hourlyCapAmount")
    effective_from:      date = Field(validation_alias="effectiveFrom")
    effective_to:        Optional[date] = Field(None, validation_alias="effectiveTo")
    authority_source_id: Optional[int] = Field(None, validation_alias="authoritySourceId")
    jurisdiction_pack_id: Optional[int] = Field(None, validation_alias="jurisdictionPackId")  # Phase 8DI

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class GermanyOvertimeGrundlohnCapResponse(BaseModel):
    id:                  int
    dimension:           str
    hourlyCapAmount:     Decimal = Field(validation_alias="hourly_cap_amount", serialization_alias="hourlyCapAmount")
    effectiveFrom:       date = Field(validation_alias="effective_from", serialization_alias="effectiveFrom")
    effectiveTo:         Optional[date] = Field(None, validation_alias="effective_to", serialization_alias="effectiveTo")
    status:              str
    authoritySourceId:   Optional[int] = Field(None, validation_alias="authority_source_id", serialization_alias="authoritySourceId")
    previousVersionId:   Optional[int] = Field(None, validation_alias="previous_version_id", serialization_alias="previousVersionId")
    jurisdictionPackId:  Optional[int] = Field(None, validation_alias="jurisdiction_pack_id", serialization_alias="jurisdictionPackId")  # Phase 8DJ
    createdById:         Optional[int] = Field(None, validation_alias="created_by_id", serialization_alias="createdById")
    approvedById:        Optional[int] = Field(None, validation_alias="approved_by_id", serialization_alias="approvedById")
    createdAt:           Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── US: Locality (county/municipal/school-district) tax ──────────────────
# Deliberately manual-entry, not auto-geocoded from an address — the same
# trust model as EmployerTaxProfile/SUI: Tax Ops enters a real, published
# local rate against a locality code, evidenced by a SourceArtifact if
# desired. An automated address-to-jurisdiction-code resolver (what the
# standard's §7 ultimately wants) needs a licensed geocoding/locality
# dataset — a data-sourcing decision, not something to fabricate here.

class LocalityRateUpsert(BaseModel):
    id: Optional[int] = None
    jurisdictionCountry: str = "US"
    jurisdictionState: str
    localityCode: str
    localityType: str = "MUNICIPAL"   # COUNTY | MUNICIPAL | SCHOOL_DISTRICT | PSD_EIT_LST | OH_MUNI_CREDIT
    localityName: Optional[str] = None
    residentRatePct: Optional[Decimal] = None
    nonresidentRatePct: Optional[Decimal] = None
    flatAmount: Optional[Decimal] = None
    taxCollectorId: Optional[str] = None
    # Tiered/progressive local tax (Production-Readiness Plan Phase 4) —
    # {"SINGLE": {"deduction": N, "brackets": [{"min","max","rate"}, ...]},
    # "MFJ": {...}}. None (every locality before this field existed, and
    # every ordinary flat-rate locality since) is a complete no-op.
    bracketSchedule: Optional[dict] = None
    # PA Local Services Tax (LST) low-income exemption threshold —
    # Production-Readiness Plan Phase 4. Only meaningful when localityType
    # == "PSD_EIT_LST" and flatAmount (the LST fee) is also set. None is a
    # complete no-op (LST applies at every income level).
    lstExemptionThreshold: Optional[Decimal] = None
    effectiveFrom: Optional[date] = None
    effectiveTo: Optional[date] = None
    sourceDocumentId: Optional[int] = None


class LocalityRateResponse(BaseModel):
    id: int
    localityDatasetId: int = Field(validation_alias="locality_dataset_id", serialization_alias="localityDatasetId")
    localityCode: str = Field(validation_alias="locality_code", serialization_alias="localityCode")
    localityType: str = Field(validation_alias="locality_type", serialization_alias="localityType")
    localityName: Optional[str] = Field(None, validation_alias="locality_name", serialization_alias="localityName")
    residentRatePct: Optional[Decimal] = Field(None, validation_alias="resident_rate_pct", serialization_alias="residentRatePct")
    nonresidentRatePct: Optional[Decimal] = Field(None, validation_alias="nonresident_rate_pct", serialization_alias="nonresidentRatePct")
    flatAmount: Optional[Decimal] = Field(None, validation_alias="flat_amount", serialization_alias="flatAmount")
    taxCollectorId: Optional[str] = Field(None, validation_alias="tax_collector_id", serialization_alias="taxCollectorId")
    bracketSchedule: Optional[dict] = Field(None, validation_alias="bracket_schedule", serialization_alias="bracketSchedule")
    lstExemptionThreshold: Optional[Decimal] = Field(None, validation_alias="lst_exemption_threshold", serialization_alias="lstExemptionThreshold")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── US: Locality Dataset Manager (gap-closure Plan Phase 3) ─────────────

class LocalityDatasetRateRow(BaseModel):
    """One row within a bulk locality-dataset import — same shape as
    LocalityRateUpsert minus the dataset-identifying fields, which the
    import endpoint supplies once for the whole batch."""
    localityCode: str
    localityType: str = "MUNICIPAL"
    localityName: Optional[str] = None
    residentRatePct: Optional[Decimal] = None
    nonresidentRatePct: Optional[Decimal] = None
    flatAmount: Optional[Decimal] = None
    taxCollectorId: Optional[str] = None
    bracketSchedule: Optional[dict] = None
    lstExemptionThreshold: Optional[Decimal] = None


class LocalityDatasetImportRequest(BaseModel):
    jurisdictionCountry: str = "US"
    jurisdictionState: str
    version: str
    effectiveFrom: Optional[date] = None
    sourceDocumentId: Optional[int] = None
    rows: List[LocalityDatasetRateRow]


class StateTaxBracketRow(BaseModel):
    """One row within a bulk state-tax import — a single MARGINAL_RATE
    bracket for one filing status. Same shape as the relevant subset of
    CanonicalTaxSlabUpsert, minus the fields the import endpoint supplies
    once for the whole batch (jurisdictionPackId/jurisdictionState/ruleType)."""
    filingStatus: Optional[str] = None
    minAmount: Decimal
    maxAmount: Optional[Decimal] = None
    ratePct: Decimal
    rateLabel: Optional[str] = None
    taxFormula: Optional[str] = None


class StateStandardDeductionRow(BaseModel):
    """One row within a bulk state-tax import — a flat standard-deduction
    amount for one filing status (ContributionRate component_key=
    "state_standard_deduction")."""
    filingStatus: Optional[str] = None
    label: Optional[str] = None
    flatAmount: Decimal


class BulkStateTaxImportRequest(BaseModel):
    jurisdictionState: str
    version: str
    packId: Optional[str] = None
    effectiveFrom: Optional[date] = None
    sourceDocumentId: Optional[int] = None
    bracketRows: List[StateTaxBracketRow]
    standardDeductionRows: List[StateStandardDeductionRow] = Field(default_factory=list)


class LocalityDatasetResponse(BaseModel):
    id: int
    jurisdictionCountry: str = Field(validation_alias="jurisdiction_country", serialization_alias="jurisdictionCountry")
    jurisdictionState: str = Field(validation_alias="jurisdiction_state", serialization_alias="jurisdictionState")
    version: str
    status: str
    checksumSha256: Optional[str] = Field(None, validation_alias="checksum_sha256", serialization_alias="checksumSha256")
    effectiveFrom: Optional[date] = Field(None, validation_alias="effective_from", serialization_alias="effectiveFrom")
    effectiveTo: Optional[date] = Field(None, validation_alias="effective_to", serialization_alias="effectiveTo")
    sourceDocumentId: Optional[int] = Field(None, validation_alias="source_document_id", serialization_alias="sourceDocumentId")
    importedById: Optional[int] = Field(None, validation_alias="imported_by_id", serialization_alias="importedById")
    approvedById: Optional[int] = Field(None, validation_alias="approved_by_id", serialization_alias="approvedById")
    createdAt: Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")
    rateCount: Optional[int] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class LocalityDatasetDiffResponse(BaseModel):
    datasetId: int
    comparedAgainstDatasetId: Optional[int] = None
    comparedAgainstVersion: Optional[str] = None
    added: List[str]
    removed: List[str]
    changed: List[dict]


# ── Dashboard ──────────────────────────────────────────────────────────

class DashboardSummaryResponse(BaseModel):
    totalPayrollCost:            Decimal
    totalPayrollCostChangePct:   Optional[float] = None
    totalGross:                  Optional[Decimal] = None
    totalTaxes:                  Optional[Decimal] = None
    totalAttendanceDeduction:    Optional[Decimal] = None
    totalNet:                    Optional[Decimal] = None
    headcount:                   int
    activeCount:                 Optional[int] = None
    onLeaveCount:                Optional[int] = None
    pendingApprovals:            int

    model_config = ConfigDict(populate_by_name=True)


class DashboardTrendPoint(BaseModel):
    month: str
    gross: Optional[Decimal] = None
    net:   Optional[Decimal] = None
    cost:  Optional[Decimal] = None


class RecentActivityItem(BaseModel):
    id:          str
    description: str
    timestamp:   datetime
    status:      ActivityStatus


class SuccessResponse(BaseModel):
    message: str


# ── Compliance: Documents ─────────────────────────────────────────────

class ExtractedContributionRate(BaseModel):
    id:       Optional[str] = None
    label:    str
    employee: str
    employer: str
    total:    str


class ExtractedTaxSlab(BaseModel):
    id:  Optional[str] = None
    min: str
    max: str
    rate: str
    tax:  str


class ExtractedRequirement(BaseModel):
    label: str
    note:  Optional[str] = None


class ExtractedRegisteredEntityDetails(BaseModel):
    # Common
    name:    Optional[str] = None
    address: Optional[str] = None

    # UK
    registrationNumber:    Optional[str] = None
    vatNumber:             Optional[str] = None
    payeReference:         Optional[str] = None
    utr:                   Optional[str] = None
    accountsReferenceDate: Optional[str] = None

    # India
    pan:     Optional[str] = None
    tan:     Optional[str] = None
    gst:     Optional[str] = None
    pfCode:  Optional[str] = None
    esiCode: Optional[str] = None

    # US
    ein:       Optional[str] = None
    stateId:   Optional[str] = None
    naicsCode: Optional[str] = None


class ExtractedComplianceData(BaseModel):
    contributionRates:      List[ExtractedContributionRate] = []
    taxSlabs:               List[ExtractedTaxSlab] = []
    requirements:           List[ExtractedRequirement] = []
    registeredEntityDetails: Optional[ExtractedRegisteredEntityDetails] = None


class ComplianceDocumentResponse(BaseModel):
    """Shape consumed by payrollService.js / ComplianceDocuments.jsx.
    Field names below are the exact contract documented in
    payrollService.js's uploadComplianceDocument() comment block —
    `response_model_by_alias=True` on the route serializes these as
    camelCase for the frontend while the Python side stays snake_case."""
    id:            int
    fileName:      str = Field(validation_alias="file_name", serialization_alias="fileName")
    title:         Optional[str] = None
    documentType:  Optional[str] = Field(None, validation_alias="document_type", serialization_alias="documentType")
    category:      str = "other"
    description:   Optional[str] = None
    fileSize:      Optional[int] = Field(None, validation_alias="file_size", serialization_alias="fileSize")
    mimeType:      Optional[str] = Field(None, validation_alias="mime_type", serialization_alias="mimeType")
    uploadedBy:    Optional[int] = Field(None, validation_alias="uploaded_by", serialization_alias="uploadedBy")
    uploadedAt:    datetime = Field(validation_alias="uploaded_at", serialization_alias="uploadedAt")
    country:       Optional[str] = None
    status:        str  # "processing" | "parsed" | "failed"
    extracted:     Optional[ExtractedComplianceData] = Field(None, validation_alias="extracted_data", serialization_alias="extracted")
    error:         Optional[str] = Field(None, validation_alias="error_message", serialization_alias="error")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

# ── Hong Kong (ZP-HK-ENG-001) request bodies ────────────────────────────
# Responses are the plain dicts built by hong_kong_service.serialize_* (same
# convention as the Singapore IR21 endpoints).

class _HKBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class HKWorkHoursEntry(_HKBody):
    date: date
    hours: Decimal
    source: Optional[str] = "VERIFIED_TIMESHEET"
    evidenceRef: Optional[str] = None


class HKWorkHoursRequest(_HKBody):
    entries: List[HKWorkHoursEntry]
    reason: Optional[str] = None


class HKDepartureRequest(_HKBody):
    employeeId: int
    expectedDepartureDate: date
    identifiedOn: Optional[date] = None
    returnDate: Optional[date] = None


class HKIr56gFiledRequest(_HKBody):
    filedOn: date
    filingReference: str


class HKReleaseRequest(_HKBody):
    basis: str
    reference: Optional[str] = None
    evidenceRef: str


class HKDepartureChangeRequest(_HKBody):
    reason: str
    evidenceRef: str
    newDepartureDate: Optional[date] = None


class HKAnnualReturnRequest(_HKBody):
    yearOfAssessment: str = Field(pattern=r"^\d{4}/\d{2}$")


class HKIrdTransitionRequest(_HKBody):
    target: str
    filingReference: Optional[str] = None
    receiptReference: Optional[str] = None
    # FILED only: how the employer submitted (recorded from its evidence).
    submissionMode: Optional[str] = None
    authorizedSigner: Optional[str] = None
    transactionReference: Optional[str] = None
    controlListReference: Optional[str] = None
    submittedOn: Optional[date] = None


class HKIrdAmendRequest(_HKBody):
    reason: str
    amendmentType: str = "REPLACEMENT"


class HKReasonRequest(_HKBody):
    reason: str


class HKCorrectionRequest(_HKBody):
    reason: str = Field(min_length=1, max_length=2000)


class HKLegalHoldRequest(_HKBody):
    employeeId: Optional[int] = None
    reason: str = Field(min_length=1, max_length=2000)
    reference: Optional[str] = Field(default=None, max_length=200)


class HKEmployeeCopyRequest(_HKBody):
    evidenceRef: str = Field(min_length=1, max_length=200)


class HKAverageWageRequest(_HKBody):
    benefitType: str
    referenceDate: date
    disregarded: List[dict] = []
    overtimeConstant: bool = False


class HKAverageWageOverrideRequest(_HKBody):
    averageDailyWage: Decimal
    reason: str
    evidenceRef: str


class HKEntitlementRequest(_HKBody):
    benefit: str
    averageWageSnapshotId: int
    date: Optional[date] = None
    days: Optional[Decimal] = None
    sicknessDays: Optional[int] = None
    consecutiveDays: Optional[int] = None
    medicallyCertified: bool = False
    pregnancyRelated: bool = False
    availablePaidSicknessDays: Optional[Decimal] = None
    noticeGiven: bool = False
    documentProvided: bool = False


class HKTerminationRequest(_HKBody):
    terminationDate: date
    reason: str
    postTransitionWage: Decimal
    postTransitionWageBasis: Optional[str] = "LAST_FULL_MONTH"
    preTransitionWage: Optional[Decimal] = None
    preTransitionWageBasis: Optional[str] = None
    payBasis: Optional[str] = None
    offsets: List[dict] = []
    renewalOfferRefused: bool = False
    finalWages: Optional[Decimal] = None
    annualLeavePay: Optional[Decimal] = None
    holidayPay: Optional[Decimal] = None


class HKEmpfPrepareRequest(_HKBody):
    contributionPeriod: str = Field(pattern=r"^\d{4}-\d{2}$")


class HKEmpfTransitionRequest(_HKBody):
    target: str
    submissionReference: Optional[str] = None
    rowOutcomes: Optional[List[dict]] = None
    settlementReference: Optional[str] = None


class HKSalariesTaxEstimateRequest(_HKBody):
    yearOfAssessment: str = Field(pattern=r"^\d{4}/\d{2}$")
    income: Decimal
    deductions: Decimal = Decimal("0")
    allowances: dict = {}
    # Itemised claims, each capped by the engine to the statutory ceiling for the
    # year of assessment: mandatory_contributions, self_education, home_loan_
    # interest, elderly_residential_care, domestic_rents, voluntary_mpf,
    # assisted_reproductive, qvhi_premium, approved_donation.
    deductionClaims: dict = {}
    # Additional HLI / domestic-rent ceiling elections (IRD, from YA 2024/25):
    # home_loan_interest_additional_ceiling, domestic_rents_additional_ceiling.
    elections: List[str] = []


class HKCalculationPreviewRequest(_HKBody):
    payDate: date
    periodStart: Optional[date] = None
    periodEnd: Optional[date] = None
    payFrequency: str = "Monthly"
    gross: Decimal
    dateOfBirth: date
    dateOfJoining: date
    workerFacts: dict = {}
    hours: dict = {}


# ── France (ZP-FR-ENG-001) ───────────────────────────────────────────────
# Endpoints wire 1:1 to service functions; authority data (PAS rates,
# AT/MP rates, DSN lifecycle) is never admin-editable freeform — the
# request models carry provenance so corrections keep lineage (FR §4/§10/§13).

class EmployerFranceProfileUpsert(BaseModel):
    """Super-admin/provider upsert of the org 1:1 France employer profile
    (FR §11 panels A/C/D). Deliberately NOT in this payload: pas_crm_status
    (authority-held), effectif (governed history — record/correct it via
    the effectif endpoints) and readiness (computed from real checks; LIVE
    only via the go-live action) — so a profile save can never overwrite
    them wholesale."""
    siren:                  str
    legalName:              Optional[str] = None
    legalForm:              Optional[str] = None
    address:                Optional[str] = None
    payrollContact:         Optional[str] = None
    # Convention collective — mandatory or explicitly "unknown under review"
    # (FR-035); never silently defaulted to the Code du travail floor.
    idcc:                   Optional[str] = None
    idccStatus:             Optional[str] = None  # APPLICABLE | NOT_APPLICABLE | UNDER_REVIEW
    urssafAccount:          Optional[str] = None
    dsnDeclarant:           Optional[str] = None
    # M5 (50+ / 5th of M+1) | M15 (<50 / 15th of M+1) | DEFERRED_M15
    filingDueDateClass:     str = Field("M15", validation_alias="filingDueDateClass")
    paymentMandateRef:      Optional[str] = None
    pasCollectorIdentity:   Optional[str] = None
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class FranceEstablishmentUpsert(BaseModel):
    """A SIRET establishment of the employer (FR §11 panel B)."""
    siret:              str
    name:               Optional[str] = None
    address:            Optional[str] = None
    communeInsee:       Optional[str] = None
    workforceLocation:  Optional[str] = None
    payrollIdentifier:  Optional[str] = None
    isActive:           bool = True
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class FranceEstablishmentResponse(BaseModel):
    id:                 int
    organizationId:     int = Field(..., validation_alias="organization_id", serialization_alias="organizationId")
    siret:              str
    name:               Optional[str] = None
    address:            Optional[str] = None
    communeInsee:       Optional[str] = Field(None, validation_alias="commune_insee", serialization_alias="communeInsee")
    workforceLocation:  Optional[str] = Field(None, validation_alias="workforce_location", serialization_alias="workforceLocation")
    payrollIdentifier:  Optional[str] = Field(None, validation_alias="payroll_identifier", serialization_alias="payrollIdentifier")
    isActive:           bool = Field(..., validation_alias="is_active", serialization_alias="isActive")
    createdAt:          Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")
    updatedAt:          Optional[datetime] = Field(None, validation_alias="updated_at", serialization_alias="updatedAt")
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class FranceEstablishmentRatePackUpsert(BaseModel):
    """Effective-dated per-SIRET rate pack (FR-002/FR-013). Every write
    creates a NEW period row (Jan/Jul history preserved); a unique
    (org, siret, effective_from) collision is a clean batch-style error.
    `establishmentId` links the period to the SIRET registry (its SIRET and
    commune then come from the establishment)."""
    establishmentId:      Optional[int] = None
    siret:                Optional[str] = None
    communeInsee:         Optional[str] = None
    workplaceLabel:       Optional[str] = None
    atMpRatePct:          Optional[Decimal] = None
    atMpRiskCode:         Optional[str] = None
    atMpEvidence:         Optional[str] = None
    atMpSource:           Optional[str] = None
    vmRatePct:            Optional[Decimal] = None
    vmThresholdApplies:   Optional[bool] = None
    vmSource:             Optional[str] = None
    vmEvidence:           Optional[str] = None
    agsSpecialStatus:     Optional[str] = None
    fnalClass:            Optional[str] = None  # UNDER_50 | OVER_50
    cfpClass:             Optional[str] = None  # UNDER_11 | OVER_11
    effectif:             Optional[int] = None
    effectiveFrom:        date
    effectiveTo:          Optional[date] = None
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class FranceEstablishmentRatePackUpdate(BaseModel):
    """Edit a rate-pack period that has NOT started yet (effective_from in
    the future). A period already in force is never edited in place — add a
    new period instead, so history the payroll ran on stays intact."""
    communeInsee:         Optional[str] = None
    workplaceLabel:       Optional[str] = None
    atMpRatePct:          Optional[Decimal] = None
    atMpRiskCode:         Optional[str] = None
    atMpEvidence:         Optional[str] = None
    atMpSource:           Optional[str] = None
    vmRatePct:            Optional[Decimal] = None
    vmThresholdApplies:   Optional[bool] = None
    vmSource:             Optional[str] = None
    vmEvidence:           Optional[str] = None
    agsSpecialStatus:     Optional[str] = None
    fnalClass:            Optional[str] = None
    cfpClass:             Optional[str] = None
    effectif:             Optional[int] = None
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class FranceRatePackClose(BaseModel):
    """Close an open rate-pack period (e.g. establishment closed)."""
    effectiveTo:  date
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class FrancePASRateUpsert(BaseModel):
    """PAS rate intake (FR-008/FR-010). PERSONALIZED carries the DGFiP CRM
    rate with authority provenance; NEUTRAL rows carry no percentage (the
    engine resolves the neutral grid from the payroll date)."""
    employeeId:      int
    rateType:        str  # PERSONALIZED | NEUTRAL
    ratePct:         Optional[Decimal] = None
    dgfipRateId:     Optional[str] = None
    crmReference:    Optional[str] = None     # DGFiP CRM message the PERSONALIZED rate came from
    source:          Optional[str] = None     # derived: CRM for PERSONALIZED, NEUTRAL_GRID for NEUTRAL
    receivedDate:    Optional[date] = None
    effectiveFrom:   date
    effectiveTo:     Optional[date] = None
    correctionOfId:  Optional[int] = None
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class FranceEffectifRecord(BaseModel):
    year:    int
    value:   int
    source:  str
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class FranceEffectifCorrection(BaseModel):
    """Correct an already-recorded year: the previous value is kept in that
    year's `history`, never silently overwritten (FR-015/FR-036)."""
    year:    int
    value:   int
    source:  str
    reason:  str
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class FranceGoLiveRequest(BaseModel):
    """Mark an org's France payroll LIVE — only accepted when every computed
    readiness check passes (gate H); `evidence` is kept on the profile."""
    evidence: Optional[dict] = None
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class FranceDsnSubmissionCreate(BaseModel):
    """Body for opening a FranceDsnSubmission. periodEnd defaults to the
    month end of periodStart; the service computes payload_hash, due_date
    (from the profile's filing_due_date_class) and runs the FR-031
    pre-submit validator (READY profile, effective SIRET pack, resolved
    PAS, governed effectif)."""
    periodStart: date
    periodEnd:   Optional[date] = None
    releaseRef:  str
    # Open a correction of an earlier submission for the same period; the
    # original stays immutable (FR-033/FR-053).
    correctionOfId: Optional[int] = None
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class FranceDsnStatusUpdate(BaseModel):
    status:        str  # DRAFT|VALIDATED|QUEUED|TRANSMITTED|ACKNOWLEDGED|BUSINESS_REJECTED|CRM_RESOLVED|UNKNOWN|SETTLED
    technicalAck:  Optional[str] = None  # e.g. "OK"
    businessCrm:   Optional[dict] = None # report/anomaly codes
    paymentState:  Optional[str] = None  # SEPA/direct-debit state
    blockedReason: Optional[str] = None
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class FranceDsnOutboxCreate(BaseModel):
    submissionId: int
    action:       str  # TRANSMIT | PAS_RATE_EXCHANGE | CRM_CLOSE | CORRECTION
    payload:      Optional[dict] = None
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class FranceDsnSubmissionResponse(BaseModel):
    id:                 int
    organizationId:     int = Field(..., validation_alias="organization_id", serialization_alias="organizationId")
    dsnVersion:         str = Field(..., validation_alias="dsn_version", serialization_alias="dsnVersion")
    releaseRef:         str = Field(..., validation_alias="release_ref", serialization_alias="releaseRef")
    payloadHash:        str = Field(..., validation_alias="payload_hash", serialization_alias="payloadHash")
    periodStart:        date = Field(..., validation_alias="period_start", serialization_alias="periodStart")
    periodEnd:          date = Field(..., validation_alias="period_end", serialization_alias="periodEnd")
    dueDate:            date = Field(..., validation_alias="due_date", serialization_alias="dueDate")
    status:             str
    validationErrors:   Optional[list] = Field(None, validation_alias="validation_errors", serialization_alias="validationErrors")
    blockedReason:      Optional[str] = Field(None, validation_alias="blocked_reason", serialization_alias="blockedReason")
    technicalAck:       Optional[str] = Field(None, validation_alias="technical_ack", serialization_alias="technicalAck")
    businessCrm:        Optional[dict] = Field(None, validation_alias="business_crm", serialization_alias="businessCrm")
    paymentState:       Optional[str] = Field(None, validation_alias="payment_state", serialization_alias="paymentState")
    correctionOfId:     Optional[int] = Field(None, validation_alias="correction_of_id", serialization_alias="correctionOfId")
    submittedAt:        Optional[datetime] = Field(None, validation_alias="submitted_at", serialization_alias="submittedAt")
    acknowledgedAt:      Optional[datetime] = Field(None, validation_alias="acknowledged_at", serialization_alias="acknowledgedAt")
    createdAt:          Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")
    updatedAt:          Optional[datetime] = Field(None, validation_alias="updated_at", serialization_alias="updatedAt")
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class EmployerFranceProfileResponse(BaseModel):
    id:                  int
    organizationId:      int = Field(..., validation_alias="organization_id", serialization_alias="organizationId")
    siren:               str
    legalName:           Optional[str] = Field(None, validation_alias="legal_name", serialization_alias="legalName")
    legalForm:           Optional[str] = Field(None, validation_alias="legal_form", serialization_alias="legalForm")
    address:             Optional[str] = None
    payrollContact:      Optional[str] = Field(None, validation_alias="payroll_contact", serialization_alias="payrollContact")
    idcc:                Optional[str] = None
    idccStatus:          Optional[str] = Field(None, validation_alias="idcc_status", serialization_alias="idccStatus")
    urssafAccount:       Optional[str] = Field(None, validation_alias="urssaf_account", serialization_alias="urssafAccount")
    dsnDeclarant:        Optional[str] = Field(None, validation_alias="dsn_declarant", serialization_alias="dsnDeclarant")
    filingDueDateClass:  str = Field(..., validation_alias="filing_due_date_class", serialization_alias="filingDueDateClass")
    paymentMandateRef:   Optional[str] = Field(None, validation_alias="payment_mandate_ref", serialization_alias="paymentMandateRef")
    pasCollectorIdentity: Optional[str] = Field(None, validation_alias="pas_collector_identity", serialization_alias="pasCollectorIdentity")
    pasCrmStatus:        str = Field(..., validation_alias="pas_crm_status", serialization_alias="pasCrmStatus")
    effectifState:       Optional[dict] = Field(None, validation_alias="effectif_state", serialization_alias="effectifState")
    readinessStatus:     str = Field(..., validation_alias="readiness_status", serialization_alias="readinessStatus")
    readinessEvidence:   Optional[dict] = Field(None, validation_alias="readiness_evidence", serialization_alias="readinessEvidence")
    createdAt:           Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")
    updatedAt:           Optional[datetime] = Field(None, validation_alias="updated_at", serialization_alias="updatedAt")
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Italy F24 (§16, IT-043/IT-046) ─────────────────────────────────────────
# A F24 is a PAYMENT INSTRUCTION. Every one of its rows must name a real
# "codice tributo / causale" and the right section, or the instruction is not
# merely incomplete, it is wrong. That single fact drives the whole shape of
# this API:
#
#   * There is no default, fallback, or "best guess" causale anywhere in this
#     module. `taxCode` is required and must already exist in the governed
#     catalog, because IT-043 forbids inventing one.
#   * The catalog ships empty and is populated only from the Agenzia delle
#     Entrate catalogs by a Super Admin, so `build` is expected to refuse until
#     it has been. Refusing loudly is the correct behaviour, not a gap to fill.
#   * Lines are derived from COMMITTED payroll only (IT-044). A draft run is
#     rejected rather than estimated, since an F24 built from a draft pays money
#     that may never be owed.

class ItalyF24CausaleUpsert(BaseModel):
    """Record a governed F24 causale for one snapshot component.

    `componentKey` addresses a path this platform already computed and stored on
    PayslipItem.it_calculation_snapshot - "inps.employer", "irpef.withheld",
    "localTax.regionalSaldo" and so on. Binding the causale to a fact we
    actually computed means the F24 line cannot drift from the payslip it
    settles; inventing a parallel re-derivation is exactly the failure mode
    IT-043 exists to prevent.

    Creating a new row for an existing (section, component) does NOT overwrite
    the old one. Supply `effectiveTo` on the outgoing row and open a new
    `effectiveFrom`: F24 causali change over time, and retroactively editing the
    code that was in force for a period already filed would corrupt the audit
    trail the archived filing depends on (IT-060).
    """
    organizationId:     Optional[int] = None   # never trusted; tenancy comes from the caller
    section:            str = Field(..., min_length=1, max_length=20)
    componentKey:       str = Field(..., min_length=1, max_length=40)
    taxCode:            str = Field(..., min_length=1, max_length=10)
    requiresRegion:     bool = False
    requiresComune:     bool = False
    # Required, and deliberately not defaulted. Whether a component increases or
    # offsets the amount due on its F24 line is a fact about that causale, so it
    # has to be stated by whoever records the code rather than inferred from the
    # component's name. A default here would let a missing decision become a
    # silent DEBIT.
    direction:          str
    effectiveFrom:      date
    effectiveTo:        Optional[date] = None
    sourceDocumentId:   Optional[int] = None
    notes:              Optional[str] = None
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class ItalyF24CausaleResponse(BaseModel):
    id:                 int
    organizationId:     int = Field(..., validation_alias="organization_id", serialization_alias="organizationId")
    section:            str
    componentKey:       str = Field(..., validation_alias="component_key", serialization_alias="componentKey")
    taxCode:            str = Field(..., validation_alias="tax_code", serialization_alias="taxCode")
    requiresRegion:     bool = Field(..., validation_alias="requires_region", serialization_alias="requiresRegion")
    requiresComune:     bool = Field(..., validation_alias="requires_comune", serialization_alias="requiresComune")
    direction:          str
    effectiveFrom:      date = Field(..., validation_alias="effective_from", serialization_alias="effectiveFrom")
    effectiveTo:        Optional[date] = Field(None, validation_alias="effective_to", serialization_alias="effectiveTo")
    sourceDocumentId:   Optional[int] = Field(None, validation_alias="source_document_id", serialization_alias="sourceDocumentId")
    status:             str  # Draft | Approved | Superseded
    notes:              Optional[str] = None
    createdById:        Optional[int] = Field(None, validation_alias="created_by_id", serialization_alias="createdById")
    approvedById:       Optional[int] = Field(None, validation_alias="approved_by_id", serialization_alias="approvedById")
    createdAt:          Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")
    updatedAt:          Optional[datetime] = Field(None, validation_alias="updated_at", serialization_alias="updatedAt")
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ItalyF24BuildRequest(BaseModel):
    """Derive the payable F24 lines for one committed run and reference period.

    `referencePeriod` is the F24 "periodo di riferimento" (MM/YYYY). The caller
    supplies it rather than the server inferring it, because the period and the
    run are two independent facts and silently deriving one from the other is
    how a December liability lands in the wrong month.
    """
    organizationId:     Optional[int] = None   # never trusted
    payrollRunId:       int
    referencePeriod:    str = Field(..., min_length=7, max_length=7)  # MM/YYYY
    statutoryFilingId:  Optional[int] = None
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class ItalyF24LineResponse(BaseModel):
    id:                 int
    organizationId:     int = Field(..., validation_alias="organization_id", serialization_alias="organizationId")
    statutoryFilingId:  Optional[int] = Field(None, validation_alias="statutory_filing_id", serialization_alias="statutoryFilingId")
    payrollRunId:       Optional[int] = Field(None, validation_alias="payroll_run_id", serialization_alias="payrollRunId")
    section:            str
    taxCode:            str = Field(..., validation_alias="tax_code", serialization_alias="taxCode")
    regionCode:         Optional[str] = Field(None, validation_alias="region_code", serialization_alias="regionCode")
    comuneCode:         Optional[str] = Field(None, validation_alias="comune_code", serialization_alias="comuneCode")
    referencePeriod:    str = Field(..., validation_alias="reference_period", serialization_alias="referencePeriod")
    debitAmount:        Decimal = Field(..., validation_alias="debit_amount", serialization_alias="debitAmount")
    creditAmount:       Decimal = Field(..., validation_alias="credit_amount", serialization_alias="creditAmount")
    sourceLines:        Optional[list] = Field(None, validation_alias="source_lines", serialization_alias="sourceLines")
    createdAt:          Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Italy Libro Unico del Lavoro (§20, IT-058/IT-059/IT-060) ───────────────
# IT-058: "an auditable statutory record, not a PDF theme" — sequence,
# inalterability, retention and the authorized method are engineering
# requirements. These schemas keep the caller from supplying any of the four:
# the service allocates the sequence, hashes the content, advances the retention
# horizon, and reads the authorized method off the employer profile. A request
# body that could set a sequence number or a retention date would let a caller
# forge the audit trail from outside it.

class ItalyLulBuildRequest(BaseModel):
    """Register one committed run's payslips in the LUL for a reference month.

    `eventKind` is the statutory event and is deliberately NOT validated against
    a closed list: spec source S10 (the official LUL catalog) is not yet
    available, and inventing the vocabulary would be the same error as inventing
    an F24 causale (IT-043). It is recorded as governed data instead.
    """
    organizationId:     Optional[int] = None   # never trusted
    payrollRunId:       int
    referenceMonth:     str = Field(..., min_length=7, max_length=7, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")  # YYYY-MM
    eventKind:          Optional[str] = Field(None, max_length=40)
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class ItalyLulCorrectionRequest(BaseModel):
    """Correct a registered LUL entry. Required `reason` — see the schema note."""
    organizationId:     Optional[int] = None
    reason:             str = Field(..., min_length=1, max_length=500)
    eventKind:          Optional[str] = Field(None, max_length=40)
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class ItalyLulEntryResponse(BaseModel):
    id:                 int
    organizationId:     int = Field(..., validation_alias="organization_id", serialization_alias="organizationId")
    employeeId:         int = Field(..., validation_alias="employee_id", serialization_alias="employeeId")
    referenceMonth:     str = Field(..., validation_alias="reference_month", serialization_alias="referenceMonth")
    sequenceNumber:     int = Field(..., validation_alias="sequence_number", serialization_alias="sequenceNumber")
    entryType:          str = Field(..., validation_alias="entry_type", serialization_alias="entryType")
    correctsEntryId:    Optional[int] = Field(None, validation_alias="corrects_entry_id", serialization_alias="correctsEntryId")
    payslipItemId:      Optional[int] = Field(None, validation_alias="payslip_item_id", serialization_alias="payslipItemId")
    payrollRunId:       Optional[int] = Field(None, validation_alias="payroll_run_id", serialization_alias="payrollRunId")
    contentHash:        str = Field(..., validation_alias="content_hash", serialization_alias="contentHash")
    payload:            Optional[dict] = Field(None)
    eventKind:          Optional[str] = Field(None, validation_alias="event_kind", serialization_alias="eventKind")
    method:             Optional[str] = None
    registeredReference: Optional[str] = Field(None, validation_alias="registered_reference", serialization_alias="registeredReference")
    registeredAt:       Optional[datetime] = Field(None, validation_alias="registered_at", serialization_alias="registeredAt")
    retentionUntil:     Optional[date] = Field(None, validation_alias="retention_until", serialization_alias="retentionUntil")
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ItalyLulIntegrityResponse(BaseModel):
    """IT-058 inalterability, made checkable rather than merely asserted."""
    entries:                      int
    firstSequence:                Optional[int] = None
    lastSequence:                 Optional[int] = None
    sequenceGaps:                 List[int] = Field(default_factory=list)
    driftedSequenceNumbers:       List[int] = Field(default_factory=list)
    unverifiableSequenceNumbers:  List[int] = Field(default_factory=list)
    earliestRetentionUntil:       Optional[date] = None
    verifiedAt:                   str
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Italy TFR (§13, IT-037/IT-038/IT-039/IT-040/IT-041) ───────────────────
# TFR is a LIABILITY ledger (IT-037), not an earning. The destination in force
# for each entry is recorded (IT-038), revaluation is annual on prior balances
# with a substitute tax (IT-039), and the Fondo Tesoreria threshold depends on
# prior-year average headcount (IT-040/IT-041).

class ItalyTfrAccrualRequest(BaseModel):
    """Post TFR accruals for one committed run (APPROVED or later)."""
    organizationId:     Optional[int] = None   # never trusted
    payrollRunId:       int
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class ItalyTfrRevaluationRequest(BaseModel):
    """Post annual TFR revaluation on prior-year balances."""
    organizationId:         Optional[int] = None
    taxYear:                int
    istatFoiIncreasePct:    Decimal
    months:                 int = 12
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class ItalyTfrLedgerEntryResponse(BaseModel):
    id:                 int
    organizationId:     int = Field(..., validation_alias="organization_id", serialization_alias="organizationId")
    employeeId:         Optional[int] = Field(None, validation_alias="employee_id", serialization_alias="employeeId")
    entryType:          str = Field(..., validation_alias="entry_type", serialization_alias="entryType")
    taxYear:            int = Field(..., validation_alias="tax_year", serialization_alias="taxYear")
    entryDate:          date = Field(..., validation_alias="entry_date", serialization_alias="entryDate")
    amount:             Decimal
    destination:        Optional[str] = None
    pensionFund:        Optional[str] = Field(None, validation_alias="pension_fund", serialization_alias="pensionFund")
    payslipItemId:      Optional[int] = Field(None, validation_alias="payslip_item_id", serialization_alias="payslipItemId")
    payrollRunId:       Optional[int] = Field(None, validation_alias="payroll_run_id", serialization_alias="payrollRunId")
    reversesEntryId:    Optional[int] = Field(None, validation_alias="reverses_entry_id", serialization_alias="reversesEntryId")
    evidence:           Optional[dict] = None
    idempotencyKey:     str = Field(..., validation_alias="idempotency_key", serialization_alias="idempotencyKey")
    createdAt:          Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ItalyTfrBalanceResponse(BaseModel):
    total:              str
    byDestination:      Dict[str, str]
    asOfYear:           Optional[int] = None


class ItalyTfrIdempotencyResponse(BaseModel):
    duplicateCount:     int
    duplicateKeys:      List[str] = Field(default_factory=list)
    checkedAt:          str


class FranceEstablishmentRatePackResponse(BaseModel):
    id:                 int
    organizationId:     int = Field(..., validation_alias="organization_id", serialization_alias="organizationId")
    establishmentId:    Optional[int] = Field(None, validation_alias="establishment_id", serialization_alias="establishmentId")
    siret:              str
    communeInsee:       Optional[str] = Field(None, validation_alias="commune_insee", serialization_alias="communeInsee")
    workplaceLabel:     Optional[str] = Field(None, validation_alias="workplace_label", serialization_alias="workplaceLabel")
    atMpRatePct:        Optional[Decimal] = Field(None, validation_alias="at_mp_rate_pct", serialization_alias="atMpRatePct")
    atMpRiskCode:       Optional[str] = Field(None, validation_alias="at_mp_risk_code", serialization_alias="atMpRiskCode")
    atMpEvidence:       Optional[str] = Field(None, validation_alias="at_mp_evidence", serialization_alias="atMpEvidence")
    atMpSource:         Optional[str] = Field(None, validation_alias="at_mp_source", serialization_alias="atMpSource")
    vmRatePct:          Optional[Decimal] = Field(None, validation_alias="vm_rate_pct", serialization_alias="vmRatePct")
    vmThresholdApplies: Optional[bool] = Field(None, validation_alias="vm_threshold_applies", serialization_alias="vmThresholdApplies")
    vmSource:           Optional[str] = Field(None, validation_alias="vm_source", serialization_alias="vmSource")
    vmEvidence:         Optional[str] = Field(None, validation_alias="vm_evidence", serialization_alias="vmEvidence")
    agsSpecialStatus:   Optional[str] = Field(None, validation_alias="ags_special_status", serialization_alias="agsSpecialStatus")
    fnalClass:          Optional[str] = Field(None, validation_alias="fnal_class", serialization_alias="fnalClass")
    cfpClass:           Optional[str] = Field(None, validation_alias="cfp_class", serialization_alias="cfpClass")
    effectif:           Optional[int] = None
    effectiveFrom:      date = Field(..., validation_alias="effective_from", serialization_alias="effectiveFrom")
    effectiveTo:        Optional[date] = Field(None, validation_alias="effective_to", serialization_alias="effectiveTo")
    createdAt:          Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class FrancePASRateResponse(BaseModel):
    id:                 int
    organizationId:     int = Field(..., validation_alias="organization_id", serialization_alias="organizationId")
    employeeId:         int = Field(..., validation_alias="employee_id", serialization_alias="employeeId")
    rateType:           str = Field(..., validation_alias="rate_type", serialization_alias="rateType")
    ratePct:            Optional[Decimal] = Field(None, validation_alias="rate_pct", serialization_alias="ratePct")
    dgfipRateId:        Optional[str] = Field(None, validation_alias="dgfip_rate_id", serialization_alias="dgfipRateId")
    crmReference:       Optional[str] = Field(None, validation_alias="crm_reference", serialization_alias="crmReference")
    source:             str
    receivedDate:       Optional[date] = Field(None, validation_alias="received_date", serialization_alias="receivedDate")
    effectiveFrom:      date = Field(..., validation_alias="effective_from", serialization_alias="effectiveFrom")
    effectiveTo:        Optional[date] = Field(None, validation_alias="effective_to", serialization_alias="effectiveTo")
    status:             str
    correctionOfId:     Optional[int] = Field(None, validation_alias="correction_of_id", serialization_alias="correctionOfId")
    createdAt:          Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class FranceDsnOutboxItemResponse(BaseModel):
    id:                 int
    submissionId:       int = Field(..., validation_alias="submission_id", serialization_alias="submissionId")
    action:             str
    payload:            Optional[dict] = None
    idempotencyKey:     str = Field(..., validation_alias="idempotency_key", serialization_alias="idempotencyKey")
    status:             str  # PENDING|SENT|UNKNOWN|ACKNOWLEDGED|FAILED
    attempts:           int
    lastError:          Optional[str] = Field(None, validation_alias="last_error", serialization_alias="lastError")
    sentAt:             Optional[datetime] = Field(None, validation_alias="sent_at", serialization_alias="sentAt")
    acknowledgedAt:     Optional[datetime] = Field(None, validation_alias="acknowledged_at", serialization_alias="acknowledgedAt")
    createdAt:          Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Ireland (ZP-IE-ENG-001) ──────────────────────────────────────────────
# RPN (Revenue Payroll Notification) ingestion & retrieval (IE-005, IE-022,
# IE-033, IE-045). The snapshot is content-addressed by raw_hash so a
# historical payroll is always reproducible from the exact authority response.

class IrelandRpnSnapshotUpsert(BaseModel):
    """Ingest a frozen Revenue Payroll Notification (IE-005/IE-022).

    The raw_hash MUST be a deterministic SHA-256 (or equivalent) over the
    full authority JSON response. If the same raw_hash is submitted again for
    the same employee/tax_year, the existing snapshot is returned (no
    duplicate). A genuine change in the authority response creates a new
immutable row — the historical payroll must always be reproducible from the
    exact snapshot that was in force (IE-045)."""
    # Optional and NEVER trusted: tenancy comes from the authenticated caller,
    # so a body can never name another organization. Required-but-ignored would
    # only invite a caller to believe the value did something.
    organizationId:           Optional[int] = None
    employeeId:               int
    rpnNumber:                str
    issuedAt:                 str   # ISO-8601 datetime
    taxYear:                  str   # "2026"
    calculationBasis:         str   # CUMULATIVE | WEEK_1 | EMERGENCY
    ppsnSupplied:             bool
    standardRateBand:         Optional[Decimal] = None
    taxCredit:                Optional[Decimal] = None
    standardRateBandPeriod:   Optional[Decimal] = None
    taxCreditPeriod:          Optional[Decimal] = None
    previousTaxablePayYtd:    Optional[Decimal] = None
    previousPayYtd:           Optional[Decimal] = None
    periodsElapsed:           Optional[int] = None
    lptInstructed:            bool
    lptRatePct:               Optional[Decimal] = None
    emergencyTaxCreditWeekly: Optional[Decimal] = None
    rawHash:                  str   # SHA-256 of the full authority response
    rawPayload:               Optional[dict] = None
    statutoryProfileId:       Optional[int] = None
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class IrelandRpnSnapshotResponse(BaseModel):
    id:                     int
    organizationId:         int = Field(..., validation_alias="organization_id", serialization_alias="organizationId")
    employeeId:             int = Field(..., validation_alias="employee_id", serialization_alias="employeeId")
    statutoryProfileId:     Optional[int] = Field(None, validation_alias="statutory_profile_id", serialization_alias="statutoryProfileId")
    rpnNumber:              str
    issuedAt:               datetime = Field(..., validation_alias="issued_at", serialization_alias="issuedAt")
    taxYear:                str
    calculationBasis:       str = Field(..., validation_alias="calculation_basis", serialization_alias="calculationBasis")
    ppsnSupplied:           bool
    standardRateBand:       Optional[Decimal] = Field(None, validation_alias="standard_rate_band", serialization_alias="standardRateBand")
    taxCredit:              Optional[Decimal] = Field(None, validation_alias="tax_credit", serialization_alias="taxCredit")
    standardRateBandPeriod: Optional[Decimal] = Field(None, validation_alias="standard_rate_band_period", serialization_alias="standardRateBandPeriod")
    taxCreditPeriod:        Optional[Decimal] = Field(None, validation_alias="tax_credit_period", serialization_alias="taxCreditPeriod")
    previousTaxablePayYtd:  Optional[Decimal] = Field(None, validation_alias="previous_taxable_pay_ytd", serialization_alias="previousTaxablePayYtd")
    previousPayYtd:         Optional[Decimal] = Field(None, validation_alias="previous_pay_ytd", serialization_alias="previousPayYtd")
    periodsElapsed:         Optional[int] = Field(None, validation_alias="periods_elapsed", serialization_alias="periodsElapsed")
    lptInstructed:          bool
    lptRatePct:             Optional[Decimal] = Field(None, validation_alias="lpt_rate_pct", serialization_alias="lptRatePct")
    emergencyTaxCreditWeekly: Optional[Decimal] = Field(None, validation_alias="emergency_tax_credit_weekly", serialization_alias="emergencyTaxCreditWeekly")
    rawHash:                str = Field(..., validation_alias="raw_hash", serialization_alias="rawHash")
    rawPayload:             Optional[dict] = Field(None, validation_alias="raw_payload", serialization_alias="rawPayload")
    isStale:                bool = Field(..., validation_alias="is_stale", serialization_alias="isStale")
    retrievedAt:            Optional[datetime] = Field(None, validation_alias="retrieved_at", serialization_alias="retrievedAt")
    createdAt:              Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ═══════════════════════════════════════════════════════════════════════════
# Sweden (ZP-SE-ENG-001) — CBA registry, sick episodes, leave ledger, and
# the §37 activation-readiness checklist. Same camelCase alias discipline as
# everything above; same Draft→approval status vocabulary as JurisdictionPack.
# ═══════════════════════════════════════════════════════════════════════════

class CollectiveAgreementUpsert(BaseModel):
    id: Optional[int] = None
    jurisdictionCountry: str
    organizationId: Optional[int] = None
    agreementCode: str
    name: str
    # EMPLOYER_SPECIFIC | SECTOR | LOCAL_SUPPLEMENT — never "NATIONAL"
    # (spec §44: no Swedish national default CBA).
    agreementType: str
    employerScope: Optional[str] = None
    employeeGroup: Optional[str] = None
    occupation: Optional[str] = None
    grade: Optional[str] = None
    version: str = "1.0"
    effectiveFrom: Optional[date] = None
    effectiveTo: Optional[date] = None
    status: str = "Draft"
    # Governed modules this agreement configures (spec §9): wage_scales,
    # overtime, unsocial_hours, sickness_supplements, parental_pay,
    # vacation_enhancement, occupational_pension, insurance, termination.
    modules: Optional[List[str]] = None
    sourceDocumentId: Optional[int] = None
    previousVersionId: Optional[int] = None
    notes: Optional[str] = None
    reason: Optional[str] = None


class CollectiveAgreementResponse(BaseModel):
    id: int
    jurisdictionCountry: str = Field(validation_alias="jurisdiction_country", serialization_alias="jurisdictionCountry")
    organizationId: Optional[int] = Field(None, validation_alias="organization_id", serialization_alias="organizationId")
    agreementCode: str = Field(validation_alias="agreement_code", serialization_alias="agreementCode")
    name: str
    agreementType: str = Field(validation_alias="agreement_type", serialization_alias="agreementType")
    employerScope: Optional[str] = Field(None, validation_alias="employer_scope", serialization_alias="employerScope")
    employeeGroup: Optional[str] = Field(None, validation_alias="employee_group", serialization_alias="employeeGroup")
    occupation: Optional[str] = None
    grade: Optional[str] = None
    version: str
    effectiveFrom: Optional[date] = Field(None, validation_alias="effective_from", serialization_alias="effectiveFrom")
    effectiveTo: Optional[date] = Field(None, validation_alias="effective_to", serialization_alias="effectiveTo")
    status: str
    modules: Optional[List[str]] = None
    sourceDocumentId: Optional[int] = Field(None, validation_alias="source_document_id", serialization_alias="sourceDocumentId")
    previousVersionId: Optional[int] = Field(None, validation_alias="previous_version_id", serialization_alias="previousVersionId")
    approvedById: Optional[int] = Field(None, validation_alias="approved_by_id", serialization_alias="approvedById")
    createdById: Optional[int] = Field(None, validation_alias="created_by_id", serialization_alias="createdById")
    notes: Optional[str] = None
    createdAt: Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")
    updatedAt: Optional[datetime] = Field(None, validation_alias="updated_at", serialization_alias="updatedAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class CollectiveAgreementStatusUpdate(BaseModel):
    status: str
    reason: Optional[str] = Field(None, max_length=1000)


class SwedenSickEpisodeUpsert(BaseModel):
    id: Optional[int] = None
    employeeId: int
    episodeStart: date
    episodeEnd: Optional[date] = None
    recurrenceGroupId: Optional[int] = None
    workCapacityPct: Optional[Decimal] = None
    expectedWeeklySickPay: Optional[Decimal] = None
    qualifyingDeductionPct: Optional[Decimal] = None
    qualifyingDeductionAmount: Optional[Decimal] = None
    deductionAlreadyApplied: bool = False
    employerPeriodDayFrom: Optional[int] = None
    employerPeriodDayTo: Optional[int] = None
    transferToForsakringskassan: bool = False
    medicalCertificateRef: Optional[str] = None
    absenceReported: bool = False
    employerSickPayAmount: Optional[Decimal] = None
    cbaSupplementAmount: Optional[Decimal] = None
    cbaAgreementId: Optional[int] = None
    status: str = "OPEN"
    source: Optional[str] = None


class SwedenSickEpisodeResponse(BaseModel):
    id: int
    organizationId: int = Field(validation_alias="organization_id", serialization_alias="organizationId")
    employeeId: int = Field(validation_alias="employee_id", serialization_alias="employeeId")
    episodeStart: date = Field(validation_alias="episode_start", serialization_alias="episodeStart")
    episodeEnd: Optional[date] = Field(None, validation_alias="episode_end", serialization_alias="episodeEnd")
    recurrenceGroupId: Optional[int] = Field(None, validation_alias="recurrence_group_id", serialization_alias="recurrenceGroupId")
    workCapacityPct: Optional[Decimal] = Field(None, validation_alias="work_capacity_pct", serialization_alias="workCapacityPct")
    expectedWeeklySickPay: Optional[Decimal] = Field(None, validation_alias="expected_weekly_sick_pay", serialization_alias="expectedWeeklySickPay")
    qualifyingDeductionPct: Optional[Decimal] = Field(None, validation_alias="qualifying_deduction_pct", serialization_alias="qualifyingDeductionPct")
    qualifyingDeductionAmount: Optional[Decimal] = Field(None, validation_alias="qualifying_deduction_amount", serialization_alias="qualifyingDeductionAmount")
    deductionAlreadyApplied: bool = Field(validation_alias="deduction_already_applied", serialization_alias="deductionAlreadyApplied")
    employerPeriodDayFrom: Optional[int] = Field(None, validation_alias="employer_period_day_from", serialization_alias="employerPeriodDayFrom")
    employerPeriodDayTo: Optional[int] = Field(None, validation_alias="employer_period_day_to", serialization_alias="employerPeriodDayTo")
    transferToForsakringskassan: bool = Field(validation_alias="transfer_to_forsakringskassan", serialization_alias="transferToForsakringskassan")
    medicalCertificateRef: Optional[str] = Field(None, validation_alias="medical_certificate_ref", serialization_alias="medicalCertificateRef")
    absenceReported: bool = Field(validation_alias="absence_reported", serialization_alias="absenceReported")
    employerSickPayAmount: Optional[Decimal] = Field(None, validation_alias="employer_sick_pay_amount", serialization_alias="employerSickPayAmount")
    cbaSupplementAmount: Optional[Decimal] = Field(None, validation_alias="cba_supplement_amount", serialization_alias="cbaSupplementAmount")
    cbaAgreementId: Optional[int] = Field(None, validation_alias="cba_agreement_id", serialization_alias="cbaAgreementId")
    status: str
    source: Optional[str] = None
    createdAt: Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")
    updatedAt: Optional[datetime] = Field(None, validation_alias="updated_at", serialization_alias="updatedAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SwedenLeaveLedgerUpsert(BaseModel):
    id: Optional[int] = None
    employeeId: int
    entitlementYear: str
    qualifyingYear: Optional[str] = None
    paidDays: Decimal = Decimal("0")
    unpaidDays: Decimal = Decimal("0")
    savedDays: Decimal = Decimal("0")
    carryoverDays: Decimal = Decimal("0")
    carryoverExpiry: Optional[date] = None
    qualifyingEarnings: Optional[Decimal] = None
    # PERCENTAGE_12 | SAME_PAY | CBA_OVERRIDE (spec §7)
    vacationPayMethod: str = "PERCENTAGE_12"
    creditedAbsence: Optional[dict] = None
    finalVacationAllowance: Optional[Decimal] = None
    cbaAgreementId: Optional[int] = None
    effectiveFrom: Optional[date] = None
    effectiveTo: Optional[date] = None
    version: str = "1.0"
    status: str = "Draft"


class SwedenLeaveLedgerResponse(BaseModel):
    id: int
    organizationId: int = Field(validation_alias="organization_id", serialization_alias="organizationId")
    employeeId: int = Field(validation_alias="employee_id", serialization_alias="employeeId")
    entitlementYear: str = Field(validation_alias="entitlement_year", serialization_alias="entitlementYear")
    qualifyingYear: Optional[str] = Field(None, validation_alias="qualifying_year", serialization_alias="qualifyingYear")
    paidDays: Decimal = Field(validation_alias="paid_days", serialization_alias="paidDays")
    unpaidDays: Decimal = Field(validation_alias="unpaid_days", serialization_alias="unpaidDays")
    savedDays: Decimal = Field(validation_alias="saved_days", serialization_alias="savedDays")
    carryoverDays: Decimal = Field(validation_alias="carryover_days", serialization_alias="carryoverDays")
    carryoverExpiry: Optional[date] = Field(None, validation_alias="carryover_expiry", serialization_alias="carryoverExpiry")
    qualifyingEarnings: Optional[Decimal] = Field(None, validation_alias="qualifying_earnings", serialization_alias="qualifyingEarnings")
    vacationPayMethod: str = Field(validation_alias="vacation_pay_method", serialization_alias="vacationPayMethod")
    creditedAbsence: Optional[dict] = Field(None, validation_alias="credited_absence", serialization_alias="creditedAbsence")
    finalVacationAllowance: Optional[Decimal] = Field(None, validation_alias="final_vacation_allowance", serialization_alias="finalVacationAllowance")
    cbaAgreementId: Optional[int] = Field(None, validation_alias="cba_agreement_id", serialization_alias="cbaAgreementId")
    effectiveFrom: Optional[date] = Field(None, validation_alias="effective_from", serialization_alias="effectiveFrom")
    effectiveTo: Optional[date] = Field(None, validation_alias="effective_to", serialization_alias="effectiveTo")
    version: str
    status: str
    createdAt: Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")
    updatedAt: Optional[datetime] = Field(None, validation_alias="updated_at", serialization_alias="updatedAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SwedenReadinessItem(BaseModel):
    key: str
    label: str
    required: bool
    complete: bool
    detail: Optional[str] = None


class SwedenReadinessResponse(BaseModel):
    """§37 activation-readiness checklist: Sweden must NOT become
    production-active merely because the country record exists."""
    packId: Optional[int] = Field(None, serialization_alias="packId")
    packVersion: Optional[str] = Field(None, serialization_alias="packVersion")
    ready: bool
    items: List[SwedenReadinessItem] = []
    blockers: List[str] = []

class SwedenCalculationPreviewRequest(BaseModel):
    """Read-only Super Admin preview of one Sweden pack (ZP-SE-ENG-001 §13
    "Statutory content console: simulation before activation"). Worker facts
    are supplied inline — nothing is read from or written to an employee."""
    jurisdictionPackId: int
    payDate: date
    gross: Decimal
    cashPay: Optional[Decimal] = None
    dateOfBirth: date
    payFrequency: str = "Monthly"
    taxStatus: str = "A_TAX"
    incomeRole: str = "MAIN_INCOME"
    taxTable: Optional[str] = None
    taxColumn: Optional[str] = None
    sinkStatus: Optional[str] = None
    decisionOverride: bool = False
    decisionId: Optional[str] = None
    decisionEffectiveFrom: Optional[date] = None
    decisionEffectiveTo: Optional[date] = None
    decisionMonthlyWithholding: Optional[Decimal] = None
    decisionRatePct: Optional[Decimal] = None
    annualIncome: Optional[Decimal] = None
    monthToDatePrior: Optional[Decimal] = None
    pensionCostBase: Optional[Decimal] = None
    employeePensionShare: Optional[Decimal] = None
    employerPensionShare: Optional[Decimal] = None


# ── Italy (ZP-IT-ENG-001) — employer profile, readiness, preview ────────────
class ItalyEmployerProfileUpsert(BaseModel):
    """§17 B-G employer facts. readinessStatus is deliberately absent: it is
    RECOMPUTED by italy_service.evaluate_employer_readiness, never set."""
    matricolaInps: Optional[str] = Field(None, max_length=20)
    cscCode: Optional[str] = Field(None, max_length=10)
    caCode: Optional[str] = Field(None, max_length=10)
    atecoCode: Optional[str] = Field(None, max_length=10)
    inpsOffice: Optional[str] = Field(None, max_length=50)
    cnelCode: Optional[str] = Field(None, max_length=20)
    # {"fund": "FIS" | "CIG" | "SECTOR_FUND", "fisBand": "UP_TO_5" | "OVER_5"}
    fundStatus: Optional[dict] = None
    priorYearAvgHeadcount: Optional[int] = None
    tesoreriaStatus: Optional[str] = Field(None, max_length=20)
    f24OperatingModel: Optional[str] = Field(None, max_length=30)
    lulMethod: Optional[str] = Field(None, max_length=30)


class ItalyEmployerProfileResponse(BaseModel):
    id: int
    organizationId: int = Field(validation_alias="organization_id", serialization_alias="organizationId")
    matricolaInps: Optional[str] = Field(None, validation_alias="matricola_inps", serialization_alias="matricolaInps")
    cscCode: Optional[str] = Field(None, validation_alias="csc_code", serialization_alias="cscCode")
    caCode: Optional[str] = Field(None, validation_alias="ca_code", serialization_alias="caCode")
    atecoCode: Optional[str] = Field(None, validation_alias="ateco_code", serialization_alias="atecoCode")
    inpsOffice: Optional[str] = Field(None, validation_alias="inps_office", serialization_alias="inpsOffice")
    cnelCode: Optional[str] = Field(None, validation_alias="cnel_code", serialization_alias="cnelCode")
    fundStatus: Optional[dict] = Field(None, validation_alias="fund_status", serialization_alias="fundStatus")
    priorYearAvgHeadcount: Optional[int] = Field(None, validation_alias="prior_year_avg_headcount",
                                                 serialization_alias="priorYearAvgHeadcount")
    tesoreriaStatus: Optional[str] = Field(None, validation_alias="tesoreria_status", serialization_alias="tesoreriaStatus")
    f24OperatingModel: Optional[str] = Field(None, validation_alias="f24_operating_model",
                                             serialization_alias="f24OperatingModel")
    lulMethod: Optional[str] = Field(None, validation_alias="lul_method", serialization_alias="lulMethod")
    readinessStatus: str = Field(validation_alias="readiness_status", serialization_alias="readinessStatus")
    readinessEvidence: Optional[dict] = Field(None, validation_alias="readiness_evidence",
                                              serialization_alias="readinessEvidence")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ItalyReadinessItem(BaseModel):
    key: str
    label: str
    required: bool
    complete: bool
    detail: Optional[str] = None


class ItalyReadinessResponse(BaseModel):
    """§27 release gates G1-G8: Italy must NOT become production-active
    because its content exists."""
    packId: Optional[int] = None
    packVersion: Optional[str] = None
    packStatus: Optional[str] = None
    ready: bool
    items: List[ItalyReadinessItem] = []
    blockers: List[str] = []


class ItalyCalculationPreviewRequest(BaseModel):
    """Read-only Super Admin preview of one Italian pack. Every worker and
    employer fact is supplied inline; nothing is read from or written to an
    employee or organization. Defaults describe one ordinary full month for a
    permanent worker employed all year with nothing paid yet."""
    jurisdictionPackId: Optional[int] = None
    payDate: date
    gross: Decimal = Field(gt=0)
    workerClass: str
    contractType: str = "INDETERMINATO"
    cigsApplies: bool = False
    capCohort: Optional[str] = None
    tfrDestination: Optional[str] = None
    pensionFund: Optional[str] = None
    taxDomicileRegion: str
    taxDomicileComune: str
    fringeChildDeclared: bool = False
    cscCode: str
    caCode: Optional[str] = None
    fund: str = "CIG"
    fisBand: Optional[str] = None
    priorYearAvgHeadcount: Optional[int] = None
    mensilita: Optional[int] = None
    mensilitaPaidPrior: int = 0
    ytdTaxablePrior: Decimal = Decimal("0")
    ytdIrpefWithheldPrior: Decimal = Decimal("0")
    ytdContributoryBasePrior: Decimal = Decimal("0")
    workDaysInYear: int = 365
    ytdFringePrior: Decimal = Decimal("0")
    ytdWedgePaidPrior: Decimal = Decimal("0")
    # IT-011 wedge-sum recovery plan; 0/0 = nothing is being recovered.
    wedgeRecoveryOutstanding: Decimal = Decimal("0")
    wedgeRecoveryInstalment: Decimal = Decimal("0")
    # §5 determined local-surtax amounts for the year; absent = not recorded,
    # which the engine blocks on exactly as a real run would.
    addregSaldoDue: Optional[Decimal] = None
    addcomSaldoDue: Optional[Decimal] = None
    addcomAccontoDue: Optional[Decimal] = None


# ── Italy filing outbox (§15/§16, IT-044/IT-048) ───────────────────────────
# Delivery state only. Filing status, receipt, correction lineage and schema
# version live on the linked StatutoryFiling, never duplicated here.

class ItalyFilingOutboxCreate(BaseModel):
    """Enqueue one outbound Italian filing action. Built from COMMITTED payroll
    by a caller, never transmitted from inside the calculator (IT-044)."""
    action: str  # UNIEMENS_TRANSMIT | F24_SUBMIT | LUL_REGISTER | CU_TRANSMIT | 770_TRANSMIT | CORRECTION
    statutoryFilingId: Optional[int] = None
    periodKey: Optional[str] = Field(None, max_length=20)
    payload: Optional[dict] = None
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class ItalyFilingOutboxItemResponse(BaseModel):
    id:                 int
    organizationId:     int = Field(..., validation_alias="organization_id", serialization_alias="organizationId")
    action:             str
    statutoryFilingId:  Optional[int] = Field(None, validation_alias="statutory_filing_id", serialization_alias="statutoryFilingId")
    periodKey:          Optional[str] = Field(None, validation_alias="period_key", serialization_alias="periodKey")
    payload:            Optional[dict] = None
    idempotencyKey:     str = Field(..., validation_alias="idempotency_key", serialization_alias="idempotencyKey")
    status:             str  # PENDING|SENT|UNKNOWN|ACKNOWLEDGED|FAILED
    attempts:           int
    lastError:          Optional[str] = Field(None, validation_alias="last_error", serialization_alias="lastError")
    sentAt:             Optional[datetime] = Field(None, validation_alias="sent_at", serialization_alias="sentAt")
    acknowledgedAt:     Optional[datetime] = Field(None, validation_alias="acknowledged_at", serialization_alias="acknowledgedAt")
    createdAt:          Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")
    updatedAt:          Optional[datetime] = Field(None, validation_alias="updated_at", serialization_alias="updatedAt")
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Saudi Arabia (ZP-SA-ENG-001) — readiness, preview ───────────────────────
class SaudiArabiaReadinessItem(BaseModel):
    key: str
    label: str
    required: bool
    complete: bool
    detail: Optional[str] = None


class SaudiArabiaReadinessResponse(BaseModel):
    """§16/§17 activation-readiness checklist for one Saudi tax pack —
    Saudi Arabia must NOT become production-active merely because the
    country record exists."""
    packId: Optional[int] = Field(None, serialization_alias="packId")
    packVersion: Optional[str] = Field(None, serialization_alias="packVersion")
    packStatus: Optional[str] = Field(None, serialization_alias="packStatus")
    ready: bool
    items: List[SaudiArabiaReadinessItem] = []
    blockers: List[str] = []


class SaudiArabiaCalculationPreviewRequest(BaseModel):
    """Read-only Super Admin preview of one Saudi pack (ZP-SA-ENG-001 §13
    "simulation before activation"). Worker facts are supplied inline —
    nothing is read from or written to an employee."""
    jurisdictionPackId: Optional[int] = Field(None, alias="jurisdictionPackId")
    payDate: date
    gross: Decimal = Field(gt=0)
    basic: Optional[Decimal] = None
    payFrequency: str = "Monthly"
    organizationId: Optional[int] = Field(None, alias="organizationId")
    employeeId: Optional[int] = Field(None, alias="employeeId")
    workerClass: str
    cohort: str
    cohortEvidenceRef: Optional[str] = Field(None, alias="cohortEvidenceRef")
    contributoryWage: Optional[Decimal] = Field(None, alias="contributoryWage")
    deductionOrders: Optional[List[dict]] = Field(None, alias="deductionOrders")
    overtimeHours: Optional[Decimal] = Field(None, alias="overtimeHours")
    ramadan: bool = False
    workHoursRecords: Optional[List[dict]] = Field(None, alias="workHoursRecords")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


# ── Saudi Arabia ledgers (ZP-SA-ENG-001 §7/§12) — employer, contract, ────────
#    GOSI liability, EOS accrual, final settlement, WPS SIE ─────────────────
class SaEmployerProfileCreateRequest(BaseModel):
    effectiveFrom: date
    gosiEmployerCode: str
    branchCode: Optional[str] = None
    activityCode: Optional[str] = None
    riskCategory: Optional[str] = None
    occupationalHazardRatePct: Optional[Decimal] = None
    sanedEmployerRatePct: Optional[Decimal] = None
    pensionEmployerRatePct: Optional[Decimal] = None
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class SaEmployerProfileResponse(BaseModel):
    id: int
    organizationId: int = Field(alias="organization_id")
    effectiveFrom: date = Field(alias="effective_from")
    effectiveTo: Optional[date] = Field(default=None, alias="effective_to")
    gosiEmployerCode: str = Field(alias="gosi_employer_code")
    branchCode: Optional[str] = Field(default=None, alias="branch_code")
    activityCode: Optional[str] = Field(default=None, alias="activity_code")
    riskCategory: Optional[str] = Field(default=None, alias="risk_category")
    status: str
    previousVersionId: Optional[int] = Field(default=None, alias="previous_version_id")
    approvedById: Optional[int] = Field(default=None, alias="approved_by_id")
    createdAt: datetime = Field(alias="created_at")
    updatedAt: Optional[datetime] = Field(default=None, alias="updated_at")
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SaContractVersionCreateRequest(BaseModel):
    effectiveFrom: date = Field(alias="effective_from")
    contractType: str = Field(alias="contract_type")
    occupation: Optional[str] = None
    basicWage: Optional[Decimal] = Field(default=None, alias="basic_wage")
    housingAllowance: Optional[Decimal] = Field(default=None, alias="housing_allowance")
    transportAllowance: Optional[Decimal] = Field(default=None, alias="transport_allowance")
    otherAllowances: Optional[Decimal] = Field(default=None, alias="other_allowances")
    inKindHousingValue: Optional[Decimal] = Field(default=None, alias="in_kind_housing_value")
    probationEndDate: Optional[date] = Field(default=None, alias="probation_end_date")
    contractEndDate: Optional[date] = Field(default=None, alias="contract_end_date")
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class SaContractVersionResponse(BaseModel):
    id: int
    employeeId: int = Field(alias="employee_id")
    organizationId: int = Field(alias="organization_id")
    effectiveFrom: date = Field(alias="effective_from")
    effectiveTo: Optional[date] = Field(default=None, alias="effective_to")
    contractType: str = Field(alias="contract_type")
    occupation: Optional[str] = None
    basicWage: Optional[Decimal] = Field(default=None, alias="basic_wage")
    housingAllowance: Optional[Decimal] = Field(default=None, alias="housing_allowance")
    transportAllowance: Optional[Decimal] = Field(default=None, alias="transport_allowance")
    otherAllowances: Optional[Decimal] = Field(default=None, alias="other_allowances")
    inKindHousingValue: Optional[Decimal] = Field(default=None, alias="in_kind_housing_value")
    status: str
    previousVersionId: Optional[int] = Field(default=None, alias="previous_version_id")
    approvedById: Optional[int] = Field(default=None, alias="approved_by_id")
    createdAt: datetime = Field(alias="created_at")
    updatedAt: Optional[datetime] = Field(default=None, alias="updated_at")
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SaGosiLiabilityResponse(BaseModel):
    id: int
    organizationId: int = Field(alias="organization_id")
    contributionMonth: date = Field(alias="contribution_month")
    totalWages: Decimal = Field(alias="total_wages")
    contributoryWages: Decimal = Field(alias="contributory_wages")
    pensionEmployee: Decimal = Field(alias="pension_employee")
    pensionEmployer: Decimal = Field(alias="pension_employer")
    sanedEmployee: Decimal = Field(alias="saned_employee")
    sanedEmployer: Decimal = Field(alias="saned_employer")
    occupationalHazardEmployer: Decimal = Field(alias="occupational_hazard_employer")
    totalDue: Decimal = Field(alias="total_due")
    status: str
    paidAt: Optional[datetime] = Field(default=None, alias="paid_at")
    paymentReference: Optional[str] = Field(default=None, alias="payment_reference")
    sourceRunId: Optional[int] = Field(default=None, alias="source_run_id")
    createdAt: datetime = Field(alias="created_at")
    updatedAt: Optional[datetime] = Field(default=None, alias="updated_at")
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SaGosiLiabilityPaidRequest(BaseModel):
    paymentReference: Optional[str] = Field(default=None, alias="payment_reference")
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class SaEosLedgerEntryResponse(BaseModel):
    id: int
    employeeId: int = Field(alias="employee_id")
    organizationId: int = Field(alias="organization_id")
    periodFrom: date = Field(alias="period_from")
    periodTo: date = Field(alias="period_to")
    basicWage: Decimal = Field(alias="basic_wage")
    housingAllowance: Decimal = Field(alias="housing_allowance")
    eosBase: Decimal = Field(alias="eos_base")
    daysWorked: int = Field(alias="days_worked")
    accrualMonths: Decimal = Field(alias="accrual_months")
    eosAwardAccrued: Decimal = Field(alias="eos_award_accrued")
    cumulativeAward: Decimal = Field(alias="cumulative_award")
    status: str
    sourceRunId: Optional[int] = Field(default=None, alias="source_run_id")
    createdAt: datetime = Field(alias="created_at")
    updatedAt: Optional[datetime] = Field(default=None, alias="updated_at")
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SaEosAccrualResponse(BaseModel):
    entries: List[SaEosLedgerEntryResponse] = []
    skipped: List[dict] = []


class SaFinalSettlementCreateRequest(BaseModel):
    employeeId: int = Field(alias="employee_id")
    terminationDate: date = Field(alias="termination_date")
    terminationType: str = Field(alias="termination_type")  # TERMINATION | RESIGNATION
    noticeGiven: bool = Field(default=False, alias="notice_given")
    noticePeriodDays: Optional[int] = Field(default=None, alias="notice_period_days")
    unusedLeaveDays: Optional[int] = Field(default=None, alias="unused_leave_days")
    unusedLeavePay: Optional[Decimal] = Field(default=None, alias="unused_leave_pay")
    noticePay: Optional[Decimal] = Field(default=None, alias="notice_pay")
    repatriationPay: Optional[Decimal] = Field(default=None, alias="repatriation_pay")
    otherDues: Optional[Decimal] = Field(default=None, alias="other_dues")
    deductions: Optional[Decimal] = Field(default=None, alias="deductions")
    excluded: bool = Field(default=False, alias="excluded")  # a recorded Art. 80 exclusion
    settlementDeadlineDays: Optional[int] = Field(default=None, alias="settlement_deadline_days")
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class SaFinalSettlementResponse(BaseModel):
    id: int
    employeeId: int = Field(alias="employee_id")
    organizationId: int = Field(alias="organization_id")
    terminationDate: date = Field(alias="termination_date")
    terminationType: str = Field(alias="termination_type")
    noticeGiven: bool = Field(alias="notice_given")
    noticePeriodDays: Optional[int] = Field(default=None, alias="notice_period_days")
    eosAward: Decimal = Field(alias="eos_award")
    unusedLeaveDays: int = Field(alias="unused_leave_days")
    unusedLeavePay: Decimal = Field(alias="unused_leave_pay")
    noticePay: Decimal = Field(alias="notice_pay")
    repatriationPay: Decimal = Field(alias="repatriation_pay")
    otherDues: Decimal = Field(alias="other_dues")
    totalDue: Decimal = Field(alias="total_due")
    deductions: Decimal
    netPayable: Decimal = Field(alias="net_payable")
    deadlineDate: date = Field(alias="deadline_date")
    paidAt: Optional[datetime] = Field(default=None, alias="paid_at")
    paymentReference: Optional[str] = Field(default=None, alias="payment_reference")
    status: str
    approvedById: Optional[int] = Field(default=None, alias="approved_by_id")
    createdAt: datetime = Field(alias="created_at")
    updatedAt: Optional[datetime] = Field(default=None, alias="updated_at")
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SaFinalSettlementPayRequest(BaseModel):
    paymentReference: Optional[str] = Field(default=None, alias="payment_reference")
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class SaWpsFileResponse(BaseModel):
    id: int
    organizationId: int = Field(alias="organization_id")
    payrollRunId: Optional[int] = Field(default=None, alias="payroll_run_id")
    fileName: str = Field(alias="file_name")
    fileSha256: str = Field(alias="file_sha256")
    employeeCount: int = Field(alias="employee_count")
    totalAmount: Decimal = Field(alias="total_amount")
    status: str
    submittedAt: Optional[datetime] = Field(default=None, alias="submitted_at")
    acceptedAt: Optional[datetime] = Field(default=None, alias="accepted_at")
    rejectedAt: Optional[datetime] = Field(default=None, alias="rejected_at")
    rejectionReason: Optional[str] = Field(default=None, alias="rejection_reason")
    createdAt: datetime = Field(alias="created_at")
    updatedAt: Optional[datetime] = Field(default=None, alias="updated_at")
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SaWpsObservationResponse(BaseModel):
    id: int
    wpsFileId: int = Field(alias="wps_file_id")
    employeeId: int = Field(alias="employee_id")
    observationCode: str = Field(alias="observation_code")
    observationDescription: Optional[str] = Field(default=None, alias="observation_description")
    expectedAmount: Optional[Decimal] = Field(default=None, alias="expected_amount")
    reportedAmount: Optional[Decimal] = Field(default=None, alias="reported_amount")
    resolved: bool
    resolvedById: Optional[int] = Field(default=None, alias="resolved_by_id")
    resolvedAt: Optional[datetime] = Field(default=None, alias="resolved_at")
    createdAt: datetime = Field(alias="created_at")
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SaWpsFileBuildResponse(BaseModel):
    file: SaWpsFileResponse
    records: List[dict] = []
    observations: List[dict] = []
    sha256: str


class SaWpsRejectRequest(BaseModel):
    reason: str
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
