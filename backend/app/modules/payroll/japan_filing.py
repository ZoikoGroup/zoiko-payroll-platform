"""
japan_filing.py — Japan remittance obligations and statutory filings
(ZP-JP-ENG-001 §2, §8, §9; Phase 8).

  * obligations  written ONCE when a run is PAID, from the frozen payslip
                 results: withholding (by the signed day of the following
                 month), social insurance (employee + employer, by the end of
                 the following month) and resident tax per municipality.
                 Employment insurance is settled through the annual labour-
                 insurance declaration, not monthly, so it has no obligation
                 here. A due-date rule that is not signed leaves due_on empty;
                 dates are never moved for holidays (jp_wht_due_non_business_day_rule
                 is PENDING_G1).
  * workflow     CREATED -> APPROVED (a second person) -> SUBMITTED (channel)
                 -> ACCEPTED / REJECTED with the receipt.
  * previews     withholding certificate, salary payment reports by
                 municipality, JPS bonus report, annual determination report
                 — JSON only. Every submission FILE is refused until G5
                 certifies its schema (content.JP_EXPORT_SCHEMAS is empty).
    No preview ever carries a My Number.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException

JP = "JP"
ZERO = Decimal("0")
OBLIGATION_STATUSES = ("CREATED", "APPROVED", "SUBMITTED", "ACCEPTED", "REJECTED", "CORRECTED")
DOCUMENTS = ("WITHHOLDING_CERTIFICATE", "SALARY_PAYMENT_REPORT", "BONUS_PAYMENT_REPORT",
             "ANNUAL_DETERMINATION_REPORT")


def _models():
    from app.modules.payroll import models

    return models


def _content():
    from app.modules.payroll.engine.countries import japan_content

    return japan_content


def _dec(value) -> Decimal:
    return Decimal(str(value)) if value not in (None, "") else ZERO


def _items(db: Session, run) -> list:
    m = _models()
    return (db.query(m.PayslipItem)
            .filter(m.PayslipItem.payroll_run_id == run.id, m.PayslipItem.country_code == JP)
            .order_by(m.PayslipItem.id).all())


def _registration(db: Session, organization_id: int, on: date):
    from app.modules.payroll import japan_service

    return japan_service._jp_one_active(db, _models().PayrollJpEmployerRegistration, organization_id,
                                        None, on, "employer registration")


def refuse_uncertified_remittance_scheme(db: Session, run) -> None:
    """The small-employer twice-yearly withholding remittance scheme has no
    signed rule: a run for such an employer is refused, never remitted on an
    assumed date."""
    from fastapi import HTTPException, status as http_status

    if run.pay_date is None:
        return
    registration = _registration(db, run.organization_id, run.pay_date)
    if registration is not None and (registration.withholding_payer_status or "") == "SMALL_EMPLOYER_SPECIAL":
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail=(
            "Japan: the small-employer twice-yearly withholding remittance scheme is not certified; "
            "the run cannot be approved or paid."))


def _rate(frozen: dict, key: str) -> dict:
    return (frozen.get("rateMap") or {}).get(key) or {}


def _next_month(on: date):
    return (on.year + 1, 1) if on.month == 12 else (on.year, on.month + 1)


def _day_of_next_month(on: date, day) -> Optional[date]:
    if day in (None, ""):
        return None
    year, month = _next_month(on)
    return date(year, month, min(int(Decimal(str(day))), calendar.monthrange(year, month)[1]))


def _si_due(on: date, rule: str) -> Optional[date]:
    if (rule or "").upper() != "LAST_DAY_FOLLOWING_MONTH":
        return None
    year, month = _next_month(on)
    return date(year, month, calendar.monthrange(year, month)[1])


def record_run_obligations(db: Session, run, actor_id: Optional[int]) -> list:
    """Write the run's remittance obligations once (idempotent per run and
    key). Reads only the frozen payslip results and the frozen rate rows."""
    m = _models()
    items = [i for i in _items(db, run) if i.jp_calculation_snapshot]
    if not items or run.pay_date is None:
        return []
    frozen = (items[0].jp_calculation_snapshot or {}).get("frozenContext") or {}
    period = f"{run.pay_date.year}-{run.pay_date.month:02d}"
    wht = si = ZERO
    resident = {}
    for item in items:
        snap = item.jp_calculation_snapshot
        wht += _dec(snap.get("jp_wht_total"))
        bonus = snap.get("jp_bonus") or {}
        si += (_dec(snap.get("jp_si_employee_total")) + _dec(snap.get("jp_si_employer_total"))
               + _dec(bonus.get("jp_bonus_si_employee_total")) + _dec(bonus.get("jp_bonus_si_employer_total")))
        amount = _dec(snap.get("jp_resident_tax"))
        if amount > ZERO:
            code = str((snap.get("jp_resident_tax_notice") or {}).get("municipality") or "")
            if not code:
                raise BadRequestException(f"Payslip #{item.id} has resident tax but no notice municipality.")
            resident[code] = resident.get(code, ZERO) + amount
    wanted = [("WHT_REMITTANCE", None, wht,
               _day_of_next_month(run.pay_date, _rate(frozen, "jp_wht_remittance_due_day").get("flat_amount")),
               "jp_wht_remittance_due_day")]
    wanted.append(("SI_REMITTANCE", None, si,
                   _si_due(run.pay_date, _rate(frozen, "jp_si_remittance_due").get("text_value")),
                   "jp_si_remittance_due"))
    for code, amount in sorted(resident.items()):
        wanted.append(("RESIDENT_TAX_REMITTANCE", code, amount,
                       _day_of_next_month(run.pay_date,
                                          _rate(frozen, "jp_resident_tax_remittance_due_day").get("flat_amount")),
                       "jp_resident_tax_remittance_due_day"))
    created = []
    for kind, municipality, amount, due, rule in wanted:
        key = f"{kind}:{municipality or '-'}"
        exists = (db.query(m.PayrollJpObligation)
                  .filter(m.PayrollJpObligation.source_run_id == run.id,
                          m.PayrollJpObligation.obligation_key == key).first())
        if exists is not None:
            continue
        row = m.PayrollJpObligation(
            organization_id=run.organization_id, obligation_type=kind, obligation_key=key, period=period,
            municipality_code=municipality, due_on=due, amount=max(ZERO, amount), source_run_id=run.id,
            status="CREATED", created_by_id=actor_id,
            detail={"netAmount": str(amount), "dueRule": rule if due else f"{rule} not signed — no due date",
                    "holidayShift": "NOT APPLIED (jp_wht_due_non_business_day_rule PENDING_G1)",
                    "payslips": [i.id for i in items]})
        db.add(row)
        created.append(row)
    db.flush()
    return created


def _row(row) -> dict:
    return {c.name: (getattr(row, c.name).isoformat() if isinstance(getattr(row, c.name), (date, datetime))
                     else (str(getattr(row, c.name)) if isinstance(getattr(row, c.name), Decimal)
                           else getattr(row, c.name)))
            for c in row.__table__.columns}


def list_obligations(db: Session, organization_id: int, status: Optional[str] = None) -> list:
    m = _models()
    q = db.query(m.PayrollJpObligation).filter(m.PayrollJpObligation.organization_id == organization_id)
    if status:
        q = q.filter(m.PayrollJpObligation.status == status.strip().upper())
    return [_row(r) for r in q.order_by(m.PayrollJpObligation.due_on.is_(None),
                                        m.PayrollJpObligation.due_on, m.PayrollJpObligation.id).all()]


def _obligation(db: Session, organization_id: int, obligation_id: int):
    m = _models()
    row = (db.query(m.PayrollJpObligation)
           .filter(m.PayrollJpObligation.id == obligation_id,
                   m.PayrollJpObligation.organization_id == organization_id).first())
    if row is None:
        raise NotFoundException("Japan obligation not found.")
    return row


def approve_obligation(db: Session, organization_id: int, obligation_id: int, actor_id: Optional[int]) -> dict:
    from app.modules.payroll.service import require_four_eyes

    row = _obligation(db, organization_id, obligation_id)
    if row.status != "CREATED":
        raise BadRequestException(f"Only a CREATED obligation can be approved (this one is {row.status}).")
    require_four_eyes(row.created_by_id, actor_id, "Approving a Japan remittance", db=db,
                      entity_type="jp_obligation", entity_id=row.id, current_status=row.status)
    row.status, row.approved_by_id, row.approved_at = "APPROVED", actor_id, datetime.now(timezone.utc)
    db.flush()
    return _row(row)


def submit_obligation(db: Session, organization_id: int, obligation_id: int, channel: str) -> dict:
    """Record that an APPROVED remittance was made through ``channel`` (bank,
    e-Tax payment, eLTAX). No file is produced here."""
    row = _obligation(db, organization_id, obligation_id)
    if row.status != "APPROVED":
        raise BadRequestException("Only an APPROVED obligation can be submitted.")
    if not (channel or "").strip():
        raise BadRequestException("The submission channel is required.")
    row.status, row.channel, row.submitted_at = "SUBMITTED", channel.strip()[:40], datetime.now(timezone.utc)
    db.flush()
    return _row(row)


def record_obligation_receipt(db: Session, organization_id: int, obligation_id: int, *, accepted: bool,
                              receipt_ref: Optional[str]) -> dict:
    row = _obligation(db, organization_id, obligation_id)
    if row.status != "SUBMITTED":
        raise BadRequestException("A receipt is recorded only for a SUBMITTED obligation.")
    if accepted and not (receipt_ref or "").strip():
        raise BadRequestException("An accepted remittance needs its receipt reference.")
    row.status = "ACCEPTED" if accepted else "REJECTED"
    row.receipt_ref = (receipt_ref or "").strip()[:100] or None
    db.flush()
    return _row(row)


# ── previews (JSON only) ────────────────────────────────────────────────────
def export_refusal(document: str) -> Optional[str]:
    """The reason a submission file cannot be produced, or None once G5 has
    certified a schema for the document."""
    if document not in DOCUMENTS:
        return f"unknown document {document!r}"
    if document not in _content().JP_EXPORT_SCHEMAS:
        return (f"no certified export schema for {document} (e-Tax / eLTAX / Japan Pension Service formats "
                "are certified at G5); only a JSON preview is available")
    return None


def _employee(db: Session, organization_id: int, employee_id: int):
    from app.modules.payroll import japan_service

    return japan_service._jp_employee(db, organization_id, employee_id)


def withholding_certificate(db: Session, organization_id: int, case_id: int) -> dict:
    """The withholding certificate content (S5) from an APPLIED / LOCKED
    year-end case, or an EXCLUDED case's annual figures. No My Number."""
    m = _models()
    case = (db.query(m.PayrollJpYeaCase)
            .filter(m.PayrollJpYeaCase.id == case_id, m.PayrollJpYeaCase.organization_id == organization_id).first())
    if case is None:
        raise NotFoundException("Japan year-end case not found.")
    if case.state not in ("APPLIED", "LOCKED", "EXCLUDED"):
        raise BadRequestException("A certificate is prepared from an APPLIED, LOCKED or EXCLUDED year-end case.")
    employee = _employee(db, organization_id, case.employee_id)
    registration = _registration(db, organization_id, date(case.tax_year, 12, 31))
    result = case.result or {}
    return {"document": "WITHHOLDING_CERTIFICATE", "taxYear": case.tax_year,
            "payer": {"corporateNumber": getattr(registration, "corporate_number", None),
                      "withholdingTaxOffice": getattr(registration, "withholding_tax_office", None)},
            "employee": {"id": employee.id, "name": employee.name, "employeeCode": employee.employee_code},
            "yearEndAdjusted": case.state != "EXCLUDED", "excludedReason": case.excluded_reason,
            "paymentAmount": str(case.annual_income or 0),
            "employmentIncome": result.get("employmentIncome"),
            "deductions": result.get("deductions"),
            "socialInsurance": str(case.si_withheld or 0),
            "annualTax": str(case.annual_tax) if case.annual_tax is not None else None,
            "withheld": str(case.tax_withheld or 0),
            "exportRefusal": export_refusal("WITHHOLDING_CERTIFICATE")}


