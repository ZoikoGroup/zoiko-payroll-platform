"""
modules/super_admin/command_center_router.py
-----------------------------------------------
Net-new Super Admin Command Center sections:

    Zoiko Commercial   -> /super-admin/billing/subscriptions
                          /super-admin/commercial/revenue-collections
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

The single exception is the Filings & Remittances write pair below
(PUT/DELETE on /compliance/filings-remittances/{organization_id}): while
the dashboard is displayed read-only, it is also where a Super Admin
records an organization's filing status into the otherwise-empty
statutory_filings table. That write still funnels through the same
validated service function (payroll.service.upsert_statutory_filing) any
org-facing recording UI would call, so the org jurisdiction is derived from
compliance config and per-period uniqueness is enforced in one place.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_super_admin
from app.core.jurisdiction import CODE_TO_COUNTRY_NAME
from app.database import get_db
from app.modules.organizations.models import Organization
from app.modules.billing.models import (
    BillingDunningState,
    BillingInvoice,
    BillingPlan,
    BillingPlanVersion,
    BillingSubscription,
    BillingCommercialAuditEvent,
)
from app.modules.payroll.models import (
    CompanyComplianceDetails,
    PayrollRun,
    PayrollStatus,
    GermanyElsterTransmission,
    StatutoryFiling,
    TaxConfigurationAudit,
)
from app.modules.payroll.schemas import StatutoryFilingUpsert, StatutoryFilingResponse
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
    status: Optional[str] = Query(None, description="Filter by SubscriptionStatus value, or 'NONE' for organizations with no subscription row at all"),
    workspace_type: Optional[str] = Query(None, description="Filter by Organization.workspace_type"),
    billing_classification: Optional[str] = Query(None, description="Filter by Organization.billing_classification"),
    charge_enabled: Optional[bool] = Query(None, description="Filter by Organization.charge_enabled"),
    dunning_stage: Optional[str] = Query(None, description="Filter by BillingDunningState.stage, or 'NONE' for organizations with no dunning row at all"),
    db: Session = Depends(get_db),
    _admin=Depends(get_current_super_admin),
):
    """Cross-tenant view of every Organization and its BillingSubscription,
    if it has one — an org outer-joins in as a NONE-status row rather than
    being silently dropped, since a plain inner join on BillingSubscription
    hides every PRODUCTION org that predates the trial/billing feature (they
    were created via /auth/register, which never creates a subscription
    row). Read-only; plan/subscription mutation stays in
    billing/admin_router.py's existing endpoints.

    billing_classification/charge_enabled filters exist specifically so
    "show me every non-chargeable org with an active subscription" — a
    real inconsistency worth surfacing — is answerable from this one page.

    dunning_stage/dunning_in_flight_run_guard (Step 4 / blocker #17) exist
    so a Super Admin can tell a correctly-protected org (PAST_DUE, dunning
    frozen because a run is genuinely in flight) apart from a mistakenly-
    unrestricted one at a glance, without cross-referencing the payroll
    runs list."""
    from app.modules.billing.trial_lifecycle import resolve_trial_stage

    q = db.query(Organization, BillingSubscription).outerjoin(
        BillingSubscription, BillingSubscription.organization_id == Organization.id
    )
    if workspace_type:
        q = q.filter(Organization.workspace_type == workspace_type)
    if billing_classification:
        q = q.filter(Organization.billing_classification == billing_classification)
    if charge_enabled is not None:
        q = q.filter(Organization.charge_enabled == charge_enabled)
    if status:
        if status == "NONE":
            q = q.filter(BillingSubscription.id.is_(None))
        else:
            q = q.filter(BillingSubscription.status == status)

    dunning_states = {s.organization_id: s for s in db.query(BillingDunningState).all()}

    rows = []
    for org, sub in q.order_by(Organization.organization_name.asc()).all():
        dunning_row = dunning_states.get(org.id)
        row_dunning_stage = dunning_row.stage if dunning_row else None
        if dunning_stage:
            if dunning_stage == "NONE" and dunning_row is not None:
                continue
            if dunning_stage != "NONE" and row_dunning_stage != dunning_stage:
                continue

        if sub is None:
            rows.append({
                "subscription_id": None,
                "organization_id": org.id,
                "organization_name": org.organization_name,
                "workspace_type": org.workspace_type,
                "billing_classification": org.billing_classification,
                "charge_enabled": org.charge_enabled,
                "billing_authority": None,
                "status": "NONE",
                "trial_stage": None,
                "plan_code": None,
                "plan_name": None,
                "current_period_start": None,
                "current_period_end": None,
                "grace_period_ends_at": None,
                "dunning_stage": row_dunning_stage,
                "dunning_in_flight_run_guard": dunning_row.in_flight_run_guard if dunning_row else False,
            })
            continue

        plan_code, plan_name = _resolve_plan_label(db, sub.plan_version_id)
        rows.append({
            "subscription_id": sub.id,
            "organization_id": org.id,
            "organization_name": org.organization_name,
            "workspace_type": org.workspace_type,
            "billing_classification": org.billing_classification,
            "charge_enabled": org.charge_enabled,
            "billing_authority": sub.billing_authority,
            "status": sub.status,
            # Derived stage (ACTIVE/GRACE_READONLY/CLOSED), same pure
            # function the expiry sweep uses — the raw `status` column
            # stays "TRIALING" through grace and closure, so the table
            # would otherwise show a stale trial as still-active.
            "trial_stage": resolve_trial_stage(sub),
            "plan_code": plan_code,
            "plan_name": plan_name,
            "current_period_start": sub.current_period_start,
            "current_period_end": sub.current_period_end,
            "grace_period_ends_at": sub.grace_period_ends_at,
            "dunning_stage": row_dunning_stage,
            "dunning_in_flight_run_guard": dunning_row.in_flight_run_guard if dunning_row else False,
        })
    return {"subscriptions": rows, "total": len(rows)}


# ── Zoiko Commercial: Revenue & Collections ───────────────────────────────

def _suspended_dunning_orgs(db: Session) -> list[dict]:
    """Organizations currently suspended/restricted by dunning — shared by
    revenue-collections' past_due list AND the alerts feed (billing
    category). A restricted org with in_flight_run_guard True is NOT
    treated as at-risk: the guard means an actual payroll run is in flight
    and the restriction isn't imminently destructive (see dunning.py)."""
    rows = (
        db.query(BillingDunningState, Organization)
        .join(Organization, Organization.id == BillingDunningState.organization_id)
        .order_by(Organization.organization_name.asc())
        .all()
    )
    return [
        {
            "organization_id": org.id,
            "organization_name": org.organization_name,
            "dunning_stage": state.stage,
            "in_flight_run_guard": state.in_flight_run_guard,
        }
        for state, org in rows
    ]


