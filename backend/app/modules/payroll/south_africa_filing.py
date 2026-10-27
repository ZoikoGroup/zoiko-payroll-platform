"""
modules/payroll/south_africa_filing.py
--------------------------------------
South Africa SARS filing and reconciliation (ZP-ZA-ENG-001 §9, ZA-015 and
ZA-018..ZA-020; Phase 8). "ZA" is South Africa; "SA" is Saudi Arabia.

Export-and-evidence, never portal automation (ZA-002):

  * build_za_emp201          monthly declaration from COMMITTED payroll, per
                             legal employer (ZA-014: no netting across orgs);
  * build_za_reconciliation  EMP501 interim (Mar–Aug) / annual (Mar–Feb):
                             payroll = EMP201 = payment = certificates, or an
                             approved explained variance (ZA-019);
  * build_za_certificates    canonical IRP5 / IT3(a) per employee — internal
                             line names only;
  * map_to_brs               the ONLY place that knows SARS BRS fields / source
                             codes (ZA-018). The catalogue is empty until the
                             official BRS v25.3.0 is archived, so it BLOCKS;
  * artefact lifecycle       versioned, hashed, four-eyes approved, never
                             overwritten; ACCEPTED only with a receipt (ZA-020);
  * build_za_coida_evidence  return-of-earnings evidence, no assessment rate.

"Committed" for South Africa = the run reached Approved or later (Approved,
Authorized, Paid, Closed): the results a second person has approved and that
can no longer be recalculated in place.
"""
from __future__ import annotations

import calendar
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll.engine.countries import south_africa_content as content

ZA = "ZA"
TWO = Decimal("0.01")
ZERO = Decimal("0")
COMMITTED_RUN_STATUSES = ("Approved", "Authorized", "Paid", "Closed")
ARTIFACT_TYPES = ("EMP201", "EMP501_INTERIM", "EMP501_ANNUAL", "IRP5", "IT3A", "CANCELLATION")
CHANNELS = ("EASYFILE", "EFILING")
DECLARED_STATUSES = ("APPROVED", "SUBMITTED", "ACCEPTED")
MEASURES = ("PAYROLL_VS_EMP201", "EMP201_VS_PAYMENT", "CERTIFICATES_VS_EMP201")


# ── small helpers ───────────────────────────────────────────────────────────
def _dec(value) -> Decimal:
    if value is None or value == "":
        return ZERO
    return Decimal(str(value))


def _money(value) -> str:
    return str(_dec(value).quantize(TWO, rounding=ROUND_HALF_UP))


def _scalar(key: str):
    for row in content.ZA_SCALAR_CONTENT:
        if row[0] == key:
            return row
    raise BadRequestException(f"South Africa content has no '{key}' row.")


def _text(key: str) -> str:
    return _scalar(key)[5]


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _month_bounds(period_key: str):
    try:
        year, month = (int(part) for part in period_key.split("-"))
        start = date(year, month, 1)
    except (ValueError, TypeError):
        raise BadRequestException(f"Period '{period_key}' must be YYYY-MM.")
    return start, date(year, month, calendar.monthrange(year, month)[1])


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _mask(value) -> Optional[str]:
    raw = str(value or "")
    if not raw:
        return None
    return "*" * max(len(raw) - 4, 0) + raw[-4:]


# ── committed ZA payslips ───────────────────────────────────────────────────
def _committed_items(db: Session, organization_id: int, start: date, end: date):
    from app.modules.payroll.models import PayrollRun, PayslipItem

    rows = (db.query(PayslipItem, PayrollRun)
            .join(PayrollRun, PayslipItem.payroll_run_id == PayrollRun.id)
            .filter(PayrollRun.organization_id == organization_id, PayslipItem.organization_id == organization_id,
                    PayslipItem.country_code == ZA,
                    PayrollRun.pay_date >= start, PayrollRun.pay_date <= end,
                    PayrollRun.status.in_(COMMITTED_RUN_STATUSES))
            .order_by(PayslipItem.id).all())
    return rows


def _payroll_totals(items) -> dict:
    paye = sum((_dec(i.tds) for i, _r in items), ZERO)
    sdl = sum((_dec(i.employer_payroll_tax) for i, _r in items), ZERO)
    uif = sum((_dec(i.esi) + _dec(i.employer_esi) for i, _r in items), ZERO)
    return {"paye": paye, "sdl": sdl, "uif": uif}


