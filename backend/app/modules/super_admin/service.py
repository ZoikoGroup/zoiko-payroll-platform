"""
modules/super_admin/service.py
-------------------------------
Cross-organization aggregation for Super Admin Finance, Reports, and
Dashboard charts.

Reuses the existing PayrollRun / PayslipItem / PayrollEmployee /
Organization / CompanyComplianceDetails / JurisdictionPack models exactly
as they are — every other payroll aggregation endpoint
(app.modules.payroll.service.get_dashboard_summary/_trend/_breakdowns) is
deliberately single-organization-scoped (that's the whole product for an
org admin), so there is nothing to "extend" for a cross-org view; grouping
by organization/jurisdiction across the whole platform is genuinely new
and lives here, not duplicated per-module.

Currency-safety: nothing in this file sums monetary values across
different jurisdictions/currencies. Aggregates are always grouped by
`jurisdiction_country` first; the frontend (which already owns the full
country -> currency mapping in utils/currency.js) is responsible for
formatting each group with its correct currency symbol.
"""

from datetime import date, timedelta
from typing import Optional, List

from sqlalchemy.orm import Session
from sqlalchemy import func as sa_func, or_

from app.modules.payroll.models import (
    PayrollRun, PayrollEmployee, CompanyComplianceDetails, JurisdictionPack, ContributionRate, PayrollStatus,
)
from app.modules.organizations.models import Organization
from app.core.exceptions import NotFoundException


def _date_filter(query, column, start_date: Optional[date], end_date: Optional[date]):
    if start_date:
        query = query.filter(column >= start_date)
    if end_date:
        # `column` is a timestamp; comparing it `<=` a bare date casts that
        # date to midnight (00:00:00), excluding every row touched later
        # the SAME day (e.g. "end_date = today" would hide a row updated
        # at 6pm today). Use the start of the following day instead so the
        # whole end_date is actually included.
        query = query.filter(column < end_date + timedelta(days=1))
    return query


# ── Finance ──────────────────────────────────────────────────────────────

def finance_overview(
    db: Session, organization_id: Optional[int] = None, country: Optional[str] = None,
    status: Optional[str] = None, start_date: Optional[date] = None, end_date: Optional[date] = None,
    skip: int = 0, limit: int = 50,
) -> dict:
    """Cross-org payroll run listing. Each row carries its own operating
    jurisdiction so the client can group/format currency correctly —
    amounts from different jurisdictions are never combined here."""
    query = (
        db.query(
            PayrollRun, Organization.organization_name, Organization.organization_code, Organization.currency,
            CompanyComplianceDetails.jurisdiction_country,
        )
        .join(Organization, Organization.id == PayrollRun.organization_id)
        .outerjoin(CompanyComplianceDetails, CompanyComplianceDetails.organization_id == Organization.id)
    )
    if organization_id:
        query = query.filter(PayrollRun.organization_id == organization_id)
    if country:
        query = query.filter(CompanyComplianceDetails.jurisdiction_country == country)
    if status:
        query = query.filter(PayrollRun.status == status)
    query = _date_filter(query, PayrollRun.period_start, start_date, end_date)

    total = query.count()
    rows = query.order_by(PayrollRun.period_start.desc()).offset(skip).limit(limit).all()

    items = [
        {
            "id": run.id,
            "organizationId": run.organization_id,
            "organizationName": org_name,
            "organizationCode": org_code,
            "jurisdictionCountry": jurisdiction,
            "currency": org_currency,
            "periodLabel": run.period_label,
            "periodStart": run.period_start,
            "periodEnd": run.period_end,
            "payDate": run.pay_date,
            "status": run.status,
            "grossPay": run.total_gross,
            "netPay": run.total_net,
            "totalDeductions": run.total_deductions,
            "totalTaxes": run.total_taxes,
            "employerCost": run.total_employer_contribution,
            "employeeCount": run.employee_count,
        }
        for run, org_name, org_code, org_currency, jurisdiction in rows
    ]
    return {"items": items, "total": total}


