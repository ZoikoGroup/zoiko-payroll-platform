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

from . import classification, isn, period, rounding
from .content import Content
from .errors import MXBlock


def fact(obj, name: str):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def run(ctx) -> dict:
    reasons: list = []
    resolved: dict = {}

    def attempt(label, fn):
        try:
            resolved[label] = fn()
        except MXBlock as exc:
            reasons.extend(exc.reasons)

    attempt("on", lambda: period.pay_date(ctx))
    content = Content(getattr(ctx, "rate_map", None), getattr(ctx, "slabs", None))
    resolved["content"] = content
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
    if not getattr(ctx, "mx_risk_premium", None):
        reasons.append(("MX_NO_RISK_PREMIUM", "no approved work-risk premium for the registration and period"))
    if not getattr(ctx, "mx_labor_policy", None):
        reasons.append(("MX_LABOR_POLICY_MISSING", "no employer labour policy is in force"))
    zone = getattr(ctx, "mx_min_wage_zone", None)
    if zone not in ("GENERAL", "ZLFN"):
        reasons.append(("MX_MIN_WAGE_ZONE_UNRESOLVED", "the employee's minimum-wage zone is not resolved"))

    earnings = getattr(ctx, "mx_earnings", None) or []
    if not any(str(l.get("kind") or "").upper() == classification.ORDINARY_SALARY for l in earnings):
        reasons.append(("MX_SALARY_LINE_MISSING", "the period has no ordinary-salary earning line"))
    hour_kinds = (classification.OVERTIME, classification.SUNDAY_PREMIUM)
    if any(str(l.get("kind") or "").upper() in hour_kinds for l in earnings):
        reasons.append(("MX_OVERTIME_NOT_FROM_HOURS",
                        "overtime / Sunday premium is derived only from approved hours (MX-049), never a supplied line"))
    else:
        on = resolved.get("on")
        if on is not None:
            attempt("lines", lambda: classification.classify(earnings, getattr(ctx, "mx_classifications", None), on,
                                                             work_state))

    if reasons:
        seen, unique = set(), []
        for r in reasons:
            if r not in seen:
                seen.add(r)
                unique.append(r)
        raise MXBlock("MX_PREFLIGHT_BLOCKED", "; ".join(f"{k}: {d}" for k, d in unique), reasons=unique)
    return resolved
