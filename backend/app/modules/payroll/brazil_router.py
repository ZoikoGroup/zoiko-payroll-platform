"""
payroll/brazil_router.py
------------------------
Super Admin API for the Brazil workspace (ZP-BR-ENG-001), mounted under
/api/super-admin/compliance/brazil.

Rules every route follows (same as netherlands_router.py):
  * Super Admin only (get_current_super_admin).
  * Organisation-scoped data needs an explicit `org_id` — there is no default
    organisation.
  * Statutory pack content is never edited here: it changes only through the
    governed pack editor (draft -> review -> approve -> activate).
  * Phase 2: Super Admin endpoints now exist (pack-rows, rubric-catalogue,
    fpas-table, gates, golden-check) per the implementation plan. Phase 0/1
    included readiness; organisation endpoints live in a separate router (Phase 3).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.authz.scopes import organization_scoped
from app.core.dependencies import get_current_super_admin
from app.core.exceptions import BadRequestException, NotFoundException
from app.database import get_db
from app.modules.organizations.models import Organization
from app.modules.payroll.brazil_schemas import BRReadinessResponse

router = APIRouter(prefix="/super-admin/compliance/brazil", tags=["Brazil (Super Admin)"])

BR = "BR"

# ── helpers ──────────────────────────────────────────────────────────────────

def _plain(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _row(obj, fields) -> Dict[str, Any]:
    return {f: _plain(getattr(obj, f, None)) for f in fields}


def _actor(user) -> Optional[int]:
    return getattr(user, "id", None)


def _org(db: Session, org_id: int) -> Organization:
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if org is None:
        raise NotFoundException("Organization", org_id)
    return org


def _active_pack(db: Session, on: Optional[date] = None):
    from app.modules.payroll.models import JurisdictionPack

    on = on or date.today()
    return (db.query(JurisdictionPack)
            .filter(JurisdictionPack.jurisdiction_country == BR, JurisdictionPack.pack_type == "tax",
                    JurisdictionPack.status == "Active",
                    or_(JurisdictionPack.effective_from.is_(None), JurisdictionPack.effective_from <= on),
                    or_(JurisdictionPack.effective_to.is_(None), JurisdictionPack.effective_to >= on))
            .order_by(JurisdictionPack.effective_from.desc()).first())


def _pack_slabs(db: Session, rule_type: str, on: Optional[date]) -> Dict[str, Any]:
    from app.modules.payroll.models import TaxSlab

    pack = _active_pack(db, on)
    rows = [] if pack is None else (
        db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id, TaxSlab.rule_type == rule_type,
                                 TaxSlab.organization_id.is_(None))
        .order_by(TaxSlab.sort_order, TaxSlab.id).all())
    return {"packId": pack.id if pack else None, "packCode": pack.pack_id if pack else None,
            "editable": False, "editVia": "governed pack editor (draft -> review -> approve)",
            "rows": [{"id": r.id, "key": r.filing_status, "rate": _plain(r.rate_pct), "amount": _plain(r.flat_amount),
                      "min": _plain(r.min_amount), "max": _plain(r.max_amount),
                      "effectiveFrom": _plain(r.effective_from), "effectiveTo": _plain(r.effective_to)}
                     for r in rows]}


# ── organisations & employees ────────────────────────────────────────────────

@router.get("/organizations", summary="Organisations with Brazil payroll (an employer profile or Brazil jurisdiction)")
def list_br_organizations(current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    from app.modules.payroll.models import CompanyComplianceDetails, PayrollBrEmployerProfile

    # ZP-PRIV: a platform principal never reads worker rows, so employees are
    # not consulted — an organisation is Brazilian by its employer profile or
    # its company jurisdiction.
    ids = {r[0] for r in db.query(PayrollBrEmployerProfile.organization_id).distinct()}
    ids |= {r[0] for r in db.query(CompanyComplianceDetails.organization_id)
            .filter(CompanyComplianceDetails.jurisdiction_country.in_((BR, "Brazil")))}
    orgs = db.query(Organization).filter(Organization.id.in_(ids)).all() if ids else []
    return sorted(({"id": o.id, "name": getattr(o, "organization_name", None) or f"Organisation #{o.id}"}
                   for o in orgs), key=lambda o: o["name"].lower())


@router.get("/employees", summary="Brazil employees of one organisation")
def list_br_employees(org_id: int = Query(...), current_user=Depends(get_current_super_admin),
                      db: Session = Depends(get_db)):
    from app.modules.payroll.models import PayrollEmployee

    _org(db, org_id)
    rows = (organization_scoped(db, PayrollEmployee, org_id).filter(PayrollEmployee.country_code == BR)
            .order_by(PayrollEmployee.name).all())
    return [{"id": e.id, "name": e.name, "employee_code": e.employee_code} for e in rows]


# ── statutory pack content — READ ONLY (governed pack editor owns writes) ────

_ALLOWED_BR_RULE_TYPES = {
    "BR_INSS_BAND", "BR_IRRF_TABLE", "BR_IRRF_REDUCTION", "BR_MIN_WAGE",
    "BR_SAL_FAMILIA", "BR_FGTS_RATE", "BR_CPP_RATE",
}


@router.get("/pack-rows", summary="BR Active pack rows (read-only)")
def get_pack_rows(rule_type: str = Query(...), on: Optional[date] = Query(None),
                  current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    if rule_type not in _ALLOWED_BR_RULE_TYPES:
        raise BadRequestException(f"rule_type must be one of {_ALLOWED_BR_RULE_TYPES}")
    return _pack_slabs(db, rule_type, on)


# ── rubric catalogue ──────────────────────────────────────────────────────────

@router.get("/rubric-catalogue", summary="Canonical eSocial Table 03 rubrics with org overrides")
def get_rubric_catalogue(org_id: Optional[int] = Query(None),
                         current_user=Depends(get_current_super_admin),
                         db: Session = Depends(get_db)):
    from app.modules.payroll.engine.countries import brazil_content

    try:
        content_hash = brazil_content.CONTENT_HASH
    except Exception:
        content_hash = None

    # Canonical system rubrics
    catalogue: List[Dict[str, Any]] = []
    for r in getattr(brazil_content, "STANDARD_SYSTEM_RUBRICS", []):
        catalogue.append({
            "rubric_code": r.get("rubric_code"),
            "rubric_name": r.get("rubric_name"),
            "nature_code": r.get("nature_code"),
            "rubric_type": r.get("rubric_type"),
            "cod_inc_cp": r.get("cod_inc_cp"),
            "cod_inc_irrf": r.get("cod_inc_irrf"),
            "cod_inc_fgts": r.get("cod_inc_fgts"),
            "is_system_standard": True,
            "source": "canonical",
            "valid_from": _plain(getattr(brazil_content, "BRAZIL_EFFECTIVE_DATE", None)),
            "valid_to": None,
        })

    # Merge org overrides if requested
    if org_id is not None:
        _org(db, org_id)
        from app.modules.payroll.models import PayrollBrRubric
        overrides = (db.query(PayrollBrRubric)
                     .filter(PayrollBrRubric.organization_id == org_id)
                     .order_by(PayrollBrRubric.rubric_code, PayrollBrRubric.valid_from.desc())
                     .all())
        for o in overrides:
            catalogue.append({
                "rubric_code": o.rubric_code,
                "rubric_name": o.rubric_name,
                "nature_code": o.nature_code,
                "rubric_type": o.rubric_type,
                "cod_inc_cp": o.cod_inc_cp,
                "cod_inc_irrf": o.cod_inc_irrf,
                "cod_inc_fgts": o.cod_inc_fgts,
                "is_system_standard": bool(o.is_system_standard),
                "source": "organization",
                "valid_from": _plain(o.valid_from),
                "valid_to": _plain(o.valid_to),
            })

    return {
        "catalogueHash": content_hash,
        "rubrics": catalogue,
        "note": "Codes are unverified against the official eSocial Tabela 03 pending decision D6 (fixes BR-K3).",
    }


# ── FPAS table ────────────────────────────────────────────────────────────────

@router.get("/fpas-table", summary="Employer FPAS/Tabela 04 reference")
def get_fpas_table(current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return {
        "available": False,
        "ruleType": "BR_FPAS_TABLE",
        "note": "Tabela 04 reference data is not yet supplied (D6) — FPAS/RAT/FAP are entered per establishment in Phase 3.",
    }


# ── gates & readiness ─────────────────────────────────────────────────────────

@router.get("/gates", summary="Gate G1–G8 states")
def get_gates(current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import brazil_service as br
    return br.gate_states(db)


@router.get("/readiness", response_model=BRReadinessResponse,
            summary="Gate G1–G8 states and engine version (spec §24)")
def get_readiness(current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import brazil_service as br
    return br.statutory_summary(db)


# ── golden check ─────────────────────────────────────────────────────────────

@router.post("/golden-check", summary="Run the golden-vector certification for BR")
def golden_check(current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import service
    result = service.run_golden_test_certification(db, BR, actor_id=_actor(current_user))
    return {
        "run_id": result.id,
        "status": result.status,
        "real_case_count": result.real_case_count,
        "total_cases": result.total_cases,
        "passed_cases": result.passed_cases,
        "failed_cases": result.failed_cases,
        "failure_details": result.failure_details,
        "run_at": _plain(result.run_at),
    }
