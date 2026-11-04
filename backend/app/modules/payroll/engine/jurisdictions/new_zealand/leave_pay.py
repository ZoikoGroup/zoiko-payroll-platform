"""Holidays Act leave pay (spec "Holidays Act", NZ-017, NZ-021; Phase 6). Pure.

Annual holidays are paid at the greater of ordinary weekly pay (OWP) and
average weekly earnings (AWE); sick, bereavement, family-violence, alternative
and public-holiday days at relevant daily pay (RDP) or, where RDP cannot be
determined or pay varies, average daily pay (ADP). Both candidates and the
winning reason are always kept; a candidate that cannot be computed blocks —
never assumed (NZ-017). Lookback windows, divisors and methods are signed
content (empty until gate G2); the pay-as-you-go percentage, cash-up limit and
public-holiday multiplier are the spec's own rows.

Ledger rows (from payroll_nz_gross_earnings_ledger) are dicts:
  {"payDate", "periodStart", "periodEnd", "component", "amount", "included",
   "treatment", "daysWorked"}
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from . import errors as E
from .holidays_act import add_months
from .pack import HUNDRED, ZERO, NzPack, as_date, dec, field, money, upper

OWP_METHOD = "AGREEMENT_THEN_FALLBACK"
RDP_METHOD = "AGREEMENT_DAILY"
ADP_RULE = "RDP_UNDETERMINABLE_OR_VARIES"
UNVESTED_METHOD = "PCT_OF_GROSS_SINCE_ANNIVERSARY"
IRREGULAR = ("BONUS", "LUMP_SUM")          # never ordinary weekly pay
DAILY_PURPOSES = ("SICK", "BEREAVEMENT", "FAMILY_VIOLENCE", "PUBLIC_HOLIDAY_NOT_WORKED", "ALTERNATIVE_HOLIDAY")
NOT_PAYABLE_ON_TERMINATION = ("SICK", "BEREAVEMENT_CLOSE", "BEREAVEMENT_OTHER", "FAMILY_VIOLENCE")


@dataclass
class Candidate:
    name: str
    rate: Optional[Decimal]
    steps: list = dc_field(default_factory=list)
    missing: Optional[str] = None


@dataclass
class LeavePay:
    purpose: str
    method_pair: str
    a: Optional[Candidate]
    b: Optional[Candidate]
    chosen: str
    reason: str
    units: Decimal
    unit: str
    rate: Decimal
    amount: Decimal
    steps: list = dc_field(default_factory=list)
    entitlement_id: Optional[int] = None

    def as_dict(self) -> dict:
        def cand(c):
            return None if c is None else {"name": c.name, "rate": None if c.rate is None else str(c.rate),
                                           "missing": c.missing, "steps": c.steps}
        return {"purpose": self.purpose, "methodPair": self.method_pair, "a": cand(self.a), "b": cand(self.b),
                "chosen": self.chosen, "reason": self.reason, "units": str(self.units), "unit": self.unit,
                "rate": str(self.rate), "amount": money(self.amount), "entitlementId": self.entitlement_id,
                "steps": self.steps}


# ── ledger windows ──────────────────────────────────────────────────────────
def _window(rows, end: date, *, months: Optional[int] = None, weeks: Optional[Decimal] = None) -> list:
    start = add_months(end, -months) if months is not None else end - timedelta(weeks=int(weeks))
    return [r for r in rows or () if start < as_date(r.get("periodEnd")) <= end]


def _require_reviewed(rows, pack: NzPack) -> None:
    for row in rows:
        if upper(row.get("treatment")) == "REVIEW":
            pack.block(E.HOL_GROSS_UNREVIEWED,
                       f"{row.get('component')} paid on {row.get('payDate')} has no signed gross-earnings "
                       "treatment (NZ-017)")


def _included(rows) -> Decimal:
    return sum((dec(r.get("amount")) for r in rows if r.get("included")), ZERO)


def _whole(pack: NzPack, key: str) -> int:
    value = pack.amount(key)
    if value <= ZERO or value != value.to_integral_value():
        pack.block(E.keyed(E.ROW_MISSING, key), "must be a whole number above zero")
    return int(value)


# ── candidates ──────────────────────────────────────────────────────────────
def owp(agreement_weekly, ledger, last_period_end: date, pack: NzPack) -> Candidate:
    pack.text("nz_hol_owp_method", allowed=(OWP_METHOD,))
    if agreement_weekly is not None:
        rate = dec(agreement_weekly)
        return Candidate("OWP", rate, [{"step": "owp", "value": money(rate), "note": "employment agreement"}])
    weeks = _whole(pack, "nz_hol_owp_fallback_weeks")
    rows = [r for r in _window(ledger, last_period_end, weeks=weeks) if upper(r.get("component")) not in IRREGULAR]
    _require_reviewed(rows, pack)
    if not rows:
        return Candidate("OWP", None, missing="no gross earnings in the ordinary-weekly-pay fallback window")
    rate = _included(rows) / weeks
    return Candidate("OWP", rate, [{"step": "owpFallback", "value": money(rate),
                                    "note": f"{money(_included(rows))} / {weeks} weeks"}])


def awe(ledger, last_period_end: date, pack: NzPack) -> Candidate:
    months = _whole(pack, "nz_hol_awe_lookback_months")
    divisor = pack.amount("nz_hol_awe_divisor_weeks")
    if divisor <= ZERO:
        pack.block(E.keyed(E.ROW_MISSING, "nz_hol_awe_divisor_weeks"), "must be above zero")
    rows = _window(ledger, last_period_end, months=months)
    _require_reviewed(rows, pack)
    if not rows:
        return Candidate("AWE", None, missing="no gross earnings in the average-weekly-earnings window")
    total = _included(rows)
    rate = total / divisor
    return Candidate("AWE", rate, [{"step": "awe", "value": money(rate), "note": f"{money(total)} / {divisor}",
                                    "ledgerRows": len(rows)}])


def rdp(agreement_daily) -> Candidate:
    if agreement_daily is None:
        return Candidate("RDP", None, missing="relevant daily pay cannot be determined")
    rate = dec(agreement_daily)
    return Candidate("RDP", rate, [{"step": "rdp", "value": money(rate), "note": "employment agreement"}])


def adp(ledger, last_period_end: date, pack: NzPack) -> Candidate:
    weeks = _whole(pack, "nz_hol_adp_lookback_weeks")
    rows = _window(ledger, last_period_end, weeks=weeks)
    _require_reviewed(rows, pack)
    if not rows:
        return Candidate("ADP", None, missing="no gross earnings in the average-daily-pay window")
    by_payslip = {}
    for row in rows:
        if row.get("daysWorked") is None:
            return Candidate("ADP", None, missing="days worked are unknown for part of the window")
        by_payslip[(row.get("payDate"), row.get("periodStart"), row.get("periodEnd"))] = dec(row.get("daysWorked"))
    days = sum(by_payslip.values(), ZERO)
    if days <= ZERO:
        return Candidate("ADP", None, missing="no days worked in the average-daily-pay window")
    total = _included(rows)
    rate = total / days
    return Candidate("ADP", rate, [{"step": "adp", "value": money(rate), "note": f"{money(total)} / {days} days"}])


def _evidence(pack: NzPack, candidate: Candidate) -> None:
    if candidate.rate is None:
        pack.block(E.keyed(E.LEAVE_EVIDENCE_MISSING, candidate.name), candidate.missing or "not computable")


# ── payments ────────────────────────────────────────────────────────────────
def annual_leave_pay(weeks, agreement_weekly, ledger, last_period_end: date, pack: NzPack,
                     purpose: str = "ANNUAL_LEAVE") -> LeavePay:
    """Greater of OWP and AWE; both must be computable (NZ-017). Equal rates
    choose OWP."""
    weeks = dec(weeks)
    a, b = owp(agreement_weekly, ledger, last_period_end, pack), awe(ledger, last_period_end, pack)
    _evidence(pack, a)
    _evidence(pack, b)
    chosen = a if a.rate >= b.rate else b
    amount = pack.rounder("nz_hol_pay_rounding")(weeks * chosen.rate)
    return LeavePay(purpose, "OWP_AWE", a, b, chosen.name, "greater of OWP and AWE (Holidays Act annual holiday pay)",
                    weeks, "WEEKS", chosen.rate, amount)


def daily_leave_pay(purpose: str, days, agreement_daily, daily_pay_varies: bool, ledger, last_period_end: date,
                    pack: NzPack) -> LeavePay:
    """RDP, unless RDP cannot be determined or daily pay varies: then ADP.
    Both candidates are kept; the chosen one must be computable."""
    pack.text("nz_hol_rdp_method", allowed=(RDP_METHOD,))
    pack.text("nz_hol_adp_use_rule", allowed=(ADP_RULE,))
    a, b = rdp(agreement_daily), adp(ledger, last_period_end, pack)
    if a.rate is not None and not daily_pay_varies:
        chosen, reason = a, "relevant daily pay is determinable"
    else:
        chosen = b
        reason = "average daily pay: daily pay varies" if daily_pay_varies and a.rate is not None \
            else "average daily pay: relevant daily pay cannot be determined"
    _evidence(pack, chosen)
    days = dec(days)
    amount = pack.rounder("nz_hol_pay_rounding")(days * chosen.rate)
    return LeavePay(purpose, "RDP_ADP", a, b, chosen.name, reason, days, "DAYS", chosen.rate, amount)


def public_holiday_worked_pay(hours, hourly_rate, pack: NzPack) -> LeavePay:
    if hourly_rate is None:
        pack.block(E.keyed(E.LEAVE_EVIDENCE_MISSING, "HOURLY_RATE"), "the hourly rate for the holiday is unknown")
    multiplier = pack.amount("nz_hol_ph_worked_multiplier")
    rate = dec(hourly_rate) * multiplier
    hours = dec(hours)
    amount = pack.rounder("nz_hol_pay_rounding")(hours * rate)
    return LeavePay("PUBLIC_HOLIDAY_WORKED", "RDP_ADP", rdp(hourly_rate), None, "RDP",
                    f"hours worked on the public holiday at {multiplier} times the relevant rate",
                    hours, "HOURS", rate, amount)


def payg_holiday_pay(gross_this_period, payg_eligible: bool, pack: NzPack) -> LeavePay:
    """Pay-as-you-go holiday pay: only on a recorded eligible basis with a
    written agreement — never a default for "casual"."""
    if not payg_eligible:
        pack.block(E.PAYG_NOT_ELIGIBLE, "the employment is not recorded as pay-as-you-go eligible")
    pct = pack.pct("nz_hol_payg_pct")
    gross = dec(gross_this_period)
    amount = pack.rounder("nz_hol_pay_rounding")(gross * pct / HUNDRED)
    return LeavePay("PAYG", "PAYG_PCT", None, None, "PCT", f"{pct}% of gross earnings (pay-as-you-go)",
                    gross, "AMOUNT", pct, amount)


def cash_up_pay(weeks, balance, agreement_weekly, ledger, last_period_end: date, pack: NzPack) -> LeavePay:
    weeks = dec(weeks)
    if weeks <= ZERO or weeks > pack.amount("nz_hol_cashup_max_weeks"):
        pack.block(E.CASHUP_LIMIT, "a cash-up is limited to the signed maximum weeks per entitlement year")
    if weeks > dec(balance):
        pack.block(E.CASHUP_LIMIT, "the cash-up exceeds the remaining annual holiday balance")
    return annual_leave_pay(weeks, agreement_weekly, ledger, last_period_end, pack, purpose="CASH_UP")


def final_pay(entitlements, *, payg_eligible: bool, since: date, termination_date: date, ledger,
              agreement_weekly, agreement_daily, daily_pay_varies: bool, advance_paid, last_period_end: date,
              pack: NzPack) -> list:
    """Every entitlement is resolved, none zeroed (NZ-021): vested annual
    weeks at the annual rate, alternative days at the daily rate, holiday pay
    on the unvested period at the signed percentage (not for pay-as-you-go),
    and sick / bereavement / family-violence listed as not payable."""
    out = []
    for ent in entitlements:
        kind, left = upper(field(ent, "leave_type")), dec(field(ent, "balance"))
        ident = field(ent, "id")
        if left <= ZERO:
            continue
        if kind == "ANNUAL":
            line = annual_leave_pay(left, agreement_weekly, ledger, last_period_end, pack, purpose="FINAL_VESTED")
        elif kind == "ALTERNATIVE":
            line = daily_leave_pay("ALTERNATIVE_HOLIDAY", left, agreement_daily, daily_pay_varies, ledger,
                                   last_period_end, pack)
        elif kind in NOT_PAYABLE_ON_TERMINATION:
            line = LeavePay(kind, "NONE", None, None, "NONE", "not payable on termination", left,
                            upper(field(ent, "unit")) or "DAYS", ZERO, ZERO)
        else:
            continue
        line.entitlement_id = ident
        out.append(line)
    if not payg_eligible:
        pack.text("nz_hol_final_pay_unvested_method", allowed=(UNVESTED_METHOD,))
        rows = [r for r in ledger or () if since <= as_date(r.get("periodEnd")) <= termination_date]
        _require_reviewed(rows, pack)
        gross = max(_included(rows) - dec(advance_paid), ZERO)
        pct = pack.pct("nz_hol_payg_pct")
        amount = pack.rounder("nz_hol_pay_rounding")(gross * pct / HUNDRED)
        out.append(LeavePay("FINAL_UNVESTED", "PCT_GROSS", None, None, "PCT",
                            f"{pct}% of gross earnings since the last anniversary", gross, "AMOUNT", pct, amount,
                            [{"step": "unvested", "since": since.isoformat(), "ledgerRows": len(rows)}]))
    return out
