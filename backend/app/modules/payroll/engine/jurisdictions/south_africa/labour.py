"""
engine/jurisdictions/south_africa/labour.py
-------------------------------------------
South Africa labour controls (ZP-ZA-ENG-001 §5, ZA-012, ZA-013; Phase 9).
Pure functions over `rate_map` rows — no ORM, no clock, no network. Same shape
as engine/jurisdictions/saudi_arabia/labour.py.

  * validate_za_labour     National Minimum Wage floor, BCEA earnings-threshold
                           applicability and the overtime / Sunday / public-
                           holiday premium checks;
  * evaluate_za_deductions non-statutory deductions need a recognised authority
                           and evidence (ZA-013); damage / loss deductions need
                           a configured limit.

Doctrine: a value the specification does not state (the BCEA premium
multipliers, the damage-deduction limit) is a content row with NO value — a
check that needs it reports NOT_CONFIGURED (WARN) or BLOCKS. A number is never
assumed. The wage floor is a validation, not a PAYE base (spec §2).
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

OK, WARN, BLOCK = "OK", "WARN", "BLOCK"
_RANK = {OK: 0, WARN: 1, BLOCK: 2}
ZERO = Decimal("0")
HUNDRED = Decimal("100")
TWO = Decimal("0.01")
PREMIUM_KINDS = (("overtime", "za_bcea_overtime_multiplier"),
                 ("sunday", "za_bcea_sunday_multiplier"),
                 ("public_holiday", "za_bcea_public_holiday_multiplier"))
DAMAGE_TYPES = ("DAMAGE", "LOSS")


def _dec(value) -> Decimal:
    if value is None or value == "":
        return ZERO
    return Decimal(str(value))


def _value(rate_map: dict, key: str, attr: str):
    row = (rate_map or {}).get(key)
    if row is None:
        return None
    value = getattr(row, attr, None)
    return None if value is None else Decimal(str(value))


def _text(rate_map: dict, key: str):
    row = (rate_map or {}).get(key)
    value = getattr(row, "text_value", None) if row is not None else None
    return None if value in (None, "") else str(value)


def _finding(code: str, severity: str, detail: str) -> dict:
    return {"code": code, "severity": severity, "detail": detail}


def _status(findings: list) -> str:
    return max((f["severity"] for f in findings), key=lambda s: _RANK[s], default=OK)


def validate_za_labour(*, hours: dict | None, ordinary_pay, annual_remuneration, overtime_paid,
                       rate_map: dict) -> dict:
    """hours = {"ordinary", "overtime", "sunday", "public_holiday"} (Decimal-able) or None when
    no approved time record exists. Returns {"status", "findings", "hourly", "bcea"}."""
    findings = []
    hours = {k: _dec(v) for k, v in (hours or {}).items()} if hours else None
    ordinary_pay = _dec(ordinary_pay)
    annual = _dec(annual_remuneration)

    # National Minimum Wage (spec §2, §5): a validation floor, never a PAYE base.
    nmw = _value(rate_map, "za_nmw_hourly", "flat_amount")
    hourly = None
    if nmw is None:
        findings.append(_finding("ZA_NMW_NOT_CONFIGURED", BLOCK,
                                 "no National Minimum Wage row is in force for the pay date"))
    elif not hours or hours.get("ordinary", ZERO) <= ZERO:
        findings.append(_finding("ZA_NMW_NOT_VERIFIABLE", WARN,
                                 "no approved ordinary hours are recorded, so the hourly rate cannot be "
                                 "checked against the minimum wage"))
    else:
        hourly = (ordinary_pay / hours["ordinary"]).quantize(TWO, rounding=ROUND_HALF_UP)
        if hourly < nmw:
            findings.append(_finding("ZA_BELOW_NMW", BLOCK,
                                     f"ordinary hourly rate R{hourly} is below the National Minimum Wage "
                                     f"R{nmw} (spec §5)"))

    # BCEA working-time sections apply only below the earnings threshold (spec §2, §5).
    premium_hours = {kind: (hours or {}).get(kind, ZERO) for kind, _key in PREMIUM_KINDS}
    bcea = {"applicable": None, "threshold": None, "premiums": {}}
    if any(h > ZERO for h in premium_hours.values()):
        threshold = _value(rate_map, "za_bcea_earnings_threshold", "flat_amount")
        bcea["threshold"] = None if threshold is None else str(threshold)
        if threshold is None:
            findings.append(_finding("ZA_BCEA_THRESHOLD_UNKNOWN", BLOCK,
                                     "overtime / Sunday / public-holiday hours are recorded but no BCEA "
                                     "earnings-threshold row is in force for the pay date"))
        elif annual >= threshold:
            bcea["applicable"] = False
        else:
            bcea["applicable"] = True
            for kind, key in PREMIUM_KINDS:
                if premium_hours[kind] <= ZERO:
                    continue
                multiplier = _value(rate_map, key, "flat_amount")
                if multiplier is None:
                    findings.append(_finding("ZA_BCEA_PREMIUM_NOT_CONFIGURED", WARN,
                                             f"{kind.replace('_', ' ')} hours are recorded but the BCEA "
                                             f"multiplier is not configured — the premium is not checked"))
                    bcea["premiums"][kind] = "NOT_CONFIGURED"
                    continue
                if hourly is None:
                    findings.append(_finding("ZA_BCEA_PREMIUM_NOT_VERIFIABLE", WARN,
                                             f"{kind.replace('_', ' ')} premium cannot be checked without "
                                             "ordinary hours"))
                    continue
                required = (premium_hours[kind] * hourly * multiplier).quantize(TWO, rounding=ROUND_HALF_UP)
                bcea["premiums"][kind] = str(required)
                if kind == "overtime" and _dec(overtime_paid) < required:
                    findings.append(_finding("ZA_BCEA_PREMIUM_UNDERPAID", BLOCK,
                                             f"overtime paid R{_dec(overtime_paid)} is below the required "
                                             f"R{required}"))
    return {"status": _status(findings), "findings": findings,
            "hourly": None if hourly is None else str(hourly), "bcea": bcea}


def evaluate_za_deductions(orders: list | None, net_before, rate_map: dict) -> dict:
    """orders = [{"id", "order_type", "authority_type", "amount", "evidence_ref"}].
    Returns {"status", "total", "lines", "findings"}; BLOCK on any unauthorised,
    unevidenced, uncapped damage, or over-net deduction (ZA-013)."""
    findings, lines = [], []
    net_before = _dec(net_before)
    authorities = [a.strip().upper() for a in (_text(rate_map, "za_deduction_authority_types") or "").split(",")
                   if a.strip()]
    limit_pct = _value(rate_map, "za_damage_deduction_limit_pct", "employee_rate_pct")
    total = ZERO
    for order in orders or []:
        authority = str(order.get("authority_type") or "").strip().upper()
        kind = str(order.get("order_type") or "").strip().upper()
        ref = order.get("id")
        if order.get("amount") in (None, ""):
            findings.append(_finding("ZA_DEDUCTION_NO_AMOUNT", BLOCK,
                                     f"deduction {ref} has no fixed amount — a rate-only order is not supported"))
            continue
        amount = _dec(order.get("amount"))
        if amount <= ZERO:
            continue
        if not authorities:
            findings.append(_finding("ZA_DEDUCTION_AUTHORITIES_NOT_CONFIGURED", BLOCK,
                                     "no recognised deduction authorities are configured"))
        elif authority not in authorities:
            findings.append(_finding("ZA_DEDUCTION_UNAUTHORISED", BLOCK,
                                     f"deduction {ref} has authority {authority or 'none'} — one of "
                                     f"{', '.join(authorities)} is required (ZA-013)"))
        if not (order.get("evidence_ref") or "").strip():
            findings.append(_finding("ZA_DEDUCTION_NO_EVIDENCE", BLOCK,
                                     f"deduction {ref} carries no evidence of its authority (ZA-013)"))
        if kind in DAMAGE_TYPES:
            if limit_pct is None:
                findings.append(_finding("ZA_DAMAGE_LIMIT_NOT_CONFIGURED", BLOCK,
                                         f"{kind.lower()} deduction {ref}: the damage / loss limit is not "
                                         "configured, so it cannot be validated"))
            elif amount > (net_before * limit_pct / HUNDRED).quantize(TWO, rounding=ROUND_HALF_UP):
                findings.append(_finding("ZA_DAMAGE_LIMIT_EXCEEDED", BLOCK,
                                         f"{kind.lower()} deduction {ref} exceeds the configured limit"))
        total += amount
        lines.append({"id": ref, "orderType": kind, "authorityType": authority, "amount": str(amount)})
    if total > net_before:
        findings.append(_finding("ZA_DEDUCTIONS_EXCEED_NET", BLOCK,
                                 f"deductions R{total} exceed the net pay available R{net_before}"))
    return {"status": _status(findings), "total": total, "lines": lines, "findings": findings}
