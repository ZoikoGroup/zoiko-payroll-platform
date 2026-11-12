"""Labour-territory resolver (ZP-MY-ENG-001 MY-001 / MY-003 / MY-024).

Malaysian labour law is territorial: Peninsular Malaysia + Labuan, Sabah and
Sarawak each have their own framework, independent of the national
obligations (EPF, PERKESO, EIS, HRD, PCB). The territory comes ONLY from the
approved work assignment in force — never from the company address, the
employee's home state or a default.

  * no assignment                    -> MY_TERRITORY_UNRESOLVED (review)
  * assignment not ACTIVE, or its holiday state lies in another territory
                                     -> MY_TERRITORY_CONFLICT (review)
  * two territories inside one pay period -> the signed
    my_transfer_split_rule decides; until it is signed the period is
    refused (MY_TERRITORY_TRANSFER) — never a guessed split.
"""
from __future__ import annotations

from datetime import date

from app.modules.payroll.engine.countries import malaysia_content as content
from app.modules.payroll.engine.jurisdictions.malaysia import errors as E
from app.modules.payroll.engine.jurisdictions.malaysia.pack import MyPack, as_date, field, upper

# Holiday states inside Sabah / Sarawak; every other state and federal
# territory (Labuan included) is Peninsular + Labuan. Geography, not content.
_TERRITORY_OF_STATE = {"SBH": "SABAH", "SWK": "SARAWAK"}


def _territory(pack: MyPack, assignment) -> tuple:
    territory = upper(field(assignment, "labour_territory"))
    state = upper(field(assignment, "holiday_state"))
    if upper(field(assignment, "status")) not in ("", "ACTIVE"):
        pack.block(E.TERRITORY_CONFLICT, "the work assignment in force is not ACTIVE")
    if territory not in content.TERRITORIES or state not in content.HOLIDAY_STATES:
        pack.block(E.TERRITORY_CONFLICT, "the work assignment names no valid territory / holiday state")
    if _TERRITORY_OF_STATE.get(state, "PENINSULAR_LABUAN") != territory:
        pack.block(E.TERRITORY_CONFLICT, f"holiday state {state} does not lie in {territory} (MY-003)")
    return territory, state


def resolve(pack: MyPack, assignment, assignments, start: date, end: date) -> dict:
    """{"territory", "holidayState", "assignmentId", "rule"} for the period."""
    if assignment is None:
        pack.block(E.TERRITORY_UNRESOLVED, "no approved work assignment covers the period end (MY-003)")
    territory, state = _territory(pack, assignment)
    def overlaps(a) -> bool:
        a_from, a_to = as_date(field(a, "effective_from")), as_date(field(a, "effective_to"))
        return (a_from is None or a_from <= end) and (a_to is None or a_to >= start)

    overlapping = [a for a in (assignments or []) if overlaps(a)]
    territories = {_territory(pack, a)[0] for a in overlapping} | {territory}
    rule = "SINGLE_TERRITORY"
    if len(territories) > 1:
        try:
            rule = pack.text("my_transfer_split_rule", content.TRANSFER_SPLIT_RULES)
        except E.MYCalculationBlockedError as exc:
            pack.block(E.TERRITORY_TRANSFER, f"the period spans {', '.join(sorted(territories))}: {exc.reason}")
    return {"territory": territory, "holidayState": state, "assignmentId": field(assignment, "id"), "rule": rule,
            "territoriesInPeriod": sorted(territories)}
