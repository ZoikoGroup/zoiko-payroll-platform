"""
south_africa_journal.py — South Africa payroll journal (ZP-ZA-ENG-001 §10;
Phase 9). "ZA" is South Africa.

Double-entry lines for one run, from the payslips' frozen ZA snapshots and
money columns, under the employer's own chart of accounts
(payroll_za_employer_registrations.za_journal_accounts). A missing account is
BLOCKED — never a default account — and so is a journal whose debits and
credits do not balance. ETI is an employer incentive (ZA-010): it is posted
only between the ETI receivable and the ETI incentive accounts, never to an
employee line or to net pay.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundException

ZA = "ZA"
ZERO = Decimal("0")
TWO = Decimal("0.01")
# (account key, side, measure) — the base lines every ZA journal posts.
JOURNAL_LINES = (
    ("gross_expense", "DEBIT", "gross"),
    ("employer_uif_expense", "DEBIT", "uifEmployer"),
    ("employer_sdl_expense", "DEBIT", "sdl"),
    ("paye_liability", "CREDIT", "paye"),
    ("uif_liability", "CREDIT", "uifTotal"),
    ("sdl_liability", "CREDIT", "sdl"),
    ("retirement_liability", "CREDIT", "retirement"),
    ("other_deductions_liability", "CREDIT", "otherDeductions"),
    ("net_pay_clearing", "CREDIT", "net"),
)
ETI_LINES = (("eti_receivable", "DEBIT", "eti"), ("eti_incentive", "CREDIT", "eti"))
ACCOUNT_KEYS = tuple(k for k, _s, _m in JOURNAL_LINES + ETI_LINES)


def _dec(value) -> Decimal:
    return ZERO if value in (None, "") else Decimal(str(value))


def _blocked(run_id: int, reason: str, **extra) -> dict:
    return {"runId": run_id, "status": "BLOCKED", "reason": reason, "lines": [], **extra}


def za_run_measures(items) -> dict:
    """Totals over a run's ZA payslips (money columns; ETI from the snapshot)."""
    m = {k: ZERO for k in ("gross", "paye", "uifEmployee", "uifEmployer", "sdl", "retirement",
                           "otherDeductions", "net", "eti")}
    for item in items:
        snap = item.za_calculation_snapshot or {}
        m["gross"] += _dec(item.gross_pay)
        m["paye"] += _dec(item.tds)
        m["uifEmployee"] += _dec(item.esi)
        m["uifEmployer"] += _dec(item.employer_esi)
        m["sdl"] += _dec(item.employer_payroll_tax)
        m["retirement"] += _dec(item.employee_pension)
        m["otherDeductions"] += _dec(snap.get("za_other_deductions"))
        m["net"] += _dec(item.net_pay)
        if ((snap.get("za_eti") or {}).get("status") or "").upper() == "ELIGIBLE":
            m["eti"] += _dec(snap.get("za_eti_amount"))
    m["uifTotal"] = m["uifEmployee"] + m["uifEmployer"]
    return m


def _account_map(db: Session, organization_id: int, on: Optional[date]) -> Optional[dict]:
    from app.modules.payroll import south_africa_service as za

    registration = za.get_za_employer_registration(db, organization_id, on)
    return getattr(registration, "za_journal_accounts", None) if registration is not None else None


def build_za_journal(db: Session, organization_id: int, run_id: int, account_map: Optional[dict] = None) -> dict:
    from app.modules.payroll.models import PayrollRun, PayslipItem

    run = (db.query(PayrollRun)
           .filter(PayrollRun.id == run_id, PayrollRun.organization_id == organization_id).first())
    if run is None:
        raise NotFoundException("PayrollRun", run_id)
    items = (db.query(PayslipItem)
             .filter(PayslipItem.payroll_run_id == run.id, PayslipItem.country_code == ZA)
             .order_by(PayslipItem.id).all())
    if not items:
        return _blocked(run.id, "the run has no South African payslips")
    accounts = account_map if account_map is not None else _account_map(db, organization_id, run.pay_date)
    if not accounts:
        return _blocked(run.id, "no ZA journal account map is configured for the employer registration (spec §10)")

    measures = za_run_measures(items)
    wanted = JOURNAL_LINES + (ETI_LINES if measures["eti"] > ZERO else ())
    missing = sorted({key for key, _side, measure in wanted
                      if measures[measure] != ZERO and not str(accounts.get(key) or "").strip()})
    if missing:
        return _blocked(run.id, f"account(s) not configured: {', '.join(missing)}", missingAccounts=missing)

    lines = []
    for key, side, measure in wanted:
        amount = measures[measure].quantize(TWO)
        if amount == ZERO:
            continue
        lines.append({"accountKey": key, "account": str(accounts[key]).strip(), "side": side, "amount": str(amount)})
    debit = sum((Decimal(l["amount"]) for l in lines if l["side"] == "DEBIT"), ZERO)
    credit = sum((Decimal(l["amount"]) for l in lines if l["side"] == "CREDIT"), ZERO)
    totals = {"debitTotal": str(debit), "creditTotal": str(credit),
              "measures": {k: str(v.quantize(TWO)) for k, v in measures.items()}}
    if debit != credit:
        return _blocked(run.id, f"ZA_JOURNAL_UNBALANCED: debits R{debit} != credits R{credit} — a payslip carries a "
                                "deduction outside the ZA result", **totals)
    return {"runId": run.id, "status": "READY", "payDate": run.pay_date.isoformat() if run.pay_date else None,
            "payslipCount": len(items), "lines": lines, **totals}
