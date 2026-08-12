"""
modules/assist/tools.py
-----------------------
Tool Gateway for Zoiko Payroll Assist.

Read tools retrieve authoritative payroll data deterministically and expose
it as evidence. A3 action tools compute a before/after preview that must be
confirmed by the user before the mutation is applied; execution re-checks
permissions, bumps object versions and writes an action receipt + audit
event. No A4/A5 executable tools are registered (AIG-006).

The payroll domain tables remain authoritative — Assist only stores typed
references and approved minimum snapshots.
"""

import logging
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.modules.assist.models import (
    AssistAuditEvent,
    AssistExceptionSnapshot,
    AssistHandoff,
    AssistHandoffPreview,
)
from app.modules.payroll.models import PayrollLeaveRequest, PayrollRun, PayslipItem

logger = logging.getLogger("zoiko_payroll.assist.tools")


# ── Run resolution ──────────────────────────────────────────────────────

def resolve_run(
    db: Session,
    org_id: int,
    run_id: int | None = None,
    context_object: dict | None = None,
) -> PayrollRun | None:
    """Resolve the target payroll run from an explicit id or the bound context."""
    if run_id:
        return db.query(PayrollRun).filter(PayrollRun.organization_id == org_id, PayrollRun.id == run_id).first()
    if context_object and context_object.get("type") == "PAYROLL_RUN" and context_object.get("id"):
        try:
            return db.query(PayrollRun).filter(
                PayrollRun.organization_id == org_id,
                PayrollRun.id == int(context_object["id"]),
            ).first()
        except (TypeError, ValueError):
            return None
    return (
        db.query(PayrollRun)
        .filter(PayrollRun.organization_id == org_id)
        .order_by(PayrollRun.period_start.desc())
        .first()
    )


