"""
modules/billing/jurisdiction_entitlement.py
---------------------------------------------
Country entitlement: which countries an organization may add employees in
and run payroll for. The ledger is OrganizationJurisdiction
(billing/models.py); the cap is the plan's max_jurisdictions, resolved the
same way require_scope_limit resolves it (plan version flag, live override,
or EnterpriseOrderForm.negotiated_scale_limits).

  Core 1 · Professional 3 (also every EVALUATION trial, which runs on the
  Professional plan version) · Business 10 · Enterprise negotiated.

The registration country is the primary row and always counts.

Country limit — always enforced, in every BILLING_ENFORCEMENT_MODE:
  * Adding: an org at or over its limit cannot ADD a country
    (add_entitled_country / a new default country).
  * Downgrading: a plan change that would leave the org with more ACTIVE
    countries than the target plan allows is REFUSED (guard_country_downgrade,
    409 reason=downgrade_exceeds_country_limit) on every path that can refuse
    it: Org Admin checkout / in-place plan change, and the Super Admin trial
    conversion, Enterprise order form and max_jurisdictions override. A Super
    Admin can override the refusal with a reason; that is written to the
    billing audit log (COUNTRY_LIMIT_DOWNGRADE_OVERRIDE).
  * Changes that cannot be refused (Stripe-initiated subscription changes,
    checkout completion): existing countries keep running, adding is
    blocked, and the org is flagged for Super Admin review
    (COUNTRY_LIMIT_REVIEW_REQUIRED + the compliance exceptions list).
  * A max_jurisdictions entitlement override simply stops applying at its
    expires_at (read time, _resolve_entitlement): no job, event or email
    runs then. Existing countries keep running and adding is blocked; the org
    appears on the live compliance exceptions list at once, and gets a
    COUNTRY_LIMIT_REVIEW_REQUIRED event the next time a reconcile runs.
  * Nothing is paused, removed or reactivated automatically any more. Rows
    the earlier rule left OVER_LIMIT keep that state (see
    scripts/report_paused_countries.py); an admin re-adding the country
    reactivates it like any add.

Same three-state rollout switch as the rest of billing
(settings.BILLING_ENFORCEMENT_MODE): "off" never blocks, "warn" records an
ENTITLEMENT_WOULD_HAVE_BLOCKED audit event and lets the write through,
"enforce" raises. The ledger itself is maintained in every mode so that
flipping to "enforce" never starts from an empty or stale ledger.

Write paths only: assert_country_allowed is called from employee create/
update/bulk/ELStAM and from payroll run generation — never from
payroll.service._resolve_employee_country, which has many read-only callers.
"""

from datetime import datetime
from typing import Callable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, ForbiddenException, ZoikoException
from app.modules.billing.entitlements import (
    _current_plan_code,
    _enforcement_mode,
    _resolve_entitlement,
    get_active_subscription,
    require_not_dunning_restricted,
)
from app.modules.billing.feature_keys import MAX_JURISDICTIONS
from app.modules.billing.models import (
    BillingCommercialAuditEvent,
    DunningStage,
    OrganizationJurisdiction,
    OrganizationJurisdictionStatus,
)

ACTIVE = OrganizationJurisdictionStatus.ACTIVE.value
OVER_LIMIT = OrganizationJurisdictionStatus.OVER_LIMIT.value
REMOVED = OrganizationJurisdictionStatus.REMOVED.value

# Audit feature_key for a would-have-blocked country write (warn mode).
COUNTRY_NOT_ENTITLED = "country_not_entitled"


class ConflictException(ZoikoException):
    """409 — the request is valid but the org's current data prevents it
    (e.g. removing a country that still has employees)."""

    def __init__(self, message: str, trace: dict | None = None):
        super().__init__(status_code=409, error_code="CONFLICT", message=message)
        if trace:
            self.trace = trace


# ── Normalization / labels ───────────────────────────────────────────────

def normalize_country_code(raw) -> Optional[str]:
    """The 2-letter form PayrollEmployee.country_code uses, or None.

    Names go through payroll.service._jurisdiction_code_for_org_country
    (the helper _resolve_org_country's registration-name fallback relies
    on); the result, or a bare 2-letter code, then through
    payroll.service._normalize_country so e.g. "GB" lands on the same "UK"
    an employee row would carry. Unlike _normalize_country alone, blank or
    unrecognized input returns None instead of defaulting to "IN" or
    truncating a name.
    """
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    from app.modules.payroll.service import _jurisdiction_code_for_org_country, _normalize_country

    code = _jurisdiction_code_for_org_country(value)
    if code:
        return _normalize_country(code)
    if len(value) == 2 and value.isalpha():
        return _normalize_country(value)
    return None


def country_name(code: Optional[str]) -> str:
    from app.core.jurisdiction import ALL_CODE_TO_COUNTRY_NAME

    return ALL_CODE_TO_COUNTRY_NAME.get(code or "", code or "Unknown")


def _join_names(codes: list[str]) -> str:
    return ", ".join(country_name(c) for c in codes) or "none"


def _plan_label(db: Session, subscription) -> str:
    if subscription is None:
        return "current"
    from app.modules.billing.models import BillingAuthority, BillingPlan, BillingPlanVersion

    if subscription.billing_authority == BillingAuthority.ENTERPRISE_ORDER_FORM.value:
        return "Enterprise"
    version = db.query(BillingPlanVersion).filter(BillingPlanVersion.id == subscription.plan_version_id).first()
    plan = db.query(BillingPlan).filter(BillingPlan.id == version.plan_id).first() if version else None
    return plan.name if plan else "current"


def _countries_phrase(n: int) -> str:
    return "1 country" if n == 1 else f"{n} countries"


# ── Ledger reads ─────────────────────────────────────────────────────────

