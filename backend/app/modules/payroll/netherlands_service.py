"""
payroll/netherlands_service.py
------------------------------
Netherlands statutory service (ZP-NL-ENG-001). Reached by the shared platform
only through jurisdiction_hooks (registered at the end of this file), never by
import, so the dependency direction stays: platform <- this module <- engine.

Sections:
  * Phase 4  — employer profile, income relationships (IKV), tax-credit
               instructions, contract versions (AWf class), readiness card H.
  * Phase 5  — calculation inputs (resolve_nl_calc_inputs / calc_inputs hook),
               run preflight, approval fingerprint, COMMIT of the VCR / WKR /
               vacation-allowance ledgers on approval, recalculation lock.
  * Phase 6  — earning classifications, employer premium decisions, company
               cars, expat decisions.
  * Phase 7  — pension schemes, absence-pay policies, sickness events,
               termination settlements (transition payment, four-eyes).
  * Platform hooks — the 13 hooks every registered jurisdiction provides.

No hard-coded statutory figure lives here: rates come from the NL-PAYROLL pack
through the engine's rate_map/slabs, and employer/employee facts from the
nl_* tables. Writes flush only; the caller (router / run transition) commits.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.organizations.models import Organization
from app.modules.payroll import retention_service, service
from app.modules.payroll.engine.countries.netherlands import ENGINE_VERSION, normalise_period
from app.modules.payroll.engine.jurisdictions.netherlands import transition_payment
from app.modules.payroll.engine.jurisdictions.netherlands import wkr as wkr_engine
from app.modules.payroll.engine.jurisdictions.netherlands.premiums import AwfContractFacts
from app.modules.payroll.engine.jurisdictions.netherlands.vcr import VcrFamily
from app.modules.payroll.engine.jurisdictions.netherlands.wage_tax import PeriodCode, TableColor
from app.modules.payroll.models import (
    EmployeeStatutoryProfile,
    PayrollEmployee,
    PayrollNlAbsencePayPolicy,
    PayrollNlCompanyCar,
    PayrollNlContractVersion,
    PayrollNlEarningClassification,
    PayrollNlEmployerPremiumDecision,
    PayrollNlEmployerProfile,
    PayrollNlExpatDecision,
    PayrollNlIncomeRelationship,
    PayrollNlPensionScheme,
    PayrollNlSicknessEvent,
    PayrollNlTaxCreditInstruction,
    PayrollNlTerminationSettlement,
    PayrollNlVacationAllowanceLedger,
    PayrollNlVcrSnapshot,
    PayrollNlWkrAccumulator,
    PayrollRun,
    PayrollStatus,
    PayslipItem,
)
from app.modules.payroll import netherlands_tables_service as tables
from app.modules.payroll.netherlands_schemas import (
    ContractVersionCreate,
    ContractVersionResponse,
    ContractVersionUpdate,
    EmployeeNLFields,
    EmployerProfileCreate,
    EmployerProfileResponse,
    EmployerProfileUpdate,
    EmployerReadinessCard,
    IncomeRelationshipCreate,
    IncomeRelationshipResponse,
    IncomeRelationshipUpdate,
    ReadinessItem,
    ReadinessSection,
    TaxCreditInstructionCreate,
    TaxCreditInstructionResponse,
)

NL = "NL"
SPEC = "ZP-NL-ENG-001 v1.0"


def _expired(moment) -> bool:
    """Timezone-safe "is this timestamp in the past" (DB values are aware)."""
    if moment is None:
        return False
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment <= datetime.now(timezone.utc)


def _sha(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _employee(db: Session, employee_id: int, organization_id: int) -> PayrollEmployee:
    employee = service.get_employee_by_id(db, employee_id, organization_id)  # 404s outside the tenant
    if service._normalize_country(employee.country_code or "") != NL:
        raise BadRequestException(f"employee #{employee_id} is not a Netherlands employee")
    return employee


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
        # Inclusive windows: the old version ends the day before the new one.
        open_profile.effective_to = data.effectiveFrom - timedelta(days=1)

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
    """AWf class from contract facts (NL-015, S6) — the same rule the engine
    applies: LOW only for a WRITTEN INDEFINITE contract that is not on-call, or
    a recorded statutory exception; HIGH otherwise. Returns (class, reason)."""
    facts = AwfContractFacts(is_permanent=contract_term == "INDEFINITE", fixed_term_months=None,
                             has_written_contract=bool(written_record), is_on_call_no_guaranteed_hours=bool(on_call),
                             is_standby_contract=False, statutory_exception_code=statutory_exception_code)
    reason = facts.low_rate_reason()
    return ("LOW", reason) if reason else ("HIGH", "low-rate conditions not met (fixed-term, unwritten or on-call)")


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
        prev.effective_to = data.startDate - timedelta(days=1)

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
            status="COMPLETE" if profile.pki_cert_expires_at and not _expired(profile.pki_cert_expires_at) else "BLOCKED",
            details="Certificate expired" if profile.pki_cert_expires_at and _expired(profile.pki_cert_expires_at) else None,
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



# ══════════════════════════════════════════════════════════════════════════
# Phase 5 — calculation inputs (PayrollContext nl_* kwargs for one payslip)
# ══════════════════════════════════════════════════════════════════════════

def _window(query, model, on: date, start_attr: str = "effective_from", end_attr: str = "effective_to"):
    start, end = getattr(model, start_attr), getattr(model, end_attr)
    return query.filter(start <= on, or_(end.is_(None), end >= on))


def _num(value) -> Optional[str]:
    return None if value is None else str(value)


def nl_profile(db: Session, employee, organization_id: int, on: Optional[date]):
    profile = service.resolve_employee_statutory_profile(db, employee.id, organization_id, on)
    if profile is None or (profile.country_code or "").upper() != NL:
        return None
    return profile


def tax_credit_instruction(db: Session, organization_id: int, employee_id: int, on: date):
    """The signed instruction in force on `on` — the latest by effective date
    (a later instruction supersedes it from its own date, never retroactively)."""
    return (db.query(PayrollNlTaxCreditInstruction)
            .filter(PayrollNlTaxCreditInstruction.organization_id == organization_id,
                    PayrollNlTaxCreditInstruction.employee_id == employee_id,
                    PayrollNlTaxCreditInstruction.effective_from <= on)
            .order_by(PayrollNlTaxCreditInstruction.effective_from.desc(), PayrollNlTaxCreditInstruction.id.desc())
            .first())


def contract_in_force(db: Session, organization_id: int, employee_id: int, on: date):
    q = db.query(PayrollNlContractVersion).filter(PayrollNlContractVersion.organization_id == organization_id,
                                                  PayrollNlContractVersion.employee_id == employee_id)
    return _window(q, PayrollNlContractVersion, on).order_by(PayrollNlContractVersion.version.desc()).first()


def premium_decision_in_force(db: Session, organization_id: int, on: date):
    q = db.query(PayrollNlEmployerPremiumDecision).filter(
        PayrollNlEmployerPremiumDecision.organization_id == organization_id,
        PayrollNlEmployerPremiumDecision.tax_year == on.year,
        PayrollNlEmployerPremiumDecision.status == "ACTIVE")
    return _window(q, PayrollNlEmployerPremiumDecision, on).order_by(
        PayrollNlEmployerPremiumDecision.effective_from.desc()).first()


def committed_vcr_state(db: Session, organization_id: int, employee_id: int, tax_year: int) -> Dict[str, dict]:
    """{family: latest committed state} — {} for a series with no commit yet."""
    out = {}
    for family in VcrFamily.ALL:
        row = (db.query(PayrollNlVcrSnapshot)
               .filter(PayrollNlVcrSnapshot.organization_id == organization_id,
                       PayrollNlVcrSnapshot.employee_id == employee_id,
                       PayrollNlVcrSnapshot.tax_year == tax_year,
                       PayrollNlVcrSnapshot.family == family)
               .order_by(PayrollNlVcrSnapshot.revision.desc()).first())
        if row is not None:
            out[family] = {"period_count": row.period_count, "cumulative_wage": str(row.cumulative_wage),
                           "cumulative_max": str(row.cumulative_max), "cumulative_base": str(row.cumulative_base),
                           "revision": row.revision, "snapshot_id": row.id}
    return out


_CLASSIFICATION_AXES = ("remuneration_type", "wage_tax", "employee_insurance_wage", "zvw_wage", "pensionable",
                        "wkr_treatment", "vacation_allowance_basis", "minimum_wage_reckonable", "evidence_policy")


def earning_classifications(db: Session, organization_id: int, on: date) -> Dict[str, dict]:
    """ACTIVE classifications in force on `on`; an org row overrides the catalog row."""
    q = db.query(PayrollNlEarningClassification).filter(
        PayrollNlEarningClassification.status == "ACTIVE",
        or_(PayrollNlEarningClassification.organization_id.is_(None),
            PayrollNlEarningClassification.organization_id == organization_id))
    out: Dict[str, dict] = {}
    for row in sorted(_window(q, PayrollNlEarningClassification, on).all(), key=lambda r: r.organization_id is not None):
        out[row.earning_code] = {**{a: getattr(row, a) for a in _CLASSIFICATION_AXES}, "id": row.id, "sha256": row.sha256}
    return out


def _table(db: Session, *, tax_year: int, color: Optional[str], residence: Optional[str], period: Optional[str],
           special: bool, on: date) -> Optional[dict]:
    if not color:
        return None
    try:
        key = tables.NlTableKey(tax_year=tax_year, table_color=TableColor(color),
                                table_kind=tables.TableKind.SPECIAL_REMUNERATION if special else tables.TableKind.PERIOD,
                                period=None if special else PeriodCode(period), residence_variant=residence or "NL",
                                aow_cohort=tables.AowCohort.BELOW_AOW, with_tax_credit=False)
    except ValueError:
        return None
    file_row = tables.get_active_table_file(db, key, on)
    if file_row is None:
        return None
    return {"fileId": file_row.id, "fileSha256": file_row.file_sha256, "tableKey": {
        "taxYear": tax_year, "color": color, "kind": key.table_kind.value, "period": file_row.period,
        "residenceVariant": key.residence_variant}, "rows": tables.table_rows(db, file_row.id)}


def _company_cars(db: Session, organization_id: int, employee_id: int, on: date) -> List[dict]:
    q = db.query(PayrollNlCompanyCar).filter(PayrollNlCompanyCar.organization_id == organization_id,
                                            PayrollNlCompanyCar.employee_id == employee_id,
                                            PayrollNlCompanyCar.status == "ACTIVE")
    return [{"id": c.id, "vehicle_class": c.vehicle_class, "addition_rate_window_key": c.addition_rate_window_key,
             "catalog_value": _num(c.catalog_value), "first_admission_date": c.first_admission_date.isoformat(),
             "private_use_status": c.private_use_status, "no_private_use_evidence_ref": c.no_private_use_evidence_ref,
             "employee_own_contribution": _num(c.employee_own_contribution)}
            for c in _window(q, PayrollNlCompanyCar, on).all()]


def _expat_decision(db: Session, organization_id: int, employee_id: int, on: date) -> Optional[dict]:
    row = (db.query(PayrollNlExpatDecision)
           .filter(PayrollNlExpatDecision.organization_id == organization_id,
                   PayrollNlExpatDecision.employee_id == employee_id,
                   PayrollNlExpatDecision.granted_from <= on,
                   or_(PayrollNlExpatDecision.granted_to.is_(None), PayrollNlExpatDecision.granted_to >= on))
           .order_by(PayrollNlExpatDecision.granted_from.desc()).first())
    if row is None:
        return None
    return {"id": row.id, "decision_reference": row.decision_reference, "status": row.status,
            "granted_from": row.granted_from.isoformat(), "granted_to": row.granted_to.isoformat() if row.granted_to else None,
            "method": row.method, "threshold_category": row.threshold_category, "allowance_pct": _num(row.allowance_pct)}


def _pension_scheme(db: Session, profile, on: date) -> Optional[dict]:
    scheme_id = getattr(profile, "nl_pension_scheme_id", None) if profile is not None else None
    if scheme_id is None:
        return None
    row = db.query(PayrollNlPensionScheme).filter(PayrollNlPensionScheme.id == scheme_id).first()
    if row is None or row.status != "ACTIVE" or row.effective_from > on or (row.effective_to and row.effective_to < on):
        # A recorded scheme that is not in force is a configuration error the
        # engine must not silently skip.
        return {"scheme_code": f"scheme#{scheme_id}", "basis_rule": "NOT_IN_FORCE"}
    return {"id": row.id, "scheme_code": row.scheme_code, "basis_rule": row.basis_rule,
            "franchise_amount": _num(row.franchise_amount), "max_pensionable_salary": _num(row.max_pensionable_salary),
            "employee_pct": _num(row.employee_pct), "employer_pct": _num(row.employer_pct),
            "mandatory_sector": row.mandatory_sector}


def _sickness(db: Session, organization_id: int, employee_id: int, period_start: Optional[date],
              period_end: date) -> Optional[dict]:
    start = period_start or period_end
    event = (db.query(PayrollNlSicknessEvent)
             .filter(PayrollNlSicknessEvent.organization_id == organization_id,
                     PayrollNlSicknessEvent.employee_id == employee_id,
                     PayrollNlSicknessEvent.first_sick_day <= period_end,
                     or_(PayrollNlSicknessEvent.recovery_date.is_(None), PayrollNlSicknessEvent.recovery_date >= start))
             .order_by(PayrollNlSicknessEvent.first_sick_day.desc()).first())
    if event is None:
        return None
    q = db.query(PayrollNlAbsencePayPolicy).filter(PayrollNlAbsencePayPolicy.organization_id == organization_id)
    policy = (db.query(PayrollNlAbsencePayPolicy).filter(PayrollNlAbsencePayPolicy.id == event.policy_id).first()
              if event.policy_id else _window(q, PayrollNlAbsencePayPolicy, period_end)
              .order_by(PayrollNlAbsencePayPolicy.effective_from.desc()).first())
    return {"event_id": event.id, "first_sick_day": event.first_sick_day.isoformat(),
            "policy": None if policy is None else {
                "id": policy.id, "waiting_days": policy.waiting_days, "year1_pct": _num(policy.year1_pct),
                "year1_min_wage_floor": policy.year1_min_wage_floor, "year2_pct": _num(policy.year2_pct),
                "cao_enhancements": policy.cao_enhancements or {}}}


def vacation_balance(db: Session, organization_id: int, employee_id: int, year: int) -> Decimal:
    row = (db.query(PayrollNlVacationAllowanceLedger)
           .filter(PayrollNlVacationAllowanceLedger.organization_id == organization_id,
                   PayrollNlVacationAllowanceLedger.employee_id == employee_id,
                   PayrollNlVacationAllowanceLedger.accrual_year == year)
           .order_by(PayrollNlVacationAllowanceLedger.id.desc()).first())
    return Decimal(str(row.balance_after)) if row is not None else Decimal("0")


def resolve_nl_calc_inputs(db: Session, organization_id: int, employee, as_of: Optional[date],
                           period_start: Optional[date] = None) -> dict:
    """Every nl_* PayrollContext field for one payslip. Nothing is defaulted:
    a missing fact stays None and the engine blocks with a precise reason."""
    on = as_of or date.today()
    profile = nl_profile(db, employee, organization_id, on)
    instruction = tax_credit_instruction(db, organization_id, employee.id, on)
    contract = contract_in_force(db, organization_id, employee.id, on)
    decision = premium_decision_in_force(db, organization_id, on)
    try:
        _, _, table_period = normalise_period(getattr(employee, "pay_frequency", None) or "Monthly")
    except Exception:
        table_period = None  # the engine raises the precise period block
    color = getattr(profile, "nl_table_color", None)
    residence = getattr(profile, "nl_residence_variant", None)
    bsn = ((getattr(employee, "compliance_fields", None) or {}).get("bsn") or "").strip()
    return {
        "nl_statutory_profile": profile,
        "nl_organization_id": organization_id,
        "nl_employee_id": employee.id,
        "nl_with_tax_credit": None if instruction is None else bool(instruction.apply_tax_credit),
        "nl_tax_credit_instruction_id": None if instruction is None else instruction.id,
        "nl_anonymous": not bsn,
        "nl_wage_tax_table": _table(db, tax_year=on.year, color=color, residence=residence, period=table_period,
                                    special=False, on=on) if table_period else None,
        "nl_special_tax_table": _table(db, tax_year=on.year, color=color, residence=residence, period=None,
                                       special=True, on=on),
        "nl_contract": None if contract is None else {
            "id": contract.id, "version": contract.version, "contract_term": contract.contract_term,
            "written_record": contract.written_record, "on_call": contract.on_call,
            "statutory_exception_code": contract.statutory_exception_code,
            "agreed_hours_per_week": _num(contract.agreed_hours_per_week)},
        "nl_premium_decision": None if decision is None else {
            "id": decision.id, "aof_size_class": decision.aof_size_class, "whk_wga_pct": _num(decision.whk_wga_pct),
            "whk_wga_employee_recoverable_pct": _num(decision.whk_wga_employee_recoverable_pct),
            "whk_zw_flex_pct": _num(decision.whk_zw_flex_pct), "decision_reference": decision.decision_reference,
            "sha256": decision.sha256},
        "nl_vcr_before": committed_vcr_state(db, organization_id, employee.id, on.year),
        "nl_earning_classifications": earning_classifications(db, organization_id, on),
        "nl_company_cars": _company_cars(db, organization_id, employee.id, on),
        "nl_expat_decision": _expat_decision(db, organization_id, employee.id, on),
        "nl_pension_scheme": _pension_scheme(db, profile, on),
        "nl_sickness": _sickness(db, organization_id, employee.id, period_start, on),
        "nl_vacation_balance_before": vacation_balance(db, organization_id, employee.id, on.year),
    }


def run_committed(db: Session, run: Optional[PayrollRun]) -> bool:
    """True once nl_commit_run has written this run's ledgers (the marker lives
    on the run's approval record; a correction may legitimately write no VCR row)."""
    if run is None or getattr(run, "id", None) is None:
        return False
    if (getattr(run, "nl_approval_fingerprint", None) or {}).get("committedAt"):
        return True
    return db.query(PayrollNlVcrSnapshot.id).filter(PayrollNlVcrSnapshot.payroll_run_id == run.id).first() is not None