def salary_payment_reports(db: Session, organization_id: int, tax_year: int) -> dict:
    """Salary payment reports (S5) grouped by the municipality of residence on
    1 January of the following year (the worker tax profile in force then).
    An employee with no recorded municipality is listed, never guessed."""
    from app.modules.payroll import japan_service

    m = _models()
    cases = (db.query(m.PayrollJpYeaCase)
             .filter(m.PayrollJpYeaCase.organization_id == organization_id,
                     m.PayrollJpYeaCase.tax_year == tax_year,
                     m.PayrollJpYeaCase.state.in_(("APPLIED", "LOCKED", "EXCLUDED")))
             .order_by(m.PayrollJpYeaCase.employee_id).all())
    january = date(tax_year + 1, 1, 1)
    groups, unrouted = {}, []
    for case in cases:
        profile = japan_service._jp_one_active(db, m.PayrollJpWorkerTaxProfile, organization_id,
                                               case.employee_id, january, "worker tax profile")
        code = getattr(profile, "municipality_code", None)
        entry = {"employeeId": case.employee_id, "caseId": case.id,
                 "paymentAmount": str(case.annual_income or 0),
                 "annualTax": None if case.annual_tax is None else str(case.annual_tax)}
        if code:
            groups.setdefault(code, []).append(entry)
        else:
            unrouted.append(entry)
    return {"document": "SALARY_PAYMENT_REPORT", "taxYear": tax_year,
            "byMunicipality": [{"municipalityCode": k, "employees": v} for k, v in sorted(groups.items())],
            "unrouted": unrouted, "exportRefusal": export_refusal("SALARY_PAYMENT_REPORT")}


