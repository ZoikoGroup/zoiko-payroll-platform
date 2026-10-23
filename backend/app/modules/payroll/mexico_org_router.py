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
    MXClose, MXCredentialCreate, MXEmployerCreate, MXEstablishmentCreate, MXInfonavitModel, MXInfonavitNoticeCreate,
    MXIsnRegistrationCreate,
    MXLaborPolicyCreate, MXRegistrationCreate, MXRiskPremiumCreate,
)

def require_mexico_tenant(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    """Phase 4a dormancy guard on EVERY route here: refused unless Mexico
    onboarding is enabled on this platform AND the caller's organisation is
    Mexican (its payroll jurisdiction resolves to MX). Role checks stay on
    each route (reads: payroll operator; writes: org admin)."""
    from app.modules.payroll import mexico_dormancy, service

    org_id = getattr(current_user, "organization_id", None)
    # Phase 10e: open only with the kill switch on AND general availability or
    # this organisation's active pilot grant.
    if not mexico_dormancy.onboarding_enabled(db, org_id):
        raise ForbiddenException(mexico_dormancy.DORMANT_MESSAGE)
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


# ── employees (Phase 4b, spec §12) ───────────────────────────────────────────
# The statutory profile itself is saved through the shared
# /api/payroll/employees/{id}/statutory-profile route (Mexico hooks).

@router.get("/employees/{employee_id}", summary="Everything Mexico payroll holds for one employee (identifiers masked)")
def employee_record(employee_id: int, current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import mexico_employee_service

    return mexico_employee_service.employee_record(db, _org_id(current_user), employee_id)


@router.get("/employees/{employee_id}/readiness", summary="One employee's Mexico readiness on an explicit date")
def employee_readiness(employee_id: int, on: date = Query(..., description="Required — never the server date"),
                       current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import mexico_employee_service

    return mexico_employee_service.employee_readiness(db, _org_id(current_user), employee_id, on)


@router.post("/employees/{employee_id}/infonavit-notices",
             summary="Record an INFONAVIT credit notice (RETENCION / MODIFICACION / SUSPENSION) with its evidence")
def record_infonavit_notice(employee_id: int, body: MXInfonavitNoticeCreate, current_user=Depends(get_current_org_admin),
                            db: Session = Depends(get_db)):
    from app.modules.payroll import mexico_employee_service

    return mexico_employee_service.record_infonavit_notice(db, _org_id(current_user), employee_id, body.to_service(),
                                                           _actor(current_user))


# ── payroll runs (Phase 6, spec §13) ─────────────────────────────────────────
# Run generation / preview / approval stay on the shared run routes (Mexico
# hooks); these are the Mexico-only stages: preflight, status (four separate
# lifecycles, MX-041), reset, approved hours and opening balances.

def _run(db: Session, user, run_id: int):
    from app.modules.payroll import service

    return service.get_payroll_run_by_id(db, run_id, _org_id(user))


@router.get("/runs/{run_id}/preflight", summary="Mexico run preflight exceptions (BLOCK / WARN) from generation")
def run_preflight(run_id: int, current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import mexico_run_service

    return mexico_run_service.run_preflight(db, _run(db, current_user, run_id))


@router.post("/runs/{run_id}/preflight/{exception_id}/acknowledge",
             summary="Acknowledge a WARN exception with a note (BLOCK can never be acknowledged)")
def acknowledge_exception(run_id: int, exception_id: int, body: Dict[str, Any] = Body(...),
                          current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import mexico_run_service

    return mexico_run_service.acknowledge_exception(db, _run(db, current_user, run_id), exception_id,
                                                    str(body.get("note") or ""), _actor(current_user))


@router.get("/runs/{run_id}/status",
            summary="Payroll / CFDI / authority / bank lifecycles kept separate (MX-041) + approval drift (MX-040)")
def run_status(run_id: int, current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import mexico_run_service

    return mexico_run_service.run_status(db, _run(db, current_user, run_id))


@router.post("/runs/{run_id}/reset",
             summary="Reset an Approved (committed) run to Review — refused once any downstream lifecycle acted")
def reset_run(run_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
              db: Session = Depends(get_db)):
    from app.modules.payroll import mexico_run_service

    return mexico_run_service.reset_run(db, _run(db, current_user, run_id), _actor(current_user),
                                        str(body.get("reason") or ""))


@router.get("/employees/{employee_id}/hours", summary="Approved-hours records of one employee (D1)")
def list_hours(employee_id: int, current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import mexico_run_service

    return mexico_run_service.list_hours(db, _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/hours", summary="Record a week of hours with its time-record evidence (DRAFT)")
def record_hours(employee_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                 db: Session = Depends(get_db)):
    from app.modules.payroll import mexico_run_service

    def _date(v):
        try:
            return date.fromisoformat(str(v))
        except ValueError:
            raise BadRequestException("weekStart must be an ISO date")

    data = {"week_start": _date(body.get("weekStart")) if body.get("weekStart") else None,
            "ordinary_hours": body.get("ordinaryHours"), "overtime_hours": body.get("overtimeHours"),
            "sundays_worked": body.get("sundaysWorked"), "rest_days_worked": body.get("restDaysWorked"),
            "evidence_document_id": body.get("evidenceDocumentId")}
    return mexico_run_service.record_hours(db, _org_id(current_user), employee_id, data, _actor(current_user))


@router.post("/hours/{hours_id}/approve", summary="Approve recorded hours (a second person — four-eyes)")
def approve_hours(hours_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import mexico_run_service

    return mexico_run_service.approve_hours(db, _org_id(current_user), hours_id, _actor(current_user))


@router.post("/employees/{employee_id}/opening-balances",
             summary="Record an evidenced opening variable-pay balance for a first bimester (D4)")
def record_opening_balance(employee_id: int, body: Dict[str, Any] = Body(...),
                           current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import mexico_run_service

    data = {"bimester": body.get("bimester"), "variable_total": body.get("variableTotal"), "days": body.get("days"),
            "evidence_document_id": body.get("evidenceDocumentId")}
    return mexico_run_service.record_opening_balance(db, _org_id(current_user), employee_id, data, _actor(current_user))


@router.post("/opening-balances/{row_id}/approve", summary="Approve an opening balance (a second person — four-eyes)")
def approve_opening_balance(row_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import mexico_run_service

    return mexico_run_service.approve_opening_balance(db, _org_id(current_user), row_id, _actor(current_user))


# ── CFDI 4.0 + Nómina 1.2 (Phase 7, spec §6 / §13 stage 6) ───────────────────
# Generation refuses in production (builder / signer blocked, no PAC adapter);
# the lifecycle, outbox, UNKNOWN rule and lineage are live behind the 4a guard.

@router.get("/runs/{run_id}/cfdi", summary="CFDI preflight, documents and summary for a Mexican run")
def run_cfdi(run_id: int, current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import mexico_cfdi_service

    return mexico_cfdi_service.run_documents(db, _run(db, current_user, run_id))


@router.post("/runs/{run_id}/cfdi/generate", summary="Generate + sign CFDI for a committed run (refused until X1–X4)")
def generate_cfdi(run_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import mexico_cfdi_service

    return mexico_cfdi_service.generate(db, _run(db, current_user, run_id), _actor(current_user))


@router.post("/cfdi/outbox/process", summary="Process pending PAC actions (explicit, operator-triggered — D5)")
def process_cfdi_outbox(current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import mexico_cfdi_service

    return mexico_cfdi_service.process_outbox(db, _org_id(current_user), _actor(current_user))


@router.get("/cfdi/documents/{document_id}", summary="One CFDI: lineage, event timeline, outbox attempts (never XML)")
def cfdi_document(document_id: int, current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import mexico_cfdi_service

    return mexico_cfdi_service.document_detail(db, _org_id(current_user), document_id)


@router.post("/cfdi/documents/{document_id}/status-query", summary="Query the PAC for an UNKNOWN / cancelling CFDI")
def cfdi_status_query(document_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import mexico_cfdi_service

    return mexico_cfdi_service.request_status_query(db, _org_id(current_user), document_id, _actor(current_user))


@router.post("/cfdi/documents/{document_id}/confirm-retry",
             summary="Confirm a retry of an UNKNOWN stamp (same payload, same idempotency key; recorded)")
def cfdi_confirm_retry(document_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                       db: Session = Depends(get_db)):
    from app.modules.payroll import mexico_cfdi_service

    return mexico_cfdi_service.confirm_retry(db, _org_id(current_user), document_id, _actor(current_user),
                                             str(body.get("reason") or ""))


@router.post("/cfdi/documents/{document_id}/cancel", summary="Request cancellation with a catalog reason (MX-018)")
def cfdi_cancel(document_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                db: Session = Depends(get_db)):
    from app.modules.payroll import mexico_cfdi_service

    return mexico_cfdi_service.cancel(db, _org_id(current_user), document_id, str(body.get("reasonCode") or ""),
                                      body.get("replacementUuid"), _actor(current_user))


@router.post("/cfdi/reconcile", summary="Move every in-flight CFDI action to UNKNOWN (after a timeout / restore, MX-062)")
def cfdi_reconcile(current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import mexico_cfdi_service

    return mexico_cfdi_service.reconcile_after_restore(db, _org_id(current_user), _actor(current_user))


@router.get("/cfdi/cancellation-reasons", summary="Cancellation reasons from the Active CFDI catalog (empty until S30)")
def cfdi_cancel_reasons(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import mexico_cfdi_service

    return mexico_cfdi_service.cancellation_reasons(db)


# ── Authorities (Phase 8): IMSS movements, liabilities, SUA, ISN returns ─────
# File-export mode (D1): nothing here transmits. Reads need a payroll
# operator; every write needs an org admin. Docs: MEXICO_PHASE_8_PLAN.md.

_ENTITY_PATHS = {"movements": "MOVEMENT", "liabilities": "LIABILITY", "isn-returns": "ISN_RETURN",
                 "sua-periods": "SUA_PERIOD"}


def _imss():
    from app.modules.payroll import mexico_imss_service

    return mexico_imss_service


def _filing():
    from app.modules.payroll import mexico_filing_service

    return mexico_filing_service


def _entity(kind: str) -> str:
    if kind not in _ENTITY_PATHS:
        raise BadRequestException(f"Unknown authority object {kind!r}")
    return _ENTITY_PATHS[kind]


@router.get("/authorities/summary", summary="Social Security Center — registrations, counts and the blocks (§14)")
def authorities_summary(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return _imss().center_summary(db, _org_id(current_user))


@router.post("/authorities/accrue", summary="Accrue authority liabilities from committed runs (idempotent)")
def authorities_accrue(current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _filing().accrue(db, _org_id(current_user), _actor(current_user))


@router.get("/authorities/liabilities", summary="Authority liability ledger (SAT ISR / IMSS / INFONAVIT / ISN)")
def authorities_liabilities(period: Optional[str] = Query(None), current_user=Depends(get_current_payroll_operator),
                            db: Session = Depends(get_db)):
    return _filing().list_liabilities(db, _org_id(current_user), period)


@router.get("/authorities/liabilities/{liability_id}", summary="One liability with its committed sources and events")
def authorities_liability(liability_id: int, current_user=Depends(get_current_payroll_operator),
                          db: Session = Depends(get_db)):
    org_id = _org_id(current_user)
    return _filing().liability_view(db, _filing()._liability(db, org_id, liability_id), with_sources=True)


@router.post("/authorities/liabilities/{liability_id}/file", summary="Record the declaration as filed (reference)")
def authorities_liability_file(liability_id: int, body: Dict[str, Any] = Body(...),
                               current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _filing().file_liability(db, _org_id(current_user), liability_id, str(body.get("reference") or ""),
                                    _actor(current_user), body.get("evidenceRef"))


@router.post("/authorities/liabilities/{liability_id}/pay", summary="Record a payment made outside Zoiko")
def authorities_liability_pay(liability_id: int, body: Dict[str, Any] = Body(...),
                              current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _filing().pay_liability(db, _org_id(current_user), liability_id, str(body.get("reference") or ""),
                                   _actor(current_user), body.get("evidenceRef"))


@router.post("/authorities/liabilities/{liability_id}/reconcile", summary="Reconcile a paid liability (four-eyes)")
def authorities_liability_reconcile(liability_id: int, current_user=Depends(get_current_org_admin),
                                    db: Session = Depends(get_db)):
    return _filing().reconcile_liability(db, _org_id(current_user), liability_id, _actor(current_user))


@router.get("/authorities/movements", summary="IMSS affiliation movements (NSS masked)")
def authorities_movements(status: Optional[str] = Query(None), current_user=Depends(get_current_payroll_operator),
                          db: Session = Depends(get_db)):
    return _imss().list_movements(db, _org_id(current_user), status)


@router.post("/authorities/movements/generate", summary="Generate movements from committed events (idempotent)")
def authorities_movements_generate(current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _imss().generate_movements(db, _org_id(current_user), _actor(current_user))


@router.post("/authorities/movements/export", summary="Export PENDING movements as a Zoiko worklist (not an IDSE file)")
def authorities_movements_export(body: Dict[str, Any] = Body(default={}), current_user=Depends(get_current_org_admin),
                                 db: Session = Depends(get_db)):
    from fastapi.responses import Response

    out = _imss().export_worklist(db, _org_id(current_user), _actor(current_user), body.get("movementIds"))
    disposition = "attachment; filename=" + '"' + out["filename"] + '"'
    return Response(content=out["content"].encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": disposition, "X-Zoiko-Batch": out["batchRef"],
                             "Cache-Control": "no-store"})


@router.get("/authorities/movements/{movement_id}", summary="One movement with its event timeline")
def authorities_movement(movement_id: int, current_user=Depends(get_current_payroll_operator),
                         db: Session = Depends(get_db)):
    org_id = _org_id(current_user)
    return _imss().movement_view(db, _imss()._movement(db, org_id, movement_id), detail=True)


@router.post("/authorities/movements/{movement_id}/outcome", summary="Record FILED / ACCEPTED / REJECTED")
def authorities_movement_outcome(movement_id: int, body: Dict[str, Any] = Body(...),
                                 current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _imss().record_outcome(db, _org_id(current_user), movement_id, str(body.get("outcome") or ""),
                                  _actor(current_user), body.get("reference"), body.get("evidenceRef"),
                                  body.get("reason"))


@router.post("/authorities/movements/{movement_id}/withdraw", summary="Withdraw a never-exported movement (reason)")
def authorities_movement_withdraw(movement_id: int, body: Dict[str, Any] = Body(...),
                                  current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _imss().withdraw(db, _org_id(current_user), movement_id, str(body.get("reason") or ""),
                            _actor(current_user))


@router.post("/authorities/movements/{movement_id}/regenerate", summary="Re-issue a REJECTED movement")
def authorities_movement_regenerate(movement_id: int, current_user=Depends(get_current_org_admin),
                                    db: Session = Depends(get_db)):
    return _imss().regenerate(db, _org_id(current_user), movement_id, _actor(current_user))


@router.get("/authorities/sua-periods", summary="SUA reconciliation periods")
def authorities_sua_periods(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return _filing().list_sua_periods(db, _org_id(current_user))


@router.post("/authorities/sua-periods", summary="Open a SUA period for a registration and month")
def authorities_sua_open(body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                         db: Session = Depends(get_db)):
    try:
        reg_id = int(body.get("registrationId"))
    except (TypeError, ValueError):
        raise BadRequestException("registrationId is required")
    return _filing().open_sua_period(db, _org_id(current_user), reg_id, str(body.get("periodKey") or ""),
                                     _actor(current_user))


@router.get("/authorities/sua-periods/{period_id}", summary="One SUA period: totals, differences, events")
def authorities_sua_period(period_id: int, current_user=Depends(get_current_payroll_operator),
                           db: Session = Depends(get_db)):
    org_id = _org_id(current_user)
    return _filing().sua_view(db, _filing()._sua(db, org_id, period_id), detail=True)


@router.post("/authorities/sua-periods/{period_id}/figures", summary="Enter SUA figures (Zoiko template, D5)")
def authorities_sua_figures(period_id: int, body: Dict[str, Any] = Body(...),
                            current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _filing().enter_sua_figures(db, _org_id(current_user), period_id, body.get("rows"),
                                       body.get("suaVersion"), _actor(current_user))


@router.post("/authorities/sua-differences/{difference_id}/explain", summary="Explain a SUA difference")
def authorities_sua_explain(difference_id: int, body: Dict[str, Any] = Body(...),
                            current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _filing().explain_difference(db, _org_id(current_user), difference_id, str(body.get("code") or ""),
                                        str(body.get("explanation") or ""), _actor(current_user))


@router.post("/authorities/sua-differences/{difference_id}/approve", summary="Approve an explanation (four-eyes)")
def authorities_sua_approve(difference_id: int, current_user=Depends(get_current_org_admin),
                            db: Session = Depends(get_db)):
    return _filing().approve_difference(db, _org_id(current_user), difference_id, _actor(current_user))


@router.post("/authorities/sua-periods/{period_id}/reconcile", summary="Reconcile a SUA period (four-eyes)")
def authorities_sua_reconcile(period_id: int, current_user=Depends(get_current_org_admin),
                              db: Session = Depends(get_db)):
    return _filing().reconcile_sua(db, _org_id(current_user), period_id, _actor(current_user))


@router.post("/authorities/sua-periods/{period_id}/payment", summary="Record the SUA / SIPARE payment made outside Zoiko")
def authorities_sua_payment(period_id: int, body: Dict[str, Any] = Body(...),
                            current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _filing().record_sua_payment(db, _org_id(current_user), period_id, str(body.get("reference") or ""),
                                        body.get("captureLine"), _actor(current_user), body.get("evidenceRef"))


@router.get("/authorities/isn-returns", summary="State ISN returns")
def authorities_isn_returns(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return _filing().list_isn_returns(db, _org_id(current_user))


@router.post("/authorities/isn-returns", summary="Draft (or refresh / amend) a state ISN return for a month")
def authorities_isn_draft(body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                          db: Session = Depends(get_db)):
    return _filing().draft_isn_return(db, _org_id(current_user), str(body.get("stateCode") or ""),
                                      str(body.get("periodKey") or ""), _actor(current_user))


@router.get("/authorities/isn-returns/{return_id}", summary="One ISN return with its MX-046 reconciliation")
def authorities_isn_return(return_id: int, current_user=Depends(get_current_payroll_operator),
                           db: Session = Depends(get_db)):
    org_id = _org_id(current_user)
    return _filing().isn_view(db, _filing()._return(db, org_id, return_id), detail=True)


@router.post("/authorities/isn-returns/{return_id}/file", summary="Record the return as filed (reference)")
def authorities_isn_file(return_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                         db: Session = Depends(get_db)):
    return _filing().file_isn_return(db, _org_id(current_user), return_id, str(body.get("reference") or ""),
                                     _actor(current_user), body.get("evidenceRef"))


@router.post("/authorities/isn-returns/{return_id}/outcome", summary="Record ACCEPTED (four-eyes) / REJECTED")
def authorities_isn_outcome(return_id: int, body: Dict[str, Any] = Body(...),
                            current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _filing().record_isn_outcome(db, _org_id(current_user), return_id, str(body.get("outcome") or ""),
                                        _actor(current_user))


@router.post("/authorities/{kind}/{entity_id}/unknown", summary="Record that a transmission's outcome is not known")
def authorities_mark_unknown(kind: str, entity_id: int, body: Dict[str, Any] = Body(default={}),
                             current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _authority_unknown_action(db, current_user, kind, entity_id, "unknown", body)


@router.post("/authorities/{kind}/{entity_id}/status-check", summary="Record an authority status check (FOUND / NOT_FOUND)")
def authorities_status_check(kind: str, entity_id: int, body: Dict[str, Any] = Body(...),
                             current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _authority_unknown_action(db, current_user, kind, entity_id, "status", body)


@router.post("/authorities/{kind}/{entity_id}/confirm-retry",
             summary="Confirm a retry after NOT_FOUND (same record, payload and key; recorded)")
def authorities_confirm_retry(kind: str, entity_id: int, body: Dict[str, Any] = Body(...),
                              current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _authority_unknown_action(db, current_user, kind, entity_id, "retry", body)


def _authority_unknown_action(db, current_user, kind, entity_id, action, body):
    from app.modules.payroll import mexico_authority_lifecycle as L

    org_id, actor = _org_id(current_user), _actor(current_user)
    entity_type = _entity(kind)
    _filing().guard(db, org_id)
    obj = L.load(db, entity_type, org_id, entity_id)
    if action == "unknown":
        L.mark_unknown(db, org_id, entity_type, obj, actor, body.get("note"))
    elif action == "status":
        L.record_status_check(db, org_id, entity_type, obj, bool(body.get("found")), body.get("reference"), actor,
                              body.get("evidenceRef"))
    else:
        L.confirm_retry(db, org_id, entity_type, obj, actor, str(body.get("reason") or ""))
    db.commit()
    views = {"MOVEMENT": lambda: _imss().movement_view(db, obj, detail=True),
             "LIABILITY": lambda: _filing().liability_view(db, obj, with_sources=True),
             "ISN_RETURN": lambda: _filing().isn_view(db, obj, detail=True),
             "SUA_PERIOD": lambda: _filing().sua_view(db, obj, detail=True)}
    return views[entity_type]()


# ── Corrections (Phase 9a): CORRECTION runs of committed payslips ────────────

def _corrections():
    from app.modules.payroll import mexico_correction_service

    return mexico_correction_service


@router.get("/runs/{run_id}/corrections", summary="Corrections of this run and corrections made by it")
def run_corrections(run_id: int, current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return _corrections().run_view(db, _org_id(current_user), run_id)


@router.post("/runs/{run_id}/corrections", summary="Open a CORRECTION run for committed payslips (recalculated)")
def open_run_correction(run_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                        db: Session = Depends(get_db)):
    return _corrections().create_correction(db, _org_id(current_user), run_id, body.get("itemIds") or [],
                                            str(body.get("reason") or ""), _actor(current_user))


@router.post("/corrections/{run_id}/void", summary="Void an uncommitted correction (its run is deleted, records kept)")
def void_run_correction(run_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                        db: Session = Depends(get_db)):
    return _corrections().void(db, _org_id(current_user), run_id, str(body.get("reason") or ""), _actor(current_user))


# ── Vacation and aguinaldo (Phase 9b) ────────────────────────────────────────

def _benefits():
    from app.modules.payroll import mexico_benefits_service

    return mexico_benefits_service


def _opt_date(value, name: str):
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise BadRequestException(f"{name} must be a date (YYYY-MM-DD)")


@router.get("/employees/{employee_id}/vacation", summary="Vacation ledger per service year, with every record")
def employee_vacation(employee_id: int, on: Optional[str] = Query(None),
                      current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return _benefits().ledger(db, _org_id(current_user), employee_id, _opt_date(on, "on"))


@router.post("/employees/{employee_id}/vacation", summary="Record vacation TAKEN or an OPENING balance (needs approval)")
def record_employee_vacation(employee_id: int, body: Dict[str, Any] = Body(...),
                             current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    data = {"kind": body.get("kind"), "days": body.get("days"), "service_year": body.get("serviceYear"),
            "start_date": _opt_date(body.get("startDate"), "startDate"),
            "end_date": _opt_date(body.get("endDate"), "endDate"), "note": body.get("note")}
    return _benefits().record_vacation(db, _org_id(current_user), employee_id, data, _actor(current_user))


@router.post("/vacation/{record_id}/approve", summary="Approve a vacation record (a different person)")
def approve_employee_vacation(record_id: int, current_user=Depends(get_current_org_admin),
                              db: Session = Depends(get_db)):
    return _benefits().approve_vacation(db, _org_id(current_user), record_id, _actor(current_user))


@router.post("/vacation/{record_id}/withdraw", summary="Withdraw a vacation record whose premium is not paid")
def withdraw_employee_vacation(record_id: int, body: Dict[str, Any] = Body(...),
                               current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _benefits().withdraw_vacation(db, _org_id(current_user), record_id, str(body.get("reason") or ""),
                                         _actor(current_user))


@router.post("/aguinaldo-runs", summary="Open the AGUINALDO run of a year (calculated; blocks until S24 / S26 rules)")
def open_aguinaldo_run(body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                       db: Session = Depends(get_db)):
    try:
        year = int(body.get("year"))
    except (TypeError, ValueError):
        raise BadRequestException("year is required")
    return _benefits().create_aguinaldo_run(db, _org_id(current_user), year, _opt_date(body.get("payDate"), "payDate"),
                                            body.get("employeeIds"), _actor(current_user))


# ── Termination and finiquito (Phase 9c) ─────────────────────────────────────

def _terminations():
    from app.modules.payroll import mexico_termination_service

    return mexico_termination_service


@router.get("/termination-reasons", summary="The transcribed termination-reason catalog (empty until S26)")
def termination_reasons(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return _terminations().reasons(db, _org_id(current_user))


@router.get("/employees/{employee_id}/terminations", summary="The employee's termination records")
def employee_terminations(employee_id: int, current_user=Depends(get_current_payroll_operator),
                          db: Session = Depends(get_db)):
    return _terminations().list_terminations(db, _org_id(current_user), employee_id)


@router.post("/employees/{employee_id}/terminations",
             summary="Record a termination: date, catalog reason, evidence (needs approval)")
def record_employee_termination(employee_id: int, body: Dict[str, Any] = Body(...),
                                current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    data = {"termination_date": _opt_date(body.get("terminationDate"), "terminationDate"),
            "reason_code": body.get("reasonCode"), "evidence_ref": body.get("evidenceRef"), "note": body.get("note")}
    return _terminations().record_termination(db, _org_id(current_user), employee_id, data, _actor(current_user))


@router.post("/terminations/{termination_id}/approve",
             summary="Approve a termination (a different person) — sets the date of leaving, generates the BAJA")
def approve_employee_termination(termination_id: int, current_user=Depends(get_current_org_admin),
                                 db: Session = Depends(get_db)):
    return _terminations().approve_termination(db, _org_id(current_user), termination_id, _actor(current_user))


@router.post("/terminations/{termination_id}/cancel",
             summary="Cancel a termination before its finiquito run exists (withdraws an unsent BAJA)")
def cancel_employee_termination(termination_id: int, body: Dict[str, Any] = Body(...),
                                current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _terminations().cancel_termination(db, _org_id(current_user), termination_id,
                                              str(body.get("reason") or ""), _actor(current_user))


@router.post("/terminations/{termination_id}/finiquito-run",
             summary="Open the FINIQUITO run of an approved termination (blocks until S24 / S25 / S26 rules)")
def open_finiquito_run(termination_id: int, body: Dict[str, Any] = Body(...),
                       current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _terminations().create_finiquito_run(db, _org_id(current_user), termination_id,
                                                _opt_date(body.get("payDate"), "payDate"), _actor(current_user))


# ── PTU (Phase 9d) ───────────────────────────────────────────────────────────

def _ptu():
    from app.modules.payroll import mexico_ptu_service

    return mexico_ptu_service


@router.get("/ptu/exclusion-reasons", summary="The transcribed PTU exclusion catalog (empty until S26)")
def ptu_exclusion_reasons(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return _ptu().exclusion_reasons(db, _org_id(current_user))


@router.get("/ptu/cycles", summary="PTU cycles of the organisation's legal employers")
def ptu_cycles(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return _ptu().list_cycles(db, _org_id(current_user))


@router.post("/ptu/cycles", summary="Record a PTU cycle: employer, fiscal year, distributable amount, evidence")
def create_ptu_cycle(body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                     db: Session = Depends(get_db)):
    data = {"employer_profile_id": body.get("employerId"), "fiscal_year": body.get("fiscalYear"),
            "distributable_amount": body.get("distributableAmount"), "evidence_ref": body.get("evidenceRef"),
            "note": body.get("note")}
    return _ptu().create_cycle(db, _org_id(current_user), data, _actor(current_user))


@router.get("/ptu/cycles/{cycle_id}", summary="One PTU cycle with its allocation")
def ptu_cycle(cycle_id: int, current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return _ptu().get_cycle(db, _org_id(current_user), cycle_id)


@router.post("/ptu/cycles/{cycle_id}/approve-amount", summary="Approve the distributable amount (a different person)")
def approve_ptu_amount(cycle_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _ptu().approve_amount(db, _org_id(current_user), cycle_id, _actor(current_user))


@router.post("/ptu/cycles/{cycle_id}/exclusions", summary="Record an operator exclusion (catalog reason + evidence)")
def record_ptu_exclusion(cycle_id: int, body: Dict[str, Any] = Body(...),
                         current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    data = {"employee_id": body.get("employeeId"), "reason_code": body.get("reasonCode"),
            "evidence_ref": body.get("evidenceRef")}
    return _ptu().record_exclusion(db, _org_id(current_user), cycle_id, data, _actor(current_user))


@router.post("/ptu/cycles/{cycle_id}/exclusions/{employee_id}/approve",
             summary="Approve an operator exclusion (a different person)")
def approve_ptu_exclusion(cycle_id: int, employee_id: int, current_user=Depends(get_current_org_admin),
                          db: Session = Depends(get_db)):
    return _ptu().approve_exclusion(db, _org_id(current_user), cycle_id, employee_id, _actor(current_user))


@router.post("/ptu/cycles/{cycle_id}/allocate",
             summary="Allocate the pool by the transcribed rule from committed runs (blocks until S26)")
def allocate_ptu(cycle_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _ptu().allocate(db, _org_id(current_user), cycle_id, _actor(current_user))


@router.post("/ptu/cycles/{cycle_id}/approve-allocation",
             summary="Approve the allocation (a different person; refused if the inputs changed)")
def approve_ptu_allocation(cycle_id: int, current_user=Depends(get_current_org_admin),
                           db: Session = Depends(get_db)):
    return _ptu().approve_allocation(db, _org_id(current_user), cycle_id, _actor(current_user))


@router.post("/ptu/cycles/{cycle_id}/ptu-run", summary="Open the PTU run of an approved cycle")
def open_ptu_run(cycle_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                 db: Session = Depends(get_db)):
    return _ptu().create_ptu_run(db, _org_id(current_user), cycle_id, _opt_date(body.get("payDate"), "payDate"),
                                 _actor(current_user))


@router.post("/ptu/cycles/{cycle_id}/cancel", summary="Cancel a PTU cycle before its PTU run exists")
def cancel_ptu_cycle(cycle_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                     db: Session = Depends(get_db)):
    return _ptu().cancel_cycle(db, _org_id(current_user), cycle_id, str(body.get("reason") or ""),
                               _actor(current_user))


@router.get("/employees/{employee_id}/ptu", summary="The employee's PTU allocations by fiscal year")
def employee_ptu(employee_id: int, current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return _ptu().employee_ptu(db, _org_id(current_user), employee_id)


# ── Annual ISR adjustment (Phase 9e) ─────────────────────────────────────────

def _annual():
    from app.modules.payroll import mexico_annual_service

    return mexico_annual_service


@router.get("/annual-adjustments/exclusion-reasons", summary="The transcribed annual-adjustment exclusion catalog")
def annual_adjustment_exclusion_reasons(current_user=Depends(get_current_payroll_operator),
                                        db: Session = Depends(get_db)):
    return _annual().exclusion_reasons(db, _org_id(current_user))


@router.get("/annual-adjustments", summary="Annual ISR adjustments by legal employer and fiscal year")
def annual_adjustments(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return _annual().list_adjustments(db, _org_id(current_user))


@router.post("/annual-adjustments/compute",
             summary="Compute an employer's ended fiscal year from committed runs (blocks until S24)")
def compute_annual_adjustment(body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                              db: Session = Depends(get_db)):
    data = {"employer_profile_id": body.get("employerId"), "fiscal_year": body.get("fiscalYear")}
    return _annual().compute(db, _org_id(current_user), data, _actor(current_user))


@router.post("/annual-adjustments/approve", summary="Approve an employer-year (a different person; refused if stale)")
def approve_annual_adjustment(body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                              db: Session = Depends(get_db)):
    data = {"employer_profile_id": body.get("employerId"), "fiscal_year": body.get("fiscalYear")}
    return _annual().approve(db, _org_id(current_user), data, _actor(current_user))


@router.post("/annual-adjustments/apply", summary="Apply an approved employer-year in a later open ordinary run")
def apply_annual_adjustment(body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                            db: Session = Depends(get_db)):
    data = {"employer_profile_id": body.get("employerId"), "fiscal_year": body.get("fiscalYear"),
            "run_id": body.get("runId")}
    return _annual().apply_to_run(db, _org_id(current_user), data, _actor(current_user))


@router.post("/annual-adjustments/{row_id}/exclusion", summary="Record an operator exclusion (catalog reason + evidence)")
def record_annual_adjustment_exclusion(row_id: int, body: Dict[str, Any] = Body(...),
                                       current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    data = {"reason_code": body.get("reasonCode"), "evidence_ref": body.get("evidenceRef")}
    return _annual().record_exclusion(db, _org_id(current_user), row_id, data, _actor(current_user))


@router.post("/annual-adjustments/{row_id}/exclusion/approve", summary="Approve an exclusion (a different person)")
def approve_annual_adjustment_exclusion(row_id: int, current_user=Depends(get_current_org_admin),
                                        db: Session = Depends(get_db)):
    return _annual().approve_exclusion(db, _org_id(current_user), row_id, _actor(current_user))


@router.get("/employees/{employee_id}/annual-adjustments", summary="The employee's annual ISR adjustments")
def employee_annual_adjustments(employee_id: int, current_user=Depends(get_current_payroll_operator),
                                db: Session = Depends(get_db)):
    return _annual().employee_adjustments(db, _org_id(current_user), employee_id)


# ── Salary payments (Phase 10a) ──────────────────────────────────────────────

def _payments():
    from app.modules.payroll import mexico_payment_service

    return mexico_payment_service


@router.get("/payments/batches", summary="Salary payment batches (optionally of one run)")
def payment_batches(run_id: Optional[int] = Query(None), current_user=Depends(get_current_payroll_operator),
                    db: Session = Depends(get_db)):
    return _payments().list_batches(db, _org_id(current_user), run_id)


@router.post("/runs/{run_id}/payment-batch", summary="Build the salary payment batch of a committed run")
def create_payment_batch(run_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _payments().create_batch(db, _org_id(current_user), run_id, _actor(current_user))


@router.get("/payments/batches/{batch_id}", summary="One payment batch with its items (CLABE last 4 only)")
def payment_batch(batch_id: int, current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return _payments().get_batch(db, _org_id(current_user), batch_id)


@router.post("/payments/batches/{batch_id}/release", summary="Release a batch (a different person)")
def release_payment_batch(batch_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _payments().release_batch(db, _org_id(current_user), batch_id, _actor(current_user))


@router.post("/payments/batches/{batch_id}/cancel", summary="Cancel a DRAFT batch")
def cancel_payment_batch(batch_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                         db: Session = Depends(get_db)):
    return _payments().cancel_batch(db, _org_id(current_user), batch_id, str(body.get("reason") or ""),
                                    _actor(current_user))


@router.post("/payments/batches/{batch_id}/worklist",
             summary="Build the payment worklist of a released batch (NOT a bank file; full CLABE, not stored)")
def payment_worklist(batch_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from fastapi.responses import Response

    out = _payments().export_worklist(db, _org_id(current_user), batch_id, _actor(current_user))
    return Response(content=out["content"].encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{out["filename"]}"',
                             "Cache-Control": "no-store", "X-Zoiko-Worklist-Sha256": out["sha256"]})


@router.post("/payments/items/{item_id}/outcome", summary="Record a payment's outcome (with the bank reference)")
def record_payment_outcome(item_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                           db: Session = Depends(get_db)):
    data = {"outcome": body.get("outcome"), "reference": body.get("reference"), "reason": body.get("reason")}
    return _payments().record_item_outcome(db, _org_id(current_user), item_id, data, _actor(current_user))


@router.post("/payments/batches/{batch_id}/reissue", summary="Re-issue the failed / returned payments in a new batch")
def reissue_payments(batch_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _payments().reissue(db, _org_id(current_user), batch_id, _actor(current_user))


# ── Payroll journal (Phase 10b) ──────────────────────────────────────────────

def _journal():
    from app.modules.payroll import mexico_journal_service

    return mexico_journal_service


@router.get("/journal/mappings", summary="Journal account mappings (versions) and the line types")
def journal_mappings(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return {"lineTypes": _journal().line_types(), "mappings": _journal().list_mappings(db, _org_id(current_user))}


@router.post("/journal/mappings", summary="Propose a journal account mapping (a new DRAFT version)")
def create_journal_mapping(body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                           db: Session = Depends(get_db)):
    return _journal().create_mapping(db, _org_id(current_user), body, _actor(current_user))


@router.post("/journal/mappings/{mapping_id}/approve", summary="Approve a DRAFT mapping (a different person)")
def approve_journal_mapping(mapping_id: int, current_user=Depends(get_current_org_admin),
                            db: Session = Depends(get_db)):
    return _journal().approve_mapping(db, _org_id(current_user), mapping_id, _actor(current_user))


@router.post("/journal/mappings/{mapping_id}/withdraw", summary="Withdraw a DRAFT mapping")
def withdraw_journal_mapping(mapping_id: int, current_user=Depends(get_current_org_admin),
                             db: Session = Depends(get_db)):
    return _journal().withdraw_mapping(db, _org_id(current_user), mapping_id, _actor(current_user))


@router.get("/runs/{run_id}/journal", summary="The journal of a committed run (preview, with its exports)")
def run_journal(run_id: int, current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    return _journal().run_journal(db, _org_id(current_user), run_id)


@router.post("/runs/{run_id}/journal/export", summary="Export the journal CSV of a committed run (nothing is posted)")
def export_run_journal(run_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from fastapi.responses import Response

    out = _journal().export_journal(db, _org_id(current_user), run_id, _actor(current_user))
    return Response(content=out["content"].encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{out["filename"]}"',
                             "Cache-Control": "no-store", "X-Zoiko-Journal-Sha256": out["sha256"]})


@router.post("/journal/exports/{export_id}/void", summary="Void a journal export (reversed or never posted)")
def void_journal_export(export_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                        db: Session = Depends(get_db)):
    return _journal().void_export(db, _org_id(current_user), export_id, str(body.get("reason") or ""),
                                  _actor(current_user))


# ── Pilot status (Phase 10e) — the banner on a pilot organisation's screens ──

@router.get("/pilot-status", summary="Whether this organisation is a non-binding Mexico pilot")
def pilot_status(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    from app.modules.payroll import mexico_pilot_service

    return mexico_pilot_service.pilot_status(db, _org_id(current_user))
