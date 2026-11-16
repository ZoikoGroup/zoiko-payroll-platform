"""Malaysia accounting journal for a PAID run (ZP-MY-ENG-001 Phase 9; mirrors
poland_journal.py).

From the frozen payslip results only:
  Dr salary expense (gross), employer EPF expense, employer SOCSO + EIS
     expense, HRD levy expense
  Cr PCB payable, EPF payable (employee + employer), PERKESO payable (SOCSO +
     EIS, employee + employer), HRD levy payable, other deductions payable,
     net pay payable
Debits always equal credits; otherwise BLOCKED with the difference. A net pay
under a tax-clearance hold (MY-020) is still net pay payable — it is owed to
the employee, never a deduction. The account codes are the employer's own
(registration my_journal_accounts): without a complete map the journal is
BLOCKED, never posted to a guessed account.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import malaysia_service as mys

ZERO = Decimal("0")
ACCOUNT_KEYS = ("salary_expense", "employer_epf_expense", "employer_socso_eis_expense", "hrd_levy_expense",
                "pcb_payable", "epf_payable", "perkeso_payable", "hrd_payable", "other_deductions_payable",
                "net_pay_payable")


def clean_journal_accounts(accounts) -> dict:
    """The employer's own account map (not statutory content)."""
    if not isinstance(accounts, dict):
        raise BadRequestException("my_journal_accounts must be an object of account codes.")
    unknown = sorted(set(accounts) - set(ACCOUNT_KEYS))
    if unknown:
        raise BadRequestException(f"unknown journal account key(s): {', '.join(unknown)}")
    return {k: str(v).strip()[:40] for k, v in accounts.items() if str(v or "").strip()}


def run_measures(items) -> dict:
    from app.modules.payroll.malaysia_filing import item_measures

    t = {k: ZERO for k in ("gross", "erEpf", "erPerkeso", "hrd", "pcb", "epf", "perkeso", "other", "net")}
    for item in items:
        mm = item_measures(item)
        net = Decimal(str(item.net_pay)) if item.net_pay is not None else mm["net"]
        t["gross"] += mm["gross"]
        t["erEpf"] += mm["epfEmployer"]
        t["erPerkeso"] += mm["socsoEmployer"] + mm["eisEmployer"]
        t["hrd"] += mm["hrd"]
        t["pcb"] += mm["pcb"]
        t["epf"] += mm["epfEmployee"] + mm["epfEmployer"]
        t["perkeso"] += mm["socsoEmployee"] + mm["socsoEmployer"] + mm["eisEmployee"] + mm["eisEmployer"]
        t["other"] += mm["net"] - net
        t["net"] += net
    return t


def _accounts(db: Session, run, items) -> tuple:
    """The account map of every legal employer in the run; they must agree."""
    from app.modules.payroll.models import PayrollEmployee

    m = mys._models()
    maps = []
    for entity in {getattr(db.get(PayrollEmployee, i.employee_id), "legal_entity_id", None) for i in items}:
        registration = mys._one_active(db, m.PayrollMyEmployerRegistration, run.organization_id, None, run.pay_date,
                                       "employer registration", legal_entity_id=entity, entity_scoped=True)
        if registration is None:
            return None, "no ACTIVE Malaysia employer registration covers the pay date"
        maps.append(dict(registration.my_journal_accounts or {}))
    merged = maps[0] if maps else {}
    if any(mp != merged for mp in maps):
        return None, "the legal employers in this run use different account maps"
    missing = [k for k in ACCOUNT_KEYS if not merged.get(k)]
    if missing:
        return None, f"no account code for: {', '.join(missing)}"
    return merged, None


def build_my_journal(db: Session, organization_id: int, run_id: int) -> dict:
    from app.modules.payroll.models import PayrollRun

    run = db.query(PayrollRun).filter(PayrollRun.id == run_id, PayrollRun.organization_id == organization_id).first()
    if run is None:
        raise NotFoundException("Payroll run")
    if str(getattr(run.status, "value", run.status)) not in ("Paid", "Closed"):
        return {"runId": run_id, "status": "BLOCKED", "reason": "the journal is built for a PAID run"}
    items = mys._run_items(db, run)
    if not items:
        return {"runId": run_id, "status": "BLOCKED", "reason": "the run has no Malaysia payslips"}
    if any(item.my_calculation_snapshot is None for item in items):
        return {"runId": run_id, "status": "BLOCKED", "reason": "a Malaysia payslip has no frozen calculation"}
    a, problem = _accounts(db, run, items)
    if problem:
        return {"runId": run_id, "status": "BLOCKED", "reason": problem}
    t = run_measures(items)
    if t["other"] < ZERO:
        return {"runId": run_id, "status": "BLOCKED",
                "reason": f"the payslips do not reconcile (other deductions {t['other']})"}
    lines = [("DR", a["salary_expense"], t["gross"], "Salaries and wages (gross)"),
             ("DR", a["employer_epf_expense"], t["erEpf"], "Employer EPF"),
             ("DR", a["employer_socso_eis_expense"], t["erPerkeso"], "Employer SOCSO + EIS"),
             ("DR", a["hrd_levy_expense"], t["hrd"], "HRD levy"),
             ("CR", a["pcb_payable"], t["pcb"], "PCB / MTD payable (HASiL)"),
             ("CR", a["epf_payable"], t["epf"], "EPF payable (employee + employer)"),
             ("CR", a["perkeso_payable"], t["perkeso"], "PERKESO payable (SOCSO + EIS)"),
             ("CR", a["hrd_payable"], t["hrd"], "HRD levy payable"),
             ("CR", a["other_deductions_payable"], t["other"], "Other deductions payable"),
             ("CR", a["net_pay_payable"], t["net"], "Net pay payable (incl. any held under tax clearance)")]
    lines = [line for line in lines if line[2] != ZERO]
    debit = sum((l[2] for l in lines if l[0] == "DR"), ZERO)
    credit = sum((l[2] for l in lines if l[0] == "CR"), ZERO)
    if debit != credit:
        return {"runId": run_id, "status": "BLOCKED", "reason": f"debits {debit} != credits {credit}"}
    return {"runId": run_id, "status": "READY", "debit": str(debit), "credit": str(credit),
            "lines": [{"side": s, "account": acc, "amount": str(amt), "memo": memo} for s, acc, amt, memo in lines]}
