"""
payroll/brazil_org_router.py
----------------------------
Organisation API for Brazil employer onboarding (ZP-BR-ENG-001 Phase 3),
mounted inside payroll_router as /api/payroll/brazil (so the subscription gate
applies). Same house rules as netherlands_org_router.py / mexico_org_router.py:

  * Dormancy: a router-level guard (require_brazil_tenant) refuses every route
    unless BR_TENANT_ONBOARDING_ENABLED is on AND the caller's organisation is
    Brazilian (payroll jurisdiction BR) — off by default and in production.
  * The organisation is ALWAYS the caller's own (current_user.organization_id);
    no route takes an organisation id. Super Admin (no organisation) uses the
    read-only Super Admin Employer tab instead.
  * Every child id is checked against that organisation before the service
    acts (the service's _owned / employer_root lookups are org-scoped).
  * Reads need a payroll operator; writes need an org admin.
  * No secret is accepted — credentials are gcp-sm:// references; the
    certificate upload takes the PUBLIC .cer only, read from the request
    stream in memory with a hard 16 KB cap, and zeroed afterwards.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_org_admin, get_current_payroll_operator
from app.core.exceptions import BadRequestException, ForbiddenException
from app.database import get_db
from app.modules.payroll.brazil_schemas import (
    BRAlimonyOrderClose, BRAlimonyOrderCreate, BRConcurrentInssDeclarationCreate, BRCprbOptionCreate,
    BRCredentialCreate, BRDeactivate, BREmployerCreate, BREstablishmentCreate, BRRiskAssignmentCreate,
    BRValeTransporteElectionCreate,
)
from app.modules.payroll import brazil_service as br


def require_brazil_tenant(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    """Dormancy guard on EVERY route here: refused unless Brazil onboarding is
    enabled on this platform AND the caller's organisation is Brazilian (its
    payroll jurisdiction resolves to BR). Role checks stay on each route."""
    from app.modules.payroll import brazil_dormancy, service

    if not brazil_dormancy.onboarding_enabled():
        raise ForbiddenException(brazil_dormancy.DORMANT_MESSAGE)
    org_id = getattr(current_user, "organization_id", None)
    if org_id is None:
        return                                   # each route's _org_id answers Super Admin with its own 403
    if not brazil_dormancy.is_brazil(service._resolve_org_country(db, org_id)):
        raise ForbiddenException("The Brazil API is only available to organisations whose payroll jurisdiction "
                                 "is Brazil.")


router = APIRouter(prefix="/brazil", tags=["Brazil (Organisation)"], dependencies=[Depends(require_brazil_tenant)])

_CERT_CONTENT_TYPES = ("application/octet-stream", "application/pkix-cert", "application/x-x509-ca-cert",
                       "application/x-pem-file")


def _svc():
    from app.modules.payroll import brazil_employer_service

    return brazil_employer_service


def _emp():
    from app.modules.payroll import brazil_employee_service

    return brazil_employee_service


def _org_id(user) -> int:
    org_id = getattr(user, "organization_id", None)
    if org_id is None:
        raise ForbiddenException("Brazil employer routes act on your own organisation; "
                                 "Super Admin uses the Super Admin Brazil workspace (Employer tab, read-only).")
    return org_id


def _actor(user) -> Optional[int]:
    return getattr(user, "id", None)


# ── legal employers ──────────────────────────────────────────────────────────

@router.get("/employers", summary="Your legal employers (CNPJ-root chains) with every version")
def list_employers(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return _svc().list_employers(db, _org_id(current_user))


@router.post("/employers", summary="Record a new legal employer (version 1, org admin)")
def create_employer(body: BREmployerCreate, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _svc().create_employer(db, _org_id(current_user), body.to_service(), _actor(current_user))


@router.get("/employers/{employer_id}", summary="One legal employer with establishments, CPRB options and credentials")
def employer_detail(employer_id: int, current_user=Depends(get_current_payroll_operator),
                    db: Session = Depends(get_db)):
    return _svc().employer_detail(db, _org_id(current_user), employer_id)


@router.post("/employers/{employer_id}/versions", summary="Record a new employer version from its effective date")
def create_employer_version(employer_id: int, body: BREmployerCreate, current_user=Depends(get_current_org_admin),
                            db: Session = Depends(get_db)):
    return _svc().create_employer_version(db, _org_id(current_user), employer_id, body.to_service(),
                                          _actor(current_user))


# ── establishments ───────────────────────────────────────────────────────────

@router.post("/employers/{employer_id}/establishments", summary="Add an establishment (CNPJ checked; FPAS DECLARED)")
def create_establishment(employer_id: int, body: BREstablishmentCreate, current_user=Depends(get_current_org_admin),
                         db: Session = Depends(get_db)):
    return _svc().create_establishment(db, _org_id(current_user), employer_id, body.to_service(), _actor(current_user))


@router.put("/establishments/{establishment_id}/deactivate", summary="Deactivate an establishment from a date")
def deactivate_establishment(establishment_id: int, body: BRDeactivate, current_user=Depends(get_current_org_admin),
                             db: Session = Depends(get_db)):
    return _svc().deactivate_establishment(db, _org_id(current_user), establishment_id, body.activeTo,
                                           _actor(current_user))


# ── RAT / FAP per year ───────────────────────────────────────────────────────

@router.post("/establishments/{establishment_id}/risk-assignments",
             summary="Record RAT / FAP for a calendar year (DRAFT, with evidence)")
def create_risk_assignment(establishment_id: int, body: BRRiskAssignmentCreate,
                           current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _svc().create_risk_assignment(db, _org_id(current_user), establishment_id, body.to_service(),
                                         _actor(current_user))


@router.put("/risk-assignments/{risk_id}/activate", summary="Activate a DRAFT risk assignment (supersedes the year's)")
def activate_risk_assignment(risk_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _svc().activate_risk_assignment(db, _org_id(current_user), risk_id, _actor(current_user))


# ── CPRB option per year ─────────────────────────────────────────────────────

@router.post("/employers/{employer_id}/cprb-options", summary="Record the CPRB option for a calendar year")
def create_cprb_option(employer_id: int, body: BRCprbOptionCreate, current_user=Depends(get_current_org_admin),
                       db: Session = Depends(get_db)):
    return _svc().create_cprb_option(db, _org_id(current_user), employer_id, body.to_service(), _actor(current_user))


# ── credential references ────────────────────────────────────────────────────

@router.post("/employers/{employer_id}/credentials",
             summary="Record a gcp-sm:// credential reference (never the secret); rotates the ACTIVE one")
def create_credential(employer_id: int, payload: Dict[str, Any] = Body(...),
                      current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    # Validated here, not as a FastAPI body model: the default 422 echoes the
    # offending input back, and on this route that input may be a pasted
    # secret. Only field names and error types are returned.
    from pydantic import ValidationError

    try:
        body = BRCredentialCreate(**payload)
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


# ── readiness ────────────────────────────────────────────────────────────────

@router.get("/readiness", summary="Employer readiness for an explicit date, plus the G1–G8 gates")
def readiness(on: date = Query(..., description="The date to assess — required, never the server date"),
              current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return _svc().organisation_readiness(db, _org_id(current_user), on)


# ── employee statutory profiles & child records (Phase 4) ────────────────────

@router.get("/employees/{employee_id}",
            summary="One Brazil employee record: statutory profile versions + child records (identifiers masked)")
def employee_record(employee_id: int, on: Optional[date] = Query(None, description="Restrict profile versions to those in force on this date"),
                    current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return _emp().employee_record(db, _org_id(current_user), employee_id, on)


@router.get("/employees/{employee_id}/readiness", summary="Per-employee Brazil readiness on an explicit date")
def employee_readiness(employee_id: int, on: date = Query(..., description="The date to assess — required"),
                       current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return _emp().employee_readiness(db, _org_id(current_user), employee_id, on)


@router.post("/employees/{employee_id}/concurrent-inss-declarations",
             summary="Record the concurrent-employment INSS declaration for a competência (supersedes the month's)")
def record_concurrent_inss(employee_id: int, body: BRConcurrentInssDeclarationCreate,
                           current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _emp().record_concurrent_inss_declaration(db, _org_id(current_user), employee_id, body.to_service(),
                                                     _actor(current_user))


@router.get("/employees/{employee_id}/concurrent-inss-declarations",
            summary="The concurrent-employment INSS declarations recorded for an employee")
def list_concurrent_inss(employee_id: int, current_user=Depends(get_current_payroll_operator),
                         db: Session = Depends(get_db)):
    return _emp().list_concurrent_inss_declarations(db, _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/alimony-orders",
             summary="Record a court-ordered alimony order (fixed amount or percentage × base)")
def record_alimony_order(employee_id: int, body: BRAlimonyOrderCreate,
                         current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _emp().record_alimony_order(db, _org_id(current_user), employee_id, body.to_service(),
                                       _actor(current_user))


@router.put("/alimony-orders/{order_id}/close", summary="Close an active alimony order from a date")
def close_alimony_order(order_id: int, body: BRAlimonyOrderClose,
                        current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _emp().close_alimony_order(db, _org_id(current_user), order_id, body.to_service(), _actor(current_user))


@router.post("/employees/{employee_id}/vale-transporte-elections",
             summary="Record a vale-transporte election (elected flag + declared daily cost)")
def record_vale_transporte(employee_id: int, body: BRValeTransporteElectionCreate,
                           current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _emp().record_vale_transporte_election(db, _org_id(current_user), employee_id, body.to_service(),
                                                  _actor(current_user))


# ── run preflight & approval fingerprint (Phase 6) ─────────────────────────────

@router.get("/runs/{run_id}/preflight", summary="Brazil preflight + exceptions for a run (read-only)")
def get_run_preflight(run_id: int, current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    org_id = _org_id(current_user)
    from app.modules.payroll.models import PayrollRun
    run = db.query(PayrollRun).filter(PayrollRun.id == run_id, PayrollRun.organization_id == org_id).first()
    if run is None:
        raise BadRequestException(f"Run #{run_id} not found in this organisation")
    checks = br.br_run_preflight(db, run)
    status = "BLOCKED" if any(c["severity"] == "BLOCK" for c in checks) else "OK"
    return {"status": status, "checks": checks}


@router.get("/runs/{run_id}/fingerprint", summary="Approval fingerprint over the run's frozen BR inputs")
def get_run_fingerprint(run_id: int, current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    org_id = _org_id(current_user)
    from app.modules.payroll.models import PayrollRun
    run = db.query(PayrollRun).filter(PayrollRun.id == run_id, PayrollRun.organization_id == org_id).first()
    if run is None:
        raise BadRequestException(f"Run #{run_id} not found in this organisation")
    fp = br.br_approval_fingerprint(db, run, store=False)
    return {**fp, "stored": run.br_approval_fingerprint}
