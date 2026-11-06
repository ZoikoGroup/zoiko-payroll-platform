"""Poland accounting journal for a PAID run (ZP-PL-ENG-001 Phase 8, spec §10
Journal; mirrors nz_journal.py).

From the frozen payslip results only:
  Dr salary expense (gross), employer ZUS expense, employer fund expense
     (FP / FS, FGŚP, FEP), employer PPK expense
  Cr ZUS payable (employee + employer ZUS, health contribution and the funds —
     one ZUS transfer), PIT payable (advances), PPK payable (employee +
     employer), other deductions payable, net pay payable
Debits always equal credits; otherwise BLOCKED with the difference. The
account codes are the employer's own (registration pl_journal_accounts):
without a complete map the journal is BLOCKED, never posted to a guessed
account.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import poland_service as pls

ZERO = Decimal("0")
ACCOUNT_KEYS = ("salary_expense", "employer_zus_expense", "employer_funds_expense", "employer_ppk_expense",
                "zus_payable", "pit_payable", "ppk_payable", "other_deductions_payable", "net_pay_payable")


def clean_journal_accounts(accounts) -> dict:
    """The employer's own account map (not statutory content)."""
    if not isinstance(accounts, dict):
        raise BadRequestException("pl_journal_accounts must be an object of account codes.")
    unknown = sorted(set(accounts) - set(ACCOUNT_KEYS))
    if unknown:
        raise BadRequestException(f"unknown journal account key(s): {', '.join(unknown)}")
    return {k: str(v).strip()[:40] for k, v in accounts.items() if str(v or "").strip()}


def run_measures(items) -> dict:
    from app.modules.payroll.poland_filing import item_measures

    t = {k: ZERO for k in ("gross", "erZus", "funds", "erPpk", "zus", "pit", "ppk", "other", "net")}
    for item in items:
        mm = item_measures(item)
        er_zus = sum(mm["zusEmployer"].values(), ZERO)
        funds = sum(mm["funds"].values(), ZERO)
        net = Decimal(str(item.net_pay)) if item.net_pay is not None else mm["net"]
        t["gross"] += mm["gross"]
        t["erZus"] += er_zus
        t["funds"] += funds
        t["erPpk"] += mm["ppkEmployer"]
        t["zus"] += sum(mm["zusEmployee"].values(), ZERO) + mm["health"] + er_zus + funds
        t["pit"] += mm["pit"]
        t["ppk"] += mm["ppkEmployee"] + mm["ppkEmployer"]
        t["other"] += mm["net"] - net
        t["net"] += net
    return t


def _accounts(db: Session, run, items) -> tuple:
    """The account map of every legal employer in the run; they must agree."""
    from app.modules.payroll.models import PayrollEmployee

    m = pls._models()
    maps = []
    for entity in {getattr(db.get(PayrollEmployee, i.employee_id), "legal_entity_id", None) for i in items}:
        registration = pls._one_active(db, m.PayrollPlEmployerRegistration, run.organization_id, None, run.pay_date,
                                       "employer registration", legal_entity_id=entity, entity_scoped=True)
        if registration is None:
            return None, "no ACTIVE Poland employer registration covers the pay date"
        maps.append(dict(registration.pl_journal_accounts or {}))
    merged = maps[0] if maps else {}
    if any(mp != merged for mp in maps):
        return None, "the legal employers in this run use different account maps"
    missing = [k for k in ACCOUNT_KEYS if not merged.get(k)]
    if missing:
        return None, f"no account code for: {', '.join(missing)}"
    return merged, None


def build_pl_journal(db: Session, organization_id: int, run_id: int) -> dict:
    from app.modules.payroll.models import PayrollRun

    run = db.query(PayrollRun).filter(PayrollRun.id == run_id, PayrollRun.organization_id == organization_id).first()
    if run is None:
        raise NotFoundException("Payroll run")
    if str(getattr(run.status, "value", run.status)) not in ("Paid", "Closed"):
        return {"runId": run_id, "status": "BLOCKED", "reason": "the journal is built for a PAID run"}
    items = pls._run_items(db, run)
    if not items:
        return {"runId": run_id, "status": "BLOCKED", "reason": "the run has no Poland payslips"}
    if any(item.pl_calculation_snapshot is None for item in items):
        return {"runId": run_id, "status": "BLOCKED", "reason": "a Poland payslip has no frozen calculation"}
    a, problem = _accounts(db, run, items)
    if problem:
        return {"runId": run_id, "status": "BLOCKED", "reason": problem}
    t = run_measures(items)
    if t["other"] < ZERO:
        return {"runId": run_id, "status": "BLOCKED",
                "reason": f"the payslips do not reconcile (other deductions {t['other']})"}
    lines = [("DR", a["salary_expense"], t["gross"], "Salaries and wages (gross)"),
             ("DR", a["employer_zus_expense"], t["erZus"], "Employer ZUS (pension, disability, accident)"),
             ("DR", a["employer_funds_expense"], t["funds"], "Employer funds (FP/FS, FGŚP, FEP)"),
             ("DR", a["employer_ppk_expense"], t["erPpk"], "Employer PPK"),
             ("CR", a["zus_payable"], t["zus"], "ZUS payable (social insurance, health, funds)"),
             ("CR", a["pit_payable"], t["pit"], "PIT advances payable"),
             ("CR", a["ppk_payable"], t["ppk"], "PPK payable (employee + employer)"),
             ("CR", a["other_deductions_payable"], t["other"], "Other deductions payable"),
             ("CR", a["net_pay_payable"], t["net"], "Net pay payable")]
    lines = [line for line in lines if line[2] != ZERO]
    debit = sum((l[2] for l in lines if l[0] == "DR"), ZERO)
    credit = sum((l[2] for l in lines if l[0] == "CR"), ZERO)
    if debit != credit:
        return {"runId": run_id, "status": "BLOCKED", "reason": f"debits {debit} != credits {credit}"}
    return {"runId": run_id, "status": "READY", "debit": str(debit), "credit": str(credit),
            "lines": [{"side": s, "account": acc, "amount": str(amt), "memo": memo} for s, acc, amt, memo in lines]}
