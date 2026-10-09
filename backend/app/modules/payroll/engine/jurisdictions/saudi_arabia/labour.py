"""
engine/jurisdictions/saudi_arabia/labour.py
-------------------------------------------
Saudi Arabia labour-pay controls — ZP-SA-ENG-001 §11 (hours, overtime and
deductions). Pure: every statutory number is a ContributionRate row (resolved
for the pay month and passed in as `rates`), never a hardcoded figure.

  * Hours (spec §11, S9): normally no more than 8 hours/day or 48/week;
    Muslim workers in Ramadan 6/day or 36/week. A compliance REPORT here —
    the run preflight decides whether a breach blocks approval.
  * Overtime (spec §11): the additional wage is the hourly wage plus
    sa_overtime_basic_premium_pct (50%) of the basic hourly wage. The hourly
    divisor (sa_monthly_hours_divisor) is not stated by the specification and
    is PENDING_G1 content.
  * Deductions (spec §11, SA-029/SA-030): each authorised type is validated
    on its own and in aggregate. Employer loan recovery is capped at
    sa_loan_cap_pct (10%) of the wage; damage recovery has its own special
    monthly limit (sa_damage_cap_pct, no value until G1 supplies it); the total
    of all deductions may not exceed sa_aggregate_deduction_cap_pct (50%) of
    the due wage. A breach is returned in `errors` and the engine BLOCKS —
    an over-cap deduction is never silently reduced.
"""

from decimal import Decimal, ROUND_HALF_UP

_Z = Decimal("0")
_HUNDRED = Decimal("100")


def _amount(rates, key):
    row = rates.get(key)
    if row is None or getattr(row, "flat_amount", None) is None:
        return None
    try:
        return Decimal(str(row.flat_amount))
    except Exception:  # noqa: BLE001 — a non-numeric scalar is "not configured"
        return None


def _pct(rates, key):
    row = rates.get(key)
    for attr in ("employee_rate_pct", "employer_rate_pct"):
        value = getattr(row, attr, None) if row is not None else None
        if value is not None:
            return Decimal(str(value))
    return None


def normal_hours(rates, ramadan: bool = False) -> dict:
    """The statutory normal-hours ceiling in force. A missing row is reported,
    never assumed."""
    daily_key = "sa_ramadan_hours_daily" if ramadan else "sa_normal_hours_daily"
    weekly_key = "sa_ramadan_hours_weekly" if ramadan else "sa_normal_hours_weekly"
    daily, weekly = _amount(rates, daily_key), _amount(rates, weekly_key)
    return {"ramadan": ramadan, "daily": daily, "weekly": weekly,
            "dailyKey": daily_key, "weeklyKey": weekly_key,
            "configured": daily is not None and weekly is not None}


def hours_check(records, rates, ramadan: bool = False) -> dict:
    """Report any day or ISO calendar week whose worked hours exceed the
    normal-hours ceiling. records: [{date, hours}]. A missing ceiling row is
    NOT_EVALUATED rather than a pass."""
    from datetime import date as _date

    limits = normal_hours(rates, ramadan)
    if not limits["configured"]:
        return {"status": "NOT_EVALUATED", "reason": "normal-hours rows not configured", "limits": limits}
    daily, weekly = limits["daily"], limits["weekly"]
    breaches, weeks = [], {}
    for r in records or []:
        try:
            hours = Decimal(str(r.get("hours")))
        except Exception:  # noqa: BLE001 — an unparsable row is skipped, not guessed
            continue
        if hours > daily:
            breaches.append({"date": r.get("date"), "hours": str(hours), "limit": str(daily), "scope": "daily"})
        raw = r.get("date")
        iso = None
        if isinstance(raw, _date):
            iso = raw.isocalendar()[:2]
        elif raw:
            try:
                iso = _date.fromisoformat(str(raw)[:10]).isocalendar()[:2]
            except ValueError:
                iso = None
        if iso is not None:
            weeks.setdefault(iso, {"hours": _Z, "days": 0})
            weeks[iso]["hours"] += hours
            weeks[iso]["days"] += 1
    for (year, week), agg in sorted(weeks.items()):
        if agg["hours"] > weekly:
            breaches.append({"date": f"{year}-W{week:02d}", "hours": str(agg["hours"]),
                             "limit": str(weekly), "scope": "weekly", "days": agg["days"]})
    return {"status": "BREACH" if breaches else "OK", "breaches": breaches, "limits": limits,
            "weeks": {f"{y}-W{w:02d}": {"hours": str(a["hours"]), "days": a["days"]}
                      for (y, w), a in sorted(weeks.items())}}


