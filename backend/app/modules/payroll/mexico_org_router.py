"""
payroll/mexico_org_router.py
----------------------------
Organisation API for Mexico employer onboarding (ZP-MX-ENG-001 Phase 3,
spec §11 panels A–H), mounted inside payroll_router as /api/payroll/mexico
(so the subscription gate applies). Same house rules as
netherlands_org_router.py:

  * Phase 4a dormancy: a router-level guard (require_mexico_tenant) refuses
    every route unless MX_TENANT_ONBOARDING_ENABLED is on AND the caller's
    organisation is Mexican (payroll jurisdiction MX) — off by default and
    in production.
  * The organisation is ALWAYS the caller's own (current_user.organization_id);
    no route takes an organisation id. Super Admin (no organisation) uses the
    read-only Super Admin Employer tab instead.
  * Every child id is checked against that organisation before the service
    acts (the service's _owned / employer_root lookups are org-scoped).
  * Reads need a payroll operator; writes need an org admin.
  * No statutory fact is typed in, and no secret is accepted — credentials
    are gcp-sm:// references; the certificate upload takes the PUBLIC .cer
    only, read from the request stream in memory with a hard 16 KB cap (a
    multipart UploadFile would spool to a temporary file; this never does).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.dependencies import _role_value, get_current_org_admin, get_current_payroll_operator
from app.core.exceptions import BadRequestException, ForbiddenException
from app.database import get_db
from app.modules.payroll.mexico_schemas import (
    MXClose, MXCredentialCreate, MXEmployerCreate, MXEstablishmentCreate, MXInfonavitModel, MXIsnRegistrationCreate,
    MXLaborPolicyCreate, MXRegistrationCreate, MXRiskPremiumCreate,
)

def require_mexico_tenant(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    """Phase 4a dormancy guard on EVERY route here: refused unless Mexico
    onboarding is enabled on this platform AND the caller's organisation is
    Mexican (its payroll jurisdiction resolves to MX). Role checks stay on
    each route (reads: payroll operator; writes: org admin)."""
    from app.modules.payroll import mexico_dormancy, service

    if not mexico_dormancy.onboarding_enabled():
        raise ForbiddenException(mexico_dormancy.DORMANT_MESSAGE)
    org_id = getattr(current_user, "organization_id", None)
    if org_id is None:
        return                                   # each route's _org_id answers Super Admin with its own 403
    if not mexico_dormancy.is_mexico(service._resolve_org_country(db, org_id)):
        raise ForbiddenException("The Mexico API is only available to organisations whose payroll jurisdiction "
                                 "is Mexico.")


router = APIRouter(prefix="/mexico", tags=["Mexico (Organisation)"], dependencies=[Depends(require_mexico_tenant)])

_CERT_CONTENT_TYPES = ("application/octet-stream", "application/pkix-cert", "application/x-x509-ca-cert",
                       "application/x-pem-file")


def _svc():
    from app.modules.payroll import mexico_employer_service

    return mexico_employer_service


def _org_id(user) -> int:
    org_id = getattr(user, "organization_id", None)
    if org_id is None:
        raise ForbiddenException("Mexico employer routes act on your own organisation; "
                                 "Super Admin uses the Super Admin Mexico workspace (Employer tab, read-only).")
    return org_id


def _actor(user) -> Optional[int]:
    return getattr(user, "id", None)


# ── employers (panels A and B) ───────────────────────────────────────────────

@router.get("/employers", summary="Your legal employers (RFC chains) with every version")
def list_employers(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return _svc().list_employers(db, _org_id(current_user))


@router.post("/employers", summary="Record a new legal employer (version 1, org admin)")
def create_employer(body: MXEmployerCreate, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _svc().create_employer(db, _org_id(current_user), body.to_service(), _actor(current_user))


@router.get("/employers/{employer_id}", summary="One legal employer with establishments, registrations and policies")
def employer_detail(employer_id: int, current_user=Depends(get_current_payroll_operator),
                    db: Session = Depends(get_db)):
    return _svc().employer_detail(db, _org_id(current_user), employer_id)


@router.post("/employers/{employer_id}/versions", summary="Record a new employer version from its effective date")
def create_employer_version(employer_id: int, body: MXEmployerCreate, current_user=Depends(get_current_org_admin),
                            db: Session = Depends(get_db)):
    return _svc().create_employer_version(db, _org_id(current_user), employer_id, body.to_service(),
                                          _actor(current_user))


# ── establishments ───────────────────────────────────────────────────────────

@router.post("/employers/{employer_id}/establishments", summary="Add an establishment (zone derived from content)")
def create_establishment(employer_id: int, body: MXEstablishmentCreate, current_user=Depends(get_current_org_admin),
                         db: Session = Depends(get_db)):
    return _svc().create_establishment(db, _org_id(current_user), employer_id, body.to_service(), _actor(current_user))


@router.put("/establishments/{establishment_id}/deactivate", summary="Deactivate an establishment")
def deactivate_establishment(establishment_id: int, current_user=Depends(get_current_org_admin),
                             db: Session = Depends(get_db)):
    return _svc().deactivate_establishment(db, _org_id(current_user), establishment_id, _actor(current_user))


# ── IMSS registrations, INFONAVIT model, risk premiums (panels C and D) ──────

@router.post("/employers/{employer_id}/imss-registrations", summary="Add an IMSS employer registration")
def create_registration(employer_id: int, body: MXRegistrationCreate, current_user=Depends(get_current_org_admin),
                        db: Session = Depends(get_db)):
    return _svc().create_registration(db, _org_id(current_user), employer_id, body.to_service(), _actor(current_user))


@router.put("/imss-registrations/{registration_id}/infonavit", summary="Set the INFONAVIT operating model")
def set_infonavit_model(registration_id: int, body: MXInfonavitModel, current_user=Depends(get_current_org_admin),
                        db: Session = Depends(get_db)):
    return _svc().set_infonavit_model(db, _org_id(current_user), registration_id, body.infonavitOperatingModel,
                                      _actor(current_user))


@router.put("/imss-registrations/{registration_id}/close", summary="Close an IMSS registration")
def close_registration(registration_id: int, body: MXClose, current_user=Depends(get_current_org_admin),
                       db: Session = Depends(get_db)):
    return _svc().close_registration(db, _org_id(current_user), registration_id, body.effectiveTo,
                                     _actor(current_user))


@router.post("/imss-registrations/{registration_id}/risk-premiums",
             summary="Record a work-risk premium (DRAFT — a second org admin approves)")
def create_risk_premium(registration_id: int, body: MXRiskPremiumCreate, current_user=Depends(get_current_org_admin),
                        db: Session = Depends(get_db)):
    return _svc().create_risk_premium(db, _org_id(current_user), registration_id, body.to_service(),
                                      _actor(current_user))


@router.put("/risk-premiums/{premium_id}/approve", summary="Approve a DRAFT premium (a different org admin)")
def approve_risk_premium(premium_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _svc().approve_risk_premium(db, _org_id(current_user), premium_id, _actor(current_user),
                                       _role_value(current_user))


# ── state ISN (panel E) ──────────────────────────────────────────────────────

@router.post("/employers/{employer_id}/isn-registrations", summary="Register for state payroll tax (in-scope states)")
def create_isn_registration(employer_id: int, body: MXIsnRegistrationCreate,
                            current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _svc().create_isn_registration(db, _org_id(current_user), employer_id, body.to_service(),
                                          _actor(current_user))


@router.put("/isn-registrations/{isn_id}/close", summary="Close a state ISN registration")
def close_isn_registration(isn_id: int, body: MXClose, current_user=Depends(get_current_org_admin),
                           db: Session = Depends(get_db)):
    return _svc().close_isn_registration(db, _org_id(current_user), isn_id, body.effectiveTo, _actor(current_user))


# ── labour policy (panels F and G) ───────────────────────────────────────────

@router.post("/employers/{employer_id}/labor-policies", summary="Record a labour policy version (floor-checked, DRAFT)")
def create_labor_policy(employer_id: int, body: MXLaborPolicyCreate, current_user=Depends(get_current_org_admin),
                        db: Session = Depends(get_db)):
    return _svc().create_labor_policy(db, _org_id(current_user), employer_id, body.to_service(), _actor(current_user))


@router.put("/labor-policies/{policy_id}/activate", summary="Activate a DRAFT policy (floor check must PASS)")
def activate_labor_policy(policy_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _svc().activate_labor_policy(db, _org_id(current_user), policy_id, _actor(current_user))


@router.get("/labor-policies/{policy_id}/floor-check", summary="Statutory floor check on an explicit date (read-only)")
def floor_check(policy_id: int, on: date = Query(...), current_user=Depends(get_current_payroll_operator),
                db: Session = Depends(get_db)):
    return _svc().floor_check_view(db, _org_id(current_user), policy_id, on)


@router.get("/collective-agreements", summary="Mexico collective agreements you may link (read-only)")
def list_collective_agreements(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return _svc().list_collective_agreements(db, _org_id(current_user))


# ── credential references (MX-035) ───────────────────────────────────────────

@router.post("/employers/{employer_id}/credentials",
             summary="Record a gcp-sm:// credential reference (never the secret); rotates the ACTIVE one")
def create_credential(employer_id: int, payload: Dict[str, Any] = Body(...),
                      current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    # Validated here, not as a FastAPI body model: the default 422 echoes the
    # offending input back, and on this route that input may be a pasted
    # secret. Only field names and error types are returned.
    from pydantic import ValidationError

    try:
        body = MXCredentialCreate(**payload)
    except ValidationError as exc:
        fields = sorted({f"{'.'.join(str(p) for p in e['loc'])}: {e['type']}" for e in exc.errors()})
        raise BadRequestException("invalid credential reference request — " + "; ".join(fields))
    return _svc().create_credential(db, _org_id(current_user), employer_id, body.to_service(), _actor(current_user))


@router.put("/credentials/{credential_id}/revoke", summary="Revoke a credential reference")
def revoke_credential(credential_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _svc().revoke_credential(db, _org_id(current_user), credential_id, _actor(current_user))


@router.post("/credentials/{credential_id}/certificate",
             summary="Attach the PUBLIC certificate (.cer, DER or PEM, ≤16 KB) — raw body, processed in memory")
async def attach_certificate(credential_id: int, request: Request, current_user=Depends(get_current_org_admin),
                             db: Session = Depends(get_db)):
    svc = _svc()
    org_id = _org_id(current_user)
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if content_type not in _CERT_CONTENT_TYPES:
        raise BadRequestException("send the .cer file as the raw request body (application/octet-stream)")
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > svc.MAX_CERTIFICATE_BYTES:
        raise BadRequestException(f"the certificate file is larger than {svc.MAX_CERTIFICATE_BYTES // 1024} KB")
    buf = bytearray()
    async for chunk in request.stream():
        buf.extend(chunk)
        if len(buf) > svc.MAX_CERTIFICATE_BYTES:
            raise BadRequestException(f"the certificate file is larger than {svc.MAX_CERTIFICATE_BYTES // 1024} KB")
    try:
        return svc.attach_certificate(db, org_id, credential_id, bytes(buf), _actor(current_user))
    finally:
        buf[:] = b"\x00" * len(buf)          # nothing of the upload outlives the request


# ── readiness (panel H) ──────────────────────────────────────────────────────

@router.get("/readiness", summary="Employer readiness (panel H) for an explicit date, plus the G1–G8 gates")
def readiness(on: date = Query(..., description="The date to assess — required, never the server date"),
              current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return _svc().organisation_readiness(db, _org_id(current_user), on)
