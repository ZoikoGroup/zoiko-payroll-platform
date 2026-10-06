"""
modules/payroll/engine/countries/hong_kong.py
---------------------------------------------
Hong Kong SAR (HK) — ZP-HK-ENG-001 v1.0 statutory calculator, verified
against the official IRD / MPFA / Labour Department sources recorded as
SourceArtifact rows by scripts/seed_hong_kong_canonical_pack.py.

ARCHITECTURE LOCK: Hong Kong is NOT a monthly-PAYE jurisdiction. Ordinary
Salaries Tax is employee-assessed by the IRD, so this calculator NEVER
populates `tds` (or any other income-tax slot). What a Hong Kong payslip
carries:

  1. MPF mandatory contributions (jurisdictions/hong_kong/mpf.py) — coverage
     decision first (age 18–64, 60-day rule, exemptions; never inferred from
     full-/part-time), then the employee's 30-day + incomplete-period
     contribution holiday, then the relevant-income thresholds (monthly
     HK$7,100 / HK$30,000, or the daily HK$280 / HK$1,000 × days). Reused
     result fields (same convention as Singapore's CPF):
         employee_pension = MPF employee mandatory contribution (deduction)
         employer_pension = MPF employer mandatory contribution (employer cost)
     Before the 60th day the contributions ACCRUE (trace) and are booked in
     the period the 60-day condition is met, employer from the first day.
  2. Statutory Minimum Wage assessment (jurisdictions/hong_kong/minimum_wage.py)
     — hours × the SMW rate in force on each day (a period crossing 1 May
     2026 splits at HK$42.10 / HK$43.10), the hours-record trigger. An
     assessment in the trace; pay is never silently changed.
  3. IRD reportable remuneration for the year of assessment ending 31 March
     (HK-011), by IR56 field, from the earning classification.

Earning classification (HK-006): per component and per obligation (EO wages,
MPF relevant income, SMW countable wages, IRD field) from pack rows
rule_type HK_EARNING_CLASS — filing_status = component, tax_regime =
obligation, assessment_basis = INCLUDED | EXCLUDED | REVIEW, tax_formula =
IRD field, rate_label = rule id. A component with no MPF classification
BLOCKS (money-affecting); REVIEW amounts are disclosed, never guessed.

Fail-closed (HK-020): the calculator is pure; every statutory value comes
from the pinned pack; every missing row / fact BLOCKS with
HongKongCalculationBlockedError.
"""

from datetime import date
from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.jurisdictions.hong_kong import minimum_wage, mpf
from app.modules.payroll.engine.jurisdictions.hong_kong.common import (
    HongKongCalculationBlockedError, ZERO, cents, dec, month_end, row_ref, year_of_assessment,
)

ENGINE_VERSION = "HK-2026.1"

# Fail-closed: no Hong Kong statutory value has a hardcoded fallback. These
# exist only so fallback_registry.py can list the keys an HK pack must carry
# (readiness); every value is read from the pinned pack or the calculation
# BLOCKS ("HK" is in shared._VALIDATION_ENABLED_COUNTRIES).
_HK_MPF_EMPLOYEE_RATE = None
_HK_MPF_EMPLOYER_RATE = None
_HK_MPF_MIN_RI_MONTHLY = None
_HK_MPF_MAX_RI_MONTHLY = None
_HK_MPF_MIN_RI_DAILY = None
_HK_MPF_MAX_RI_DAILY = None
EARNING_CLASS = "HK_EARNING_CLASS"
OBLIGATIONS = ("EO_WAGES", "MPF_RI", "SMW_WAGES", "IRD")
_PAYROLL_DAYS_DEFAULT = 30

__all__ = ["calculate", "HongKongCalculationBlockedError", "ENGINE_VERSION"]


def _period(ctx: PayrollContext) -> tuple:
    start, end = getattr(ctx, "period_start", None), getattr(ctx, "period_end", None)
    if start and end:
        return start, end
    if ctx.pay_date is None:
        raise HongKongCalculationBlockedError("pay_date", "a pay date or payroll period is required")
    return ctx.pay_date.replace(day=1), month_end(ctx.pay_date)


