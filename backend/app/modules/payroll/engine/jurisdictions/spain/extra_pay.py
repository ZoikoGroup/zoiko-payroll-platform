"""Extra payments (pagas extraordinarias) — ZP-ES-ENG-001 §8, ES-006, ES-021, F5.

The Social Security prorrata of the extra payments is a BASE component, never a
cash earning:

  * PRORATED_12  the extras are already paid inside the 12 monthly salaries, so
                 the monthly cash already carries them: prorrata 0 (adding it
                 again would double-count).
  * SEPARATE_14  the extras are paid as separate cash payments on their
                 agreement dates: every month's bases carry
                 annual extra-pay total / 12, and the cash extra pay in its
                 payment month is gross pay but is NEVER added to the base a
                 second time (F5).
"""
from decimal import Decimal

from app.modules.payroll.engine.jurisdictions.spain import errors as E
from app.modules.payroll.engine.jurisdictions.spain.params import ZERO, round2

POLICIES = ("PRORATED_12", "SEPARATE_14")


def monthly_prorrata(policy, annual_amount) -> Decimal:
    policy = (policy or "").upper()
    if policy not in POLICIES:
        raise E.ESCalculationBlockedError(
            E.keyed(E.EMPLOYEE_FACT_MISSING, "extra_pay_policy"),
            "the employee needs extra_pay_policy PRORATED_12 or SEPARATE_14 (ZP-ES-ENG-001 §8).")
    if policy == "PRORATED_12":
        return ZERO
    try:
        annual = Decimal(str(annual_amount))
    except Exception:  # noqa: BLE001 — None / text: the fact is missing, never a guess
        annual = None
    if annual is None or annual <= ZERO:
        raise E.ESCalculationBlockedError(
            E.keyed(E.EMPLOYEE_FACT_MISSING, "extra_pay_annual_amount"),
            "SEPARATE_14 needs the annual total of the extra payments (extra_pay_annual_amount) to prorate "
            "them into the contribution bases (ES-006).")
    return round2(annual / Decimal(12))
