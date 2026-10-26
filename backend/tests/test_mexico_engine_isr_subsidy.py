"""Mexico engine (Phase 5) — ISR withholding (T1 bracket boundaries) and the
employment subsidy (ceiling, divisor, offset, remainder rule Q4, the
January/February UMA switch by pay date — F5 mechanics). SYNTHETIC content."""

import copy
from decimal import Decimal as D

import pytest

from tests import _mx_engine_helpers as h


def _blocked(fn, *a, **k):
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    with pytest.raises(MXBlock) as exc:
        fn(*a, **k)
    return exc.value


def _tariff(period="MONTHLY"):
    return h.content().isr_tariff(period)


# ── ISR (T1) ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("i", range(11))
def test_every_bracket_boundary(i):
    from app.modules.payroll.engine.jurisdictions.mexico import isr

    t = _tariff()
    b = t[i]
    at_lower = isr.withholding(b["lower"], t)
    assert at_lower["isr"] == b["fixed"] and at_lower["bracket"]["lower"] == b["lower"]
    if b["upper"] is not None:
        at_upper = isr.withholding(b["upper"], t)
        assert at_upper["bracket"]["lower"] == b["lower"]
        assert at_upper["isr"] == b["fixed"] + (b["upper"] - b["lower"]) * b["rate"]
        nxt = isr.withholding(t[i + 1]["lower"], t)
        assert nxt["bracket"]["lower"] == t[i + 1]["lower"] and nxt["isr"] == t[i + 1]["fixed"]


def test_isr_grows_with_the_base():
    from app.modules.payroll.engine.jurisdictions.mexico import isr

    t = _tariff()
    values = [isr.withholding(D(x), t)["isr"] for x in ("1", "999", "1500", "4000", "9999", "10000.01", "50000")]
    assert values == sorted(values) and len(set(values)) == len(values)


def test_zero_base_and_below_the_tariff():
    from app.modules.payroll.engine.jurisdictions.mexico import isr

    t = _tariff()
    assert isr.withholding(D("0"), t)["isr"] == 0
    assert _blocked(isr.withholding, D("0.001"), t).key == "MX_ISR_BELOW_TARIFF"
    assert _blocked(isr.withholding, D("-1"), t).key == "MX_EARNING_INVALID"


def test_a_tariff_without_an_open_top_bracket_blocks_above_it():
    from app.modules.payroll.engine.jurisdictions.mexico import isr

    t = copy.deepcopy(_tariff())
    t[-1]["upper"] = D("11000")
    assert _blocked(isr.withholding, D("11000.01"), t).key == "MX_CONTENT_INVALID"


def test_each_period_uses_its_own_tariff():
    slabs = [s for s in h.base_slabs() if not (s["rule_type"] == "MX_ISR_TARIFF" and s["filing_status"] == "WEEKLY_7")]
    c = h.content(slabs=slabs)
    assert c.isr_tariff("MONTHLY")
    with pytest.raises(Exception) as exc:
        c.isr_tariff("WEEKLY_7")
    assert exc.value.key == "MX_CONTENT_MISSING"


# ── Subsidy ──────────────────────────────────────────────────────────────────

def _sub(taxable, tariff="MONTHLY", days=30, mtd=None, rates=None):
    from app.modules.payroll.engine.jurisdictions.mexico import subsidy

    return subsidy.subsidy(h.content(rates=rates), tariff, D(days), D(taxable), mtd)


def test_subsidy_ceiling_plus_minus_one_cent():
    assert _sub("8000")["eligible"] is True
    assert _sub("7999.99")["eligible"] is True
    off = _sub("8000.01")
    assert off["eligible"] is False and off["amount"] == 0


def test_monthly_amount_is_rate_times_monthly_uma():
    assert _sub("5000")["amount"] == D("0.10") * D("3000")


def test_shorter_period_uses_the_days_divisor():
    s = _sub("2000", tariff="QUINCENAL_15", days=15, mtd={"taxable": 0, "subsidy_applied": 0})
    assert s["amount"] == D("300") / D("30") * D("15")
    w = _sub("2000", tariff="WEEKLY_7", days=7, mtd={"taxable": 0, "subsidy_applied": 0})
    assert w["amount"] < s["amount"]                       # fewer days ⇒ less subsidy


def test_shorter_period_needs_month_to_date_and_counts_it():
    assert _blocked(_sub, "2000", tariff="QUINCENAL_15", days=15).key == "MX_MONTH_TO_DATE_MISSING"
    over = _sub("2000", tariff="QUINCENAL_15", days=15, mtd={"taxable": "6000.01", "subsidy_applied": 0})
    assert over["eligible"] is False


def test_month_cap_without_a_rule_blocks():
    e = _blocked(_sub, "2000", tariff="QUINCENAL_15", days=15, mtd={"taxable": 0, "subsidy_applied": "200"})
    assert e.key == "MX_SUBSIDY_MONTHLY_CAP_RULE_MISSING"


