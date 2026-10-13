"""
engine/jurisdictions/netherlands/company_car.py
-----------------------------------------------
Company-car private-use addition (bijtelling) — ZP-NL-ENG-001 §8, NL-024/NL-025.

The addition is a taxable benefit in kind (no cash): annual addition =
catalog value × the rate of the car's rate window, reduced by the employee's
own contribution, spread over the pay periods. NL-025: the 22% / 18% headline
rates are NOT a universal fleet rule — the rate window is selected from the
active pack's NL_CAR_ADDITION rows (filing_status = car class, rate_pct,
effective_from/effective_to = the first-admission window). A car whose
first-admission date has no window BLOCKS, as does a zero-emission car while
the catalog-value cap for its window is not in the pack.

"No private use" (≤ 500 km per year) needs recorded evidence (NL-024);
without it the addition applies.
Pure: no ORM, no framework.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, Mapping, Optional

NL_CAR_ADDITION_RULE = "NL_CAR_ADDITION"


class CompanyCarError(Exception):
    """A car fact or rate window is missing — the caller blocks."""


@dataclass(frozen=True)
class CompanyCarResult:
    car_id: Optional[int]
    car_class: str
    catalog_value: Decimal
    rate_pct: Decimal
    annual_addition: Decimal
    own_contribution_period: Decimal
    period_addition: Decimal
    no_private_use: bool

    def as_dict(self) -> dict:
        return {"carId": self.car_id, "carClass": self.car_class, "catalogValue": str(self.catalog_value),
                "ratePct": str(self.rate_pct), "annualAddition": str(self.annual_addition),
                "ownContributionPeriod": str(self.own_contribution_period),
                "periodAddition": str(self.period_addition), "noPrivateUse": self.no_private_use}


def _window(slabs: Iterable[Any], car_class: str, first_admission: date):
    for row in slabs or ():
        if getattr(row, "rule_type", None) != NL_CAR_ADDITION_RULE or getattr(row, "filing_status", None) != car_class:
            continue
        eff_from, eff_to = getattr(row, "effective_from", None), getattr(row, "effective_to", None)
        if (eff_from is None or eff_from <= first_admission) and (eff_to is None or eff_to >= first_admission):
            return row
    return None


def period_addition(car: Mapping[str, Any], *, slabs: Iterable[Any], periods_per_year: int) -> CompanyCarResult:
    """Addition for one pay period for one car record (payroll_nl_company_cars shape)."""
    car_class = (car.get("vehicle_class") or car.get("addition_rate_window_key") or "").strip().upper()
    if not car_class:
        raise CompanyCarError("company car has no vehicle class / rate-window key (NL-024)")
    first_admission = car.get("first_admission_date")
    if first_admission is None:
        raise CompanyCarError("company car has no first-admission date (NL-024)")
    if isinstance(first_admission, str):
        first_admission = date.fromisoformat(first_admission)
    catalog = Decimal(str(car.get("catalog_value") or "0"))
    own = Decimal(str(car.get("employee_own_contribution") or "0"))
    if (car.get("private_use_status") or "PRIVATE") == "NO_PRIVATE_USE_500KM":
        if not car.get("no_private_use_evidence_ref"):
            raise CompanyCarError("'no private use' needs recorded ≤500 km evidence (NL-024) — the addition cannot be skipped without it")
        return CompanyCarResult(car.get("id"), car_class, catalog, Decimal("0"), Decimal("0.00"), Decimal("0.00"),
                                Decimal("0.00"), True)
    window = _window(slabs, car_class, first_admission)
    if window is None:
        raise CompanyCarError(
            f"no NL_CAR_ADDITION rate window in the active pack for a {car_class} car first admitted {first_admission} "
            f"— older vehicles keep their own effective-dated rate (NL-025)")
    if car_class == "ZERO_EMISSION" and getattr(window, "max_amount", None) is None:
        raise CompanyCarError("zero-emission rate window has no catalog-value cap in the active pack (NL-025)")
    rate = Decimal(str(window.rate_pct))
    capped = getattr(window, "max_amount", None)
    if capped is not None and catalog > Decimal(str(capped)):
        raise CompanyCarError("catalog value above the reduced-rate cap needs the above-cap rate window (NL-025)")
    annual = (catalog * rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    per_period = (annual / Decimal(periods_per_year)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return CompanyCarResult(car.get("id"), car_class, catalog, rate, annual, own,
                            max(per_period - own, Decimal("0.00")), False)


__all__ = ["CompanyCarError", "CompanyCarResult", "period_addition", "NL_CAR_ADDITION_RULE"]