def finance_summary(
    db: Session, organization_id: Optional[int] = None, country: Optional[str] = None,
    start_date: Optional[date] = None, end_date: Optional[date] = None,
) -> dict:
    """Financial totals grouped by jurisdiction country — the only
    currency-safe way to aggregate across organizations. Also returns
    currency-agnostic platform counts (orgs, runs, pending/completed)."""
    grouped = (
        db.query(
            CompanyComplianceDetails.jurisdiction_country.label("country"),
            sa_func.count(sa_func.distinct(PayrollRun.organization_id)).label("org_count"),
            sa_func.count(PayrollRun.id).label("run_count"),
            sa_func.coalesce(sa_func.sum(PayrollRun.total_gross), 0).label("gross"),
            sa_func.coalesce(sa_func.sum(PayrollRun.total_net), 0).label("net"),
            sa_func.coalesce(sa_func.sum(PayrollRun.total_deductions), 0).label("deductions"),
            sa_func.coalesce(sa_func.sum(PayrollRun.total_employer_contribution), 0).label("employer_cost"),
        )
        .select_from(PayrollRun)
        .outerjoin(CompanyComplianceDetails, CompanyComplianceDetails.organization_id == PayrollRun.organization_id)
    )
    if organization_id:
        grouped = grouped.filter(PayrollRun.organization_id == organization_id)
    if country:
        grouped = grouped.filter(CompanyComplianceDetails.jurisdiction_country == country)
    grouped = _date_filter(grouped, PayrollRun.period_start, start_date, end_date)
    rows = grouped.group_by(CompanyComplianceDetails.jurisdiction_country).all()

    by_country = [
        {
            "country": r.country or "Unassigned",
            "organizations": r.org_count,
            "payrollRuns": r.run_count,
            "grossPay": r.gross,
            "netPay": r.net,
            "totalDeductions": r.deductions,
            "employerCost": r.employer_cost,
        }
        for r in rows
    ]

    status_query = db.query(PayrollRun.status, sa_func.count(PayrollRun.id))
    if organization_id:
        status_query = status_query.filter(PayrollRun.organization_id == organization_id)
    if country:
        status_query = status_query.join(
            CompanyComplianceDetails, CompanyComplianceDetails.organization_id == PayrollRun.organization_id
        ).filter(CompanyComplianceDetails.jurisdiction_country == country)
    status_query = _date_filter(status_query, PayrollRun.period_start, start_date, end_date)
    status_counts = dict(status_query.group_by(PayrollRun.status).all())
    pending = sum(
        v for k, v in status_counts.items()
        if k in (PayrollStatus.REVIEW.value, PayrollStatus.APPROVED.value, PayrollStatus.AUTHORIZED.value)
    )
    completed = status_counts.get(PayrollStatus.PAID.value, 0) + status_counts.get(PayrollStatus.CLOSED.value, 0)

    org_count_query = db.query(sa_func.count(sa_func.distinct(PayrollRun.organization_id)))
    if organization_id:
        org_count_query = org_count_query.filter(PayrollRun.organization_id == organization_id)
    org_count_query = _date_filter(org_count_query, PayrollRun.period_start, start_date, end_date)

    return {
        "byCountry": by_country,
        "totalOrganizations": org_count_query.scalar() or 0,
        "totalPayrollRuns": sum(status_counts.values()),
        "payrollsPending": pending,
        "payrollsCompleted": completed,
    }


def list_organization_currencies(db: Session) -> List[dict]:
    """Every organization (not just ones with payroll runs) plus its
    jurisdiction and any explicit currency override — the data source for
    Finance's organization-currency management panel."""
    rows = (
        db.query(Organization, CompanyComplianceDetails.jurisdiction_country)
        .outerjoin(CompanyComplianceDetails, CompanyComplianceDetails.organization_id == Organization.id)
        .order_by(Organization.organization_name)
        .all()
    )
    return [
        {
            "id": org.id,
            "organizationName": org.organization_name,
            "organizationCode": org.organization_code,
            "country": org.country,
            "jurisdictionCountry": jurisdiction,
            "currency": org.currency,
        }
        for org, jurisdiction in rows
    ]


def update_organization_currency(db: Session, organization_id: int, currency: Optional[str]) -> Organization:
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise NotFoundException("Organization", organization_id)
    org.currency = currency.upper() if currency else None
    db.commit()
    db.refresh(org)
    return org


