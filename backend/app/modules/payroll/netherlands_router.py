"""
payroll/netherlands_router.py
-----------------------------
Super Admin API for the Netherlands workspace (ZP-NL-ENG-001), mounted under
/api/super-admin/compliance/netherlands.

Rules every route follows:
  * Super Admin only (get_current_super_admin).
  * Organisation-scoped data needs an explicit `org_id` — there is no default
    organisation (a default would silently act on another customer's data).
  * Writes go through netherlands_service / netherlands_tables_service /
    netherlands_filing_service (which flush only) and are committed here.
  * Statutory pack content (minimum wage, WKR bands, car-addition windows) is
    READ-ONLY here: it changes only through the governed pack editor
    (draft -> review -> approve -> activate), never by a direct edit.
  * Authority transport (Digipoort submit, filed / accepted / rejected states,
    authority payments) stays LOCKED until gate G3 is signed.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, File, Form, Query, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_super_admin
from app.core.exceptions import BadRequestException, NotFoundException
from app.database import get_db
from app.modules.organizations.models import Organization

router = APIRouter(prefix="/super-admin/compliance/netherlands", tags=["Netherlands (Super Admin)"])

NL = "NL"


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


def _platform_catalog_only(org_id) -> None:
    """ZP-PRIV B.1: Super Admin maintains the platform catalog only. An
    organization's own overrides are tenant configuration and are managed
    by that organization (/api/payroll/netherlands/...)."""
    if org_id not in (None, ""):
        raise BadRequestException(
            "Organization-specific entries are managed by the organization itself; "
            "Super Admin maintains the platform catalog only.")


def _commit(db: Session, obj=None):
    db.commit()
    if obj is not None:
        db.refresh(obj)
    return obj


def _active_pack(db: Session, on: Optional[date] = None):
    from app.modules.payroll.models import JurisdictionPack

    on = on or date.today()
    return (db.query(JurisdictionPack)
            .filter(JurisdictionPack.jurisdiction_country == NL, JurisdictionPack.pack_type == "tax",
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


def _locked(action: str):
    raise BadRequestException(
        f"Netherlands {action} is locked until gate G3 is signed (official Gegevensspecificaties, PKIoverheid "
        "certificate and Digipoort test access). Returns can be built and reconciled, not transmitted.")


# ── organisations & employees ────────────────────────────────────────────────

@router.get("/organizations", summary="Organisations with Netherlands payroll (employees or an employer profile)")
def list_nl_organizations(current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    from app.modules.payroll.models import PayrollEmployee, PayrollNlEmployerProfile

    ids = {r[0] for r in db.query(PayrollEmployee.organization_id).filter(PayrollEmployee.country_code == NL).distinct()}
    ids |= {r[0] for r in db.query(PayrollNlEmployerProfile.organization_id).distinct()}
    orgs = db.query(Organization).filter(Organization.id.in_(ids)).all() if ids else []
    return sorted(({"id": o.id, "name": getattr(o, "organization_name", None) or f"Organisation #{o.id}"}
                   for o in orgs), key=lambda o: o["name"].lower())


@router.get("/employees", summary="Netherlands employees of one organisation")
def list_nl_employees(org_id: int = Query(...), current_user=Depends(get_current_super_admin),
                      db: Session = Depends(get_db)):
    from app.modules.payroll.models import PayrollEmployee

    _org(db, org_id)
    rows = (db.query(PayrollEmployee).filter(PayrollEmployee.organization_id == org_id,
                                             PayrollEmployee.country_code == NL)
            .order_by(PayrollEmployee.name).all())
    return [{"id": e.id, "name": e.name, "employee_code": e.employee_code} for e in rows]


# ── employer profile (spec §10) ──────────────────────────────────────────────

@router.get("/employer-profile", summary="The organisation's employer profile in force (null when none)")
def get_employer_profile(org_id: int = Query(...), current_user=Depends(get_current_super_admin),
                         db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_service as nl

    _org(db, org_id)
    try:
        return nl.get_employer_profile(db, organization_id=org_id).model_dump(mode="json")
    except NotFoundException:
        return None


@router.post("/employer-profile", summary="Record a new employer-profile version (closes the open one)")
def create_employer_profile(payload: Dict[str, Any] = Body(...), org_id: int = Query(...),
                            current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_service as nl
    from app.modules.payroll.netherlands_schemas import EmployerProfileCreate

    _org(db, org_id)
    result = nl.create_employer_profile(db, organization_id=org_id, data=EmployerProfileCreate(**payload),
                                        actor_id=_actor(current_user))
    db.commit()
    return result.model_dump(mode="json")


@router.get("/employer-profile/readiness", summary="Employer readiness card H (spec §10)")
def get_employer_readiness(org_id: int = Query(...), current_user=Depends(get_current_super_admin),
                           db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_service as nl

    _org(db, org_id)
    return nl.get_employer_readiness_card(db, organization_id=org_id).model_dump(mode="json")


# ── wage-tax tables (gate G1) — national authority data, not org-scoped ─────

_TABLE_FIELDS = ("id", "jurisdiction_pack_id", "tax_year", "table_color", "table_kind", "period",
                 "residence_variant", "source_filename", "source_url", "file_sha256", "row_count", "status",
                 "validation_report", "imported_by", "validated_by", "approved_by", "activated_by",
                 "effective_from", "effective_to", "superseded_by_id", "created_at")


@router.get("/tax-tables", summary="Imported wage-tax table files")
def list_tax_tables(status: Optional[str] = Query(None), current_user=Depends(get_current_super_admin),
                    db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_tables_service as tables

    return [_row(f, _TABLE_FIELDS) for f in tables.list_table_files(db, status=status)]


@router.post("/tax-tables/import", summary="Import an official Belastingdienst table file (CSV) as IMPORTED")
async def import_tax_table(file: UploadFile = File(...), jurisdiction_pack_id: int = Form(...),
                           tax_year: int = Form(...), table_color: str = Form(...), table_kind: str = Form(...),
                           period: Optional[str] = Form(None), residence_variant: str = Form("NL"),
                           source_url: Optional[str] = Form(None), current_user=Depends(get_current_super_admin),
                           db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_tables_service as tables

    row = tables.import_table_file(
        db, jurisdiction_pack_id=jurisdiction_pack_id, tax_year=tax_year, table_color=table_color,
        table_kind=table_kind, period=period or None, residence_variant=residence_variant, source_url=source_url,
        source_filename=file.filename or "upload.csv", file_bytes=await file.read(), actor_id=_actor(current_user))
    return _row(_commit(db, row), _TABLE_FIELDS)


@router.put("/tax-tables/{file_id}/{action}", summary="validate / approve / activate / reject (four-eyes)")
def transition_tax_table(file_id: int, action: str, payload: Optional[Dict[str, Any]] = Body(None),
                         current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_tables_service as tables

    actor = _actor(current_user)
    if action == "validate":
        row = tables.validate_table_file(db, file_id, actor)
    elif action == "approve":
        row = tables.approve_table_file(db, file_id, actor)
    elif action == "activate":
        row, _superseded = tables.activate_table_file(db, file_id, actor)
    elif action == "reject":
        reason = ((payload or {}).get("reason") or "").strip()
        if not reason:
            raise BadRequestException("a rejection needs a reason")
        row = tables.reject_table_file(db, file_id, actor, reason)
    else:
        raise BadRequestException("action must be validate, approve, activate or reject")
    return _row(_commit(db, row), _TABLE_FIELDS)


# ── statutory pack content — READ ONLY (governed pack editor owns writes) ────

@router.get("/minimum-wage", summary="NL_MIN_WAGE rows of the Active pack (read-only)")
def get_minimum_wage(on: Optional[date] = Query(None), current_user=Depends(get_current_super_admin),
                     db: Session = Depends(get_db)):
    return _pack_slabs(db, "NL_MIN_WAGE", on)


@router.get("/wkr-bands", summary="NL_WKR_BAND rows of the Active pack (read-only)")
def get_wkr_bands(on: Optional[date] = Query(None), current_user=Depends(get_current_super_admin),
                  db: Session = Depends(get_db)):
    return _pack_slabs(db, "NL_WKR_BAND", on)


@router.get("/car-bands", summary="NL_CAR_ADDITION windows of the Active pack (read-only)")
def get_car_bands(on: Optional[date] = Query(None), current_user=Depends(get_current_super_admin),
                  db: Session = Depends(get_db)):
    return _pack_slabs(db, "NL_CAR_ADDITION", on)


@router.get("/period-maxima", summary="NL_PERIOD_MAX rows of the Active pack (read-only)")
def get_period_maxima(on: Optional[date] = Query(None), current_user=Depends(get_current_super_admin),
                      db: Session = Depends(get_db)):
    return _pack_slabs(db, "NL_PERIOD_MAX", on)


# ── employer premium decisions (Aof / Whk, NL-017) ───────────────────────────

_PREMIUM_FIELDS = ("id", "organization_id", "tax_year", "aof_size_class", "aof_basis_year", "aof_basis_premium_wage",
                   "whk_wga_pct", "whk_wga_employee_recoverable_pct", "whk_zw_flex_pct", "sector_code",
                   "decision_reference", "decision_date", "evidence_artifact_id", "effective_from", "effective_to",
                   "status", "created_by", "approved_by", "sha256")


@router.get("/premium-decisions", summary="Employer premium decisions of one organisation")
def list_premium_decisions(org_id: int = Query(...), current_user=Depends(get_current_super_admin),
                           db: Session = Depends(get_db)):
    from app.modules.payroll.models import PayrollNlEmployerPremiumDecision as M

    _org(db, org_id)
    rows = db.query(M).filter(M.organization_id == org_id).order_by(M.tax_year.desc(), M.effective_from.desc()).all()
    return [_row(r, _PREMIUM_FIELDS) for r in rows]


@router.post("/premium-decisions", summary="Record a DRAFT premium decision with its evidence")
def create_premium_decision(payload: Dict[str, Any] = Body(...), org_id: int = Query(...),
                            current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_service as nl

    _org(db, org_id)
    try:
        row = nl.create_premium_decision(
            db, organization_id=org_id, tax_year=int(payload["tax_year"]),
            aof_size_class=payload["aof_size_class"], aof_basis_year=int(payload["aof_basis_year"]),
            aof_basis_premium_wage=Decimal(str(payload["aof_basis_premium_wage"])),
            decision_reference=payload["decision_reference"],
            decision_date=date.fromisoformat(payload["decision_date"]),
            effective_from=date.fromisoformat(payload["effective_from"]), actor_id=_actor(current_user),
            whk_wga_pct=_opt_dec(payload.get("whk_wga_pct")), whk_zw_flex_pct=_opt_dec(payload.get("whk_zw_flex_pct")),
            whk_wga_employee_recoverable_pct=_opt_dec(payload.get("whk_wga_employee_recoverable_pct")),
            sector_code=payload.get("sector_code") or None, evidence_artifact_id=payload.get("evidence_artifact_id"))
    except (KeyError, ValueError) as exc:
        raise BadRequestException(f"invalid premium decision: {exc}")
    return _row(_commit(db, row), _PREMIUM_FIELDS)


@router.put("/premium-decisions/{decision_id}/activate", summary="Activate (four-eyes; supersedes the active one)")
def activate_premium_decision(decision_id: int, org_id: int = Query(...),
                              current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_service as nl

    row = nl.activate_premium_decision(db, decision_id, org_id, actor_id=_actor(current_user))
    return _row(_commit(db, row), _PREMIUM_FIELDS)


def _opt_dec(value) -> Optional[Decimal]:
    return None if value in (None, "") else Decimal(str(value))


# ── VCR inspector (read-only) ────────────────────────────────────────────────

@router.get("/vcr", summary="Committed VCR snapshots of one employee, by family")
def get_vcr(org_id: int = Query(...), employee_id: int = Query(...), tax_year: int = Query(...),
            current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    from app.modules.payroll.models import PayrollNlVcrSnapshot as M

    _org(db, org_id)
    rows = (db.query(M).filter(M.organization_id == org_id, M.employee_id == employee_id, M.tax_year == tax_year)
            .order_by(M.family, M.revision).all())
    out: Dict[str, List[dict]] = {"EI": [], "ZVW_LEVY": [], "ZVW_CONTRIB": []}
    for r in rows:
        out.setdefault(r.family, []).append(_row(r, (
            "id", "revision", "period_count", "cumulative_wage", "cumulative_max", "cumulative_base",
            "base_increment", "period_max_amount", "payroll_run_id", "payslip_item_id", "is_correction",
            "created_at")))
    return out


# ── earning classifications (NL-047) ─────────────────────────────────────────

_CLASS_FIELDS = ("id", "organization_id", "earning_code", "remuneration_type", "wage_tax", "employee_insurance_wage",
                 "zvw_wage", "pensionable", "wkr_treatment", "vacation_allowance_basis", "minimum_wage_reckonable",
                 "evidence_policy", "effective_from", "effective_to", "status")


@router.get("/earning-classifications", summary="Platform catalog + the organisation's overrides")
def list_earning_classifications(org_id: Optional[int] = Query(None), current_user=Depends(get_current_super_admin),
                                 db: Session = Depends(get_db)):
    from app.modules.payroll.models import PayrollNlEarningClassification as M

    _platform_catalog_only(org_id)

    q = db.query(M).filter(M.organization_id.is_(None) if org_id is None
                           else or_(M.organization_id.is_(None), M.organization_id == org_id))
    return [_row(r, _CLASS_FIELDS) for r in q.order_by(M.earning_code, M.effective_from.desc()).all()]


@router.post("/earning-classifications",
             summary="New classification (platform catalog when organization_id is null); supersedes the open one")
def create_earning_classification(payload: Dict[str, Any] = Body(...), current_user=Depends(get_current_super_admin),
                                  db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_service as nl

    org_id = payload.get("organization_id")
    _platform_catalog_only(org_id)
    try:
        row = nl.create_earning_classification(
            db, organization_id=None if org_id is None else int(org_id), earning_code=payload["earning_code"].strip(),
            effective_from=date.fromisoformat(payload["effective_from"]),
            remuneration_type=payload["remuneration_type"], wage_tax=bool(payload["wage_tax"]),
            employee_insurance_wage=bool(payload["employee_insurance_wage"]), zvw_wage=bool(payload["zvw_wage"]),
            pensionable=bool(payload["pensionable"]), wkr_treatment=payload["wkr_treatment"],
            vacation_allowance_basis=bool(payload["vacation_allowance_basis"]),
            minimum_wage_reckonable=bool(payload["minimum_wage_reckonable"]),
            evidence_policy=payload.get("evidence_policy") or "NONE")
    except (KeyError, ValueError, AttributeError) as exc:
        raise BadRequestException(f"invalid earning classification: {exc}")
    return _row(_commit(db, row), _CLASS_FIELDS)


# ── expat decisions (NL-026) ─────────────────────────────────────────────────

_EXPAT_FIELDS = ("id", "organization_id", "employee_id", "decision_reference", "decision_date", "granted_from",
                 "granted_to", "method", "threshold_category", "allowance_pct", "evidence_artifact_id", "status",
                 "verified_by", "verified_at")


@router.get("/expat-decisions", summary="30% facility decisions of one organisation")
def list_expat_decisions(org_id: int = Query(...), current_user=Depends(get_current_super_admin),
                         db: Session = Depends(get_db)):
    from app.modules.payroll.models import PayrollEmployee, PayrollNlExpatDecision as M

    _org(db, org_id)
    names = {e.id: e.name for e in db.query(PayrollEmployee).filter(PayrollEmployee.organization_id == org_id)}
    return [{**_row(r, _EXPAT_FIELDS), "employee_name": names.get(r.employee_id)}
            for r in db.query(M).filter(M.organization_id == org_id).order_by(M.granted_from.desc()).all()]


@router.post("/expat-decisions", summary="Record a decision (PENDING until verified against the document)")
def create_expat_decision(payload: Dict[str, Any] = Body(...), org_id: int = Query(...),
                          current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_service as nl

    _org(db, org_id)
    try:
        row = nl.record_expat_decision(
            db, organization_id=org_id, employee_id=int(payload["employee_id"]),
            decision_reference=payload["decision_reference"], decision_date=date.fromisoformat(payload["decision_date"]),
            granted_from=date.fromisoformat(payload["granted_from"]),
            granted_to=date.fromisoformat(payload["granted_to"]) if payload.get("granted_to") else None,
            method=payload["method"], threshold_category=payload["threshold_category"],
            allowance_pct=Decimal(str(payload["allowance_pct"])),
            evidence_artifact_id=payload.get("evidence_artifact_id") or None)
    except (KeyError, ValueError) as exc:
        raise BadRequestException(f"invalid expat decision: {exc}")
    return _row(_commit(db, row), _EXPAT_FIELDS)


@router.put("/expat-decisions/{decision_id}/{action}", summary="verify / revoke")
def transition_expat_decision(decision_id: int, action: str, org_id: int = Query(...),
                              current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_service as nl

    if action == "verify":
        row = nl.verify_expat_decision(db, decision_id, org_id, actor_id=_actor(current_user))
    elif action == "revoke":
        row = nl.revoke_expat_decision(db, decision_id, org_id, actor_id=_actor(current_user))
    else:
        raise BadRequestException("action must be verify or revoke")
    return _row(_commit(db, row), _EXPAT_FIELDS)


# ── CAO (read-only, governed registry) & pension schemes (NL-043) ────────────

@router.get("/caos", summary="Netherlands collective agreements (read-only; governed CAO registry)")
def list_caos(current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    from app.modules.payroll.models import CollectiveAgreement as M

    rows = db.query(M).filter(M.jurisdiction_country == NL).order_by(M.name).all()
    return [_row(r, ("id", "organization_id", "agreement_code", "name", "agreement_type", "employee_group",
                     "version", "effective_from", "effective_to", "status")) for r in rows]


_PENSION_FIELDS = ("id", "organization_id", "fund_name", "scheme_code", "mandatory_sector", "collective_agreement_id",
                   "franchise_amount", "max_pensionable_salary", "employee_pct", "employer_pct", "basis_rule",
                   "effective_from", "effective_to", "status", "evidence_artifact_id")


@router.get("/pension-schemes", summary="Pension schemes: platform catalog + the organisation's own")
def list_pension_schemes(org_id: Optional[int] = Query(None), current_user=Depends(get_current_super_admin),
                         db: Session = Depends(get_db)):
    from app.modules.payroll.models import PayrollNlPensionScheme as M

    _platform_catalog_only(org_id)

    q = db.query(M).filter(M.organization_id.is_(None) if org_id is None
                           else or_(M.organization_id.is_(None), M.organization_id == org_id))
    return [_row(r, _PENSION_FIELDS) for r in q.order_by(M.fund_name, M.effective_from.desc()).all()]


@router.post("/pension-schemes", summary="Record a pension scheme (catalog when organization_id is null)")
def create_pension_scheme(payload: Dict[str, Any] = Body(...), current_user=Depends(get_current_super_admin),
                          db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_service as nl

    org_id = payload.get("organization_id")
    _platform_catalog_only(org_id)
    try:
        row = nl.create_pension_scheme(
            db, organization_id=None if org_id is None else int(org_id), fund_name=payload["fund_name"],
            scheme_code=payload["scheme_code"], effective_from=date.fromisoformat(payload["effective_from"]),
            basis_rule=payload["basis_rule"], employee_pct=Decimal(str(payload["employee_pct"])),
            employer_pct=Decimal(str(payload["employer_pct"])),
            franchise_amount=Decimal(str(payload.get("franchise_amount") or "0")),
            max_pensionable_salary=_opt_dec(payload.get("max_pensionable_salary")),
            mandatory_sector=bool(payload.get("mandatory_sector")),
            collective_agreement_id=payload.get("collective_agreement_id") or None,
            evidence_artifact_id=payload.get("evidence_artifact_id") or None)
    except (KeyError, ValueError) as exc:
        raise BadRequestException(f"invalid pension scheme: {exc}")
    return _row(_commit(db, row), _PENSION_FIELDS)


# ── readiness gates G1–G8 & owner decisions (spec §19) ───────────────────────

@router.get("/readiness", summary="Gate G1–G8 states, owner decisions and engine version")
def get_readiness(current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_service as nl

    return nl.statutory_summary(db)


# ── loonaangifte (build / reconcile / view) — transport LOCKED until G3 ──────

_RETURN_FIELDS = ("id", "organization_id", "employer_profile_id", "loonheffingennummer", "tax_year", "period_code",
                  "period_start", "period_end", "due_date", "payment_due_date", "version", "return_type",
                  "correction_of_id", "status", "total_wage_tax", "total_awf", "total_aof", "total_whk", "total_wko",
                  "total_zvw_employer", "total_zvw_employee", "total_final_levies", "total_payable", "spec_version",
                  "payload_sha256", "journal_reconciled", "reconciliation_report", "created_at")


@router.get("/loonaangifte", summary="Built returns of one organisation")
def list_returns(org_id: int = Query(...), tax_year: Optional[int] = Query(None),
                 current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_filing_service as filings

    _org(db, org_id)
    return [_row(r, _RETURN_FIELDS) for r in filings.list_returns(db, org_id, tax_year)]


@router.get("/loonaangifte/{return_id}", summary="One return with its employee lines")
def get_return(return_id: int, org_id: int = Query(...), current_user=Depends(get_current_super_admin),
               db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_filing_service as filings

    ret, lines = filings.get_return_with_lines(db, return_id)
    if ret.organization_id != org_id:
        raise NotFoundException("PayrollNlLoonaangifteReturn", return_id)
    return {**_row(ret, _RETURN_FIELDS), "lines": [_row(l, (
        "id", "employee_id", "income_relationship_id", "personnel_number", "line_type", "correction_of_line_id",
        "wage_lb_phf", "wage_sv", "wage_zvw", "hours", "awf_class", "premium_amounts", "wage_tax", "zvw",
        "line_sha256")) for l in lines]}


@router.post("/loonaangifte/build", summary="Build a return from committed payroll (REGULAR / NIL / ZERO)")
def build_return(payload: Dict[str, Any] = Body(...), org_id: int = Query(...),
                 current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_filing_service as filings
    from app.modules.payroll.models import PayrollNlEmployerProfile

    _org(db, org_id)
    profile = (db.query(PayrollNlEmployerProfile).filter(PayrollNlEmployerProfile.organization_id == org_id,
                                                         PayrollNlEmployerProfile.effective_to.is_(None)).first())
    if profile is None:
        raise BadRequestException("the organisation has no Netherlands employer profile")
    return_type = payload.get("return_type") or "REGULAR"
    if return_type not in ("REGULAR", "NIL", "ZERO"):
        raise BadRequestException("build REGULAR, NIL or ZERO returns here; corrections use /{id}/correction")
    try:
        ret = filings.build_loonaangifte_return(db, organization_id=org_id, employer_profile_id=profile.id,
                                                tax_year=int(payload["tax_year"]), period_code=str(payload["period_code"]),
                                                return_type=return_type, actor_id=_actor(current_user))
    except (KeyError, ValueError) as exc:
        raise BadRequestException(f"invalid build request: {exc}")
    return _row(_commit(db, ret), _RETURN_FIELDS)


@router.put("/loonaangifte/{return_id}/reconcile", summary="Re-derive from committed payroll and compare")
def reconcile_return(return_id: int, org_id: int = Query(...), current_user=Depends(get_current_super_admin),
                     db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_filing_service as filings

    _owned_return(db, return_id, org_id)
    try:
        report = filings.reconcile_return(db, return_id, _actor(current_user))
    finally:
        db.commit()  # the mismatch report is evidence too
    return report


@router.post("/loonaangifte/{return_id}/correction", summary="Build a CORRECTION return (full replacement)")
def correct_return(return_id: int, org_id: int = Query(...), current_user=Depends(get_current_super_admin),
                   db: Session = Depends(get_db)):
    from app.modules.payroll import netherlands_filing_service as filings

    _owned_return(db, return_id, org_id)
    ret = filings.create_correction_return(db, return_id, actor_id=_actor(current_user))
    return _row(_commit(db, ret), _RETURN_FIELDS)


def _owned_return(db: Session, return_id: int, org_id: int):
    from app.modules.payroll.models import PayrollNlLoonaangifteReturn as M

    ret = db.query(M).filter(M.id == return_id, M.organization_id == org_id).first()
    if ret is None:
        raise NotFoundException("PayrollNlLoonaangifteReturn", return_id)
    return ret


@router.post("/loonaangifte/{return_id}/file", summary="LOCKED until gate G3")
def file_return(return_id: int, current_user=Depends(get_current_super_admin)):
    _locked("filing")


@router.put("/loonaangifte/{return_id}/accept", summary="LOCKED until gate G3")
def accept_return(return_id: int, current_user=Depends(get_current_super_admin)):
    _locked("authority acceptance")


@router.put("/loonaangifte/{return_id}/reject", summary="LOCKED until gate G3")
def reject_return(return_id: int, current_user=Depends(get_current_super_admin)):
    _locked("authority rejection")


@router.post("/digipoort/submit", summary="LOCKED until gate G3")
def digipoort_submit(current_user=Depends(get_current_super_admin)):
    _locked("Digipoort transport")


@router.post("/authority-payments/prepare", summary="LOCKED until gate G3")
def authority_payment_prepare(current_user=Depends(get_current_super_admin)):
    _locked("authority payment")
