"""New Zealand accounting journal for a PAID run (ZP-NZ-ENG-001 Phase 8;
mirrors japan_journal.py).

From the frozen payslip results only:
  Dr salary expense (gross), employer KiwiSaver expense (employer gross)
  Cr PAYE payable (incl. the ACC earner levy), student loan payable,
     KiwiSaver payable (employee + employer net), ESCT payable, child support
     payable, other deductions payable, net pay payable
Debits always equal credits; otherwise BLOCKED with the difference. The
account codes are the employer's own (employer profile nz_journal_accounts):
without a complete map the journal is BLOCKED, never posted to a guessed
account.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import new_zealand_service as nzs

ZERO = Decimal("0")
ACCOUNT_KEYS = ("salary_expense", "employer_kiwisaver_expense", "paye_payable", "student_loan_payable",
                "kiwisaver_payable", "esct_payable", "child_support_payable", "other_deductions_payable",
                "net_pay_payable")


def _dec(value) -> Decimal:
    return Decimal(str(value)) if value not in (None, "") else ZERO


def run_measures(items) -> dict:
    t = {k: ZERO for k in ("gross", "erKs", "paye", "sl", "ksEe", "ksErNet", "esct", "cs", "other", "net")}
    for item in items:
        s = item.nz_calculation_snapshot or {}
        o = s.get("obligations") or {}
        engine_net = _dec(s.get("netPay"))
        gross = engine_net + _dec(o.get("payeTotal")) + _dec(s.get("employeeTotal"))
        net = _dec(item.net_pay) if item.net_pay is not None else engine_net
        t["gross"] += gross
        t["erKs"] += _dec(o.get("ksEmployerGross"))
        t["paye"] += _dec(o.get("payeTotal"))
        t["sl"] += _dec(o.get("studentLoan"))
        t["ksEe"] += _dec(o.get("ksEmployee"))
        t["ksErNet"] += _dec(o.get("ksEmployerNet"))
        t["esct"] += _dec(o.get("esct"))
        t["cs"] += _dec(o.get("childSupport"))
        t["other"] += engine_net - net
        t["net"] += net
    return t


def _accounts(db: Session, run, items) -> tuple:
    """The account map of every legal employer in the run; they must agree."""
    from app.modules.payroll.models import PayrollEmployee

    m = nzs._nz_models()
    maps = []
    for entity in {getattr(db.get(PayrollEmployee, i.employee_id), "legal_entity_id", None) for i in items}:
        profile = nzs._nz_one_active(db, m.PayrollNzEmployerProfile, run.organization_id, None, run.pay_date,
                                     "employer profile", legal_entity_id=entity, entity_scoped=True)
        maps.append(dict(getattr(profile, "nz_journal_accounts", None) or {}))
    merged = maps[0] if maps else {}
    if any(mp != merged for mp in maps):
        return None, "the legal employers in this run use different account maps"
    missing = [k for k in ACCOUNT_KEYS if not merged.get(k)]
    if missing:
        return None, f"no account code for: {', '.join(missing)}"
    return merged, None


def build_nz_journal(db: Session, organization_id: int, run_id: int) -> dict:
    from app.modules.payroll.models import PayrollRun

    run = db.query(PayrollRun).filter(PayrollRun.id == run_id, PayrollRun.organization_id == organization_id).first()
    if run is None:
        raise NotFoundException("Payroll run")
    if str(getattr(run.status, "value", run.status)) not in ("Paid", "Closed"):
        return {"runId": run_id, "status": "BLOCKED", "reason": "the journal is built for a PAID run"}
    items = nzs._nz_run_items(db, run)
    if not items:
        return {"runId": run_id, "status": "BLOCKED", "reason": "the run has no New Zealand payslips"}
    a, problem = _accounts(db, run, items)
    if problem:
        return {"runId": run_id, "status": "BLOCKED", "reason": problem}
    t = run_measures(items)
    if t["other"] < ZERO:
        return {"runId": run_id, "status": "BLOCKED",
                "reason": f"the payslips do not reconcile (other deductions {t['other']})"}
    lines = [("DR", a["salary_expense"], t["gross"], "Salaries and wages"),
             ("DR", a["employer_kiwisaver_expense"], t["erKs"], "Employer KiwiSaver contributions (gross)"),
             ("CR", a["paye_payable"], t["paye"], "PAYE payable (incl. ACC earner levy)"),
             ("CR", a["student_loan_payable"], t["sl"], "Student loan payable"),
             ("CR", a["kiwisaver_payable"], t["ksEe"] + t["ksErNet"], "KiwiSaver payable"),
             ("CR", a["esct_payable"], t["esct"], "ESCT payable"),
             ("CR", a["child_support_payable"], t["cs"], "Child support payable"),
             ("CR", a["other_deductions_payable"], t["other"], "Other deductions payable"),
             ("CR", a["net_pay_payable"], t["net"], "Net pay payable")]
    lines = [line for line in lines if line[2] != ZERO]
    debit = sum((l[2] for l in lines if l[0] == "DR"), ZERO)
    credit = sum((l[2] for l in lines if l[0] == "CR"), ZERO)
    if debit != credit:
        return {"runId": run_id, "status": "BLOCKED", "reason": f"debits {debit} != credits {credit}"}
    return {"runId": run_id, "status": "READY", "debit": str(debit), "credit": str(credit),
            "lines": [{"side": s, "account": acc, "amount": str(amt), "memo": memo} for s, acc, amt, memo in lines]}


def set_journal_accounts(db: Session, organization_id: int, profile_id: int, accounts: dict, actor_id, reason=None):
    """The employer's own account map (not statutory content; audited)."""
    m = nzs._nz_models()
    reason = nzs._nz_reason(reason)
    P = m.PayrollNzEmployerProfile
    profile = db.query(P).filter(P.id == profile_id, P.organization_id == organization_id).first()
    if profile is None:
        raise NotFoundException("New Zealand employer profile")
    if not isinstance(accounts, dict):
        raise BadRequestException("accounts must be an object of account codes.")
    unknown = sorted(set(accounts) - set(ACCOUNT_KEYS))
    if unknown:
        raise BadRequestException(f"unknown account key(s): {', '.join(unknown)}")
    clean = {k: str(v).strip()[:40] for k, v in accounts.items() if str(v or "").strip()}
    old = profile.nz_journal_accounts
    profile.nz_journal_accounts = clean
    db.flush()
    nzs._nz_audit(db, actor_id, "updated", "nz_journal_accounts", profile.id, old={"accounts": old},
                  new={"accounts": clean}, reason=reason)
    return profile
