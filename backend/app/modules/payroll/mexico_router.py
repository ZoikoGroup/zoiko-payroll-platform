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
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_super_admin
from app.database import get_db
from app.modules.payroll.mexico_schemas import (
    MXCatalogEntryCreate, MXClassificationArchive, MXClassificationCreate, MXReadinessResponse, MXReleaseCreate,
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


@router.get("/cfdi-catalogs/{release_id}/entries", summary="Catalog entries of one release")
def list_entries(release_id: int, current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return _mx().list_catalog_entries(db, release_id)


@router.post("/cfdi-catalogs/{release_id}/entries", summary="Add a catalog entry to a Draft release")
def add_entry(release_id: int, body: MXCatalogEntryCreate, current_user=Depends(get_current_super_admin),
              db: Session = Depends(get_db)):
    return _mx().add_catalog_entry(db, release_id, body.to_service(), _actor(current_user))


@router.put("/cfdi-catalogs/{release_id}/{action}",
            summary="submit / approve / activate / supersede (activate is refused in Phase 2)")
def transition_release(release_id: int, action: str, current_user=Depends(get_current_super_admin),
                       db: Session = Depends(get_db)):
    return _mx().transition_release(db, release_id, action, _actor(current_user))


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
