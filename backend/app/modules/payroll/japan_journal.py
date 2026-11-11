"""
japan_journal.py — accounting journal for a committed Japan run
(ZP-JP-ENG-001 §8; Phase 8).

From the frozen payslip results only:
  Dr salary expense (gross), employer social insurance, employer employment
     insurance
  Cr withholding payable, social insurance payable (employee + employer),
     employment insurance payable (employee + employer), resident tax payable
     per municipality, other deductions payable, net pay payable
Debits always equal credits (asserted). The account codes are the employer's
own choice: without a complete account map the journal is BLOCKED, never
posted to a guessed account.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException

ZERO = Decimal("0")
ACCOUNT_KEYS = ("salary_expense", "employer_si_expense", "employer_ei_expense", "withholding_payable",
                "si_payable", "ei_payable", "resident_tax_payable", "other_deductions_payable", "net_pay_payable")


def _dec(value) -> Decimal:
    return Decimal(str(value)) if value not in (None, "") else ZERO


def run_measures(items) -> dict:
    gross = net = wht = ee_si = er_si = ee_ei = er_ei = ZERO
    resident = {}
    for item in items:
        snap = item.jp_calculation_snapshot or {}
        bonus = snap.get("jp_bonus") or {}
        gross += _dec(item.gross_pay)
        net += _dec(item.net_pay)
        wht += _dec(item.tds)
        ee_si += _dec(snap.get("jp_si_employee_total")) + _dec(bonus.get("jp_bonus_si_employee_total"))
        er_si += _dec(snap.get("jp_si_employer_total")) + _dec(bonus.get("jp_bonus_si_employer_total"))
        ee_ei += _dec(snap.get("jp_ei_employee")) + _dec(bonus.get("jp_bonus_ei_employee"))
        er_ei += _dec(snap.get("jp_ei_employer")) + _dec(bonus.get("jp_bonus_ei_employer"))
        amount = _dec(snap.get("jp_resident_tax"))
        if amount:
            code = str((snap.get("jp_resident_tax_notice") or {}).get("municipality") or "UNKNOWN")
            resident[code] = resident.get(code, ZERO) + amount
    other = gross - net - wht - ee_si - ee_ei - sum(resident.values(), ZERO)
    return {"gross": gross, "net": net, "wht": wht, "eeSi": ee_si, "erSi": er_si, "eeEi": ee_ei,
            "erEi": er_ei, "resident": resident, "other": other}


def build_jp_journal(db: Session, organization_id: int, run_id: int,
                     account_map: Optional[dict] = None) -> dict:
    from app.modules.payroll.models import PayrollRun, PayslipItem

    run = (db.query(PayrollRun)
           .filter(PayrollRun.id == run_id, PayrollRun.organization_id == organization_id).first())
    if run is None:
        raise BadRequestException("Payroll run not found.")
    if str(getattr(run.status, "value", run.status)) not in ("Paid", "Closed"):
        return {"runId": run_id, "status": "BLOCKED", "reason": "the journal is built for a committed run"}
    items = (db.query(PayslipItem)
             .filter(PayslipItem.payroll_run_id == run.id, PayslipItem.country_code == "JP").all())
    missing = [k for k in ACCOUNT_KEYS if not (account_map or {}).get(k)]
    if missing:
        return {"runId": run_id, "status": "BLOCKED",
                "reason": f"no account code for: {', '.join(missing)}"}
    t = run_measures(items)
    if t["other"] < ZERO:
        return {"runId": run_id, "status": "BLOCKED",
                "reason": f"the payslips do not reconcile (other deductions {t['other']})"}
    a = account_map
    lines = [("DR", a["salary_expense"], t["gross"], "Salaries"),
             ("DR", a["employer_si_expense"], t["erSi"], "Employer social insurance"),
             ("DR", a["employer_ei_expense"], t["erEi"], "Employer employment insurance"),
             ("CR", a["withholding_payable"], t["wht"], "Withholding income tax payable"),
             ("CR", a["si_payable"], t["eeSi"] + t["erSi"], "Social insurance payable"),
             ("CR", a["ei_payable"], t["eeEi"] + t["erEi"], "Employment insurance payable")]
    lines += [("CR", a["resident_tax_payable"], amount, f"Resident tax payable — {code}")
              for code, amount in sorted(t["resident"].items())]
    lines += [("CR", a["other_deductions_payable"], t["other"], "Other deductions payable"),
              ("CR", a["net_pay_payable"], t["net"], "Net pay payable")]
    lines = [line for line in lines if line[2] != ZERO]
    debit = sum((l[2] for l in lines if l[0] == "DR"), ZERO)
    credit = sum((l[2] for l in lines if l[0] == "CR"), ZERO)
    if debit != credit:
        return {"runId": run_id, "status": "BLOCKED", "reason": f"debits {debit} != credits {credit}"}
    return {"runId": run_id, "status": "READY", "debit": str(debit), "credit": str(credit),
            "lines": [{"side": s, "account": acc, "amount": str(amt), "memo": memo} for s, acc, amt, memo in lines]}