def _rows(db: Session, organization_id: int, include_removed: bool = False) -> list[OrganizationJurisdiction]:
    """Primary first, then oldest first — the order reconcile keeps rows in."""
    query = db.query(OrganizationJurisdiction).filter(OrganizationJurisdiction.organization_id == organization_id)
    if not include_removed:
        query = query.filter(OrganizationJurisdiction.status != REMOVED)
    return query.order_by(
        OrganizationJurisdiction.is_primary.desc(),
        OrganizationJurisdiction.activated_at.asc(),
        OrganizationJurisdiction.id.asc(),
    ).all()


def resolve_country_limit(db: Session, organization_id: int) -> Optional[int]:
    """The org's max_jurisdictions; None = unlimited.

    Same resolution require_scope_limit uses (_resolve_entitlement: live
    override, then EnterpriseOrderForm.negotiated_scale_limits on the
    ENTERPRISE_ORDER_FORM route, then the plan version's flag). An org with
    no subscription at all is legacy/NON_CHARGEABLE and gets no limit. A
    subscription whose plan doesn't grant max_jurisdictions still keeps its
    primary country — the floor is 1, never 0.
    """
    subscription = get_active_subscription(db, organization_id)
    if subscription is None:
        return None
    allowed, limit_value = _resolve_entitlement(db, subscription, MAX_JURISDICTIONS)
    if not allowed:
        return 1
    if limit_value is None:
        return None
    return max(int(limit_value), 1)


def _effective_org_country(db: Session, organization_id: int) -> Optional[str]:
    """Same precedence as payroll.service._resolve_org_country
    (CompanyComplianceDetails.jurisdiction_country, else
    Organization.country), but None instead of an "IN" default."""
    from app.modules.organizations.models import Organization
    from app.modules.payroll.models import CompanyComplianceDetails

    company = db.query(CompanyComplianceDetails).filter(
        CompanyComplianceDetails.organization_id == organization_id
    ).first()
    code = normalize_country_code(getattr(company, "jurisdiction_country", None))
    if code:
        return code
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    return normalize_country_code(getattr(org, "country", None))


def ensure_ledger(db: Session, organization_id: int) -> list[OrganizationJurisdiction]:
    """Non-REMOVED rows for the org, seeding them first if the org has no
    ledger rows at all (an org created by a path other than registration,
    or one the backfill hasn't reached). Seeding is the same per-org
    backfill the migration script runs."""
    if organization_id is None:
        return []
    has_any = db.query(OrganizationJurisdiction.id).filter(
        OrganizationJurisdiction.organization_id == organization_id
    ).first()
    if has_any is None:
        backfill_organization(db, organization_id)
        return _rows(db, organization_id)
    # No automatic status changes: rows paused by the earlier OVER_LIMIT rule
    # keep that state until an admin reviews them (re-adding reactivates).
    return _rows(db, organization_id)


def limit_for_plan_version(db: Session, version) -> Optional[int]:
    """max_jurisdictions a plan version grants: None = unlimited, a missing
    or zero flag = 1 (the primary country always counts)."""
    from app.modules.billing.models import BillingEntitlementFlag

    flag = None
    if version is not None:
        flag = db.query(BillingEntitlementFlag).filter(
            BillingEntitlementFlag.plan_version_id == version.id,
            BillingEntitlementFlag.feature_key == MAX_JURISDICTIONS,
        ).first()
    if flag is None or flag.limit_value == 0:
        return 1
    return None if flag.limit_value is None else max(int(flag.limit_value), 1)


def plan_change_impact(db: Session, organization_id: int, plan_code: str) -> dict:
    """What switching this org to `plan_code`'s PUBLISHED version would do
    to its countries, computed without writing. Nothing is ever paused, so
    `pause`/`restore` are always empty. `blocked` is True when the org has
    more ACTIVE countries than the plan allows — the change is refused until
    `removeCount` countries are removed (`message` says so). Used by the plan
    picker and checkout so a refused downgrade is never a surprise."""
    from app.modules.billing.models import BillingPlan
    from app.modules.billing.plan_catalog import get_published_plan_version

    rows = ensure_ledger(db, organization_id)
    version = get_published_plan_version(db, plan_code)
    new_limit = limit_for_plan_version(db, version)
    countries = [r.country_code for r in rows if r.status == ACTIVE]
    remove = 0 if new_limit is None else max(len(countries) - new_limit, 0)
    plan = db.query(BillingPlan).filter(BillingPlan.code == plan_code).first()
    plan_name = plan.name if plan else plan_code
    return {
        "planCode": plan_code,
        "newLimit": new_limit,
        "currentLimit": resolve_country_limit(db, organization_id),
        "countries": countries,
        "keep": countries,
        "pause": [],
        "restore": [],
        "overLimitBy": remove,
        "blocked": remove > 0,
        "removeCount": remove,
        "message": downgrade_blocked_message(len(countries), plan_name, new_limit) if remove else None,
    }


# ── Downgrades ───────────────────────────────────────────────────────────

DOWNGRADE_BLOCKED = "downgrade_exceeds_country_limit"


def downgrade_blocked_message(used: int, plan_name: str, new_limit: int) -> str:
    remove = used - new_limit
    return (
        f"Your organization has {_countries_phrase(used)}; the {plan_name} plan allows {new_limit}. "
        f"Remove {_countries_phrase(remove)} under Compliance > Countries to downgrade."
    )


def guard_country_downgrade(db: Session, organization_id: int, new_limit: Optional[int], plan_name: str, *,
                            source: str, actor_user_id: Optional[int] = None,
                            override: bool = False, override_reason: Optional[str] = None) -> None:
    """Refuse a change that would leave the org with more ACTIVE countries
    than `new_limit` (409, reason=downgrade_exceeds_country_limit). A Super
    Admin may pass override=True with a reason: the change then goes ahead
    (existing countries keep running, adding stays blocked) and the override
    is written to the billing audit log. Does not commit."""
    if new_limit is None:
        return
    # Read-only ledger read: Super Admin callers must never trigger the
    # backfill (it reads worker tables a platform principal may not touch).
    # An org with no ledger yet has nothing to exceed.
    rows = _rows(db, organization_id)
    active = [r.country_code for r in rows if r.status == ACTIVE]
    if len(active) <= new_limit:
        return
    if override:
        if not (override_reason or "").strip():
            raise BadRequestException("A reason is required to override the country limit on a downgrade.")
        _audit(db, organization_id, actor_user_id, "COUNTRY_LIMIT_DOWNGRADE_OVERRIDE", {
            "source": source, "plan": plan_name, "new_limit": new_limit, "used": len(active),
            "countries": active, "reason": override_reason.strip(),
        })
        db.flush()
        return
    raise ConflictException(downgrade_blocked_message(len(active), plan_name, new_limit), trace={
        "resource": MAX_JURISDICTIONS,
        "reason": DOWNGRADE_BLOCKED,
        "source": source,
        "used": len(active),
        "new_limit": new_limit,
        "remove_count": len(active) - new_limit,
        "countries": active,
        "plan": plan_name,
    })