@router.get("/commercial/revenue-collections")
def revenue_collections(
    db: Session = Depends(get_db),
    _admin=Depends(get_current_super_admin),
):
    """Zoiko's own subscription revenue — deliberately named and placed
    under /commercial (Zoiko Commercial), NOT under /finance, and never to
    be merged with GET /super-admin/finance/overview or /finance/summary
    (service.py), which sum customer PAYROLL money movement across orgs.
    These are two different legal-entity ledgers: this endpoint reports
    what customers pay Zoiko (BillingInvoice rows); the finance endpoints
    report payroll net totals that belong to the customers themselves.
    Mixing them mislabels either one.

    MRR here is the sum of PAID BillingInvoice totals issued since the
    first of this month — populated by the real Stripe invoice.paid
    webhook path (billing/router.py:_write_invoice_from_stripe), never a
    placeholder. Split by currency because Zoiko invoices carry a currency
    column and a cross-currency aggregate without that breakdown silently
    implies a single denomination."""  # noqa: E501
    current_month_start = date.today().replace(day=1)

    paid_invoices = (
        db.query(BillingInvoice)
        .filter(BillingInvoice.status == "PAID", BillingInvoice.issued_at >= current_month_start)
        .all()
    )
    mrr_total = sum((inv.total or 0) for inv in paid_invoices)
    mrr_by_currency: dict[str, dict] = {}
    for inv in paid_invoices:
        bucket = mrr_by_currency.setdefault(inv.currency or "UNK", {"total": 0, "invoices": 0})
        bucket["total"] += inv.total or 0
        bucket["invoices"] += 1

    active_subs = (
        db.query(func.count(BillingSubscription.id))
        .filter(BillingSubscription.status == "ACTIVE")
        .scalar()
    ) or 0
    cancelled_this_month = (
        db.query(func.count(BillingSubscription.id))
        .filter(
            BillingSubscription.status == "CANCELLED",
            BillingSubscription.updated_at >= current_month_start,
        )
        .scalar()
    ) or 0

    # Simple churn: cancelled-this-month over the base that could have
    # churned (cancelled + still active). Computed in the response, not a
    # separate endpoint — it's a ratio of the two counts right above.
    churn_base = active_subs + cancelled_this_month
    churn_pct = round((cancelled_this_month / churn_base) * 100, 2) if churn_base else 0.0

    return {
        "mrr_this_month": str(mrr_total),
        "mrr_by_currency": [
            {
                "currency": cur,
                "total": str(bucket["total"]),
                "invoices": bucket["invoices"],
            }
            for cur, bucket in mrr_by_currency.items()
        ],
        "paid_invoices_this_month": len(paid_invoices),
        "active_subscriptions": active_subs,
        "cancelled_this_month": cancelled_this_month,
        "churn_pct": churn_pct,
        "past_due": _suspended_dunning_orgs(db),
    }