def list_known_jurisdictions(db: Session) -> List[dict]:
    """Countries the app already supports (app.core.jurisdiction — the
    single source of truth used by registration/compliance elsewhere),
    plus any state already in use by an org or a pack under that country.
    Reused, not hardcoded, per the task's explicit instruction."""
    from app.core.jurisdiction import ALL_CODE_TO_COUNTRY_NAME

    states_by_country: dict = {}
    for country, state in db.query(CompanyComplianceDetails.jurisdiction_country, CompanyComplianceDetails.jurisdiction_state):
        if country and state:
            states_by_country.setdefault(country, set()).add(state)
    for country, state in db.query(JurisdictionPack.jurisdiction_country, JurisdictionPack.jurisdiction_state):
        if country and state:
            states_by_country.setdefault(country, set()).add(state)

    return [
        {"code": code, "name": name, "states": sorted(states_by_country.get(code, []))}
        for code, name in sorted(ALL_CODE_TO_COUNTRY_NAME.items(), key=lambda kv: kv[1])
    ]


def get_jurisdiction_summary(db: Session) -> List[dict]:
    """Card-grid data for the jurisdiction-first Compliance / Statutory
    Rates pages — one row per country, built on the exact same source of
    truth list_known_jurisdictions() already uses (ALL_CODE_TO_COUNTRY_NAME
    + whatever states are actually in use), so a country only needs real
    data to "show up" as configured — no separate hardcoded list to extend
    when a new jurisdiction is added. Every count defaults to 0 and every
    optional value falls back to None (the frontend renders "N/A") rather
    than ever surfacing `undefined`."""
    from app.core.jurisdiction import get_jurisdiction_schema

    base = list_known_jurisdictions(db)

    def _count_by_country(query_col, *filters):
        q = db.query(query_col, sa_func.count()).filter(*filters).group_by(query_col)
        return dict(q.all())

    tax_counts = _count_by_country(
        JurisdictionPack.jurisdiction_country,
        JurisdictionPack.pack_type == "tax", JurisdictionPack.status == "Active",
    )
    policy_counts = _count_by_country(
        JurisdictionPack.jurisdiction_country,
        JurisdictionPack.pack_type == "policy", JurisdictionPack.status == "Active",
    )
    # Canonical (Super-Admin-owned) contribution-rate rows — the same data
    # the Statutory Rates page now displays. Previously counted the
    # now-removed GlobalStatutoryRate table, which the payroll engine never
    # actually read; this counts real, engine-facing canonical rows instead.
    rate_counts = _count_by_country(
        ContributionRate.jurisdiction_country, ContributionRate.organization_id.is_(None),
    )
    org_counts = dict(
        db.query(CompanyComplianceDetails.jurisdiction_country, sa_func.count(sa_func.distinct(CompanyComplianceDetails.organization_id)))
        .filter(CompanyComplianceDetails.jurisdiction_country.isnot(None))
        .group_by(CompanyComplianceDetails.jurisdiction_country)
        .all()
    )
    last_updated = dict(
        db.query(JurisdictionPack.jurisdiction_country, sa_func.max(JurisdictionPack.updated_at))
        .group_by(JurisdictionPack.jurisdiction_country)
        .all()
    )

    summaries = []
    for entry in base:
        code = entry["code"]
        schema = get_jurisdiction_schema(code)
        tax_n, policy_n, rate_n = tax_counts.get(code, 0), policy_counts.get(code, 0), rate_counts.get(code, 0)
        summaries.append({
            "code": code,
            "name": entry["name"],
            "states": entry["states"],
            "currency": (schema or {}).get("currency"),
            "taxPackCount": tax_n,
            "policyPackCount": policy_n,
            "statutoryRateCount": rate_n,
            "organizationCount": org_counts.get(code, 0),
            "lastUpdated": last_updated.get(code),
            "isConfigured": bool(tax_n or policy_n or rate_n),
        })
    return summaries