def get_entitled_countries(db: Session, organization_id: int) -> list[str]:
    """ACTIVE rows only, primary first."""
    return [r.country_code for r in ensure_ledger(db, organization_id) if r.status == ACTIVE]


def count_entitled(db: Session, organization_id: int) -> int:
    """ACTIVE entitled countries, including the primary."""
    return len(get_entitled_countries(db, organization_id))


def org_runs_country(db: Session, organization_id: Optional[int], country_code: str) -> bool:
    """True when the org pays employees in `country_code`: it is the org's
    default country, or an ACTIVE entitled country. Read-only (never seeds
    the ledger). For country-specific org setup and guards (Mexico employer
    profile, CFDI, filings, ...) that used to require the org's single
    default country, so a multi-country org can run each country's payroll."""
    if not organization_id:
        return False
    code = normalize_country_code(country_code)
    if code is None:
        return False
    if _effective_org_country(db, organization_id) == code:
        return True
    return db.query(OrganizationJurisdiction.id).filter(
        OrganizationJurisdiction.organization_id == organization_id,
        OrganizationJurisdiction.country_code == code,
        OrganizationJurisdiction.status == ACTIVE,
    ).first() is not None


def org_payroll_countries(db: Session, organization_id: Optional[int]) -> list[str]:
    """Every country the org runs (or has run) payroll in, default country
    first: the default plus every non-REMOVED ledger row. OVER_LIMIT rows
    are included — new payroll there is paused, but filings, reports and
    holidays for payroll already run still apply. Read-only."""
    if not organization_id:
        return []
    countries: list[str] = []
    default = _effective_org_country(db, organization_id)
    if default:
        countries.append(default)
    for row in _rows(db, organization_id):
        if row.country_code not in countries:
            countries.append(row.country_code)
    return countries


def get_primary_country(db: Session, organization_id: int) -> Optional[str]:
    for row in ensure_ledger(db, organization_id):
        if row.is_primary:
            return row.country_code
    return None


# ── Audit ────────────────────────────────────────────────────────────────

def _audit(db: Session, organization_id: int, actor_user_id: Optional[int], event_type: str, payload: dict) -> None:
    db.add(BillingCommercialAuditEvent(
        organization_id=organization_id, actor_user_id=actor_user_id,
        event_type=event_type, payload=payload,
    ))


def _record_would_have_blocked(db: Session, organization_id: int, detail: dict) -> None:
    """Same event as entitlements._record_would_have_blocked, but added to
    the caller's transaction rather than committed on the spot: this runs
    inside bulk imports and payroll generation, where an intermediate
    commit would break their own all-or-savepoint transaction boundaries."""
    _audit(db, organization_id, None, "ENTITLEMENT_WOULD_HAVE_BLOCKED",
           {"feature_key": COUNTRY_NOT_ENTITLED, **detail})
    db.flush()


# ── The write-path gate ──────────────────────────────────────────────────

def _not_entitled_error(db: Session, organization_id: int, country_code: Optional[str],
                        rows: list[OrganizationJurisdiction]) -> ForbiddenException:
    subscription = get_active_subscription(db, organization_id)
    limit_value = resolve_country_limit(db, organization_id)
    entitled = [r.country_code for r in rows if r.status == ACTIVE]
    over_limit = [r.country_code for r in rows if r.status == OVER_LIMIT]
    plan = _plan_label(db, subscription)
    target = country_name(country_code)

    if country_code in over_limit:
        message = (
            f"{target} is paused because your {plan} plan now includes {_countries_phrase(limit_value or len(entitled))} "
            f"({_join_names(entitled)}). Existing employees there stay readable, but to add or change employees "
            f"in {target} or run payroll for them, upgrade your plan."
        )
    elif limit_value is not None and len(entitled) >= limit_value:
        message = (
            f"Your {plan} plan includes {_countries_phrase(limit_value)} ({_join_names(entitled)}). "
            f"To add employees in {target}, upgrade your plan"
            + (" or change your country under Compliance > Countries." if limit_value == 1 else ".")
        )
    else:
        message = (
            f"{target} is not one of your organization's countries ({_join_names(entitled)}). "
            f"Add it under Compliance > Countries before adding employees there."
        )
    return ForbiddenException(message, trace={
        "resource": MAX_JURISDICTIONS,
        "reason": COUNTRY_NOT_ENTITLED,
        "country_code": country_code,
        "entitled": entitled,
        "over_limit": over_limit,
        "limit_value": limit_value,
        "plan_code": _current_plan_code(db, subscription),
    })