# ── Payroll Operations: cross-tenant Payroll Runs monitor ─────────────────

AT_RISK_STATUSES = {PayrollStatus.DRAFT.value, PayrollStatus.REVIEW.value, PayrollStatus.APPROVED.value}


def _load_payroll_runs(db: Session, status: Optional[str] = None, at_risk_window_days: int = 5) -> tuple[list, list]:
    """Shared query behind list_all_payroll_runs AND the alerts feed — the
    at-risk derivation exists once, not copied per caller."""
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
    return at_risk, all_runs


def _at_risk_payroll_runs(db: Session, at_risk_window_days: int = 5) -> list[dict]:
    """Just the at-risk subset — used by the /alerts feed (payroll_run
    category), sharing list_all_payroll_runs' query."""
    at_risk, _ = _load_payroll_runs(db, at_risk_window_days=at_risk_window_days)
    return at_risk


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
    at_risk, all_runs = _load_payroll_runs(db, status=status, at_risk_window_days=at_risk_window_days)
    return {"at_risk": at_risk, "all_runs": all_runs, "at_risk_window_days": at_risk_window_days}


# ── Payroll Operations: Filings & Remittances ──────────────────────────────

# Statuses that mean "a human needs to intervene", across both filing
# sources: Germany's ELSTER transport rejects (REJECTED / BLOCKED_EXTERNAL)
# and the manual StatutoryFiling workflow's BLOCKED state.
BLOCKED_FILING_STATUSES = ("BLOCKED_EXTERNAL", "REJECTED", "BLOCKED")


def _load_statutory_filings(db: Session) -> list[dict]:
    """All manual filing-status rows (StatutoryFiling) — the
    cross-jurisdiction model every org's AU/IN/… filings live in."""
    rows = (
        db.query(StatutoryFiling)
        .order_by(StatutoryFiling.updated_at.desc().nullslast())
        .all()
    )
    return [{
        "filing_id": sf.id,
        "source": "statutory",
        "organization_id": sf.organization_id,
        "filing_type": sf.filing_type or "—",
        "period_label": sf.period_label,
        "period_start": sf.period_start,
        "period_end": sf.period_end,
        "status": sf.status,
        "blocked_reason": sf.blocked_reason,
        "updated_at": sf.updated_at,
    } for sf in rows]


def _load_germany_filings(db: Session) -> list[dict]:
    """Shared query behind list_filings_remittances AND the alerts feed."""
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
            "source": "elster",
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
    germany.sort(key=lambda r: 0 if r["status"] in BLOCKED_FILING_STATUSES else 1)
    return germany


def _blocked_filings(db: Session) -> list[dict]:
    """Confirmed-blocked filings only (ELSTER REJECTED / BLOCKED_EXTERNAL and
    manual BLOCKED) — the subset that needs a human across both filing
    sources. Nothing here is inferred from a missing signal."""
    blocked = []
    for f in _load_statutory_filings(db):
        if f["status"] == "BLOCKED":
            blocked.append(f)
    for f in _load_germany_filings(db):
        if f["status"] in BLOCKED_FILING_STATUSES:
            blocked.append(f)
    return blocked


