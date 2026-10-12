"""
engine/jurisdictions/singapore/compliance.py
--------------------------------------------
Singapore Compliance Centre (ZP-SG-ENG-001 §14, SG-041/SG-042) — pure
helpers: the item shape every Compliance Centre row uses (STATUS,
EFFECTIVE DATE, SOURCE/EVIDENCE, BLOCKER, OWNER, ACTION) and the three
distinct clocks (SG-041) plus the worker-specific IR21 clock. service.py
gathers the facts; nothing here reads a database or holds a rate.

Clock rules (RulePack rows, sourced):
  - Salary: within salary_payment_deadline_days (overtime:
    overtime_payment_deadline_days) after the salary period — MOM "Paying salary".
  - CPF / SDL / SHG: due the last day of the wage month; enforcement if
    unpaid by cpf_enforcement_day_following_month of the next month "or the
    next working day if the 14th falls on a Saturday, Sunday or public
    holiday" — CPF Board "Enforcement and penalties".
  - Foreign worker levy: by fwl_payment_due_day of the following month (or
    the next working day) — MOM "Paying the levy".
  - AIS: the StatutoryFilingCalendar IR8A due date (1 Mar) — IRAS.
"""

import calendar
from datetime import date, timedelta

PASS, FAIL, REVIEW, BLOCKED, INFO = "PASS", "FAIL", "REVIEW", "BLOCKED", "INFO"


def item(area, key, label, status, evidence, effective_date=None, source=None, blocker=None, owner="Employer payroll",
         action=None):
    return {"area": area, "key": key, "label": label, "status": status, "effectiveDate": effective_date,
            "evidence": evidence, "source": source, "blocker": blocker if status != PASS else None,
            "owner": owner, "action": action if status != PASS else None}


def next_working_day(d: date, holidays: set) -> date:
    while d.weekday() >= 5 or d in holidays:
        d += timedelta(days=1)
    return d


def _month_after(d: date, day: int) -> date:
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(y, m, min(day, calendar.monthrange(y, m)[1]))


def clocks(wage_month_start: date, period_end, pay_date, rates: dict, holidays: set, ais_due, ir21_cases) -> list:
    def amount(key):
        row = rates.get(key)
        return None if row is None or row.flat_amount is None else int(row.flat_amount)

    out = []
    salary_days, ot_days = amount("salary_payment_deadline_days"), amount("overtime_payment_deadline_days")
    if period_end is not None and salary_days is not None:
        out.append({"clock": "SALARY_PAYMENT", "due": (period_end + timedelta(days=salary_days)).isoformat(),
                    "overtimeDue": (period_end + timedelta(days=ot_days)).isoformat() if ot_days is not None else None,
                    "payDate": pay_date.isoformat() if pay_date else None,
                    "rule": f"within {salary_days} days after the salary period (overtime {ot_days})",
                    "source": "MOM Paying salary"})
    enforce = amount("cpf_enforcement_day_following_month")
    if enforce is not None:
        month_end = date(wage_month_start.year, wage_month_start.month,
                         calendar.monthrange(wage_month_start.year, wage_month_start.month)[1])
        out.append({"clock": "CPF_SDL_SHG_CONTRIBUTION", "wageMonth": wage_month_start.strftime("%Y-%m"),
                    "due": month_end.isoformat(),
                    "enforcementAfter": next_working_day(_month_after(wage_month_start, enforce), holidays).isoformat(),
                    "rule": "due on the last day of the month; enforcement if unpaid by the 14th of the following month "
                            "(next working day if a weekend / public holiday)", "source": "CPF Board enforcement page"})
    levy = amount("fwl_payment_due_day")
    if levy is not None:
        out.append({"clock": "FOREIGN_WORKER_LEVY", "wageMonth": wage_month_start.strftime("%Y-%m"),
                    "due": next_working_day(_month_after(wage_month_start, levy), holidays).isoformat(),
                    "rule": "by the 17th of the following month (next working day if a weekend / public holiday)",
                    "source": "MOM Paying the levy"})
    if ais_due is not None:
        out.append({"clock": "IRAS_AIS", "due": ais_due.isoformat(), "rule": "employment income by 1 March of the year of assessment",
                    "source": "IRAS AIS"})
    for case in ir21_cases:
        out.append({"clock": "IR21", "employeeId": case["employeeId"], "caseId": case["id"], "status": case["status"],
                    "due": case["fileBy"], "rule": "notify IRAS at least one month before cessation / departure",
                    "source": "IRAS IR21"})
    return out
