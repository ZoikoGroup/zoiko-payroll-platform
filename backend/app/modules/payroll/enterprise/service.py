"""
modules/payroll/enterprise/service.py
----------------------------------------
Business logic for Enterprise Policy jurisdiction onboarding.

Tenant isolation, audit logging, and org-scoping all follow the exact
conventions already established in app/modules/payroll/service.py and
policy/service.py (see _apply_org_filter / log_activity).
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional, List

from sqlalchemy.orm import Session
from fastapi import HTTPException, status as http_status

from app.core.exceptions import NotFoundException, BadRequestException
from app.modules.payroll.enterprise.models import EnterpriseJurisdiction, JurisdictionStatus
from app.modules.payroll.enterprise.schemas import JurisdictionConfigUpdate
from app.modules.payroll.models import ContributionRate, TaxSlab, PayrollActivityLog, ActivityStatus
from app.modules.payroll.service import (
    _apply_org_filter, log_activity, get_contribution_rates, get_tax_slabs, get_company_details,
    _seed_holidays_for_country,
)
from app.modules.payroll.policy.service import get_active_policy

# The jurisdictions this onboarding flow supports. Kept here, not in the
# engine, because it's onboarding/reference metadata, not calculation logic.
SUPPORTED_COUNTRY_CODES = ["IN", "US", "UK", "AU", "DE", "CA"]

ACTIVATION_BLOCKED_MESSAGE = (
    "Enterprise Payroll cannot be enabled until all selected jurisdictions are properly configured."
)


def _country_label(code: str) -> str:
    return {
        "US": "United States", "UK": "United Kingdom", "AU": "Australia",
        "DE": "Germany", "CA": "Canada", "IN": "India",
    }.get(code, code)


# ── Jurisdictions CRUD ──────────────────────────────────────────────────

def get_jurisdictions(db: Session, organization_id: int) -> List[EnterpriseJurisdiction]:
    query = db.query(EnterpriseJurisdiction)
    query = _apply_org_filter(query, EnterpriseJurisdiction, organization_id)
    return query.order_by(EnterpriseJurisdiction.country_code).all()


def get_jurisdiction_by_id(db: Session, organization_id: int, jurisdiction_id: int) -> EnterpriseJurisdiction:
    query = db.query(EnterpriseJurisdiction).filter(EnterpriseJurisdiction.id == jurisdiction_id)
    query = _apply_org_filter(query, EnterpriseJurisdiction, organization_id)
    row = query.first()
    if not row:
        raise NotFoundException("EnterpriseJurisdiction", jurisdiction_id)
    return row


def add_jurisdiction(db: Session, organization_id: int, country_code: str, actor_id: Optional[int] = None) -> EnterpriseJurisdiction:
    country_code = country_code.upper().strip()
    if country_code not in SUPPORTED_COUNTRY_CODES:
        raise BadRequestException(
            f"'{country_code}' is not a supported Enterprise jurisdiction. "
            f"Supported: {', '.join(SUPPORTED_COUNTRY_CODES)}."
        )
    existing = (
        db.query(EnterpriseJurisdiction)
        .filter(EnterpriseJurisdiction.organization_id == organization_id,
                EnterpriseJurisdiction.country_code == country_code)
        .first()
    )
    if existing:
        return existing  # idempotent — already added

    row = EnterpriseJurisdiction(
        organization_id=organization_id, country_code=country_code,
        status=JurisdictionStatus.DRAFT.value,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    # Auto-seed contribution rates / tax slabs so the admin sees real
    # engine-consulted defaults immediately rather than an empty table.
    get_contribution_rates(db, organization_id, country_code)
    get_tax_slabs(db, organization_id, country_code)
    # Same for holidays — seeded per onboarded jurisdiction (not just
    # whichever one is currently "active" on CompanyComplianceDetails), so
    # each country's calendar shows real defaults as soon as it's added.
    _seed_holidays_for_country(db, organization_id, country_code, datetime.utcnow().year)

    log_activity(
        db, organization_id,
        f"Jurisdiction '{_country_label(country_code)}' added to Enterprise Payroll onboarding.",
        ActivityStatus.INFO, actor_id=actor_id,
    )
    _recompute_enterprise_status(db, organization_id)
    return row


def remove_jurisdiction(db: Session, organization_id: int, jurisdiction_id: int, actor_id: Optional[int] = None) -> None:
    row = get_jurisdiction_by_id(db, organization_id, jurisdiction_id)
    label = _country_label(row.country_code)
    db.delete(row)
    db.commit()
    log_activity(
        db, organization_id, f"Jurisdiction '{label}' removed from Enterprise Payroll onboarding.",
        ActivityStatus.INFO, actor_id=actor_id,
    )
    _recompute_enterprise_status(db, organization_id)


def update_jurisdiction_config(
    db: Session, organization_id: int, jurisdiction_id: int,
    data: JurisdictionConfigUpdate, actor_id: Optional[int] = None,
) -> EnterpriseJurisdiction:
    row = get_jurisdiction_by_id(db, organization_id, jurisdiction_id)
    old_status = row.status

    if data.general_config is not None:
        row.general_config = data.general_config.model_dump(by_alias=True, exclude_none=True)
    if data.compliance_config is not None:
        row.compliance_config = data.compliance_config.model_dump(by_alias=True, exclude_none=True)
    if data.payroll_rules_config is not None:
        row.payroll_rules_config = data.payroll_rules_config.model_dump(by_alias=True, exclude_none=True)

    if data.mark_configured:
        if not (row.general_config and row.compliance_config and row.payroll_rules_config):
            raise BadRequestException(
                "Complete General, Compliance, and Payroll Rules sections before marking this jurisdiction as configured."
            )
        row.status = JurisdictionStatus.CONFIGURED.value
        row.configured_at = datetime.utcnow()

    db.commit()
    db.refresh(row)

    if data.mark_configured and old_status != row.status:
        log_activity(
            db, organization_id,
            f"Jurisdiction '{_country_label(row.country_code)}' status changed: {old_status} → {row.status}.",
            ActivityStatus.SUCCESS, actor_id=actor_id,
        )
    else:
        log_activity(
            db, organization_id, f"Jurisdiction '{_country_label(row.country_code)}' compliance configuration updated.",
            ActivityStatus.INFO, actor_id=actor_id,
        )
    _recompute_enterprise_status(db, organization_id)
    return row


def verify_jurisdiction(db: Session, organization_id: int, jurisdiction_id: int, actor_id: Optional[int] = None) -> EnterpriseJurisdiction:
    row = get_jurisdiction_by_id(db, organization_id, jurisdiction_id)
    if row.status == JurisdictionStatus.DRAFT.value:
        raise BadRequestException("Mark this jurisdiction as configured before verifying it.")
    old_status = row.status
    row.status = JurisdictionStatus.VERIFIED.value
    row.verified_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    log_activity(
        db, organization_id,
        f"Jurisdiction '{_country_label(row.country_code)}' status changed: {old_status} → {row.status}.",
        ActivityStatus.SUCCESS, actor_id=actor_id,
    )

    # Real payroll runs resolve their country from CompanyComplianceDetails.
    # jurisdiction_country alone (see generate_payslips_for_run) — nothing
    # about configuring/verifying an EnterpriseJurisdiction ever updated that
    # field, so payroll kept calculating against whatever country was set
    # there before (India, by default), no matter what was configured here.
    # The most-recently-verified jurisdiction becomes the active one, the
    # same convention the existing Compliance > Company Details dropdown
    # already uses (it stores the 2-letter code, not the full name).
    company = get_company_details(db, organization_id)
    if company.jurisdiction_country != row.country_code:
        company.jurisdiction_country = row.country_code
        # jurisdiction_state belongs to whichever country was previously
        # active — carrying it over would show a stale state (e.g. "Bremen")
        # against a newly-active country that never had a state selected.
        company.jurisdiction_state = None
        db.commit()
        log_activity(
            db, organization_id,
            f"Active payroll jurisdiction switched to {_country_label(row.country_code)} "
            f"(verifying this Enterprise jurisdiction made it the active one for real payroll runs).",
            ActivityStatus.SUCCESS, actor_id=actor_id,
        )

    _recompute_enterprise_status(db, organization_id)
    return row


# ── Contribution rates / tax slabs — structured upsert (not the OCR-string
# parsing apply_extracted_rate path — this takes clean numeric input from
# the Enterprise config panel's editable form) ─────────────────────────

def get_contribution_rates_numeric(db: Session, organization_id: int, country_code: str) -> List[ContributionRate]:
    """Same rows get_contribution_rates() returns (auto-seeds if empty),
    but callers here need the numeric fields, not the display-string-only
    ContributionRateResponse used by the read-only Compliance tables."""
    return get_contribution_rates(db, organization_id, country_code)


def upsert_contribution_rate(
    db: Session, organization_id: int, country_code: str, component_key: str,
    employee_rate_pct: Optional[Decimal] = None, employer_rate_pct: Optional[Decimal] = None,
    flat_amount: Optional[Decimal] = None, actor_id: Optional[int] = None,
) -> ContributionRate:
    row = (
        db.query(ContributionRate)
        .filter(ContributionRate.organization_id == organization_id,
                ContributionRate.jurisdiction_country == country_code,
                ContributionRate.component_key == component_key)
        .first()
    )
    if not row:
        raise NotFoundException("ContributionRate", f"{country_code}/{component_key}")
    if employee_rate_pct is not None:
        row.employee_rate_pct = employee_rate_pct
    if employer_rate_pct is not None:
        row.employer_rate_pct = employer_rate_pct
    if flat_amount is not None:
        row.flat_amount = flat_amount
    db.commit()
    db.refresh(row)
    log_activity(
        db, organization_id,
        f"Contribution rate '{row.label}' updated for {_country_label(country_code)}.",
        ActivityStatus.SUCCESS, actor_id=actor_id,
    )
    return row


# ── Validation & Activation ──────────────────────────────────────────────

def validate_enterprise_readiness(db: Session, organization_id: int) -> dict:
    jurisdictions = get_jurisdictions(db, organization_id)
    if not jurisdictions:
        return {
            "can_activate": False,
            "blocking_reasons": ["Select at least one jurisdiction before activating Enterprise Payroll."],
            "configured_jurisdictions": [],
        }

    not_ready = [j for j in jurisdictions if j.status == JurisdictionStatus.DRAFT.value]
    if not_ready:
        names = ", ".join(_country_label(j.country_code) for j in not_ready)
        return {
            "can_activate": False,
            "blocking_reasons": [ACTIVATION_BLOCKED_MESSAGE, f"Not yet configured: {names}."],
            "configured_jurisdictions": [_country_label(j.country_code) for j in jurisdictions if j not in not_ready],
        }

    return {
        "can_activate": True,
        "blocking_reasons": [],
        "configured_jurisdictions": [_country_label(j.country_code) for j in jurisdictions],
    }


def activate_enterprise(db: Session, organization_id: int, actor_id: Optional[int] = None) -> dict:
    result = validate_enterprise_readiness(db, organization_id)
    if not result["can_activate"]:
        raise HTTPException(http_status.HTTP_400_BAD_REQUEST, detail=ACTIVATION_BLOCKED_MESSAGE)

    policy = get_active_policy(db, organization_id)
    policy.calculation_mode = "enterprise"
    policy.enterprise_status = "active"
    policy.enterprise_activated_at = datetime.utcnow()
    db.commit()

    # Covers jurisdictions verified before this sync existed, or an org that
    # verified several and is only activating now — same "most recently
    # verified wins" rule as verify_jurisdiction, applied once at activation.
    verified = [j for j in get_jurisdictions(db, organization_id) if j.status == JurisdictionStatus.VERIFIED.value and j.verified_at]
    if verified:
        latest = max(verified, key=lambda j: j.verified_at)
        company = get_company_details(db, organization_id)
        if company.jurisdiction_country != latest.country_code:
            company.jurisdiction_country = latest.country_code
            company.jurisdiction_state = None
            db.commit()
            log_activity(
                db, organization_id,
                f"Active payroll jurisdiction set to {_country_label(latest.country_code)} on Enterprise activation.",
                ActivityStatus.SUCCESS, actor_id=actor_id,
            )

    jurisdictions_label = ", ".join(result["configured_jurisdictions"])
    log_activity(
        db, organization_id, f"Enterprise Payroll activated with jurisdictions: {jurisdictions_label}.",
        ActivityStatus.SUCCESS, actor_id=actor_id,
    )
    return {
        "activated": True,
        "enterprise_status": policy.enterprise_status,
        "activated_jurisdictions": result["configured_jurisdictions"],
    }


def deactivate_enterprise(db: Session, organization_id: int, actor_id: Optional[int] = None) -> dict:
    policy = get_active_policy(db, organization_id)
    policy.calculation_mode = "standard"
    jurisdictions = get_jurisdictions(db, organization_id)
    policy.enterprise_status = "configured" if jurisdictions else "not_configured"
    db.commit()
    log_activity(
        db, organization_id, "Enterprise Payroll disabled (reverted to Standard).",
        ActivityStatus.INFO, actor_id=actor_id,
    )
    return {"activated": False, "enterprise_status": policy.enterprise_status, "activated_jurisdictions": []}


def _recompute_enterprise_status(db: Session, organization_id: int) -> None:
    """Keeps PayrollPolicy.enterprise_status in sync after any jurisdiction
    mutation, so reads (the Policy page badge) never need to recompute."""
    policy = get_active_policy(db, organization_id)
    if policy.calculation_mode == "enterprise" and policy.enterprise_status == "active":
        return  # activation status is only changed by activate/deactivate, not by editing jurisdictions
    jurisdictions = get_jurisdictions(db, organization_id)
    if not jurisdictions:
        policy.enterprise_status = "not_configured"
    elif all(j.status in (JurisdictionStatus.CONFIGURED.value, JurisdictionStatus.VERIFIED.value) for j in jurisdictions):
        policy.enterprise_status = "configured"
    else:
        policy.enterprise_status = "in_progress"
    db.commit()


# ── Dashboard ────────────────────────────────────────────────────────────

def get_dashboard(db: Session, organization_id: int) -> dict:
    jurisdictions = get_jurisdictions(db, organization_id)
    policy = get_active_policy(db, organization_id)

    configured_count = sum(1 for j in jurisdictions if j.status in (JurisdictionStatus.CONFIGURED.value, JurisdictionStatus.VERIFIED.value))
    pending_count = sum(1 for j in jurisdictions if j.status == JurisdictionStatus.DRAFT.value)
    total = len(jurisdictions)
    completion_pct = round((configured_count / total) * 100, 1) if total else 0.0
    active_countries = (
        [_country_label(j.country_code) for j in jurisdictions]
        if policy.calculation_mode == "enterprise" and policy.enterprise_status == "active"
        else []
    )

    upcoming_filings = []
    for j in jurisdictions:
        schedule = (j.compliance_config or {}).get("governmentFilingSchedule")
        if schedule:
            upcoming_filings.append({"country": _country_label(j.country_code), "schedule": schedule})

    recent = (
        db.query(PayrollActivityLog)
        .filter(PayrollActivityLog.organization_id == organization_id)
        .filter(PayrollActivityLog.description.ilike("%jurisdiction%") | PayrollActivityLog.description.ilike("%enterprise%"))
        .order_by(PayrollActivityLog.created_at.desc())
        .limit(10)
        .all()
    )
    recent_changes = [
        {"description": r.description, "status": r.status, "createdAt": r.created_at.isoformat() if r.created_at else None}
        for r in recent
    ]

    return {
        "configured_count": configured_count,
        "pending_count": pending_count,
        "active_countries": active_countries,
        "completion_pct": completion_pct,
        "upcoming_filings": upcoming_filings,
        "recent_changes": recent_changes,
    }