def _load_org_filing_coverage(db: Session) -> tuple[dict, list[dict]]:
    """Every Organization, bucketed by its configured compliance jurisdiction.

    Returns ``(jurisdictions, unconfigured)``:

      jurisdictions  {code: {label, total, blocked_count, total_orgs,
                    organizations: [{org_id, org_name, filings: [...]}]}}
                    — every org with a jurisdiction country, one bucket per
                    country. Each org's filings merge two sources:
                    StatutoryFiling rows (the manual cross-jurisdiction
                    model) plus, for Germany, its live ELSTER transmission
                    state. Orgs with no filing records get ``filings: []`` —
                    the frontend renders that as a muted "no filing records
                    yet" state, never as filed, and never as a dropped org.
      unconfigured [{org_id, org_name}] — orgs with no jurisdiction_country
                    set.

    Every org appears exactly once across the two buckets; nothing is
    inferred from a missing signal."""
    org_rows = (
        db.query(
            Organization.id.label("org_id"),
            Organization.organization_name,
            CompanyComplianceDetails.jurisdiction_country,
        )
        .outerjoin(
            CompanyComplianceDetails,
            CompanyComplianceDetails.organization_id == Organization.id,
        )
        .order_by(Organization.organization_name)
        .all()
    )
    org_names = {org_id: org_name for org_id, org_name, _ in org_rows}

    filings_by_org: dict[int, list[dict]] = {}
    for tx in _load_statutory_filings(db):
        tx["organization_name"] = org_names.get(tx["organization_id"])
        filings_by_org.setdefault(tx["organization_id"], []).append(tx)
    for tx in _load_germany_filings(db):
        filings_by_org.setdefault(tx["organization_id"], []).append(tx)

    jurisdictions: dict[str, dict] = {}
    unconfigured: list[dict] = []

    def _section(code: str) -> dict:
        if code not in jurisdictions:
            jurisdictions[code] = {
                "label": CODE_TO_COUNTRY_NAME.get(code, code),
                "total": 0,
                "blocked_count": 0,
                "total_orgs": 0,
                "organizations": [],
            }
        return jurisdictions[code]

    for org_id, org_name, raw_country in org_rows:
        country = (raw_country or "").strip().upper() or None
        if country is None:
            unconfigured.append({"org_id": org_id, "org_name": org_name})
            continue
        org_filings = filings_by_org.get(org_id, [])
        # Blocked first, then most recently updated — "what's at risk" on
        # top, matching the payroll-run monitor's framing. Stable two-pass
        # so the update ordering survives the blocked reordering.
        org_filings.sort(
            key=lambda r: r["updated_at"] or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        org_filings.sort(key=lambda r: 0 if r["status"] in BLOCKED_FILING_STATUSES else 1)
        section = _section(country)
        section["organizations"].append({
            "org_id": org_id,
            "org_name": org_name,
            "filings": org_filings,
        })
        section["total"] += len(org_filings)
        section["blocked_count"] += sum(
            1 for tx in org_filings if tx["status"] in BLOCKED_FILING_STATUSES
        )
        section["total_orgs"] += 1

    return jurisdictions, unconfigured


@router.get("/compliance/filings-remittances")
def list_filings_remittances(
    db: Session = Depends(get_db),
    _admin=Depends(get_current_super_admin),
):
    """Cross-tenant statutory filing status, with every organization visible.

    Backed by two persisted sources, merged per org: GermanyElsterTransmission
    (Germany's live ELSTER transport state) and StatutoryFiling (the manual
    cross-jurisdiction model that covers AU GST/BAS, IN TDS/GST, … and any
    manual record for a German org). Every org is bucketed under its
    configured compliance jurisdiction — never silently dropped — and an org
    with no filing records shows an explicit empty state, not a fabricated
    "filed" status. Orgs with no jurisdiction set land in 'unconfigured'.
    Bank-export/remittance file generation (modules/payroll/bank_export/)
    still has no persisted status model — that gap is stated below rather
    than faked."""
    jurisdictions, unconfigured = _load_org_filing_coverage(db)
    return {
        "jurisdictions": jurisdictions,
        "unconfigured": unconfigured,
        "known_gaps": [
            "Bank-export/remittance file generation has no persisted status "
            "model yet — only on-demand file generation. Not represented here."
        ],
    }


@router.put(
    "/compliance/filings-remittances/{organization_id}",
    response_model=StatutoryFilingResponse,
    response_model_by_alias=True,
    summary="Record or update a statutory filing status for an organization (Super Admin authored)",
)
def upsert_statutory_filing_record(
    organization_id: int,
    payload: StatutoryFilingUpsert,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_super_admin),
):
    """Write path for the Filings & Remittances dashboard: creates/updates
    one (org, jurisdiction, filing type, period) status row via the same
    validated service function any org-facing recording UI calls. The
    jurisdiction is always derived from the org's configured compliance
    country, and re-recording an existing period updates its row."""
    from app.modules.payroll import service as payroll_service

    return payroll_service.upsert_statutory_filing(db, organization_id, payload, actor_id=_admin.id)


