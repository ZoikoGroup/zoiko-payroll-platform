"""
modules/super_admin/command_center_router.py
-----------------------------------------------
Net-new Super Admin Command Center sections:

    Zoiko Commercial   -> /super-admin/billing/subscriptions
    Payroll Operations -> /super-admin/payroll/runs
                          /super-admin/compliance/filings-remittances
                          /super-admin/compliance/exceptions
    Platform           -> /super-admin/platform/service-health
                          /super-admin/platform/integrations
                          /super-admin/security/audit

Every endpoint here is a cross-tenant READ model — Super Admin is the one
legitimate case for querying across organizations without an
organization_id filter. None of these endpoints mutate payroll, billing, or
statutory state; that stays in each domain's existing, already-correct
workflows. This router is deliberately separate from the very large existing
modules/super_admin/router.py so that file doesn't grow further for
unrelated new work.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_super_admin
from app.database import get_db
from app.modules.organizations.models import Organization
from app.modules.billing.models import (
    BillingPlan,
    BillingPlanVersion,
    BillingSubscription,
    BillingWorkerMonthRecord,
    BillingCommercialAuditEvent,
)
from app.modules.payroll.models import (
    PayrollRun,
    PayrollStatus,
    GermanyElsterTransmission,
    TaxConfigurationAudit,
)
from app.modules.assist.models import AssistAuditEvent

router = APIRouter(prefix="/super-admin", tags=["Super Admin — Command Center"])


# ── Zoiko Commercial: cross-tenant Subscriptions & Billing ────────────────

def _resolve_plan_label(db: Session, plan_version_id: int) -> tuple[Optional[str], Optional[str]]:
    """Direct-ID resolution — works regardless of whether the version is
    currently PUBLISHED, unlike a filtered plan-catalog scan."""
    version = db.query(BillingPlanVersion).filter(BillingPlanVersion.id == plan_version_id).first()
    if version is None:
        return None, None
    plan = db.query(BillingPlan).filter(BillingPlan.id == version.plan_id).first()
    return (plan.code if plan else None), (plan.name if plan else None)


@router.get("/billing/subscriptions")
def list_all_subscriptions(
    status: Optional[str] = Query(None, description="Filter by SubscriptionStatus value"),
    workspace_type: Optional[str] = Query(None, description="Filter by Organization.workspace_type"),
    db: Session = Depends(get_db),
    _admin=Depends(get_current_super_admin),
):
    """Cross-tenant view of every BillingSubscription. Read-only; plan/
    subscription mutation stays in billing/admin_router.py's existing
    endpoints."""
    q = db.query(BillingSubscription, Organization).join(
        Organization, Organization.id == BillingSubscription.organization_id
    )
    if status:
        q = q.filter(BillingSubscription.status == status)
    if workspace_type:
        q = q.filter(Organization.workspace_type == workspace_type)

    rows = []
    for sub, org in q.order_by(BillingSubscription.current_period_end.asc()).all():
        plan_code, plan_name = _resolve_plan_label(db, sub.plan_version_id)
        rows.append({
            "subscription_id": sub.id,
            "organization_id": org.id,
            "organization_name": org.organization_name,
            "workspace_type": org.workspace_type,
            "status": sub.status,
            "plan_code": plan_code,
            "plan_name": plan_name,
            "current_period_start": sub.current_period_start,
            "current_period_end": sub.current_period_end,
            "grace_period_ends_at": sub.grace_period_ends_at,
        })
    return {"subscriptions": rows, "total": len(rows)}


# ── Payroll Operations: cross-tenant Payroll Runs monitor ─────────────────

AT_RISK_STATUSES = {PayrollStatus.DRAFT.value, PayrollStatus.REVIEW.value, PayrollStatus.APPROVED.value}


@router.get("/payroll/runs")
def list_all_payroll_runs(
    status: Optional[str] = Query(None),
    at_risk_window_days: int = Query(5, ge=1, le=60),
    db: Session = Depends(get_db),
    _admin=Depends(get_current_super_admin),
):
    """Cross-tenant payroll run monitor. Surfaces 'what's due soon and not
    yet AUTHORIZED' as its own at-risk section rather than a flat,
    unprioritized row list. Read-only: run status changes stay in each
    org's own existing approval workflow."""
    q = db.query(PayrollRun, Organization).join(Organization, Organization.id == PayrollRun.organization_id)
    if status:
        q = q.filter(PayrollRun.status == status)

    today = date.today()
    at_risk_cutoff = today + timedelta(days=at_risk_window_days)

    at_risk, all_runs = [], []
    for run, org in q.order_by(PayrollRun.pay_date.asc()).all():
        row = {
            "run_id": run.id,
            "run_code": run.run_code,
            "organization_id": org.id,
            "organization_name": org.organization_name,
            "period_label": run.period_label,
            "pay_date": run.pay_date,
            "status": run.status,
            "employee_count": run.employee_count,
            "total_net": str(run.total_net) if run.total_net is not None else None,
        }
        all_runs.append(row)
        if run.status in AT_RISK_STATUSES and run.pay_date <= at_risk_cutoff:
            at_risk.append(row)

    return {"at_risk": at_risk, "all_runs": all_runs, "at_risk_window_days": at_risk_window_days}