def calc_inputs(db: Session, run: Optional[PayrollRun], employee: PayrollEmployee,
                resolved_pack=None, as_of: Optional[date] = None) -> dict:
    """Hook entry point. ``run`` is None on the preview path (non-mutating,
    NL-033). Once a run's NL ledgers are committed its NL payslips are frozen:
    recalculating them would count this run twice in the VCR series (NL-045)."""
    if run_committed(db, run):
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail=(
            "Netherlands: this run's VCR / WKR / vacation-allowance ledgers are committed — its Dutch payslips "
            "cannot be recalculated or added. Use a correction instead (NL-045)."))
    pay_date = as_of or getattr(run, "pay_date", None)
    return resolve_nl_calc_inputs(db, employee.organization_id, employee, pay_date,
                                  period_start=getattr(run, "period_start", None))


# ══════════════════════════════════════════════════════════════════════════
# Phase 5 — run preflight, approval fingerprint, COMMIT
# ══════════════════════════════════════════════════════════════════════════

NL_APPROVAL_ENTITY = "nl_run_approval"


def _nl_items(db: Session, run: PayrollRun) -> List[PayslipItem]:
    return (db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id, PayslipItem.country_code == NL)
            .order_by(PayslipItem.id).all())


def _check(employee_id, key, reason, severity, source="NL engine", action=None) -> dict:
    return {"employeeId": employee_id, "key": key, "reason": reason, "severity": severity, "source": source,
            "action": action}


def nl_run_preflight(db: Session, run: PayrollRun) -> List[dict]:
    """Blocking prerequisites + material exceptions (spec §12 stages 1/3).
    BLOCK items refuse approval; WARN items are shown, never silently dropped."""
    checks: List[dict] = []
    profile = (db.query(PayrollNlEmployerProfile)
               .filter(PayrollNlEmployerProfile.organization_id == run.organization_id,
                       PayrollNlEmployerProfile.effective_to.is_(None)).first())
    if profile is None:
        checks.append(_check(None, "employer_profile", "no Netherlands employer profile", "BLOCK", "employer",
                             "Create the employer registration (spec §10)"))
    else:
        if not profile.loonheffingennummer or not profile.registration_verified_at:
            checks.append(_check(None, "loonheffingennummer", "loonheffingennummer not recorded / not verified",
                                 "BLOCK", "employer", "Verify against the Belastingdienst registration letter (NL-029)"))
        if profile.cao_status == "UNKNOWN":
            checks.append(_check(None, "cao_status", "CAO / mandatory pension applicability is UNKNOWN", "BLOCK",
                                 "employer", "Resolve CAO and sector-pension applicability (NL-043)"))
    for item in _nl_items(db, run):
        snapshot = item.nl_calculation_snapshot
        if not snapshot:
            checks.append(_check(item.employee_id, "snapshot", "payslip has no frozen NL calculation", "BLOCK",
                                 action="Recalculate the run"))
            continue
        stale_action = ("Create the correction again" if snapshot.get("correction") else "Recalculate the payslip")
        for exc in snapshot.get("exceptions") or []:
            checks.append(_check(item.employee_id, exc.get("code"), exc.get("message"), exc.get("severity", "WARN")))
        employee = db.query(PayrollEmployee).filter(PayrollEmployee.id == item.employee_id).first()
        if employee is not None and (employee.compliance_fields or {}).get("bsn"):
            sp = nl_profile(db, employee, run.organization_id, run.pay_date)
            if sp is not None and sp.nl_bsn_verified_at is None:
                checks.append(_check(item.employee_id, "bsn_unverified", "BSN recorded but not verified", "WARN",
                                     action="Verify the BSN against the identity document"))
        # NL-046: the series must not have moved since this payslip was calculated.
        current = committed_vcr_state(db, run.organization_id, item.employee_id, run.pay_date.year)
        for family, after in ((snapshot.get("vcr") or {}).get("after") or {}).items():
            expected = int(after.get("revision", 0)) - 1
            actual = int((current.get(family) or {}).get("revision", 0))
            if actual != expected and not run_committed(db, run):
                checks.append(_check(item.employee_id, "vcr_stale",
                                     f"{family} VCR series moved (calculated on revision {expected}, committed revision "
                                     f"is now {actual})", "BLOCK", action=stale_action))
    return checks