def earning_components(ctx: PayrollContext) -> dict:
    """Gross split into classifiable components. Named allowances are folded
    into gross by the service without their own ctx field, so they are the
    remainder; an unpaid-absence deduction is a negative component."""
    parts = {
        "basic": dec(ctx.basic), "hra": dec(ctx.hra), "special_allowance": dec(ctx.special_allowance),
        "overtime": dec(ctx.overtime), "additional_compensation": dec(ctx.additional_compensation),
    }
    parts["named_allowances"] = dec(ctx.gross) - sum(parts.values(), ZERO)
    payroll_days = ctx.payroll_days or _PAYROLL_DAYS_DEFAULT
    unpaid = max(ctx.unpaid_leave_days or 0, 0)
    if unpaid:
        per_day = _round2(dec(ctx.gross) / Decimal(payroll_days))
        parts["unpaid_absence"] = -min(_round2(per_day * Decimal(unpaid)), dec(ctx.gross))
    return {k: v for k, v in parts.items() if v != ZERO}


def _classification_rows(slabs: list) -> dict:
    rows = {}
    for s in slabs or []:
        if getattr(s, "rule_type", None) != EARNING_CLASS:
            continue
        key = (s.filing_status, s.tax_regime)
        if key in rows:
            raise HongKongCalculationBlockedError(
                "earning_classification", f"two classification rows for {s.filing_status} / {s.tax_regime}")
        rows[key] = s
    return rows


def classify(ctx: PayrollContext) -> dict:
    """{obligation: {included, excluded, review, lines}} + IRD field totals."""
    rows = _classification_rows(ctx.slabs)
    out = {o: {"included": ZERO, "excluded": ZERO, "review": ZERO, "lines": []} for o in OBLIGATIONS}
    ird_fields = {}
    for component, amount in earning_components(ctx).items():
        # An unpaid absence reduces whatever the paid components count for;
        # it follows the basic-salary classification.
        lookup = "basic" if component == "unpaid_absence" else component
        for obligation in OBLIGATIONS:
            row = rows.get((lookup, obligation))
            if row is None:
                if obligation == "MPF_RI":
                    raise HongKongCalculationBlockedError(
                        f"earning_classification:{component}",
                        f"earning component {component!r} has no certified MPF relevant-income classification")
                basis, ref = "REVIEW", None
            else:
                basis, ref = row.assessment_basis, row_ref(row)
            if basis not in ("INCLUDED", "EXCLUDED", "REVIEW"):
                raise HongKongCalculationBlockedError(
                    f"earning_classification:{component}", f"invalid classification {basis!r} for {obligation}")
            bucket = {"INCLUDED": "included", "EXCLUDED": "excluded", "REVIEW": "review"}[basis]
            out[obligation][bucket] += amount
            out[obligation]["lines"].append({"component": component, "amount": str(cents(amount)),
                                             "treatment": basis, "ref": ref})
            if obligation == "IRD" and basis == "INCLUDED":
                field = (getattr(row, "tax_formula", None) or "UNMAPPED") if row is not None else "UNMAPPED"
                ird_fields[field] = ird_fields.get(field, ZERO) + amount
    for o in OBLIGATIONS:
        for k in ("included", "excluded", "review"):
            out[o][k] = cents(out[o][k])
    return {"obligations": out, "irdFields": {k: cents(v) for k, v in sorted(ird_fields.items())}}


def _period_contribution(params, frequency, ps, pe, relevant_income, start) -> dict:
    levels = mpf.thresholds(params, frequency, ps, pe)
    holiday = mpf.employee_holiday_applies(ps, pe, start, int(params["values"]["mpf_employee_holiday_days"]))
    return mpf.contributions(relevant_income, params, levels, holiday)