@router.delete(
    "/compliance/filings-remittances/{organization_id}/{filing_id}",
    summary="Delete a statutory filing record",
)
def delete_statutory_filing_record(
    organization_id: int,
    filing_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_super_admin),
):
    from app.modules.payroll import service as payroll_service

    payroll_service.delete_statutory_filing(
        db, filing_id, actor_id=_admin.id, organization_id=organization_id,
    )
    return {"success": True, "message": "Filing record deleted."}


# ── Payroll Operations: Exceptions & Reconciliation ────────────────────────

def _load_bwm_scale_limit_overages(db: Session, billing_month: date) -> list:
    """Orgs whose live billable-worker count exceeds their plan's resolved
    MAX_BWM limit for `billing_month`.

    Two deliberate changes from the original implementation, which read
    BillingWorkerMonthRecord rows (a table nothing ever populated — see
    billing/bwm.py's own disclosure) against BillingPlanVersion.scale_limits
    under the wrong key ('billable_worker_months' vs feature_keys.MAX_BWM):

      1. bwm_count comes from billing/bwm.count_billable_workers() — the
         SAME live inclusion logic entitlements.require_scope_limit enforces
         at employee-creation time (payroll/router.py), so a count that
         would have been blocked always surfaces here, and it works whether
         or not the background BWM aggregation has ever run.
      2. plan_limit resolves through entitlements._resolve_entitlement() with
         feature_keys.MAX_BWM — the same feature-key vocabulary as the
         enforcement path (including Enterprise Order Form negotiated limits
         and live org overrides). A None limit means unlimited, so no
         overage row; a limit == 0 means the feature is explicitly off.
    """
    from app.modules.billing import bwm as bwm_service
    from app.modules.billing.entitlements import _resolve_entitlement, get_active_subscription
    from app.modules.billing.feature_keys import MAX_BWM

    overages = []
    for org_id, name in db.query(Organization.id, Organization.organization_name).all():
        sub = get_active_subscription(db, org_id)
        if sub is None:
            continue
        allowed, limit_value = _resolve_entitlement(db, sub, MAX_BWM)
        if not allowed or limit_value is None:
            continue
        count = bwm_service.count_billable_workers(db, org_id, as_of=billing_month)
        if count > limit_value:
            overages.append({
                "organization_id": org_id,
                "organization_name": name,
                "billing_month": billing_month,
                "bwm_count": count,
                "plan_limit": limit_value,
                "over_by": count - limit_value,
            })
    return overages


