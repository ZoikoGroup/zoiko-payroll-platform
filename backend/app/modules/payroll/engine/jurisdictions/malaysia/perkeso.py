"""PERKESO Act 4 social security (ZP-MY-ENG-001 §7; MY-013 / MY-014).

Separate obligation from EIS. Local / PR employees use MY_SOCSO_SCHEDULE
(category EI_AND_INVALIDITY or EI_ONLY); foreign workers use their own
MY_FW_SOCSO_SCHEDULE (FOREIGN_WORKER) — never the local path. The signed
wage ceiling caps ONLY this base (MY-013). The LINDUNG 24 JAM phase is the
schedule row in force for the contribution month (MY-014: rows carry their
own effective dates; the pack is read as of the pay date).
"""
from __future__ import annotations

from app.modules.payroll.engine.jurisdictions.malaysia.pack import MyPack, dec, money


def capped(pack: MyPack, wage) -> tuple:
    ceiling = pack.amount("my_socso_wage_ceiling")
    wage = dec(wage)
    return min(wage, ceiling), wage > ceiling, ceiling


def compute(pack: MyPack, wage, decision: dict) -> dict:
    base, was_capped, ceiling = capped(pack, wage)
    row = pack.schedule(decision["schedule"], decision["category"], base)
    return {"employee": row["employee"], "employer": row["employer"],
            "trace": {"wage": money(wage), "contributionWage": money(base), "ceiling": money(ceiling),
                      "capped": was_capped, **{k: v for k, v in row.items() if k not in ("employee", "employer")},
                      "employee": money(row["employee"]), "employer": money(row["employer"])}}
