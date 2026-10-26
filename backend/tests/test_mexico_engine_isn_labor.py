"""Mexico engine (Phase 5) — state ISN (base by classification + state
override, Active pack only, federal bases untouched — F7 mechanics) and the
labour checks: minimum-wage geography (F4 mechanics), workweek by the pay
date's rows, overtime only from approved hours (MX-049), Sunday premium,
rest days. SYNTHETIC content."""

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


def _calc(**over):
    from app.modules.payroll.engine.countries import mexico

    return mexico.calculate(h.ctx(**over))


# ── ISN ──────────────────────────────────────────────────────────────────────

def _line(code, isn):
    return {"code": code, "amount": D("1000"), "isn": isn}


def test_isn_base_is_the_included_lines_at_the_state_rate():
    from app.modules.payroll.engine.jurisdictions.mexico import isn

    r = isn.employer([_line("A", True), _line("B", False), _line("C", True)], "CDMX", h.facts()["mx_isn_state_pack"])
    assert r["base"] == D("2000") and r["amount"] == D("2000") * D("0.03") and r["codes"] == ["A", "C"]


def test_state_override_beats_the_default():
    from app.modules.payroll.engine.jurisdictions.mexico import classification as cl

    assert cl.isn_included(h.classification(isn_default_included=False, isn_state_overrides={"CDMX": True}), "CDMX")
    assert not cl.isn_included(h.classification(isn_state_overrides={"CDMX": False}), "CDMX")
    assert cl.isn_included(h.classification(isn_state_overrides={"JAL": False}), "CDMX")


def test_isn_pack_must_be_in_scope_and_active():
    from app.modules.payroll.engine.jurisdictions.mexico import isn

    pack = h.facts()["mx_isn_state_pack"]
    assert _blocked(isn.employer, [], "JAL", pack).key == "MX_STATE_UNSUPPORTED"
    assert _blocked(isn.employer, [], None, pack).key == "MX_STATE_UNSUPPORTED"
    assert _blocked(isn.employer, [], "CDMX", None).key == "MX_STATE_UNSUPPORTED"
    assert _blocked(isn.employer, [], "CDMX", dict(pack, status="Draft")).key == "MX_ISN_PACK_NOT_ACTIVE"
    assert _blocked(isn.employer, [], "CDMX", dict(pack, rate_map={})).key == "MX_CONTENT_MISSING"


def test_isn_never_changes_a_federal_base():
    """F7 mechanics: the same payslip with an ISN-excluded classification
    has identical ISR, SBC and IMSS — only the ISN differs."""
    incl = _calc()["mx_result"]
    excl = _calc(mx_classifications={"SALARY": h.classification(isn_default_included=False)})["mx_result"]
    for key in ("isr", "isr_withheld", "imss_employee", "imss_employer", "infonavit_employer", "sbc"):
        assert incl[key] == excl[key], key
    assert D(incl["isn"]["amount"]) > 0 and D(excl["isn"]["amount"]) == 0


# ── Minimum wage (F4 mechanics) ──────────────────────────────────────────────

def test_minimum_wage_by_zone():
    from app.modules.payroll.engine.jurisdictions.mexico import labor

    c = h.content()
    assert labor.minimum_wage(c, D("100"), "GENERAL")["minimum"] == D("80")
    assert _blocked(labor.minimum_wage, c, D("100"), "ZLFN").key == "MX_BELOW_MINIMUM_WAGE"
    assert labor.minimum_wage(c, D("120"), "ZLFN")["applied"] == "ZLFN"
    assert _blocked(labor.minimum_wage, c, D("100"), "UNRESOLVED").key == "MX_MIN_WAGE_ZONE_UNRESOLVED"


def test_professional_minimum_overrides_the_zone():
    from app.modules.payroll.engine.jurisdictions.mexico import labor

    slabs = h.base_slabs() + [{"rule_type": "MX_MIN_WAGE", "filing_status": "PROF_A", "flat_amount": "150",
                               "assessment_basis": "PROFESSION", "jurisdiction_state": None}]
    c = h.content(slabs=slabs)
    assert _blocked(labor.minimum_wage, c, D("100"), "GENERAL", "PROF_A").key == "MX_BELOW_MINIMUM_WAGE"
    assert labor.minimum_wage(c, D("150"), "GENERAL", "PROF_A")["applied"] == "PROF_A"
    assert _blocked(labor.minimum_wage, h.content(), D("500"), "GENERAL", "PROF_A").key == "MX_CONTENT_MISSING"


# ── Workweek (MX-048/MX-050) ─────────────────────────────────────────────────

def _week_rows(hours):
    return [dict(s, flat_amount=hours) if s["rule_type"] == "MX_WORKWEEK" else s for s in h.base_slabs()]


def test_workweek_limit_comes_from_the_pay_dates_rows():
    """2026 → 2027: the resolver hands each pay date its own row; a policy
    within the 2026 limit is refused against a lower later limit."""
    from app.modules.payroll.engine.jurisdictions.mexico import labor

    policy = h.facts()["mx_labor_policy"]
    assert labor.workweek(h.content(slabs=_week_rows("50")), policy)["statutory_max"] == D("50")
    assert _blocked(labor.workweek, h.content(slabs=_week_rows("38")), policy).key == "MX_WORKWEEK_ABOVE_MAXIMUM"
    out_2026 = _calc()
    with pytest.raises(Exception) as exc:
        _calc(slabs=_week_rows("38"), mx_payroll_date=date(2027, 1, 15))
    assert out_2026["mx_result"]["labor"]["workweek"]["statutory_max"] == "50"
    assert exc.value.key == "MX_WORKWEEK_ABOVE_MAXIMUM"


