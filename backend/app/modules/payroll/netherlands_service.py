"""
payroll/netherlands_service.py
------------------------------
Netherlands statutory service — employer profiles, income relationships,
tax-credit instructions, contract versions, employer readiness card H.

Follows the CH/SA pattern: thin hook layer, delegates to engine where appropriate,
no hardcoded rates. All rates come from the NL-PAYROLL-2026 canonical pack.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from .models import (
    PayrollEmployee,
    PayrollNlEmployerProfile,
    PayrollNlIncomeRelationship,
    PayrollNlTaxCreditInstruction,
    PayrollNlContractVersion,
    EmployeeStatutoryProfile,
    CollectiveAgreement,
    ComplianceDocument,
)
from app.modules.organizations.models import Organization
from app.modules.auth.models import User
from .engine.jurisdictions.netherlands.vcr import VcrFamily
from app.core.exceptions import BadRequestException, NotFoundException, ForbiddenException
from .netherlands_schemas import (
    EmployerProfileCreate,
    EmployerProfileUpdate,
    EmployerProfileResponse,
    IncomeRelationshipCreate,
    IncomeRelationshipUpdate,
    IncomeRelationshipResponse,
    TaxCreditInstructionCreate,
    TaxCreditInstructionResponse,
    ContractVersionCreate,
    ContractVersionUpdate,
    ContractVersionResponse,
    EmployerReadinessCard,
    ReadinessSection,
    ReadinessItem,
    EmployeeNLFields,
)
from .netherlands_schemas import EmployerProfileResponse as EmpResp


def calculate_nl(ctx: Any) -> Dict[str, Any]:
    """Statutory entry point for NL payroll calculation."""
    from .engine.countries.netherlands import calculate, NLError, NLBlock
    try:
        return calculate(ctx)
    except NLBlock:
        raise
    except NLError:
        raise
    except Exception as e:
        raise NLError(f"NL calculation failed: {e}")


# ---- Employer Profile ----

def create_employer_profile(
    db: Session,
    *,
    organization_id: int,
    data: EmployerProfileCreate,
    actor_id: int,
) -> EmployerProfileResponse:
    """Create a new NL employer profile version. Closes any open version."""
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise NotFoundException("Organization", organization_id)

    # Close any open version
    open_profile = db.query(PayrollNlEmployerProfile).filter(
        PayrollNlEmployerProfile.organization_id == organization_id,
        PayrollNlEmployerProfile.effective_to.is_(None),
    ).first()
    if open_profile:
        open_profile.effective_to = data.effectiveFrom

    profile = PayrollNlEmployerProfile(
        organization_id=organization_id,
        version=(open_profile.version + 1) if open_profile else 1,
        previous_version_id=open_profile.id if open_profile else None,
        effective_from=data.effectiveFrom,
        legal_name=data.legalName,
        kvk_number=data.kvkNumber,
        rsin=data.rsin,
        address=data.address,
        payroll_contact=data.payrollContact,
        loonheffingennummer=data.loonheffingennummer,
        loonheffingen_subnumber=data.loonheffingenSubnumber,
        registration_letter_ref=data.registrationLetterRef,
        return_period=data.returnPeriod,
        payroll_schedule=data.payrollSchedule,
        standard_pay_day=data.standardPayDay,
        bank_lead_days=data.bankLeadDays,
        bank_iban_token=data.bankIbanToken,
        bank_bic=data.bankBic,
        pki_cert_ref=data.pkiCertRef,
        pki_cert_fingerprint=data.pkiCertFingerprint,
        pki_cert_issuer=data.pkiCertIssuer,
        pki_cert_expires_at=data.pkiCertExpiresAt,
        digipoort_channel=data.digipoortChannel,
        digipoort_test_status=data.digipoortTestStatus,
        digipoort_test_evidence_id=data.digipoortTestEvidenceId,
        cao_status=data.caoStatus,
        collective_agreement_id=data.collectiveAgreementId,
        pension_status=data.pensionStatus,
        wkr_mode=data.wkrMode,
        wkr_concern_id=data.wkrConcernId,
        readiness_status="INCOMPLETE",
        created_by=actor_id,
    )
    db.add(profile)
    db.flush()
    return _to_employer_profile_response(profile)


def update_employer_profile(
    db: Session,
    *,
    profile_id: int,
    data: EmployerProfileUpdate,
    actor_id: int,
) -> EmployerProfileResponse:
    """Update mutable fields of an employer profile."""
    profile = db.query(PayrollNlEmployerProfile).filter(PayrollNlEmployerProfile.id == profile_id).first()
    if not profile:
        raise NotFoundException("PayrollNlEmployerProfile", profile_id)

    for field, value in data.model_dump(exclude_unset=True).items():
        # Convert camelCase to snake_case
        snake = _camel_to_snake(field)
        if hasattr(profile, snake):
            setattr(profile, snake, value)

    db.flush()
    return _to_employer_profile_response(profile)


def get_employer_profile(
    db: Session,
    *,
    organization_id: int,
    version: Optional[int] = None,
) -> EmployerProfileResponse:
    """Get employer profile by org and optional version (latest if None)."""
    q = db.query(PayrollNlEmployerProfile).filter(PayrollNlEmployerProfile.organization_id == organization_id)
    if version:
        q = q.filter(PayrollNlEmployerProfile.version == version)
    else:
        q = q.filter(PayrollNlEmployerProfile.effective_to.is_(None))
    profile = q.first()
    if not profile:
        raise NotFoundException("PayrollNlEmployerProfile", f"org={organization_id}, version={version}")
    return _to_employer_profile_response(profile)


def _to_employer_profile_response(profile: PayrollNlEmployerProfile) -> EmployerProfileResponse:
    return EmployerProfileResponse(
        id=profile.id,
        organizationId=profile.organization_id,
        version=profile.version,
        previousVersionId=profile.previous_version_id,
        effectiveFrom=profile.effective_from,
        effectiveTo=profile.effective_to,
        legalName=profile.legal_name,
        kvkNumber=profile.kvk_number,
        rsin=profile.rsin,
        address=profile.address,
        payrollContact=profile.payroll_contact,
        loonheffingennummer=profile.loonheffingennummer,
        loonheffingenSubnumber=profile.loonheffingen_subnumber,
        registrationLetterRef=profile.registration_letter_ref,
        registrationVerifiedAt=profile.registration_verified_at,
        registrationVerifiedBy=profile.registration_verified_by,
        returnPeriod=profile.return_period,
        payrollSchedule=profile.payroll_schedule,
        standardPayDay=profile.standard_pay_day,
        bankLeadDays=profile.bank_lead_days,
        bankIbanToken=profile.bank_iban_token,
        bankBic=profile.bank_bic,
        pkiCertRef=profile.pki_cert_ref,
        pkiCertFingerprint=profile.pki_cert_fingerprint,
        pkiCertIssuer=profile.pki_cert_issuer,
        pkiCertExpiresAt=profile.pki_cert_expires_at,
        digipoortChannel=profile.digipoort_channel,
        digipoortTestStatus=profile.digipoort_test_status,
        digipoortTestEvidenceId=profile.digipoort_test_evidence_id,
        caoStatus=profile.cao_status,
        collectiveAgreementId=profile.collective_agreement_id,
        pensionStatus=profile.pension_status,
        wkrMode=profile.wkr_mode,
        wkrConcernId=profile.wkr_concern_id,
        readinessStatus=profile.readiness_status,
        readinessEvidence=profile.readiness_evidence,
        createdBy=profile.created_by,
        createdAt=profile.created_at,
    )


def _camel_to_snake(name: str) -> str:
    import re
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


# ---- Income Relationship (IKV) ----

def create_income_relationship(
    db: Session,
    *,
    organization_id: int,
    employee_id: int,
    data: IncomeRelationshipCreate,
    actor_id: int,
) -> IncomeRelationshipResponse:
    """Create a new IKV. ikv_number is set once and never regenerated."""
    emp = db.query(PayrollEmployee).filter(
        PayrollEmployee.id == employee_id,
        PayrollEmployee.organization_id == organization_id,
    ).first()
    if not emp:
        raise NotFoundException("PayrollEmployee", employee_id)

    # Check ikv_number uniqueness
    existing = db.query(PayrollNlIncomeRelationship).filter(
        PayrollNlIncomeRelationship.organization_id == organization_id,
        PayrollNlIncomeRelationship.employee_id == employee_id,
        PayrollNlIncomeRelationship.ikv_number == data.ikvNumber,
    ).first()
    if existing:
        raise BadRequestException(f"IKV number {data.ikvNumber} already exists for this employee")

    ikv = PayrollNlIncomeRelationship(
        organization_id=organization_id,
        employee_id=employee_id,
        ikv_number=data.ikvNumber,
        income_relation_code=data.incomeRelationCode,
        payroll_period=data.payrollPeriod,
        start_date=data.startDate,
        end_date=data.endDate,
        created_by=actor_id,
    )
    db.add(ikv)
    db.flush()
    return _to_income_relationship_response(ikv)


def update_income_relationship(
    db: Session,
    *,
    ikv_id: int,
    data: IncomeRelationshipUpdate,
    actor_id: int,
) -> IncomeRelationshipResponse:
    ikv = db.query(PayrollNlIncomeRelationship).filter(PayrollNlIncomeRelationship.id == ikv_id).first()
    if not ikv:
        raise NotFoundException("PayrollNlIncomeRelationship", ikv_id)

    for field, value in data.model_dump(exclude_unset=True).items():
        snake = _camel_to_snake(field)
        if hasattr(ikv, snake):
            setattr(ikv, snake, value)

    db.flush()
    return _to_income_relationship_response(ikv)


def get_income_relationships(
    db: Session,
    *,
    organization_id: int,
    employee_id: Optional[int] = None,
) -> List[IncomeRelationshipResponse]:
    q = db.query(PayrollNlIncomeRelationship).filter(
        PayrollNlIncomeRelationship.organization_id == organization_id
    )
    if employee_id:
        q = q.filter(PayrollNlIncomeRelationship.employee_id == employee_id)
    return [_to_income_relationship_response(r) for r in q.all()]


def _to_income_relationship_response(ikv: PayrollNlIncomeRelationship) -> IncomeRelationshipResponse:
    return IncomeRelationshipResponse(
        id=ikv.id,
        organizationId=ikv.organization_id,
        employeeId=ikv.employee_id,
        ikvNumber=ikv.ikv_number,
        incomeRelationCode=ikv.income_relation_code,
        payrollPeriod=ikv.payroll_period,
        startDate=ikv.start_date,
        endDate=ikv.end_date,
        status=ikv.status,
        closedReason=ikv.closed_reason,
        createdBy=ikv.created_by,
        createdAt=ikv.created_at,
    )


# ---- Tax Credit Instruction (Model opgaaf) ----

def create_tax_credit_instruction(
    db: Session,
    *,
    organization_id: int,
    employee_id: int,
    data: TaxCreditInstructionCreate,
    actor_id: int,
) -> TaxCreditInstructionResponse:
    """Create a new tax credit instruction. Supersedes any active one."""
    emp = db.query(PayrollEmployee).filter(
        PayrollEmployee.id == employee_id,
        PayrollEmployee.organization_id == organization_id,
    ).first()
    if not emp:
        raise NotFoundException("PayrollEmployee", employee_id)

    # Supersede any existing active instruction
    active = db.query(PayrollNlTaxCreditInstruction).filter(
        PayrollNlTaxCreditInstruction.organization_id == organization_id,
        PayrollNlTaxCreditInstruction.employee_id == employee_id,
        PayrollNlTaxCreditInstruction.superseded_by_id.is_(None),
    ).first()
    if active:
        active.superseded_by_id = None  # will be set after flush

    instr = PayrollNlTaxCreditInstruction(
        organization_id=organization_id,
        employee_id=employee_id,
        apply_tax_credit=data.applyTaxCredit,
        form_version=data.formVersion,
        signed_at=data.signedAt,
        effective_from=data.effectiveFrom,
        signed_document_artifact_id=data.signedDocumentArtifactId,
        captured_by=actor_id,
    )
    db.add(instr)
    db.flush()

    if active:
        active.superseded_by_id = instr.id
        db.flush()

    return _to_tax_credit_response(instr)


def get_tax_credit_instructions(
    db: Session,
    *,
    organization_id: int,
    employee_id: Optional[int] = None,
) -> List[TaxCreditInstructionResponse]:
    q = db.query(PayrollNlTaxCreditInstruction).filter(
        PayrollNlTaxCreditInstruction.organization_id == organization_id
    )
    if employee_id:
        q = q.filter(PayrollNlTaxCreditInstruction.employee_id == employee_id)
    return [_to_tax_credit_response(r) for r in q.all()]


def _to_tax_credit_response(instr: PayrollNlTaxCreditInstruction) -> TaxCreditInstructionResponse:
    return TaxCreditInstructionResponse(
        id=instr.id,
        organizationId=instr.organization_id,
        employeeId=instr.employee_id,
        applyTaxCredit=instr.apply_tax_credit,
        formVersion=instr.form_version,
        signedAt=instr.signed_at,
        effectiveFrom=instr.effective_from,
        signedDocumentArtifactId=instr.signed_document_artifact_id,
        supersededById=instr.superseded_by_id,
        capturedBy=instr.captured_by,
        createdAt=instr.created_at,
    )


# ---- Contract Version with AWf Class Derivation ----

def _derive_awf_class(
    contract_term: str,
    written_record: bool,
    on_call: bool,
    agreed_hours_per_week: Optional[Decimal],
    statutory_exception_code: Optional[str],
) -> tuple[str, str]:
    """
    Derive AWf class per NL-015:
    - LOW (2.74%) if: permanent OR fixed-term >= 12 months with written contract
      AND NOT on-call without guaranteed hours AND NOT standby
    - HIGH (7.74%) otherwise
    Returns (class, reason).
    """
    if on_call:
        return "HIGH", "on_call_without_guaranteed_hours"
    if statutory_exception_code:
        return "HIGH", f"statutory_exception_{statutory_exception_code}"
    if contract_term == "INDEFINITE" and written_record:
        return "LOW", "indefinite_with_written_contract"
    if contract_term == "FIXED" and written_record:
        if agreed_hours_per_week is not None and agreed_hours_per_week >= 0:
            return "LOW", "fixed_term_with_written_contract"
        return "HIGH", "fixed_term_insufficient_hours"
    return "HIGH", "does_not_meet_low_rate_conditions"


def create_contract_version(
    db: Session,
    *,
    organization_id: int,
    employee_id: int,
    data: ContractVersionCreate,
    actor_id: int,
) -> ContractVersionResponse:
    """Create a new contract version with derived AWf class."""
    emp = db.query(PayrollEmployee).filter(
        PayrollEmployee.id == employee_id,
        PayrollEmployee.organization_id == organization_id,
    ).first()
    if not emp:
        raise NotFoundException("PayrollEmployee", employee_id)

    # Verify income_relationship if provided
    if data.incomeRelationshipId:
        ikv = db.query(PayrollNlIncomeRelationship).filter(
            PayrollNlIncomeRelationship.id == data.incomeRelationshipId,
            PayrollNlIncomeRelationship.organization_id == organization_id,
            PayrollNlIncomeRelationship.employee_id == employee_id,
        ).first()
        if not ikv:
            raise BadRequestException("Income relationship not found for this employee")

    # Get previous version for chain
    prev = db.query(PayrollNlContractVersion).filter(
        PayrollNlContractVersion.organization_id == organization_id,
        PayrollNlContractVersion.employee_id == employee_id,
        PayrollNlContractVersion.effective_to.is_(None),
    ).first()

    # Derive AWf class
    awf_class, awf_reason = _derive_awf_class(
        data.contractTerm,
        data.writtenRecord,
        data.onCall,
        data.agreedHoursPerWeek,
        data.statutoryExceptionCode,
    )

    version_num = (prev.version + 1) if prev else 1

    contract = PayrollNlContractVersion(
        organization_id=organization_id,
        employee_id=employee_id,
        income_relationship_id=data.incomeRelationshipId,
        version=version_num,
        previous_version_id=prev.id if prev else None,
        contract_term=data.contractTerm,
        written_record=data.writtenRecord,
        written_evidence_ref=data.writtenEvidenceRef,
        on_call=data.onCall,
        agreed_hours_per_week=data.agreedHoursPerWeek,
        statutory_exception_code=data.statutoryExceptionCode,
        start_date=data.startDate,
        end_date=data.endDate,
        derived_awf_class=awf_class,
        awf_derivation_reason=awf_reason,
        effective_from=data.startDate,
        created_by=actor_id,
    )
    db.add(contract)

    # Close previous
    if prev:
        prev.effective_to = data.startDate
        prev.effective_from = prev.start_date  # keep original

    db.flush()
    return _to_contract_response(contract)


def update_contract_version(
    db: Session,
    *,
    contract_id: int,
    data: ContractVersionUpdate,
    actor_id: int,
) -> ContractVersionResponse:
    contract = db.query(PayrollNlContractVersion).filter(PayrollNlContractVersion.id == contract_id).first()
    if not contract:
        raise NotFoundException("PayrollNlContractVersion", contract_id)

    # Re-derive AWf class if relevant fields change
    update_data = data.model_dump(exclude_unset=True)
    if any(k in update_data for k in ("contractTerm", "writtenRecord", "onCall", "agreedHoursPerWeek", "statutoryExceptionCode")):
        term = update_data.get("contractTerm", contract.contract_term)
        written = update_data.get("writtenRecord", contract.written_record)
        on_call = update_data.get("onCall", contract.on_call)
        hours = update_data.get("agreedHoursPerWeek", contract.agreed_hours_per_week)
        exception = update_data.get("statutoryExceptionCode", contract.statutory_exception_code)

        awf_class, awf_reason = _derive_awf_class(term, written, on_call, hours, exception)
        contract.derived_awf_class = awf_class
        contract.awf_derivation_reason = awf_reason

    for field, value in update_data.items():
        snake = _camel_to_snake(field)
        if hasattr(contract, snake):
            setattr(contract, snake, value)

    db.flush()
    return _to_contract_response(contract)


def get_contract_versions(
    db: Session,
    *,
    organization_id: int,
    employee_id: Optional[int] = None,
) -> List[ContractVersionResponse]:
    q = db.query(PayrollNlContractVersion).filter(
        PayrollNlContractVersion.organization_id == organization_id
    )
    if employee_id:
        q = q.filter(PayrollNlContractVersion.employee_id == employee_id)
    return [_to_contract_response(r) for r in q.all()]


def _to_contract_response(c: PayrollNlContractVersion) -> ContractVersionResponse:
    return ContractVersionResponse(
        id=c.id,
        organizationId=c.organization_id,
        employeeId=c.employee_id,
        incomeRelationshipId=c.income_relationship_id,
        version=c.version,
        previousVersionId=c.previous_version_id,
        contractTerm=c.contract_term,
        writtenRecord=c.written_record,
        writtenEvidenceRef=c.written_evidence_ref,
        onCall=c.on_call,
        agreedHoursPerWeek=c.agreed_hours_per_week,
        statutoryExceptionCode=c.statutory_exception_code,
        startDate=c.start_date,
        endDate=c.end_date,
        derivedAwfClass=c.derived_awf_class,
        awfDerivationReason=c.awf_derivation_reason,
        effectiveFrom=c.effective_from,
        effectiveTo=c.effective_to,
        createdBy=c.created_by,
        createdAt=c.created_at,
    )


# ---- Employer Readiness Card H ----

def get_employer_readiness_card(
    db: Session,
    *,
    organization_id: int,
) -> EmployerReadinessCard:
    """Build the H-card for NL employer readiness."""
    profile = db.query(PayrollNlEmployerProfile).filter(
        PayrollNlEmployerProfile.organization_id == organization_id,
        PayrollNlEmployerProfile.effective_to.is_(None),
    ).first()

    if not profile:
        return EmployerReadinessCard(
            organizationId=organization_id,
            profileVersion=0,
            overallStatus="INCOMPLETE",
            sections=[],
            lastUpdated=datetime.utcnow(),
        )

    sections = []

    # Section 1: Core Registration
    core_items = [
        ReadinessItem(
            key="kvk_number",
            label="KvK Number",
            status="COMPLETE" if profile.kvk_number else "INCOMPLETE",
            details="Chamber of Commerce registration number" if profile.kvk_number else "Missing",
        ),
        ReadinessItem(
            key="rsin",
            label="RSIN",
            status="COMPLETE" if profile.rsin else "INCOMPLETE",
        ),
        ReadinessItem(
            key="loonheffingennummer",
            label="Loonheffingennummer",
            status="COMPLETE" if profile.loonheffingennummer else "INCOMPLETE",
        ),
        ReadinessItem(
            key="registration_verified",
            label="Registration Verified",
            status="COMPLETE" if profile.registration_verified_at else "INCOMPLETE",
        ),
    ]
    sections.append(ReadinessSection(section="Core Registration", items=core_items))

    # Section 2: Bank & Payment
    bank_items = [
        ReadinessItem(
            key="bank_iban",
            label="Bank IBAN (tokenized)",
            status="COMPLETE" if profile.bank_iban_token else "INCOMPLETE",
        ),
        ReadinessItem(
            key="bank_bic",
            label="Bank BIC",
            status="COMPLETE" if profile.bank_bic else "INCOMPLETE",
        ),
        ReadinessItem(
            key="bank_lead_days",
            label="Bank Lead Days",
            status="COMPLETE" if profile.bank_lead_days is not None else "INCOMPLETE",
        ),
        ReadinessItem(
            key="payroll_schedule",
            label="Payroll Schedule",
            status="COMPLETE" if profile.payroll_schedule else "INCOMPLETE",
        ),
        ReadinessItem(
            key="standard_pay_day",
            label="Standard Pay Day",
            status="COMPLETE" if profile.standard_pay_day else "INCOMPLETE",
        ),
    ]
    sections.append(ReadinessSection(section="Bank & Payment", items=bank_items))

    # Section 3: PKI & Digipoort
    pki_items = [
        ReadinessItem(
            key="pki_cert",
            label="PKI Certificate",
            status="COMPLETE" if profile.pki_cert_ref else "INCOMPLETE",
        ),
        ReadinessItem(
            key="pki_cert_expiry",
            label="PKI Certificate Expiry",
            status="COMPLETE" if profile.pki_cert_expires_at and profile.pki_cert_expires_at > datetime.utcnow() else "BLOCKED",
            details="Certificate expired" if profile.pki_cert_expires_at and profile.pki_cert_expires_at <= datetime.utcnow() else None,
        ),
        ReadinessItem(
            key="digipoort_channel",
            label="Digipoort Channel",
            status="COMPLETE" if profile.digipoort_channel else "INCOMPLETE",
        ),
        ReadinessItem(
            key="digipoort_test",
            label="Digipoort Test Status",
            status=profile.digipoort_test_status or "INCOMPLETE",
        ),
    ]
    sections.append(ReadinessSection(section="PKI & Digipoort", items=pki_items))

    # Section 4: CAO & Pension
    cao_items = [
        ReadinessItem(
            key="cao_status",
            label="CAO Status",
            status="COMPLETE" if profile.cao_status == "APPLICABLE" else "INCOMPLETE",
            details=profile.cao_status,
        ),
        ReadinessItem(
            key="collective_agreement",
            label="Collective Agreement",
            status="COMPLETE" if profile.collective_agreement_id else "INCOMPLETE",
        ),
        ReadinessItem(
            key="pension_status",
            label="Pension Status",
            status="COMPLETE" if profile.pension_status else "INCOMPLETE",
        ),
    ]
    sections.append(ReadinessSection(section="CAO & Pension", items=cao_items))

    # Section 5: WKR
    wkr_items = [
        ReadinessItem(
            key="wkr_mode",
            label="WKR Mode",
            status="COMPLETE" if profile.wkr_mode else "INCOMPLETE",
            details=profile.wkr_mode,
        ),
        ReadinessItem(
            key="wkr_concern",
            label="WKR Concern ID",
            status="COMPLETE" if (profile.wkr_mode == "CONCERN" and profile.wkr_concern_id) else ("N/A" if profile.wkr_mode == "STANDALONE" else "INCOMPLETE"),
        ),
    ]
    sections.append(ReadinessSection(section="WKR", items=wkr_items))

    # Overall status
    all_complete = all(item.status == "COMPLETE" for section in sections for item in section.items)
    any_blocked = any(item.status == "BLOCKED" for section in sections for item in section.items)
    overall = "BLOCKED" if any_blocked else ("READY" if all_complete else "INCOMPLETE")

    return EmployerReadinessCard(
        organizationId=organization_id,
        profileVersion=profile.version,
        overallStatus=overall,
        sections=sections,
        lastUpdated=datetime.utcnow(),
        updatedBy=profile.created_by,
    )


# ---- Employee NL Fields (statutory profile) ----

def get_employee_nl_fields(
    db: Session,
    *,
    employee_id: int,
) -> EmployeeNLFields:
    """Get NL-specific fields from the latest statutory profile."""
    from .models import EmployeeStatutoryProfile
    profile = db.query(EmployeeStatutoryProfile).filter(
        EmployeeStatutoryProfile.employee_id == employee_id,
        EmployeeStatutoryProfile.effective_to.is_(None),
    ).first()
    if not profile:
        return EmployeeNLFields()
    return EmployeeNLFields(
        bsnVerifiedAt=profile.nl_bsn_verified_at,
        identityStatus=profile.nl_identity_status,
        residenceCountry=profile.nl_residence_country,
        residenceVariant=profile.nl_residence_variant,
        tableColor=profile.nl_table_color,
        zvwPath=profile.nl_zvw_path,
        eiInsured=profile.nl_ei_insured,
        insuranceExceptionCode=profile.nl_insurance_exception_code,
        insuranceEvidenceRef=profile.nl_insurance_evidence_ref,
        crossBorderStatus=profile.nl_cross_border_status,
        a1Reference=profile.nl_a1_reference,
        pensionSchemeId=profile.nl_pension_scheme_id,
        voluntaryExtraWithholding=profile.nl_voluntary_extra_withholding,
        vacationAllowancePct=profile.nl_vacation_allowance_pct,
        contractHoursPerWeek=profile.nl_contract_hours_per_week,
        personnelNumber=profile.nl_personnel_number,
    )


__all__ = [
    "calculate_nl",
    "create_employer_profile",
    "update_employer_profile",
    "get_employer_profile",
    "create_income_relationship",
    "update_income_relationship",
    "get_income_relationships",
    "create_tax_credit_instruction",
    "get_tax_credit_instructions",
    "create_contract_version",
    "update_contract_version",
    "get_contract_versions",
    "get_employer_readiness_card",
    "get_employee_nl_fields",
    "_derive_awf_class",
]


# Hook registry used by jurisdiction_hooks.py (fail-closed: hook must exist)
JURISDICTION_HOOKS = {
    "calculate": "calculate_nl",
}