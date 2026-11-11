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
from app.modules.billing import jurisdiction_entitlement
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
    country_limit: Optional[str] = Query(None, description="'OVER' for organizations with OVER_LIMIT countries or more countries than their plan allows"),
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

        # Country entitlement usage (billing/jurisdiction_entitlement.py).
        country_usage = jurisdiction_entitlement.org_country_usage(db, org.id)
        if country_limit == "OVER":
            limit_value = country_usage["countries_limit"]
            over = country_usage["countries_over_limit"] > 0 or (
                limit_value is not None and country_usage["countries_used"] > limit_value
            )
            if not over:
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
                **country_usage,
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
            **country_usage,
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


def _payroll_run_aggregates(db: Session, status: Optional[str], at_risk_window_days: int) -> dict:
    """ZP-PRIV B.1: run monitoring as platform aggregates only — counts of
    runs and of organizations per jurisdiction and status. No run row, run
    code, organization name, pay date, headcount or money ever leaves here:
    those are a tenant's own payroll workflow."""
    jurisdictions = dict(
        db.query(CompanyComplianceDetails.organization_id, CompanyComplianceDetails.jurisdiction_country).all()
    )
    q = db.query(PayrollRun.organization_id, PayrollRun.status, PayrollRun.pay_date)
    if status:
        q = q.filter(PayrollRun.status == status)
    today = date.today()
    cutoff = today + timedelta(days=at_risk_window_days)
    cells: dict = {}
    at_risk_runs, at_risk_orgs = 0, set()
    for org_id, run_status, pay_date in q.all():
        country = ((jurisdictions.get(org_id) or "").strip().upper()) or "UNASSIGNED"
        cell = cells.setdefault((country, run_status), {"runs": 0, "orgs": set()})
        cell["runs"] += 1
        cell["orgs"].add(org_id)
        if run_status in AT_RISK_STATUSES and pay_date is not None and pay_date <= cutoff:
            at_risk_runs += 1
            at_risk_orgs.add(org_id)
    by_status = [
        {"jurisdiction": country, "status": run_status, "run_count": c["runs"],
         "organization_count": len(c["orgs"])}
        for (country, run_status), c in sorted(cells.items())
    ]
    return {
        "by_status": by_status,
        "at_risk": {"run_count": at_risk_runs, "organization_count": len(at_risk_orgs)},
        "at_risk_window_days": at_risk_window_days,
    }