# ── Payroll Operations: Filings & Remittances ──────────────────────────────

@router.get("/compliance/filings-remittances")
def list_filings_remittances(
    db: Session = Depends(get_db),
    _admin=Depends(get_current_super_admin),
):
    """Cross-tenant filing status. Germany ELSTER today (GermanyElsterTransmission)
    — structured so a second jurisdiction's filings slot in under their own
    'jurisdiction' key without a rewrite. Bank-export/remittance file
    generation (modules/payroll/bank_export/) has no persisted status model
    today — that's a real gap, surfaced honestly below rather than a
    fabricated status column."""
    rows = (
        db.query(GermanyElsterTransmission, Organization)
        .join(Organization, Organization.id == GermanyElsterTransmission.organization_id)
        .order_by(GermanyElsterTransmission.updated_at.desc().nullslast())
        .all()
    )
    germany = []
    for tx, org in rows:
        germany.append({
            "transmission_id": tx.id,
            "organization_id": org.id,
            "organization_name": org.organization_name,
            "transmission_type": tx.transmission_type,
            "period_start": tx.period_start,
            "period_end": tx.period_end,
            "status": tx.status,
            "blocked_reason": tx.blocked_reason,
            "updated_at": tx.updated_at,
        })
    # Failed/blocked first, matching the "what's at risk" framing used for
    # the payroll-run monitor above.
    germany.sort(key=lambda r: 0 if r["status"] in ("BLOCKED_EXTERNAL", "REJECTED") else 1)

    return {
        "jurisdictions": {
            "germany": {"filings": germany, "total": len(germany)},
        },
        "known_gaps": [
            "Bank-export/remittance file generation has no persisted status "
            "model yet — only on-demand file generation. Not represented here."
        ],
    }


# ── Payroll Operations: Exceptions & Reconciliation ────────────────────────

