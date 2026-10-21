"""
engine/jurisdictions/brazil/labor.py
-------------------------------------
Brazil CLT working-time rules (ZP-BR-ENG-001 v1.0) — pure, ORM-free.

Sources:
- CLT art. 59 (overtime 50% / 100%, CCT override)
- CLT art. 73 (night premium 20% on 52m30s legal night hour)
- Lei 605/1949 (DSR on overtime and variable pay)
- State wage floors (SP, RJ, RS, PR, SC, etc.)
- Collective agreements (CCT/ACT) — Phase 8

Phase 5b: statutory defaults as constants.
Phase 8: CCT/state floor overrides via resolve_labor_rates().
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Tuple, Dict, Any

# ──────────────────────────────────────────────────────────────────────────────
# Statutory defaults (CLT) — fallback when no CCT/state floor applies
# ──────────────────────────────────────────────────────────────────────────────

# Aliases for backward compatibility (used by __init__.py and existing code)
OVERTIME_50_PCT = Decimal("50")      # CLT art. 59 §1
OVERTIME_100_PCT = Decimal("100")    # CLT art. 59 §1 (Sundays/holidays)
NIGHT_PREMIUM_PCT = Decimal("20")    # CLT art. 73
NIGHT_HOUR_MINUTES = Decimal("52.5") # 52m30s legal night hour
DSR_ON_VARIABLE = True               # Lei 605/1949

# Canonical names (used internally)
STATUTORY_OVERTIME_50_PCT = OVERTIME_50_PCT
STATUTORY_OVERTIME_100_PCT = OVERTIME_100_PCT
STATUTORY_NIGHT_PREMIUM_PCT = NIGHT_PREMIUM_PCT
STATUTORY_NIGHT_HOUR_MINUTES = NIGHT_HOUR_MINUTES
STATUTORY_DSR_ON_VARIABLE = True


def _r2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ──────────────────────────────────────────────────────────────────────────────
# CCT/State Floor Resolution
# ──────────────────────────────────────────────────────────────────────────────

class LaborRates:
    """
    Resolved labor rates for a specific employee/context.
    Priority: ENTERPRISE CCT > SECTOR CCT > UNION CCT > STATE FLOOR > STATUTORY
    """
    def __init__(
        self,
        overtime_50_pct: Decimal,
        overtime_100_pct: Decimal,
        night_premium_pct: Decimal,
        night_hour_minutes: Decimal,
        dsr_on_variable: bool,
        wage_floor_monthly: Optional[Decimal] = None,
        wage_floor_hourly: Optional[Decimal] = None,
        hazard_premium_pct: Optional[Decimal] = None,
        unhealthy_premium_pct: Optional[Decimal] = None,
        source: str = "STATUTORY",
    ):
        self.overtime_50_pct = overtime_50_pct
        self.overtime_100_pct = overtime_100_pct
        self.night_premium_pct = night_premium_pct
        self.night_hour_minutes = night_hour_minutes
        self.dsr_on_variable = dsr_on_variable
        self.wage_floor_monthly = wage_floor_monthly
        self.wage_floor_hourly = wage_floor_hourly
        self.hazard_premium_pct = hazard_premium_pct
        self.unhealthy_premium_pct = unhealthy_premium_pct
        self.source = source


def resolve_labor_rates(
    employee_state: str,
    employee_cbo: Optional[str],
    collective_agreements: list[Dict[str, Any]],
    state_floors: list[Dict[str, Any]],
) -> LaborRates:
    """
    Resolve the applicable labor rates for an employee.

    Priority (highest wins):
      1. ENTERPRISE CCT (organization-specific)
      2. SECTOR CCT (state + sector)
      3. UNION CCT (municipality/state + category)
      4. STATE FLOOR (state-specific wage floor by UF/CBO)
      5. STATUTORY defaults

    Args:
        employee_state: UF code (SP, RJ, etc.)
        employee_cbo: 6-digit CBO code or None
        collective_agreements: List of dicts with CCT fields from PayrollBrCollectiveAgreement
        state_floors: List of dicts with state floor fields from PayrollBrStateWageFloor

    Returns:
        LaborRates with the highest-priority applicable values.
    """
    # Start with statutory defaults
    rates = LaborRates(
        overtime_50_pct=OVERTIME_50_PCT,
        overtime_100_pct=OVERTIME_100_PCT,
        night_premium_pct=NIGHT_PREMIUM_PCT,
        night_hour_minutes=NIGHT_HOUR_MINUTES,
        dsr_on_variable=DSR_ON_VARIABLE,
        source="STATUTORY",
    )

    # 1. State wage floors (base layer — overridden by CCTs)
    for floor in state_floors:
        uf = floor.get("state_uf")
        cbo = floor.get("cbo_code")
        if uf == employee_state and (cbo is None or cbo == employee_cbo):
            if floor.get("monthly_floor"):
                rates.wage_floor_monthly = floor["monthly_floor"]
            if floor.get("hourly_floor"):
                rates.wage_floor_hourly = floor["hourly_floor"]
            rates.source = f"STATE_FLOOR:{uf}"

    # 2. UNION CCTs (municipality/state + professional category)
    for cct in collective_agreements:
        if cct.get("scope_type") != "UNION":
            continue
        if not _cct_applies(cct, employee_state, employee_cbo):
            continue
        _apply_cct_rates(rates, cct)

    # 3. SECTOR CCTs (state + economic sector)
    for cct in collective_agreements:
        if cct.get("scope_type") != "SECTOR":
            continue
        if not _cct_applies(cct, employee_state, employee_cbo):
            continue
        _apply_cct_rates(rates, cct)

    # 4. ENTERPRISE CCTs (organization-specific, highest priority)
    for cct in collective_agreements:
        if cct.get("scope_type") != "ENTERPRISE":
            continue
        _apply_cct_rates(rates, cct)

    return rates


def _cct_applies(cct: Dict[str, Any], employee_state: str, employee_cbo: Optional[str]) -> bool:
    """Check if a CCT applies to the given employee context."""
    # Check states covered
    states = cct.get("states_covered") or []
    if states and employee_state not in states:
        return False
    # Check CBO codes covered
    cbo_codes = cct.get("cbo_codes_covered") or []
    if cbo_codes and employee_cbo not in cbo_codes:
        return False
    return True


def _apply_cct_rates(rates: LaborRates, cct: Dict[str, Any]) -> None:
    """Apply CCT rates if they are more favorable (higher) than current."""
    ot50 = cct.get("overtime_50_pct")
    if ot50 is not None and ot50 > rates.overtime_50_pct:
        rates.overtime_50_pct = ot50
        rates.source = f"CCT:{cct.get('cct_number')}"

    ot100 = cct.get("overtime_100_pct")
    if ot100 is not None and ot100 > rates.overtime_100_pct:
        rates.overtime_100_pct = ot100

    night = cct.get("night_premium_pct")
    if night is not None and night > rates.night_premium_pct:
        rates.night_premium_pct = night

    night_min = cct.get("night_hour_minutes")
    if night_min is not None:
        rates.night_hour_minutes = night_min

    dsr = cct.get("dsr_on_variable")
    if dsr is not None:
        rates.dsr_on_variable = dsr

    floor_m = cct.get("wage_floor_monthly")
    if floor_m is not None and (rates.wage_floor_monthly is None or floor_m > rates.wage_floor_monthly):
        rates.wage_floor_monthly = floor_m
        rates.source = f"CCT:{cct.get('cct_number')}"

    floor_h = cct.get("wage_floor_hourly")
    if floor_h is not None and (rates.wage_floor_hourly is None or floor_h > rates.wage_floor_hourly):
        rates.wage_floor_hourly = floor_h

    hazard = cct.get("hazard_premium_pct")
    if hazard is not None:
        rates.hazard_premium_pct = hazard

    unhealthy = cct.get("unhealthy_premium_pct")
    if unhealthy is not None:
        rates.unhealthy_premium_pct = unhealthy


# ──────────────────────────────────────────────────────────────────────────────
# Calculation Functions (using resolved LaborRates)
# ──────────────────────────────────────────────────────────────────────────────

def calculate_overtime(
    hours_50: Decimal,
    hours_100: Decimal,
    base_hourly_rate: Decimal,
    rates: LaborRates,
) -> tuple[Decimal, Decimal]:
    """
    Compute overtime amounts at resolved 50% and 100% premiums.
    """
    amount_50 = _r2(hours_50 * base_hourly_rate * (Decimal("1") + rates.overtime_50_pct / Decimal("100")))
    amount_100 = _r2(hours_100 * base_hourly_rate * (Decimal("1") + rates.overtime_100_pct / Decimal("100")))
    return amount_50, amount_100


def calculate_night_premium(
    night_hours: Decimal,
    base_hourly_rate: Decimal,
    rates: LaborRates,
) -> Decimal:
    """Night premium using resolved night_premium_pct and night_hour_minutes."""
    premium = _r2(night_hours * base_hourly_rate * rates.night_premium_pct / Decimal("100"))
    return premium


def calculate_dsr(
    variable_daily_amount: Decimal,
    days_worked: int,
    sundays_holidays: int,
    rates: LaborRates,
) -> Decimal:
    """DSR using resolved dsr_on_variable flag."""
    if not rates.dsr_on_variable:
        return Decimal("0")
    if days_worked <= 0:
        raise ValueError("days_worked must be > 0")
    return _r2(variable_daily_amount * Decimal(str(sundays_holidays)))


def calculate_dsr_from_total(
    total_variable_pay: Decimal,
    days_worked: int,
    sundays_holidays: int,
    rates: LaborRates,
) -> Decimal:
    if not rates.dsr_on_variable:
        return Decimal("0")
    if days_worked <= 0:
        raise ValueError("days_worked must be > 0")
    daily_avg = total_variable_pay / Decimal(str(days_worked))
    return _r2(daily_avg * Decimal(str(sundays_holidays)))


def check_wage_floor(
    contract_salary: Decimal,
    rates: LaborRates,
) -> tuple[bool, Optional[Decimal]]:
    """
    Check if contract salary meets the applicable wage floor.
    Returns (meets_floor, applicable_floor).
    """
    floor = rates.wage_floor_monthly
    if floor is not None and contract_salary < floor:
        return False, floor
    return True, floor


def _r2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)