"""EIS Act 800 (ZP-MY-ENG-001 §7). Independent of PERKESO Act 4: its own
eligibility (applicability) and its own official schedule MY_EIS_SCHEDULE
(class COVERED), on the same signed wage ceiling. Foreign workers never reach
this module (applicability excludes them)."""
from __future__ import annotations

from app.modules.payroll.engine.countries import malaysia_content as content
from app.modules.payroll.engine.jurisdictions.malaysia import perkeso
from app.modules.payroll.engine.jurisdictions.malaysia.pack import MyPack, money


def compute(pack: MyPack, wage) -> dict:
    base, was_capped, ceiling = perkeso.capped(pack, wage)
    row = pack.schedule(content.MY_EIS_SCHEDULE_RULE, "COVERED", base)
    return {"employee": row["employee"], "employer": row["employer"],
            "trace": {"wage": money(wage), "contributionWage": money(base), "ceiling": money(ceiling),
                      "capped": was_capped, **{k: v for k, v in row.items() if k not in ("employee", "employer")},
                      "employee": money(row["employee"]), "employer": money(row["employer"])}}
