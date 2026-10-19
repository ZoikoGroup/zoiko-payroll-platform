"""Mexico engine (Phase 5) — SBC: integration factor from the labour policy
(directional, F2 mechanics), variable part from the accumulator, the floor
rule (Q5), the UMA cap per contribution segment (F1 mechanics). SYNTHETIC."""

import copy
from datetime import date
from decimal import Decimal as D

import pytest

from tests import _mx_engine_helpers as h


def _blocked(fn, *a, **k):
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    with pytest.raises(MXBlock) as exc:
        fn(*a, **k)
    return exc.value


def _segments(c=None, **over):
    from app.modules.payroll.engine.jurisdictions.mexico import period

    return period.resolve(h.ctx(**over), c or h.content()).segments


def _compute(salary="600", policy=None, accumulator=None, lines=None, segments=None, zone="GENERAL",
             seniority=date(2024, 3, 1), on=h.PAY_DATE):
    from app.modules.payroll.engine.jurisdictions.mexico import sbc

    f = h.facts()
    return sbc.compute(daily_salary=D(salary), policy=f["mx_labor_policy"] if policy is None else policy,
                       seniority_date=seniority, on=on,
                       lines=lines if lines is not None else [{"code": "SALARY", "kind": "ORDINARY_SALARY", "sbc": "FIXED"}],
                       accumulator={"total": 0, "days": 0} if accumulator is None else accumulator,
                       segments=segments or _segments(), zone=zone)


def _policy(**over):
    p = copy.deepcopy(h.facts()["mx_labor_policy"])
    p.update(over)
    return p


def test_factor_formula_from_the_policy():
    from app.modules.payroll.engine.jurisdictions.mexico import sbc

    f = sbc.integration_factor(_policy(), 3)
    assert f["factor"] == (D("365") + D("15") + D("16") * D("25") / D("100")) / D("365")
    assert f["vacation_days"] == D("16")


def test_factor_is_directional():
    from app.modules.payroll.engine.jurisdictions.mexico import sbc

    base = sbc.integration_factor(_policy(), 3)["factor"]
    assert sbc.integration_factor(_policy(aguinaldo_days="20"), 3)["factor"] > base
    assert sbc.integration_factor(_policy(vacation_premium_pct="50"), 3)["factor"] > base
    assert sbc.integration_factor(_policy(), 1)["factor"] < base          # fewer vacation days in year 1
    assert base > 1


@pytest.mark.parametrize("on,year", [(date(2024, 3, 1), 1), (date(2025, 2, 28), 1), (date(2025, 3, 1), 2),
                                     (date(2026, 2, 28), 2), (date(2026, 3, 1), 3)])
def test_service_year_by_anniversary(on, year):
    from app.modules.payroll.engine.jurisdictions.mexico import sbc

    assert sbc.service_year(date(2024, 3, 1), on) == year


def test_seniority_problems_block():
    from app.modules.payroll.engine.jurisdictions.mexico import sbc

    assert _blocked(sbc.service_year, None, h.PAY_DATE).key == "MX_SENIORITY_DATE_MISSING"
    assert _blocked(sbc.service_year, date(2027, 1, 1), h.PAY_DATE).key == "MX_SENIORITY_DATE_INVALID"


def test_policy_missing_or_incomplete_blocks():
    assert _blocked(_compute, policy={}).key == "MX_LABOR_POLICY_MISSING"
    short = _policy(vacation_policy=[{"serviceYearFrom": 1, "serviceYearTo": 1, "days": 12}])
    assert _blocked(_compute, policy=short).key == "MX_LABOR_POLICY_INCOMPLETE"


def test_fixed_part_and_variable_part():
    r = _compute(accumulator={"total": "6100", "days": "61"})
    c = r["components"]
    assert D(c["variable_daily"]) == D("100")
    assert r["segments"][0]["sbc"] == D("600") * c["factor"] + D("100")
    more = _compute(accumulator={"total": "12200", "days": "61"})
    assert more["segments"][0]["sbc"] > r["segments"][0]["sbc"]


def test_variable_accumulator_must_be_supplied_and_consistent():
    from app.modules.payroll.engine.jurisdictions.mexico import sbc

    assert _blocked(sbc.variable_daily, None).key == "MX_VARIABLE_ACCUMULATOR_MISSING"
    assert _blocked(sbc.variable_daily, {"total": "5", "days": "0"}).key == "MX_VARIABLE_ACCUMULATOR_INVALID"


def test_other_fixed_items_block_until_their_rule_exists():
    lines = [{"code": "SALARY", "kind": "ORDINARY_SALARY", "sbc": "FIXED"},
             {"code": "BONO", "kind": "OTHER", "sbc": "FIXED"}]
    assert _blocked(_compute, lines=lines).key == "MX_SBC_FIXED_RULE_MISSING"
    ok = [{"code": "SALARY", "kind": "ORDINARY_SALARY", "sbc": "FIXED"}, {"code": "X", "kind": "OTHER", "sbc": "EXCLUDED"}]
    assert _compute(lines=ok)["segments"]


def _floor_case(rule):
    rates = copy.deepcopy(h.SYN_RATES)
    if rule is None:
        rates.pop("mx_sbc_min_rule")
    else:
        rates["mx_sbc_min_rule"] = h.txt(rule)
    c = h.content(rates=rates)
    return _compute(salary="70", segments=_segments(c))


def test_floor_rule_q5():
    r = _floor_case("RAISE_TO_ZONE_MIN_WAGE")["segments"][0]
    assert r["sbc"] == D("80") and r["floored"] is True
    assert _blocked(_floor_case, "BLOCK_BELOW_ZONE_MIN_WAGE").key == "MX_SBC_BELOW_MINIMUM"
    assert _blocked(_floor_case, None).key == "MX_SBC_MIN_RULE_MISSING"
    assert _blocked(_floor_case, "WHATEVER").key == "MX_RULE_UNRECOGNISED"


def test_floor_rule_not_needed_above_the_minimum():
    rates = h.without("mx_sbc_min_rule")
    seg = _compute(segments=_segments(h.content(rates=rates)))["segments"][0]
    assert seg["floored"] is False


def test_zone_must_be_resolved():
    assert _blocked(_compute, zone="UNRESOLVED").key == "MX_MIN_WAGE_ZONE_UNRESOLVED"


def test_cap_is_multiple_times_daily_uma():
    seg = _compute(salary="3000")["segments"][0]
    assert seg["capped"] is True and seg["sbc"] == D("20") * D("100") == seg["cap"]
    below = _compute(salary="600")["segments"][0]
    assert below["capped"] is False and below["sbc"] < below["cap"]


def test_january_february_cap_split_per_segment():
    """F1 mechanics: each contribution segment caps with its own UMA."""
    jan, feb = copy.deepcopy(h.SYN_RATES), copy.deepcopy(h.SYN_RATES)
    feb["mx_uma_daily"] = h.amt("110")
    facts = {"start": date(2026, 1, 25), "end": date(2026, 2, 7), "days_paid": 14,
             "segments": [{"start": date(2026, 1, 25), "end": date(2026, 1, 31), "days": 7, "rate_map": jan},
                          {"start": date(2026, 2, 1), "end": date(2026, 2, 7), "days": 7, "rate_map": feb}]}
    segs = _segments(mx_period=facts, mx_payment_period="WEEKLY_7")
    r = _compute(salary="3000", segments=segs, on=date(2026, 2, 7))["segments"]
    assert [s["cap"] for s in r] == [D("2000"), D("2200")]
    assert r[0]["sbc"] < r[1]["sbc"]