def nl_approval_fingerprint(db: Session, run: PayrollRun, store: bool = False, actor_id: Optional[int] = None) -> dict:
    """NL-034: approval binds every payslip's frozen inputs (which already carry
    the table file, rule pack values, premium decision and VCR-before state)."""
    payslips = [{"id": i.id, "employeeId": i.employee_id,
                 "inputHash": (i.nl_calculation_snapshot or {}).get("inputHash"),
                 "totals": _sha((i.nl_calculation_snapshot or {}).get("totals"))} for i in _nl_items(db, run)]
    fingerprint = _sha({"run": run.id, "engine": ENGINE_VERSION, "payslips": payslips})
    result = {"fingerprint": fingerprint, "payslips": len(payslips)}
    if store:
        # Keeps committedAt: a re-approval never re-opens committed ledgers.
        run.nl_approval_fingerprint = {**(run.nl_approval_fingerprint or {}), "fingerprint": fingerprint,
                                       "approvedBy": actor_id, "approvedAt": datetime.utcnow().isoformat() + "Z"}
    return result


def _vcr_rows(db: Session, run: PayrollRun, item: PayslipItem, snapshot: dict, actor_id):
    vcr = snapshot.get("vcr") or {}
    is_correction = bool(snapshot.get("correction"))
    current = committed_vcr_state(db, run.organization_id, item.employee_id, run.pay_date.year)
    for family, after in (vcr.get("after") or {}).items():
        expected = int(after.get("revision", 0)) - 1
        previous = current.get(family) or {}
        if int(previous.get("revision", 0)) != expected:
            raise HTTPException(http_status.HTTP_409_CONFLICT, detail=(
                f"Netherlands: stale {family} VCR snapshot for employee #{item.employee_id} (calculated on revision "
                f"{expected}, committed revision {previous.get('revision', 0)}) — recalculate before approval (NL-046)."))
        db.add(PayrollNlVcrSnapshot(
            organization_id=run.organization_id, employee_id=item.employee_id, tax_year=run.pay_date.year,
            family=family, revision=int(after["revision"]), payroll_run_id=run.id, payslip_item_id=item.id,
            period_count=int(after["period_count"]), period_max_amount=Decimal(vcr.get("periodMax") or "0"),
            cumulative_wage=Decimal(after["cumulative_wage"]), cumulative_max=Decimal(after["cumulative_max"]),
            cumulative_base=Decimal(after["cumulative_base"]),
            base_increment=Decimal((vcr.get("increments") or {}).get(family) or "0"),
            previous_snapshot_id=previous.get("snapshot_id"), is_correction=is_correction,
            snapshot_sha256=_sha({"item": item.id, "family": family, "after": after}), created_by=actor_id))


def _vacation_rows(db: Session, run: PayrollRun, item: PayslipItem, snapshot: dict):
    vac = snapshot.get("vacationAllowance") or {}
    accrual, payout = Decimal(vac.get("accrual") or "0"), Decimal(vac.get("payout") or "0")
    balance = vacation_balance(db, run.organization_id, item.employee_id, run.pay_date.year)
    period = (snapshot.get("periodCode") or "MONTHLY")
    entries = (("ACCRUAL", accrual, 1), ("PAYOUT", payout, -1))
    if snapshot.get("correction"):
        # A correction books one signed CORRECTION entry (NL-045).
        entries = (("CORRECTION", accrual - payout, 1),)
    for entry_type, amount, sign in entries:
        if amount == 0:
            continue
        balance = balance + sign * amount
        db.add(PayrollNlVacationAllowanceLedger(
            organization_id=run.organization_id, employee_id=item.employee_id, accrual_year=run.pay_date.year,
            period=period, entry_type=entry_type, basis_amount=Decimal(vac.get("basis") or "0"),
            pct=Decimal(vac.get("pct") or "0"), amount=amount, balance_after=balance, payroll_run_id=run.id,
            payslip_item_id=item.id))
        db.flush()


def _wkr_row(db: Session, run: PayrollRun, snapshots: List[dict]):
    if not snapshots:
        return None
    profile = (db.query(PayrollNlEmployerProfile)
               .filter(PayrollNlEmployerProfile.organization_id == run.organization_id,
                       PayrollNlEmployerProfile.effective_to.is_(None)).first())
    concern_id = profile.wkr_concern_id if profile is not None and profile.wkr_mode == "CONCERN" else None
    latest = (db.query(PayrollNlWkrAccumulator)
              .filter(PayrollNlWkrAccumulator.organization_id == run.organization_id,
                      PayrollNlWkrAccumulator.tax_year == run.pay_date.year,
                      PayrollNlWkrAccumulator.concern_id.is_(None) if concern_id is None
                      else PayrollNlWkrAccumulator.concern_id == concern_id)
              .order_by(PayrollNlWkrAccumulator.revision.desc()).first())
    state = wkr_engine.WkrState() if latest is None else wkr_engine.WkrState(
        fiscal_wage_cumulative=Decimal(latest.fiscal_wage_cumulative),
        designated_wage_cumulative=Decimal(latest.designated_wage_cumulative),
        targeted_exemptions_cumulative=Decimal(latest.targeted_exemptions_cumulative), revision=latest.revision)
    # The WKR bands are read from the frozen inputs, never a live lookup.
    slabs = [SimpleNamespace(rule_type=s["ruleType"], filing_status=s["key"], rate_pct=s.get("rate"),
                             min_amount=s.get("min"), max_amount=s.get("max"))
             for s in (snapshots[0].get("inputs") or {}).get("slabs") or [] if s.get("ruleType") == "NL_WKR_BAND"]
    fiscal = sum((Decimal((s.get("wkr") or {}).get("fiscalWage") or "0") for s in snapshots), Decimal("0"))
    designated = sum((Decimal((s.get("wkr") or {}).get("designated") or "0") for s in snapshots), Decimal("0"))
    targeted = sum((Decimal((s.get("wkr") or {}).get("targetedExemptions") or "0") for s in snapshots), Decimal("0"))
    try:
        position = wkr_engine.advance(state, fiscal_wage=fiscal, designated=designated, targeted=targeted, slabs=slabs)
    except wkr_engine.WkrError as exc:
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail=f"Netherlands WKR: {exc}")
    row = PayrollNlWkrAccumulator(
        organization_id=run.organization_id, concern_id=concern_id, tax_year=run.pay_date.year,
        revision=position.state.revision, fiscal_wage_cumulative=position.state.fiscal_wage_cumulative,
        free_space_available=position.free_space_available,
        designated_wage_cumulative=position.state.designated_wage_cumulative,
        targeted_exemptions_cumulative=position.state.targeted_exemptions_cumulative,
        excess_amount=position.excess_amount, excess_levy_80=position.excess_levy, payroll_run_id=run.id,
        snapshot_sha256=_sha({"run": run.id, **position.as_dict()}))
    db.add(row)
    return row


def nl_commit_run(db: Session, run: PayrollRun, actor_id: Optional[int] = None) -> dict:
    """Spec §12 stage 5: write the VCR snapshots, vacation-allowance ledger and
    the employer WKR revision from the approved payslips' frozen results. Atomic
    with the run transition (flush only) and idempotent per run."""
    if run_committed(db, run):
        return {"committed": False, "alreadyCommitted": True}
    items = _nl_items(db, run)
    snapshots = []
    for item in items:
        snapshot = item.nl_calculation_snapshot or {}
        _vcr_rows(db, run, item, snapshot, actor_id)
        db.flush()
        _vacation_rows(db, run, item, snapshot)
        snapshots.append(snapshot)
    _wkr_row(db, run, snapshots)
    run.nl_approval_fingerprint = {**(run.nl_approval_fingerprint or {}),
                                   "committedAt": datetime.utcnow().isoformat() + "Z", "committedBy": actor_id}
    db.flush()
    return {"committed": True, "payslips": len(items)}


def _nl_before_run_transition(db: Session, run: PayrollRun, next_status, actor_id) -> None:
    """At APPROVED: every NL payslip carries its frozen calculation, preflight
    has no BLOCK, the approval is bound by fingerprint and the ledgers are
    committed. Later stages re-verify the fingerprint (NL-034)."""
    if not _nl_items(db, run):
        return
    if next_status == PayrollStatus.APPROVED:
        blocks = [c for c in nl_run_preflight(db, run) if c["severity"] == "BLOCK"]
        if blocks:
            details = "; ".join(f"Emp {c['employeeId'] or 'N/A'}: {c['key']} — {c['reason']}" for c in blocks)
            raise HTTPException(http_status.HTTP_409_CONFLICT,
                                detail=f"Netherlands preflight has {len(blocks)} BLOCK item(s): {details}")
        nl_approval_fingerprint(db, run, store=True, actor_id=actor_id)
        nl_commit_run(db, run, actor_id)
    elif next_status in (PayrollStatus.AUTHORIZED, PayrollStatus.PAID):
        stored = (run.nl_approval_fingerprint or {}).get("fingerprint")
        if not stored:
            raise HTTPException(http_status.HTTP_409_CONFLICT, detail=(
                "Netherlands: no approval fingerprint is recorded for this run — approve it first (NL-034)."))
        if nl_approval_fingerprint(db, run)["fingerprint"] != stored:
            raise HTTPException(http_status.HTTP_409_CONFLICT, detail=(
                "Netherlands: the run changed after approval (fingerprint mismatch) — use a correction (NL-034)."))


# ══════════════════════════════════════════════════════════════════════════
# Phase 6 — classifications, premium decisions, company cars, expat
# ══════════════════════════════════════════════════════════════════════════

