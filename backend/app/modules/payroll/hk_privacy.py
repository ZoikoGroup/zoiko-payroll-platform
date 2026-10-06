"""
modules/payroll/hk_privacy.py
-----------------------------
Hong Kong privacy technical controls (gap-closure D-19), HK-only:

* an append-only ACCESS LOG for HK statutory data — report / certificate /
  ZIP downloads and HK statutory-profile views — with actor, organisation,
  resource, employee, purpose, result, client address, user agent and, when
  the request runs under a SafeGuard assisted-access session, that session id;
* LEGAL HOLDS on HK records (organisation-wide or per employee): while one is
  ACTIVE, no HK record in scope can be deleted; releasing needs a different
  user from the one who placed it (four-eyes);
* a deletion guard: an HK employee with retained statutory records is never
  hard-deleted by an ordinary tenant path.

What this module deliberately does NOT do: choose a retention period, delete
or anonymise anything on a schedule, or claim PDPO compliance. Those are owner
/ privacy-counsel decisions (docs/HONG_KONG_RELEASE_EVIDENCE/D19/).
"""

from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import hk_service
from app.modules.payroll.models import HkgAccessEvent, HkgLegalHold

ACCESS_ACTIONS = ("VIEW_REPORT", "DOWNLOAD_CERTIFICATE", "DOWNLOAD_CERTIFICATES_ZIP", "VIEW_STATUTORY_PROFILE",
                  "DOWNLOAD_PAYSLIP", "DOWNLOAD_PAYSLIPS_ZIP", "DOWNLOAD_BANK_FILE")


def _request_meta(request) -> dict:
    if request is None:
        return {}
    meta = {"client_address": (getattr(getattr(request, "client", None), "host", None) or None),
            "user_agent": (request.headers.get("user-agent") or "")[:300] or None}
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        try:
            from app.core.security import decode_assisted_access_token

            payload = decode_assisted_access_token(auth.split(" ", 1)[1].strip())
            if payload and payload.get("assisted_access_session_id"):
                meta["assisted_access_session_id"] = int(payload["assisted_access_session_id"])
        except Exception:   # an access log never breaks the request it records
            pass
    return meta


def record_access(db: Session, organization_id: int, actor_id: Optional[int], action: str, resource_type: str,
                  resource_id: Optional[int] = None, employee_id: Optional[int] = None, report_type: Optional[str] = None,
                  purpose: Optional[str] = None, result: str = "SUCCESS", request=None) -> HkgAccessEvent:
    if action not in ACCESS_ACTIONS:
        raise ValueError(f"unknown HK access action {action!r}")
    event = HkgAccessEvent(organization_id=organization_id, actor_id=actor_id, action=action,
                           resource_type=resource_type, resource_id=resource_id, employee_id=employee_id,
                           report_type=report_type, purpose=(purpose or None) and purpose[:200], result=result,
                           **_request_meta(request))
    db.add(event)
    db.commit()
    return event


def is_hk_report(report) -> bool:
    return bool(report is not None and (str(getattr(report, "jurisdiction_country", "") or "").upper() == "HK"
                                        or str(getattr(report, "report_type", "") or "").startswith("HK_")))


def log_report_download(db: Session, organization_id: int, actor_id: Optional[int], report_id: int, action: str,
                        employee_id: Optional[int] = None, request=None, purpose: Optional[str] = None) -> None:
    """Called by the SHARED download routes after the file was produced; a
    no-op for every non-HK report, so no other country's behaviour changes."""
    from app.modules.payroll.models import GeneratedReport

    report = (db.query(GeneratedReport)
              .filter(GeneratedReport.id == report_id, GeneratedReport.organization_id == organization_id).first())
    if not is_hk_report(report):
        return
    record_access(db, organization_id, actor_id, action, "generated_report", resource_id=report.id,
                  employee_id=employee_id if employee_id is not None else report.employee_id,
                  report_type=report.report_type, purpose=purpose, request=request)


def log_payslip_access(db: Session, organization_id: int, actor_id: Optional[int], payslip_ids: list, action: str,
                       request=None, run_id: Optional[int] = None) -> None:
    """Called by the SHARED payslip / payslip-ZIP / bank-file download routes
    after the file was produced. Logs one event per HONG KONG payslip in the
    download (with its employee); a no-op for every other country's payslips."""
    from app.modules.payroll.models import PayslipItem

    if not payslip_ids:
        return
    rows = (db.query(PayslipItem.id, PayslipItem.employee_id, PayslipItem.country_code)
            .filter(PayslipItem.organization_id == organization_id, PayslipItem.id.in_(list(payslip_ids))).all())
    hk_rows = [r for r in rows if (r.country_code or "").upper() == "HK"]
    if not hk_rows:
        return
    meta = _request_meta(request)
    for r in hk_rows:
        db.add(HkgAccessEvent(organization_id=organization_id, actor_id=actor_id, action=action,
                              resource_type="payslip_item", resource_id=r.id, employee_id=r.employee_id,
                              purpose=f"payroll run {run_id}" if run_id else None, result="SUCCESS", **meta))
    db.commit()


def list_access_events(db: Session, organization_id: int, employee_id: Optional[int] = None, limit: int = 200) -> list:
    q = db.query(HkgAccessEvent).filter(HkgAccessEvent.organization_id == organization_id)
    if employee_id is not None:
        q = q.filter(HkgAccessEvent.employee_id == employee_id)
    rows = q.order_by(HkgAccessEvent.id.desc()).limit(max(1, min(int(limit), 1000))).all()
    return [{"id": e.id, "actorId": e.actor_id, "action": e.action, "resourceType": e.resource_type,
             "resourceId": e.resource_id, "employeeId": e.employee_id, "reportType": e.report_type,
             "purpose": e.purpose, "result": e.result, "clientAddress": e.client_address,
             "assistedAccessSessionId": e.assisted_access_session_id,
             "occurredAt": hk_service._iso(e.occurred_at)} for e in rows]


