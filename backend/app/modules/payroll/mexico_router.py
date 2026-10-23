"""
payroll/mexico_router.py
------------------------
Super Admin API for the Mexico workspace (ZP-MX-ENG-001), mounted under
/api/super-admin/compliance/mexico.

Rules every route follows (same as netherlands_router.py):
  * Super Admin only (get_current_super_admin).
  * Organisation-scoped data needs an explicit `org_id` — there is no default
    organisation.
  * Statutory pack content is READ-ONLY here: it changes only through the
    governed pack lifecycle (Draft -> review -> approve -> activate).
  * Content is read as legally in force on an explicit `on` date; when it is
    omitted the pack's own effective_from is used — never the server date.

Employer-profile routes arrive with their table in Phase 3.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_super_admin
from app.database import get_db
from app.modules.payroll.mexico_schemas import (
    MXCatalogEntryCreate, MXClassificationArchive, MXClassificationCreate, MXPinnedSetLoad, MXReadinessResponse,
    MXReleaseCreate, MXSystemConceptCreate,
)

router = APIRouter(prefix="/super-admin/compliance/mexico", tags=["Mexico (Super Admin)"])


def _mx():
    from app.modules.payroll import mexico_service

    return mexico_service


def _actor(user) -> Optional[int]:
    return getattr(user, "id", None)


@router.get("/readiness", response_model=MXReadinessResponse,
            summary="Gate G1–G8 states and engine version (spec §22)")
def get_readiness(current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return _mx().statutory_summary(db)


# ── organisations & employees ────────────────────────────────────────────────

@router.get("/organizations", summary="Organisations with Mexico employees")
def list_organizations(current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return _mx().list_organizations(db)


@router.get("/employees", summary="Mexico employees of one organisation (explicit org_id)")
def list_employees(org_id: int = Query(...), current_user=Depends(get_current_super_admin),
                   db: Session = Depends(get_db)):
    return _mx().list_employees(db, org_id)


# ── packs & activation readiness ─────────────────────────────────────────────

@router.get("/packs", summary="Mexico national and state ISN packs")
def list_packs(current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return _mx().list_packs(db)


@router.get("/packs/{pack_row_id}/activation-readiness",
            summary="Every Mexico activation condition, met/unmet with its reason, plus warnings")
def get_activation_readiness(pack_row_id: int, current_user=Depends(get_current_super_admin),
                             db: Session = Depends(get_db)):
    return _mx().activation_readiness(db, pack_row_id, actor_id=_actor(current_user))


# ── read-only statutory content (date-selected) ──────────────────────────────

def _view(db, family, on, pack_id):
    return _mx().content_view(db, family, on=on, pack_row_id=pack_id)


@router.get("/isr-tariffs", summary="Art. 96 ISR tariffs in force on `on` (read-only)")
def isr_tariffs(on: Optional[date] = Query(None), pack_id: Optional[int] = Query(None),
                current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return _view(db, "isr", on, pack_id)


@router.get("/uma-min-wage", summary="UMA, employment subsidy and minimum wages in force on `on` (read-only)")
def uma_min_wage(on: Optional[date] = Query(None), pack_id: Optional[int] = Query(None),
                 current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return {"uma": _view(db, "uma", on, pack_id), "minimumWages": _view(db, "minwage", on, pack_id)}


@router.get("/imss-branches", summary="IMSS branches and the SBC ceiling in force on `on` (read-only)")
def imss_branches(on: Optional[date] = Query(None), pack_id: Optional[int] = Query(None),
                  current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return _view(db, "imss", on, pack_id)


@router.get("/ceav-schedule", summary="2026 seeded CEAV bands + the full 2023–2030 content schedule (read-only)")
def ceav_schedule(on: Optional[date] = Query(None), pack_id: Optional[int] = Query(None),
                  current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return _view(db, "ceav", on, pack_id)


@router.get("/infonavit", summary="INFONAVIT employer contribution in force on `on` (read-only)")
def infonavit(on: Optional[date] = Query(None), pack_id: Optional[int] = Query(None),
              current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return _view(db, "infonavit", on, pack_id)


@router.get("/benefits-workweek", summary="Benefit floors, vacation schedule and workweek in force on `on` (read-only)")
def benefits_workweek(on: Optional[date] = Query(None), pack_id: Optional[int] = Query(None),
                      current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return _view(db, "benefits", on, pack_id)


@router.get("/isn-states", summary="The 32 federal entities with ISN pack and readiness state (MX-045)")
def isn_states(current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return _mx().isn_states(db)


# ── earning classifications (MX-005 / MX-006) ────────────────────────────────

@router.get("/earning-classifications", summary="Canonical (no org_id) or one organisation's classifications")
def list_classifications(org_id: Optional[int] = Query(None), on: Optional[date] = Query(None),
                         current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return _mx().list_classifications(db, organization_id=org_id, on=on)


@router.post("/earning-classifications", summary="Create a new classification version (DRAFT)")
def create_classification(body: MXClassificationCreate, current_user=Depends(get_current_super_admin),
                          db: Session = Depends(get_db)):
    return _mx().create_classification(db, body.to_service(), _actor(current_user))


@router.post("/earning-classifications/{classification_id}/approve",
             summary="Second Super Admin approves a DRAFT (DRAFT -> ACTIVE, prior version SUPERSEDED)")
def approve_classification(classification_id: int, current_user=Depends(get_current_super_admin),
                           db: Session = Depends(get_db)):
    return _mx().approve_classification(db, classification_id, _actor(current_user))


@router.post("/earning-classifications/{classification_id}/archive", summary="Archive a DRAFT or ACTIVE row")
def archive_classification(classification_id: int, body: MXClassificationArchive,
                           current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return _mx().archive_classification(db, classification_id, _actor(current_user), body.reason)


# ── CFDI schema releases & catalog entries (MX-015) ──────────────────────────

@router.get("/cfdi-catalogs", summary="CFDI 4.0 + Nómina 1.2 schema releases")
def list_releases(current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return _mx().list_releases(db)


@router.post("/cfdi-catalogs", summary="Register a schema release (Draft)")
def create_release(body: MXReleaseCreate, current_user=Depends(get_current_super_admin),
                   db: Session = Depends(get_db)):
    return _mx().create_release(db, body.to_service(), _actor(current_user))


def _cfdi_catalogs():
    from app.modules.payroll import mexico_cfdi_catalog_service

    return mexico_cfdi_catalog_service


@router.get("/cfdi-catalogs/pinned-sets", summary="Pinned SAT schema sets (Phase 11a) and their verification")
def list_pinned_sets(current_user=Depends(get_current_super_admin)):
    return _cfdi_catalogs().pinned_sets()


@router.get("/cfdi-catalogs/{release_id}/entries", summary="Catalog entries of one release (filtered, capped)")
def list_entries(release_id: int, catalog: Optional[str] = Query(None), q: Optional[str] = Query(None),
                 limit: int = Query(200, ge=1, le=1000), current_user=Depends(get_current_super_admin),
                 db: Session = Depends(get_db)):
    return _cfdi_catalogs().list_entries(db, release_id, catalog=catalog, q=q, limit=limit)


@router.post("/cfdi-catalogs/{release_id}/load-pinned", summary="Load a pinned SAT set into an empty Draft release")
def load_pinned_set(release_id: int, body: MXPinnedSetLoad, current_user=Depends(get_current_super_admin),
                    db: Session = Depends(get_db)):
    return _cfdi_catalogs().load_pinned_set(db, release_id, body.setId, _actor(current_user))


@router.post("/cfdi-catalogs/{release_id}/entries", summary="Add a catalog entry to a Draft release")
def add_entry(release_id: int, body: MXCatalogEntryCreate, current_user=Depends(get_current_super_admin),
              db: Session = Depends(get_db)):
    return _mx().add_catalog_entry(db, release_id, body.to_service(), _actor(current_user))


@router.put("/cfdi-catalogs/{release_id}/{action}",
            summary="submit / approve / activate / supersede (activate is refused in Phase 2)")
def transition_release(release_id: int, action: str, current_user=Depends(get_current_super_admin),
                       db: Session = Depends(get_db)):
    return _mx().transition_release(db, release_id, action, _actor(current_user))


# ── Phase 11a — SAT codes for engine-produced amounts (maker-checker, D4) ──────

@router.get("/cfdi-system-concepts", summary="System-concept SAT code mappings (per schema release)")
def list_system_concepts(release_id: Optional[int] = Query(None, alias="releaseId"),
                         current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return _cfdi_catalogs().list_system_concepts(db, release_id)


@router.post("/cfdi-system-concepts", summary="Propose the SAT code of an engine-produced amount")
def propose_system_concept(body: MXSystemConceptCreate, current_user=Depends(get_current_super_admin),
                           db: Session = Depends(get_db)):
    return _cfdi_catalogs().propose_system_concept(db, body.to_service(), _actor(current_user))


@router.post("/cfdi-system-concepts/{concept_id}/approve", summary="Approve a proposed mapping (a different Super Admin)")
def approve_system_concept(concept_id: int, current_user=Depends(get_current_super_admin),
                           db: Session = Depends(get_db)):
    return _cfdi_catalogs().approve_system_concept(db, concept_id, _actor(current_user))


@router.post("/cfdi-system-concepts/{concept_id}/withdraw", summary="Withdraw a proposed mapping")
def withdraw_system_concept(concept_id: int, current_user=Depends(get_current_super_admin),
                            db: Session = Depends(get_db)):
    return _cfdi_catalogs().withdraw_system_concept(db, concept_id, _actor(current_user))


# ── Phase 3 — employers, read-only (tenant facts are authored by the org; Q5) ──

def _emp():
    from app.modules.payroll import mexico_employer_service

    return mexico_employer_service


@router.get("/employers", summary="One organisation's legal employers (read-only, RFC masked)")
def sa_list_employers(organization_id: int = Query(...), current_user=Depends(get_current_super_admin),
                      db: Session = Depends(get_db)):
    _mx()._org(db, organization_id)
    return _emp().list_employers(db, organization_id, masked=True)


@router.get("/employers/{employer_id}", summary="One legal employer with panels A–G (read-only, identifiers masked)")
def sa_employer_detail(employer_id: int, organization_id: int = Query(...),
                       current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    _mx()._org(db, organization_id)
    return _emp().employer_detail(db, organization_id, employer_id, masked=True)


@router.get("/employer-readiness", summary="One organisation's employer readiness on an explicit date (read-only)")
def sa_employer_readiness(organization_id: int = Query(...), on: date = Query(...),
                          current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    _mx()._org(db, organization_id)
    return _emp().organisation_readiness(db, organization_id, on, masked=True)


@router.get("/employer-readiness/summary", summary="Per-gate employer readiness counts on an explicit date")
def sa_employer_readiness_summary(on: date = Query(...), current_user=Depends(get_current_super_admin),
                                  db: Session = Depends(get_db)):
    return _emp().readiness_summary(db, on)


@router.get("/employees/{employee_id}", summary="One Mexican employee's record and readiness (read-only, masked)")
def sa_employee_record(employee_id: int, organization_id: int = Query(...), on: date = Query(...),
                       current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import mexico_employee_service

    _mx()._org(db, organization_id)
    record = mexico_employee_service.employee_record(db, organization_id, employee_id)
    record["readiness"] = mexico_employee_service.employee_readiness(db, organization_id, employee_id, on)
    return record


@router.get("/cfdi", summary="CFDI lifecycle — read-only counts by status, UNKNOWN items, the pinned schema release")
def sa_cfdi_lifecycle(organization_id: Optional[int] = Query(None), current_user=Depends(get_current_super_admin),
                      db: Session = Depends(get_db)):
    from app.modules.payroll import mexico_cfdi_service

    if organization_id is not None:
        _mx()._org(db, organization_id)
    out = mexico_cfdi_service.lifecycle_overview(db, organization_id)
    # ZP-PRIV B.1: the platform plane gets counts only. UNKNOWN documents name
    # an employee, run and payslip - the organization resolves them in its own
    # workspace (or Zoiko support through an approved Support Access grant).
    out["unknownCount"] = len(out.pop("unknown", None) or [])
    return out


@router.get("/authorities", summary="Authorities — read-only counts (movements, liabilities, SUA, ISN) and the blocks")
def sa_authorities(organization_id: Optional[int] = Query(None), current_user=Depends(get_current_super_admin),
                   db: Session = Depends(get_db)):
    from app.modules.payroll import mexico_imss_service

    if organization_id is not None:
        _mx()._org(db, organization_id)
    return mexico_imss_service.overview(db, organization_id)


# ── Phase 10e: pilot grants and the master-data copy (Super Admin, four-eyes) ──

def _pilot():
    from app.modules.payroll import mexico_pilot_service

    return mexico_pilot_service


@router.get("/pilot-grants", summary="Mexico pilot grants (named organisations, non-binding)")
def list_pilot_grants(current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return {"grants": _pilot().list_grants(db), "preconditions": _pilot().pilot_preconditions(db)}


@router.post("/pilot-grants", summary="Propose a pilot grant for one EVALUATION organisation")
def propose_pilot_grant(body: Dict[str, Any] = Body(...), current_user=Depends(get_current_super_admin),
                        db: Session = Depends(get_db)):
    org_id = body.get("organizationId")
    if not isinstance(org_id, int):
        from app.core.exceptions import BadRequestException

        raise BadRequestException("organizationId is required")
    return _pilot().propose_grant(db, org_id, body, _actor(current_user))


@router.post("/pilot-grants/{grant_id}/approve", summary="Approve a pilot grant (a different Super Admin)")
def approve_pilot_grant(grant_id: int, current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return _pilot().approve_grant(db, grant_id, _actor(current_user))


@router.post("/pilot-grants/{grant_id}/withdraw", summary="Withdraw a proposed pilot grant")
def withdraw_pilot_grant(grant_id: int, body: Dict[str, Any] = Body(default={}),
                         current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return _pilot().withdraw_grant(db, grant_id, str(body.get("reason") or ""), _actor(current_user))


@router.post("/pilot-grants/{grant_id}/revoke", summary="Revoke an approved pilot grant (takes effect at once)")
def revoke_pilot_grant(grant_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_super_admin),
                       db: Session = Depends(get_db)):
    return _pilot().revoke_grant(db, grant_id, str(body.get("reason") or ""), _actor(current_user))


@router.get("/master-copies", summary="Governed copies of a pilot's master data into a live organisation")
def list_master_copies(current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return _pilot().list_copies(db)


@router.post("/master-copies", summary="Propose copying a pilot's master data into a new live organisation")
def propose_master_copy(body: Dict[str, Any] = Body(...), current_user=Depends(get_current_super_admin),
                        db: Session = Depends(get_db)):
    source, target = body.get("sourceOrganizationId"), body.get("targetOrganizationId")
    if not isinstance(source, int) or not isinstance(target, int):
        from app.core.exceptions import BadRequestException

        raise BadRequestException("sourceOrganizationId and targetOrganizationId are required")
    return _pilot().propose_copy(db, source, target, str(body.get("reason") or ""), _actor(current_user))


@router.post("/master-copies/{copy_id}/approve", summary="Approve and execute a master-data copy (a different Super Admin)")
def approve_master_copy(copy_id: int, current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return _pilot().approve_copy(db, copy_id, _actor(current_user))


@router.post("/master-copies/{copy_id}/cancel", summary="Cancel a proposed master-data copy")
def cancel_master_copy(copy_id: int, body: Dict[str, Any] = Body(default={}),
                       current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return _pilot().cancel_copy(db, copy_id, str(body.get("reason") or ""), _actor(current_user))


# ── Phase 10g: the "no new Mexican organisations" switch (Super Admin, four-eyes) ──

@router.get("/onboarding-pause", summary="Whether new Mexican organisations are paused, with every change")
def onboarding_pause_state(current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return _pilot().onboarding_pause_state(db)


@router.post("/onboarding-pause", summary="Propose PAUSE or RESUME of new Mexican organisations")
def propose_onboarding_change(body: Dict[str, Any] = Body(...), current_user=Depends(get_current_super_admin),
                              db: Session = Depends(get_db)):
    return _pilot().propose_onboarding_change(db, body, _actor(current_user))


@router.post("/onboarding-pause/{pause_id}/approve", summary="Approve a pause / resume (a different Super Admin)")
def approve_onboarding_change(pause_id: int, current_user=Depends(get_current_super_admin),
                              db: Session = Depends(get_db)):
    return _pilot().approve_onboarding_change(db, pause_id, _actor(current_user))


@router.post("/onboarding-pause/{pause_id}/withdraw", summary="Withdraw a proposed pause / resume")
def withdraw_onboarding_change(pause_id: int, current_user=Depends(get_current_super_admin),
                               db: Session = Depends(get_db)):
    return _pilot().withdraw_onboarding_change(db, pause_id, _actor(current_user))
