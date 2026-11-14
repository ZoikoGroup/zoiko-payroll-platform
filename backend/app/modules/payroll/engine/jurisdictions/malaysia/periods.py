"""Legal periods (ZP-MY-ENG-001 MY-006): every obligation declares the period
it belongs to; nothing is inferred from the payroll run label.

  PCB / CP38   deduction month  = the month of the PAYMENT DATE
  EPF          wage month       = the month of the pay period's end
  SOCSO / EIS  contribution month = the month of the pay period's end
  HRD          wage month       = the month of the pay period's end
"""
from __future__ import annotations

from datetime import date


def _month(on: date) -> str:
    return f"{on.year:04d}-{on.month:02d}"


def legal_periods(pay_date: date, period_end: date) -> dict:
    return {
        "PCB": {"basis": "DEDUCTION_MONTH", "period": _month(pay_date)},
        "EPF": {"basis": "WAGE_MONTH", "period": _month(period_end)},
        "SOCSO": {"basis": "CONTRIBUTION_MONTH", "period": _month(period_end)},
        "EIS": {"basis": "CONTRIBUTION_MONTH", "period": _month(period_end)},
        "HRD": {"basis": "WAGE_MONTH", "period": _month(period_end)},
    }