def create_earning_classification(db: Session, *, organization_id: Optional[int], earning_code: str,
                                  effective_from: date, remuneration_type: str, wage_tax: bool,
                                  employee_insurance_wage: bool, zvw_wage: bool, pensionable: bool,
                                  wkr_treatment: str, vacation_allowance_basis: bool, minimum_wage_reckonable: bool,
                                  evidence_policy: str = "NONE") -> PayrollNlEarningClassification:
    """A new effective-dated classification; the one it replaces (same scope
    and code) is end-dated the day before and SUPERSEDED."""
    if wkr_treatment not in wkr_engine.TREATMENTS:
        raise BadRequestException(f"wkr_treatment must be one of {', '.join(wkr_engine.TREATMENTS)} (NL-022)")
    if remuneration_type not in ("REGULAR", "SPECIAL"):
        raise BadRequestException("remuneration_type must be REGULAR or SPECIAL")
    values = {"remuneration_type": remuneration_type, "wage_tax": wage_tax,
              "employee_insurance_wage": employee_insurance_wage, "zvw_wage": zvw_wage, "pensionable": pensionable,
              "wkr_treatment": wkr_treatment, "vacation_allowance_basis": vacation_allowance_basis,
              "minimum_wage_reckonable": minimum_wage_reckonable, "evidence_policy": evidence_policy}
    scope = (PayrollNlEarningClassification.organization_id.is_(None) if organization_id is None
             else PayrollNlEarningClassification.organization_id == organization_id)
    previous = (db.query(PayrollNlEarningClassification)
                .filter(scope, PayrollNlEarningClassification.earning_code == earning_code,
                        PayrollNlEarningClassification.status == "ACTIVE",
                        PayrollNlEarningClassification.effective_to.is_(None)).first())
    if previous is not None:
        if previous.effective_from >= effective_from:
            raise BadRequestException("a new classification must start after the one it replaces")
        previous.effective_to = effective_from - timedelta(days=1)
        previous.status = "SUPERSEDED"
    row = PayrollNlEarningClassification(organization_id=organization_id, earning_code=earning_code,
                                         effective_from=effective_from, status="ACTIVE",
                                         sha256=_sha({"code": earning_code, "from": effective_from, **values}), **values)
    db.add(row)
    db.flush()
    return row


def create_premium_decision(db: Session, *, organization_id: int, tax_year: int, aof_size_class: str,
                            aof_basis_year: int, aof_basis_premium_wage: Decimal, decision_reference: str,
                            decision_date: date, effective_from: date, actor_id: int,
                            whk_wga_pct: Optional[Decimal] = None, whk_zw_flex_pct: Optional[Decimal] = None,
                            whk_wga_employee_recoverable_pct: Optional[Decimal] = None,
                            sector_code: Optional[str] = None,
                            evidence_artifact_id: Optional[int] = None) -> PayrollNlEmployerPremiumDecision:
    """DRAFT employer premium decision with its source evidence (NL-017)."""
    if aof_size_class not in ("SMALL", "LARGE"):
        raise BadRequestException("aof_size_class must be SMALL or LARGE")
    values = {"tax_year": tax_year, "aof_size_class": aof_size_class, "aof_basis_year": aof_basis_year,
              "aof_basis_premium_wage": aof_basis_premium_wage, "whk_wga_pct": whk_wga_pct,
              "whk_zw_flex_pct": whk_zw_flex_pct, "whk_wga_employee_recoverable_pct": whk_wga_employee_recoverable_pct,
              "sector_code": sector_code, "decision_reference": decision_reference, "decision_date": decision_date,
              "effective_from": effective_from}
    row = PayrollNlEmployerPremiumDecision(organization_id=organization_id, status="DRAFT", created_by=actor_id,
                                           evidence_artifact_id=evidence_artifact_id, sha256=_sha(values), **values)
    db.add(row)
    db.flush()
    return row


def activate_premium_decision(db: Session, decision_id: int, organization_id: int, actor_id: int) -> PayrollNlEmployerPremiumDecision:
    """Four-eyes: the creator cannot activate. Activation supersedes the
    decision in force for the same year from the day before."""
    row = (db.query(PayrollNlEmployerPremiumDecision)
           .filter(PayrollNlEmployerPremiumDecision.id == decision_id,
                   PayrollNlEmployerPremiumDecision.organization_id == organization_id).first())
    if row is None:
        raise NotFoundException("PayrollNlEmployerPremiumDecision", decision_id)
    if row.status != "DRAFT":
        raise BadRequestException(f"only a DRAFT decision can be activated (status {row.status})")
    if row.created_by == actor_id:
        raise BadRequestException("the creator of a premium decision cannot activate it (four-eyes)")
    if row.whk_wga_pct is None or row.whk_zw_flex_pct is None:
        raise BadRequestException("Whk WGA and ZW-flex rates are required — there is no universal Whk rate (NL-017)")
    current = (db.query(PayrollNlEmployerPremiumDecision)
               .filter(PayrollNlEmployerPremiumDecision.organization_id == organization_id,
                       PayrollNlEmployerPremiumDecision.tax_year == row.tax_year,
                       PayrollNlEmployerPremiumDecision.status == "ACTIVE").all())
    for old in current:
        old.status = "SUPERSEDED"
        old.effective_to = row.effective_from - timedelta(days=1)
    row.status = "ACTIVE"
    row.approved_by = actor_id
    db.flush()
    return row


def add_company_car(db: Session, *, organization_id: int, employee_id: int, catalog_value: Decimal,
                    first_admission_date: date, addition_rate_window_key: str, effective_from: date,
                    vehicle_class: Optional[str] = None, plate_masked: Optional[str] = None,
                    private_use_status: str = "PRIVATE", no_private_use_evidence_ref: Optional[str] = None,
                    employee_own_contribution: Decimal = Decimal("0")) -> PayrollNlCompanyCar:
    _employee(db, employee_id, organization_id)
    if private_use_status == "NO_PRIVATE_USE_500KM" and not no_private_use_evidence_ref:
        raise BadRequestException("'no private use' needs the ≤500 km evidence reference (NL-024)")
    row = PayrollNlCompanyCar(organization_id=organization_id, employee_id=employee_id, catalog_value=catalog_value,
                              first_admission_date=first_admission_date, vehicle_class=vehicle_class,
                              addition_rate_window_key=addition_rate_window_key, plate_masked=plate_masked,
                              private_use_status=private_use_status,
                              no_private_use_evidence_ref=no_private_use_evidence_ref,
                              employee_own_contribution=employee_own_contribution, effective_from=effective_from)
    db.add(row)
    db.flush()
    return row


def record_expat_decision(db: Session, *, organization_id: int, employee_id: int, decision_reference: str,
                          decision_date: date, granted_from: date, method: str, threshold_category: str,
                          allowance_pct: Decimal, granted_to: Optional[date] = None,
                          evidence_artifact_id: Optional[int] = None) -> PayrollNlExpatDecision:
    """Recorded as PENDING — payroll ignores it until verified (NL-026)."""
    _employee(db, employee_id, organization_id)
    row = PayrollNlExpatDecision(organization_id=organization_id, employee_id=employee_id,
                                 decision_reference=decision_reference, decision_date=decision_date,
                                 granted_from=granted_from, granted_to=granted_to, method=method,
                                 threshold_category=threshold_category, allowance_pct=allowance_pct,
                                 evidence_artifact_id=evidence_artifact_id, status="PENDING")
    db.add(row)
    db.flush()
    return row


def verify_expat_decision(db: Session, decision_id: int, organization_id: int, actor_id: int) -> PayrollNlExpatDecision:
    row = (db.query(PayrollNlExpatDecision)
           .filter(PayrollNlExpatDecision.id == decision_id,
                   PayrollNlExpatDecision.organization_id == organization_id).first())
    if row is None:
        raise NotFoundException("PayrollNlExpatDecision", decision_id)
    if row.evidence_artifact_id is None:
        raise BadRequestException("the Belastingdienst decision document must be attached before verification (NL-026)")
    row.status = "VERIFIED"
    row.verified_by = actor_id
    row.verified_at = datetime.utcnow()
    db.flush()
    return row


def revoke_expat_decision(db: Session, decision_id: int, organization_id: int, actor_id: int) -> PayrollNlExpatDecision:
    """The authority decision no longer applies: payroll stops applying the
    facility from now on (committed payslips are never rewritten — use a
    correction for any retroactive effect)."""
    row = (db.query(PayrollNlExpatDecision)
           .filter(PayrollNlExpatDecision.id == decision_id,
                   PayrollNlExpatDecision.organization_id == organization_id).first())
    if row is None:
        raise NotFoundException("PayrollNlExpatDecision", decision_id)
    if row.status not in ("PENDING", "VERIFIED"):
        raise BadRequestException(f"a {row.status} decision cannot be revoked")
    row.status = "REVOKED"
    db.flush()
    return row


# ══════════════════════════════════════════════════════════════════════════
# Phase 7 — pension, absence pay, sickness, termination
# ══════════════════════════════════════════════════════════════════════════

def create_pension_scheme(db: Session, *, organization_id: Optional[int], fund_name: str, scheme_code: str,
                          effective_from: date, basis_rule: str, employee_pct: Decimal, employer_pct: Decimal,
                          franchise_amount: Decimal = Decimal("0"), max_pensionable_salary: Optional[Decimal] = None,
                          mandatory_sector: bool = False, collective_agreement_id: Optional[int] = None,
                          evidence_artifact_id: Optional[int] = None) -> PayrollNlPensionScheme:
    if basis_rule not in ("GROSS_MINUS_FRANCHISE", "CAPPED_PENSIONABLE"):
        raise BadRequestException("basis_rule must be GROSS_MINUS_FRANCHISE or CAPPED_PENSIONABLE")
    if basis_rule == "CAPPED_PENSIONABLE" and max_pensionable_salary is None:
        raise BadRequestException("CAPPED_PENSIONABLE needs a maximum pensionable salary")
    if mandatory_sector and evidence_artifact_id is None:
        raise BadRequestException("a mandatory sector scheme needs its applicability evidence (NL-043)")
    row = PayrollNlPensionScheme(organization_id=organization_id, fund_name=fund_name, scheme_code=scheme_code,
                                 effective_from=effective_from, basis_rule=basis_rule, employee_pct=employee_pct,
                                 employer_pct=employer_pct, franchise_amount=franchise_amount,
                                 max_pensionable_salary=max_pensionable_salary, mandatory_sector=mandatory_sector,
                                 collective_agreement_id=collective_agreement_id,
                                 evidence_artifact_id=evidence_artifact_id, status="ACTIVE")
    db.add(row)
    db.flush()
    return row


def create_absence_pay_policy(db: Session, *, organization_id: int, effective_from: date, year1_pct: Decimal,
                              year2_pct: Decimal, waiting_days: int = 0, year1_min_wage_floor: bool = True,
                              cao_enhancements: Optional[dict] = None) -> PayrollNlAbsencePayPolicy:
    row = PayrollNlAbsencePayPolicy(organization_id=organization_id, effective_from=effective_from,
                                    year1_pct=year1_pct, year2_pct=year2_pct, waiting_days=waiting_days,
                                    year1_min_wage_floor=year1_min_wage_floor, cao_enhancements=cao_enhancements)
    db.add(row)
    db.flush()
    return row