def assert_country_allowed(db: Session, organization_id: int, country_code: Optional[str]) -> None:
    """Raise unless country_code is an ACTIVE entitled country of the org.

    off -> pass. warn -> record ENTITLEMENT_WOULD_HAVE_BLOCKED and pass.
    enforce -> ForbiddenException with a trace the frontend renders as an
    upgrade prompt. OVER_LIMIT rows are not entitled for new writes. An org
    with no limit (no subscription) has the country recorded instead.
    """
    mode = _enforcement_mode()
    if mode == "off" or organization_id is None:
        return
    code = normalize_country_code(country_code)
    rows = ensure_ledger(db, organization_id)

    if not rows:
        if mode == "warn":
            _record_would_have_blocked(db, organization_id, {"reason": "no_country", "country_code": code})
            return
        raise BadRequestException("Set your organization's country before adding employees.")

    if code is not None and any(r.country_code == code and r.status == ACTIVE for r in rows):
        return
    # No limit (no subscription: legacy / NON_CHARGEABLE): nothing to
    # exceed, so a new country is simply recorded in the ledger.
    if code is not None and resolve_country_limit(db, organization_id) is None:
        ensure_country_row(db, organization_id, code)
        return

    error = _not_entitled_error(db, organization_id, code, rows)
    if mode == "warn":
        _record_would_have_blocked(db, organization_id, {
            "reason": COUNTRY_NOT_ENTITLED, "country_code": code,
            "entitled": error.trace["entitled"], "limit_value": error.trace["limit_value"],
        })
        return
    raise error


def payroll_run_country_gate(db: Session, organization_id: int) -> Optional[Callable[[Optional[str]], Optional[str]]]:
    """For payroll generation: a function country_code -> block reason
    (None = calculate), or None when nothing is gated (mode "off").

    Resolved once per run. In "warn" mode the gate records one
    would-have-blocked event per unentitled country and never blocks.
    An employee with no country_code of their own falls back to the
    primary country, the same fallback _resolve_employee_country applies.
    """
    mode = _enforcement_mode()
    if mode == "off" or organization_id is None:
        return None
    rows = ensure_ledger(db, organization_id)
    if not rows or resolve_country_limit(db, organization_id) is None:
        return None
    entitled = {r.country_code for r in rows if r.status == ACTIVE}
    primary = next((r.country_code for r in rows if r.is_primary), None)
    warned: set = set()

    def gate(country_code: Optional[str]) -> Optional[str]:
        code = normalize_country_code(country_code) or primary
        if code in entitled:
            return None
        error = _not_entitled_error(db, organization_id, code, rows)
        if mode == "warn":
            if code not in warned:
                warned.add(code)
                _record_would_have_blocked(db, organization_id, {
                    "reason": COUNTRY_NOT_ENTITLED, "country_code": code, "context": "payroll_run",
                    "entitled": error.trace["entitled"], "limit_value": error.trace["limit_value"],
                })
            return None
        return error.message

    return gate


# ── Reconcile / backfill ─────────────────────────────────────────────────

def reconcile_jurisdiction_limit(db: Session, organization_id: int, actor_user_id: Optional[int] = None,
                                 reason: str = "plan_change") -> dict:
    """Check the org's ledger against its current country limit after a
    change. Never changes a row's status (nothing is paused, removed or
    reactivated). When the org now has more ACTIVE countries than the limit —
    a change that could not be refused (Stripe-initiated subscription change)
    or an audited Super Admin downgrade override — it is flagged for Super
    Admin review with a COUNTRY_LIMIT_REVIEW_REQUIRED audit event (one per
    distinct used/limit situation). An expired entitlement override is only
    noticed here when something next calls this (no expiry job). Does not
    commit.
    Returns {"limit_value", "over_limit_by", "flagged"}."""
    rows = _rows(db, organization_id)
    limit_value = resolve_country_limit(db, organization_id)
    active = [r.country_code for r in rows if r.status == ACTIVE]
    over_limit_by = 0 if limit_value is None else max(len(active) - limit_value, 0)
    flagged = False
    if over_limit_by:
        last = _latest_review_flag(db, organization_id)
        situation = {"used": len(active), "limit_value": limit_value}
        if last is None or {k: (last.payload or {}).get(k) for k in situation} != situation:
            _audit(db, organization_id, actor_user_id, REVIEW_EVENT, {
                "reason": reason, **situation, "over_limit_by": over_limit_by, "countries": active,
            })
            db.flush()
            flagged = True
    return {"limit_value": limit_value, "over_limit_by": over_limit_by, "flagged": flagged}


REVIEW_EVENT = "COUNTRY_LIMIT_REVIEW_REQUIRED"


def _latest_review_flag(db: Session, organization_id: int):
    return db.query(BillingCommercialAuditEvent).filter(
        BillingCommercialAuditEvent.organization_id == organization_id,
        BillingCommercialAuditEvent.event_type == REVIEW_EVENT,
    ).order_by(BillingCommercialAuditEvent.created_at.desc(), BillingCommercialAuditEvent.id.desc()).first()


def safe_reconcile(db: Session, organization_id: int, actor_user_id: Optional[int] = None,
                   reason: str = "plan_change") -> None:
    """reconcile_jurisdiction_limit for plan-change hooks (Stripe webhooks,
    trial conversion, order forms): a ledger problem must never fail the
    commercial event itself. Logged, not raised. Runs in a savepoint so a
    failure leaves the caller's own pending changes intact."""
    import logging

    try:
        with db.begin_nested():
            reconcile_jurisdiction_limit(db, organization_id, actor_user_id=actor_user_id, reason=reason)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("zoiko").warning(
            f"[billing] country-limit reconcile failed for org {organization_id}: {exc}"
        )