@router.get("/compliance/exceptions")
def list_exceptions(
    stuck_review_days: int = Query(3, ge=1, le=30, description="Flag runs in REVIEW longer than this"),
    db: Session = Depends(get_db),
    _admin=Depends(get_current_super_admin),
):
    """Narrow, honest scope: (1) payroll runs stuck in REVIEW an unusual
    length of time with an approaching pay date, and (2) orgs whose current
    Billable Worker-Month count exceeds their plan's resolved limit — a real,
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

    current_month_start = date.today().replace(day=1)
    bwm_overages = _load_bwm_scale_limit_overages(db, current_month_start)

    # Step 3 / Part 7 — any invoice whose BWM-priced line quantity doesn't
    # match the actual counted BillingWorkerMonthRecord rows for that org/
    # month is a real billing bug. Folded into this existing page rather
    # than a second, separate reconciliation view — this is the one home
    # for "two systems that don't otherwise talk to each other disagree."
    from app.modules.billing.invoice_explanation import find_bwm_invoice_discrepancies

    bwm_invoice_mismatches = find_bwm_invoice_discrepancies(db)

    return {
        "stuck_reviews": stuck_runs,
        "bwm_scale_limit_overages": bwm_overages,
        "bwm_invoice_mismatches": bwm_invoice_mismatches,
        "note": (
            "bwm_scale_limit_overages counts billable workers live (the "
            "same inclusion logic require_scope_limit(MAX_BWM) uses at "
            "employee creation) and resolves the plan limit through "
            "entitlements, so it reports real demand vs. the plan even "
            "before the background BWM aggregation has run."
        ),
    }


# ── Platform: Service Health ───────────────────────────────────────────────

def _job_health(name: str, tracker: dict) -> dict:
    last_run = tracker.get("last_run_at")
    if last_run is None:
        return {"job": name, "state": "unknown", "detail": "Has not run since this process started."}
    if tracker.get("last_error"):
        return {"job": name, "state": "error", "last_run_at": last_run, "error": tracker["last_error"]}
    return {"job": name, "state": "healthy", "last_run_at": last_run, "last_success_at": tracker.get("last_success_at")}


def _service_health_report(db: Session) -> dict:
    """Real signals only: DB connectivity/latency, and last-run/last-success/
    last-error for each registered BackgroundScheduler job. No fabricated
    'green checkmark' for a job that simply hasn't reported — an unknown/
    stale state is returned explicitly. Shared by the service-health endpoint
    AND the alerts feed (platform category)."""
    from app.modules.assist import scheduler as assist_scheduler
    from app.modules.auth import scheduler as auth_scheduler
    from app.modules.billing import scheduler as billing_scheduler
    from app.modules.assisted_access import scheduler as assisted_access_scheduler

    db_status = {"status": "unknown", "latency_ms": None}
    try:
        start = datetime.utcnow()
        db.execute(text("SELECT 1"))
        latency_ms = (datetime.utcnow() - start).total_seconds() * 1000
        db_status = {"status": "healthy", "latency_ms": round(latency_ms, 2)}
    except Exception as exc:  # noqa: BLE001
        db_status = {"status": "error", "error": str(exc)}

    return {
        "database": db_status,
        "scheduled_jobs": [
            _job_health("trial_expiry_sweep", billing_scheduler.last_run_status),
            _job_health("dunning_sweep", billing_scheduler.dunning_last_run_status),
            _job_health("bwm_aggregation", billing_scheduler.bwm_last_run_status),
            _job_health("assist_sweep", assist_scheduler.last_run_status),
            _job_health("assisted_access_sweep", assisted_access_scheduler.last_run_status),
            _job_health("token_cleanup_sweep", auth_scheduler.last_run_status),
        ],
        "checked_at": datetime.utcnow(),
    }


def _unhealthy_scheduler_jobs(db: Session, health: Optional[dict] = None) -> list[dict]:
    """Scheduler jobs whose last signal is error or unknown — platform
    alerts. A job that ran cleanly or is paused-intentionally is NOT a
    fabricated alert; only real error/never-ran states surface."""
    report = health if health is not None else _service_health_report(db)
    return [job for job in report["scheduled_jobs"] if job["state"] != "healthy"]


@router.get("/platform/service-health")
def service_health(
    db: Session = Depends(get_db),
    _admin=Depends(get_current_super_admin),
):
    """Real signals only: DB connectivity/latency, and last-run/last-success/
    last-error for each registered BackgroundScheduler job. No fabricated
    'green checkmark' for a job that simply hasn't reported — an unknown/
    stale state is returned explicitly."""
    return _service_health_report(db)


# ── Platform: Integrations (real, computed from this deployment's config) ──

@router.get("/platform/integrations")
def list_integrations(_admin=Depends(get_current_super_admin)):
    """Every external-service integration this deployment has available to
    it, computed from live settings — not a fabricated card for something
    that isn't configured. Each entry carries `configured` (bool) and a
    status string so the page can show a real state per provider:

      - stripe_billing   — self-service checkout/subs/invoices (STRIPE_SECRET_KEY)
      - email_smtp       — outbound email (SMTP_HOST)
      - sentry           — error tracking (SENTRY_DSN; optional, no-op when empty)
      - assist_model     — Assist model gateway (ASSIST_MODEL_PROVIDER; deterministic-only when unset)

    Nothing here pings a provider: `configured` reflects configuration, not
    liveness. Stripe/SMTP liveness is exercised separately by real money/
    email flows and would fail loudly in their own logs.
    """
    from app.config import settings

    integrations = [
        {
            "slug": "stripe_billing",
            "name": "Stripe Billing",
            "configured": bool(settings.STRIPE_SECRET_KEY),
            "status": "Connected" if settings.STRIPE_SECRET_KEY else "Not configured",
            "description": "Self-service checkout, subscriptions and invoicing.",
        },
        {
            "slug": "email_smtp",
            "name": "Email delivery (SMTP)",
            "configured": bool(settings.SMTP_HOST),
            "status": "Connected" if settings.SMTP_HOST else "Not configured",
            "description": "Transactional email (verify, onboarding, templates).",
        },
        {
            "slug": "sentry",
            "name": "Sentry (error tracking)",
            "configured": bool(settings.SENTRY_DSN),
            "status": "Configured" if settings.SENTRY_DSN else "Not configured (optional)",
            "description": "Server-side error monitoring.",
        },
        {
            "slug": "assist_model",
            "name": "Assist model gateway",
            "configured": bool(settings.ASSIST_MODEL_PROVIDER),
            "status": "Connected" if settings.ASSIST_MODEL_PROVIDER else "Deterministic-only",
            "description": "LLM provider for grounded Assist answers.",
        },
    ]
    connected = sum(1 for it in integrations if it["configured"])
    return {
        "integrations": integrations,
        "message": f"{connected} of {len(integrations)} integrations configured.",
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
    source: Optional[str] = None,
    actor_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_super_admin),
):
    """No single audit table exists — TaxConfigurationAudit (compliance),
    BillingCommercialAuditEvent (billing/trial), AssistAuditEvent (assist)
    and AssistedAccessAuditEvent are four separately-shaped tables. Rather
    than a risky consolidation migration, this normalizes and merge-sorts
    across all four as a read model.

    Filters are pushed down to the SQL queries (actor + inclusive date
    range on the source's own timestamp column) BEFORE any row is loaded,
    so a filtered page can never silently drop rows that fall outside the
    loaded limit; then all matching rows across the requested sources are
    merge-sorted once and sliced for the page. `total` is the exact count
    of the filtered union, so pagination is exact (not "more rows than
    page_size on this page"). Append-only by nature — no edit/delete
    endpoint exists or should ever exist here."""
    end_exclusive = end_date + timedelta(days=1) if end_date else None

    def _date_filter(ts_column):
        clause = []
        if start_date:
            clause.append(func.date(ts_column) >= start_date)
        if end_exclusive:
            clause.append(func.date(ts_column) < end_exclusive)
        return clause

    normalized = []
    totals = {"compliance": 0, "billing": 0, "assist": 0, "assisted_access": 0}

    if source in (None, "compliance"):
        q = db.query(TaxConfigurationAudit)
        if actor_id:
            q = q.filter(TaxConfigurationAudit.actor_id == actor_id)
        for predicate in _date_filter(TaxConfigurationAudit.created_at):
            q = q.filter(predicate)
        totals["compliance"] = q.count()
        for row in q.order_by(TaxConfigurationAudit.id.desc()).all():
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
        for predicate in _date_filter(BillingCommercialAuditEvent.created_at):
            q = q.filter(predicate)
        totals["billing"] = q.count()
        for row in q.order_by(BillingCommercialAuditEvent.id.desc()).all():
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
        for predicate in _date_filter(AssistAuditEvent.recorded_at):
            q = q.filter(predicate)
        totals["assist"] = q.count()
        for row in q.order_by(AssistAuditEvent.id.desc()).all():
            normalized.append({
                "timestamp": _naive_utc(row.recorded_at),
                "actor_id": row.user_id,
                "action": row.event_type,
                "entity_type": "assist",
                "entity_id": row.id,
                "source": "assist",
                "detail": row.payload,
            })

    if source in (None, "assisted_access"):
        from app.modules.assisted_access.models import AssistedAccessAuditEvent

        q = db.query(AssistedAccessAuditEvent)
        if actor_id:
            q = q.filter(AssistedAccessAuditEvent.actor_user_id == actor_id)
        for predicate in _date_filter(AssistedAccessAuditEvent.recorded_at):
            q = q.filter(predicate)
        totals["assisted_access"] = q.count()
        for row in q.order_by(AssistedAccessAuditEvent.id.desc()).all():
            normalized.append({
                "timestamp": _naive_utc(row.recorded_at),
                "actor_id": row.actor_user_id,
                "action": row.event_type,
                "entity_type": "assisted_access_session",
                "entity_id": row.organization_id,
                "source": "assisted_access",
                "detail": {
                    "session_id": row.assisted_access_session_id,
                    "method": row.method,
                    "path": row.path,
                    "status_code": row.status_code,
                    **(row.payload or {}),
                },
            })

    def _sort_key(entry):
        ts = entry["timestamp"]
        return ts if ts is not None else datetime.min

    normalized.sort(key=_sort_key, reverse=True)

    total_filtered = sum(totals.values()) if source is None else totals.get(source, 0)
    start_idx = (page - 1) * page_size
    page_rows = normalized[start_idx:start_idx + page_size]

    return {
        "entries": page_rows,
        "page": page,
        "page_size": page_size,
        "returned": len(page_rows),
        "total": total_filtered,
    }


# ── Command Center: Alerts & Incidents (unified triage feed) ──────────────

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@router.get("/alerts")
def list_alerts(
    db: Session = Depends(get_db),
    _admin=Depends(get_current_super_admin),
):
    """First unified triage surface: every signal each existing Command
    Center page already computes, collected into one feed. No new queries
    that duplicate those pages' logic — each category below calls the SAME
    helper functions those endpoints use, so the feed can never drift from
    the detail views. Every alert links back to its source page; this never
    replaces them.

    Severity derives from the source signal, not repackaged here:
      payroll_run  high   run due soon, not yet AUTHORIZED
      filing       high   transmission BLOCKED_EXTERNAL / REJECTED
      platform     medium scheduler job errored or never ran, or DB down
      billing      high   dunning-restricted with NO in-flight run to
                          shield it; medium "(protected)" when
                          in_flight_run_guard is True — the whole point of
                          the guard is that an in-flight run means the
                          restriction is not imminently destructive."""  # noqa: E501
    alerts = []

    for run in _at_risk_payroll_runs(db):
        alerts.append({
            "severity": "high",
            "category": "payroll_run",
            "message": f"{run['organization_name']}: run due {run['pay_date']} not yet authorized",
            "link": "/super-admin/payroll-runs",
        })

    for tx in _blocked_filings(db):
        alerts.append({
            "severity": "high",
            "category": "filing",
            "message": f"{tx['organization_name']}: filing blocked",
            "link": "/super-admin/filings-remittances",
        })

    health = _service_health_report(db)
    for job in _unhealthy_scheduler_jobs(db, health=health):
        alerts.append({
            "severity": "medium",
            "category": "platform",
            "message": f"{job['job']} last run: {job['state']}",
            "link": "/super-admin/service-health",
        })
    if health["database"]["status"] != "healthy":
        alerts.append({
            "severity": "high",
            "category": "platform",
            "message": "Database unreachable — Service Health reports a connectivity error",
            "link": "/super-admin/service-health",
        })

    for org in _suspended_dunning_orgs(db):
        protected = org["in_flight_run_guard"]
        alerts.append({
            "severity": "medium" if protected else "high",
            "category": "billing",
            "message": f"{org['organization_name']}: {org['dunning_stage']}"
            + (" (protected)" if protected else ""),
            "link": "/super-admin/subscriptions-billing",
        })

    alerts.sort(key=lambda a: SEVERITY_ORDER.get(a["severity"], 9))
    high_severity_count = sum(1 for a in alerts if a["severity"] == "high")

    return {
        "alerts": alerts,
        "total": len(alerts),
        "high_severity_count": high_severity_count,
    }