def record_sickness_event(db: Session, *, organization_id: int, employee_id: int, first_sick_day: date,
                          policy_id: Optional[int] = None) -> PayrollNlSicknessEvent:
    _employee(db, employee_id, organization_id)
    row = PayrollNlSicknessEvent(organization_id=organization_id, employee_id=employee_id,
                                 first_sick_day=first_sick_day, policy_id=policy_id, status="ACTIVE")
    db.add(row)
    db.flush()
    return row


def close_sickness_event(db: Session, event_id: int, organization_id: int, recovery_date: date) -> PayrollNlSicknessEvent:
    row = (db.query(PayrollNlSicknessEvent)
           .filter(PayrollNlSicknessEvent.id == event_id, PayrollNlSicknessEvent.organization_id == organization_id).first())
    if row is None:
        raise NotFoundException("PayrollNlSicknessEvent", event_id)
    if recovery_date < row.first_sick_day:
        raise BadRequestException("recovery date cannot be before the first sick day")
    row.recovery_date = recovery_date
    row.status = "RECOVERED"
    db.flush()
    return row


def _pack_value(db: Session, key: str, on: date):
    """A scalar from the NL tax pack in force (amount, text or %)."""
    from app.modules.payroll.models import ContributionRate, JurisdictionPack

    row = (db.query(ContributionRate).join(JurisdictionPack, ContributionRate.jurisdiction_pack_id == JurisdictionPack.id)
           .filter(JurisdictionPack.jurisdiction_country == NL, ContributionRate.component_key == key,
                   ContributionRate.organization_id.is_(None),
                   or_(JurisdictionPack.effective_from.is_(None), JurisdictionPack.effective_from <= on),
                   or_(JurisdictionPack.effective_to.is_(None), JurisdictionPack.effective_to >= on))
           .order_by(JurisdictionPack.effective_from.desc()).first())
    if row is None:
        return None
    return row.flat_amount if row.flat_amount is not None else (row.text_value or row.employee_rate_pct or row.employer_rate_pct)


def prepare_termination_settlement(db: Session, *, organization_id: int, employee_id: int, termination_date: date,
                                   reason: str, initiated_by: str, service_months: int, monthly_salary: Decimal,
                                   annual_salary: Decimal, unused_leave_hours: Decimal, hourly_wage: Decimal,
                                   actor_id: int, income_relationship_id: Optional[int] = None) -> PayrollNlTerminationSettlement:
    """NL-044: final-pay components kept separate, computed from the pack in
    force on the termination date; DRAFT until a second person approves."""
    _employee(db, employee_id, organization_id)
    if initiated_by not in ("EMPLOYER", "EMPLOYEE", "MUTUAL"):
        raise BadRequestException("initiated_by must be EMPLOYER, EMPLOYEE or MUTUAL")
    cap = _pack_value(db, "nl_transition_payment_cap", termination_date)
    fraction = _pack_value(db, "nl_transition_payment_month_frac", termination_date)
    try:
        tp = transition_payment.calculate(initiated_by=initiated_by, service_months=service_months,
                                          monthly_salary=monthly_salary, annual_salary=annual_salary,
                                          statutory_cap=None if cap is None else Decimal(str(cap)),
                                          month_fraction=None if fraction is None else str(fraction))
    except transition_payment.TransitionPaymentError as exc:
        raise BadRequestException(f"Netherlands transition payment: {exc}")
    leave_payout = (Decimal(unused_leave_hours) * Decimal(hourly_wage)).quantize(Decimal("0.01"))
    vacation_payout = vacation_balance(db, organization_id, employee_id, termination_date.year)
    row = PayrollNlTerminationSettlement(
        organization_id=organization_id, employee_id=employee_id, income_relationship_id=income_relationship_id,
        termination_date=termination_date, reason=reason, initiated_by=initiated_by,
        transition_payment_eligible=tp.eligible, service_months=service_months, monthly_salary_basis=monthly_salary,
        transition_payment_amount=tp.amount, cap_applied=tp.cap_applied, unused_leave_hours=unused_leave_hours,
        leave_payout=leave_payout, vacation_allowance_payout=vacation_payout,
        tax_treatment={"transitionPayment": tp.as_dict(),
                       "note": "each component is paid as its own earning code; wage-tax treatment follows its "
                               "classification (special remuneration) — never netted together (NL-044)"},
        status="DRAFT", prepared_by=actor_id)
    db.add(row)
    db.flush()
    return row


def approve_termination_settlement(db: Session, settlement_id: int, organization_id: int, actor_id: int) -> PayrollNlTerminationSettlement:
    row = (db.query(PayrollNlTerminationSettlement)
           .filter(PayrollNlTerminationSettlement.id == settlement_id,
                   PayrollNlTerminationSettlement.organization_id == organization_id).first())
    if row is None:
        raise NotFoundException("PayrollNlTerminationSettlement", settlement_id)
    if row.status != "DRAFT":
        raise BadRequestException(f"only a DRAFT settlement can be approved (status {row.status})")
    try:
        transition_payment.validate_four_eyes(row.prepared_by, actor_id)
    except transition_payment.FourEyesError as exc:
        raise BadRequestException(str(exc))
    row.status = "APPROVED"
    row.approved_by = actor_id
    row.approved_at = datetime.utcnow()
    db.flush()
    return row


# ══════════════════════════════════════════════════════════════════════════
# Phase 8 — corrections, back-pay methods, AWf revision (NL-011/016/045)
# ══════════════════════════════════════════════════════════════════════════
#
# A committed payslip is immutable (NL-045). A correction:
#   1. replays the payslip's frozen inputs and refuses unless that reproduces
#      the original exactly (no live pack / table / VCR lookup — the original
#      table file is re-read by its pinned id and sha256, NL-004);
#   2. recomputes the ORIGINAL period with the restated inputs (its own table,
#      pack values and VCR-before position);
#   3. books the difference as a delta payslip in an "[NL-CORRECTION]" run.
#      A change in premium wage is applied at the LATEST point of the VCR
#      series as a new revision (catch-up / negative increments, NL-012), so
#      later committed periods are never rewritten;
#   4. commits through the normal approval of that run (NL-033).

NL_CORRECTION_MARKER = "[NL-CORRECTION]"
_FINALIZED_RUN_STATUSES = ("Approved", "Authorized", "Paid", "Closed")
BACK_PAY_METHODS = {
    "REPROCESS_ORIGINAL_PERIOD": "Recompute the original period with its own table, pack and VCR position, and book "
                                 "the difference as a correction (NL-004/NL-011).",
    "SPECIAL_REMUNERATION_CURRENT_PERIOD": "Pay the back-pay in the current period as an earning classified SPECIAL, "
                                           "taxed through the special-remuneration table (NL-010/NL-011).",
}
_CORRECTABLE_INPUTS = ("earnings", "contract", "periodHours")
_CORRECTABLE_CONTRACT_FACTS = ("contract_term", "written_record", "on_call", "statutory_exception_code",
                               "awf_revision_trigger")


def is_nl_correction_run(run) -> bool:
    return bool(run is not None and (run.notes or "").startswith(NL_CORRECTION_MARKER))


def _dec(value, default="0") -> Decimal:
    return Decimal(str(value if value not in (None, "") else default))


def _opt_dec(value) -> Optional[Decimal]:
    return None if value in (None, "") else Decimal(str(value))


def _opt_date(value) -> Optional[date]:
    if value in (None, ""):
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _thaw_rate(entry: dict):
    if "value" in entry:
        return entry["value"]
    return SimpleNamespace(employee_rate_pct=_opt_dec(entry.get("employee")),
                           employer_rate_pct=_opt_dec(entry.get("employer")),
                           flat_amount=_opt_dec(entry.get("amount")), text_value=entry.get("text"))


def _thaw_slab(entry: dict):
    return SimpleNamespace(rule_type=entry["ruleType"], filing_status=entry["key"], min_amount=_opt_dec(entry.get("min")),
                           max_amount=_opt_dec(entry.get("max")), rate_pct=_opt_dec(entry.get("rate")),
                           flat_amount=_opt_dec(entry.get("amount")), effective_from=_opt_date(entry.get("from")),
                           effective_to=_opt_date(entry.get("to")))


def _thaw_table(db: Session, ref: Optional[dict]) -> Optional[dict]:
    if not ref or not ref.get("fileId"):
        return None
    from app.modules.payroll.models import PayrollNlTaxTableFile

    file_row = db.query(PayrollNlTaxTableFile).filter(PayrollNlTaxTableFile.id == ref["fileId"]).first()
    if file_row is None or file_row.file_sha256 != ref.get("fileSha256"):
        raise BadRequestException(f"the wage-tax table file #{ref['fileId']} this payslip used is missing or changed "
                                  "— it cannot be replayed exactly (NL-004)")
    return {**ref, "rows": tables.table_rows(db, file_row.id)}


def nl_thaw_context(db: Session, frozen: dict):
    """Rebuild the PayrollContext from a payslip's frozen inputs."""
    from app.modules.payroll.engine.base import PayrollContext

    vcr_before = frozen.get("vcrBefore")
    return PayrollContext(
        gross=_dec(frozen.get("gross")), basic=_dec(frozen.get("basic")), country=NL,
        pay_date=_opt_date(frozen.get("payDate")), period_start=_opt_date(frozen.get("periodStart")),
        period_end=_opt_date(frozen.get("periodEnd")), date_of_birth=_opt_date(frozen.get("dateOfBirth")),
        pay_frequency=frozen.get("payFrequency") or "Monthly",
        rate_map={k: _thaw_rate(v) for k, v in (frozen.get("rates") or {}).items()},
        slabs=[_thaw_slab(s) for s in frozen.get("slabs") or []],
        nl_statutory_profile=SimpleNamespace(**(frozen.get("profile") or {})),
        nl_with_tax_credit=frozen.get("withTaxCredit"),
        nl_tax_credit_instruction_id=frozen.get("taxCreditInstructionId"),
        nl_anonymous=bool(frozen.get("anonymous")),
        nl_wage_tax_table=_thaw_table(db, frozen.get("wageTaxTable")),
        nl_special_tax_table=_thaw_table(db, frozen.get("specialTaxTable")),
        nl_reference_annual_wage=_opt_dec(frozen.get("referenceAnnualWage")),
        nl_contract=frozen.get("contract"), nl_premium_decision=frozen.get("premiumDecision"),
        nl_vcr_before=vcr_before if vcr_before is not None else {},
        nl_earnings={k: _dec(v) for k, v in (frozen.get("earnings") or {}).items()},
        nl_earning_classifications=frozen.get("classifications") or {},
        nl_company_cars=frozen.get("companyCars") or [], nl_expat_decision=frozen.get("expatDecision"),
        nl_pension_scheme=frozen.get("pensionScheme"), nl_sickness=frozen.get("sickness"),
        nl_period_hours=_opt_dec(frozen.get("periodHours")),
        nl_vacation_balance_before=_opt_dec(frozen.get("vacationBalanceBefore")),
    )


