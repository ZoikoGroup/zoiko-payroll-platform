"""EPF contribution (ZP-MY-ENG-001 §6; MY-011 / MY-012).

Schedule-driven: the official Third Schedule (MY_EPF_SCHEDULE rows, loaded
from the EPF document and signed) is the calculation authority. The row used
is persisted with the result. The ONLY direct percentage branch is the one
the specification names — non-Malaysian members after 1 Aug 1998, Part F
direct calculation — and only while the signed my_epf_direct_calc_rule says
so, with the signed rounding. Wages above the schedule's upper wage for the
other classes block (the direct-calculation rule for them is not signed).
Voluntary excess / i-Topup is not calculated yet: an approved election blocks.
"""
from __future__ import annotations

from datetime import date

from app.modules.payroll.engine.countries import malaysia_content as content
from app.modules.payroll.engine.jurisdictions.malaysia import errors as E
from app.modules.payroll.engine.jurisdictions.malaysia.pack import HUNDRED, MyPack, dec, field, in_window, money, upper


def _voluntary_excess(declarations, on: date) -> bool:
    return any(upper(field(d, "declaration_type")) == "EPF_VOLUNTARY_EXCESS"
               and upper(field(d, "status")) == "APPROVED"
               and in_window(field(d, "effective_from"), field(d, "effective_to"), on)
               for d in declarations or [])


def compute(pack: MyPack, wage, decision: dict, declarations, on: date) -> dict:
    if _voluntary_excess(declarations, on):
        pack.block(E.EPF_VOLUNTARY_EXCESS_UNSUPPORTED,
                   "an approved EPF voluntary-excess election is not calculated in this release")
    wage = dec(wage)
    cls = decision["memberClass"]
    if cls == "NONMY_POST_1998":
        pack.text("my_epf_direct_calc_rule", content.EPF_DIRECT_CALC_RULES)
        round_ = pack.rounder("my_rounding_epf_direct")
        ee = round_(wage * pack.pct("my_epf_rate_non_malaysian", "employee") / HUNDRED)
        er = round_(wage * pack.pct("my_epf_rate_non_malaysian", "employer") / HUNDRED)
        return {"employee": ee, "employer": er, "method": "PART_F_DIRECT", "memberClass": cls,
                "trace": {"method": "PART_F_DIRECT", "wage": money(wage), "rateKey": "my_epf_rate_non_malaysian",
                          "employee": money(ee), "employer": money(er)}}
    upper_wage = pack.amount("my_epf_schedule_upper_wage")
    if wage > upper_wage:
        pack.block(E.EPF_ABOVE_SCHEDULE, "wages above the Third Schedule table need the signed direct-calculation "
                                         "rule for this member class")
    row = pack.schedule(content.MY_EPF_SCHEDULE_RULE, cls, wage)
    return {"employee": row["employee"], "employer": row["employer"], "method": "THIRD_SCHEDULE", "memberClass": cls,
            "trace": {"method": "THIRD_SCHEDULE", **{k: v for k, v in row.items() if k not in ("employee", "employer")},
                      "employee": money(row["employee"]), "employer": money(row["employer"])}}