# ── due date (spec §9) ──────────────────────────────────────────────────────
def za_due_date(db: Session, organization_id: int, period_key: str):
    """(due_date, blocked_reason). Day za_emp201_due_day of the following month;
    a weekend or ZA public holiday moves it to the PRECEDING business day. With no
    ZA holiday rows recorded for that year the date is BLOCKED, never assumed."""
    from app.modules.payroll.models import PayrollHoliday

    _start, end = _month_bounds(period_key)
    nxt = end + timedelta(days=1)
    day = int(_dec(_scalar("za_emp201_due_day")[4]))
    due = date(nxt.year, nxt.month, min(day, calendar.monthrange(nxt.year, nxt.month)[1]))
    rule = _text("za_emp201_non_business_day_rule")
    if rule != "PRECEDING_BUSINESS_DAY":
        return None, f"non-business-day rule '{rule}' is not supported"
    holidays = {h.date for h in db.query(PayrollHoliday)
                .filter(PayrollHoliday.organization_id == organization_id, PayrollHoliday.country == ZA,
                        PayrollHoliday.date >= date(due.year, 1, 1), PayrollHoliday.date <= date(due.year, 12, 31))}
    if not holidays:
        return None, (f"no South African public-holiday calendar is recorded for {due.year}; the EMP201 due date "
                      "is not assumed")
    while due.weekday() >= 5 or due in holidays:
        due -= timedelta(days=1)
    return due, None


# ── EMP201 ──────────────────────────────────────────────────────────────────
def _eti_available(db: Session, organization_id: int, start: date) -> Decimal:
    from app.modules.payroll.models import PayrollZaEtiLedgerEntry

    rows = (db.query(PayrollZaEtiLedgerEntry)
            .filter(PayrollZaEtiLedgerEntry.organization_id == organization_id,
                    PayrollZaEtiLedgerEntry.claim_month == start,
                    PayrollZaEtiLedgerEntry.status.in_(("CALCULATED", "CLAIMED"))).all())
    return sum((_dec(r.eti_amount) for r in rows), ZERO)


def build_za_emp201(db: Session, organization_id: int, period_key: str) -> dict:
    start, end = _month_bounds(period_key)
    items = _committed_items(db, organization_id, start, end)
    totals = _payroll_totals(items)
    eti_available = _eti_available(db, organization_id, start)
    policy = _text("za_eti_offset_policy")
    warnings = []
    if policy == "OFFSET_UP_TO_PAYE":
        eti_utilised = min(eti_available, totals["paye"])
    else:
        eti_utilised = ZERO
        if eti_available > ZERO:
            warnings.append("ETI is available but not utilised: the ETI offset policy is PENDING_G1.")
    due, blocked = za_due_date(db, organization_id, period_key)
    amount_due = totals["paye"] - eti_utilised + totals["sdl"] + totals["uif"]
    return {
        "periodKey": period_key, "organizationId": organization_id,
        "paye": _money(totals["paye"]), "sdl": _money(totals["sdl"]), "uif": _money(totals["uif"]),
        "etiAvailable": _money(eti_available), "etiUtilised": _money(eti_utilised), "etiOffsetPolicy": policy,
        "amountDue": _money(amount_due),
        "dueDate": due.isoformat() if due else None, "dueDateBlockedReason": blocked,
        "payslipIds": [i.id for i, _r in items], "runIds": sorted({r.id for _i, r in items}),
        "employeeCount": len({i.employee_id for i, _r in items}),
        "warnings": warnings,
    }


# ── certificates (IRP5 / IT3(a)) ────────────────────────────────────────────
def _tax_year_months(period: str):
    """'2027-INTERIM' -> Mar–Aug 2026; '2027-ANNUAL' -> Mar 2026 – Feb 2027."""
    try:
        year_label, kind = period.split("-")
        tax_year = int(year_label)
    except ValueError:
        raise BadRequestException(f"Reconciliation period '{period}' must be YYYY-INTERIM or YYYY-ANNUAL.")
    if kind == "INTERIM":
        first, last = (int(m) for m in _text("za_emp501_interim_months").split("-"))
        months = [(tax_year - 1, m) for m in range(first, last + 1)]
    elif kind == "ANNUAL":
        months = [(tax_year - 1, m) for m in range(3, 13)] + [(tax_year, m) for m in (1, 2)]
    else:
        raise BadRequestException(f"Reconciliation period '{period}' must be YYYY-INTERIM or YYYY-ANNUAL.")
    return [f"{y:04d}-{m:02d}" for y, m in months]