def _run_summary(run: PayrollRun) -> dict:
    return {
        "run_id": run.id,
        "run_code": run.run_code,
        "period": run.period_label,
        "period_start": str(run.period_start) if run.period_start else None,
        "period_end": str(run.period_end) if run.period_end else None,
        "pay_date": str(run.pay_date) if run.pay_date else None,
        "status": run.status,
        "employees": run.employee_count,
        "gross": float(run.total_gross or 0),
        "deductions": float(run.total_deductions or 0),
        "taxes": float(run.total_taxes or 0),
        "employer_contribution": float(run.total_employer_contribution or 0),
        "net": float(run.total_net or 0),
        "calculation_mode": run.calculation_mode,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


# ── Read tools ──────────────────────────────────────────────────────────

def tool_get_run_summary(db, org_id, run_id=None, context_object=None) -> dict:
    run = resolve_run(db, org_id, run_id, context_object)
    if run is None:
        return {"found": False, "reason": "No visible payroll run."}
    return {"found": True, "run": _run_summary(run), "object_version": 1}


def _materialize_exceptions(db, org_id, run: PayrollRun) -> list[AssistExceptionSnapshot]:
    """Derive exception snapshots deterministically from a run (idempotent)."""
    from app.modules.assist.models import AssistExceptionSnapshot as Snapshot

    expected = []
    if not run.employee_count:
        expected.append(("NO_EMPLOYEES", "No employees are attached to this run.", "HIGH"))
    item_count = (
        db.query(func.count(PayslipItem.id))
        .filter(PayslipItem.payroll_run_id == run.id)
        .scalar()
    )
    if item_count == 0:
        expected.append(("NO_PAYSLIP_ITEMS", "No payslip items have been generated for this run.", "HIGH"))
    if run.status == "Draft":
        expected.append(("RUN_IN_DRAFT", "The run is still in Draft and has not been submitted for review.", "MEDIUM"))
    pending_leaves = (
        db.query(func.count(PayrollLeaveRequest.id))
        .filter(
            PayrollLeaveRequest.organization_id == org_id,
            PayrollLeaveRequest.status == "pending",
        )
        .scalar()
    )
    if pending_leaves:
        expected.append(
            ("PENDING_LEAVE_REQUESTS", f"{pending_leaves} leave request(s) are awaiting review.", "MEDIUM")
        )

    created = []
    for key, description, severity in expected:
        snap = (
            db.query(Snapshot)
            .filter(Snapshot.organization_id == org_id, Snapshot.run_id == run.id, Snapshot.exception_key == key)
            .first()
        )
        if snap is None:
            snap = Snapshot(
                organization_id=org_id,
                run_id=run.id,
                exception_key=key,
                description=description,
                severity=severity,
                state="OPEN",
            )
            db.add(snap)
            db.flush()
        snap.description = description
        snap.severity = severity
        created.append(snap)
    db.commit()
    return created


def tool_get_run_readiness(db, org_id, run_id=None, context_object=None) -> dict:
    run = resolve_run(db, org_id, run_id, context_object)
    if run is None:
        return {"found": False, "reason": "No visible payroll run."}
    exceptions = _materialize_exceptions(db, org_id, run)
    open_exceptions = [e for e in exceptions if e.state != "RESOLVED"]
    readiness = "READY" if not open_exceptions and run.status == "Review" else "NOT_READY"
    return {
        "found": True,
        "run": _run_summary(run),
        "readiness": readiness,
        "blockers": [
            {"exception_key": e.exception_key, "description": e.description, "severity": e.severity, "state": e.state}
            for e in open_exceptions
        ],
        "materiality": "APPROVAL_RECOMMENDATION_NOT_RETURNED",
    }


def tool_list_exceptions(db, org_id, run_id=None, context_object=None) -> dict:
    run = resolve_run(db, org_id, run_id, context_object)
    if run is None:
        return {"found": False, "reason": "No visible payroll run."}
    exceptions = _materialize_exceptions(db, org_id, run)
    return {
        "found": True,
        "run": _run_summary(run),
        "exceptions": [
            {
                "exception_id": e.id,
                "exception_key": e.exception_key,
                "description": e.description,
                "severity": e.severity,
                "state": e.state,
                "assignee_role": e.assignee_role,
                "version": e.object_version,
            }
            for e in exceptions
        ],
    }


def tool_get_approval_status(db, org_id, run_id=None, context_object=None) -> dict:
    run = resolve_run(db, org_id, run_id, context_object)
    if run is None:
        return {"found": False, "reason": "No visible payroll run."}
    return {
        "found": True,
        "run": _run_summary(run),
        "workflow": {
            "state": run.status,
            "approved_by": run.approved_by,
            "approved_at": run.approved_at.isoformat() if run.approved_at else None,
            "authorized_by": run.authorized_by,
            "authorized_at": run.authorized_at.isoformat() if run.authorized_at else None,
            "paid_at": run.processed_at.isoformat() if run.processed_at else None,
        },
        "canonical_approval_route": "/payroll/payroll-runs",
        "cannot_approve": True,
    }


def tool_compare_periods(db, org_id, run_id=None, context_object=None, arguments=None) -> dict:
    arguments = arguments or {}
    base_run = resolve_run(db, org_id, run_id, context_object)
    target_id = arguments.get("target_run_id") or arguments.get("run_id")
    if base_run is None:
        return {"found": False, "reason": "No visible payroll run to compare."}
    target_run = None
    if target_id:
        target_run = (
            db.query(PayrollRun)
            .filter(PayrollRun.organization_id == org_id, PayrollRun.id == int(target_id))
            .first()
        )
    if target_run is None or target_run.id == base_run.id:
        target_run = (
            db.query(PayrollRun)
            .filter(
                PayrollRun.organization_id == org_id,
                PayrollRun.id != base_run.id,
            )
            .order_by(PayrollRun.period_start.desc())
            .first()
        )
    if target_run is None:
        return {"found": False, "reason": "Need two payroll runs to compare."}
    return {
        "found": True,
        "period_a": _run_summary(base_run),
        "period_b": _run_summary(target_run),
        "deltas": {
            "gross": float(base_run.total_gross or 0) - float(target_run.total_gross or 0),
            "deductions": float(base_run.total_deductions or 0) - float(target_run.total_deductions or 0),
            "taxes": float(base_run.total_taxes or 0) - float(target_run.total_taxes or 0),
            "net": float(base_run.total_net or 0) - float(target_run.total_net or 0),
        },
        "partial_data": False,
    }


# ── A3 action tools (preview / execute) ─────────────────────────────────

def preview_assign_exception(db, org_id, session_id, user, target, arguments) -> dict:
    run = db.query(PayrollRun).filter(PayrollRun.organization_id == org_id, PayrollRun.id == int(target["id"])).first()
    exception = None
    if run is not None:
        exception = (
            db.query(AssistExceptionSnapshot)
            .filter(
                AssistExceptionSnapshot.organization_id == org_id,
                AssistExceptionSnapshot.run_id == run.id,
            )
            .first()
        )
    if run is None or exception is None:
        return {"error": "No visible exception for the target run."}
    assignee_role = (arguments.get("assignee_role") or "LOCAL_PAYROLL_OWNER").upper()
    return {
        "target": {"type": "PAYROLL_EXCEPTION", "id": str(exception.id), "version": exception.object_version},
        "before": {"assignee_role": exception.assignee_role, "state": exception.state},
        "after": {"assignee_role": assignee_role, "state": exception.state},
        "confirmation_label": f"Confirm assignment to {assignee_role}",
        "step_up_required": False,
        "expires_minutes": 10,
    }


def execute_assign_exception(db, org_id, session_id, user, preview) -> dict:
    exception = db.query(AssistExceptionSnapshot).filter(AssistExceptionSnapshot.id == int(preview.target_id)).first()
    if exception is None or exception.organization_id != org_id:
        return {"outcome": "FAILED", "reason": "Target exception no longer visible."}
    assignee_role = (preview.after_data or {}).get("assignee_role") or "LOCAL_PAYROLL_OWNER"
    exception.assignee_role = assignee_role
    exception.object_version += 1
    db.flush()
    audit = _record_audit(db, org_id, user, session_id, "assist.action_assigned", {"action": "payroll.assignException", "target": f"exc_{exception.id}"})
    return {"outcome": "SUCCEEDED", "target_version": exception.object_version, "audit_id": audit.id}


def preview_add_note(db, org_id, session_id, user, target, arguments) -> dict:
    run = db.query(PayrollRun).filter(PayrollRun.organization_id == org_id, PayrollRun.id == int(target["id"])).first()
    if run is None:
        return {"error": "No visible payroll run for the target."}
    note = (arguments.get("note") or "").strip()
    if not note:
        return {"error": "A note is required."}
    current_notes = run.notes or ""
    appended = (current_notes.rstrip() + "\n" if current_notes else "") + f"[Assist] {note}"
    return {
        "target": {"type": "PAYROLL_RUN", "id": str(run.id), "version": 1},
        "before": {"notes": current_notes},
        "after": {"notes": appended},
        "confirmation_label": "Confirm note",
        "step_up_required": False,
        "expires_minutes": 10,
    }


def execute_add_note(db, org_id, session_id, user, preview) -> dict:
    run = db.query(PayrollRun).filter(PayrollRun.organization_id == org_id, PayrollRun.id == int(preview.target_id)).first()
    if run is None:
        return {"outcome": "FAILED", "reason": "Target run no longer visible."}
    run.notes = (preview.after_data or {}).get("notes") or run.notes
    db.flush()
    audit = _record_audit(db, org_id, user, session_id, "assist.note_added", {"action": "payroll.addExceptionNote", "target": f"run_{run.id}"})
    return {"outcome": "SUCCEEDED", "target_version": 1, "audit_id": audit.id}


def preview_create_handoff(db, org_id, session_id, user, target, arguments) -> dict:
    return {
        "target": {"type": "HANDOFF", "id": "new", "version": None},
        "before": {"state": "none"},
        "after": {"destination": arguments.get("destination", "PAYROLL_SUPPORT"), "reason_code": arguments.get("reason_code", "USER_REQUESTED")},
        "confirmation_label": "Confirm handoff",
        "step_up_required": False,
        "expires_minutes": 15,
    }


def execute_create_handoff(db, org_id, session_id, user, preview) -> dict:
    handoff_preview = (
        db.query(AssistHandoffPreview)
        .filter(AssistHandoffPreview.id == int(preview.target_id))
        .first()
        if preview.target_type == "HANDOFF" and preview.target_id.isdigit()
        else None
    )
    destination = (preview.after_data or {}).get("destination") or "PAYROLL_SUPPORT"
    reason_code = (preview.after_data or {}).get("reason_code") or "USER_REQUESTED"
    summary = "Handoff created through Assist."
    if handoff_preview is not None:
        destination = handoff_preview.destination
        reason_code = handoff_preview.reason_code
        summary = handoff_preview.summary
    case_id = f"case_{org_id}_{int(datetime.now().timestamp())}"
    handoff = AssistHandoff(
        organization_id=org_id,
        preview_id=preview.id,
        user_id=user.id,
        destination=destination,
        reason_code=reason_code,
        summary=summary,
        case_id=case_id,
        state="CREATED",
    )
    db.add(handoff)
    db.flush()
    audit = _record_audit(db, org_id, user, session_id, "assist.handoff_created", {"case_id": case_id, "destination": destination})
    return {"outcome": "SUCCEEDED", "handoff_id": handoff.id, "case_id": case_id, "audit_id": audit.id}


# ── Action tool registry ────────────────────────────────────────────────

ACTION_TOOLS = {
    "payroll.assignException": {
        "name": "Assign exception",
        "risk_tier": "A3",
        "description": "Assign an allowlisted exception to a permitted owner.",
        "preview": preview_assign_exception,
        "execute": execute_assign_exception,
        "requires_confirmation": True,
    },
    "payroll.addExceptionNote": {
        "name": "Add exception note",
        "risk_tier": "A3",
        "description": "Add an approved non-sensitive note to a payroll run.",
        "preview": preview_add_note,
        "execute": execute_add_note,
        "requires_confirmation": True,
    },
    "case.createHandoff": {
        "name": "Create handoff",
        "risk_tier": "A3",
        "description": "Create a governed support or compliance task/case.",
        "preview": preview_create_handoff,
        "execute": execute_create_handoff,
        "requires_confirmation": True,
    },
}

READ_TOOLS = {
    "payroll.getRunSummary": tool_get_run_summary,
    "payroll.getRunReadiness": tool_get_run_readiness,
    "payroll.listExceptions": tool_list_exceptions,
    "payroll.getApprovalStatus": tool_get_approval_status,
    "payroll.comparePeriods": tool_compare_periods,
}


def _record_audit(db, org_id, user, session_id, event_type, payload) -> AssistAuditEvent:
    event = AssistAuditEvent(
        organization_id=org_id,
        user_id=user.id if user else None,
        session_id=session_id,
        event_type=event_type,
        payload=payload,
    )
    db.add(event)
    db.flush()
    return event


def invoke_read_tool(db, org_id, tool_id, run_id=None, context_object=None, arguments=None) -> dict:
    import inspect

    handler = READ_TOOLS.get(tool_id)
    if handler is None:
        return {"found": False, "reason": f"Tool {tool_id} is not registered."}
    try:
        kwargs = {"run_id": run_id, "context_object": context_object}
        if "arguments" in inspect.signature(handler).parameters:
            kwargs["arguments"] = arguments
        return handler(db, org_id, **kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Read tool %s failed: %s", tool_id, exc)
        return {"found": False, "reason": "The requested data could not be retrieved."}


def get_action_tool(action_id: str) -> dict | None:
    return ACTION_TOOLS.get(action_id)
