"""Belgium absence episodes (ZP-BE-ENG-001 §9, BE-029 .. BE-032; Block B2). Pure.

Episode engine over the employee's ACTIVE episodes (dates, kind, worker
category at start — never a diagnosis):

* Incapacity (SICKNESS / WORK_ACCIDENT / OCCUPATIONAL_DISEASE): employer-paid
  guaranteed-salary days by day band. The rules are those in force on the
  INCAPACITY START DATE (BE-030): a BePack scoped to that date reads them.
  White-collar workers whose contract meets be_abs_wc_min_contract_months get
  be_abs_wc_guaranteed_days at be_abs_wc_guaranteed_pct; others use the
  manual-worker day bands (be_abs_manual_day_bands: [min, max) day numbers,
  rate_pct = employer share).
* Relapse (8-week rule, be_abs_relapse_window_weeks): a new incapacity that
  starts within the window after a previous one ended, and is not declared a
  different cause, CONTINUES the earlier episode's day count — no new
  guaranteed period. The lookback reads earlier episodes regardless of year
  (an episode ending 31 Dec 2025 links a relapse starting in January 2026).
  A declared different cause starts a new period and raises an exception for
  review.
* Maternity suspends the employer salary; a CBA top-up (agreement
  modules["topups"]["MATERNITY"], BE-032) is an employer overlay.
* Birth leave: be_abs_birth_leave_employer_days are employer days, the rest of
  be_abs_birth_leave_days are external.
* External benefits (mutuality / insurer / ONEM) are NEVER in net pay (BE-031):
  only their days are traced.
Employer amounts are VERIFIED against the GUARANTEED_SALARY / BIRTH_LEAVE_PAY
components when the daily rate is known; due > paid is an exception.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from app.modules.payroll.engine.jurisdictions.belgium import errors as E
from app.modules.payroll.engine.jurisdictions.belgium.pack import ZERO, BePack, as_date, dec, field, upper

_PERCENT = Decimal("100")
_DAYS_PER_WEEK = 7                                  # calendar fact
_INCAPACITY = ("SICKNESS", "WORK_ACCIDENT", "OCCUPATIONAL_DISEASE")


def _months_between(start: Optional[date], end: Optional[date]) -> Optional[int]:
    if start is None or end is None:
        return None
    return (end.year - start.year) * 12 + (end.month - start.month) + (1 if end.day >= start.day else 0)


def _overlap(start: date, end: Optional[date], period_start: date, period_end: date):
    lo, hi = max(start, period_start), min(end or period_end, period_end)
    return (lo, hi) if lo <= hi else None


def _continuation_offset(episode, episodes, window_days: int) -> tuple:
    """(days already counted, linked episode id) when this incapacity relapses
    an earlier one within the window and is not a different cause."""
    if field(episode, "different_cause") is True:
        return 0, None
    start = as_date(field(episode, "start_date"))
    best = None
    for other in episodes:
        if other is episode or upper(field(other, "kind")) not in _INCAPACITY:
            continue
        other_end = as_date(field(other, "end_date"))
        other_start = as_date(field(other, "start_date"))
        if other_end is None or other_start >= start or other_end >= start:
            continue
        if (start - other_end).days <= window_days and (best is None or other_end > as_date(field(best, "end_date"))):
            best = other
    if best is None:
        return 0, None
    duration = (as_date(field(best, "end_date")) - as_date(field(best, "start_date"))).days + 1
    earlier, _ = _continuation_offset(best, episodes, window_days)       # a chain of relapses keeps counting
    return earlier + duration, field(best, "id")


def compute_be_absence(pack_for, worker: dict, line: dict, episodes, agreement, pay: dict, daily_rate,
                       period_start: date, period_end: date) -> dict:
    """pack_for(on) -> BePack scoped to `on` (the incapacity start date)."""
    episodes = sorted([e for e in (episodes or ()) if upper(field(e, "status")) == "ACTIVE"],
                      key=lambda e: as_date(field(e, "start_date")))
    out = {"episodes": [], "employerDays": ZERO, "externalDays": ZERO, "employerDue": ZERO,
           "birthLeaveDue": ZERO, "topupDue": ZERO, "exceptions": []}
    if not episodes:
        return out
    category = worker.get("workerCategory")
    topups = {}
    modules = field(agreement, "modules") if agreement is not None else None
    if isinstance(modules, dict) and isinstance(modules.get("topups"), dict):
        topups = modules["topups"]
    rate = None if daily_rate in (None, "") else dec(daily_rate)
    for episode in episodes:
        kind = upper(field(episode, "kind"))
        start = as_date(field(episode, "start_date"))
        window = _overlap(start, as_date(field(episode, "end_date")), period_start, period_end)
        if window is None:
            continue
        pack: BePack = pack_for(start)                                    # rules by incapacity start date
        entry = {"id": field(episode, "id"), "kind": kind, "start": start.isoformat(), "bands": []}
        first_day = (window[0] - start).days + 1
        last_day = (window[1] - start).days + 1
        if kind in _INCAPACITY:
            relapse_days = int(pack.amount("be_abs_relapse_window_weeks") * _DAYS_PER_WEEK)
            offset, linked = _continuation_offset(episode, episodes, relapse_days)
            entry["relapseOf"] = linked
            if field(episode, "different_cause") is True:
                out["exceptions"].append({"code": E.ABSENCE_DIFFERENT_CAUSE,
                                          "detail": f"episode {entry['id']}: declared a different cause — a new "
                                                    "guaranteed period starts; review the evidence"})
            first_day, last_day = first_day + offset, last_day + offset
            white_collar = upper(field(episode, "worker_category_at_start")) == "EMPLOYEE"
            contract_ok = False
            if white_collar:
                months_required = pack.amount("be_abs_wc_min_contract_months")
                if line.get("contractType") == "INDEFINITE":
                    contract_ok = True
                else:
                    months = _months_between(as_date(line.get("contractStart")), as_date(line.get("contractEnd")))
                    contract_ok = months is not None and Decimal(months) >= months_required
            if white_collar and contract_ok:
                days = pack.amount("be_abs_wc_guaranteed_days")
                pct = pack.pct("be_abs_wc_guaranteed_pct", "employer")
                bands = [{"from": 1, "to": int(days), "pct": pct}]
                entry["regime"] = "WHITE_COLLAR"
            else:
                rows = pack.table("be_abs_manual_day_bands")
                bands = [{"from": int(dec(field(r, "min_amount"))),
                          "to": int(dec(field(r, "max_amount"))) - 1 if field(r, "max_amount") not in (None, "")
                          else None, "pct": dec(field(r, "rate_pct"))} for r in rows]
                entry["regime"] = "MANUAL_BANDS"
            employer_days, employer_amount = ZERO, ZERO
            for band in bands:
                lo = max(first_day, band["from"])
                hi = last_day if band["to"] is None else min(last_day, band["to"])
                if lo > hi:
                    continue
                count = Decimal(hi - lo + 1)
                entry["bands"].append({"fromDay": lo, "toDay": hi, "pct": str(band["pct"])})
                employer_days += count
                if rate is not None:
                    employer_amount += count * rate * band["pct"] / _PERCENT
            total = Decimal(last_day - first_day + 1)
            out["employerDays"] += employer_days
            out["externalDays"] += total - employer_days
            out["employerDue"] += employer_amount
            entry.update({"employerDays": str(employer_days), "externalDays": str(total - employer_days)})
        elif kind == "MATERNITY":
            total = Decimal(last_day - first_day + 1)
            out["externalDays"] += total
            entry.update({"employerDays": "0", "externalDays": str(total), "salarySuspended": True})
            overlay = topups.get("MATERNITY") if isinstance(topups, dict) else None
            if overlay not in (None, ""):
                entry["topupPct"] = str(overlay)
                if rate is not None:
                    out["topupDue"] += total * rate * dec(overlay) / _PERCENT
        elif kind == "BIRTH_LEAVE":
            employer_days = pack.amount("be_abs_birth_leave_employer_days")
            all_days = pack.amount("be_abs_birth_leave_days")
            lo, hi = Decimal(first_day), min(Decimal(last_day), all_days)
            employer = max(ZERO, min(hi, employer_days) - lo + 1) if lo <= employer_days else ZERO
            external = max(ZERO, hi - lo + 1 - employer)
            out["employerDays"] += employer
            out["externalDays"] += external
            if rate is not None:
                out["birthLeaveDue"] += employer * rate
            entry.update({"employerDays": str(employer), "externalDays": str(external)})
        else:
            entry.update({"employerDays": "0", "externalDays": "0", "note": "unpaid leave"})
        out["episodes"].append(entry)

    paid_guaranteed = pay.get("GUARANTEED_SALARY", ZERO)
    paid_birth = pay.get("BIRTH_LEAVE_PAY", ZERO)
    if out["employerDays"] > ZERO and rate is None:
        out["exceptions"].append({"code": E.ABSENCE_PAY_UNVERIFIED,
                                  "detail": "the daily rate is not known, so the employer absence pay cannot be checked"})
    if rate is not None and paid_guaranteed < out["employerDue"] + out["topupDue"]:
        out["exceptions"].append({"code": E.ABSENCE_PAY_SHORT, "detail": "guaranteed salary below the amount due"})
    if rate is not None and paid_birth < out["birthLeaveDue"]:
        out["exceptions"].append({"code": E.ABSENCE_PAY_SHORT, "detail": "birth-leave pay below the employer days due"})
    return out
