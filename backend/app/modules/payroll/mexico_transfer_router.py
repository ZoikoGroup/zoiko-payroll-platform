"""
payroll/mexico_transfer_router.py
---------------------------------
Mexico Phase 10f (option B): the tenant-run master-data handshake between a
pilot organisation and the new live organisation of the same employer
(/api/payroll/mexico-transfer/...). Not under the /mexico guard on purpose:
the pilot side stays reachable after its pilot grant ends (releasing is its
last act) — each route runs its own guard (mexico_transfer_service.release_guard
/ import_guard). Every route acts on the caller's OWN organisation, org admins
only; four-eyes is enforced in the service. Needs the ZP-PRIV owner's sign-off.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_org_admin
from app.core.exceptions import ForbiddenException
from app.database import get_db

router = APIRouter(prefix="/mexico-transfer", tags=["Mexico (Organisation) — master-data transfer"])


def _xfer():
    from app.modules.payroll import mexico_transfer_service

    return mexico_transfer_service


def _xfer_org(user) -> int:
    org_id = getattr(user, "organization_id", None)
    if org_id is None:
        raise ForbiddenException("The master-data transfer is run by the two organisations' own admins.")
    return org_id


def _xfer_actor(user) -> Optional[int]:
    return getattr(user, "id", None)


@router.get("/status", summary="This organisation's releases (out), releases to it (in) and imports")
def transfer_status(current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _xfer().transfer_status(db, _xfer_org(current_user))


@router.post("/releases", summary="Pilot: propose a one-time release to one live organisation of the same employer")
def propose_release(body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                    db: Session = Depends(get_db)):
    return _xfer().propose_release(db, _xfer_org(current_user), body, _xfer_actor(current_user))


@router.post("/releases/{release_id}/release", summary="Pilot: release it (a different admin; expires in 7 days)")
def approve_release(release_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _xfer().approve_release(db, _xfer_org(current_user), release_id, _xfer_actor(current_user))


@router.post("/releases/{release_id}/revoke", summary="Pilot: revoke a release before it is used")
def revoke_release(release_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                   db: Session = Depends(get_db)):
    return _xfer().revoke_release(db, _xfer_org(current_user), release_id, str(body.get("reason") or ""),
                                  _xfer_actor(current_user))


@router.get("/releases/{release_id}/preview", summary="Live: the diff to review before importing (identifiers masked)")
def preview_import(release_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _xfer().preview_import(db, _xfer_org(current_user), release_id)


@router.post("/releases/{release_id}/import", summary="Live: propose the import, bound to the reviewed diff")
def propose_import(release_id: int, body: Dict[str, Any] = Body(...), current_user=Depends(get_current_org_admin),
                   db: Session = Depends(get_db)):
    return _xfer().propose_import(db, _xfer_org(current_user), release_id, body, _xfer_actor(current_user))


@router.post("/imports/{copy_id}/approve", summary="Live: approve and execute the import (a different admin)")
def approve_import(copy_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    return _xfer().approve_import(db, _xfer_org(current_user), copy_id, _xfer_actor(current_user))


@router.post("/imports/{copy_id}/cancel", summary="Live: cancel a proposed import")
def cancel_import(copy_id: int, body: Dict[str, Any] = Body(default={}), current_user=Depends(get_current_org_admin),
                  db: Session = Depends(get_db)):
    return _xfer().cancel_import(db, _xfer_org(current_user), copy_id, str(body.get("reason") or ""),
                                 _xfer_actor(current_user))