def backfill_organization(db: Session, organization_id: int) -> dict:
    """Seed/top up one org's ledger from what it already uses. Idempotent:
    only adds rows that are missing, then reconciles against the limit.

      1. primary = effective org country (_resolve_org_country precedence)
      2. + every distinct PayrollEmployee.country_code in use
      3. beyond the plan limit -> still ACTIVE, and the org is flagged for
         Super Admin review (no new country can be added until it is under)

    A REMOVED row is an explicit admin decision and is left REMOVED.
    Does not commit. Returns {"created", "over_limit" (countries above the
    limit — still ACTIVE), "unresolved"}.
    """
    existing = {r.country_code: r for r in _rows(db, organization_id, include_removed=True)}
    created: list[str] = []
    primary_code = _effective_org_country(db, organization_id)
    has_primary = any(r.is_primary for r in existing.values())

    def _add(code: str, is_primary: bool = False) -> None:
        row = OrganizationJurisdiction(
            organization_id=organization_id, country_code=code, is_primary=is_primary,
            status=ACTIVE, activated_at=datetime.utcnow(),
        )
        db.add(row)
        db.flush()
        existing[code] = row
        created.append(code)

    if primary_code and not has_primary:
        row = existing.get(primary_code)
        if row is None:
            _add(primary_code, is_primary=True)
        elif row.status != REMOVED:
            row.is_primary = True
            db.flush()

    employee_codes = [code for code in employee_country_counts(db, organization_id) if code]
    for raw in employee_codes:
        code = normalize_country_code(raw)
        if code and code not in existing:
            _add(code)

    result = reconcile_jurisdiction_limit(db, organization_id, reason="backfill")
    if created:
        _audit(db, organization_id, None, "JURISDICTION_LEDGER_BACKFILLED", {
            "created": created, "primary": primary_code if primary_code in created else None,
            "over_limit_by": result["over_limit_by"],
        })
        db.flush()
    # Countries above the limit, in ledger order (primary first, then oldest):
    # still ACTIVE; the reconcile above flagged the org for Super Admin review.
    active_rows = [r for r in _rows(db, organization_id) if r.status == ACTIVE]
    limit_value = result["limit_value"]
    over_limit = [] if limit_value is None else [r.country_code for r in active_rows[limit_value:]]
    return {"created": created, "over_limit": over_limit, "unresolved": primary_code is None and not has_primary}


def create_primary_for_new_org(db: Session, organization_id: int, registered_country,
                               actor_user_id: Optional[int] = None) -> Optional[OrganizationJurisdiction]:
    """Registration: the registered country becomes the primary row, in the
    caller's transaction (no commit). The registered value is a country
    name, resolved via the same helper _resolve_org_country's fallback uses."""
    code = normalize_country_code(registered_country)
    if code is None:
        return None
    row = OrganizationJurisdiction(
        organization_id=organization_id, country_code=code, is_primary=True,
        status=ACTIVE, activated_at=datetime.utcnow(), activated_by_user_id=actor_user_id,
    )
    db.add(row)
    db.flush()
    return row


def ensure_country_row(db: Session, organization_id: int, country_code: str,
                       actor_user_id: Optional[int] = None) -> OrganizationJurisdiction:
    """Make sure `country_code` has a non-REMOVED ledger row (callers have
    already run their own limit check — add_entitled_country /
    sync_primary_with_default_country). Becomes the primary only if the org has
    none yet. Does not commit."""
    code = normalize_country_code(country_code)
    if code is None:
        raise BadRequestException(f"'{country_code}' is not a recognized country.")
    ensure_ledger(db, organization_id)
    row = db.query(OrganizationJurisdiction).filter(
        OrganizationJurisdiction.organization_id == organization_id,
        OrganizationJurisdiction.country_code == code,
    ).first()
    has_primary = db.query(OrganizationJurisdiction.id).filter(
        OrganizationJurisdiction.organization_id == organization_id,
        OrganizationJurisdiction.is_primary.is_(True),
    ).first() is not None
    if row is None:
        row = OrganizationJurisdiction(
            organization_id=organization_id, country_code=code, is_primary=not has_primary,
            status=ACTIVE, activated_at=datetime.utcnow(), activated_by_user_id=actor_user_id,
        )
        db.add(row)
        db.flush()
        _audit(db, organization_id, actor_user_id, "JURISDICTION_ENTITLEMENT_ADDED",
               {"country_code": code, "source": "enterprise_jurisdiction"})
    elif row.status == REMOVED:
        row.status = ACTIVE
        row.activated_at = datetime.utcnow()
        row.activated_by_user_id = actor_user_id
        db.flush()
        _audit(db, organization_id, actor_user_id, "JURISDICTION_ENTITLEMENT_ADDED",
               {"country_code": code, "source": "enterprise_jurisdiction", "restored": True})
    reconcile_jurisdiction_limit(db, organization_id, actor_user_id=actor_user_id, reason="country_added")
    return row


# ── Org-admin management (payroll/jurisdictions_router.py) ───────────────

def employee_country_counts(db: Session, organization_id: int) -> dict:
    """{country_code: employee count} for one org, in order of each
    country's first employee. The only worker-table read in this module —
    aggregate counts, never a worker row — through the scoped query helper
    (app.core.authz.scopes) like any new PayrollEmployee query."""
    from app.core.authz.scopes import organization_scoped
    from app.modules.payroll.models import PayrollEmployee

    rows = (
        organization_scoped(db, PayrollEmployee, organization_id)
        .with_entities(PayrollEmployee.country_code, func.count(PayrollEmployee.id))
        .group_by(PayrollEmployee.country_code)
        .order_by(func.min(PayrollEmployee.id))
        .all()
    )
    return {code: int(n) for code, n in rows}


def _employee_count(db: Session, organization_id: int, country_code: str) -> int:
    return employee_country_counts(db, organization_id).get(country_code, 0)


def _onboarding_block_reason(db: Session, organization_id: int, code: str) -> Optional[str]:
    """Same gate registration uses (JurisdictionServiceRegistry availability
    + canonical pack readiness). EVALUATION workspaces are exempt, exactly
    as register_trial is exempt from it."""
    from app.modules.organizations.models import Organization
    from app.modules.payroll.engine.tax_resolver import get_jurisdiction_onboarding_block_reason

    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if org is not None and org.workspace_type == "EVALUATION":
        from app.core.jurisdiction import REGISTRATION_COUNTRIES

        names = {normalize_country_code(c) for c in REGISTRATION_COUNTRIES}
        return None if code in names else f"{country_name(code)} is not available for evaluation workspaces yet."
    return get_jurisdiction_onboarding_block_reason(db, country_name(code))