@router.get("/payroll/runs")
def list_all_payroll_runs(
    status: Optional[str] = Query(None),
    at_risk_window_days: int = Query(5, ge=1, le=60),
    db: Session = Depends(get_db),
    _admin=Depends(get_current_super_admin),
):
    """Cross-tenant payroll run monitor (ZP-PRIV B.1): counts by
    jurisdiction and status, plus how many runs (across how many
    organizations) are due soon and not yet authorized. Individual runs are
    a tenant's own workflow and are visible only inside that tenant, or to
    Zoiko support through an approved JIT Support Access grant."""
    out = _payroll_run_aggregates(db, status, at_risk_window_days)
    out["privacy_note"] = ("Individual payroll runs are tenant data. Use Support Access with the "
                           "tenant's approval to look at a specific run.")
    return out


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
                "label": CODE_TO_COUNTRY_NAME.get(code) or CODE_TO_COUNTRY_NAME.get({"GB": "UK"}.get(code, ""), code),
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
    """Cross-tenant statutory filing coverage as platform aggregates
    (ZP-PRIV B.1): per jurisdiction, how many organizations are configured,
    how many filing records exist, how many are blocked and across how many
    organizations. Individual filings, periods and organization names stay
    in each tenant (/api/payroll/filings)."""
    jurisdictions, unconfigured = _load_org_filing_coverage(db)
    summary = {}
    for code, section in jurisdictions.items():
        blocked_orgs = sum(
            1 for org in section["organizations"]
            if any(f["status"] in BLOCKED_FILING_STATUSES for f in org["filings"])
        )
        orgs_without_records = sum(1 for org in section["organizations"] if not org["filings"])
        summary[code] = {
            "label": section["label"],
            "total": section["total"],
            "blocked_count": section["blocked_count"],
            "total_orgs": section["total_orgs"],
            "orgs_with_blocked_filings": blocked_orgs,
            "orgs_without_filing_records": orgs_without_records,
        }
    return {
        "jurisdictions": summary,
        "unconfigured_count": len(unconfigured),
        "known_gaps": [
            "Bank-export/remittance file generation has no persisted status "
            "model yet — only on-demand file generation. Not represented here."
        ],
        "privacy_note": "Individual filings are tenant data and are recorded by each organization.",
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
    # ZP-PRIV B.1: stuck runs are a tenant's own workflow - reported as
    # counts only (no run, organization name, period or date).
    cutoff = datetime.utcnow() - timedelta(days=stuck_review_days)
    stuck_run_count, stuck_orgs = 0, set()
    for run in db.query(PayrollRun).filter(PayrollRun.status == PayrollStatus.REVIEW.value).all():
        # Postgres returns tz-aware timestamps, SQLite naive ones: compare
        # both as naive UTC (comparing mixed kinds raised a 500 in prod).
        marker = _naive_utc(getattr(run, "updated_at", None) or getattr(run, "created_at", None))
        if marker is not None and marker <= cutoff:
            stuck_run_count += 1
            stuck_orgs.add(run.organization_id)

    current_month_start = date.today().replace(day=1)
    bwm_overages = _load_bwm_scale_limit_overages(db, current_month_start)

    # Step 3 / Part 7 — any invoice whose BWM-priced line quantity doesn't
    # match the actual counted BillingWorkerMonthRecord rows for that org/
    # month is a real billing bug. Folded into this existing page rather
    # than a second, separate reconciliation view — this is the one home
    # for "two systems that don't otherwise talk to each other disagree."
    from app.modules.billing.invoice_explanation import find_bwm_invoice_discrepancies

    bwm_invoice_mismatches = find_bwm_invoice_discrepancies(db)

    # Country entitlement: orgs with paused (OVER_LIMIT) countries, more
    # countries than their plan allows, or employees in a country that isn't
    # entitled. Per-country employee counts only, no employee rows.
    country_limit_exceptions = jurisdiction_entitlement.find_country_limit_exceptions(db)

    return {
        "stuck_reviews": {"run_count": stuck_run_count, "organization_count": len(stuck_orgs),
                          "older_than_days": stuck_review_days},
        "bwm_scale_limit_overages": bwm_overages,
        "bwm_invoice_mismatches": bwm_invoice_mismatches,
        "country_limit_exceptions": country_limit_exceptions,
        "note": (
            "Plan-limit checks count billable workers live, the same way new employees are checked "
            "against the plan, so they show real demand even before the monthly billing count has run."
        ),
    }


# ── Platform: Service Health ───────────────────────────────────────────────

def _z(ts: Optional[datetime]) -> Optional[str]:
    """UTC timestamp with an explicit Z (naive values are UTC by convention)."""
    if ts is None:
        return None
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts.replace(microsecond=0).isoformat() + "Z"


# job key -> (label, what it does)
_JOB_INFO = {
    "trial_expiry_sweep": ("Trial expiry sweep", "Moves expired trials into grace and closes lapsed ones."),
    "dunning_sweep": ("Dunning sweep", "Retries failed payments and sends payment reminders."),
    "bwm_aggregation": ("Billable-worker aggregation", "Computes monthly billable workers per organization."),
    "assist_sweep": ("Assist maintenance", "Knowledge expiry and Assist retention clean-up."),
    "support_access_sweep": ("Support access sweep", "Ends expired support grants and escalates overdue reviews."),
    "token_cleanup_sweep": ("Token clean-up", "Removes expired revoked tokens and one-time links."),
}


def _job_interval_seconds(name: str) -> int:
    from app.config import settings

    return {
        "trial_expiry_sweep": settings.TRIAL_SWEEP_INTERVAL_HOURS * 3600,
        "dunning_sweep": settings.DUNNING_SWEEP_INTERVAL_HOURS * 3600,
        "bwm_aggregation": settings.BWM_AGGREGATION_INTERVAL_HOURS * 3600,
        "assist_sweep": settings.ASSIST_SWEEP_INTERVAL_HOURS * 3600,
        "support_access_sweep": settings.SUPPORT_ACCESS_SWEEP_INTERVAL_SECONDS,
        "token_cleanup_sweep": settings.TOKEN_CLEANUP_SWEEP_INTERVAL_HOURS * 3600,
    }.get(name, 86400)


def _job_health(name: str, tracker: dict, now: Optional[datetime] = None) -> dict:
    """unknown (never ran in this process / missed its schedule) / error (last
    run failed) / healthy. The service-health contract only allows
    {"unknown", "healthy", "error"} - a job that missed its schedule is
    normalized to "unknown" rather than surfacing a raw "stale" value."""
    now = now or datetime.utcnow()
    label, description = _JOB_INFO.get(name, (name.replace("_", " ").capitalize(), ""))
    interval = _job_interval_seconds(name)
    last_run = tracker.get("last_run_at")
    base = {"job": name, "label": label, "description": description, "interval_seconds": interval,
            "last_run_at": _z(last_run), "last_success_at": _z(tracker.get("last_success_at"))}
    if last_run is None:
        return {**base, "state": "unknown", "detail": "Has not run since this server process started."}
    if tracker.get("last_error"):
        return {**base, "state": "error", "error": str(tracker["last_error"])[:500]}
    if (now - last_run).total_seconds() > 2 * interval + 300:
        return {**base, "state": "unknown",
                "detail": "Has not run recently: last run is stale (the scheduler may have stopped)."}
    return {**base, "state": "healthy"}


def _service_health_report(db: Session) -> dict:
    """Real signals only: DB connectivity/latency, and last-run/last-success/
    last-error for each registered BackgroundScheduler job. No fabricated
    'green checkmark' for a job that simply hasn't reported — an unknown/
    stale state is returned explicitly. Shared by the service-health endpoint
    AND the alerts feed (platform category)."""
    from app.modules.assist import scheduler as assist_scheduler
    from app.modules.auth import scheduler as auth_scheduler
    from app.modules.billing import scheduler as billing_scheduler
    from app.modules.support_access import scheduler as support_access_scheduler

    db_status = {"status": "unknown", "latency_ms": None}
    try:
        start = datetime.utcnow()
        db.execute(text("SELECT 1"))
        latency_ms = (datetime.utcnow() - start).total_seconds() * 1000
        db_status = {"status": "healthy", "latency_ms": round(latency_ms, 2)}
    except Exception as exc:  # noqa: BLE001
        db_status = {"status": "error", "latency_ms": None, "error": type(exc).__name__}

    now = datetime.utcnow()
    jobs = [
        _job_health("trial_expiry_sweep", billing_scheduler.last_run_status, now),
        _job_health("dunning_sweep", billing_scheduler.dunning_last_run_status, now),
        _job_health("bwm_aggregation", billing_scheduler.bwm_last_run_status, now),
        _job_health("assist_sweep", assist_scheduler.last_run_status, now),
        _job_health("support_access_sweep", support_access_scheduler.last_run_status, now),
        _job_health("token_cleanup_sweep", auth_scheduler.last_run_status, now),
    ]
    summary = {s: sum(1 for j in jobs if j["state"] == s) for s in ("healthy", "error", "unknown")}
    if db_status["status"] != "healthy" or summary["error"]:
        overall = "error"
    elif summary["unknown"]:
        overall = "degraded"
    else:
        overall = "healthy"
    return {
        "overall": overall,
        "database": db_status,
        "scheduled_jobs": jobs,
        "summary": summary,
        "checked_at": _z(now),
    }


def _unhealthy_scheduler_jobs(db: Session, health: Optional[dict] = None) -> list[dict]:
    """Scheduler jobs whose last signal is error, stale or unknown — platform
    alerts. A job that ran cleanly is NOT a fabricated alert; only real
    error / missed-schedule / never-ran states surface."""
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

def _integration(slug, name, category, configured, status, description, optional=False):
    return {"slug": slug, "name": name, "category": category, "configured": bool(configured),
            "optional": optional, "status": status, "description": description}


@router.get("/platform/integrations")
def list_integrations(_admin=Depends(get_current_super_admin)):
    """Every external-service integration this deployment uses, computed from
    live settings. ``configured`` reflects configuration, not liveness —
    nothing here pings a provider, and no secret or URL is ever returned."""
    from app.config import settings
    from app.core import outbound

    stripe_key = settings.STRIPE_SECRET_KEY or ""
    stripe_mode = "live" if stripe_key.startswith(("sk_live_", "rk_live_")) else "test" if stripe_key else None
    real_email = outbound.real_delivery_allowed("email")
    integrations = [
        _integration("stripe_billing", "Stripe billing", "Payments", stripe_key,
                     f"Connected ({stripe_mode} mode)" if stripe_key else "Not configured",
                     "Self-service checkout, subscriptions and invoicing."),
        _integration("stripe_webhooks", "Stripe webhooks", "Payments", settings.STRIPE_WEBHOOK_SECRET,
                     "Signing secret set" if settings.STRIPE_WEBHOOK_SECRET else "No signing secret",
                     "Verified payment and subscription events from Stripe."),
        _integration("email_smtp", "Email delivery (SMTP)", "Messaging", settings.SMTP_HOST,
                     ("Connected" if real_email else "Configured (delivery blocked in this environment)")
                     if settings.SMTP_HOST else "Not configured",
                     "Transactional email: verification, onboarding, payslips, notices."),
        _integration("security_alert_email", "Security alert recipients", "Security",
                     settings.SECURITY_ALERT_EMAILS,
                     f"{len([e for e in settings.SECURITY_ALERT_EMAILS.split(',') if e.strip()])} recipient(s)"
                     if settings.SECURITY_ALERT_EMAILS else "Console only",
                     "Where security alerts are emailed in addition to the Alerts page.", optional=True),
        _integration("job_queue", "Background job queue (Redis / Celery)", "Infrastructure", settings.REDIS_URL,
                     "Configured" if settings.REDIS_URL else "Not configured (jobs run in-process)",
                     "Parallel payslip generation and other background work.", optional=True),
        _integration("audit_anchor", "Audit anchoring bucket", "Security", settings.SECURITY_ANCHOR_BUCKET,
                     "Configured" if settings.SECURITY_ANCHOR_BUCKET else "Not configured",
                     "Retention-locked storage for the security-log hash anchors.", optional=True),
        _integration("sentry", "Sentry (error tracking)", "Monitoring", settings.SENTRY_DSN,
                     "Configured" if settings.SENTRY_DSN else "Not configured (optional)",
                     "Server-side error monitoring (personal data scrubbed before sending).", optional=True),
        _integration("assist_model", "Assist model gateway", "AI", settings.ASSIST_MODEL_PROVIDER,
                     "Connected" if settings.ASSIST_MODEL_PROVIDER else "Deterministic answers only",
                     "LLM provider for grounded Assist answers (identities masked before sending).", optional=True),
        _integration("zoiko_one", "Zoiko One sign-in (federation)", "Identity", settings.FEDERATION_ISSUER,
                     "Configured" if settings.FEDERATION_ISSUER else "Not configured (integration pending)",
                     "Single sign-on from Zoiko One, limited to the user's own organization.", optional=True),
    ]
    required = [it for it in integrations if not it["optional"]]
    connected = sum(1 for it in integrations if it["configured"])
    missing_required = [it["name"] for it in required if not it["configured"]]
    return {
        "integrations": integrations,
        "summary": {"configured": connected, "total": len(integrations), "missingRequired": missing_required},
        "message": f"{connected} of {len(integrations)} integrations configured.",
        "checked_at": _z(datetime.utcnow()),
    }


# ── Platform: Security & Audit (merged read model across the audit tables) ──

def _naive_utc(ts: Optional[datetime]) -> Optional[datetime]:
    """The source tables mix tz-aware and tz-naive columns; normalize to
    naive UTC so every entry sorts on the same basis."""
    if ts is None:
        return None
    if ts.tzinfo is not None:
        return ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts


AUDIT_SOURCES = {
    "compliance": "Compliance configuration",
    "billing": "Billing",
    "support_access": "Support access",
    "assist": "Assist",
    "assisted_access": "Assisted access (retired)",
}


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
    """Platform audit trail merged across the append-only audit tables
    (compliance configuration, billing, support access, Assist and the
    retired Assisted Access). Metadata only: no tenant payloads, request
    paths or worker values reach the platform plane.

    Filters are pushed down to SQL. Each source loads only its newest
    ``page * page_size`` matching rows (enough for an exact merge of the
    requested page); ``total`` is the exact count of the filtered union."""
    from app.core.exceptions import BadRequestException

    if source and source not in AUDIT_SOURCES:
        raise BadRequestException(f"Unknown source. Use one of: {', '.join(AUDIT_SOURCES)}.")
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    need = page * page_size
    end_exclusive = end_date + timedelta(days=1) if end_date else None

    def _filtered(q, ts_column, actor_column):
        if actor_id:
            q = q.filter(actor_column == actor_id)
        if start_date:
            q = q.filter(func.date(ts_column) >= start_date)
        if end_exclusive:
            q = q.filter(func.date(ts_column) < end_exclusive)
        return q

    normalized = []
    totals = {key: 0 for key in AUDIT_SOURCES}

    if source in (None, "compliance"):
        from app.modules.payroll.service import platform_audit_filter

        # ZP-PRIV B.1: platform configuration changes only; tenant/worker
        # audit rows never reach the platform plane.
        q = _filtered(platform_audit_filter(db.query(TaxConfigurationAudit)),
                      TaxConfigurationAudit.created_at, TaxConfigurationAudit.actor_id)
        totals["compliance"] = q.count()
        for row in q.order_by(TaxConfigurationAudit.created_at.desc()).limit(need).all():
            normalized.append({
                "timestamp": _naive_utc(row.created_at), "actor_id": row.actor_id, "action": row.action,
                "entity_type": row.entity_type, "entity_id": row.entity_id, "organization_id": None,
                "source": "compliance",
                "detail": {"reason": row.reason, "old_value": row.old_value, "new_value": row.new_value},
            })

    if source in (None, "billing"):
        q = _filtered(db.query(BillingCommercialAuditEvent), BillingCommercialAuditEvent.created_at,
                      BillingCommercialAuditEvent.actor_user_id)
        totals["billing"] = q.count()
        for row in q.order_by(BillingCommercialAuditEvent.created_at.desc()).limit(need).all():
            normalized.append({
                "timestamp": _naive_utc(row.created_at), "actor_id": row.actor_user_id, "action": row.event_type,
                "entity_type": "billing_subscription", "entity_id": row.organization_id,
                "organization_id": row.organization_id, "source": "billing", "detail": row.payload,
            })

    if source in (None, "support_access"):
        from app.modules.support_access.models import SupportAccessAuditEvent

        q = _filtered(db.query(SupportAccessAuditEvent), SupportAccessAuditEvent.recorded_at,
                      SupportAccessAuditEvent.actor_user_id)
        totals["support_access"] = q.count()
        for row in q.order_by(SupportAccessAuditEvent.recorded_at.desc()).limit(need).all():
            normalized.append({
                "timestamp": _naive_utc(row.recorded_at), "actor_id": row.actor_user_id, "action": row.event_type,
                "entity_type": "support_grant", "entity_id": row.grant_id, "organization_id": row.organization_id,
                "source": "support_access",
                # Who acted and on whose behalf; never request paths or values.
                "detail": {"actor_role": row.actor_role, "requested_by_user_id": row.requested_by_user_id},
            })

    if source in (None, "assist"):
        q = _filtered(db.query(AssistAuditEvent), AssistAuditEvent.recorded_at, AssistAuditEvent.user_id)
        totals["assist"] = q.count()
        for row in q.order_by(AssistAuditEvent.recorded_at.desc()).limit(need).all():
            normalized.append({
                "timestamp": _naive_utc(row.recorded_at), "actor_id": row.user_id, "action": row.event_type,
                "entity_type": "assist", "entity_id": row.id, "organization_id": row.organization_id,
                "source": "assist",
                # The payload can quote a tenant user's question; event only.
                "detail": {},
            })

    if source in (None, "assisted_access"):
        from app.modules.assisted_access.models import AssistedAccessAuditEvent

        q = _filtered(db.query(AssistedAccessAuditEvent), AssistedAccessAuditEvent.recorded_at,
                      AssistedAccessAuditEvent.actor_user_id)
        totals["assisted_access"] = q.count()
        for row in q.order_by(AssistedAccessAuditEvent.recorded_at.desc()).limit(need).all():
            normalized.append({
                "timestamp": _naive_utc(row.recorded_at), "actor_id": row.actor_user_id, "action": row.event_type,
                "entity_type": "assisted_access_session", "entity_id": row.organization_id,
                "organization_id": row.organization_id, "source": "assisted_access",
                # Request paths name tenant objects: kept in the tenant's view.
                "detail": {"session_id": row.assisted_access_session_id, "method": row.method,
                           "status_code": row.status_code},
            })

    normalized.sort(key=lambda e: e["timestamp"] or datetime.min, reverse=True)
    start_idx = (page - 1) * page_size
    page_rows = normalized[start_idx:start_idx + page_size]
    for entry in page_rows:
        entry["timestamp"] = _z(entry["timestamp"])
    total_filtered = sum(totals.values()) if source is None else totals.get(source, 0)
    return {
        "entries": page_rows,
        "page": page,
        "page_size": page_size,
        "returned": len(page_rows),
        "total": total_filtered,
        "totals_by_source": totals,
        "sources": [{"key": k, "label": v} for k, v in AUDIT_SOURCES.items()],
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

    # ZP-PRIV B.1: tenant workflow signals are reported as counts only —
    # never an organization name, a pay date or a filing.
    at_risk = _at_risk_payroll_runs(db)
    if at_risk:
        orgs = len({r["organization_id"] for r in at_risk})
        alerts.append({
            "severity": "high",
            "category": "payroll_run",
            "message": f"{len(at_risk)} payroll run(s) across {orgs} organization(s) are due soon and not yet authorized",
            "link": "/super-admin/payroll-runs",
        })

    blocked = _blocked_filings(db)
    if blocked:
        orgs = len({f["organization_id"] for f in blocked})
        alerts.append({
            "severity": "high",
            "category": "filing",
            "message": f"{len(blocked)} filing(s) across {orgs} organization(s) are blocked",
            "link": "/super-admin/filings-remittances",
        })

    health = _service_health_report(db)
    for job in _unhealthy_scheduler_jobs(db, health=health):
        alerts.append({
            "severity": "medium",
            "category": "platform",
            "message": f"{job.get('label', job['job'])}: {job['state']}",
            "link": "/super-admin/service-health",
        })
    if health["database"]["status"] != "healthy":
        alerts.append({
            "severity": "high",
            "category": "platform",
            "message": "Database unreachable — Service Health reports a connectivity error",
            "link": "/super-admin/service-health",
        })

    # ZP-PRIV Part D: open break-glass access and overdue post-incident
    # reviews are high-severity security alerts.
    from app.modules.support_access import models as support_models

    for grant in (db.query(support_models.SupportAccessGrant)
                  .filter(support_models.SupportAccessGrant.is_break_glass.is_(True),
                          support_models.SupportAccessGrant.reviewed_at.is_(None)).all()):
        overdue = grant.review_due_at is not None and grant.review_due_at <= datetime.utcnow()
        alerts.append({
            "severity": "high",
            "category": "security",
            "message": (f"Break-glass access #{grant.id}: post-incident review overdue" if overdue
                        else f"Break-glass access #{grant.id} is waiting for its independent review"),
            "link": "/super-admin/support-access?tab=reviews",
        })

    from app.modules.assisted_access.service import break_glass_notification_alerts

    for bg in break_glass_notification_alerts(db):
        alerts.append({
            "severity": "high",
            "category": "security",
            "message": f"{bg['organization_name']}: break-glass session #{bg['session_id']} — tenant notification "
                       "FAILED; notify the tenant manually and record it",
            "link": "/super-admin/security-audit",
        })

    from app.modules.assisted_access.service import assisted_audit_gap_alerts

    for gap in assisted_audit_gap_alerts(db):
        alerts.append({
            "severity": "high",
            "category": "security",
            "message": f"Assisted-access session #{gap['session_id']}: {gap['unmatched_starts']} request(s) started but "
                       "their completion audit row is missing; review the session's audit trail",
            "link": "/super-admin/security-audit",
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