# ── Overtime only from approved hours (MX-049, Q9) ───────────────────────────

OT_RATES = dict(copy.deepcopy(h.SYN_RATES), mx_overtime_double_weekly_max_hours=h.amt("9"),
                mx_overtime_double_multiplier=h.amt("2"), mx_overtime_triple_multiplier=h.amt("3"))


def _hours(*weeks, **over):
    out = {"weeks": [{"overtime_hours": w} for w in weeks], "hourly_rate": "75", "overtime_code": "HE",
           "sundays_worked": 0, "sunday_premium_code": "PD", "holiday_days": 0}
    out.update(over)
    return out


def _ot(hours, rates=OT_RATES):
    from app.modules.payroll.engine.jurisdictions.mexico import labor

    return labor.hour_lines(h.content(rates=rates), hours, h.facts()["mx_labor_policy"], D("600"))


def test_overtime_tiers():
    r = _ot(_hours(12))
    assert r["lines"] == [{"code": "HE", "kind": "OVERTIME", "amount": D("75") * (9 * 2 + 3 * 3)}]
    assert r["overtime"][0]["first_tier_hours"] == D("9") and r["overtime"][0]["second_tier_hours"] == D("3")
    two = _ot(_hours(4, 4))
    assert two["lines"][0]["amount"] == D("75") * 8 * 2          # the tier limit is per week


def test_hours_past_the_first_tier_cost_more():
    nine, ten, eleven = (_ot(_hours(x))["lines"][0]["amount"] for x in (9, 10, 11))
    assert (eleven - ten) == (ten - nine) and (ten - nine) > nine / 9


def test_no_hours_no_overtime():
    assert _ot(None)["lines"] == [] and _ot(_hours(0))["lines"] == []


def test_overtime_without_tier_content_or_rate_blocks():
    assert _blocked(_ot, _hours(5), h.SYN_RATES).key == "MX_OVERTIME_RULES_MISSING"
    assert _blocked(_ot, _hours(5, hourly_rate="0")).key == "MX_HOURS_INVALID"
    assert _blocked(_ot, _hours(5, overtime_code=None)).key == "MX_HOURS_INVALID"


def test_supplied_overtime_line_is_refused():
    earnings = [{"code": "SALARY", "kind": "ORDINARY_SALARY", "amount": D("9000")},
                {"code": "HE", "kind": "OVERTIME", "amount": D("100")}]
    with pytest.raises(Exception) as exc:
        _calc(mx_earnings=earnings)
    assert "MX_OVERTIME_NOT_FROM_HOURS" in [k for k, _ in exc.value.reasons]


def test_overtime_end_to_end_needs_its_classification_and_the_full_gross():
    cls = {"SALARY": h.classification(), "HE": h.classification("HE", sbc_treatment="VARIABLE")}
    with pytest.raises(Exception) as exc:
        _calc(rates=copy.deepcopy(OT_RATES), mx_hours=_hours(12))
    assert exc.value.key == "MX_CLASSIFICATION_MISSING"
    with pytest.raises(Exception) as exc:
        _calc(rates=copy.deepcopy(OT_RATES), mx_hours=_hours(12), mx_classifications=cls)
    assert exc.value.key == "MX_GROSS_MISMATCH"
    r = _calc(rates=copy.deepcopy(OT_RATES), mx_hours=_hours(12), mx_classifications=cls, gross=D("9000") + D("2025"))
    assert D(r["mx_result"]["gross"]) == D("11025") and r["mx_result"]["labor"]["overtime"][0]["hours"] == "12"


# ── Sunday premium and rest days ─────────────────────────────────────────────

def test_sunday_premium_from_the_policy_not_below_the_floor():
    r = _ot(_hours(sundays_worked=2))
    assert r["lines"] == [{"code": "PD", "kind": "SUNDAY_PREMIUM", "amount": D("600") * D("0.25") * 2}]
    from app.modules.payroll.engine.jurisdictions.mexico import labor

    low = dict(h.facts()["mx_labor_policy"], sunday_premium_pct="15")
    e = _blocked(labor.hour_lines, h.content(), _hours(sundays_worked=1), low, D("600"))
    assert e.key == "MX_LABOR_POLICY_BELOW_FLOOR"
    assert _blocked(_ot, _hours(sundays_worked=1, sunday_premium_code=None)).key == "MX_HOURS_INVALID"


def test_rest_day_work_blocks():
    assert _blocked(_ot, _hours(holiday_days=1)).key == "MX_REST_DAY_CONTENT_MISSING"


def test_rest_day_work_pays_the_multiplier_on_top_of_the_daily_salary():
    """W3-2 (LFT Arts. 73, 75): SYNTHETIC multiplier 2, daily salary 600 —
    2 rest days worked pay 2 x 600 x 2 = 2,400 on a REST_DAY_WORK line."""
    from app.modules.payroll.engine.jurisdictions.mexico.classification import REST_DAY_WORK

    rates = dict(OT_RATES, mx_rest_day_work_multiplier=h.amt("2"))
    out = _ot(_hours(holiday_days=2, rest_day_code="DESC"), rates)
    assert out["rest_day"] == {"days": D("2"), "multiplier": D("2"), "amount": D("2400")}
    assert {"code": "DESC", "kind": REST_DAY_WORK, "amount": D("2400")} in out["lines"]
    assert _blocked(_ot, _hours(holiday_days=1), rates).key == "MX_HOURS_INVALID"        # no earning code
    assert _ot(_hours(rest_day_code="DESC"), rates)["rest_day"] is None                  # none worked
