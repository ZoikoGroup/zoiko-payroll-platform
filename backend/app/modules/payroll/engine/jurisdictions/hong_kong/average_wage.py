"""Employment Ordinance 12-month average wage engine (ZP-HK-ENG-001 §9,
HK-014; Labour Department Concise Guide Appendix 1 — SourceArtifact ld_cg_app1).

One reusable engine for holiday pay, annual leave pay, sickness allowance,
maternity / paternity leave pay, and the SP/LSP 12-month average election —
never an ad hoc formula per benefit.

Rules (Appendix 1):
  * the 12-month period is the 12 CALENDAR months preceding the specified
    date's month (Tuen Ng 22 Jun 2023 → 1 Jun 2022 – 31 May 2023); if the
    employee has been employed for less than 12 months, the shorter period;
  * disregarded: periods for which the employee was not paid wages or full
    wages (leave with less than full pay, no work provided on a normal working
    day) — BOTH the days and the sums paid for them are excluded;
  * average daily wages = (total wages − excluded sums) ÷ (days − excluded days);
  * average monthly wages = (total wages − excluded sums) ÷ months, months =
    included days × 12 ÷ 365 (Appendix 1 Example 4 method);
  * overtime pay is included when of a constant character, or when its
    12-month monthly average is ≥ 20% of the average monthly wages (Concise
    Guide ch.3) — the comparison base is disclosed in the trace.

Only COMMITTED payroll rows are accepted (the service passes finalized
payslips only). Missing months, or a wage period straddling the lookback
boundary, BLOCK — the engine never estimates a missing month.
"""

from datetime import date, timedelta
from decimal import Decimal

from app.modules.payroll.engine.jurisdictions.hong_kong.common import (
    HongKongCalculationBlockedError, ZERO, add_months, canonical_hash, cents, dec, days_inclusive,
    fraction_value, rate_value, row_ref, to_date,
)


def parameters(rate_map: dict) -> dict:
    """The statutory factors of the average-wage formula. All of them come from
    pack rows — the 12-month window, the 365-day divisor, the 20% overtime
    inclusion test and the 4/5 daily-wage factor are Labour Department figures,
    not code constants."""
    values, refs = {}, {}
    for key in ("eo_average_wage_months", "eo_average_wage_days_per_year"):
        values[key], row = rate_value(rate_map, key)
        refs[key] = row_ref(row)
    pct, row_pct = rate_value(rate_map, "eo_overtime_aw_test_share_pct")
    values["overtime_share"] = pct / Decimal("100")
    refs["eo_overtime_aw_test_share_pct"] = row_ref(row_pct)
    values["four_fifths"], row_ff = fraction_value(rate_map, "eo_four_fifths_factor")
    refs["eo_four_fifths_factor"] = row_ref(row_ff)
    return {"values": values, "refs": refs}


def lookback_window(reference_date: date, employment_start: date, months: int) -> tuple:
    """(start, end, shorter_period) of the `months`-calendar-month window that
    precedes the reference month. `months` comes from the pack row
    eo_average_wage_months — there is no default, so no caller can silently
    assume 12."""
    end = reference_date.replace(day=1) - timedelta(days=1)
    start = add_months(reference_date.replace(day=1), -int(months))
    if employment_start > start:
        return employment_start, end, True
    return start, end, False