# ── legal holds ─────────────────────────────────────────────────────────

def place_legal_hold(db: Session, organization_id: int, employee_id: Optional[int], reason: str,
                     reference: Optional[str], actor_id: Optional[int]) -> HkgLegalHold:
    reason = (reason or "").strip()
    if not reason:
        raise BadRequestException("a legal hold needs a reason")
    if employee_id is not None:
        hk_service._employee(db, employee_id, organization_id)       # 404 outside the tenant; HK employees only
    hold = HkgLegalHold(organization_id=organization_id, employee_id=employee_id, status="ACTIVE", reason=reason,
                        reference=(reference or None), placed_by_id=actor_id,
                        placed_at=datetime.utcnow().replace(microsecond=0))
    db.add(hold)
    db.flush()
    hk_service._audit(db, actor_id, "create", "hkg_legal_hold", hold.id,
                      new={"employeeId": employee_id, "reference": reference, "scope": "EMPLOYEE" if employee_id else "ORGANISATION"},
                      reason=reason, commit=False)
    db.commit()
    return hold


def release_legal_hold(db: Session, organization_id: int, hold_id: int, reason: str,
                       actor_id: Optional[int]) -> HkgLegalHold:
    hold = (db.query(HkgLegalHold)
            .filter(HkgLegalHold.id == hold_id, HkgLegalHold.organization_id == organization_id).first())
    if hold is None:
        raise NotFoundException("Hong Kong legal hold", hold_id)
    if hold.status != "ACTIVE":
        raise BadRequestException(f"legal hold #{hold.id} is {hold.status}")
    reason = (reason or "").strip()
    if not reason:
        raise BadRequestException("releasing a legal hold needs a reason")
    hk_service._four_eyes(hold.placed_by_id, actor_id, "Releasing a legal hold")
    hold.status, hold.released_by_id, hold.release_reason = "RELEASED", actor_id, reason
    hold.released_at = datetime.utcnow().replace(microsecond=0)
    hk_service._audit(db, actor_id, "status_change", "hkg_legal_hold", hold.id, old={"status": "ACTIVE"},
                      new={"status": "RELEASED"}, reason=reason, commit=False)
    db.commit()
    return hold


def active_legal_holds(db: Session, organization_id: int, employee_id: Optional[int] = None) -> list:
    q = db.query(HkgLegalHold).filter(HkgLegalHold.organization_id == organization_id, HkgLegalHold.status == "ACTIVE")
    rows = q.all()
    if employee_id is None:
        return rows
    return [h for h in rows if h.employee_id is None or h.employee_id == employee_id]


def list_legal_holds(db: Session, organization_id: int) -> list:
    rows = (db.query(HkgLegalHold).filter(HkgLegalHold.organization_id == organization_id)
            .order_by(HkgLegalHold.id.desc()).all())
    return [{"id": h.id, "employeeId": h.employee_id, "scope": "EMPLOYEE" if h.employee_id else "ORGANISATION",
             "status": h.status, "reason": h.reason, "reference": h.reference, "placedById": h.placed_by_id,
             "placedAt": hk_service._iso(h.placed_at), "releasedById": h.released_by_id,
             "releasedAt": hk_service._iso(h.released_at), "releaseReason": h.release_reason} for h in rows]


def assert_employee_deletable(db: Session, organization_id: int, employee_id: int) -> None:
    """Refuses to hard-delete an HK employee under a legal hold, or one with any
    retained HK statutory record (profile versions, work hours, IRD cases,
    IR56G holds, average-wage / termination results, corrections). Deactivate
    the employee instead — the retention period is an owner decision (D-19)."""
    from app.modules.payroll.models import (
        EmployeeStatutoryProfile, HkgAverageWageSnapshot, HkgIrdReportingCase, HkgPayslipCorrection,
        HkgTaxClearanceHold, HkgTerminationResult, HkgWorkHours,
    )

    holds = active_legal_holds(db, organization_id, employee_id)
    if holds:
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail=(
            f"legal hold #{holds[0].id} is in force — Hong Kong records in its scope cannot be deleted"))
    for model, label in ((HkgIrdReportingCase, "IRD reporting cases"), (HkgTaxClearanceHold, "IR56G tax-clearance cases"),
                         (HkgWorkHours, "verified work hours"), (HkgAverageWageSnapshot, "average-wage snapshots"),
                         (HkgTerminationResult, "termination results"), (HkgPayslipCorrection, "payroll corrections"),
                         (HkgLegalHold, "legal-hold history")):            # a released hold is retained evidence too
        if db.query(model.id).filter(model.organization_id == organization_id, model.employee_id == employee_id).first():
            raise HTTPException(http_status.HTTP_409_CONFLICT, detail=(
                f"this Hong Kong employee has retained statutory records ({label}) — set the status to Inactive "
                "instead; the retention period is an owner / privacy-counsel decision"))
    if (db.query(EmployeeStatutoryProfile.id)
            .filter(EmployeeStatutoryProfile.employee_id == employee_id, EmployeeStatutoryProfile.country_code == "HK")
            .first()):
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail=(
            "this Hong Kong employee has statutory profile versions (retained evidence) — set the status to Inactive instead"))
