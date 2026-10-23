"""
payroll/mexico_dormancy.py
--------------------------
Mexico (ZP-MX-ENG-001) dormancy switch — Phase 4a.

Merging to main deploys to production, so Mexico must stay dormant there
until the release gates G1–G8 are signed. One setting,
`MX_TENANT_ONBOARDING_ENABLED` (default False, unset in production), decides
whether an organisation may become Mexican or use the Mexico organisation
API at all:

  * `Organization.country` → Mexico (org admin `PUT /organizations/me` and
    the Super Admin organization update) — via
    tax_resolver.get_jurisdiction_change_block_reason;
  * the payroll company jurisdiction → MX (`update_company_details`) and the
    Organization.country → jurisdiction back-fill in `get_company_details`;
  * every `/api/payroll/mexico/...` route (mexico_org_router) — which, with
    the flag on, still requires the caller's organisation to be Mexican.

Deliberately dependency-free (settings + the jurisdiction code map only) so
the engine-level tax_resolver can import it without a cycle (every database
lookup below is a lazy import).

Phase 10e (docs/mexico/MEXICO_PHASE_10E_PLAN.md, approved 2026-10-22): the
flag is a KILL SWITCH only — required, never sufficient. Mexico is open for
an organisation only when the flag is on AND either

  * general availability: the Mexico service registry is AVAILABLE (the
    platform refuses that transition unless G1–G8 are SIGNED, Q9 is RECORDED
    and MX_IDENTITY_TOKEN_KEY is configured), and the organisation is not a
    pilot organisation; or
  * pilot: the organisation has an APPROVED, unexpired, unrevoked pilot grant
    (four-eyes). An organisation that ever had an approved grant is a pilot
    organisation for good — its output is non-binding, and it never becomes
    live (D5: a new live organisation receives a governed copy of its master
    data).

Without a database session the answer is closed (fail closed).
"""

from __future__ import annotations

from typing import Optional

MX = "MX"
DORMANT_MESSAGE = ("Mexico is not open for onboarding on this platform yet — Mexican payroll stays disabled "
                   "until its release gates (G1–G8) are signed.")
PAUSED_MESSAGE = ("New Mexican organisations are paused on this platform (runbook §6) — organisations that are "
                  "already Mexican keep running; a new one can be onboarded once the pause is lifted.")


def flag_enabled() -> bool:
    """The deployment kill switch (never sufficient on its own)."""
    from app.config import settings

    return bool(getattr(settings, "MX_TENANT_ONBOARDING_ENABLED", False))


def registry_available(db) -> bool:
    from app.modules.billing.models import JurisdictionServiceRegistry

    row = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == MX).first()
    return row is not None and row.availability == "AVAILABLE"


def _utcnow():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def _aware(dt):
    from datetime import timezone

    return dt if dt is None or dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def active_pilot_grant(db, org_id: Optional[int]):
    """The organisation's APPROVED, unexpired grant, or None."""
    if org_id is None:
        return None
    from app.modules.payroll.models import PayrollMxPilotGrant as G

    now = _utcnow()
    for g in (db.query(G).filter(G.organization_id == org_id, G.status == "APPROVED").order_by(G.id.desc())):
        if _aware(g.expires_at) > now:
            return g
    return None


def is_pilot_organization(db, org_id: Optional[int]) -> bool:
    """Ever had an APPROVED grant (active, revoked or expired): pilot rules for good."""
    if org_id is None:
        return False
    from app.modules.payroll.models import PayrollMxPilotGrant as G

    return db.query(G.id).filter(G.organization_id == org_id, G.approved_at.isnot(None)).first() is not None


def any_active_pilot(db) -> bool:
    from app.modules.payroll.models import PayrollMxPilotGrant as G

    now = _utcnow()
    return any(_aware(g.expires_at) > now for g in db.query(G).filter(G.status == "APPROVED"))


def onboarding_enabled(db=None, org_id: Optional[int] = None) -> bool:
    """Is Mexico open — for `org_id`, or (org_id None) on the platform at all?
    Kill switch first; then pilot organisations by their grant only, every
    other organisation by general availability."""
    if not flag_enabled() or db is None:
        return False
    if org_id is not None:
        if is_pilot_organization(db, org_id):
            return active_pilot_grant(db, org_id) is not None
        return registry_available(db)
    return registry_available(db) or any_active_pilot(db)


def onboarding_paused(db) -> bool:
    """Phase 10g: the "no new Mexican organisations" switch — the latest
    APPROVED change is a PAUSE. Closed (paused) without a session."""
    if db is None:
        return True
    from app.modules.payroll.models import PayrollMxOnboardingPause as P

    latest = (db.query(P).filter(P.status == "APPROVED")
              .order_by(P.approved_at.desc(), P.id.desc()).first())
    return latest is not None and latest.action == "PAUSE"


def pilot_active(db, org_id: Optional[int]) -> bool:
    """Open AND under pilot rules (non-binding output)."""
    return flag_enabled() and db is not None and active_pilot_grant(db, org_id) is not None


def is_mexico(country: Optional[str]) -> bool:
    """Code or name, any case/accent the jurisdiction registry knows. Blank or
    unknown is never Mexico (unlike payroll.service._normalize_country, which
    defaults blanks to IN)."""
    if not country:
        return False
    from app.core.jurisdiction import get_jurisdiction_code

    return get_jurisdiction_code(country) == MX


def entering_mexico_refusal(old_country: Optional[str], new_country: Optional[str], db=None,
                            org_id: Optional[int] = None) -> Optional[str]:
    """The refusal message when a change would move an organisation INTO
    Mexico while Mexico is not open for it; None otherwise (including any
    change that does not involve Mexico, and an org that is already Mexican).
    Without a session the change is refused (fail closed)."""
    if is_mexico(new_country) and not is_mexico(old_country):
        if not onboarding_enabled(db, org_id):
            return DORMANT_MESSAGE
        if onboarding_paused(db):                     # Phase 10g: no NEW Mexican organisations
            return PAUSED_MESSAGE
    return None