def bonus_payment_report(db: Session, organization_id: int, paid_on) -> dict:
    m = _models()
    paid = date.fromisoformat(str(paid_on)[:10])
    rows = (db.query(m.PayrollJpSocialInsuranceEvent)
            .filter(m.PayrollJpSocialInsuranceEvent.organization_id == organization_id,
                    m.PayrollJpSocialInsuranceEvent.event_type == "BONUS",
                    m.PayrollJpSocialInsuranceEvent.bonus_paid_on == paid,
                    m.PayrollJpSocialInsuranceEvent.submission_status.notin_(("REJECTED", "CORRECTED")))
            .order_by(m.PayrollJpSocialInsuranceEvent.employee_id).all())
    return {"document": "BONUS_PAYMENT_REPORT", "paidOn": paid.isoformat(),
            "reportDueOn": rows[0].report_due_on.isoformat() if rows and rows[0].report_due_on else None,
            "employees": [{"employeeId": r.employee_id, "sbaAmount": str(r.sba_amount or 0),
                           "eventId": r.id, "status": r.submission_status} for r in rows],
            "exportRefusal": export_refusal("BONUS_PAYMENT_REPORT")}


def annual_determination_report(db: Session, organization_id: int, year: int) -> dict:
    m = _models()
    rows = (db.query(m.PayrollJpSocialInsuranceEvent)
            .filter(m.PayrollJpSocialInsuranceEvent.organization_id == organization_id,
                    m.PayrollJpSocialInsuranceEvent.event_type == "ANNUAL_DETERMINATION",
                    m.PayrollJpSocialInsuranceEvent.effective_from >= date(year, 1, 1),
                    m.PayrollJpSocialInsuranceEvent.effective_from <= date(year, 12, 31),
                    m.PayrollJpSocialInsuranceEvent.submission_status.notin_(("REJECTED",)))
            .order_by(m.PayrollJpSocialInsuranceEvent.employee_id).all())
    return {"document": "ANNUAL_DETERMINATION_REPORT", "year": year,
            "employees": [{"employeeId": r.employee_id, "eventId": r.id, "effectiveFrom": r.effective_from.isoformat(),
                           "proposal": {k: v for k, v in (r.payload or {}).items() if k.startswith("smr_")},
                           "status": r.submission_status} for r in rows],
            "exportRefusal": export_refusal("ANNUAL_DETERMINATION_REPORT")}