@router.get("/compliance/exceptions")
def list_exceptions(
    stuck_review_days: int = Query(3, ge=1, le=30, description="Flag runs in REVIEW longer than this"),
    db: Session = Depends(get_db),
    _admin=Depends(get_current_super_admin),
):
    """Narrow, honest scope: (1) payroll runs stuck in REVIEW an unusual
    length of time with an approaching pay date, and (2) orgs whose actual
    Billable Worker-Month count exceeds their plan's scale_limits — a real,
    computable reconciliation between two systems that don't otherwise talk
    to each other. No auto-remediation actions here — this page surfaces
    problems; fixing them uses each domain's existing workflow."""
    stuck_runs = []
    cutoff = datetime.utcnow() - timedelta(days=stuck_review_days)
    q = (
        db.query(PayrollRun, Organization)
        .join(Organization, Organization.id == PayrollRun.organization_id)
        .filter(PayrollRun.status == PayrollStatus.REVIEW.value)
    )
    for run, org in q.all():
        marker = getattr(run, "updated_at", None) or getattr(run, "created_at", None)
        if marker is not None and marker <= cutoff:
            stuck_runs.append({
                "run_id": run.id,
                "organization_id": org.id,
                "organization_name": org.organization_name,
                "period_label": run.period_label,
                "pay_date": run.pay_date,
                "stuck_since": marker,
            })

    bwm_overages = []
    current_month_start = date.today().replace(day=1)
    bwm_counts = (
        db.query(
            BillingWorkerMonthRecord.organization_id,
            func.count(BillingWorkerMonthRecord.id).label("bwm_count"),
        )
        .filter(
            BillingWorkerMonthRecord.billing_month == current_month_start,
            BillingWorkerMonthRecord.counted.is_(True),
        )
        .group_by(BillingWorkerMonthRecord.organization_id)
        .all()
    )
    for org_id, bwm_count in bwm_counts:
        sub = db.query(BillingSubscription).filter(BillingSubscription.organization_id == org_id).first()
        if sub is None:
            continue
        version = db.query(BillingPlanVersion).filter(BillingPlanVersion.id == sub.plan_version_id).first()
        if version is None or not version.scale_limits:
            continue
        limit = version.scale_limits.get("billable_worker_months")
        if limit is not None and bwm_count > limit:
            org = db.query(Organization).filter(Organization.id == org_id).first()
            bwm_overages.append({
                "organization_id": org_id,
                "organization_name": org.organization_name if org else None,
                "billing_month": current_month_start,
                "bwm_count": bwm_count,
                "plan_limit": limit,
                "over_by": bwm_count - limit,
            })

    return {
        "stuck_reviews": stuck_runs,
        "bwm_scale_limit_overages": bwm_overages,
        "note": (
            "BWM-over-limit here is informational only — require_scope_limit() "
            "is defined in billing/entitlements.py but not called from this "
            "reconciliation view, so nothing here blocks it in real time. This "
            "page is the first place that makes the gap operationally visible."
        ),
    }


# ── Platform: Service Health ───────────────────────────────────────────────

@router.get("/platform/service-health")
def service_health(
    db: Session = Depends(get_db),
    _admin=Depends(get_current_super_admin),
):
    """Real signals only: DB connectivity/latency, and last-run/last-success/
    last-error for each registered BackgroundScheduler job. No fabricated
    'green checkmark' for a job that simply hasn't reported — an unknown/
    stale state is returned explicitly."""
    from app.modules.assist import scheduler as assist_scheduler
    from app.modules.billing import scheduler as billing_scheduler

    db_status = {"status": "unknown", "latency_ms": None}
    try:
        start = datetime.utcnow()
        db.execute(text("SELECT 1"))
        latency_ms = (datetime.utcnow() - start).total_seconds() * 1000
        db_status = {"status": "healthy", "latency_ms": round(latency_ms, 2)}
    except Exception as exc:  # noqa: BLE001
        db_status = {"status": "error", "error": str(exc)}

    def _job_health(name: str, tracker: dict) -> dict:
        last_run = tracker.get("last_run_at")
        if last_run is None:
            return {"job": name, "state": "unknown", "detail": "Has not run since this process started."}
        if tracker.get("last_error"):
            return {"job": name, "state": "error", "last_run_at": last_run, "error": tracker["last_error"]}
        return {"job": name, "state": "healthy", "last_run_at": last_run, "last_success_at": tracker.get("last_success_at")}

    return {
        "database": db_status,
        "scheduled_jobs": [
            _job_health("trial_expiry_sweep", billing_scheduler.last_run_status),
            _job_health("assist_sweep", assist_scheduler.last_run_status),
        ],
        "checked_at": datetime.utcnow(),
    }


# ── Platform: Integrations (honest placeholder) ────────────────────────────

