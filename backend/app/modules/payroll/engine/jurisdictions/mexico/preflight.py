"""
engine/jurisdictions/mexico/preflight.py
----------------------------------------
Collects EVERY reason a Mexican payslip cannot be calculated before any
amount is computed (MX-001, MX-036) — missing profile facts, an identifier
MISMATCH, no IMSS registration / risk premium, labour policy, minimum-wage
zone, an unsupported work state or non-Active ISN pack, an unsupported
period, absences, special pays, unclassified earnings, no rounding rule —
and raises one MXBlock("MX_PREFLIGHT_BLOCKED") listing all of them.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from . import classification, isn, period, rounding, special_pay, termination
from .content import Content
from .errors import MXBlock


def fact(obj, name: str):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _separation_total(special) -> Decimal:
    """The whole separation paid in this payment — the base LISR Art. 93 XIII's
    shared cap is allocated over. A malformed amount is left to
    special_pay.classify, which reports it."""
    total = Decimal("0")
    for line in special or []:
        if str(line.get("kind") or "").upper() in termination.SEPARATION_KINDS:
            try:
                total += Decimal(str(line.get("amount")))
            except (InvalidOperation, ValueError):
                continue
    return total


def run(ctx) -> dict:
    reasons: list = []
    resolved: dict = {}

    def attempt(label, fn):
        try:
            resolved[label] = fn()
        except MXBlock as exc:
            reasons.extend(exc.reasons)

    attempt("on", lambda: period.pay_date(ctx))
    rows = getattr(ctx, "mx_pack_rows", None)
    content = (Content(rows.get("rate_map"), rows.get("slabs")) if rows
               else Content(getattr(ctx, "rate_map", None), getattr(ctx, "slabs", None)))
    resolved["content"] = content
    run_type = getattr(ctx, "mx_run_type", None)
    special_run = run_type in special_pay.RUN_CONCEPTS         # Phase 9b / 9c: a run that pays special concepts only
    resolved["special_run"] = run_type if special_run else None
    if special_run:
        resolved["period"] = None                               # no ordinary pay period, contribution days or tariff
    else:
        attempt("period", lambda: period.resolve(ctx, content))
    attempt("round", lambda: rounding.rounder(content))

    profile = getattr(ctx, "mx_profile", None)
    if profile is None:
        reasons.append(("MX_PROFILE_MISSING", "the employee has no Mexico statutory profile in force"))
    else:
        if fact(profile, "mx_identifier_validation_status") == "MISMATCH":
            reasons.append(("MX_IDENTIFIER_MISMATCH", "the employee's RFC / CURP / NSS do not agree"))
        try:
            salary_ok = Decimal(str(fact(profile, "mx_daily_salary"))) > 0
        except (InvalidOperation, ValueError):
            salary_ok = False
        if not salary_ok:
            reasons.append(("MX_DAILY_SALARY_MISSING", "the employee's daily salary is not recorded"))
        if fact(profile, "mx_seniority_date") is None:
            reasons.append(("MX_SENIORITY_DATE_MISSING", "the employee's seniority date is not recorded"))
    work_state = fact(profile, "mx_work_state")
    resolved["work_state"] = work_state
    try:
        isn.check_state(work_state)
        pack = getattr(ctx, "mx_isn_state_pack", None)
        if not pack or pack.get("state") != work_state:
            reasons.append(("MX_STATE_UNSUPPORTED", f"no ISN pack resolved for {work_state}"))
        elif pack.get("status") != "Active":
            reasons.append(("MX_ISN_PACK_NOT_ACTIVE", f"the {work_state} ISN pack is {pack.get('status')}, not Active"))
    except MXBlock as exc:
        reasons.extend(exc.reasons)

    registration = getattr(ctx, "mx_registration", None)
    if not registration or registration.get("status") != "ACTIVE":
        reasons.append(("MX_NO_REGISTRATION", "the employee has no ACTIVE IMSS employer registration"))
    if not special_run and not getattr(ctx, "mx_risk_premium", None):
        reasons.append(("MX_NO_RISK_PREMIUM", "no approved work-risk premium for the registration and period"))
    if not getattr(ctx, "mx_labor_policy", None):
        reasons.append(("MX_LABOR_POLICY_MISSING", "no employer labour policy is in force"))
    zone = getattr(ctx, "mx_min_wage_zone", None)
    if zone not in ("GENERAL", "ZLFN"):
        reasons.append(("MX_MIN_WAGE_ZONE_UNRESOLVED", "the employee's minimum-wage zone is not resolved"))

    earnings = getattr(ctx, "mx_earnings", None) or []
    special = [l for l in earnings if str(l.get("kind") or "").upper() in special_pay.CONCEPTS]
    ordinary = [l for l in earnings if str(l.get("kind") or "").upper() not in special_pay.CONCEPTS]
    on = resolved.get("on")
    if special_run:
        allowed = special_pay.RUN_CONCEPTS[run_type]
        # A finiquito may owe nothing (aguinaldo already paid, no vacation left,
        # a reason with no separation component); an aguinaldo run always pays.
        if (not special and run_type != "FINIQUITO") or ordinary                 or any(str(l.get("kind")).upper() not in allowed for l in special):
            reasons.append(("MX_SPECIAL_RUN_LINES_INVALID",
                            f"a {run_type} run carries only {' / '.join(allowed).lower()} lines"))
    elif not any(str(l.get("kind") or "").upper() == classification.ORDINARY_SALARY for l in ordinary):
        reasons.append(("MX_SALARY_LINE_MISSING", "the period has no ordinary-salary earning line"))
    hour_kinds = (classification.OVERTIME, classification.SUNDAY_PREMIUM)
    if any(str(l.get("kind") or "").upper() in hour_kinds for l in ordinary):
        reasons.append(("MX_OVERTIME_NOT_FROM_HOURS",
                        "overtime / Sunday premium is derived only from approved hours (MX-049), never a supplied line"))
    elif on is not None:
        facts = {"pay_date": on, "content": content, "daily_salary": fact(profile, "mx_daily_salary") if profile else None,
                 "month_to_date": getattr(ctx, "mx_month_to_date", None), "run_type": run_type or "ORDINARY",
                 "period": resolved.get("period"),
                 # W1-3: what the transcribed special-pay rules read (LISR Art. 93 XIII / XIV) —
                 # the worker's zone (RLISR Art. 167), the calendar year's exempt amounts already
                 # used, and for a separation its date, the seniority date and its whole total.
                 "zone": zone, "seniority_date": fact(profile, "mx_seniority_date") if profile else None,
                 "year_to_date_exempt": getattr(ctx, "mx_year_to_date_exempt", None),
                 "separation_date": getattr(ctx, "mx_separation_date", None),
                 "separation_total": _separation_total(special)}
        resolved["facts"] = facts
        attempt("ordinary_lines", lambda: classification.classify(ordinary, getattr(ctx, "mx_classifications", None),
                                                                  on, work_state) if ordinary else [])
        attempt("special_lines", lambda: special_pay.classify(special, facts, work_state, special_run=special_run)
                if special else [])
        if "ordinary_lines" in resolved and "special_lines" in resolved:
            resolved["lines"] = resolved["ordinary_lines"] + resolved["special_lines"]

    if reasons:
        seen, unique = set(), []
        for r in reasons:
            if r not in seen:
                seen.add(r)
                unique.append(r)
        raise MXBlock("MX_PREFLIGHT_BLOCKED", "; ".join(f"{k}: {d}" for k, d in unique), reasons=unique)
    return resolved
