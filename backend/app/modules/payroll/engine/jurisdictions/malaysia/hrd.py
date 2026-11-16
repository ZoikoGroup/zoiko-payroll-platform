"""HRD levy (ZP-MY-ENG-001 §8; MY-015 / MY-016).

Employer-level statutory cost — never an employee deduction, never part of net
pay. The rate follows the employer's REGISTERED category on its registration
(applicability), never a live headcount (MY-016). Base from the signed
earning classes; rate and rounding from signed rows."""
from __future__ import annotations

from app.modules.payroll.engine.jurisdictions.malaysia.pack import HUNDRED, MyPack, dec, money

_RATE_KEY = {"COMPULSORY": "my_hrd_rate_compulsory", "OPTIONAL_REGISTERED": "my_hrd_rate_optional"}


def compute(pack: MyPack, base, decision: dict) -> dict:
    key = _RATE_KEY[decision["category"]]
    rate = pack.pct(key, "employer")
    levy = pack.rounder("my_rounding_hrd")(dec(base) * rate / HUNDRED)
    return {"employer": levy, "trace": {"category": decision["category"], "base": money(base), "rateKey": key,
                                        "ratePct": str(rate), "levy": money(levy)}}