def _period_bounds(period: str):
    months = _tax_year_months(period)
    return _month_bounds(months[0])[0], _month_bounds(months[-1])[1], months


def _component_amounts(item) -> dict:
    snap = item.za_calculation_snapshot or {}
    lines = ((snap.get("trace") or {}).get("bases") or {}).get("PAYE", {}).get("lines") or []
    out = {}
    for line in lines:
        out[line.get("component")] = out.get(line.get("component"), ZERO) + _dec(line.get("amount"))
    return out


def build_za_certificates(db: Session, organization_id: int, period: str) -> list:
    from app.modules.payroll.models import PayrollEmployee

    start, end, _months = _period_bounds(period)
    per_employee = {}
    for item, _run in _committed_items(db, organization_id, start, end):
        cert = per_employee.setdefault(item.employee_id, {line: ZERO for line in content.ZA_CERTIFICATE_LINES})
        for component, amount in _component_amounts(item).items():
            if component in cert:
                cert[component] += amount
        snap = item.za_calculation_snapshot or {}
        cert["PAYE"] += _dec(item.tds)
        cert["UIF_EMPLOYEE"] += _dec(item.esi)
        cert["RETIREMENT_EMPLOYEE"] += _dec(item.employee_pension)
        cert["MEDICAL_CREDIT"] += _dec(snap.get("za_medical_credit_applied"))
    out = []
    for employee_id, lines in sorted(per_employee.items()):
        employee = db.query(PayrollEmployee).filter(PayrollEmployee.id == employee_id).first()
        fields = (getattr(employee, "compliance_fields", None) or {}) if employee else {}
        tax_number = fields.get("tax_number") or fields.get("za_tax_number")
        errors = [] if tax_number else ["no SARS income-tax number recorded (required for reconciliation, §9)"]
        out.append({
            "employeeId": employee_id, "employeeName": getattr(employee, "name", None),
            "taxNumberMasked": _mask(tax_number),
            "certificateType": "IRP5" if lines["PAYE"] > ZERO else "IT3A",
            "lines": {k: _money(v) for k, v in lines.items()},
            "validation": "FAILED" if errors else "PASSED", "errors": errors,
        })
    return out


# ── SARS BRS mapping layer (ZA-015, ZA-018) ─────────────────────────────────
def map_to_brs(canonical, brs_version: Optional[str] = None) -> dict:
    """Translate canonical certificates into SARS BRS fields / source codes.
    BLOCKED while the version's catalogue is empty or a line has no code —
    a source code is never guessed."""
    version = brs_version or _text("za_brs_version")
    catalogue = content.ZA_BRS_CATALOG.get(version) or {}
    codes = catalogue.get("source_codes") or {}
    if not codes:
        return {"status": "BLOCKED", "brsVersion": version,
                "reason": f"SARS PAYE BRS v{version} source-code catalogue is not archived (evidence S4)"}
    rows, missing = [], set()
    for cert in canonical if isinstance(canonical, list) else [canonical]:
        mapped = {}
        for line, amount in (cert.get("lines") or {}).items():
            if _dec(amount) == ZERO:
                continue
            code = codes.get(line)
            if code is None:
                missing.add(line)
            else:
                mapped[code] = amount
        rows.append({"employeeId": cert.get("employeeId"), "sourceCodes": mapped})
    if missing:
        return {"status": "BLOCKED", "brsVersion": version,
                "reason": f"no BRS source code for: {', '.join(sorted(missing))}"}
    return {"status": "MAPPED", "brsVersion": version, "rows": rows}