def nl_replay(db: Session, frozen: dict) -> dict:
    """The engine's nl_result for a frozen context — no live lookup."""
    from app.modules.payroll.engine.countries.netherlands import calculate

    return calculate(nl_thaw_context(db, frozen))["nl_result"]


def _position(result: dict) -> dict:
    """The money position of one period, normalised (from an nl_result)."""
    totals = result.get("totals") or {}
    ei = result.get("employeeInsurance") or {}
    vac = result.get("vacationAllowance") or {}
    return {
        "gross": totals.get("gross", "0"), "wageTax": totals.get("wageTax", "0"),
        "pensionEe": totals.get("pensionEmployee", "0"), "pensionEr": totals.get("pensionEmployer", "0"),
        "zvwEe": totals.get("zvwEmployee", "0"), "zvwEr": (result.get("zvw") or {}).get("employerLevy", "0"),
        "whkEe": totals.get("whkEmployee", "0"),
        "premiums": {k: ei.get(k, "0") for k in ("awf", "aof", "wko", "whk")},
        "increments": dict((result.get("vcr") or {}).get("increments") or {}),
        "periodAfter": dict((result.get("vcr") or {}).get("after") or {}),
        "vacAccrual": vac.get("accrual", "0"), "vacPayout": vac.get("payout", "0"), "vacBasis": vac.get("basis", "0"),
        "vacPct": vac.get("pct", "0"),
        "wkr": dict(result.get("wkr") or {}),
    }


def _correction_chain(db: Session, item: PayslipItem) -> List[PayslipItem]:
    candidates = (db.query(PayslipItem).join(PayrollRun, PayslipItem.payroll_run_id == PayrollRun.id)
                  .filter(PayslipItem.employee_id == item.employee_id, PayslipItem.country_code == NL,
                          PayrollRun.notes.like(f"{NL_CORRECTION_MARKER}%"))
                  .order_by(PayslipItem.id).all())
    return [c for c in candidates
            if ((c.nl_calculation_snapshot or {}).get("correction") or {}).get("originalPayslipId") == item.id]


def _apply_corrected_inputs(basis: dict, corrected_inputs: dict) -> dict:
    unknown = sorted(set(corrected_inputs) - set(_CORRECTABLE_INPUTS))
    if unknown:
        raise BadRequestException(
            f"cannot restate {unknown} by correction — only {list(_CORRECTABLE_INPUTS)}. A tax-credit instruction or "
            "profile change takes effect from its own date and never silently recalculates prior payroll (NL-031).")
    frozen = json.loads(json.dumps(basis))
    if "earnings" in corrected_inputs:
        old = {k: _dec(v) for k, v in (frozen.get("earnings") or {}).items()}
        new = {**old, **{k: _dec(v) for k, v in (corrected_inputs["earnings"] or {}).items()}}
        delta = sum(new.values(), Decimal("0")) - sum(old.values(), Decimal("0"))
        frozen["earnings"] = {k: str(v) for k, v in new.items()}
        frozen["gross"] = str(_dec(frozen.get("gross")) + delta)
        if "base_salary" in corrected_inputs["earnings"]:
            frozen["basic"] = str(new["base_salary"])
    if "contract" in corrected_inputs:
        bad = sorted(set(corrected_inputs["contract"] or {}) - set(_CORRECTABLE_CONTRACT_FACTS))
        if bad:
            raise BadRequestException(f"contract facts {bad} cannot be restated (allowed: {list(_CORRECTABLE_CONTRACT_FACTS)})")
        if frozen.get("contract") is None:
            raise BadRequestException("this payslip had no contract version — nothing to restate")
        frozen["contract"] = {**frozen["contract"], **corrected_inputs["contract"]}
    if "periodHours" in corrected_inputs:
        frozen["periodHours"] = str(_dec(corrected_inputs["periodHours"]))
    return frozen


def _amount(base: Decimal, rate) -> Decimal:
    return (base * _dec(rate) / Decimal("100")).quantize(Decimal("0.01"), rounding="ROUND_HALF_UP")


def _trace_rate(result: dict, code: str):
    return next((t.get("rate") for t in result.get("trace") or [] if t.get("code") == code), None)


def create_nl_correction(db: Session, organization_id: int, original_payslip_id: int, reason: str, method: str,
                         corrected_inputs: Optional[dict], actor_id: Optional[int],
                         correction_run: Optional[PayrollRun] = None) -> dict:
    """Append-only correction of a committed NL payslip (NL-011/NL-045).
    Flushes only; the caller commits."""
    if not (reason or "").strip():
        raise BadRequestException("A correction needs a reason.")
    if method not in BACK_PAY_METHODS:
        raise BadRequestException(f"method must be one of {sorted(BACK_PAY_METHODS)} — there is no generic retro rate (NL-011)")
    if method == "SPECIAL_REMUNERATION_CURRENT_PERIOD":
        raise BadRequestException(
            "SPECIAL_REMUNERATION_CURRENT_PERIOD is not a correction of the past period: pay the back-pay in the current "
            "run as an earning classified SPECIAL (special-remuneration table, NL-010). REPROCESS_ORIGINAL_PERIOD "
            "corrects the original period instead.")
    item = db.query(PayslipItem).filter(PayslipItem.id == original_payslip_id,
                                        PayslipItem.organization_id == organization_id).first()
    if item is None:
        raise NotFoundException("Payslip", original_payslip_id)
    if (item.country_code or "").upper() != NL:
        raise BadRequestException("NL corrections apply to Netherlands payslips only.")
    snapshot = item.nl_calculation_snapshot or {}
    if snapshot.get("correction"):
        raise BadRequestException("Correct the original payslip, not a correction delta.")
    run = db.query(PayrollRun).filter(PayrollRun.id == item.payroll_run_id).one()
    if str(getattr(run.status, "value", run.status)) not in _FINALIZED_RUN_STATUSES or not run_committed(db, run):
        raise BadRequestException("This payslip's run is not committed — recalculate it in place instead.")
    frozen = snapshot.get("inputs")
    if not frozen:
        raise BadRequestException("This payslip has no frozen NL inputs, so it cannot be replayed exactly.")

    # 1. integrity: the frozen inputs must reproduce the original exactly
    replay = nl_replay(db, frozen)
    if (replay.get("inputHash"), replay.get("totals")) != (snapshot.get("inputHash"), snapshot.get("totals")):
        raise BadRequestException("Replaying the frozen inputs does not reproduce the original payslip — refusing to "
                                  "correct on a drifted basis.")

    # 2. restate on the latest basis of the chain (earlier corrections stay applied)
    chain = _correction_chain(db, item)
    last = (chain[-1].nl_calculation_snapshot or {}).get("correction") if chain else None
    basis_frozen = last["frozen"] if last else frozen
    effective = last["corrected"] if last else _position(snapshot)
    new_frozen = _apply_corrected_inputs(basis_frozen, corrected_inputs or {})
    corrected_result = nl_replay(db, new_frozen)
    corrected = _position(corrected_result)

    # 3. VCR: apply the change in premium wage at the latest series point
    current = committed_vcr_state(db, organization_id, item.employee_id, run.pay_date.year)
    vcr_before, vcr_after, vcr_increments, eff_increments = {}, {}, {}, {}
    for family, period_after in corrected["periodAfter"].items():
        old_after = effective["periodAfter"].get(family) or {}
        d_wage = _dec(period_after.get("cumulative_wage")) - _dec(old_after.get("cumulative_wage"))
        d_base = Decimal("0")
        if d_wage:
            latest = current.get(family)
            if latest is None:
                raise BadRequestException(f"no committed {family} VCR series to correct")
            new_wage = _dec(latest["cumulative_wage"]) + d_wage
            new_base = min(new_wage, _dec(latest["cumulative_max"]))
            d_base = new_base - _dec(latest["cumulative_base"])
            vcr_before[family] = latest
            vcr_after[family] = {"period_count": latest["period_count"], "cumulative_wage": str(new_wage),
                                 "cumulative_max": latest["cumulative_max"], "cumulative_base": str(new_base),
                                 "revision": int(latest["revision"]) + 1}
            vcr_increments[family] = str(d_base)
        eff_increments[family] = str(_dec(effective["increments"].get(family)) + d_base)
    if correction_run is not None and vcr_after:
        raise BadRequestException("a batched correction run cannot move the VCR series — create a separate correction")

    # 4. premiums on the effective increment at the corrected period's rates
    ei_base = _dec(eff_increments.get(VcrFamily.EI))
    new_premiums = dict(effective["premiums"])
    new_whk_ee = _dec(effective["whkEe"])
    ei = corrected_result.get("employeeInsurance") or {}
    if ei.get("insured"):
        for code in ("awf", "aof", "wko"):
            new_premiums[code] = str(_amount(ei_base, _trace_rate(corrected_result, code.upper())))
        decision = new_frozen.get("premiumDecision") or {}
        new_premiums["whk"] = str(_amount(ei_base, decision.get("whk_wga_pct")) + _amount(ei_base, decision.get("whk_zw_flex_pct")))
        new_whk_ee = _amount(ei_base, decision.get("whk_wga_employee_recoverable_pct"))
    zvw = corrected_result.get("zvw") or {}
    zvw_family = VcrFamily.ZVW_LEVY if zvw.get("path") == "EMPLOYER_LEVY" else VcrFamily.ZVW_CONTRIB
    zvw_amount = _amount(_dec(eff_increments.get(zvw_family)), zvw.get("rate"))
    new_zvw_er = zvw_amount if zvw.get("path") == "EMPLOYER_LEVY" else Decimal("0.00")
    new_zvw_ee = zvw_amount if zvw.get("path") != "EMPLOYER_LEVY" else Decimal("0.00")

    d = {
        "gross": _dec(corrected["gross"]) - _dec(effective["gross"]),
        "wageTax": _dec(corrected["wageTax"]) - _dec(effective["wageTax"]),
        "pensionEe": _dec(corrected["pensionEe"]) - _dec(effective["pensionEe"]),
        "pensionEr": _dec(corrected["pensionEr"]) - _dec(effective["pensionEr"]),
        "zvwEe": new_zvw_ee - _dec(effective["zvwEe"]), "zvwEr": new_zvw_er - _dec(effective["zvwEr"]),
        "whkEe": new_whk_ee - _dec(effective["whkEe"]),
        **{f"premium_{k}": _dec(new_premiums[k]) - _dec(effective["premiums"].get(k)) for k in new_premiums},
        "vacAccrual": _dec(corrected["vacAccrual"]) - _dec(effective["vacAccrual"]),
        "vacPayout": _dec(corrected["vacPayout"]) - _dec(effective["vacPayout"]),
        "vacBasis": _dec(corrected["vacBasis"]) - _dec(effective["vacBasis"]),
        **{f"wkr_{k}": _dec(corrected["wkr"].get(k)) - _dec(effective["wkr"].get(k))
           for k in ("fiscalWage", "designated", "targetedExemptions")},
    }
    if not any(d.values()) and not vcr_after:
        raise BadRequestException("The corrected inputs produce no change — nothing to correct.")
    employer_premiums = sum((d[f"premium_{k}"] for k in ("awf", "aof", "wko", "whk")), Decimal("0")) + d["zvwEr"]
    employee_deductions = d["wageTax"] + d["pensionEe"] + d["zvwEe"] + d["whkEe"]
    totals = {"gross": str(d["gross"]), "wageTax": str(d["wageTax"]), "pensionEmployee": str(d["pensionEe"]),
              "zvwEmployee": str(d["zvwEe"]), "whkEmployee": str(d["whkEe"]),
              "employeeDeductions": str(employee_deductions), "netPay": str(d["gross"] - employee_deductions),
              "employerPremiums": str(employer_premiums), "pensionEmployer": str(d["pensionEr"]),
              "employerCost": str(employer_premiums + d["pensionEr"])}
    corrected_position = {**corrected, "zvwEe": str(new_zvw_ee), "zvwEr": str(new_zvw_er), "whkEe": str(new_whk_ee),
                          "premiums": new_premiums, "increments": eff_increments}

    # 5. the delta payslip in its correction run
    sequence = len(chain) + 1
    if correction_run is None:
        correction_run = PayrollRun(
            organization_id=organization_id, period_label=f"NL correction {sequence} of {run.period_label}"[:50],
            period_start=run.period_start, period_end=run.period_end, pay_date=run.pay_date,
            notes=f"{NL_CORRECTION_MARKER} original run {run.id}, payslip {item.id} ({method}): {reason.strip()}"[:2000],
            created_by=actor_id, calculation_mode=run.calculation_mode)
        db.add(correction_run)
        db.flush()
    correction = {
        "originalPayslipId": item.id, "originalRunId": run.id, "sequence": sequence, "method": method,
        "reason": reason.strip(), "correctedInputs": json.loads(json.dumps(corrected_inputs or {}, default=str)),
        "originalInputHash": snapshot.get("inputHash"), "newInputHash": corrected_result.get("inputHash"),
        "before": effective, "corrected": corrected_position, "frozen": new_frozen,
        "delta": {k: str(v) for k, v in d.items()}, "actorId": actor_id,
        "at": datetime.utcnow().replace(microsecond=0).isoformat(),
    }
    delta_snapshot = {
        "correction": correction, "periodCode": snapshot.get("periodCode"), "totals": totals,
        "exceptions": corrected_result.get("exceptions") or [], "inputHash": corrected_result.get("inputHash"),
        "trace": corrected_result.get("trace") or [],
        "vcr": {"periodMax": "0", "before": vcr_before, "after": vcr_after, "increments": vcr_increments},
        "vacationAllowance": {"accrual": str(d["vacAccrual"]), "payout": str(d["vacPayout"]),
                              "basis": str(d["vacBasis"]), "pct": corrected["vacPct"]},
        "wkr": {"fiscalWage": str(d["wkr_fiscalWage"]), "designated": str(d["wkr_designated"]),
                "targetedExemptions": str(d["wkr_targetedExemptions"])},
        "inputs": {"slabs": (new_frozen or {}).get("slabs") or []},
    }
    from app.modules.payroll.models import PayslipStatus

    delta_item = PayslipItem(
        payroll_run_id=correction_run.id, employee_id=item.employee_id, organization_id=organization_id,
        employee_name=item.employee_name, country_code=NL, status=PayslipStatus.PENDING,
        compliance_fields=item.compliance_fields, notes=f"NL correction delta of payslip {item.id}",
        nl_calculation_snapshot=delta_snapshot,
        gross_pay=d["gross"], tds=d["wageTax"], employee_pension=d["pensionEe"],
        total_deductions=employee_deductions, net_pay=d["gross"] - employee_deductions,
        employer_social_security=employer_premiums, employer_pension=d["pensionEr"])
    db.add(delta_item)
    db.flush()
    return {"correctionRunId": correction_run.id, "deltaPayslipId": delta_item.id, "sequence": sequence,
            "method": method, "totals": totals, "vcr": delta_snapshot["vcr"]}