def list_compliance_configurations(db: Session, country: Optional[str] = None, search: Optional[str] = None) -> List[dict]:
    """Every organization's ACTUAL, currently-configured compliance setup
    (CompanyComplianceDetails — jurisdiction, pack label, tax identifiers),
    as opposed to the abstract JurisdictionPack policy templates listed by
    list_all_jurisdiction_packs(). This is what Super Admin reviews to
    decide which real, in-use configurations should be formalized into a
    versioned policy (see the Compliance page's "Create Policy" action,
    which pre-fills the policy form from one of these rows)."""
    query = (
        db.query(
            CompanyComplianceDetails, Organization.organization_name, Organization.organization_code,
            JurisdictionPack.pack_id, JurisdictionPack.version,
        )
        .join(Organization, Organization.id == CompanyComplianceDetails.organization_id)
        .outerjoin(JurisdictionPack, JurisdictionPack.id == CompanyComplianceDetails.active_pack_id)
    )
    if country:
        query = query.filter(CompanyComplianceDetails.jurisdiction_country == country)
    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(Organization.organization_name.ilike(like), CompanyComplianceDetails.compliance_pack.ilike(like))
        )
    rows = query.order_by(Organization.organization_name).all()

    return [
        {
            "organizationId": details.organization_id,
            "organizationName": org_name,
            "organizationCode": org_code,
            "jurisdictionCountry": details.jurisdiction_country or None,
            "jurisdictionState": details.jurisdiction_state or None,
            "compliancePack": details.compliance_pack or None,
            "taxIdentifiers": details.tax_identifiers,
            "isConfigured": details.configured_at is not None,
            "configuredAt": details.configured_at,
            "updatedAt": details.updated_at,
            "activePackId": details.active_pack_id,
            "activePolicyId": pack_id,
            "activePolicyVersion": version,
        }
        for details, org_name, org_code, pack_id, version in rows
    ]


def list_contribution_rates(
    db: Session, country: Optional[str] = None, organization_id: Optional[int] = None,
    start_date: Optional[date] = None, end_date: Optional[date] = None,
) -> List[dict]:
    """Every organization's ACTUAL, currently-configured contribution
    rates (ContributionRate — the org-scoped rows the payroll engine
    really reads), for Super Admin visibility alongside the canonical
    (organization_id IS NULL) platform defaults. Filterable by
    jurisdiction and by last-updated date range."""
    query = (
        db.query(ContributionRate, Organization.organization_name, Organization.organization_code)
        .join(Organization, Organization.id == ContributionRate.organization_id)
    )
    if country:
        query = query.filter(ContributionRate.jurisdiction_country == country)
    if organization_id:
        query = query.filter(ContributionRate.organization_id == organization_id)
    # updated_at is only set by an edit (onupdate=func.now(), no insert-time
    # default) — most rows are seeded and never touched again, so filtering
    # on updated_at alone would silently hide every one of them. Falls back
    # to created_at (always populated) for the "last changed" date instead.
    effective_date = sa_func.coalesce(ContributionRate.updated_at, ContributionRate.created_at)
    query = _date_filter(query, effective_date, start_date, end_date)
    rows = query.order_by(Organization.organization_name, ContributionRate.sort_order).all()

    return [
        {
            "id": r.id,
            "organizationId": r.organization_id,
            "organizationName": org_name,
            "organizationCode": org_code,
            "componentKey": r.component_key,
            "label": r.label,
            "employeeShare": r.employee_share,
            "employerShare": r.employer_share,
            "total": r.total,
            "employeeRatePct": r.employee_rate_pct,
            "employerRatePct": r.employer_rate_pct,
            "flatAmount": r.flat_amount,
            "jurisdictionCountry": r.jurisdiction_country,
            "updatedAt": r.updated_at or r.created_at,
        }
        for r, org_name, org_code in rows
    ]


# ── Reports ──────────────────────────────────────────────────────────────
# "Payroll" and "Compliance" report categories deliberately reuse
# finance_overview()/finance_summary() and
# payroll.service.list_all_jurisdiction_packs() respectively — see
# router.py — rather than re-querying the same tables a second way.
# Only "Organizations" and "Employees" need genuinely new cross-org
# aggregation (counts alongside identity fields) that nothing else exposes.