# ── SARS payments ───────────────────────────────────────────────────────────
def record_za_sars_payment(db: Session, organization_id: int, *, period_key: str, paid_on, amount,
                           payment_reference: str, allocation: dict, evidence_ref: Optional[str] = None,
                           actor_id: Optional[int] = None):
    from app.modules.payroll.models import PayrollZaSarsPayment

    _month_bounds(period_key)
    amount = _dec(amount)
    if amount <= ZERO:
        raise BadRequestException("A SARS payment amount must be positive.")
    reference = (payment_reference or "").strip()
    if not reference:
        raise BadRequestException("The SARS payment reference (PRN) is required.")
    allocation = {k: _money(v) for k, v in (allocation or {}).items() if k in ("paye", "sdl", "uif")}
    if sum((_dec(v) for v in allocation.values()), ZERO) != amount.quantize(TWO):
        raise BadRequestException("The PAYE / SDL / UIF allocation must add up to the payment amount.")
    if (db.query(PayrollZaSarsPayment.id)
            .filter(PayrollZaSarsPayment.organization_id == organization_id,
                    PayrollZaSarsPayment.payment_reference == reference).first()):
        raise BadRequestException(f"Payment reference {reference} is already recorded.")
    paid = paid_on if isinstance(paid_on, date) else date.fromisoformat(str(paid_on))
    row = PayrollZaSarsPayment(organization_id=organization_id, period_key=period_key, paid_on=paid,
                               amount=amount, payment_reference=reference, allocation=allocation,
                               evidence_ref=evidence_ref, status="RECORDED", created_by_id=actor_id)
    db.add(row)
    db.flush()
    return row


def reverse_za_sars_payment(db: Session, organization_id: int, payment_id: int, actor_id: Optional[int] = None):
    from app.modules.payroll.models import PayrollZaSarsPayment

    row = (db.query(PayrollZaSarsPayment)
           .filter(PayrollZaSarsPayment.id == payment_id,
                   PayrollZaSarsPayment.organization_id == organization_id).first())
    if row is None:
        raise NotFoundException("SARS payment not found.")
    if row.status == "REVERSED":
        raise BadRequestException("This payment is already reversed.")
    row.status = "REVERSED"
    db.flush()
    return row


def list_za_sars_payments(db: Session, organization_id: int) -> list:
    from app.modules.payroll.models import PayrollZaSarsPayment

    return (db.query(PayrollZaSarsPayment).filter(PayrollZaSarsPayment.organization_id == organization_id)
            .order_by(PayrollZaSarsPayment.period_key, PayrollZaSarsPayment.id).all())


def _paid(db: Session, organization_id: int, month_key: str) -> Decimal:
    from app.modules.payroll.models import PayrollZaSarsPayment

    rows = (db.query(PayrollZaSarsPayment)
            .filter(PayrollZaSarsPayment.organization_id == organization_id,
                    PayrollZaSarsPayment.period_key == month_key,
                    PayrollZaSarsPayment.status != "REVERSED").all())
    return sum((_dec(r.amount) for r in rows), ZERO)


# ── artefact lifecycle (ZA-019, ZA-020) ─────────────────────────────────────
def _latest(db: Session, organization_id: int, artifact_type: str, period_key: str, statuses=None):
    from app.modules.payroll.models import PayrollZaSarsArtifact

    q = (db.query(PayrollZaSarsArtifact)
         .filter(PayrollZaSarsArtifact.organization_id == organization_id,
                 PayrollZaSarsArtifact.artifact_type == artifact_type,
                 PayrollZaSarsArtifact.period_key == period_key))
    if statuses:
        q = q.filter(PayrollZaSarsArtifact.status.in_(statuses))
    else:
        q = q.filter(PayrollZaSarsArtifact.status != "SUPERSEDED")
    return q.order_by(PayrollZaSarsArtifact.version.desc()).first()


def _validate(artifact_type: str, payload) -> list:
    errors = []
    if artifact_type == "EMP201":
        if not payload.get("dueDate"):
            errors.append({"code": "ZA_DUE_DATE_BLOCKED", "detail": payload.get("dueDateBlockedReason")})
    elif artifact_type in ("IRP5", "IT3A"):
        for cert in payload.get("certificates") or []:
            for err in cert.get("errors") or []:
                errors.append({"code": "ZA_CERTIFICATE_INVALID", "employeeId": cert.get("employeeId"), "detail": err})
        brs = payload.get("brs") or {}
        if brs.get("status") != "MAPPED":
            errors.append({"code": "ZA_BRS_BLOCKED", "detail": brs.get("reason")})
    elif artifact_type in ("EMP501_INTERIM", "EMP501_ANNUAL"):
        if payload.get("status") != "READY":
            errors.append({"code": "ZA_RECONCILIATION_IMBALANCED", "detail": "the reconciliation is not READY"})
    return errors


