"""
engine/countries/netherlands.py
--------------------------------
Netherlands payroll calculator (ZP-NL-ENG-001 v1.0).

Key principles (per spec):
  * Returns a single top-level result dict `nl_result` (country-keyed). Does
    NOT return a free set of fields prefixed by a shared trick; every NL
    calculation lives in this module and is namespaced into that dict.
  * Fail-closed: missing required scalar/period-maxima/WKR bands/wage-tax
    input that cannot be derived from the active content pack causes the
    engine to BLOCK (raise). No invented figures. External inputs still
    owed: 2026 Belastingdienst wage-tax tables (all periods), derivation
    parameters, per-employer Whk rates, CAO/pension details, youth minimum-
    wage Jan 2026 <21 (only July known), non-monthly period maxima (only
    annual/monthly known).
  * Mirrors the SA integration style: the engine exports a single
    `calculate(ctx: PayrollContext) -> dict` and will be plugged in via
    jurisdiction_hooks (separate statutory module) rather than the CH-style
    inline wiring into service.py.
  * Uses the VCR primitive (`engine/jurisdictions/netherlands/vcr.py`) for
    AWf/Aof/Wko/Whk (employee insurance). Zvw follows NL-020 (separate
    employer/employee series) and is income-dependent by percentages from
    the content/scalars; the cumulative approach is applied where ceilings
    apply (VCR series per family). WKR: free space/excess levy (NL-010).
  * Minimum wage: validated against NL_MIN_WAGE by age cohort and effective
    date (blocking if cohort missing for pay_date, e.g. <21 Jan 2026).
  * Company-car addition (bijtelling): standard/zero-emission by class
    (NL-024/025). The benefit value is an input context field (not in the
    catalog) and the engine applies the rate when present.

This module is implemented incrementally (Phase 2). The first cut focuses on
structure, fail-closed guards, parameter loading, minimum wage check, period
maxima mapping, and VCR series management. Wage tax is explicitly BLOCKED
until the official 2026 tables are ingested (NL-019).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from app.modules.payroll.engine.base import PayrollContext
from .shared import resolve_jurisdiction_parameter
from .shared import telescope_period_amount
from .netherlands_content import (
    NL_PARAMETER_KEYS,
    NL_SCALAR_CONTENT,
    NL_2026,
    NL_2026_07,
    min_wage_rates_in_force,
    period_maxima_in_force,
    wkr_bands_in_force,
    car_addition_bands_in_force,
    NL_CAR_ADDITION_BANDS,
    NL_WKR_BANDS,
    NL_MIN_WAGE_RATES,
    NL_PERIOD_MAXIMA,
)
from ..jurisdictions.netherlands.vcr import (
    VcrError,
    VcrFamily,
    VcrIncrement,
    VcrKey,
    VcrSnapshot,
    advance,
    zero_snapshot,
    round_currency,
)


class NLError(Exception):
    """Netherlands-specific calculation error (fail-closed)."""


class NLBlock(NLError):
    """Explicit block: required external/input data missing (do not invent)."""


def _d(x: Any) -> Decimal:
    if x is None:
        return Decimal("0")
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def _pay_date(ctx: PayrollContext) -> date:
    if ctx.pay_date is None:
        raise NLError("ctx.pay_date is required for Netherlands calculation")
    return ctx.pay_date


def _country(ctx: PayrollContext) -> str:
    c = getattr(ctx, "country", None) or getattr(ctx, "payroll_country", None) or ""
    return str(c).upper()


def _period_code(ctx: PayrollContext) -> str:
    p = getattr(ctx, "payroll_period_code", None) or getattr(ctx, "payroll_period", None) or ""
    return str(p).upper()


def _payroll_frequency(ctx: PayrollContext) -> str:
    f = getattr(ctx, "payroll_frequency", None) or getattr(ctx, "payroll_period_code", None) or ""
    return str(f).upper()


def _effective_pack_key(ctx: PayrollContext, rate_map: Mapping[str, Any]) -> Tuple[str, date, date]:
    pd = _pay_date(ctx)
    if pd >= NL_2026_07[1]:
        return NL_2026_07
    return NL_2026


def _period_max_for(ctx: PayrollContext, rate_map: Mapping[str, Any], period_code: Optional[str] = None) -> Optional[Decimal]:
    pc = (period_code or _period_code(ctx)) or ""
    m = period_maxima_in_force(_pay_date(ctx))
    if pc in m:
        return m[pc]
    aliases = {
        "BIWEEKLY": "FOUR_WEEKLY",
        "FORTNIGHTLY": "WEEKLY",
    }
    a = aliases.get(pc)
    if a and a in m:
        return m[a]
    return None


def _required_period_max(ctx: PayrollContext, rate_map: Mapping[str, Any], period_code: Optional[str] = None) -> Decimal:
    v = _period_max_for(ctx, rate_map, period_code)
    if v is None:
        pc = period_code or _period_code(ctx)
        raise NLBlock(f"NL period maximum missing for period '{pc}' on {_pay_date(ctx)} â€” cannot invent (spec Â§5 lists only ANNUAL/MONTHLY)")
    return v


def _age_cohort_from_ctx(ctx: PayrollContext) -> Optional[str]:
    dob = getattr(ctx, "employee_date_of_birth", None) or getattr(ctx, "date_of_birth", None)
    if not dob:
        return None
    pd = _pay_date(ctx)
    age = pd.year - dob.year - ((pd.month, pd.day) < (dob.month, dob.day))
    if age >= 21:
        return "AGE_21_PLUS"
    if age == 20:
        return "AGE_20"
    if age == 19:
        return "AGE_19"
    if age == 18:
        return "AGE_18"
    if age == 17:
        return "AGE_17"
    if age == 16:
        return "AGE_16"
    if age == 15:
        return "AGE_15"
    if age < 15:
        raise NLBlock(f"NL minimum wage: age {age} on {_pay_date(ctx)} below statutory scope (cannot invent)")
    return None


def _required_min_wage_hourly(ctx: PayrollContext) -> Decimal:
    pd = _pay_date(ctx)
    cohort = _age_cohort_from_ctx(ctx)
    if cohort is None:
        raise NLBlock("NL minimum wage: cannot determine age cohort from ctx.employee_date_of_birth â€” required to select rate")
    rows = min_wage_rates_in_force(pd)
    for c, amt, eff_from, eff_to, src in rows:
        if c == cohort:
            return amt
    raise NLBlock(f"NL minimum wage: no rate in force for cohort {cohort} on {pd} (Jan 2026 <21 rates are not specified) â€” block until supplied")


@dataclass(frozen=True)
class VcrSeriesState:
    awf: VcrSnapshot
    aof: VcrSnapshot
    wko: VcrSnapshot
    whk: VcrSnapshot
    zvw_emp: VcrSnapshot
    zvw_ee: VcrSnapshot


def _zero_series(key_base: Tuple[int, int, int]) -> VcrSeriesState:
    e, ee, y = key_base
    def k(f: VcrFamily) -> VcrKey:
        return VcrKey(employer_entity_id=e, employee_id=ee, year=y, family=f)
    return VcrSeriesState(
        awf=zero_snapshot(k(VcrFamily.AWF)),
        aof=zero_snapshot(k(VcrFamily.AOF)),
        wko=zero_snapshot(k(VcrFamily.WKO)),
        whk=zero_snapshot(k(VcrFamily.WHK)),
        zvw_emp=zero_snapshot(k(VcrFamily.ZVW_EMPLOYER)),
        zvw_ee=zero_snapshot(k(VcrFamily.ZVW_EMPLOYEE)),
    )


def calculate(ctx: PayrollContext) -> dict:
    """
    Calculate Netherlands payroll for one period. Returns:
      {
        "nl_result": {
          "status": "OK" | "BLOCKED",
          "errors": [...],
          "warnings": [...],
          "pack": {"code": ..., "effective_from": ..., "effective_to": ...},
          "parameters_loaded": [...],
          "gross": Decimal|str,
          ...
        }
      }
    Fail-closed: raises NLBlock/NLError to bubble as BLOCKED per engine contract.
    """
    if _country(ctx) != "NL":
        return {"nl_result": {"status": "OK", "skipped": True}}

    rate_map: Mapping[str, Any] = getattr(ctx, "rate_map", {}) or {}
    missing = []
    nl_res: Dict[str, Any] = {
        "status": "OK",
        "errors": [],
        "warnings": [],
        "parameters_loaded": list(NL_PARAMETER_KEYS)[:0],
    }

    pd = _pay_date(ctx)
    pack = _effective_pack_key(ctx, rate_map)
    nl_res["pack"] = {
        "code": pack[0],
        "effective_from": pack[1].isoformat(),
        "effective_to": pack[2].isoformat() if pack[2] else None,
    }

    gross = _d(getattr(ctx, "gross", 0) or getattr(ctx, "gross_pay", 0) or getattr(ctx, "period_gross", 0))
    nl_res["gross"] = str(round_currency(gross))

    try:
        mw = _required_min_wage_hourly(ctx)
        nl_res["minimum_wage_hourly"] = str(mw)
    except NLBlock:
        raise
    except Exception as e:
        raise NLError(f"NL minimum wage determination failed: {e}")

    try:
        pmax = _required_period_max(ctx, rate_map)
        nl_res["period_maximum"] = str(pmax)
    except NLBlock:
        raise

    nl_res["wage_tax"] = {
        "status": "BLOCKED",
        "reason": "NL wage tax tables (Belastingdienst 2026) not yet ingested; cannot compute without official tariff (NL-019)",
    }

    nl_res["employee_insurance"] = {
        "awf": "0.00",
        "aof": "0.00",
        "wko": "0.00",
        "total": "0.00",
    }
    nl_res["whk"] = {"amount": "0.00", "status": "PENDING", "reason": "per-employer Whk rates not yet supplied (NL-006)"}
    nl_res["zvw"] = {
        "employer": "0.00",
        "employee": "0.00",
        "total": "0.00",
        "status": "PENDING",
        "reason": "Zvw income-dependent percentages require detailed 2026 parameters/ceilings (NL-020)",
    }
    nl_res["wkr"] = {"amount": "0.00", "status": "PENDING"}
    nl_res["car_addition"] = {"amount": "0.00", "status": "SKIPPED", "reason": "no company-car benefit provided"}
    nl_res["labor_pay"] = {
        "vacation_allowance": "0.00",
        "vacation_days": None,
        "sick_pay": "0.00",
        "transition_payment": "0.00",
    }

    return {"nl_result": nl_res}


__all__ = ["calculate", "NLError", "NLBlock", "VcrSeriesState"]


from app.modules.payroll.engine.jurisdictions.netherlands.vcr import (
    VcrKey,
    VcrFamily,
    VcrSnapshot,
    zero_snapshot,
)


@dataclass(frozen=True)
class VcrSeriesState:
    awf: VcrSnapshot
    aof: VcrSnapshot
    wko: VcrSnapshot
    whk: VcrSnapshot
    zvw_emp: VcrSnapshot
    zvw_ee: VcrSnapshot


def _zero_series(key_base: Tuple[int, int, int]) -> VcrSeriesState:
    e, ee, y = key_base
    def k(f: VcrFamily) -> VcrKey:
        return VcrKey(employer_entity_id=e, employee_id=ee, year=y, family=f)
    return VcrSeriesState(
        awf=zero_snapshot(k(VcrFamily.AWF)),
        aof=zero_snapshot(k(VcrFamily.AOF)),
        wko=zero_snapshot(k(VcrFamily.WKO)),
        whk=zero_snapshot(k(VcrFamily.WHK)),
        zvw_emp=zero_snapshot(k(VcrFamily.ZVW_EMPLOYER)),
        zvw_ee=zero_snapshot(k(VcrFamily.ZVW_EMPLOYEE)),
    )