def reports_organizations(
    db: Session, search: Optional[str] = None, country: Optional[str] = None,
    status: Optional[str] = None, skip: int = 0, limit: int = 50,
) -> dict:
    query = db.query(Organization)
    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(Organization.organization_name.ilike(like), Organization.organization_code.ilike(like))
        )
    if country:
        query = query.filter(Organization.country.ilike(country))
    if status == "active":
        query = query.filter(Organization.is_active.is_(True))
    elif status == "inactive":
        query = query.filter(Organization.is_active.is_(False))

    total = query.count()
    orgs = query.order_by(Organization.organization_name).offset(skip).limit(limit).all()
    org_ids = [o.id for o in orgs]

    emp_counts = dict(
        db.query(PayrollEmployee.organization_id, sa_func.count(PayrollEmployee.id))
        .filter(PayrollEmployee.organization_id.in_(org_ids))
        .group_by(PayrollEmployee.organization_id)
        .all()
    ) if org_ids else {}
    run_counts = dict(
        db.query(PayrollRun.organization_id, sa_func.count(PayrollRun.id))
        .filter(PayrollRun.organization_id.in_(org_ids))
        .group_by(PayrollRun.organization_id)
        .all()
    ) if org_ids else {}
    jurisdictions = dict(
        db.query(CompanyComplianceDetails.organization_id, CompanyComplianceDetails.jurisdiction_country)
        .filter(CompanyComplianceDetails.organization_id.in_(org_ids))
        .all()
    ) if org_ids else {}

    items = [
        {
            "id": o.id,
            "organizationName": o.organization_name,
            "organizationCode": o.organization_code,
            "country": o.country,
            "jurisdictionCountry": jurisdictions.get(o.id),
            "isActive": o.is_active,
            "createdAt": o.created_at,
            "employeeCount": emp_counts.get(o.id, 0),
            "payrollRunCount": run_counts.get(o.id, 0),
        }
        for o in orgs
    ]
    return {"items": items, "total": total}


def reports_employees(
    db: Session, organization_id: Optional[int] = None, country: Optional[str] = None,
    status: Optional[str] = None, search: Optional[str] = None, skip: int = 0, limit: int = 50,
) -> dict:
    query = (
        db.query(PayrollEmployee, Organization.organization_name, CompanyComplianceDetails.jurisdiction_country)
        .join(Organization, Organization.id == PayrollEmployee.organization_id)
        .outerjoin(CompanyComplianceDetails, CompanyComplianceDetails.organization_id == Organization.id)
    )
    if organization_id:
        query = query.filter(PayrollEmployee.organization_id == organization_id)
    if country:
        query = query.filter(CompanyComplianceDetails.jurisdiction_country == country)
    if status:
        query = query.filter(PayrollEmployee.status == status)
    if search:
        like = f"%{search}%"
        query = query.filter(or_(PayrollEmployee.name.ilike(like), PayrollEmployee.employee_code.ilike(like)))

    total = query.count()
    rows = query.order_by(Organization.organization_name, PayrollEmployee.name).offset(skip).limit(limit).all()
    items = [
        {
            "id": e.id,
            "employeeCode": e.employee_code,
            "name": e.name,
            "department": e.department,
            "designation": e.designation,
            "status": e.status,
            "employmentType": e.employment_type,
            "organizationName": org_name,
            "jurisdictionCountry": jurisdiction,
        }
        for e, org_name, jurisdiction in rows
    ]
    return {"items": items, "total": total}


def rows_to_csv_bytes(columns: List[tuple], rows: List[dict]) -> bytes:
    """Generic CSV writer shared by every Reports export — one
    implementation for Organizations/Payroll/Compliance/Employees rather
    than a bespoke CSV builder per report type. `columns` is a list of
    (key, header_label) pairs; missing keys render as empty cells."""
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([label for _, label in columns])
    for row in rows:
        writer.writerow([row.get(key, "") for key, _ in columns])
    return buffer.getvalue().encode("utf-8-sig")  # BOM so Excel opens UTF-8 correctly


# ── Dashboard charts ───────────────────────────────────────────────────────