def record_za_artifact(db: Session, organization_id: int, artifact_type: str, period_key: str, payload: dict,
                       actor_id: Optional[int] = None):
    """A new artefact version (or the existing one when the payload is
    unchanged). The previous live version becomes SUPERSEDED; nothing is ever
    edited in place (ZA-020)."""
    from app.modules.payroll.models import PayrollZaSarsArtifact

    if artifact_type not in ARTIFACT_TYPES:
        raise BadRequestException(f"Unknown SARS artefact type {artifact_type}.")
    digest = _sha256(payload)
    previous = _latest(db, organization_id, artifact_type, period_key)
    if previous is not None and previous.payload_sha256 == digest:
        return previous
    if previous is not None and previous.status in ("SUBMITTED",):
        raise BadRequestException("The previous version is SUBMITTED to SARS — record its receipt or rejection "
                                  "before preparing a correction.")
    errors = _validate(artifact_type, payload)
    from sqlalchemy import func

    top = (db.query(func.max(PayrollZaSarsArtifact.version))
           .filter(PayrollZaSarsArtifact.organization_id == organization_id,
                   PayrollZaSarsArtifact.artifact_type == artifact_type,
                   PayrollZaSarsArtifact.period_key == period_key).scalar()) or 0
    row = PayrollZaSarsArtifact(
        organization_id=organization_id, artifact_type=artifact_type, period_key=period_key, version=top + 1,
        brs_version=_text("za_brs_version"), payload=json.loads(_canonical_json(payload)), payload_sha256=digest,
        validation_status="FAILED" if errors else "PASSED", validation_errors=errors or None,
        status="DRAFT" if errors else "VALIDATED",
        source_run_ids=payload.get("runIds"), supersedes_id=previous.id if previous is not None else None,
        created_by_id=actor_id)
    db.add(row)
    if previous is not None:
        previous.status = "SUPERSEDED"
    db.flush()
    return row


def _artifact(db: Session, organization_id: int, artifact_id: int):
    from app.modules.payroll.models import PayrollZaSarsArtifact

    row = (db.query(PayrollZaSarsArtifact)
           .filter(PayrollZaSarsArtifact.id == artifact_id,
                   PayrollZaSarsArtifact.organization_id == organization_id).first())
    if row is None:
        raise NotFoundException("SARS artefact not found.")
    return row


def approve_za_artifact(db: Session, organization_id: int, artifact_id: int, approver_id: int):
    row = _artifact(db, organization_id, artifact_id)
    if row.status != "VALIDATED":
        raise BadRequestException(f"Only a VALIDATED artefact can be approved (this one is {row.status}).")
    if row.created_by_id is not None and row.created_by_id == approver_id:
        raise BadRequestException("Four-eyes: the person who prepared the artefact cannot approve it.")
    row.status = "APPROVED"
    row.approved_by_id = approver_id
    row.approved_at = datetime.now(timezone.utc)
    db.flush()
    return row


def record_za_submission(db: Session, organization_id: int, artifact_id: int, channel: str):
    row = _artifact(db, organization_id, artifact_id)
    if row.status != "APPROVED":
        raise BadRequestException("Only an APPROVED artefact can be recorded as submitted.")
    channel = (channel or "").strip().upper()
    if channel not in CHANNELS:
        raise BadRequestException(f"Submission channel must be one of {', '.join(CHANNELS)}.")
    row.status = "SUBMITTED"
    row.submission_channel = channel
    row.submitted_at = datetime.now(timezone.utc)
    db.flush()
    return row


def record_za_receipt(db: Session, organization_id: int, artifact_id: int, *, accepted: bool,
                      receipt_ref: Optional[str] = None, raw_response=None):
    """SARS's answer. ACCEPTED needs a receipt reference; a rejection keeps the
    raw response and maps it to a stable internal code — the payload is never
    edited, the correction is a NEW version (ZA-020)."""
    row = _artifact(db, organization_id, artifact_id)
    if row.status != "SUBMITTED":
        raise BadRequestException("Only a SUBMITTED artefact can receive a SARS response.")
    if accepted:
        if not (receipt_ref or "").strip():
            raise BadRequestException("An accepted submission needs its SARS receipt reference.")
        row.status = "ACCEPTED"
        row.receipt_ref = receipt_ref.strip()
    else:
        row.status = "REJECTED"
        row.validation_errors = (row.validation_errors or []) + [
            {"code": "ZA_SARS_REJECTED", "detail": "SARS rejected the submission — see externalResponse"}]
    row.external_response = raw_response
    db.flush()
    return row


