"""
japan_year_end.py — Japan year-end adjustment workflow (ZP-JP-ENG-001 §8, S3;
Phase 8).

  declarations  versioned, captured DRAFT, approved by a second person; only
                APPROVED ones reach the calculation.
  case          OPEN -> CALCULATED -> REVIEWED (a second person) -> APPLIED
                (to one open salary run in the tax year, no earlier than the
                signed month) -> LOCKED when that run is PAID. EXCLUDED with
                the reason when the employee is outside the adjustment; VOID
                frees the year (never once LOCKED).
  figures       annual pay, withholding and social insurance come ONLY from
                the employee's committed (Paid / Closed) Japan payslips of the
                year — a corrected payslip counts at its latest correction;
                the rule rows are the ones frozen with the latest of them.
The calculation itself is engine/jurisdictions/japan/year_end.py.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException

JP = "JP"
ZERO = Decimal("0")
_COMMITTED = ("Paid", "Closed")
_OPEN_RUN = ("Draft", "Review")


def _models():
    from app.modules.payroll import models

    return models


def _now():
    return datetime.now(timezone.utc)


def _dec(value) -> Decimal:
    return Decimal(str(value)) if value not in (None, "") else ZERO


def _audit(db, actor_id, action, entity_type, entity_id, new=None):
    from app.modules.payroll.service import record_tax_audit

    record_tax_audit(db, actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id,
                     new_value=new, auto_commit=False)


def _row(row) -> dict:
    out = {}
    for c in row.__table__.columns:
        value = getattr(row, c.name)
        out[c.name] = (value.isoformat() if isinstance(value, (date, datetime))
                       else str(value) if isinstance(value, Decimal) else value)
    return out


# ── declarations ────────────────────────────────────────────────────────────
def record_declaration(db: Session, organization_id: int, employee_id: int, payload: dict,
                       actor_id: Optional[int]):
    from app.modules.payroll import japan_service
    from app.modules.payroll.engine.jurisdictions.japan import year_end

    m = _models()
    japan_service._jp_employee(db, organization_id, employee_id)
    unknown = sorted(set(payload) - {"tax_year", "declaration_type", "payload", "evidence_ref"})
    if unknown:
        raise BadRequestException(f"unknown field(s): {', '.join(unknown)}")
    try:
        tax_year = int(payload.get("tax_year"))
    except (TypeError, ValueError):
        raise BadRequestException("tax_year must be a year.")
    kind = str(payload.get("declaration_type") or "").strip().upper()
    if kind not in year_end.DECLARATION_TYPES:
        raise BadRequestException(f"declaration_type must be one of {', '.join(year_end.DECLARATION_TYPES)}.")
    body = payload.get("payload")
    if not isinstance(body, dict) or not body:
        raise BadRequestException("payload must be an object with the declared amounts.")
    extra = sorted(set(body) - set(year_end.DECLARATION_FIELDS[kind]))
    if extra:
        raise BadRequestException(f"{kind} accepts only {', '.join(year_end.DECLARATION_FIELDS[kind])}.")
    for key, value in body.items():
        if key == "categories":
            if not isinstance(value, dict) or any(not isinstance(v, int) or v < 0 for v in value.values()):
                raise BadRequestException("categories must be {category: whole count}.")
            continue
        try:
            if Decimal(str(value)) < 0:
                raise ValueError
        except Exception:
            raise BadRequestException(f"{key} must be a non-negative amount.")
    prior = (db.query(m.PayrollJpYeaDeclaration)
             .filter(m.PayrollJpYeaDeclaration.organization_id == organization_id,
                     m.PayrollJpYeaDeclaration.employee_id == employee_id,
                     m.PayrollJpYeaDeclaration.tax_year == tax_year,
                     m.PayrollJpYeaDeclaration.declaration_type == kind)
             .order_by(m.PayrollJpYeaDeclaration.id.desc()).first())
    row = m.PayrollJpYeaDeclaration(
        organization_id=organization_id, employee_id=employee_id, tax_year=tax_year,
        declaration_type=kind, payload=body, evidence_ref=(payload.get("evidence_ref") or None),
        status="DRAFT", previous_version_id=getattr(prior, "id", None), created_by_id=actor_id)
    db.add(row)
    db.flush()
    _audit(db, actor_id, "created", "jp_yea_declaration", row.id, new={"type": kind, "taxYear": tax_year})
    return row


def approve_declaration(db: Session, organization_id: int, declaration_id: int, actor_id: Optional[int]):
    from app.modules.payroll.service import require_four_eyes

    m = _models()
    row = (db.query(m.PayrollJpYeaDeclaration)
           .filter(m.PayrollJpYeaDeclaration.id == declaration_id,
                   m.PayrollJpYeaDeclaration.organization_id == organization_id).first())
    if row is None:
        raise NotFoundException("Japan year-end declaration not found.")
    if row.status != "DRAFT":
        raise BadRequestException("Only a DRAFT declaration can be approved.")
    require_four_eyes(row.created_by_id, actor_id, "Approving a Japan year-end declaration", db=db,
                      entity_type="jp_yea_declaration", entity_id=row.id, current_status=row.status)
    for old in (db.query(m.PayrollJpYeaDeclaration)
                .filter(m.PayrollJpYeaDeclaration.organization_id == organization_id,
                        m.PayrollJpYeaDeclaration.employee_id == row.employee_id,
                        m.PayrollJpYeaDeclaration.tax_year == row.tax_year,
                        m.PayrollJpYeaDeclaration.declaration_type == row.declaration_type,
                        m.PayrollJpYeaDeclaration.status == "APPROVED")):
        old.status = "SUPERSEDED"
    row.status, row.approved_by_id, row.approved_at = "APPROVED", actor_id, _now()
    db.flush()
    _audit(db, actor_id, "approved", "jp_yea_declaration", row.id)
    return row


def list_declarations(db: Session, organization_id: int, employee_id: int, tax_year: Optional[int] = None):
    m = _models()
    q = db.query(m.PayrollJpYeaDeclaration).filter(
        m.PayrollJpYeaDeclaration.organization_id == organization_id,
        m.PayrollJpYeaDeclaration.employee_id == employee_id)
    if tax_year:
        q = q.filter(m.PayrollJpYeaDeclaration.tax_year == int(tax_year))
    return [_row(r) for r in q.order_by(m.PayrollJpYeaDeclaration.id).all()]


# ── cases ───────────────────────────────────────────────────────────────────
def _case(db: Session, organization_id: int, case_id: int):
    m = _models()
    case = (db.query(m.PayrollJpYeaCase)
            .filter(m.PayrollJpYeaCase.id == case_id, m.PayrollJpYeaCase.organization_id == organization_id).first())
    if case is None:
        raise NotFoundException("Japan year-end case not found.")
    return case


def open_case(db: Session, organization_id: int, employee_id: int, tax_year: int, actor_id: Optional[int]):
    from app.modules.payroll import japan_service

    m = _models()
    japan_service._jp_employee(db, organization_id, employee_id)
    live = (db.query(m.PayrollJpYeaCase)
            .filter(m.PayrollJpYeaCase.organization_id == organization_id,
                    m.PayrollJpYeaCase.employee_id == employee_id,
                    m.PayrollJpYeaCase.tax_year == int(tax_year),
                    m.PayrollJpYeaCase.state != "VOID").first())
    if live is not None:
        raise BadRequestException(f"A {live.state} year-end case already exists for {tax_year}.")
    case = m.PayrollJpYeaCase(organization_id=organization_id, employee_id=employee_id, tax_year=int(tax_year),
                              state="OPEN", created_by_id=actor_id)
    db.add(case)
    db.flush()
    _audit(db, actor_id, "created", "jp_yea_case", case.id, new={"taxYear": int(tax_year)})
    return case


def annual_figures(db: Session, organization_id: int, employee_id: int, tax_year: int) -> dict:
    """Annual pay, withholding (before any earlier year-end difference) and
    social insurance from the committed payslips of the year."""
    m = _models()
    rows = (db.query(m.PayslipItem, m.PayrollRun.pay_date)
            .join(m.PayrollRun, m.PayrollRun.id == m.PayslipItem.payroll_run_id)
            .filter(m.PayslipItem.organization_id == organization_id,
                    m.PayslipItem.employee_id == employee_id,
                    m.PayslipItem.country_code == JP,
                    m.PayrollRun.status.in_(_COMMITTED),
                    m.PayrollRun.pay_date >= date(tax_year, 1, 1),
                    m.PayrollRun.pay_date <= date(tax_year, 12, 31))
            .order_by(m.PayrollRun.pay_date, m.PayslipItem.id).all())
    latest_by_original, order = {}, []
    for item, pay_date in rows:
        snap = item.jp_calculation_snapshot or {}
        original = (snap.get("correction") or {}).get("originalPayslipId") or item.id
        if original not in latest_by_original:
            order.append(original)
        latest_by_original[original] = (snap, pay_date)
    income = withheld = si = ZERO
    payslips, latest = [], None
    for original in order:
        snap, pay_date = latest_by_original[original]
        if not snap:
            raise BadRequestException(f"Committed payslip #{original} has no frozen Japan result.")
        bonus = snap.get("jp_bonus") or {}
        wht_base = ((snap.get("trace") or {}).get("bases") or {}).get("WHT", {}).get("base")
        income += _dec(wht_base) + _dec(bonus.get("jp_bonus"))
        withheld += _dec(snap.get("jp_wht_total")) + _dec(snap.get("jp_yea_difference"))
        si += (_dec(snap.get("jp_si_employee_total")) + _dec(snap.get("jp_ei_employee"))
               + _dec(bonus.get("jp_bonus_si_employee_total")) + _dec(bonus.get("jp_bonus_ei_employee")))
        payslips.append(original)
        if latest is None or pay_date >= latest[1]:
            latest = (snap, pay_date)
    if latest is None:
        raise BadRequestException(f"No committed Japan payslip in {tax_year}; nothing to adjust.")
    frozen = latest[0].get("frozenContext") or {}
    profile = frozen.get("profile") or {}
    return {"annualIncome": str(income), "taxWithheld": str(withheld), "socialInsuranceWithheld": str(si),
            "residency": profile.get("residency_status"), "declarationClass": profile.get("declaration_class"),
            "payslips": payslips, "latestPayDate": latest[1].isoformat(), "frozen": frozen}


def calculate_case(db: Session, organization_id: int, case_id: int, actor_id: Optional[int]):
    from app.modules.payroll import japan_service
    from app.modules.payroll.engine.countries import japan as engine
    from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError
    from app.modules.payroll.engine.jurisdictions.japan import year_end

    m = _models()
    case = _case(db, organization_id, case_id)
    if case.state not in ("OPEN", "CALCULATED", "EXCLUDED"):
        raise BadRequestException(f"A {case.state} case cannot be recalculated.")
    figures = annual_figures(db, organization_id, case.employee_id, case.tax_year)
    frozen = figures.pop("frozen")
    ctx = japan_service.jp_thaw_context(frozen)
    pack = engine._Pack(ctx.rate_map, organization_id, as_of=date(case.tax_year, 12, 31))
    declarations = {r.declaration_type: r.payload for r in db.query(m.PayrollJpYeaDeclaration).filter(
        m.PayrollJpYeaDeclaration.organization_id == organization_id,
        m.PayrollJpYeaDeclaration.employee_id == case.employee_id,
        m.PayrollJpYeaDeclaration.tax_year == case.tax_year,
        m.PayrollJpYeaDeclaration.status == "APPROVED")}
    try:
        reason = year_end.yea_eligibility(figures, pack)
        result = None if reason else year_end.year_end_tax(figures, declarations, ctx.slabs, pack,
                                                           as_of=date(case.tax_year, 12, 31))
    except MissingComplianceConfigurationError as exc:
        raise BadRequestException(f"Year-end adjustment blocked ({exc.key}): {exc}")
    case.facts = {**figures, "declarations": declarations}
    case.annual_income = _dec(figures["annualIncome"])
    case.tax_withheld = _dec(figures["taxWithheld"])
    case.si_withheld = _dec(figures["socialInsuranceWithheld"])
    case.calculated_at = _now()
    if reason:
        case.state, case.excluded_reason = "EXCLUDED", reason
        case.annual_tax = case.difference = None
        case.result = {"calculatedBy": actor_id, "excludedReason": reason}
    else:
        case.state, case.excluded_reason = "CALCULATED", None
        case.annual_tax, case.difference = result.annual_tax, result.difference
        case.result = {**result.trace, "calculatedBy": actor_id}
    db.flush()
    _audit(db, actor_id, "calculated", "jp_yea_case", case.id,
           new={"state": case.state, "difference": None if case.difference is None else str(case.difference)})
    return case


def review_case(db: Session, organization_id: int, case_id: int, actor_id: Optional[int]):
    from app.modules.payroll.service import require_four_eyes

    case = _case(db, organization_id, case_id)
    if case.state != "CALCULATED":
        raise BadRequestException("Only a CALCULATED case is reviewed.")
    require_four_eyes((case.result or {}).get("calculatedBy"), actor_id, "Reviewing a Japan year-end adjustment",
                      db=db, entity_type="jp_yea_case", entity_id=case.id, current_status=case.state)
    case.state, case.reviewed_by_id, case.reviewed_at = "REVIEWED", actor_id, _now()
    db.flush()
    _audit(db, actor_id, "reviewed", "jp_yea_case", case.id)
    return case


def apply_case(db: Session, organization_id: int, case_id: int, run_id: int, actor_id: Optional[int]):
    """Target a REVIEWED case at one open salary run of the tax year, no
    earlier than the signed month. The run must then be recalculated; its
    approval is refused until the payslip carries the case."""
    m = _models()
    case = _case(db, organization_id, case_id)
    if case.state != "REVIEWED":
        raise BadRequestException("Only a REVIEWED case is applied.")
    run = (db.query(m.PayrollRun)
           .filter(m.PayrollRun.id == run_id, m.PayrollRun.organization_id == organization_id).first())
    if run is None:
        raise NotFoundException("Payroll run not found.")
    if str(getattr(run.status, "value", run.status)).upper() not in {s.upper() for s in _OPEN_RUN}:
        raise BadRequestException("A year-end adjustment is applied to an open (Draft / Review) run.")
    if (getattr(run, "jp_payment_kind", None) or "SALARY").upper() != "SALARY":
        raise BadRequestException("A year-end adjustment is settled with a salary payment, not a bonus payment.")
    if run.pay_date is None or run.pay_date.year != case.tax_year:
        raise BadRequestException(f"The run must pay in {case.tax_year}.")
    figures = annual_figures(db, organization_id, case.employee_id, case.tax_year)
    frozen_rates = (figures.get("frozen") or {}).get("rateMap") or {}
    earliest = str((frozen_rates.get("jp_yea_earliest_month") or {}).get("text_value") or "").strip()
    if not earliest.isdigit() or not 1 <= int(earliest) <= 12:
        raise BadRequestException(f"Year-end adjustment blocked: jp_yea_earliest_month is "
                                  f"{earliest or 'not configured'} (signed at G1).")
    if run.pay_date.month < int(earliest):
        raise BadRequestException(f"A year-end adjustment is applied no earlier than month {int(earliest):02d}.")
    case.state, case.applied_run_id = "APPLIED", run.id
    case.applied_by_id, case.applied_at = actor_id, _now()
    db.flush()
    _audit(db, actor_id, "applied", "jp_yea_case", case.id, new={"runId": run.id})
    return case


def void_case(db: Session, organization_id: int, case_id: int, actor_id: Optional[int]):
    m = _models()
    case = _case(db, organization_id, case_id)
    if case.state == "LOCKED":
        raise BadRequestException("A LOCKED case is changed only through a correction.")
    if case.state == "APPLIED":
        run = db.get(m.PayrollRun, case.applied_run_id) if case.applied_run_id else None
        if run is not None and str(getattr(run.status, "value", run.status)).upper() not in {s.upper() for s in _OPEN_RUN}:
            raise BadRequestException("The run carrying this adjustment is no longer open.")
    case.state = "VOID"
    db.flush()
    _audit(db, actor_id, "voided", "jp_yea_case", case.id)
    return case


def require_cases_reflected(db: Session, run) -> None:
    """Approval gate: every case applied to the run must be carried by the
    employee's payslip (recalculate after applying)."""
    from fastapi import HTTPException, status as http_status

    m = _models()
    for case in (db.query(m.PayrollJpYeaCase)
                 .filter(m.PayrollJpYeaCase.applied_run_id == run.id, m.PayrollJpYeaCase.state == "APPLIED")):
        item = (db.query(m.PayslipItem)
                .filter(m.PayslipItem.payroll_run_id == run.id, m.PayslipItem.employee_id == case.employee_id,
                        m.PayslipItem.country_code == JP).first())
        carried = ((item.jp_calculation_snapshot or {}).get("jp_yea_case_id") if item else None)
        if carried != case.id:
            raise HTTPException(http_status.HTTP_409_CONFLICT, detail=(
                f"Japan: year-end case #{case.id} is applied to this run but employee #{case.employee_id}'s "
                "payslip does not carry it — recalculate the run before approval."))


def lock_cases_for_run(db: Session, run) -> None:
    m = _models()
    for case in (db.query(m.PayrollJpYeaCase)
                 .filter(m.PayrollJpYeaCase.applied_run_id == run.id, m.PayrollJpYeaCase.state == "APPLIED")):
        case.state, case.locked_at = "LOCKED", _now()
    db.flush()


def list_cases(db: Session, organization_id: int, tax_year: int) -> list:
    m = _models()
    return [_row(c) for c in db.query(m.PayrollJpYeaCase).filter(
        m.PayrollJpYeaCase.organization_id == organization_id,
        m.PayrollJpYeaCase.tax_year == int(tax_year)).order_by(m.PayrollJpYeaCase.employee_id).all()]