def calculate(reference_date: date, employment_start: date, payslips: list, disregarded: list,
              benefit_type: str, overtime_constant: bool = False, rate_map: dict = None) -> dict:
    """payslips: [{payslipId, periodStart, periodEnd, eoWages, overtime, revision}]
    — eoWages INCLUDES overtime; overtime is the overtime part of it.
    disregarded: [{from, to, reason, amountPaid}].

    `rate_map` is REQUIRED in production (the service passes the pinned pack):
    the window length, divisor, overtime share and 4/5 factor are pack rows."""
    stat = parameters(rate_map or {})
    v = stat["values"]
    window_months = int(v["eo_average_wage_months"])
    days_per_year = v["eo_average_wage_days_per_year"]
    overtime_share = v["overtime_share"]
    four_fifths = v["four_fifths"]
    start, end, shorter = lookback_window(reference_date, employment_start, window_months)
    if end < start:
        raise HongKongCalculationBlockedError(
            "average_wage_period", f"no complete wage history before {reference_date} (employment began {employment_start})")

    included, covered = [], set()
    for p in sorted(payslips, key=lambda r: str(r["periodStart"])):
        # A first wage period may begin before the employment did (mid-month
        # joiner): only the employed days belong to it.
        ps, pe = max(to_date(p["periodStart"]), employment_start), to_date(p["periodEnd"])
        if pe < start or ps > end:
            continue
        if ps < start or pe > end:
            raise HongKongCalculationBlockedError(
                "average_wage_period",
                f"payslip #{p['payslipId']} ({ps} – {pe}) straddles the lookback window {start} – {end}; "
                "apportioning a wage period is not in the certified content")
        for i in range((min(pe, end) - max(ps, start)).days + 1):
            covered.add(max(ps, start) + timedelta(days=i))
        included.append(p)
    missing = [start + timedelta(days=i) for i in range((end - start).days + 1)
               if start + timedelta(days=i) not in covered]
    if missing:
        raise HongKongCalculationBlockedError(
            "average_wage_history",
            f"committed payroll does not cover {len(missing)} day(s) of {start} – {end} (first gap {missing[0]}); "
            "the average wage is never estimated from incomplete history")

    total_days = days_inclusive(start, end)
    excluded_days, excluded_amount, excluded_rows = 0, ZERO, []
    seen = set()
    for d in disregarded or []:
        ds, de = max(to_date(d["from"]), start), min(to_date(d["to"]), end)
        if de < ds:
            continue
        if not d.get("reason"):
            raise HongKongCalculationBlockedError("average_wage_exclusion", "every disregarded period needs a statutory reason")
        days = [ds + timedelta(days=i) for i in range((de - ds).days + 1)]
        if seen & set(days):
            raise HongKongCalculationBlockedError("average_wage_exclusion", f"disregarded periods overlap around {ds}")
        seen |= set(days)
        excluded_days += len(days)
        excluded_amount += dec(d.get("amountPaid"))
        excluded_rows.append({"from": ds.isoformat(), "to": de.isoformat(), "days": len(days),
                              "reason": d["reason"], "amountPaid": str(cents(dec(d.get("amountPaid"))))})

    gross = sum((dec(p["eoWages"]) for p in included), ZERO)
    overtime = sum((dec(p.get("overtime")) for p in included), ZERO)
    included_days = total_days - excluded_days
    if included_days <= 0:
        raise HongKongCalculationBlockedError("average_wage_period", "every day of the lookback is disregarded")
    months = Decimal(included_days) * window_months / days_per_year
    base_wages = gross - excluded_amount
    overtime_rule = {"constantCharacter": bool(overtime_constant)}
    if overtime > ZERO and not overtime_constant:
        without_ot_monthly = (base_wages - overtime) / months
        ot_monthly = overtime / months
        share_met = without_ot_monthly > ZERO and ot_monthly >= without_ot_monthly * overtime_share
        overtime_rule.update({"monthlyAverageOvertime": str(cents(ot_monthly)),
                              "monthlyAverageWagesExcludingOvertime": str(cents(without_ot_monthly)),
                              "overtimeInclusionTestShare": str(overtime_share),
                              "overtimeInclusionTestMet": share_met,
                              "comparisonBase": "average monthly wages excluding overtime (G1 certification item)"})
        if not share_met:
            base_wages -= overtime
            overtime_rule["overtimeExcluded"] = str(cents(overtime))
    adw = base_wages / Decimal(included_days)
    result = {
        "benefitType": benefit_type, "referenceDate": reference_date.isoformat(),
        "lookbackStart": start.isoformat(), "lookbackEnd": end.isoformat(), "shorterEmploymentPeriod": shorter,
        "totalDays": total_days, "excludedDays": excluded_days, "includedDays": included_days,
        "totalWages": str(cents(gross)), "excludedAmount": str(cents(excluded_amount)),
        "wagesUsed": str(cents(base_wages)), "overtime": overtime_rule,
        "averageDailyWage": str(adw.quantize(Decimal("0.0001"))),
        "averageMonthlyWage": str(cents(base_wages / months)),
        "fourFifthsDailyWage": str(cents(adw * four_fifths)),
        "months": str(months.quantize(Decimal("0.0001"))),
        "includedRows": [{"payslipId": p["payslipId"], "periodStart": str(p["periodStart"]),
                          "periodEnd": str(p["periodEnd"]), "eoWages": str(cents(dec(p["eoWages"]))),
                          "overtime": str(cents(dec(p.get("overtime")))), "revision": p.get("revision")}
                         for p in included],
        "excludedPeriods": excluded_rows,
        "statutoryFactors": {"windowMonths": window_months, "daysPerYear": str(days_per_year),
                             "overtimeInclusionTestShare": str(overtime_share),
                             "fourFifthsFactor": str(four_fifths), "refs": stat["refs"]},
        "source": "Labour Department — Concise Guide to the Employment Ordinance, Appendix 1",
    }
    result["sourceRevisionHash"] = canonical_hash([(r["payslipId"], r["revision"]) for r in result["includedRows"]])
    result["evidenceHash"] = canonical_hash(result)
    return result