def calculate(ctx: PayrollContext) -> dict:
    facts = dict(getattr(ctx, "hk_worker_facts", None) or {})
    if not facts.get("profileId"):
        raise HongKongCalculationBlockedError(
            "statutory_profile", "no Hong Kong statutory profile version is in force for this payroll date")
    if ctx.date_of_birth and not facts.get("dateOfBirth"):
        facts["dateOfBirth"] = ctx.date_of_birth.isoformat()
    for attr, key in (("date_of_joining", "dateOfJoining"), ("date_of_leaving", "terminationDate")):
        value = getattr(ctx, attr, None)
        if value and not facts.get(key):
            facts[key] = value.isoformat()
    ps, pe = _period(ctx)
    frequency = ctx.pay_frequency or "Monthly"
    classification = classify(ctx)
    ob = classification["obligations"]
    relevant_income = ob["MPF_RI"]["included"]

    params = mpf.mpf_parameters(ctx.rate_map)
    coverage = mpf.resolve_coverage(facts, ps, pe, params)
    start = mpf.employment_start(facts)
    current = _period_contribution(params, frequency, ps, pe, relevant_income, start)
    employer = employee = ZERO
    catch_up = []
    if coverage["status"] == "COVERED":
        employer, employee = dec(current["employer"]), dec(current["employee"])
        for prior in facts.get("priorPeriods") or []:
            if prior.get("coverageStatus") != "PENDING_60_DAY" or prior.get("caughtUp"):
                continue
            pps, ppe = date.fromisoformat(prior["periodStart"]), date.fromisoformat(prior["periodEnd"])
            line = _period_contribution(params, prior.get("payFrequency") or frequency, pps, ppe,
                                        dec(prior["relevantIncome"]), start)
            employer += dec(line["employer"])
            employee += dec(line["employee"])
            catch_up.append({"payslipId": prior.get("payslipId"), "periodStart": prior["periodStart"],
                             "periodEnd": prior["periodEnd"], **line})
    mpf_trace = {
        "coverage": coverage, "currentPeriod": current, "catchUp": catch_up,
        "employer": str(cents(employer)), "employee": str(cents(employee)),
        "contributionDay": mpf.period_contribution_day(pe, int(params["values"]["mpf_contribution_day"])).isoformat(),
        "contributionDayNote": "statutory extension for non-working / suspension days is not applied (disclosed)",
        "thresholdBasis": mpf.thresholds(params, frequency, ps, pe)["basis"],
        "rounding": "half-up to the cent (G1 certification item)",
        "refs": params["refs"],
    }
    if coverage["status"] == "PENDING_60_DAY":
        mpf_trace["accruedPending"] = {"employer": current["employer"], "employee": current["employee"],
                                       "basis": "booked in the period the 60-day condition is met"}

    segments = getattr(ctx, "hk_rule_segments", None) or {}
    smw = minimum_wage.assess(
        getattr(ctx, "hk_hours", None) or {}, segments.get("smw_hourly_rate") or [],
        segments.get("smw_hours_record_cap_monthly") or [],
        ob["SMW_WAGES"]["included"], ob["SMW_WAGES"]["review"], ps, pe, frequency,
    )

    # Same figure StandardStrategy produces: gross − unpaid-absence deduction
    # − MPF employee share (the absence component is negative).
    unpaid_absence = earning_components(ctx).get("unpaid_absence", ZERO)
    net_pay = _round2(dec(ctx.gross) + unpaid_absence - employee)
    trace = {
        "engine": ENGINE_VERSION, "country": "HK",
        "period": {"start": ps.isoformat(), "end": pe.isoformat(), "payDate": ctx.pay_date.isoformat() if ctx.pay_date else None,
                   "payFrequency": frequency},
        "profileId": facts.get("profileId"), "workerFacts": {k: v for k, v in facts.items() if k != "priorPeriods"},
        "classification": {o: {k: (str(v) if not isinstance(v, list) else v) for k, v in d.items()} for o, d in ob.items()},
        "mpf": mpf_trace,
        "minimumWage": smw,
        "ird": {"yearOfAssessment": year_of_assessment(ctx.pay_date or pe),
                "reportable": {k: str(v) for k, v in classification["irdFields"].items()},
                "basis": "accumulated by payment date into the year of assessment ending 31 March (HK-011)"},
        "salariesTax": {"withholding": "NONE",
                        "basis": "Hong Kong Salaries Tax is assessed by the IRD on the employee — no payroll "
                                 "withholding. An IR56G departure hold is a payment control, not a deduction."},
        "result": {"gross": str(cents(dec(ctx.gross))), "mpfEmployee": str(cents(employee)),
                   "mpfEmployer": str(cents(employer)), "netPay": str(net_pay),
                   "employerCost": str(_round2(dec(ctx.gross) + employer))},
    }
    return dict(
        employee_pension=cents(employee),   # MPF employee mandatory contribution
        employer_pension=cents(employer),   # MPF employer mandatory contribution
        hk_calculation_trace=trace,
        _hk_statutory_profile_id=facts.get("profileId"),
    )
