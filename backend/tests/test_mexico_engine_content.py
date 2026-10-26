"""Mexico engine (Phase 5) — content accessor, period, rounding gate and the
value-free Phase 5 content keys. SYNTHETIC content only (_mx_engine_helpers)."""

import copy
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from tests import _mx_engine_helpers as h


def _blocked(fn, *a, **k):
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    with pytest.raises(MXBlock) as exc:
        fn(*a, **k)
    return exc.value


# ── content.py ───────────────────────────────────────────────────────────────

def test_missing_scalar_blocks_never_defaults():
    c = h.content(rates=h.without("mx_uma_daily"))
    assert _blocked(c.amount, "mx_uma_daily").key == "MX_CONTENT_MISSING"
    assert not c.has("mx_uma_daily")


def test_pct_reads_the_keys_own_side_and_divides_by_100():
    c = h.content()
    assert c.pct("mx_imss_iv_ee_pct") == D("0.007")
    assert c.pct("mx_imss_iv_er_pct") == D("0.016")
    rates = copy.deepcopy(h.SYN_RATES)
    rates["mx_imss_iv_er_pct"] = h.ee("1.6")          # value on the wrong side
    assert _blocked(h.content(rates=rates).pct, "mx_imss_iv_er_pct").key == "MX_CONTENT_MISSING"
    assert _blocked(c.pct, "mx_uma_daily").key == "MX_CONTENT_INVALID"


def test_text_and_non_numeric_rows():
    c = h.content()
    assert c.text("mx_rounding_rule") == "HALF_UP:0.01"
    rates = copy.deepcopy(h.SYN_RATES)
    rates["mx_uma_daily"] = h.amt("abc")
    assert _blocked(h.content(rates=rates).amount, "mx_uma_daily").key == "MX_CONTENT_INVALID"


def test_isr_tariff_is_sorted_and_per_period():
    c = h.content(slabs=list(reversed(h.base_slabs())))
    t = c.isr_tariff("MONTHLY")
    assert [b["lower"] for b in t] == sorted(b["lower"] for b in t) and len(t) == 11
    assert t[0]["rate"] == D("0.01") and t[-1]["upper"] is None
    no_monthly = [s for s in h.base_slabs() if s.get("filing_status") != "MONTHLY"]
    assert _blocked(h.content(slabs=no_monthly).isr_tariff, "MONTHLY").key == "MX_CONTENT_MISSING"


def test_min_wage_duplicate_and_missing():
    c = h.content()
    assert c.min_wage("GENERAL") == D("80") and c.min_wage("ZLFN") == D("120")
    assert _blocked(c.min_wage, "PROF_X").key == "MX_CONTENT_MISSING"
    dup = h.base_slabs() + [dict(s) for s in h.base_slabs() if s.get("filing_status") == "GENERAL"]
    assert _blocked(h.content(slabs=dup).min_wage, "GENERAL").key == "MX_CONTENT_INVALID"


def test_ceav_band_units_are_validated():
    bands = h.content().ceav_bands()
    assert [b["lower"] for b in bands] == [D("1.00"), D("1.01"), D("1.51"), D("2.01")]
    assert bands[-1]["upper"] is None and bands[0]["lower_unit"] == "SM"
    bad = [dict(s, assessment_basis="XX/UMA") if s.get("rule_type") == "MX_CEAV_BAND" else s for s in h.base_slabs()]
    assert _blocked(h.content(slabs=bad).ceav_bands).key == "MX_CONTENT_INVALID"


def test_workweek_and_vacation_days():
    c = h.content()
    assert c.workweek_max_hours() == D("50")
    assert (c.vacation_days(1), c.vacation_days(2), c.vacation_days(30)) == (D("10"), D("12"), D("14"))
    no_vac = [s for s in h.base_slabs() if s["rule_type"] != "MX_VACATION_DAYS"]
    assert _blocked(h.content(slabs=no_vac).vacation_days, 1).key == "MX_CONTENT_MISSING"
    no_week = [s for s in h.base_slabs() if s["rule_type"] != "MX_WORKWEEK"]
    assert _blocked(h.content(slabs=no_week).workweek_max_hours).key == "MX_CONTENT_MISSING"


# ── rounding.py (Q2) ─────────────────────────────────────────────────────────

def test_rounding_rule_missing_blocks_every_amount():
    from app.modules.payroll.engine.jurisdictions.mexico import rounding

    assert _blocked(rounding.rounder, h.content(rates=h.without("mx_rounding_rule"))).key == "MX_ROUNDING_RULE_MISSING"


@pytest.mark.parametrize("text", ["HALF_UP", "BANKERS:0.01", "HALF_UP:0", "HALF_UP:-1", "HALF_UP:x", ""])
def test_rounding_rule_invalid(text):
    from app.modules.payroll.engine.jurisdictions.mexico import rounding

    assert _blocked(rounding.parse, text).key == "MX_ROUNDING_RULE_INVALID"


def test_rounding_mode_and_quantum_come_from_the_rule():
    from app.modules.payroll.engine.jurisdictions.mexico import rounding

    x = D("10.125")
    assert rounding.parse("HALF_UP:0.01")(x) == D("10.13")
    assert rounding.parse("DOWN:0.01")(x) == D("10.12")
    assert rounding.parse("HALF_EVEN:0.01")(x) == D("10.12")
    assert rounding.parse("HALF_UP:1")(x) == D("10")
    assert rounding.parse("DOWN:0.01")(x) < rounding.parse("UP:0.01")(x)