def dashboard_charts(db: Session, start_date: Optional[date] = None, end_date: Optional[date] = None) -> dict:
    """Everything the enhanced Super Admin dashboard needs in one round
    trip — payroll trend, gross-vs-net totals, organization distribution,
    payroll-by-jurisdiction, compliance overview, employee distribution.
    All built directly from existing tables; nothing here is fabricated."""

    # Payroll trend — sum across ALL orgs per month, correct because this
    # is a platform-wide operational trend (run/employee counts and
    # currency-mixed monetary totals are clearly labelled as such in the
    # UI), whereas finance_summary's per-country totals are the
    # currency-safe view used wherever a real amount is displayed.
    month_expr = sa_func.date_trunc("month", PayrollRun.period_start)
    trend_query = db.query(
        month_expr.label("month"),
        sa_func.coalesce(sa_func.sum(PayrollRun.total_gross), 0).label("gross"),
        sa_func.coalesce(sa_func.sum(PayrollRun.total_net), 0).label("net"),
    )
    trend_query = _date_filter(trend_query, PayrollRun.period_start, start_date, end_date)
    trend_rows = trend_query.group_by(month_expr).order_by(month_expr).all()
    payroll_trend = [
        {"month": r.month.strftime("%b %Y") if r.month else "—", "gross": r.gross, "net": r.net}
        for r in trend_rows
    ]
    gross_vs_net = {
        "gross": sum((r.gross for r in trend_rows), 0),
        "net": sum((r.net for r in trend_rows), 0),
    }

    # Organization distribution — by jurisdiction and by status.
    org_by_country = dict(
        db.query(CompanyComplianceDetails.jurisdiction_country, sa_func.count(sa_func.distinct(Organization.id)))
        .select_from(Organization)
        .outerjoin(CompanyComplianceDetails, CompanyComplianceDetails.organization_id == Organization.id)
        .group_by(CompanyComplianceDetails.jurisdiction_country)
        .all()
    )
    org_by_status = dict(
        db.query(Organization.is_active, sa_func.count(Organization.id)).group_by(Organization.is_active).all()
    )

    # Payroll by jurisdiction — gross pay grouped by operating country.
    payroll_by_jurisdiction_query = (
        db.query(
            CompanyComplianceDetails.jurisdiction_country,
            sa_func.coalesce(sa_func.sum(PayrollRun.total_gross), 0),
        )
        .select_from(PayrollRun)
        .outerjoin(CompanyComplianceDetails, CompanyComplianceDetails.organization_id == PayrollRun.organization_id)
    )
    payroll_by_jurisdiction_query = _date_filter(payroll_by_jurisdiction_query, PayrollRun.period_start, start_date, end_date)
    payroll_by_jurisdiction = [
        {"country": country or "Unassigned", "grossPay": gross}
        for country, gross in payroll_by_jurisdiction_query.group_by(CompanyComplianceDetails.jurisdiction_country).all()
    ]

    # Compliance overview — policy status counts + expiring/overdue-review.
    today = date.today()
    horizon = today + timedelta(days=60)
    pack_status_counts = dict(
        db.query(JurisdictionPack.status, sa_func.count(JurisdictionPack.id)).group_by(JurisdictionPack.status).all()
    )
    expiring_soon = (
        db.query(sa_func.count(JurisdictionPack.id))
        .filter(JurisdictionPack.effective_to.isnot(None))
        .filter(JurisdictionPack.effective_to >= today)
        .filter(JurisdictionPack.effective_to <= horizon)
        .scalar()
    ) or 0
    pending_review = (
        db.query(sa_func.count(JurisdictionPack.id))
        .filter(JurisdictionPack.next_review_date.isnot(None))
        .filter(JurisdictionPack.next_review_date <= today)
        .scalar()
    ) or 0

    # Employee distribution — headcount by jurisdiction.
    employees_by_country = [
        {"country": country or "Unassigned", "employees": count}
        for country, count in (
            db.query(CompanyComplianceDetails.jurisdiction_country, sa_func.count(PayrollEmployee.id))
            .select_from(PayrollEmployee)
            .outerjoin(CompanyComplianceDetails, CompanyComplianceDetails.organization_id == PayrollEmployee.organization_id)
            .group_by(CompanyComplianceDetails.jurisdiction_country)
            .all()
        )
    ]

    return {
        "payrollTrend": payroll_trend,
        "grossVsNet": gross_vs_net,
        "organizationsByCountry": [{"country": k or "Unassigned", "count": v} for k, v in org_by_country.items()],
        "organizationsByStatus": {"active": org_by_status.get(True, 0), "inactive": org_by_status.get(False, 0)},
        "payrollByJurisdiction": payroll_by_jurisdiction,
        "complianceOverview": {
            "byStatus": pack_status_counts,
            "expiringSoon": expiring_soon,
            "pendingReview": pending_review,
        },
        "employeesByCountry": employees_by_country,
    }