def list_za_artifacts(db: Session, organization_id: int, artifact_type: Optional[str] = None) -> list:
    from app.modules.payroll.models import PayrollZaSarsArtifact

    q = db.query(PayrollZaSarsArtifact).filter(PayrollZaSarsArtifact.organization_id == organization_id)
    if artifact_type:
        q = q.filter(PayrollZaSarsArtifact.artifact_type == artifact_type)
    return q.order_by(PayrollZaSarsArtifact.artifact_type, PayrollZaSarsArtifact.period_key,
                      PayrollZaSarsArtifact.version).all()


# ── variances and reconciliation (ZA-019) ───────────────────────────────────
def propose_za_variance(db: Session, organization_id: int, *, reconciliation_period: str, month_key: str,
                        measure: str, amount, reason: str, evidence_ref: Optional[str] = None,
                        actor_id: Optional[int] = None):
    from app.modules.payroll.models import PayrollZaReconciliationVariance

    _tax_year_months(reconciliation_period)
    if measure not in MEASURES:
        raise BadRequestException(f"Variance measure must be one of {', '.join(MEASURES)}.")
    if not (reason or "").strip():
        raise BadRequestException("A variance needs an explanation.")
    row = PayrollZaReconciliationVariance(
        organization_id=organization_id, reconciliation_period=reconciliation_period, month_key=month_key,
        measure=measure, amount=_dec(amount).quantize(TWO), reason=reason.strip(), evidence_ref=evidence_ref,
        status="PROPOSED", created_by_id=actor_id)
    db.add(row)
    db.flush()
    return row


def approve_za_variance(db: Session, organization_id: int, variance_id: int, approver_id: int):
    from app.modules.payroll.models import PayrollZaReconciliationVariance

    row = (db.query(PayrollZaReconciliationVariance)
           .filter(PayrollZaReconciliationVariance.id == variance_id,
                   PayrollZaReconciliationVariance.organization_id == organization_id).first())
    if row is None:
        raise NotFoundException("Variance not found.")
    if row.status != "PROPOSED":
        raise BadRequestException(f"Only a PROPOSED variance can be approved (this one is {row.status}).")
    if row.created_by_id is not None and row.created_by_id == approver_id:
        raise BadRequestException("Four-eyes: the person who proposed the variance cannot approve it.")
    row.status = "APPROVED"
    row.approved_by_id = approver_id
    row.approved_at = datetime.now(timezone.utc)
    db.flush()
    return row


def list_za_variances(db: Session, organization_id: int, period: str) -> list:
    from app.modules.payroll.models import PayrollZaReconciliationVariance

    _tax_year_months(period)
    return (db.query(PayrollZaReconciliationVariance)
            .filter(PayrollZaReconciliationVariance.organization_id == organization_id,
                    PayrollZaReconciliationVariance.reconciliation_period == period)
            .order_by(PayrollZaReconciliationVariance.id).all())


def _approved_variances(db: Session, organization_id: int, period: str) -> list:
    from app.modules.payroll.models import PayrollZaReconciliationVariance

    return (db.query(PayrollZaReconciliationVariance)
            .filter(PayrollZaReconciliationVariance.organization_id == organization_id,
                    PayrollZaReconciliationVariance.reconciliation_period == period,
                    PayrollZaReconciliationVariance.status == "APPROVED").all())