def _country_catalog(db: Session, organization_id: int, taken: set) -> list[dict]:
    """The fixed list of countries Zoiko runs payroll for (a known
    jurisdiction with an employee validation strategy), minus the org's own
    ACTIVE ones. Every country is selectable; where the onboarding check
    fails (e.g. no Active statutory pack) its reason comes back as a set-up
    note so the admin knows payroll there uses default rates for now."""
    from app.core.jurisdiction import ALL_CODE_TO_COUNTRY_NAME
    from app.modules.payroll.employee_validation import is_supported_employee_country

    result = []
    for code in sorted(ALL_CODE_TO_COUNTRY_NAME, key=lambda c: ALL_CODE_TO_COUNTRY_NAME[c]):
        if code in taken or not is_supported_employee_country(code):
            continue
        note = _onboarding_block_reason(db, organization_id, code)
        result.append({"code": code, "name": ALL_CODE_TO_COUNTRY_NAME[code],
                       "available": True, "setupPending": note is not None, "setupNote": note})
    return result


def entitlement_summary(db: Session, organization_id: int) -> dict:
    """Payload for GET /payroll/jurisdictions/entitled (camelCase, like
    the rest of the payroll API)."""
    rows = ensure_ledger(db, organization_id)
    subscription = get_active_subscription(db, organization_id)
    limit_value = resolve_country_limit(db, organization_id)
    used = sum(1 for r in rows if r.status == ACTIVE)
    counts = employee_country_counts(db, organization_id)
    taken = {r.country_code for r in rows if r.status == ACTIVE}
    catalog = _country_catalog(db, organization_id, taken)
    return {
        "countries": [{
            "code": r.country_code,
            "name": country_name(r.country_code),
            "isPrimary": bool(r.is_primary),
            "status": r.status,
            "activatedAt": r.activated_at.isoformat() if r.activated_at else None,
            "employeeCount": int(counts.get(r.country_code, 0)),
            "setupNote": _onboarding_block_reason(db, organization_id, r.country_code),
        } for r in rows],
        "limit": limit_value,
        "used": used,
        "planCode": _current_plan_code(db, subscription),
        "canAdd": limit_value is None or used < limit_value,
        # Every payroll country not yet active for the org; `addable` is the
        # subset that can be added right now (kept for existing callers).
        "catalog": catalog,
        "addable": [{"code": c["code"], "name": c["name"]} for c in catalog if c["available"]],
        "remaining": None if limit_value is None else max(limit_value - used, 0),
        # Countries above the limit (a downgrade / override expiry): all keep
        # working, but none can be added until this is back to 0.
        "overLimitBy": 0 if limit_value is None else max(used - limit_value, 0),
        # The country limit is always enforced on add (see the module docstring);
        # employee / payroll gates still follow the billing enforcement mode.
        "countryLimitEnforced": True,
        "upgradePath": UPGRADE_PATH,
        "enforcementMode": _enforcement_mode(),
    }


def _get_row(db: Session, organization_id: int, code: str) -> Optional[OrganizationJurisdiction]:
    return db.query(OrganizationJurisdiction).filter(
        OrganizationJurisdiction.organization_id == organization_id,
        OrganizationJurisdiction.country_code == code,
    ).first()


def _require_code(country_code) -> str:
    code = normalize_country_code(country_code)
    if code is None:
        raise BadRequestException(f"'{country_code}' is not a recognized country.")
    return code


def _sync_default_country(db: Session, organization_id: int, code: str) -> None:
    """CompanyComplianceDetails.jurisdiction_country is the org's default
    country and is kept equal to the primary row. The state belonged to
    the previous default country, so it is cleared (same rule the
    Enterprise verify flow used)."""
    from app.modules.payroll.service import get_company_details

    company = get_company_details(db, organization_id)
    if company.jurisdiction_country != code:
        company.jurisdiction_country = code
        company.jurisdiction_state = None


def _require_payroll_country(code: str) -> None:
    """Only countries Zoiko has a payroll engine for (the fixed catalog) can
    be added — an employee could not even be created anywhere else."""
    from app.modules.payroll.employee_validation import is_supported_employee_country

    if not is_supported_employee_country(code):
        raise BadRequestException(f"{country_name(code)} is not a country Zoiko runs payroll for yet.")


COUNTRY_LIMIT_REACHED = "country_limit_reached"
UPGRADE_PATH = "/billing/plans"


def country_limit_error(db: Session, organization_id: int, country_code: Optional[str],
                        used: int, limit_value: int) -> ForbiddenException:
    """403 for adding a country at/over the plan's limit. The trace carries
    what the frontend needs for the "Upgrade plan" prompt."""
    subscription = get_active_subscription(db, organization_id)
    plan = _plan_label(db, subscription)
    target = country_name(country_code)
    if used > limit_value:
        message = (
            f"Your {plan} plan includes {_countries_phrase(limit_value)} and your organization already has {used}. "
            f"Your existing countries keep working, but {target} can't be added until you upgrade your plan "
            f"or remove {_countries_phrase(used - limit_value + 1)}."
        )
    else:
        message = (
            f"Your {plan} plan includes {_countries_phrase(limit_value)} and all are in use. "
            f"Upgrade your plan to add {target}."
        )
    return ForbiddenException(message, trace={
        "resource": MAX_JURISDICTIONS,
        "reason": COUNTRY_LIMIT_REACHED,
        "country_code": country_code,
        "limit_value": limit_value,
        "used": used,
        "over_limit_by": max(used - limit_value, 0),
        "plan_code": _current_plan_code(db, subscription),
        "upgrade_path": UPGRADE_PATH,
    })


def _require_country_slot(db: Session, organization_id: int, country_code: Optional[str],
                          rows: list[OrganizationJurisdiction]) -> None:
    """Raise unless the org can take one more country. Independent of
    BILLING_ENFORCEMENT_MODE: the country limit is always enforced on add."""
    limit_value = resolve_country_limit(db, organization_id)
    used = sum(1 for r in rows if r.status == ACTIVE)
    if limit_value is not None and used >= limit_value:
        _audit(db, organization_id, None, "JURISDICTION_ADD_REFUSED", {
            "country_code": country_code, "used": used, "limit_value": limit_value,
        })
        db.commit()
        raise country_limit_error(db, organization_id, country_code, used, limit_value)


