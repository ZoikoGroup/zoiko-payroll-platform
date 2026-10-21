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
    PayrollRun, PayrollEmployee, PayslipItem, CompanyComplianceDetails, JurisdictionPack, ContributionRate, TaxSlab,
    PayrollStatus,
)
from app.modules.organizations.models import Organization
from app.core.exceptions import NotFoundException
from app.modules.super_admin import aggregates

def _employee_counts_by_org(db: Session, org_ids: List[int]) -> dict:
    """Live worker headcount per organization — the cohort used to decide
    whether a per-organization money cell may be shown at all."""
    if not org_ids:
        return {}
    return dict(
        db.query(PayrollEmployee.organization_id, sa_func.count(PayrollEmployee.id))
        .filter(PayrollEmployee.organization_id.in_(org_ids))
        .group_by(PayrollEmployee.organization_id)
        .all()
    )


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

_MONEY_KEYS = ("grossPay", "netPay", "totalDeductions", "totalTaxes", "employerCost")


def _filtered_runs(db: Session, country: Optional[str], status: Optional[str],
                   start_date: Optional[date], end_date: Optional[date]):
    """Every run matching the platform filters, with its jurisdiction and
    currency. Never filtered to one organization: a platform view is an
    aggregate across tenants (ZP-PRIV B.1/B.2)."""
    query = (
        db.query(PayrollRun, CompanyComplianceDetails.jurisdiction_country, Organization.currency)
        .join(Organization, Organization.id == PayrollRun.organization_id)
        .outerjoin(CompanyComplianceDetails, CompanyComplianceDetails.organization_id == PayrollRun.organization_id)
    )
    if country:
        query = query.filter(CompanyComplianceDetails.jurisdiction_country == country)
    if status:
        query = query.filter(PayrollRun.status == status)
    return _date_filter(query, PayrollRun.period_start, start_date, end_date).all()


def _workers_by_run(db: Session, run_ids: List[int]) -> dict:
    """run id -> set of worker ids paid in it (the cohort of a money cell)."""
    out: dict = {}
    if not run_ids:
        return out
    for i in range(0, len(run_ids), 500):
        chunk = run_ids[i:i + 500]
        for run_id, employee_id in (
            db.query(PayslipItem.payroll_run_id, PayslipItem.employee_id)
            .filter(PayslipItem.payroll_run_id.in_(chunk)).all()
        ):
            out.setdefault(run_id, set()).add(employee_id)
    return out


def _money_cells(rows, workers_by_run: dict, key_fn) -> dict:
    """Group runs into cells; each cell tracks runs, orgs, distinct workers
    and money. ``key_fn(run, jurisdiction, currency)`` names the cell."""
    cells: dict = {}
    for run, jurisdiction, currency in rows:
        key = key_fn(run, jurisdiction, currency)
        cell = cells.setdefault(key, {
            "runs": 0, "orgs": set(), "workers": set(),
            "grossPay": 0, "netPay": 0, "totalDeductions": 0, "totalTaxes": 0, "employerCost": 0,
        })
        cell["runs"] += 1
        cell["orgs"].add(run.organization_id)
        cell["workers"] |= workers_by_run.get(run.id, set())
        cell["grossPay"] += run.total_gross or 0
        cell["netPay"] += run.total_net or 0
        cell["totalDeductions"] += run.total_deductions or 0
        cell["totalTaxes"] += run.total_taxes or 0
        cell["employerCost"] += run.total_employer_contribution or 0
    return cells


def _cell_out(cell: dict, **labels) -> dict:
    out = dict(labels)
    out.update({
        "runCount": cell["runs"],
        "organizationCount": len(cell["orgs"]),
        "employeeCount": len(cell["workers"]),
        **{k: cell[k] for k in _MONEY_KEYS},
    })
    aggregates.suppress_money_row(out, len(cell["workers"]), len(cell["orgs"]), _MONEY_KEYS)
    aggregates.suppress_row(out, len(cell["workers"]), ("employeeCount",))
    return out


