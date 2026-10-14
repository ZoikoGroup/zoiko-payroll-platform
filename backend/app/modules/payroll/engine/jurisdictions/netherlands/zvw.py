"""
engine/jurisdictions/netherlands/zvw.py
--------------------------------------
Zvw (Zorgverzekeringswet) — the income-dependent contribution (NL-019..NL-021).

NL-019: the employment's statutory path is decided BEFORE calculating Zvw:
  - EMPLOYER_LEVY        employer pays the levy (employer cost, never a deduction)
  - EMPLOYEE_CONTRIB     employee contribution withheld from net pay
  - anything else        (seafarer / special categories) has no certified
                         strategy yet -> ZvwPathError (the engine BLOCKS)
NL-020: each path is its own VCR series (ZVW_LEVY / ZVW_CONTRIB) against the
        Zvw maximum contribution wage.
NL-021: only the employee-contribution path reduces net pay.

Rates come from the active pack (nl_zvw_employer_pct / nl_zvw_employee_pct);
a missing rate raises — there is no fallback percentage.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from .premiums import PremiumConfigurationError, _rate_value
from .vcr import VcrFamily, VcrResult, round_currency


class ZvwPathError(ValueError):
    """Zvw path unknown or not certified for this release (NL-019)."""


EMPLOYER_LEVY = "EMPLOYER_LEVY"
EMPLOYEE_CONTRIB = "EMPLOYEE_CONTRIB"
_PATH_ALIASES = {"EMPLOYER_LEVY": EMPLOYER_LEVY, "EMPLOYEE_CONTRIB": EMPLOYEE_CONTRIB,
                 "EMPLOYEE_CONTRIBUTION": EMPLOYEE_CONTRIB}


def normalise_path(path: Optional[str]) -> str:
    """The employment's Zvw path, or ZvwPathError — never an assumed default."""
    key = (path or "").strip().upper()
    if not key:
        raise ZvwPathError("Zvw path not recorded on the employee's NL profile — cannot assume the employer levy (NL-019)")
    if key not in _PATH_ALIASES:
        raise ZvwPathError(f"Zvw path {key!r} has no certified calculation strategy in this release (NL-019)")
    return _PATH_ALIASES[key]


def family_for_path(path: str) -> str:
    return VcrFamily.ZVW_LEVY if normalise_path(path) == EMPLOYER_LEVY else VcrFamily.ZVW_CONTRIB


@dataclass(frozen=True)
class ZvwRates:
    employer_pct: Decimal  # nl_zvw_employer_pct (employer levy)
    employee_pct: Decimal  # nl_zvw_employee_pct (employee contribution)


def get_zvw_rates_from_pack(rate_map: dict) -> ZvwRates:
    employer = _rate_value(rate_map.get("nl_zvw_employer_pct"))
    employee = _rate_value(rate_map.get("nl_zvw_employee_pct"))
    missing = [k for k, v in (("nl_zvw_employer_pct", employer), ("nl_zvw_employee_pct", employee)) if v is None]
    if missing:
        raise PremiumConfigurationError(f"NL Zvw rate(s) not configured in the active pack: {', '.join(missing)}")
    return ZvwRates(employer_pct=employer, employee_pct=employee)


@dataclass(frozen=True)
class ZvwPeriodResult:
    path: str
    family: str
    rate_pct: Decimal
    base_increment: Decimal
    amount: Decimal

    @property
    def employer_levy(self) -> Decimal:
        return self.amount if self.path == EMPLOYER_LEVY else Decimal("0.00")

    @property
    def employee_contribution(self) -> Decimal:
        return self.amount if self.path == EMPLOYEE_CONTRIB else Decimal("0.00")


def calculate_zvw_period(path: str, vcr_result: VcrResult, rates: ZvwRates) -> ZvwPeriodResult:
    """Zvw for one period on the path's own VCR increment."""
    path = normalise_path(path)
    rate = rates.employer_pct if path == EMPLOYER_LEVY else rates.employee_pct
    return ZvwPeriodResult(path=path, family=family_for_path(path), rate_pct=rate,
                           base_increment=vcr_result.base_increment,
                           amount=round_currency(vcr_result.base_increment * rate / Decimal("100")))