def test_month_cap_rule_pays_only_what_is_left_of_the_monthly_amount():
    """W3-1 (S3 Art. Segundo para 4): SYNTHETIC monthly amount 300; 200 already
    applied this month; this fortnight's 150 is cut to the 100 left; nothing
    is left once the month has had 300."""
    rates = copy.deepcopy(h.SYN_RATES)
    rates["mx_subsidy_monthly_cap_rule"] = h.txt("CAP_AT_MONTHLY_AMOUNT")
    s = _sub("2000", tariff="QUINCENAL_15", days=15, mtd={"taxable": 0, "subsidy_applied": "200"}, rates=rates)
    assert (s["amount"], s["capped"]) == (D("100"), True)
    full = _sub("2000", tariff="QUINCENAL_15", days=15, mtd={"taxable": 0, "subsidy_applied": "300"}, rates=rates)
    assert full["amount"] == 0 and full["capped"] is True
    under = _sub("2000", tariff="QUINCENAL_15", days=15, mtd={"taxable": 0, "subsidy_applied": "0"}, rates=rates)
    assert (under["amount"], under["capped"]) == (D("150"), False)
    rates["mx_subsidy_monthly_cap_rule"] = h.txt("SOMETHING_ELSE")
    e = _blocked(_sub, "2000", tariff="QUINCENAL_15", days=15, mtd={"taxable": 0, "subsidy_applied": "200"}, rates=rates)
    assert e.key == "MX_RULE_UNRECOGNISED"


def test_january_vs_february_uma_is_chosen_by_the_pay_date_rows():
    """F5 mechanics: the resolver hands the rows in force on the pay date;
    a higher monthly UMA (the February row) gives a higher subsidy."""
    feb = copy.deepcopy(h.SYN_RATES)
    feb["mx_uma_monthly"] = h.amt("3300")
    jan_amount, feb_amount = _sub("5000")["amount"], _sub("5000", rates=feb)["amount"]
    assert feb_amount > jan_amount and feb_amount == D("330.0")


def test_offset_against_isr():
    from app.modules.payroll.engine.jurisdictions.mexico import subsidy

    c = h.content()
    o = subsidy.offset(c, D("500"), D("300"))
    assert (o["withholding"], o["subsidy_applied"], o["remainder"]) == (D("200"), D("300"), D("0"))
    assert subsidy.offset(c, D("300"), D("300"))["withholding"] == 0


def test_remainder_rule_q4():
    from app.modules.payroll.engine.jurisdictions.mexico import subsidy

    assert _blocked(subsidy.offset, h.content(), D("100"), D("300")).key == "MX_SUBSIDY_REMAINDER_RULE_MISSING"
    rates = copy.deepcopy(h.SYN_RATES)
    rates["mx_subsidy_remainder_rule"] = h.txt("NOT_PAYABLE")
    o = subsidy.offset(h.content(rates=rates), D("100"), D("300"))
    assert (o["withholding"], o["subsidy_applied"], o["remainder"]) == (D("0"), D("100"), D("200"))
    rates["mx_subsidy_remainder_rule"] = h.txt("CASH_PAYABLE")
    assert _blocked(subsidy.offset, h.content(rates=rates), D("100"), D("300")).key == \
        "MX_SUBSIDY_CASH_REMAINDER_UNSUPPORTED"
    rates["mx_subsidy_remainder_rule"] = h.txt("SOMETHING")
    assert _blocked(subsidy.offset, h.content(rates=rates), D("100"), D("300")).key == "MX_RULE_UNRECOGNISED"


def test_end_to_end_low_salary_subsidy_reduces_withholding():
    from app.modules.payroll.engine.countries import mexico

    rates = copy.deepcopy(h.SYN_RATES)
    rates["mx_subsidy_remainder_rule"] = h.txt("NOT_PAYABLE")
    profile = dict(h.facts()["mx_profile"], mx_daily_salary=D("200"))
    out = mexico.calculate(h.ctx(rates=rates, mx_profile=profile,
                                 mx_earnings=[{"code": "SALARY", "kind": "ORDINARY_SALARY", "amount": D("3000")}]))
    r = out["mx_result"]
    assert D(r["isr"]) == D("60.00") and r["subsidy"]["eligible"] is True and D(r["subsidy"]["amount"]) == D("150.00")
    assert out["tds"] == 0 and r["subsidy"]["remainder_rule"] == "NOT_PAYABLE"
    # Same case without the remainder rule: BLOCK, never a guess.
    with pytest.raises(Exception) as exc:
        mexico.calculate(h.ctx(mx_profile=profile,
                               mx_earnings=[{"code": "SALARY", "kind": "ORDINARY_SALARY", "amount": D("3000")}]))
    assert exc.value.key == "MX_SUBSIDY_REMAINDER_RULE_MISSING" and exc.value.organization_id == 11