def finance_overview(
    db: Session, country: Optional[str] = None,
    status: Optional[str] = None, start_date: Optional[date] = None, end_date: Optional[date] = None,
    skip: int = 0, limit: int = 50,
) -> dict:
    """Payroll money as platform aggregates (ZP-PRIV B.1/B.2): one cell per
    jurisdiction x currency x month x run status. A cell shows money only
    when it covers at least k distinct workers AND at least two
    organizations, so no cell is one tenant's payroll or one person's pay.
    Individual runs, run codes and organization names are tenant data and
    are never listed here."""
    rows = _filtered_runs(db, country, status, start_date, end_date)
    workers = _workers_by_run(db, [r[0].id for r in rows])
    cells = _money_cells(
        rows, workers,
        lambda run, j, c: (j or "Unassigned", c or "", run.period_start.strftime("%Y-%m") if run.period_start else "—",
                           run.status),
    )
    items = [
        _cell_out(cell, jurisdictionCountry=j, currency=c or None, period=period, status=st)
        for (j, c, period, st), cell in sorted(cells.items(), key=lambda kv: (kv[0][2], kv[0][0]), reverse=True)
    ]
    cohort = len(set().union(*workers.values())) if workers else 0
    return {"items": items[skip:skip + limit], "total": len(items), "_cohort": cohort}


def finance_summary(
    db: Session, country: Optional[str] = None,
    start_date: Optional[date] = None, end_date: Optional[date] = None,
) -> dict:
    """Financial totals per jurisdiction country plus currency-agnostic
    platform counts. Money cells follow the same k-worker / two-org rule as
    finance_overview; the cohort is the set of workers actually paid in the
    filtered runs (not the jurisdiction's whole headcount)."""
    rows = _filtered_runs(db, country, None, start_date, end_date)
    workers = _workers_by_run(db, [r[0].id for r in rows])
    cells = _money_cells(rows, workers, lambda run, j, c: (j or "Unassigned", c or ""))
    by_country = []
    for (j, c), cell in sorted(cells.items()):
        out = _cell_out(cell, country=j, currency=c or None)
        out["organizations"] = out.pop("organizationCount")
        out["payrollRuns"] = out.pop("runCount")
        by_country.append(out)

    status_counts: dict = {}
    for run, _, _ in rows:
        status_counts[run.status] = status_counts.get(run.status, 0) + 1
    pending = sum(
        v for k, v in status_counts.items()
        if k in (PayrollStatus.REVIEW.value, PayrollStatus.APPROVED.value, PayrollStatus.AUTHORIZED.value)
    )
    completed = status_counts.get(PayrollStatus.PAID.value, 0) + status_counts.get(PayrollStatus.CLOSED.value, 0)
    cohort = len(set().union(*workers.values())) if workers else 0
    return {
        "byCountry": by_country,
        "totalOrganizations": len({run.organization_id for run, _, _ in rows}),
        "totalPayrollRuns": sum(status_counts.values()),
        "payrollsPending": pending,
        "payrollsCompleted": completed,
        "_cohort": cohort,
    }


def finance_by_organization(
    db: Session, country: Optional[str] = None,
    status: Optional[str] = None, start_date: Optional[date] = None, end_date: Optional[date] = None,
) -> dict:
    """The tenant registry with payroll ACTIVITY, not payroll money
    (ZP-PRIV B.1): one row per organization with its jurisdiction,
    currency, a k-suppressed headcount bucket and whether it ran payroll in
    the window. An organization's own payroll totals, run counts and pay
    dates are tenant data and appear only inside that tenant."""
    query = (
        db.query(Organization.id, Organization.organization_name, Organization.organization_code,
                 Organization.currency, CompanyComplianceDetails.jurisdiction_country)
        .outerjoin(CompanyComplianceDetails, CompanyComplianceDetails.organization_id == Organization.id)
    )
    if country:
        query = query.filter(CompanyComplianceDetails.jurisdiction_country == country)
    orgs = query.order_by(Organization.organization_name.asc()).all()
    active = {run.organization_id for run, _, _ in _filtered_runs(db, country, status, start_date, end_date)}
    headcounts = _employee_counts_by_org(db, [o[0] for o in orgs])
    organizations = [
        {
            "organizationId": org_id,
            "organizationName": name,
            "organizationCode": code,
            "jurisdictionCountry": jurisdiction,
            "currency": currency,
            "headcount": aggregates.cohort_bucket(headcounts.get(org_id, 0)),
            "payrollActive": org_id in active,
        }
        for org_id, name, code, currency, jurisdiction in orgs
    ]
    return {"organizations": organizations, "total": len(organizations)}


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
    old_currency = org.currency
    org.currency = currency.upper() if currency else None
    db.commit()
    db.refresh(org)
    _notify_organization_currency_changed(db, org, old_currency, organization_id)
    return org