# ── period.py (Q3, Q6, MX-021) ───────────────────────────────────────────────

def _period(**over):
    from app.modules.payroll.engine.jurisdictions.mexico import period

    c = h.ctx(**over)
    return period.resolve(c, h.content())


@pytest.mark.parametrize("p", ["CATORCENAL_14", "OTHER", "", None])
def test_period_without_an_art96_tariff_blocks(p):
    assert _blocked(_period, mx_payment_period=p).key == "MX_PERIOD_UNSUPPORTED"


@pytest.mark.parametrize("field", ["absence_days", "incapacity_days"])
def test_absence_and_incapacity_block(field):
    facts = {"start": date(2026, 6, 1), "end": date(2026, 6, 15), "days_paid": 15, field: 1}
    assert _blocked(_period, mx_period=facts).key == "MX_ABSENCE_RULES_MISSING"


def test_single_segment_uses_the_pay_date_rows():
    p = _period()
    assert len(p.segments) == 1 and p.contribution_days == D("15") and p.tariff == "QUINCENAL_15"


def test_multi_segment_needs_each_segments_own_rows():
    facts = {"start": date(2026, 1, 25), "end": date(2026, 2, 7), "days_paid": 14,
             "segments": [{"start": date(2026, 1, 25), "end": date(2026, 1, 31), "days": 7},
                          {"start": date(2026, 2, 1), "end": date(2026, 2, 7), "days": 7}]}
    assert _blocked(_period, mx_period=facts, mx_payment_period="WEEKLY_7").key == "MX_SEGMENT_CONTENT_MISSING"
    for seg in facts["segments"]:
        seg["rate_map"] = copy.deepcopy(h.SYN_RATES)
    p = _period(mx_period=facts, mx_payment_period="WEEKLY_7")
    assert [s.days for s in p.segments] == [D("7"), D("7")] and p.segments[0].content is not p.segments[1].content


def test_overlapping_or_outside_segments_block():
    seg = {"rate_map": h.SYN_RATES}
    overlap = {"start": date(2026, 6, 1), "end": date(2026, 6, 15), "days_paid": 15,
               "segments": [dict(seg, start=date(2026, 6, 1), end=date(2026, 6, 8), days=8),
                            dict(seg, start=date(2026, 6, 8), end=date(2026, 6, 15), days=8)]}
    assert _blocked(_period, mx_period=overlap).key == "MX_PERIOD_INVALID"
    outside = dict(overlap, segments=[dict(seg, start=date(2026, 5, 30), end=date(2026, 6, 15), days=15)])
    assert _blocked(_period, mx_period=outside).key == "MX_PERIOD_INVALID"


def test_pay_date_is_required():
    from app.modules.payroll.engine.jurisdictions.mexico import period

    assert _blocked(period.pay_date, h.ctx(mx_payroll_date=None)).key == "MX_PAY_DATE_MISSING"


# ── Phase 5 value-free content keys (Q2, Q4, Q5, Q7, Q11) ────────────────────

def test_phase5_keys_are_named_value_free_and_tables_stay_empty():
    from app.modules.payroll.engine.countries import mexico_content as c

    for key in ("mx_rounding_rule", "mx_sbc_min_rule", "mx_subsidy_remainder_rule", "mx_infonavit_percentage_basis",
                "mx_infonavit_fixed_amount_basis"):
        assert c.MX_PARAMETER_KEYS[key][0] == "text" and c.MX_PARAMETER_KEYS[key][2] == "national"
    for key in c.MX_PER_CASE_KEYS:
        assert c.MX_PARAMETER_KEYS[key][0] == "amount"
    assert set(c.MX_REQUIRED_TEXT_KEYS) == {"mx_rounding_rule", "mx_sbc_min_rule"}
    # Batches 1-2 transcribed the subsidy remainder rule and the overtime tiers; the
    # rounding rule, the SBC floor rule and the INFONAVIT credit bases have no row yet
    present = {r.key for r in c.MX_SCALAR_CONTENT}
    assert {"mx_subsidy_remainder_rule", *c.MX_PER_CASE_KEYS} <= present
    assert not (set(c.MX_REQUIRED_TEXT_KEYS) | {"mx_infonavit_percentage_basis",
                                                "mx_infonavit_fixed_amount_basis"}) & present


def test_activation_content_check_requires_rounding_and_sbc_floor(monkeypatch):
    from app.modules.payroll import mexico_service
    from app.modules.payroll.engine.countries import mexico_content as c

    pack = SimpleNamespace(effective_from=date(2026, 1, 1), effective_to=date(2026, 12, 31), jurisdiction_state=None)
    rows = []
    for key, (kind, _l, scope) in c.MX_PARAMETER_KEYS.items():
        if scope != "national" or kind == "text" or key in c.MX_PER_CASE_KEYS:
            continue
        rows.append(c.ScalarRow(key, "1" if kind == "employee_pct" else None, "1" if kind == "employer_pct" else None,
                                "1" if kind == "amount" else None, None, None, None, "S6", "SYNTHETIC"))
    monkeypatch.setattr(c, "MX_SCALAR_CONTENT", tuple(rows))
    ok, why = mexico_service._content_check(pack, [], [])
    assert not ok and "mx_rounding_rule" in why and "mx_sbc_min_rule" in why
    # The per-case overtime keys are NOT required for activation.
    assert not any(k in why for k in c.MX_PER_CASE_KEYS)
