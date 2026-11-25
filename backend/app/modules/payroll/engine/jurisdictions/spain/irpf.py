"""IRPF withholding — ZP-ES-ENG-001 §6, §7 (docs/spain D4, gap G-01).

PHASE 4 IS NOT BUILT YET. The spec gives no IRPF value: every parameter of the
two 2026 AEAT algorithms (1 Jan-9 Sep and from 10 Sep 2026) must come from the
official AEAT "Algoritmo de cálculo de retenciones 2026" document, as pack rows
irpf_a_* / irpf_b_*. Until that phase lands, compute() BLOCKS the employee with
ES_RATE_MISSING:irpf — never a guessed rate, never a simplified bracket table
(ES-014), never an administrator-typed rate below the legal one (ES-017).

The signature is the contract engine/countries/spain.py already calls:
  compute(pay_date, monthly_gross, monthly_ss_employee, facts, rate_map)
  -> {"version": "IRPF-2026-A" | "IRPF-2026-B", "rate": Decimal fraction,
      "amount": Decimal, ...trace}
"""
from datetime import date
from decimal import Decimal

from app.modules.payroll.engine.jurisdictions.spain import errors as E

# The two 2026 algorithm versions and their boundary (spec §6, ES-015). The
# boundary is a legal date stated in the spec, not a rate; the rows of each
# version still carry their own effective dates in the pack.
VERSION_A = "IRPF-2026-A"
VERSION_B = "IRPF-2026-B"
VERSION_B_FROM = date(2026, 9, 10)


def version_for(pay_date: date) -> str:
    return VERSION_B if pay_date >= VERSION_B_FROM else VERSION_A


def compute(*, pay_date: date, monthly_gross: Decimal, monthly_ss_employee: Decimal, facts: dict,
            rate_map: dict) -> dict:
    version = version_for(pay_date)
    raise E.ESCalculationBlockedError(
        E.keyed(E.RATE_MISSING, "irpf"),
        f"IRPF withholding ({version}) is not configured: its parameters come only from the official AEAT "
        "'Algoritmo de cálculo de retenciones 2026' document (docs/spain G-01) and are added in Phase 4.")