# ── AWf retrospective revision (NL-016) ────────────────────────────────────
# Statutory revision situations (Belastingdienst, S6). The thresholds are the
# published S6 rules; they are listed here for gate-G2 review and only DETECT
# — a second person reviews before anything is applied.
AWF_REVISION_TRIGGERS = {
    "SHORT_INDEFINITE_CONTRACT": "indefinite contract ended within two months of its start (S6)",
    "EXCESS_HOURS": "part-time contract (< 35 h/week) paid more than 30% above the agreed hours in the year (S6)",
}
_SHORT_CONTRACT_MONTHS = 2
_EXCESS_HOURS_FACTOR = Decimal("1.30")
_FULL_TIME_WEEKLY_HOURS = Decimal("35")


def _add_months(day: date, months: int) -> date:
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    from calendar import monthrange

    return date(year, month, min(day.day, monthrange(year, month)[1]))


def _committed_nl_items(db: Session, organization_id: int, tax_year: int) -> List[PayslipItem]:
    rows = (db.query(PayslipItem).join(PayrollRun, PayslipItem.payroll_run_id == PayrollRun.id)
            .filter(PayrollRun.organization_id == organization_id, PayslipItem.country_code == NL)
            .order_by(PayslipItem.id).all())
    out = []
    for item in rows:
        run = db.query(PayrollRun).filter(PayrollRun.id == item.payroll_run_id).one()
        if run.pay_date and run.pay_date.year == tax_year and not is_nl_correction_run(run) and run_committed(db, run):
            out.append(item)
    return out


def detect_awf_revisions(db: Session, organization_id: int, tax_year: int, actor_id: Optional[int]) -> list:
    """Record each statutory revision situation for low-rate periods as DETECTED."""
    from app.modules.payroll.models import PayrollNlAwfRevision

    groups: Dict[tuple, list] = {}
    for item in _committed_nl_items(db, organization_id, tax_year):
        snap = item.nl_calculation_snapshot or {}
        position = _position(snap)
        chain = _correction_chain(db, item)
        if chain:
            position = chain[-1].nl_calculation_snapshot["correction"]["corrected"]
        if (snap.get("employeeInsurance") or {}).get("awfClass") != "LOW":
            continue
        contract = (snap.get("inputs") or {}).get("contract") or {}
        if contract.get("awf_revision_trigger"):
            continue
        groups.setdefault((item.employee_id, contract.get("id")), []).append((item, snap, position))
    created = []
    for (employee_id, contract_id), entries in groups.items():
        contract = db.query(PayrollNlContractVersion).filter(PayrollNlContractVersion.id == contract_id).first()
        if contract is None:
            continue
        triggers = []
        if (contract.contract_term == "INDEFINITE" and contract.end_date
                and contract.end_date < _add_months(contract.start_date, _SHORT_CONTRACT_MONTHS)):
            triggers.append("SHORT_INDEFINITE_CONTRACT")
        if contract.agreed_hours_per_week is not None and Decimal(contract.agreed_hours_per_week) < _FULL_TIME_WEEKLY_HOURS:
            paid = sum((_dec((s.get("inputs") or {}).get("periodHours")) for _i, s, _p in entries), Decimal("0"))
            agreed = sum((Decimal(contract.agreed_hours_per_week) * Decimal("52")
                          / Decimal((s.get("inputs") or {}).get("periodsPerYear") or 12) for _i, s, _p in entries),
                         Decimal("0"))
            if agreed and paid > agreed * _EXCESS_HOURS_FACTOR:
                triggers.append("EXCESS_HOURS")
        for trigger in triggers:
            exists = db.query(PayrollNlAwfRevision.id).filter(
                PayrollNlAwfRevision.organization_id == organization_id, PayrollNlAwfRevision.employee_id == employee_id,
                PayrollNlAwfRevision.contract_version_id == contract_id, PayrollNlAwfRevision.tax_year == tax_year,
                PayrollNlAwfRevision.trigger_code == trigger).first()
            if exists:
                continue
            periods, total = [], Decimal("0")
            for item, snap, position in entries:
                rates = (snap.get("inputs") or {}).get("rates") or {}
                high = (rates.get("nl_awf_high_pct") or {}).get("employer")
                increment = _dec((position.get("increments") or {}).get(VcrFamily.EI))
                delta = _amount(increment, high) - _dec((position.get("premiums") or {}).get("awf"))
                total += delta
                periods.append({"payslipId": item.id, "runId": item.payroll_run_id, "eiIncrement": str(increment),
                                "awfLow": (position.get("premiums") or {}).get("awf"), "awfHigh": str(_amount(increment, high)),
                                "delta": str(delta)})
            row = PayrollNlAwfRevision(organization_id=organization_id, employee_id=employee_id,
                                       contract_version_id=contract_id, tax_year=tax_year, trigger_code=trigger,
                                       detected_by=actor_id, affected_periods=periods,
                                       recomputed_delta={"awf": str(total), "reason": AWF_REVISION_TRIGGERS[trigger]},
                                       status="DETECTED")
            db.add(row)
            created.append(row)
    db.flush()
    return created


def _awf_revision(db: Session, revision_id: int, organization_id: int):
    from app.modules.payroll.models import PayrollNlAwfRevision

    row = (db.query(PayrollNlAwfRevision)
           .filter(PayrollNlAwfRevision.id == revision_id, PayrollNlAwfRevision.organization_id == organization_id).first())
    if row is None:
        raise NotFoundException("PayrollNlAwfRevision", revision_id)
    return row


def review_awf_revision(db: Session, revision_id: int, organization_id: int, actor_id: int):
    row = _awf_revision(db, revision_id, organization_id)
    if row.status != "DETECTED":
        raise BadRequestException(f"only a DETECTED revision can be reviewed (status {row.status})")
    if row.detected_by is not None and row.detected_by == actor_id:
        raise BadRequestException("the person who detected the revision cannot review it (four-eyes)")
    row.status = "REVIEWED"
    row.reviewed_by = actor_id
    row.reviewed_at = datetime.utcnow()
    db.flush()
    return row


def dismiss_awf_revision(db: Session, revision_id: int, organization_id: int, actor_id: int, note: str):
    row = _awf_revision(db, revision_id, organization_id)
    if row.status not in ("DETECTED", "REVIEWED"):
        raise BadRequestException(f"a {row.status} revision cannot be dismissed")
    if not (note or "").strip():
        raise BadRequestException("dismissing a statutory revision needs the reason on record")
    row.status = "DISMISSED"
    row.resolution_note = note.strip()
    row.reviewed_by = row.reviewed_by or actor_id
    db.flush()
    return row


