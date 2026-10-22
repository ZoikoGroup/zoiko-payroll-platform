"""
modules/payroll/tenant_statutory_router.py
------------------------------------------
Tenant-run employer statutory configuration and filings (ZP-PRIV decision 3).

These operations used to be Super Admin endpoints that took an
``organizationId`` query parameter and read or wrote one tenant's employer
data: France employer identity / effectif / SIRET establishments / AT-MP rate
packs / go-live, Germany accident-insurance profiles, Saudi GOSI employer
registrations and liability payment, Netherlands employer premium
decisions, US employer tax profiles (SUI), employer collective-agreement
assignments and statutory filing records.

A platform principal holds no tenant permission (ZP-PRIV A05), so they now
live here. The organization is ALWAYS the authenticated user's own — never a
URL, body or query value — and every object addressed by id is checked to
belong to it (404 otherwise, the same body as "does not exist"). The service
functions are unchanged; their maker-checker rules still apply between two
different tenant users. Super Admin keeps the platform catalog (agreement
definitions, statutory packs) and readiness status only.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_payroll_operator, get_current_user, get_organization_id
from app.core.exceptions import BadRequestException, NotFoundException
from app.database import get_db
from app.modules.payroll.schemas import (
    CollectiveAgreementResponse,
    CollectiveAgreementStatusUpdate,
    CollectiveAgreementUpsert,
    EmployerFranceProfileResponse,
    EmployerFranceProfileUpsert,
    EmployerTaxProfileResponse,
    EmployerTaxProfileUpsert,
    FranceEffectifCorrection,
    FranceEffectifRecord,
    FranceEstablishmentRatePackResponse,
    FranceEstablishmentRatePackUpdate,
    FranceEstablishmentRatePackUpsert,
    FranceEstablishmentResponse,
    FranceEstablishmentUpsert,
    FranceGoLiveRequest,
    FranceRatePackClose,
    GermanyAccidentInsuranceProfileCreate,
    GermanyAccidentInsuranceProfileResponse,
    SaEmployerProfileCreateRequest,
    SaEmployerProfileResponse,
    SaGosiLiabilityPaidRequest,
    SaGosiLiabilityResponse,
    StatutoryFilingResponse,
    StatutoryFilingUpsert,
)

router = APIRouter(tags=["Payroll — Employer statutory configuration (tenant-run)"])


def _own(row, organization_id: int, resource: str):
    """The object must exist AND belong to the caller's organization; both
    failures are the same 404 so another tenant's ids reveal nothing."""
    if row is None or getattr(row, "organization_id", None) != organization_id:
        raise NotFoundException(resource)
    return row


def _france_org(organization_id: int = Depends(get_organization_id), db: Session = Depends(get_db)) -> int:
    from app.modules.payroll import service as payroll_service

    payroll_service.require_france_organization(db, organization_id)
    return organization_id


# ── France employer identity, effectif, establishments, rate packs ─────────

@router.get("/france/employer-profile", response_model=EmployerFranceProfileResponse,
            response_model_by_alias=True, summary="Your France employer profile")
def get_france_employer_profile(organization_id: int = Depends(_france_org), db: Session = Depends(get_db)):
    from app.modules.payroll import service as payroll_service

    return payroll_service.get_employer_france_profile(db, organization_id)


@router.put("/france/employer-profile", response_model=EmployerFranceProfileResponse,
            response_model_by_alias=True, summary="Create or update your France employer profile")