def add_entitled_country(db: Session, current_user, country_code) -> dict:
    """Any country in the fixed payroll catalog can be added, within the
    plan's max_jurisdictions (counting the primary) and unless dunning
    restricts expansion. The limit is enforced in every billing enforcement
    mode (403 with an upgrade trace). A country whose statutory set-up isn't
    complete (the onboarding check) is still added — recorded with that note
    and shown as "set-up pending"; its payroll uses the default rates."""
    organization_id = current_user.organization_id
    code = _require_code(country_code)
    require_not_dunning_restricted(DunningStage.RESTRICT_EXPANSION.value)(current_user=current_user, db=db)

    rows = ensure_ledger(db, organization_id)
    row = _get_row(db, organization_id, code)
    if row is not None and row.status == ACTIVE:
        return entitlement_summary(db, organization_id)

    _require_payroll_country(code)
    setup_note = _onboarding_block_reason(db, organization_id, code)

    used = sum(1 for r in rows if r.status == ACTIVE)
    _require_country_slot(db, organization_id, code, rows)

    has_primary = any(r.is_primary for r in rows)
    if row is None:
        row = OrganizationJurisdiction(organization_id=organization_id, country_code=code)
        db.add(row)
    row.status = ACTIVE
    row.is_primary = bool(row.is_primary) or not has_primary
    row.activated_at = datetime.utcnow()
    row.activated_by_user_id = current_user.id
    db.flush()
    if row.is_primary:
        _sync_default_country(db, organization_id, code)
    _audit(db, organization_id, current_user.id, "JURISDICTION_ENTITLEMENT_ADDED",
           {"country_code": code, "source": "countries_panel", "used_after": used + 1,
            "setup_pending": setup_note})
    db.commit()
    db.refresh(row)
    _seed_country_holidays(db, organization_id, code)
    _notify_country_added(db, row, organization_id)
    return entitlement_summary(db, organization_id)


def _seed_country_holidays(db: Session, organization_id: int, code: str) -> None:
    """A newly added country's public holidays for the current year, so its
    employees' working days are right from the first run (same seeding the
    Enterprise jurisdiction flow does on add)."""
    from app.modules.payroll.service import ensure_holidays_seeded

    ensure_holidays_seeded(db, organization_id, datetime.utcnow().year, countries=[code])


def set_primary_country(db: Session, current_user, country_code) -> dict:
    organization_id = current_user.organization_id
    code = _require_code(country_code)
    ensure_ledger(db, organization_id)
    row = _get_row(db, organization_id, code)
    if row is None or row.status != ACTIVE:
        raise BadRequestException(
            f"{country_name(code)} is not an active country for your organization. Add it before making it primary."
        )
    if row.is_primary:
        return entitlement_summary(db, organization_id)
    old = db.query(OrganizationJurisdiction).filter(
        OrganizationJurisdiction.organization_id == organization_id,
        OrganizationJurisdiction.is_primary.is_(True),
    ).first()
    if old is not None:
        old.is_primary = False
        db.flush()  # the partial unique index allows one primary at a time
    row.is_primary = True
    db.flush()
    _sync_default_country(db, organization_id, code)
    _audit(db, organization_id, current_user.id, "JURISDICTION_PRIMARY_CHANGED",
           {"from": old.country_code if old else None, "to": code})
    db.commit()
    return entitlement_summary(db, organization_id)


def remove_entitled_country(db: Session, current_user, country_code) -> dict:
    organization_id = current_user.organization_id
    code = _require_code(country_code)
    rows = ensure_ledger(db, organization_id)
    row = _get_row(db, organization_id, code)
    if row is None or row.status == REMOVED:
        raise BadRequestException(f"{country_name(code)} is not one of your organization's countries.")
    if row.is_primary:
        raise ConflictException(
            f"{country_name(code)} is your primary country and can't be removed. "
            "Make another country primary first."
        )
    if len(rows) <= 1:
        raise ConflictException(f"{country_name(code)} is your only country and can't be removed.")
    employees = _employee_count(db, organization_id, code)
    if employees:
        raise ConflictException(
            f"{country_name(code)} still has {employees} employee{'s' if employees != 1 else ''}. "
            f"Move or delete them before removing the country.",
            trace={"country_code": code, "employee_count": employees},
        )
    row.status = REMOVED
    db.flush()
    _audit(db, organization_id, current_user.id, "JURISDICTION_ENTITLEMENT_REMOVED", {"country_code": code})
    # Freeing a slot can restore an OVER_LIMIT country.
    reconcile_jurisdiction_limit(db, organization_id, actor_user_id=current_user.id, reason="country_removed")
    db.commit()
    return entitlement_summary(db, organization_id)


def replace_primary_country(db: Session, current_user, country_code) -> dict:
    """One-country plans: swap the only country. Allowed only when no
    employee remains in the old country."""
    organization_id = current_user.organization_id
    code = _require_code(country_code)
    ensure_ledger(db, organization_id)
    old = db.query(OrganizationJurisdiction).filter(
        OrganizationJurisdiction.organization_id == organization_id,
        OrganizationJurisdiction.is_primary.is_(True),
    ).first()
    if old is not None and old.country_code == code:
        return entitlement_summary(db, organization_id)
    if old is not None:
        employees = _employee_count(db, organization_id, old.country_code)
        if employees:
            raise ConflictException(
                f"You can't change your country from {country_name(old.country_code)} while it has "
                f"{employees} employee{'s' if employees != 1 else ''}. Move or delete them first — "
                f"payroll history stays tied to the country it was run in.",
                trace={"country_code": old.country_code, "employee_count": employees},
            )
    _require_payroll_country(code)

    if old is not None:
        old.is_primary = False
        old.status = REMOVED
        db.flush()
    row = _get_row(db, organization_id, code)
    if row is None:
        row = OrganizationJurisdiction(organization_id=organization_id, country_code=code)
        db.add(row)
    row.is_primary = True
    row.status = ACTIVE
    row.activated_at = datetime.utcnow()
    row.activated_by_user_id = current_user.id
    db.flush()
    _sync_default_country(db, organization_id, code)
    _audit(db, organization_id, current_user.id, "JURISDICTION_PRIMARY_REPLACED",
           {"from": old.country_code if old else None, "to": code})
    reconcile_jurisdiction_limit(db, organization_id, actor_user_id=current_user.id, reason="primary_replaced")
    db.commit()
    db.refresh(row)
    _seed_country_holidays(db, organization_id, code)
    _notify_country_added(db, row, organization_id)
    return entitlement_summary(db, organization_id)


