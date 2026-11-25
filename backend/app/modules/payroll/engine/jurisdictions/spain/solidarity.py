"""2026 solidarity contribution above the maximum base — ZP-ES-ENG-001 §5,
ES-011, ES-012, ES-013, F1, F2.

The ordinary bases stay capped at the maximum; remuneration above it is split
into three tranches, each with its own employee and employer rate (a separate
contribution family and ledger line):

  tranche 1   maximum            -> es_solidarity_t1_upper
  tranche 2   t1_upper           -> es_solidarity_t2_upper
  tranche 3   above t2_upper

The thresholds are monthly pack values multiplied by the same period factor as
the bases (docs/spain D6). Daily contributors are blocked upstream (G-05).
Future phase-in rates are effective-dated rows (ES-013); nothing here is a
constant.
"""
from decimal import Decimal

from app.modules.payroll.engine.jurisdictions.spain import params as P
from app.modules.payroll.engine.jurisdictions.spain.params import ZERO, round2


def compute(*, remuneration_with_overtime, factor: Decimal, rate_map: dict) -> dict:
    total = Decimal(str(remuneration_with_overtime))
    maximum = round2(P.amount(rate_map, "es_base_max_monthly") * factor)
    upper_1 = round2(P.amount(rate_map, "es_solidarity_t1_upper") * factor)
    upper_2 = round2(P.amount(rate_map, "es_solidarity_t2_upper") * factor)
    bands = (("t1", "es_solidarity_t1", maximum, upper_1), ("t2", "es_solidarity_t2", upper_1, upper_2),
             ("t3", "es_solidarity_t3", upper_2, None))

    tranches = []
    for name, key, low, high in bands:
        amount = max(total - low, ZERO)
        if high is not None:
            amount = min(amount, max(high - low, ZERO))
        amount = round2(amount)
        tranche = {"tranche": name, "key": key, "from": low, "to": high, "amount": amount,
                   "employee": ZERO, "employer": ZERO}
        if amount > ZERO:
            tranche["employee_rate"] = P.pct(rate_map, key, "employee")
            tranche["employer_rate"] = P.pct(rate_map, key, "employer")
            tranche["employee"] = round2(amount * tranche["employee_rate"])
            tranche["employer"] = round2(amount * tranche["employer_rate"])
        tranches.append(tranche)
    return {
        "excess": round2(max(total - maximum, ZERO)),
        "tranches": tranches,
        "employee_total": round2(sum((t["employee"] for t in tranches), ZERO)),
        "employer_total": round2(sum((t["employer"] for t in tranches), ZERO)),
    }