def upsert_france_employer_profile(
    payload: EmployerFranceProfileUpsert = Body(...),
    organization_id: int = Depends(_france_org),
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.upsert_employer_france_profile(db, organization_id, payload, actor_id=current_user.id)


@router.post("/france/effectif", response_model=EmployerFranceProfileResponse,
             response_model_by_alias=True, summary="Record your governed annual France effectif")
def record_france_effectif(
    payload: FranceEffectifRecord = Body(...),
    organization_id: int = Depends(_france_org),
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.record_france_effectif(db, organization_id, payload, actor_id=current_user.id)


@router.post("/france/effectif/corrections", response_model=EmployerFranceProfileResponse,
             response_model_by_alias=True, summary="Correct a recorded France effectif year")
def correct_france_effectif(
    payload: FranceEffectifCorrection = Body(...),
    organization_id: int = Depends(_france_org),
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.correct_france_effectif(db, organization_id, payload, actor_id=current_user.id)


@router.get("/france/establishments", response_model=List[FranceEstablishmentResponse],
            response_model_by_alias=True, summary="Your France establishments (SIRET registry)")
def list_france_establishments(organization_id: int = Depends(_france_org), db: Session = Depends(get_db)):
    from app.modules.payroll import service as payroll_service

    return payroll_service.list_france_establishments(db, organization_id)


@router.post("/france/establishments", response_model=FranceEstablishmentResponse,
             response_model_by_alias=True, summary="Register a France establishment (SIRET)")
def create_france_establishment(
    payload: FranceEstablishmentUpsert = Body(...),
    organization_id: int = Depends(_france_org),
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.upsert_france_establishment(db, organization_id, payload, actor_id=current_user.id)


@router.put("/france/establishments/{establishment_id}", response_model=FranceEstablishmentResponse,
            response_model_by_alias=True, summary="Update or deactivate a France establishment")
def update_france_establishment(
    establishment_id: int,
    payload: FranceEstablishmentUpsert = Body(...),
    organization_id: int = Depends(_france_org),
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.upsert_france_establishment(
        db, organization_id, payload, establishment_id=establishment_id, actor_id=current_user.id)


@router.get("/france/establishment-rate-packs", response_model=List[FranceEstablishmentRatePackResponse],
            response_model_by_alias=True, summary="Your France establishment AT/MP rate packs")
def list_france_establishment_rate_packs(
    siret: Optional[str] = Query(None),
    organization_id: int = Depends(_france_org),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.list_france_establishment_rate_packs(db, organization_id, siret=siret)


@router.put("/france/establishment-rate-packs", response_model=FranceEstablishmentRatePackResponse,
            response_model_by_alias=True, summary="Append a France establishment rate-pack period")
def upsert_france_establishment_rate_pack(
    payload: FranceEstablishmentRatePackUpsert = Body(...),
    organization_id: int = Depends(_france_org),
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.upsert_france_establishment_rate_pack(db, organization_id, payload, actor_id=current_user.id)


@router.patch("/france/establishment-rate-packs/{pack_id}", response_model=FranceEstablishmentRatePackResponse,
              response_model_by_alias=True, summary="Edit a France rate-pack period that has not started")
def update_france_establishment_rate_pack(
    pack_id: int,
    payload: FranceEstablishmentRatePackUpdate = Body(...),
    organization_id: int = Depends(_france_org),
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.update_france_establishment_rate_pack(
        db, organization_id, pack_id, payload, actor_id=current_user.id)


@router.post("/france/establishment-rate-packs/{pack_id}/close", response_model=FranceEstablishmentRatePackResponse,
             response_model_by_alias=True, summary="Close an open France rate-pack period")
def close_france_establishment_rate_pack(
    pack_id: int,
    payload: FranceRatePackClose = Body(...),
    organization_id: int = Depends(_france_org),
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.close_france_establishment_rate_pack(
        db, organization_id, pack_id, payload, actor_id=current_user.id)


@router.get("/france/readiness", summary="Your France go-live readiness checks")
def get_france_readiness(
    for_period: Optional[date] = Query(None),
    organization_id: int = Depends(_france_org),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.get_france_readiness(db, organization_id, for_period=for_period)


@router.post("/france/go-live", summary="Mark your France payroll LIVE (only when every readiness check passes)")
def set_france_live(
    payload: FranceGoLiveRequest = Body(default_factory=FranceGoLiveRequest),
    organization_id: int = Depends(_france_org),
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.set_france_live(db, organization_id, payload, actor_id=current_user.id)


# ── Germany accident-insurance profiles (employer/carrier specific) ────────

def _germany_profile(db: Session, record_id: int, organization_id: int):
    from app.modules.payroll.models import GermanyAccidentInsuranceProfile

    row = db.query(GermanyAccidentInsuranceProfile).filter(GermanyAccidentInsuranceProfile.id == record_id).first()
    return _own(row, organization_id, "Accident insurance profile")


@router.get("/germany/accident-insurance-profiles", response_model=List[GermanyAccidentInsuranceProfileResponse],
            response_model_by_alias=True, summary="Your Germany accident-insurance profiles")
def list_germany_accident_insurance_profiles(
    organization_id: int = Depends(get_organization_id), db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.list_germany_accident_insurance_profiles(db, organization_id=organization_id)


@router.get("/germany/accident-insurance-profiles/{id}", response_model=GermanyAccidentInsuranceProfileResponse,
            response_model_by_alias=True, summary="One of your Germany accident-insurance profiles")
def get_germany_accident_insurance_profile(
    id: int, organization_id: int = Depends(get_organization_id), db: Session = Depends(get_db),
):
    return _germany_profile(db, id, organization_id)


@router.post("/germany/accident-insurance-profiles", response_model=GermanyAccidentInsuranceProfileResponse,
             response_model_by_alias=True, status_code=status.HTTP_201_CREATED,
             summary="Record a new DRAFT accident-insurance profile version")
def create_germany_accident_insurance_profile(
    payload: GermanyAccidentInsuranceProfileCreate,
    organization_id: int = Depends(get_organization_id),
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    payload = payload.model_copy(update={"organization_id": organization_id})
    return payroll_service.create_germany_accident_insurance_profile_record(db, payload, actor_id=current_user.id)


@router.put("/germany/accident-insurance-profiles/{id}/approve", response_model=GermanyAccidentInsuranceProfileResponse,
            response_model_by_alias=True, summary="Approve an accident-insurance profile (a second user)")
def approve_germany_accident_insurance_profile(
    id: int,
    organization_id: int = Depends(get_organization_id),
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    _germany_profile(db, id, organization_id)
    return payroll_service.set_germany_accident_insurance_profile_approver(db, id, actor_id=current_user.id)


@router.put("/germany/accident-insurance-profiles/{id}/status", response_model=GermanyAccidentInsuranceProfileResponse,
            response_model_by_alias=True, summary="Advance an accident-insurance profile's lifecycle status")
def set_germany_accident_insurance_profile_status(
    id: int,
    status_value: str = Query(..., alias="status"),
    organization_id: int = Depends(get_organization_id),
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    _germany_profile(db, id, organization_id)
    return payroll_service.set_germany_accident_insurance_profile_status(db, id, status_value, actor_id=current_user.id)


# ── Saudi Arabia employer GOSI registration + liability payment ────────────

@router.get("/saudi-arabia/employer-profiles", response_model=list[SaEmployerProfileResponse],
            response_model_by_alias=True, summary="Your effective-dated GOSI employer registrations")
def list_sa_employer_profiles(organization_id: int = Depends(get_organization_id), db: Session = Depends(get_db)):
    from app.modules.payroll import saudi_arabia_service

    return saudi_arabia_service.list_sa_employer_profiles(db, organization_id)


@router.post("/saudi-arabia/employer-profiles", response_model=SaEmployerProfileResponse,
             response_model_by_alias=True, summary="Record a new GOSI employer registration version")
def create_sa_employer_profile(
    data: SaEmployerProfileCreateRequest,
    organization_id: int = Depends(get_organization_id),
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import saudi_arabia_service

    return saudi_arabia_service.create_sa_employer_profile(db, organization_id, data, current_user.id)


@router.post("/saudi-arabia/employer-profiles/{profile_id}/approve", response_model=SaEmployerProfileResponse,
             response_model_by_alias=True, summary="Approve a DRAFT GOSI employer profile")
def approve_sa_employer_profile(
    profile_id: int,
    organization_id: int = Depends(get_organization_id),
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import saudi_arabia_service

    return saudi_arabia_service.approve_sa_employer_profile(db, organization_id, profile_id, current_user.id)


@router.post("/saudi-arabia/gosi-liabilities/{liability_id}/paid", response_model=SaGosiLiabilityResponse,
             response_model_by_alias=True, summary="Mark one of your DRAFT GOSI liabilities paid")
def mark_sa_gosi_liability_paid(
    liability_id: int,
    data: SaGosiLiabilityPaidRequest,
    organization_id: int = Depends(get_organization_id),
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import saudi_arabia_service

    return saudi_arabia_service.mark_sa_gosi_liability_paid(
        db, organization_id, liability_id, data.paymentReference, current_user.id)


# ── Netherlands employer premium decisions (Aof / Whk) ─────────────────────

def _premium_row(row) -> Dict[str, Any]:
    # Same serialisation as the (retired) Super Admin NL endpoint.
    from app.modules.payroll.netherlands_router import _PREMIUM_FIELDS, _row

    return _row(row, _PREMIUM_FIELDS)


def _opt_dec(value) -> Optional[Decimal]:
    return None if value in (None, "") else Decimal(str(value))


@router.get("/netherlands/premium-decisions", summary="Your employer premium decisions")
def list_nl_premium_decisions(organization_id: int = Depends(get_organization_id), db: Session = Depends(get_db)):
    from app.modules.payroll.models import PayrollNlEmployerPremiumDecision as M

    rows = (db.query(M).filter(M.organization_id == organization_id)
            .order_by(M.tax_year.desc(), M.effective_from.desc()).all())
    return [_premium_row(r) for r in rows]


@router.post("/netherlands/premium-decisions", summary="Record a DRAFT premium decision with its evidence")
def create_nl_premium_decision(
    payload: Dict[str, Any] = Body(...),
    organization_id: int = Depends(get_organization_id),
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import netherlands_service as nl

    try:
        row = nl.create_premium_decision(
            db, organization_id=organization_id, tax_year=int(payload["tax_year"]),
            aof_size_class=payload["aof_size_class"], aof_basis_year=int(payload["aof_basis_year"]),
            aof_basis_premium_wage=Decimal(str(payload["aof_basis_premium_wage"])),
            decision_reference=payload["decision_reference"],
            decision_date=date.fromisoformat(payload["decision_date"]),
            effective_from=date.fromisoformat(payload["effective_from"]), actor_id=current_user.id,
            whk_wga_pct=_opt_dec(payload.get("whk_wga_pct")),
            whk_zw_flex_pct=_opt_dec(payload.get("whk_zw_flex_pct")),
            whk_wga_employee_recoverable_pct=_opt_dec(payload.get("whk_wga_employee_recoverable_pct")),
            sector_code=payload.get("sector_code") or None,
            evidence_artifact_id=payload.get("evidence_artifact_id"))
    except (KeyError, ValueError) as exc:
        raise BadRequestException(f"invalid premium decision: {exc}")
    db.commit()
    db.refresh(row)
    return _premium_row(row)


@router.put("/netherlands/premium-decisions/{decision_id}/activate",
            summary="Activate a premium decision (four-eyes; supersedes the active one)")
def activate_nl_premium_decision(
    decision_id: int,
    organization_id: int = Depends(get_organization_id),
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import netherlands_service as nl

    row = nl.activate_premium_decision(db, decision_id, organization_id, actor_id=current_user.id)
    db.commit()
    db.refresh(row)
    return _premium_row(row)


# ── US employer tax profiles (SUI and similar) ──────────────────────────────

@router.get("/compliance/employer-tax-profiles", response_model=List[EmployerTaxProfileResponse],
            response_model_by_alias=True, summary="Your employer-specific tax profiles (SUI and similar)")
def list_employer_tax_profiles(
    jurisdictionId: Optional[str] = Query(None),
    organization_id: int = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.list_employer_tax_profiles(db, organization_id=organization_id,
                                                      jurisdiction_id=jurisdictionId)


@router.put("/compliance/employer-tax-profiles", response_model=EmployerTaxProfileResponse,
            response_model_by_alias=True, summary="Create or update one of your employer tax profiles")
def upsert_employer_tax_profile(
    payload: EmployerTaxProfileUpsert,
    organization_id: int = Depends(get_organization_id),
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service
    from app.modules.payroll.models import EmployerTaxProfile

    if getattr(payload, "id", None):
        _own(db.query(EmployerTaxProfile).filter(EmployerTaxProfile.id == payload.id).first(),
             organization_id, "Employer tax profile")
    payload = payload.model_copy(update={"organizationId": organization_id})
    return payroll_service.upsert_employer_tax_profile(db, payload, actor_id=current_user.id)


@router.delete("/compliance/employer-tax-profiles/{id}", summary="Delete one of your employer tax profiles")
def delete_employer_tax_profile(
    id: int,
    organization_id: int = Depends(get_organization_id),
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service
    from app.modules.payroll.models import EmployerTaxProfile

    _own(db.query(EmployerTaxProfile).filter(EmployerTaxProfile.id == id).first(),
         organization_id, "Employer tax profile")
    payroll_service.delete_employer_tax_profile(db, id, actor_id=current_user.id)
    return {"message": "Employer tax profile deleted."}


# ── Employer collective-agreement assignments ───────────────────────────────

@router.get("/compliance/collective-agreements", response_model=List[CollectiveAgreementResponse],
            response_model_by_alias=True,
            summary="Collective-agreement definitions plus your organization's own assignments")
def list_collective_agreements(
    country: str = Query("SE"),
    organization_id: int = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.list_collective_agreements(db, country, organization_id)


@router.post("/compliance/collective-agreements", response_model=CollectiveAgreementResponse,
             response_model_by_alias=True, summary="Create or edit your Draft collective-agreement assignment")
def upsert_collective_agreement(
    data: CollectiveAgreementUpsert,
    organization_id: int = Depends(get_organization_id),
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service
    from app.modules.payroll.models import CollectiveAgreement

    if data.id:
        _own(db.query(CollectiveAgreement).filter(CollectiveAgreement.id == data.id).first(),
             organization_id, "Collective agreement")
    data = data.model_copy(update={"organizationId": organization_id})
    return payroll_service.upsert_collective_agreement(db, data, actor_id=current_user.id)


@router.post("/compliance/collective-agreements/{agreement_id}/status", response_model=CollectiveAgreementResponse,
             response_model_by_alias=True, summary="Move your collective-agreement assignment through its lifecycle")
def set_collective_agreement_status(
    agreement_id: int,
    data: CollectiveAgreementStatusUpdate,
    organization_id: int = Depends(get_organization_id),
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service
    from app.modules.payroll.models import CollectiveAgreement

    _own(db.query(CollectiveAgreement).filter(CollectiveAgreement.id == agreement_id).first(),
         organization_id, "Collective agreement")
    return payroll_service.set_collective_agreement_status(
        db, agreement_id, data.status, actor_id=current_user.id, reason=data.reason)


# ── Statutory filing records (Filings & Remittances) ────────────────────────

@router.get("/filings/records", response_model=List[StatutoryFilingResponse], response_model_by_alias=True,
            summary="Your statutory filing records, most recently updated first")
def list_statutory_filing_records(organization_id: int = Depends(get_organization_id), db: Session = Depends(get_db)):
    from app.modules.payroll import service as payroll_service

    return payroll_service.list_statutory_filings(db, organization_id)


@router.put("/filings/records", response_model=StatutoryFilingResponse, response_model_by_alias=True,
            summary="Record or update one of your statutory filing statuses")
def upsert_statutory_filing_record(
    payload: StatutoryFilingUpsert,
    organization_id: int = Depends(get_organization_id),
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.upsert_statutory_filing(db, organization_id, payload, actor_id=current_user.id)


@router.delete("/filings/records/{filing_id}", summary="Delete one of your statutory filing records")
def delete_statutory_filing_record(
    filing_id: int,
    organization_id: int = Depends(get_organization_id),
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    payroll_service.delete_statutory_filing(db, filing_id, actor_id=current_user.id,
                                            organization_id=organization_id)
    return {"success": True, "message": "Filing record deleted."}


# ── Netherlands: the organization's own earning-classification overrides and
# pension schemes (the platform catalog stays with Super Admin) ─────────────

@router.get("/netherlands/earning-classifications",
            summary="Earning classifications: platform catalog + your organization's overrides")
def list_nl_earning_classifications(organization_id: int = Depends(get_organization_id),
                                    db: Session = Depends(get_db)):
    from sqlalchemy import or_

    from app.modules.payroll.models import PayrollNlEarningClassification as M
    from app.modules.payroll.netherlands_router import _CLASS_FIELDS, _row

    q = db.query(M).filter(or_(M.organization_id.is_(None), M.organization_id == organization_id))
    return [_row(r, _CLASS_FIELDS) for r in q.order_by(M.earning_code, M.effective_from.desc()).all()]


@router.post("/netherlands/earning-classifications",
             summary="Record your organization's override of an earning classification")
def create_nl_earning_classification(
    payload: Dict[str, Any] = Body(...),
    organization_id: int = Depends(get_organization_id),
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import netherlands_service as nl
    from app.modules.payroll.netherlands_router import _CLASS_FIELDS, _row

    try:
        row = nl.create_earning_classification(
            db, organization_id=organization_id, earning_code=payload["earning_code"].strip(),
            effective_from=date.fromisoformat(payload["effective_from"]),
            remuneration_type=payload["remuneration_type"], wage_tax=bool(payload["wage_tax"]),
            employee_insurance_wage=bool(payload["employee_insurance_wage"]), zvw_wage=bool(payload["zvw_wage"]),
            pensionable=bool(payload["pensionable"]), wkr_treatment=payload["wkr_treatment"],
            vacation_allowance_basis=bool(payload["vacation_allowance_basis"]),
            minimum_wage_reckonable=bool(payload["minimum_wage_reckonable"]),
            evidence_policy=payload.get("evidence_policy") or "NONE")
    except (KeyError, ValueError, AttributeError) as exc:
        raise BadRequestException(f"invalid earning classification: {exc}")
    db.commit()
    db.refresh(row)
    return _row(row, _CLASS_FIELDS)


@router.post("/netherlands/pension-schemes", summary="Record your organization's own pension scheme")
def create_nl_pension_scheme(
    payload: Dict[str, Any] = Body(...),
    organization_id: int = Depends(get_organization_id),
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import netherlands_service as nl
    from app.modules.payroll.netherlands_router import _PENSION_FIELDS, _row

    try:
        row = nl.create_pension_scheme(
            db, organization_id=organization_id, fund_name=payload["fund_name"],
            scheme_code=payload["scheme_code"], effective_from=date.fromisoformat(payload["effective_from"]),
            basis_rule=payload["basis_rule"], employee_pct=Decimal(str(payload["employee_pct"])),
            employer_pct=Decimal(str(payload["employer_pct"])),
            franchise_amount=Decimal(str(payload.get("franchise_amount") or "0")),
            max_pensionable_salary=_opt_dec(payload.get("max_pensionable_salary")),
            mandatory_sector=bool(payload.get("mandatory_sector")),
            collective_agreement_id=payload.get("collective_agreement_id") or None,
            evidence_artifact_id=payload.get("evidence_artifact_id") or None)
    except (KeyError, ValueError) as exc:
        raise BadRequestException(f"invalid pension scheme: {exc}")
    db.commit()
    db.refresh(row)
    return _row(row, _PENSION_FIELDS)


# ── Netherlands 30% facility (expat) decisions - per employee, tenant-run ──

@router.get("/netherlands/expat-decisions", summary="Your 30% facility decisions")
def list_nl_expat_decisions(organization_id: int = Depends(get_organization_id),
                            current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    from app.core.authz.principal import principal_from_user
    from app.core.authz.scopes import tenant_scoped
    from app.modules.payroll.models import PayrollEmployee, PayrollNlExpatDecision as M
    from app.modules.payroll.netherlands_router import _EXPAT_FIELDS, _row

    names = {e.id: e.name for e in tenant_scoped(db, PayrollEmployee, principal_from_user(current_user))}
    return [{**_row(r, _EXPAT_FIELDS), "employee_name": names.get(r.employee_id)}
            for r in db.query(M).filter(M.organization_id == organization_id).order_by(M.granted_from.desc()).all()]


@router.post("/netherlands/expat-decisions", summary="Record a decision (PENDING until verified against the document)")
def create_nl_expat_decision(
    payload: Dict[str, Any] = Body(...),
    organization_id: int = Depends(get_organization_id),
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import netherlands_service as nl
    from app.modules.payroll.netherlands_router import _EXPAT_FIELDS, _row

    try:
        row = nl.record_expat_decision(
            db, organization_id=organization_id, employee_id=int(payload["employee_id"]),
            decision_reference=payload["decision_reference"],
            decision_date=date.fromisoformat(payload["decision_date"]),
            granted_from=date.fromisoformat(payload["granted_from"]),
            granted_to=date.fromisoformat(payload["granted_to"]) if payload.get("granted_to") else None,
            method=payload["method"], threshold_category=payload["threshold_category"],
            allowance_pct=Decimal(str(payload["allowance_pct"])), actor_id=current_user.id,
            evidence_artifact_id=payload.get("evidence_artifact_id") or None)
    except (KeyError, ValueError) as exc:
        raise BadRequestException(f"invalid expat decision: {exc}")
    db.commit()
    db.refresh(row)
    return _row(row, _EXPAT_FIELDS)


@router.put("/netherlands/expat-decisions/{decision_id}/{action}", summary="verify / revoke a decision")
def transition_nl_expat_decision(
    decision_id: int,
    action: str,
    organization_id: int = Depends(get_organization_id),
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import netherlands_service as nl
    from app.modules.payroll.netherlands_router import _EXPAT_FIELDS, _row

    if action == "verify":
        row = nl.verify_expat_decision(db, decision_id, organization_id, actor_id=current_user.id)
    elif action == "revoke":
        row = nl.revoke_expat_decision(db, decision_id, organization_id, actor_id=current_user.id)
    else:
        raise BadRequestException("action must be verify or revoke")
    db.commit()
    db.refresh(row)
    return _row(row, _EXPAT_FIELDS)


# ── Switzerland: read-only calculation preview for one of YOUR employees ───

@router.post("/switzerland/calculation-preview",
             summary="Read-only: production resolver + Swiss engine for one of your employees (writes nothing)")
def preview_ch_calculation_for_tenant(
    payload: Dict[str, Any] = Body(...),
    organization_id: int = Depends(get_organization_id),
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import switzerland_service
    from app.modules.payroll.switzerland_schemas import ChCalculationPreviewRequest

    # The organization is always the caller's own; the employee must be one
    # of its workers (the data-layer scope makes any other id invisible).
    data = ChCalculationPreviewRequest(**{**payload, "organizationId": organization_id})
    return switzerland_service.preview_ch_calculation(db, data)