def sync_primary_with_default_country(db: Session, organization_id: int, raw_country,
                                      actor_user_id: Optional[int] = None) -> None:
    """Compliance > Company Details' one-time jurisdiction choice
    (payroll.service.update_company_details) sets the default country; the
    primary ledger row follows it. Choosing a country the org doesn't have
    while it is at its limit is an add, so it is refused like one (every
    enforcement mode). Does not commit."""
    code = normalize_country_code(raw_country)
    if code is None:
        return
    rows = ensure_ledger(db, organization_id)
    primary = next((r for r in rows if r.is_primary), None)
    if primary is not None and primary.country_code == code:
        return
    row = _get_row(db, organization_id, code)
    if row is None or row.status != ACTIVE:
        limit_value = resolve_country_limit(db, organization_id)
        used = sum(1 for r in rows if r.status == ACTIVE)
        if limit_value is not None and used >= limit_value:
            raise country_limit_error(db, organization_id, code, used, limit_value)
        row = ensure_country_row(db, organization_id, code, actor_user_id=actor_user_id)
    if not row.is_primary:
        if primary is not None:
            primary.is_primary = False
            db.flush()
        row.is_primary = True
        row.status = ACTIVE
        db.flush()
        _audit(db, organization_id, actor_user_id, "JURISDICTION_PRIMARY_CHANGED",
               {"from": primary.country_code if primary else None, "to": code, "source": "company_details"})
    reconcile_jurisdiction_limit(db, organization_id, actor_user_id=actor_user_id, reason="default_country_set")


def _notify_country_added(db: Session, row: OrganizationJurisdiction, organization_id: int) -> None:
    """The jurisdiction-added email, keyed on the ledger row."""
    import logging

    logger = logging.getLogger("zoiko")
    try:
        from app.services.email_service import _get_org_contact_email, send_jurisdiction_added_email

        org_email = _get_org_contact_email(db, organization_id)
        if not org_email:
            return
        from app.modules.communications.service import idempotency_key, queue_email

        queue_email(
            "payroll", "payroll.jurisdiction_added", None, org_email,
            idempotency_key(organization_id, "payroll.jurisdiction_added", org_email, None,
                            f"entitlement:{row.id}:{row.activated_at.isoformat()}"),
            send_jurisdiction_added_email, org_email, country_name(row.country_code), row.country_code,
            send_kwargs={"organization_id": organization_id},
            organization_id=organization_id, db=db,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[billing] country-added email failed for org {organization_id}: {exc}")


# ── Super Admin read model ───────────────────────────────────────────────

def org_country_usage(db: Session, organization_id: int) -> dict:
    """Read-only (never seeds): used/limit/over-limit counts for the
    Subscriptions & Billing table."""
    rows = _rows(db, organization_id)
    used = sum(1 for r in rows if r.status == ACTIVE)
    limit_value = resolve_country_limit(db, organization_id)
    paused = sum(1 for r in rows if r.status == OVER_LIMIT)
    return {
        "countries_used": used,
        "countries_limit": limit_value,
        # Countries above the limit: legacy paused (OVER_LIMIT) rows plus
        # ACTIVE countries beyond the limit after an unrefusable change.
        "countries_over_limit": paused + (0 if limit_value is None else max(used - limit_value, 0)),
    }


def find_country_limit_exceptions(db: Session) -> list[dict]:
    """Orgs for Super Admin review: more ACTIVE countries than their limit
    (an unrefusable or overridden downgrade — they can't add more), legacy
    OVER_LIMIT rows, or employees in a country that is not ACTIVE-entitled.
    Each carries the latest review flag (when and why). Aggregate counts per
    country only — no employee-level data."""
    from app.modules.organizations.models import Organization

    ledger: dict = {}
    for row in db.query(OrganizationJurisdiction).filter(OrganizationJurisdiction.status != REMOVED).all():
        ledger.setdefault(row.organization_id, []).append(row)

    result = []
    for org_id, name in db.query(Organization.id, Organization.organization_name).all():
        rows = ledger.get(org_id, [])
        if not rows:
            continue  # not seeded yet — the backfill report covers these
        active = {r.country_code for r in rows if r.status == ACTIVE}
        primary = next((r.country_code for r in rows if r.is_primary), None)
        over_limit = sorted(r.country_code for r in rows if r.status == OVER_LIMIT)
        unentitled = [
            {"country_code": normalize_country_code(code) or primary, "employee_count": n}
            for code, n in employee_country_counts(db, org_id).items()
            if (normalize_country_code(code) or primary) not in active
        ]
        limit_value = resolve_country_limit(db, org_id)
        if over_limit or unentitled or (limit_value is not None and len(active) > limit_value):
            result.append({
                "organization_id": org_id,
                "organization_name": name,
                "plan_code": _current_plan_code(db, get_active_subscription(db, org_id)),
                "countries_used": len(active),
                "countries_limit": limit_value,
                "over_limit_countries": over_limit,
                "unentitled_employee_countries": unentitled,
                "review_reason": _review_reason(db, org_id),
            })
    return result


def _review_reason(db: Session, organization_id: int) -> Optional[dict]:
    flag = _latest_review_flag(db, organization_id)
    if flag is None:
        return None
    payload = flag.payload or {}
    return {"at": flag.created_at.isoformat() if flag.created_at else None, "reason": payload.get("reason"),
            "used": payload.get("used"), "limit_value": payload.get("limit_value")}