def overtime_pay(monthly_wage: Decimal, monthly_basic: Decimal, hours: Decimal, rates) -> dict:
    """Spec §11: overtime per hour = hourly wage + premium% × basic hourly
    wage, where hourly = monthly amount / sa_monthly_hours_divisor. A missing
    row returns NOT_EVALUATED (never a guessed premium or divisor)."""
    premium = _pct(rates, "sa_overtime_basic_premium_pct")
    divisor = _amount(rates, "sa_monthly_hours_divisor")
    if premium is None or divisor is None or divisor <= _Z:
        return {"status": "NOT_EVALUATED",
                "reason": "sa_overtime_basic_premium_pct or sa_monthly_hours_divisor not configured"}
    hourly_wage = Decimal(str(monthly_wage)) / divisor
    basic_hourly = Decimal(str(monthly_basic)) / divisor
    per_hour = hourly_wage + basic_hourly * premium / _HUNDRED
    amount = (Decimal(str(hours)) * per_hour).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {"status": "OK", "hours": str(hours), "premiumPct": str(premium), "divisor": str(divisor),
            "hourlyWage": str(hourly_wage.quantize(Decimal("0.0001"))),
            "basicHourly": str(basic_hourly.quantize(Decimal("0.0001"))),
            "perHour": str(per_hour.quantize(Decimal("0.0001"))), "amount": amount}


# ── deduction types (SA-029), in statutory sequence ─────────────────────────
# type -> (per-type cap key or None, needs consent/evidence)
SA_DEDUCTION_TYPES = {
    "COURT_ORDER": None,
    "LOAN": "sa_loan_cap_pct",
    "ADVANCE": None,
    "OTHER_AUTHORISED": None,
    "DISCIPLINARY": None,
    "DAMAGE": "sa_damage_cap_pct",
}
_SEQUENCE = {t: i for i, t in enumerate(SA_DEDUCTION_TYPES)}


def evaluate_deductions(deductions, due_wage: Decimal, rates) -> dict:
    """deductions: [{id, type, amount, evidence_ref}] -> {"lines", "total",
    "errors", …}. An error BLOCKS the payroll:
      * an unknown / unauthorised deduction type;
      * no legal / consent evidence reference (private-right deductions need
        written consent; statutory cases need their order);
      * a per-type cap breached, or a per-type cap that is not configured;
      * the aggregate of all deductions above the aggregate cap."""
    due_wage = Decimal(str(due_wage or 0))
    aggregate_cap = _pct(rates, "sa_aggregate_deduction_cap_pct")
    lines, errors = [], []
    per_type = {}
    for d in sorted(deductions or [], key=lambda d: _SEQUENCE.get((d.get("type") or "").strip().upper(), 99)):
        dtype = (d.get("type") or "").strip().upper()
        ref = f"deduction {d.get('id')} ({dtype or 'no type'})"
        if dtype not in SA_DEDUCTION_TYPES:
            errors.append(f"{ref}: not an authorised Labour-Law deduction type")
            continue
        if not str(d.get("evidence_ref") or "").strip():
            errors.append(f"{ref}: no legal/consent evidence reference recorded")
            continue
        try:
            amount = Decimal(str(d.get("amount") or 0))
        except Exception:  # noqa: BLE001
            errors.append(f"{ref}: unparsable amount")
            continue
        if amount <= _Z:
            continue
        per_type[dtype] = per_type.get(dtype, _Z) + amount
        lines.append({"id": d.get("id"), "type": dtype, "amount": str(amount),
                      "evidenceRef": d.get("evidence_ref")})

    for dtype, cap_key in SA_DEDUCTION_TYPES.items():
        if cap_key is None or dtype not in per_type:
            continue
        cap = _pct(rates, cap_key)
        if cap is None:
            errors.append(f"{dtype}: {cap_key} is not configured, so the deduction cannot be validated")
        elif per_type[dtype] > due_wage * cap / _HUNDRED:
            errors.append(f"{dtype}: {per_type[dtype]} exceeds the {cap}% of wage {due_wage} limit")

    total = sum(per_type.values(), _Z)
    if lines and aggregate_cap is None:
        errors.append("sa_aggregate_deduction_cap_pct is not configured")
    elif aggregate_cap is not None and total > due_wage * aggregate_cap / _HUNDRED:
        errors.append(f"total deductions {total} exceed {aggregate_cap}% of the due wage {due_wage}")
    loan_cap = _pct(rates, "sa_loan_cap_pct")
    return {"lines": lines, "total": total, "errors": errors, "dueWage": str(due_wage),
            "byType": {k: str(v) for k, v in per_type.items()},
            "loanTotal": str(per_type.get("LOAN", _Z)),
            "loanCapPct": None if loan_cap is None else str(loan_cap),
            "aggregateCapPct": None if aggregate_cap is None else str(aggregate_cap)}
