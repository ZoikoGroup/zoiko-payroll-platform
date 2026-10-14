"""
payroll/netherlands_filing_service.py
-------------------------------------
Loonaangifte (wage tax return) builder for NL payroll.

Builds the return from committed results; supports nil and zero returns;
checks against the schema; reconciles to committed totals; handles the
correction chain; keeps transport acknowledgement, statutory acceptance
and payment as three separate states (NL-038).

No Digipoort transport here — that's the adapter in netherlands_digipoort.py.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.modules.payroll.models import (
    PayrollEmployee,
    PayrollNlAuthorityPayment,
    PayrollNlContractVersion,
    PayrollNlDigipoortSubmission,
    PayrollNlEmployerProfile,
    PayrollNlIncomeRelationship,
    PayrollNlLoonaangifteLine,
    PayrollNlLoonaangifteReturn,
    PayrollNlTerminationSettlement,
    PayrollNlVcrSnapshot,
    PayrollNlWkrAccumulator,
    PayrollRun,
    PayrollStatus,
    PayslipItem,
)
from app.modules.payroll.netherlands_service import (
    committed_vcr_state,
    _position,
    _correction_chain,
    VcrFamily,
)
from app.core.exceptions import BadRequestException, NotFoundException


SPEC_VERSION = "2026.1"
NL = "NL"


# ── Period code helpers ────────────────────────────────────────────────

def period_code_for(tax_year: int, period_start: date, return_period: str) -> str:
    """Build the Belastingdienst period code.
    MONTH: YYYYMM (e.g., 202601)
    FOUR_WEEK: YYYYWNN (e.g., 2026W01)
    """
    if return_period == "MONTH":
        return f"{tax_year}{period_start.month:02d}"
    if return_period == "FOUR_WEEK":
        # ISO week number; 4-week periods approximate
        week = period_start.isocalendar()[1]
        return f"{tax_year}W{week:02d}"
    raise BadRequestException(f"unknown return_period {return_period}")


def period_dates_for(tax_year: int, period_code: str, return_period: str) -> Tuple[date, date]:
    """Reverse of period_code_for: compute period_start/end from code."""
    if return_period == "MONTH":
        month = int(period_code[-2:])
        start = date(tax_year, month, 1)
        if month == 12:
            end = date(tax_year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(tax_year, month + 1, 1) - timedelta(days=1)
        return start, end
    if return_period == "FOUR_WEEK":
        # Approximate: 4-week periods starting from Jan 1
        week = int(period_code[-2:])
        start = date(tax_year, 1, 1) + timedelta(weeks=week - 1)
        end = start + timedelta(days=27)
        return start, end
    raise BadRequestException(f"unknown return_period {return_period}")


def due_dates_for(tax_year: int, period_start: date, return_period: str) -> Tuple[date, date]:
    """Filing and payment due date: the last day of the month following the
    period's last month (monthly), or of the month following the 4-week
    period's end. Payment is due on the same date."""
    if return_period == "MONTH":
        _, period_end = period_dates_for(tax_year, f"{tax_year}{period_start.month:02d}", "MONTH")
    elif return_period == "FOUR_WEEK":
        period_end = period_start + timedelta(days=27)
    else:
        raise BadRequestException(f"unknown return_period {return_period}")
    first_of_next = (period_end.replace(day=1) + timedelta(days=32)).replace(day=1)
    due = (first_of_next + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    return due, due


# ── Period lines from COMMITTED payroll ──────────────────────────────────
#
# A return covers the NL payslips of runs that are COMMITTED (their VCR / WKR /
# vacation ledgers were written at approval) and are NOT correction runs, with
# a pay date in the period. A correction delta is never a line of its own:
#   * REGULAR / RESEND returns report each original payslip as calculated;
#   * a CORRECTION return reports, per employee, the latest COMMITTED corrected
#     position (full replacement of that employee's period data), linked to the
#     line it corrects. Nothing is ever counted twice.
# Wage bases come from the engine's own frozen BASES trace (loon LB/PH = table
# wage + special wage; SV wage; Zvw wage) — never re-derived from gross pay.

_ZERO = Decimal("0")
_TOTAL_KEYS = ("total_wage_tax", "total_awf", "total_aof", "total_whk", "total_wko",
               "total_zvw_employer", "total_zvw_employee", "total_final_levies")


def _d(value) -> Decimal:
    return Decimal(str(value)) if value not in (None, "") else _ZERO


def _bases(result: Dict[str, Any]) -> Dict[str, Decimal]:
    trace = next((t for t in result.get("trace") or [] if t.get("code") == "BASES"), None)
    if trace is None:
        raise FilingError("payslip snapshot has no engine BASES trace — recalculate it before filing")
    return {"lb_phf": _d(trace.get("tableWage")) + _d(trace.get("specialWage")),
            "sv": _d(trace.get("eiWage")), "zvw": _d(trace.get("zvwWage"))}


def _period_items(db: Session, organization_id: int, period_start: date, period_end: date) -> List[PayslipItem]:
    from app.modules.payroll.netherlands_service import is_nl_correction_run, run_committed

    rows = (db.query(PayslipItem, PayrollRun).join(PayrollRun, PayslipItem.payroll_run_id == PayrollRun.id)
            .filter(PayrollRun.organization_id == organization_id, PayslipItem.country_code == NL,
                    PayrollRun.pay_date >= period_start, PayrollRun.pay_date <= period_end)
            .order_by(PayslipItem.id).all())
    return [item for item, run in rows
            if not is_nl_correction_run(run) and run_committed(db, run) and item.nl_calculation_snapshot]


def _committed_link(db: Session, item: PayslipItem) -> Optional[PayslipItem]:
    """The latest correction of this payslip whose correction run is committed."""
    from app.modules.payroll.netherlands_service import run_committed

    for link in reversed(_correction_chain(db, item)):
        run = db.query(PayrollRun).filter(PayrollRun.id == link.payroll_run_id).one()
        if run_committed(db, run):
            return link
    return None


def _period_lines(db: Session, organization_id: int, period_start: date, period_end: date,
                  corrected: bool, previous_return_id: Optional[int] = None) -> List[Dict[str, Any]]:
    from app.modules.payroll.netherlands_service import nl_replay

    previous = {}
    if previous_return_id:
        previous = {l.employee_id: l.id for l in db.query(PayrollNlLoonaangifteLine)
                    .filter(PayrollNlLoonaangifteLine.return_id == previous_return_id).all()}
    lines = []
    for item in _period_items(db, organization_id, period_start, period_end):
        snap = item.nl_calculation_snapshot
        pos, result, line_type = _position(snap), snap, "ORIGINAL"
        link = _committed_link(db, item) if corrected else None
        if link is not None:
            correction = link.nl_calculation_snapshot["correction"]
            pos, result, line_type = correction["corrected"], nl_replay(db, correction["frozen"]), "CORRECTION"
        bases = _bases(result)
        inputs = snap.get("inputs") or {}
        emp = db.query(PayrollEmployee).filter(PayrollEmployee.id == item.employee_id).one()
        ikv = (db.query(PayrollNlIncomeRelationship)
               .filter(PayrollNlIncomeRelationship.employee_id == item.employee_id,
                       PayrollNlIncomeRelationship.organization_id == organization_id,
                       PayrollNlIncomeRelationship.start_date <= period_end,
                       or_(PayrollNlIncomeRelationship.end_date.is_(None),
                           PayrollNlIncomeRelationship.end_date >= period_start))
               .order_by(PayrollNlIncomeRelationship.start_date.desc()).first())
        premiums = {k: str(_d((pos.get("premiums") or {}).get(k))) for k in ("awf", "aof", "wko", "whk")}
        line = {
            "employee_id": item.employee_id,
            "income_relationship_id": ikv.id if ikv else None,
            "personnel_number": emp.employee_code,
            "line_type": line_type,
            "correction_of_line_id": previous.get(item.employee_id) if line_type == "CORRECTION" else None,
            "wage_lb_phf": bases["lb_phf"], "wage_sv": bases["sv"], "wage_zvw": bases["zvw"],
            "hours": _d(inputs.get("periodHours")),
            "contract_flags": {"contract_term": (inputs.get("contract") or {}).get("contract_term"),
                               "on_call": bool((inputs.get("contract") or {}).get("on_call"))},
            "awf_class": (result.get("employeeInsurance") or {}).get("awfClass"),
            "premium_amounts": {**premiums, "zvwEmployer": str(_d(pos.get("zvwEr"))),
                                "zvwEmployee": str(_d(pos.get("zvwEe"))), "payslipItemId": item.id,
                                "correctionPayslipItemId": link.id if link is not None else None},
            "wage_tax": _d(pos.get("wageTax")),
            "zvw": _d(pos.get("zvwEe")) + _d(pos.get("zvwEr")),
            "official_codes": {},  # filled from the Gegevensspecificaties mapping (gate G3)
        }
        line["line_sha256"] = hashlib.sha256(json.dumps(line, sort_keys=True, default=str).encode()).hexdigest()
        lines.append(line)
    return lines


def _totals(lines: List[Dict[str, Any]]) -> Dict[str, Decimal]:
    totals = {k: _ZERO for k in _TOTAL_KEYS}
    for line in lines:
        p = line["premium_amounts"]
        totals["total_wage_tax"] += line["wage_tax"]
        totals["total_awf"] += _d(p.get("awf"))
        totals["total_aof"] += _d(p.get("aof"))
        totals["total_wko"] += _d(p.get("wko"))
        totals["total_whk"] += _d(p.get("whk"))          # the employer's Whk premium
        totals["total_zvw_employer"] += _d(p.get("zvwEmployer"))
        totals["total_zvw_employee"] += _d(p.get("zvwEmployee"))
    # WKR final levies are settled annually (payroll_nl_wkr_settlements), not per period.
    totals["total_payable"] = sum((totals[k] for k in _TOTAL_KEYS), _ZERO)
    return totals


# ── XML Payload generation (stub — requires Gegevensspecificaties XSD) ──

def _generate_payload_xml(return_obj: PayrollNlLoonaangifteReturn,
                           lines: List[PayrollNlLoonaangifteLine],
                           employer: PayrollNlEmployerProfile) -> str:
    """Generate the Loonaangifte XML per Gegevensspecificaties.
    This is a STUB — requires the actual XSD and field mappings from
    Belastingdienst. The real implementation uses lxml or generateDS.
    """
    # Placeholder structure — NOT the real schema; never transmitted live (gate G3).
    from xml.sax.saxutils import escape as _x
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Loonaangifte xmlns="urn:zoiko:placeholder:not-gegevensspecificaties">
  <Header>
    <Loonheffingennummer>{_x(str(employer.loonheffingennummer))}</Loonheffingennummer>
    <Periode>
      <Jaar>{_x(str(return_obj.tax_year))}</Jaar>
      <Code>{_x(str(return_obj.period_code))}</Code>
    </Periode>
    <ReturnType>{_x(str(return_obj.return_type))}</ReturnType>
    <Versie>{_x(str(return_obj.version))}</Versie>
    <SpecVersie>{_x(str(return_obj.spec_version))}</SpecVersie>
  </Header>
  <Totals>
    <Loonbelasting>{_x(str(return_obj.total_wage_tax))}</Loonbelasting>
    <AWF>{_x(str(return_obj.total_awf))}</AWF>
    <AOF>{_x(str(return_obj.total_aof))}</AOF>
    <WHK>{_x(str(return_obj.total_whk))}</WHK>
    <WKO>{_x(str(return_obj.total_wko))}</WKO>
    <ZVW_Werkgever>{_x(str(return_obj.total_zvw_employer))}</ZVW_Werkgever>
    <ZVW_Werknemer>{_x(str(return_obj.total_zvw_employee))}</ZVW_Werknemer>
    <Eindheffingen>{_x(str(return_obj.total_final_levies))}</Eindheffingen>
    <TotaalVerschuldigd>{_x(str(return_obj.total_payable))}</TotaalVerschuldigd>
  </Totals>
  <Regels>
'''
    for line in lines:
        xml += f'''    <Regel>
      <Personeelsnummer>{_x(str(line.personnel_number))}</Personeelsnummer>
      <Loon_LB_PHF>{_x(str(line.wage_lb_phf))}</Loon_LB_PHF>
      <Loon_SV>{_x(str(line.wage_sv))}</Loon_SV>
      <Loon_ZVW>{_x(str(line.wage_zvw))}</Loon_ZVW>
      <Uren>{_x(str(line.hours))}</Uren>
      <AWF_Klasse>{_x(str(line.awf_class or ''))}</AWF_Klasse>
      <Loonbelasting>{_x(str(line.wage_tax))}</Loonbelasting>
      <ZVW>{_x(str(line.zvw))}</ZVW>
    </Regel>
'''
    xml += '''  </Regels>
</Loonaangifte>'''
    return xml


# ── Public API ────────────────────────────────────────────────────────

class FilingError(BadRequestException):
    pass


class ReconciliationError(FilingError):
    pass


def build_loonaangifte_return(
    db: Session,
    organization_id: int,
    employer_profile_id: int,
    tax_year: int,
    period_code: str,
    return_type: str = "REGULAR",
    actor_id: Optional[int] = None,
    idempotency_key: Optional[str] = None,
    correction_of_id: Optional[int] = None,
) -> PayrollNlLoonaangifteReturn:
    """Build a loonaangifte return from COMMITTED payroll (see _period_lines).

    NIL / ZERO returns carry zero totals and no lines (NL-040). A CORRECTION
    return replaces the period data of the return it corrects. The default
    idempotency key is deterministic per (organisation, period, type, corrected
    return), so repeating a request returns the same return instead of a new one.
    """
    if return_type not in ("REGULAR", "NIL", "ZERO", "RESEND", "CORRECTION"):
        raise FilingError(f"unknown return_type {return_type!r}")
    if return_type == "CORRECTION" and correction_of_id is None:
        raise FilingError("a CORRECTION return must name the return it corrects")
    if idempotency_key is None:
        idempotency_key = hashlib.sha256(
            f"loonaangifte|{organization_id}|{tax_year}|{period_code}|{return_type}|{correction_of_id}".encode()
        ).hexdigest()
    existing = db.query(PayrollNlLoonaangifteReturn).filter(
        PayrollNlLoonaangifteReturn.idempotency_key == idempotency_key).first()
    if existing:
        return existing

    employer = db.query(PayrollNlEmployerProfile).filter(
        PayrollNlEmployerProfile.id == employer_profile_id,
        PayrollNlEmployerProfile.organization_id == organization_id).one_or_none()
    if not employer:
        raise NotFoundException("PayrollNlEmployerProfile", employer_profile_id)
    if not employer.loonheffingennummer:
        raise FilingError("the employer has no loonheffingennummer (NL-029)")

    period_start, period_end = period_dates_for(tax_year, period_code, employer.return_period)
    due_date, payment_due_date = due_dates_for(tax_year, period_start, employer.return_period)
    max_version = db.query(func.max(PayrollNlLoonaangifteReturn.version)).filter(
        PayrollNlLoonaangifteReturn.organization_id == organization_id,
        PayrollNlLoonaangifteReturn.tax_year == tax_year,
        PayrollNlLoonaangifteReturn.period_code == period_code).scalar() or 0

    if return_type in ("NIL", "ZERO"):
        lines_data = []
    else:
        lines_data = _period_lines(db, organization_id, period_start, period_end,
                                   corrected=return_type == "CORRECTION", previous_return_id=correction_of_id)
        if return_type == "REGULAR" and not lines_data:
            raise FilingError("no committed Dutch payroll in this period — file a NIL or ZERO return instead (NL-040)")
    totals = _totals(lines_data)

    ret = PayrollNlLoonaangifteReturn(
        organization_id=organization_id, employer_profile_id=employer_profile_id,
        loonheffingennummer=employer.loonheffingennummer, tax_year=tax_year, period_code=period_code,
        period_start=period_start, period_end=period_end, due_date=due_date, payment_due_date=payment_due_date,
        version=max_version + 1, return_type=return_type, correction_of_id=correction_of_id, status="READY",
        **totals, spec_version=SPEC_VERSION, idempotency_key=idempotency_key, created_by=actor_id,
    )
    db.add(ret)
    db.flush()
    for ld in lines_data:
        db.add(PayrollNlLoonaangifteLine(return_id=ret.id, **ld))
    db.flush()
    xml = _generate_payload_xml(ret, db.query(PayrollNlLoonaangifteLine).filter(
        PayrollNlLoonaangifteLine.return_id == ret.id).all(), employer)
    ret.payload_xml = xml
    ret.payload_sha256 = hashlib.sha256(xml.encode()).hexdigest()
    return ret


def reconcile_return(db: Session, return_id: int, actor_id: int) -> Dict[str, Any]:
    """Re-derive the return from committed payroll and compare (NL-038)."""
    ret = db.query(PayrollNlLoonaangifteReturn).filter(
        PayrollNlLoonaangifteReturn.id == return_id).one_or_none()
    if not ret:
        raise NotFoundException("PayrollNlLoonaangifteReturn", return_id)
    if ret.return_type in ("NIL", "ZERO"):
        expected = _totals([])
    else:
        expected = _totals(_period_lines(db, ret.organization_id, ret.period_start, ret.period_end,
                                         corrected=ret.return_type == "CORRECTION",
                                         previous_return_id=ret.correction_of_id))
    deltas = {k: {"expected": str(v), "actual": str(getattr(ret, k)), "delta": str(v - _d(getattr(ret, k)))}
              for k, v in expected.items() if _d(getattr(ret, k)) != v}
    if deltas:
        ret.reconciliation_report = {"status": "MISMATCH", "deltas": deltas}
        db.flush()
        raise ReconciliationError(f"Return totals do not match committed payroll: {json.dumps(deltas)}")
    report = {"status": "RECONCILED", "deltas": {}}
    ret.journal_reconciled = True
    ret.reconciliation_report = report
    db.flush()
    return report


def mark_filed(db: Session, return_id: int, actor_id: int, digipoort_reference: Optional[str] = None) -> PayrollNlLoonaangifteReturn:
    """Mark return as FILED after successful Digipoort transport (NL-038).
    Transport acknowledgement is separate from statutory acceptance.
    """
    ret = db.query(PayrollNlLoonaangifteReturn).filter(
        PayrollNlLoonaangifteReturn.id == return_id).one_or_none()
    if not ret:
        raise NotFoundException("PayrollNlLoonaangifteReturn", return_id)
    if ret.status != "READY":
        raise FilingError(f"Return must be READY to file (status={ret.status})")
    if not ret.journal_reconciled:
        raise FilingError("Return must be reconciled before filing (NL-038)")

    ret.status = "FILED"
    ret.filed_by = actor_id
    db.flush()
    return ret


def mark_accepted(db: Session, return_id: int) -> PayrollNlLoonaangifteReturn:
    """Mark return as ACCEPTED after Belastingdienst statutory acceptance.
    This is a separate state from transport ACK (NL-038).
    """
    ret = db.query(PayrollNlLoonaangifteReturn).filter(
        PayrollNlLoonaangifteReturn.id == return_id).one_or_none()
    if not ret:
        raise NotFoundException("PayrollNlLoonaangifteReturn", return_id)
    if ret.status != "FILED":
        raise FilingError(f"Return must be FILED to accept (status={ret.status})")

    ret.status = "ACCEPTED"
    db.flush()
    return ret


def mark_rejected(db: Session, return_id: int, error_codes: List[Dict[str, str]]) -> PayrollNlLoonaangifteReturn:
    """Mark return as REJECTED with Belastingdienst error codes."""
    ret = db.query(PayrollNlLoonaangifteReturn).filter(
        PayrollNlLoonaangifteReturn.id == return_id).one_or_none()
    if not ret:
        raise NotFoundException("PayrollNlLoonaangifteReturn", return_id)

    if ret.status != "FILED":
        raise FilingError(f"Only a FILED return can be rejected by the authority (status={ret.status})")
    ret.status = "REJECTED"
    # Store error codes on latest submission
    sub = db.query(PayrollNlDigipoortSubmission).filter(
        PayrollNlDigipoortSubmission.return_id == return_id).order_by(
        PayrollNlDigipoortSubmission.attempt_no.desc()).first()
    if sub:
        sub.error_codes = error_codes
    db.flush()
    return ret


def prepare_authority_payment(db: Session, return_id: int, actor_id: int,
                               payment_reference: str, bank_reference: Optional[str] = None,
                               value_date: Optional[date] = None) -> PayrollNlAuthorityPayment:
    """Prepare the authority payment record (NL-038)."""
    ret = db.query(PayrollNlLoonaangifteReturn).filter(
        PayrollNlLoonaangifteReturn.id == return_id).one_or_none()
    if not ret:
        raise NotFoundException("PayrollNlLoonaangifteReturn", return_id)
    if ret.status not in ("FILED", "ACCEPTED"):
        raise FilingError(f"Return must be FILED/ACCEPTED to prepare payment (status={ret.status})")

    payment = PayrollNlAuthorityPayment(
        organization_id=ret.organization_id,
        return_id=ret.id,
        amount=ret.total_payable,
        payment_reference=payment_reference,
        bank_reference=bank_reference,
        value_date=value_date or ret.payment_due_date,
        status="PREPARED",
        prepared_by=actor_id,
    )
    db.add(payment)
    db.flush()
    return payment


def release_payment(db: Session, payment_id: int, actor_id: int) -> PayrollNlAuthorityPayment:
    """Release the authority payment (after approval)."""
    payment = db.query(PayrollNlAuthorityPayment).filter(
        PayrollNlAuthorityPayment.id == payment_id).one_or_none()
    if not payment:
        raise NotFoundException("PayrollNlAuthorityPayment", payment_id)
    if payment.status != "PREPARED":
        raise FilingError(f"Payment must be PREPARED to release (status={payment.status})")
    if payment.prepared_by is not None and payment.prepared_by == actor_id:
        raise FilingError("The preparer cannot release the authority payment (four-eyes)")

    payment.status = "RELEASED"
    payment.released_by = actor_id
    db.flush()
    return payment


def settle_payment(db: Session, payment_id: int, bank_reference: str, settlement_evidence: str) -> PayrollNlAuthorityPayment:
    """Mark payment as SETTLED with bank evidence."""
    payment = db.query(PayrollNlAuthorityPayment).filter(
        PayrollNlAuthorityPayment.id == payment_id).one_or_none()
    if not payment:
        raise NotFoundException("PayrollNlAuthorityPayment", payment_id)
    if payment.status != "RELEASED":
        raise FilingError(f"Payment must be RELEASED to settle (status={payment.status})")

    payment.status = "SETTLED"
    payment.bank_reference = bank_reference
    payment.settlement_evidence = settlement_evidence
    payment.reconciled_at = datetime.utcnow()
    db.flush()
    return payment


def create_correction_return(
    db: Session,
    original_return_id: int,
    actor_id: int,
    idempotency_key: Optional[str] = None,
) -> PayrollNlLoonaangifteReturn:
    """Create a correction return (RESEND or CORRECTION) from an existing return.
    The correction rebuilds from committed data at the new version.
    """
    original = db.query(PayrollNlLoonaangifteReturn).filter(
        PayrollNlLoonaangifteReturn.id == original_return_id).one_or_none()
    if not original:
        raise NotFoundException("PayrollNlLoonaangifteReturn", original_return_id)

    return_type = "CORRECTION"
    new_return = build_loonaangifte_return(
        db=db,
        organization_id=original.organization_id,
        employer_profile_id=original.employer_profile_id,
        tax_year=original.tax_year,
        period_code=original.period_code,
        return_type=return_type,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        correction_of_id=original.id,
    )
    # Mark original as CORRECTED
    original.status = "CORRECTED"
    db.flush()
    return new_return


def get_return_with_lines(db: Session, return_id: int) -> Tuple[PayrollNlLoonaangifteReturn, List[PayrollNlLoonaangifteLine]]:
    ret = db.query(PayrollNlLoonaangifteReturn).filter(
        PayrollNlLoonaangifteReturn.id == return_id).one_or_none()
    if not ret:
        raise NotFoundException("PayrollNlLoonaangifteReturn", return_id)
    lines = db.query(PayrollNlLoonaangifteLine).filter(
        PayrollNlLoonaangifteLine.return_id == return_id).all()
    return ret, lines


def list_returns(db: Session, organization_id: int, tax_year: Optional[int] = None,
                  status: Optional[str] = None) -> List[PayrollNlLoonaangifteReturn]:
    q = db.query(PayrollNlLoonaangifteReturn).filter(
        PayrollNlLoonaangifteReturn.organization_id == organization_id)
    if tax_year:
        q = q.filter(PayrollNlLoonaangifteReturn.tax_year == tax_year)
    if status:
        q = q.filter(PayrollNlLoonaangifteReturn.status == status)
    return q.order_by(PayrollNlLoonaangifteReturn.tax_year.desc(),
                      PayrollNlLoonaangifteReturn.period_code.desc()).all()