def apply_awf_revision(db: Session, revision_id: int, organization_id: int, actor_id: int) -> dict:
    """One correction run re-charging every affected period at the high rate
    (employer premium only — net pay is unchanged, the VCR does not move)."""
    row = _awf_revision(db, revision_id, organization_id)
    if row.status != "REVIEWED":
        raise BadRequestException("a revision must be REVIEWED before it is applied")
    first = db.query(PayslipItem).filter(PayslipItem.id == row.affected_periods[0]["payslipId"]).one()
    original_run = db.query(PayrollRun).filter(PayrollRun.id == first.payroll_run_id).one()
    corr_run = PayrollRun(
        organization_id=organization_id, period_label=f"NL AWf revision {row.tax_year} #{row.id}"[:50],
        period_start=original_run.period_start, period_end=original_run.period_end, pay_date=original_run.pay_date,
        notes=f"{NL_CORRECTION_MARKER} AWf revision {row.id} ({row.trigger_code}) for employee {row.employee_id}"[:2000],
        created_by=actor_id, calculation_mode=original_run.calculation_mode)
    db.add(corr_run)
    db.flush()
    results = [create_nl_correction(db, organization_id, period["payslipId"],
                                    f"AWf revision: {AWF_REVISION_TRIGGERS[row.trigger_code]}",
                                    "REPROCESS_ORIGINAL_PERIOD", {"contract": {"awf_revision_trigger": row.trigger_code}},
                                    actor_id, correction_run=corr_run)
               for period in row.affected_periods]
    row.status = "APPLIED"
    row.correction_run_id = corr_run.id
    db.flush()
    return {"correctionRunId": corr_run.id, "corrections": results}


# ══════════════════════════════════════════════════════════════════════════
# Platform hooks (the 13 every registered jurisdiction provides)
# ══════════════════════════════════════════════════════════════════════════

NL_PROFILE_COLUMNS = tuple(c.name for c in EmployeeStatutoryProfile.__table__.columns if c.name.startswith("nl_"))
_UPPER_COLUMNS = ("nl_table_color", "nl_zvw_path", "nl_cross_border_status", "nl_identity_status", "nl_residence_variant")
_ALLOWED = {
    "nl_table_color": ("WHITE", "GREEN"),
    "nl_zvw_path": ("EMPLOYER_LEVY", "EMPLOYEE_CONTRIB", "EMPLOYEE_CONTRIBUTION", "SPECIAL"),
    "nl_cross_border_status": ("NONE", "SUPPORTED", "BLOCKED"),
}


def _nl_statutory_profile_errors(data) -> list:
    errors = []
    for column, allowed in _ALLOWED.items():
        value = (getattr(data, column, None) or "").strip().upper()
        if value and value not in allowed:
            errors.append(f"{column} must be one of {', '.join(allowed)}.")
    pct = getattr(data, "nl_vacation_allowance_pct", None)
    if pct is not None and pct < 0:
        errors.append("nl_vacation_allowance_pct cannot be negative.")
    extra = getattr(data, "nl_voluntary_extra_withholding", None)
    if extra is not None and extra < 0:
        errors.append("nl_voluntary_extra_withholding can only ADD tax (spec §3).")
    hours = getattr(data, "nl_contract_hours_per_week", None)
    if hours is not None and hours <= 0:
        errors.append("nl_contract_hours_per_week must be positive.")
    return errors


def _nl_profile_values(db: Session, employee, data, previous) -> dict:
    """Each version is a full NL snapshot: fields not sent carry forward."""
    sent = getattr(data, "model_fields_set", set())
    values = {}
    for column in NL_PROFILE_COLUMNS:
        if column in sent:
            value = getattr(data, column)
            if column in _UPPER_COLUMNS:
                value = (value or "").strip().upper() or None
            values[column] = value
        elif previous is not None and (previous.country_code or "").upper() == NL:
            values[column] = getattr(previous, column)
    return values


NL_RETENTION_CATEGORIES = (
    ("PAYROLL_RECORDS", "Payroll runs, payslips and NL calculation snapshots"),
    ("VCR_LEDGERS", "VCR snapshots, WKR accumulators and vacation-allowance ledger"),
    ("EMPLOYEE_DECLARATIONS", "Signed loonheffingskorting instructions (Model opgaaf)"),
    ("CONTRACTS", "Contract versions and AWf evidence"),
    ("PREMIUM_DECISIONS", "Employer premium decisions and Belastingdienst evidence"),
    ("EXPAT_DECISIONS", "30% facility decisions"),
    ("TERMINATIONS", "Termination settlements and transition payments"),
    ("EMPLOYEE_IDENTITY", "BSN and statutory profile data"),
)
DECISIONS = {
    "D-1": ("Retention period per data category (NL-053)", True),
    "D-2": ("Deletion vs anonymisation at end of retention", True),
    "D-3": ("GDPR controller / processor roles and Article 28 terms", True),
    "D-4": ("PKIoverheid certificate custody (NL-030)", True),
}


def _evidence(db: Session, tag: str):
    from app.modules.payroll.models import SourceArtifact

    rows = (db.query(SourceArtifact).filter(SourceArtifact.form_number == tag, SourceArtifact.superseded_by_id.is_(None))
            .order_by(SourceArtifact.id.desc()).all())
    accepted = next((r for r in rows if r.reviewer_id and r.file_path is not None and r.reviewer_id != r.created_by_id), None)
    return accepted, bool(rows)


def owner_decisions(db: Session) -> list:
    out = []
    for key, (label, blocks) in DECISIONS.items():
        accepted, submitted = _evidence(db, f"NL-DECISION-{key}")
        out.append({"key": key, "label": label, "blocksLaunch": blocks, "evidenceTag": f"NL-DECISION-{key}",
                    "state": "RECORDED" if accepted else ("SUBMITTED" if submitted else "OPEN"),
                    "artifactId": accepted.id if accepted else None})
    return out


NL_GATES = (("G1", "Tax tables"), ("G2", "VCR & premiums"), ("G3", "Filing"), ("G4", "CAO / pension"),
            ("G5", "WKR / benefits"), ("G6", "Labor pay"), ("G7", "Security / privacy"), ("G8", "Parallel payroll"))


def gate_states(db: Session) -> list:
    out = []
    for key, label in NL_GATES:
        accepted, submitted = _evidence(db, f"NL-GATE-{key}")
        out.append({"gate": key, "label": label, "state": "SIGNED" if accepted else ("SUBMITTED" if submitted else "OPEN")})
    return out


def _decision_state(db: Session, key: str) -> str:
    return next((d["state"] for d in owner_decisions(db) if d["key"] == key), "OPEN")


def _retained_record_label(db: Session, organization_id: int, employee_id: int) -> Optional[str]:
    for model, label in ((PayrollNlVcrSnapshot, "VCR snapshots"),
                         (PayrollNlVacationAllowanceLedger, "vacation-allowance ledger entries"),
                         (PayrollNlTerminationSettlement, "termination settlements"),
                         (PayrollNlTaxCreditInstruction, "loonheffingskorting instructions"),
                         (PayrollNlContractVersion, "contract versions")):
        if db.query(model.id).filter(model.employee_id == employee_id).first():
            return label
    return None


def _has_statutory_profile(db: Session, employee_id: int) -> bool:
    return db.query(EmployeeStatutoryProfile.id).filter(EmployeeStatutoryProfile.employee_id == employee_id,
                                                        EmployeeStatutoryProfile.country_code == NL).first() is not None


def is_nl_report(report) -> bool:
    return bool(report is not None and (str(getattr(report, "jurisdiction_country", "") or "").upper() == NL
                                        or str(getattr(report, "report_type", "") or "").startswith("NL_")))


def retention_settings() -> "retention_service.RetentionJurisdiction":
    return retention_service.RetentionJurisdiction(
        country=NL, label="Netherlands", categories=NL_RETENTION_CATEGORIES,
        period_decision="D-1", end_decision="D-2", decision_reference="NL-DECISION-D-1",
        decision_state=_decision_state,
        validate_employee=lambda db, employee_id, organization_id: _employee(db, employee_id, organization_id),
        retained_record_label=_retained_record_label, has_statutory_profile=_has_statutory_profile,
        report_matches=is_nl_report, audit_spec=SPEC)


def transition_nl_service_registry(db: Session, target: str, reason: str, actor_id: Optional[int] = None,
                                   as_of: Optional[date] = None):
    """PLANNED <-> AVAILABLE. AVAILABLE is refused until every gate G1–G8 is
    signed (spec §19: approval of the build is not approval of live payroll)."""
    def readiness():
        gates = gate_states(db)
        missing = [g for g in gates if g["state"] != "SIGNED"]
        unmet = [{"key": f"nl_gate_{g['gate'].lower()}", "label": f"Gate {g['gate']} — {g['label']}",
                  "detail": f"gate {g['gate']} is {g['state']}", "met": False} for g in missing]
        return unmet, {u["key"]: u["detail"] for u in unmet}

    return service.transition_service_registry(
        db, NL, target, reason, actor_id, label="Netherlands", readiness=readiness,
        invalid_target_message=lambda t: (
            f"Netherlands availability can only be {service.SERVICE_REGISTRY_OPEN} or {service.SERVICE_REGISTRY_CLOSED}."),
        missing_row_message="There is no Netherlands registry row — seed it (PLANNED); it is never created here.",
        open_from_message=lambda a: f"Netherlands is {a}; only PLANNED moves to AVAILABLE.")


def statutory_summary(db: Session) -> dict:
    return {"jurisdiction": NL, "spec": SPEC, "available": False, "engineVersion": ENGINE_VERSION,
            "gates": gate_states(db), "decisions": owner_decisions(db),
            "note": "Live Dutch payroll stays gated until G1–G8 are signed (ZP-NL-ENG-001 §19)."}


def nl_activation_evidence_refusal(db: Session, pack) -> Optional[str]:
    return None


def statutory_editors(db: Session, pack) -> set:
    return set()


def template_activation_refusal(db: Session, template, actor_id: Optional[int]) -> Optional[str]:
    return None


def _nl_pack_holidays(db: Session, year: int) -> list:
    """Dutch public holidays are not seeded from a reviewed source yet — none
    is invented here."""
    return []


def payment_treatment(db: Session, organization_id: int, run: PayrollRun, items: list) -> dict:
    """No NL payment hold at this phase (bank settlement lifecycle is Phase 10)."""
    return {}


def _nl_payslip_hold_view(item: PayslipItem) -> Optional[dict]:
    return None


JURISDICTION_HOOKS = {
    "retention_settings": "retention_settings",
    "service_registry_transition": "transition_nl_service_registry",
    "statutory_summary": "statutory_summary",
    "pack_activation_refusal": "nl_activation_evidence_refusal",
    "statutory_editors": "statutory_editors",
    "template_activation_refusal": "template_activation_refusal",
    "calc_inputs": "calc_inputs",
    "payment_treatment": "payment_treatment",
    "before_run_transition": "_nl_before_run_transition",
    "pack_holidays": "_nl_pack_holidays",
    "statutory_profile_errors": "_nl_statutory_profile_errors",
    "statutory_profile_values": "_nl_profile_values",
    "payslip_hold_view": "_nl_payslip_hold_view",
}