def _notify_organization_currency_changed(db: Session, org, old_currency: Optional[str], organization_id: int) -> None:
    import logging
    logger = logging.getLogger("zoiko")
    try:
        if old_currency == org.currency:
            return
        from app.services.email_service import _get_org_contact_email, send_organization_currency_changed_email
        org_email = _get_org_contact_email(db, organization_id)
        if not org_email:
            return
        from app.modules.communications.service import queue_email, repeatable_idempotency_key
        # Repeatable (A → B → A → B): keyed on the transition within the window.
        queue_email(
            "super_admin", "organizations.currency_changed", None, org_email,
            repeatable_idempotency_key(
                organization_id, "organizations.currency_changed", org_email, None,
                f"org:{organization_id}", {"old": old_currency, "new": org.currency},
            ),
            send_organization_currency_changed_email, org_email,
            send_kwargs=dict(
                org_name=getattr(org, "organization_name", None) or org.organization_code or "",
                old_currency=old_currency or "",
                new_currency=org.currency or "",
                organization_id=organization_id,
            ),
            organization_id=organization_id, db=db,
        )
    except Exception as exc:
        logger.warning(f"[super-admin] org-currency email failed for org {organization_id}: {exc}")


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

    # States whose ONLY configured tax data is Professional Tax — either
    # mechanism: the older flat ContributionRate(component_key="pt") rows
    # (Maharashtra/Karnataka) or the newer bracketed TaxSlab(rule_type=
    # "PT_FLAT") rows (Telangana) — flagged, not removed from `states`
    # itself, so Compliance (which reads `states` directly and must still
    # let PT be configured there) is completely unaffected. Statutory
    # Rates is the only consumer that filters using this — PT management
    # belongs to Compliance alone, per explicit product decision, and
    # that's true regardless of which of the two PT mechanisms a given
    # state happens to use.
    non_pt_states_by_country: dict = {}
    for country, state in db.query(ContributionRate.jurisdiction_country, ContributionRate.jurisdiction_state).filter(ContributionRate.jurisdiction_state.isnot(None), ContributionRate.component_key != "pt").distinct():
        non_pt_states_by_country.setdefault(country, set()).add(state)
    for country, state in db.query(TaxSlab.jurisdiction_country, TaxSlab.jurisdiction_state).filter(TaxSlab.jurisdiction_state.isnot(None), TaxSlab.rule_type != "PT_FLAT").distinct():
        non_pt_states_by_country.setdefault(country, set()).add(state)

    return [
        {
            "code": code, "name": name, "states": sorted(states_by_country.get(code, [])),
            "ptOnlyStates": sorted(states_by_country.get(code, set()) - non_pt_states_by_country.get(code, set())),
        }
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
            # ZP-PRIV B.1: an employer's tax identifiers are tenant data;
            # the platform only needs to know whether they are recorded.
            "taxIdentifiers": None,
            "taxIdentifiersRecorded": bool(details.tax_identifiers),
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
            # ZP-PRIV B.2: never an exact headcount for a small tenant.
            "employeeCount": aggregates.cohort_bucket(emp_counts.get(o.id, 0)),
            "payrollRunCount": run_counts.get(o.id, 0),
        }
        for o in orgs
    ]
    return {"items": items, "total": total}