@router.get("/platform/integrations")
def list_integrations(_admin=Depends(get_current_super_admin)):
    """No external integration layer exists in this codebase today — no
    live disbursement API, no third-party HR/ATS connectors. Returning a
    fabricated set of integration health cards for things that don't exist
    would be misleading. Honest empty state until a real integration is
    built."""
    return {
        "integrations": [],
        "message": "No external integrations are configured in this deployment yet.",
    }


# ── Platform: Security & Audit (merged read model across 3 audit tables) ──

def _naive_utc(ts: Optional[datetime]) -> Optional[datetime]:
    """The three source tables mix tz-aware (DateTime(timezone=True)) and
    tz-naive (plain DateTime, default=datetime.utcnow) columns — comparing
    them directly during the merge-sort below raises TypeError. Strip
    tzinfo (after converting to UTC) so every entry sorts on the same
    naive-UTC basis regardless of source."""
    if ts is None:
        return None
    if ts.tzinfo is not None:
        return ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts


@router.get("/security/audit")
def security_audit_log(
    source: Optional[str] = Query(None, description="compliance | billing | assist"),
    actor_id: Optional[int] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _admin=Depends(get_current_super_admin),
):
    """No single audit table exists — TaxConfigurationAudit (compliance),
    BillingCommercialAuditEvent (billing/trial), and AssistAuditEvent
    (assist) are three separately-shaped tables. Rather than a risky
    consolidation migration, this normalizes and merge-sorts across all
    three as a read model. Paginates each source query first, then merges
    pages, so a large date range doesn't load every table fully into
    memory. Append-only by nature — no edit/delete endpoint exists or
    should ever exist here."""
    normalized = []

    if source in (None, "compliance"):
        q = db.query(TaxConfigurationAudit)
        if actor_id:
            q = q.filter(TaxConfigurationAudit.actor_id == actor_id)
        for row in q.order_by(TaxConfigurationAudit.id.desc()).limit(page_size * page).all():
            normalized.append({
                "timestamp": _naive_utc(row.created_at),
                "actor_id": row.actor_id,
                "action": row.action,
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "source": "compliance",
                "detail": {"reason": row.reason, "old_value": row.old_value, "new_value": row.new_value},
            })

    if source in (None, "billing"):
        q = db.query(BillingCommercialAuditEvent)
        if actor_id:
            q = q.filter(BillingCommercialAuditEvent.actor_user_id == actor_id)
        for row in q.order_by(BillingCommercialAuditEvent.id.desc()).limit(page_size * page).all():
            normalized.append({
                "timestamp": _naive_utc(row.created_at),
                "actor_id": row.actor_user_id,
                "action": row.event_type,
                "entity_type": "billing_subscription",
                "entity_id": row.organization_id,
                "source": "billing",
                "detail": row.payload,
            })

    if source in (None, "assist"):
        q = db.query(AssistAuditEvent)
        if actor_id:
            q = q.filter(AssistAuditEvent.user_id == actor_id)
        for row in q.order_by(AssistAuditEvent.id.desc()).limit(page_size * page).all():
            normalized.append({
                "timestamp": _naive_utc(row.recorded_at),
                "actor_id": row.user_id,
                "action": row.event_type,
                "entity_type": "assist",
                "entity_id": row.id,
                "source": "assist",
                "detail": row.payload,
            })

    def _sort_key(entry):
        ts = entry["timestamp"]
        return ts if ts is not None else datetime.min

    normalized.sort(key=_sort_key, reverse=True)

    if start_date or end_date:
        def _in_range(entry):
            ts = entry["timestamp"]
            if ts is None:
                return False
            d = ts.date() if hasattr(ts, "date") else ts
            if start_date and d < start_date:
                return False
            if end_date and d > end_date:
                return False
            return True
        normalized = [e for e in normalized if _in_range(e)]

    start_idx = (page - 1) * page_size
    page_rows = normalized[start_idx:start_idx + page_size]

    return {
        "entries": page_rows,
        "page": page,
        "page_size": page_size,
        "returned": len(page_rows),
    }
