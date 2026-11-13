"""Poland health contribution (zdrowotne) — ZP-PL-ENG-001 §2 / §5.

Employee-funded, on its OWN base: the ZDROWOTNE earning-class base less the
employee social contributions (signed rule pl_health_base_rule =
GROSS_LESS_EMPLOYEE_SOCIAL). No 30x cap (spec §5: "no generic 30x cap").
Whether any limitation applies is NOT in the specification:
pl_health_limitation_rule must be signed ("NONE" is the only supported
value) or the calculation blocks. Own rounding rule (pl_rounding_health).
"""
from __future__ import annotations

from decimal import Decimal

from app.modules.payroll.engine.countries import poland_content as content
from app.modules.payroll.engine.jurisdictions.poland.pack import HUNDRED, ZERO, PlPack, money


def compute(pack: PlPack, bases: dict, applicability: dict, employee_social: Decimal) -> dict:
    if not applicability["obligations"]["ZDROWOTNE"]["applies"]:
        return {"amount": ZERO, "base": ZERO, "trace": {"applies": False}}
    rule = pack.text("pl_health_base_rule", ("GROSS_LESS_EMPLOYEE_SOCIAL",))
    limitation = pack.text("pl_health_limitation_rule", content.HEALTH_LIMITATION_RULES)
    rnd = pack.rounder("pl_rounding_health")
    base = max(bases["ZDROWOTNE"]["base"] - employee_social, ZERO)
    rate = pack.pct("pl_health", "employee")
    amount = rnd(base * rate / HUNDRED)
    return {"amount": amount, "base": base,
            "trace": {"applies": True, "baseRule": rule, "limitationRule": limitation, "base": money(base),
                      "employeeSocialDeducted": money(employee_social), "ratePct": str(rate),
                      "amount": money(amount)}}