def reports_employee_totals(
    db: Session, organization_id: Optional[int] = None, country: Optional[str] = None,
    status: Optional[str] = None, skip: int = 0, limit: int = 50,
) -> dict:
    """ZP-PRIV B.1/B.2: the Super Admin "Employees" report is an aggregate —
    counts by tenant, jurisdiction and status. It never returns a name, an
    employee code, a department, a designation or any other identity, and
    every cell with a cohort below k is suppressed. This replaces the old
    cross-tenant employee listing (which also carried a ?search= name oracle)
    and every field the CSV export used to write out."""
    query = (
        db.query(
            Organization.organization_name.label("organization_name"),
            Organization.organization_code.label("organization_code"),
            CompanyComplianceDetails.jurisdiction_country.label("jurisdiction_country"),
            PayrollEmployee.status.label("status"),
            PayrollEmployee.employment_type.label("employment_type"),
            sa_func.count(PayrollEmployee.id).label("employee_count"),
        )
        .join(Organization, Organization.id == PayrollEmployee.organization_id)
        .outerjoin(CompanyComplianceDetails, CompanyComplianceDetails.organization_id == Organization.id)
    )
    if organization_id:
        query = query.filter(PayrollEmployee.organization_id == organization_id)
    if country:
        query = query.filter(CompanyComplianceDetails.jurisdiction_country == country)
    if status:
        query = query.filter(PayrollEmployee.status == status)

    grouped = (
        query.group_by(
            Organization.organization_name, Organization.organization_code,
            CompanyComplianceDetails.jurisdiction_country,
            PayrollEmployee.status, PayrollEmployee.employment_type,
        )
        .order_by(Organization.organization_name.asc())
    )
    rows = grouped.all()

    items = [
        {
            "organizationName": r.organization_name,
            "organizationCode": r.organization_code,
            "jurisdictionCountry": r.jurisdiction_country,
            "status": r.status,
            "employmentType": r.employment_type,
            "employeeCount": r.employee_count,
        }
        for r in rows
    ]
    cohort = sum(r.employee_count for r in rows)
    # Primary + complementary suppression per organization: the org's own
    # total is visible elsewhere (registry headcount), so a single hidden
    # cell could otherwise be recovered by subtraction.
    by_org: dict = {}
    for cell in items:
        by_org.setdefault(cell["organizationCode"], []).append(cell)
    for cells in by_org.values():
        aggregates.suppress_group(cells, "employeeCount", ())
    return {"items": items[skip:skip + limit], "total": len(items), "_cohort": cohort}


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
    # ZP-PRIV B.2: monthly money cells need >= k distinct workers and >= 2
    # organizations, or they would be one tenant's payroll (or one person's
    # pay) whenever a single tenant ran payroll that month.
    trend_rows = _filtered_runs(db, None, None, start_date, end_date)
    trend_workers = _workers_by_run(db, [r[0].id for r in trend_rows])
    trend_cells = _money_cells(
        trend_rows, trend_workers,
        lambda run, j, c: run.period_start.replace(day=1) if run.period_start else None,
    )
    payroll_trend = []
    for month, cell in sorted(trend_cells.items(), key=lambda kv: (kv[0] is None, kv[0])):
        point = {"month": month.strftime("%b %Y") if month else "—",
                 "gross": cell["grossPay"], "net": cell["netPay"]}
        aggregates.suppress_money_row(point, len(cell["workers"]), len(cell["orgs"]), ("gross", "net"))
        payroll_trend.append(point)
    all_trend = _money_cells(trend_rows, trend_workers, lambda run, j, c: "all").get("all")
    gross_vs_net = {"gross": all_trend["grossPay"] if all_trend else 0,
                    "net": all_trend["netPay"] if all_trend else 0}
    if all_trend:
        aggregates.suppress_money_row(gross_vs_net, len(all_trend["workers"]), len(all_trend["orgs"]),
                                      ("gross", "net"))

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

    # Payroll by jurisdiction — gross pay per operating country, same rule.
    payroll_by_jurisdiction = []
    for country, cell in sorted(
        _money_cells(trend_rows, trend_workers, lambda run, j, c: j or "Unassigned").items()
    ):
        point = {"country": country, "grossPay": cell["grossPay"]}
        aggregates.suppress_money_row(point, len(cell["workers"]), len(cell["orgs"]), ("grossPay",))
        payroll_by_jurisdiction.append(point)

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

    # Employee distribution — headcount by jurisdiction (sub-k cohorts hidden).
    employees_by_country = [
        {"country": country or "Unassigned", "employees": aggregates.cohort_bucket(count)}
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
