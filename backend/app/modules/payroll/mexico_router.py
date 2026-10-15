"""
payroll/mexico_router.py
------------------------
Super Admin API for the Mexico workspace (ZP-MX-ENG-001), mounted under
/api/super-admin/compliance/mexico.

Rules every route follows (same as netherlands_router.py):
  * Super Admin only (get_current_super_admin).
  * Organisation-scoped data needs an explicit `org_id` — there is no default
    organisation.
  * Statutory pack content is never edited here: it changes only through the
    governed pack editor (draft -> review -> approve -> activate).

Phase 0: the readiness document only. The Super Admin endpoints of plan §5
arrive in Phase 2.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_super_admin
from app.database import get_db
from app.modules.payroll.mexico_schemas import MXReadinessResponse

router = APIRouter(prefix="/super-admin/compliance/mexico", tags=["Mexico (Super Admin)"])


@router.get("/readiness", response_model=MXReadinessResponse,
            summary="Gate G1–G8 states and engine version (spec §22)")
def get_readiness(current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import mexico_service as mx

    return mx.statutory_summary(db)