def build_za_reconciliation(db: Session, organization_id: int, period: str) -> dict:
    start, end, months = _period_bounds(period)
    tolerance = _dec(_scalar("za_reconciliation_tolerance")[4])
    variances = _approved_variances(db, organization_id, period)

    def explained(month_key, measure, diff):
        return any(v.month_key == month_key and v.measure == measure and _dec(v.amount) == diff for v in variances)

    rows, issues = [], []
    emp201_paye_total = ZERO
    for month_key in months:
        m_start, m_end = _month_bounds(month_key)
        payroll = _payroll_totals(_committed_items(db, organization_id, m_start, m_end))
        payroll_total = payroll["paye"] + payroll["sdl"] + payroll["uif"]
        declared = _latest(db, organization_id, "EMP201", month_key, DECLARED_STATUSES)
        declared_payload = (declared.payload or {}) if declared is not None else {}
        declared_total = (_dec(declared_payload.get("paye")) + _dec(declared_payload.get("sdl"))
                          + _dec(declared_payload.get("uif")))
        declared_due = _dec(declared_payload.get("amountDue"))
        emp201_paye_total += _dec(declared_payload.get("paye"))
        paid = _paid(db, organization_id, month_key)
        checks = {"PAYROLL_VS_EMP201": (payroll_total - declared_total).quantize(TWO),
                  "EMP201_VS_PAYMENT": (declared_due - paid).quantize(TWO)}
        row = {"month": month_key, "payroll": _money(payroll_total), "emp201": _money(declared_total),
               "emp201AmountDue": _money(declared_due), "paid": _money(paid),
               "emp201ArtifactId": getattr(declared, "id", None), "differences": {}}
        for measure, diff in checks.items():
            row["differences"][measure] = str(diff)
            if abs(diff) > tolerance and not explained(month_key, measure, diff):
                issues.append({"month": month_key, "measure": measure, "difference": str(diff)})
        rows.append(row)

    certificates = build_za_certificates(db, organization_id, period)
    cert_paye = sum((_dec(c["lines"]["PAYE"]) for c in certificates), ZERO)
    cert_diff = (cert_paye - emp201_paye_total).quantize(TWO)
    if abs(cert_diff) > tolerance and not explained("ALL", "CERTIFICATES_VS_EMP201", cert_diff):
        issues.append({"month": "ALL", "measure": "CERTIFICATES_VS_EMP201", "difference": str(cert_diff)})
    invalid = [c["employeeId"] for c in certificates if c["validation"] != "PASSED"]
    if invalid:
        issues.append({"month": "ALL", "measure": "CERTIFICATE_VALIDATION", "employees": invalid})
    return {
        "period": period, "organizationId": organization_id, "months": rows,
        "certificatesPaye": _money(cert_paye), "emp201PayeTotal": _money(emp201_paye_total),
        "certificatesVsEmp201": str(cert_diff), "certificateCount": len(certificates),
        "tolerance": _money(tolerance), "issues": issues,
        "status": "READY" if not issues else "IMBALANCED",
    }


# ── COIDA return-of-earnings evidence (spec §4) ─────────────────────────────
def build_za_coida_evidence(db: Session, organization_id: int, assessment_year: str) -> dict:
    """Earnings per employee and month for the March–February assessment year,
    classified by the COIDA earning rows. REVIEW components are listed as
    unclassified (the evidence is produced, flagged). No assessment rate."""
    from app.modules.payroll.models import PayrollZaEmployerRegistration

    start, end, months = _period_bounds(f"{assessment_year}-ANNUAL")
    treatment = {c: t for (o, t, c, _l, _s) in content.ZA_EARNING_CLASSES if o == "COIDA"}
    employees, unclassified, workers = {}, {}, {m: set() for m in months}
    for item, run in _committed_items(db, organization_id, start, end):
        month_key = _month_key(run.pay_date)
        workers[month_key].add(item.employee_id)
        for component, amount in _component_amounts(item).items():
            t = treatment.get(component)
            if t == "INCLUDED":
                employees.setdefault(item.employee_id, {}).setdefault(month_key, ZERO)
                employees[item.employee_id][month_key] += amount
            elif t != "EXCLUDED":
                unclassified.setdefault(component, ZERO)
                unclassified[component] += amount
    registration = (db.query(PayrollZaEmployerRegistration)
                    .filter(PayrollZaEmployerRegistration.organization_id == organization_id,
                            PayrollZaEmployerRegistration.status == "ACTIVE").first())
    return {
        "assessmentYear": assessment_year, "organizationId": organization_id,
        "coidaReference": getattr(registration, "coida_reference", None),
        "months": months, "workerCounts": {m: len(ids) for m, ids in workers.items()},
        "earnings": {str(emp): {m: _money(v) for m, v in by_month.items()} for emp, by_month in employees.items()},
        "totalEarnings": _money(sum((v for by_month in employees.values() for v in by_month.values()), ZERO)),
        "unclassifiedEarnings": {k: _money(v) for k, v in unclassified.items()},
        "note": "Return-of-earnings evidence only — no COIDA assessment rate is applied (spec §1).",
    }
