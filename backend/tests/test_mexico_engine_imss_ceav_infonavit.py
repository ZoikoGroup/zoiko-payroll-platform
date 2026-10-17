"""Mexico engine (Phase 5) — every IMSS branch separately (MX-023), the
registration's risk premium (MX-024), CEAV band boundaries (T4) and the
[PENDING G2] lowest band, INFONAVIT employer % and notice-only credits
(MX-031, Q7). SYNTHETIC content."""

import copy
from datetime import date
from decimal import Decimal as D

import pytest

from tests import _mx_engine_helpers as h

START, END = date(2026, 6, 1), date(2026, 6, 15)


def _blocked(fn, *a, **k):
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    with pytest.raises(MXBlock) as exc:
        fn(*a, **k)
    return exc.value


def _seg(sbc="500", days="15", rates=None, uma="100"):
    return {"start": START, "end": END, "days": D(days), "sbc": D(sbc), "uma_daily": D(uma),
            "content": h.content(rates=rates)}


def _premium(**over):
    p = copy.deepcopy(h.facts()["mx_risk_premium"])
    p.update(over)
    return p


# ── IMSS branches ────────────────────────────────────────────────────────────

def _lines(sbc="500"):
    from app.modules.payroll.engine.jurisdictions.mexico import imss

    return {(l["branch"], l["side"]): l for l in imss.contributions([_seg(sbc)], D("0.5"))["lines"]}


def test_every_branch_is_its_own_line_with_base_times_rate():
    from app.modules.payroll.engine.jurisdictions.mexico import imss

    lines = _lines()
    assert len(lines) == len(imss.BRANCHES) + 1
    assert lines[("EM_FIXED_QUOTA", "employer")]["amount"] == D("100") * 15 * D("0.15")
    assert lines[("EM_EXCESS", "employer")]["amount"] == D("100") * 15 * D("0.012")
    assert lines[("EM_EXCESS", "employee")]["amount"] == D("100") * 15 * D("0.005")
    for branch, side, pct in (("EM_CASH", "employer", "0.008"), ("EM_CASH", "employee", "0.003"),
                              ("EM_PENSIONER", "employer", "0.011"), ("EM_PENSIONER", "employee", "0.004"),
                              ("IV", "employer", "0.016"), ("IV", "employee", "0.007"),
                              ("GUARDERIAS", "employer", "0.012"), ("RETIRO", "employer", "0.025"),
                              ("CEAV", "employee", "0.011")):
        assert lines[(branch, side)]["amount"] == D("500") * 15 * D(pct), branch
    assert lines[("RIESGOS_TRABAJO", "employer")]["amount"] == D("500") * 15 * D("0.005")


def test_excess_is_zero_below_the_threshold_and_grows_above_it():
    assert _lines("300")[("EM_EXCESS", "employee")]["amount"] == 0
    assert _lines("400")[("EM_EXCESS", "employee")]["amount"] == 0
    assert _lines("600")[("EM_EXCESS", "employee")]["amount"] > _lines("500")[("EM_EXCESS", "employee")]["amount"]


def test_employee_and_employer_totals():
    from app.modules.payroll.engine.jurisdictions.mexico import imss

    r = imss.contributions([_seg()], D("0.5"))
    assert r["employee"] == sum(l["amount"] for l in r["lines"] if l["side"] == "employee")
    assert r["employer"] == sum(l["amount"] for l in r["lines"] if l["side"] == "employer")


def test_a_missing_branch_row_blocks():
    from app.modules.payroll.engine.jurisdictions.mexico import imss

    e = _blocked(imss.contributions, [_seg(rates=h.without("mx_imss_guarderias_er_pct"))], D("0.5"))
    assert e.key == "MX_CONTENT_MISSING" and "guarderias" in e.reason


def test_risk_premium_from_the_registration_only():
    from app.modules.payroll.engine.jurisdictions.mexico import imss

    reg = {"id": 1, "status": "ACTIVE"}
    assert imss.risk_premium_rate(_premium(), reg, [_seg()]) == D("0.5")
    assert _blocked(imss.risk_premium_rate, None, reg, [_seg()]).key == "MX_NO_RISK_PREMIUM"
    assert _blocked(imss.risk_premium_rate, _premium(status="DRAFT"), reg, [_seg()]).key == "MX_NO_RISK_PREMIUM"
    assert _blocked(imss.risk_premium_rate, _premium(registration_id=2), reg, [_seg()]).key == "MX_NO_RISK_PREMIUM"
    late = _premium(period_from=date(2026, 6, 10))
    assert _blocked(imss.risk_premium_rate, late, reg, [_seg()]).key == "MX_NO_RISK_PREMIUM"


# ── CEAV (T4) ────────────────────────────────────────────────────────────────

def _band(sbc, zone="GENERAL", rates=None):
    from app.modules.payroll.engine.jurisdictions.mexico import ceav

    return ceav.employer([_seg(sbc, rates=rates)], zone)["lines"][0]


@pytest.mark.parametrize("sbc,label", [("80", "1.00SM"), ("101", "1.01UMA"), ("150", "1.01UMA"), ("151", "1.51UMA"),
                                       ("200", "1.51UMA"), ("201", "2.01UMA"), ("5000", "2.01UMA")])
def test_band_boundaries(sbc, label):
    line = _band(sbc)
    assert line["band"] == label and line["amount"] == D(sbc) * 15 * line["rate_pct"] / 100


@pytest.mark.parametrize("sbc", ["90", "150.5", "200.99"])
def test_sbc_between_bands_blocks(sbc):
    assert _blocked(_band, sbc).key == "MX_CEAV_BAND_GAP"


def test_higher_band_has_the_higher_synthetic_rate():
    assert _band("201")["rate_pct"] > _band("151")["rate_pct"] > _band("101")["rate_pct"]


def test_zlfn_in_the_lowest_band_blocks_pending_g2():
    assert _blocked(_band, "80", zone="ZLFN").key == "MX_CEAV_LOWEST_BAND_PENDING_G2"
    assert _band("201", zone="ZLFN")["band"] == "2.01UMA"


def test_lowest_band_reference_is_content():
    e = _blocked(_band, "80", rates=h.without("mx_ceav_lowest_band_min_wage_ref"))
    assert e.key == "MX_CONTENT_MISSING"


# ── INFONAVIT ────────────────────────────────────────────────────────────────

def test_employer_housing_contribution():
    from app.modules.payroll.engine.jurisdictions.mexico import infonavit

    assert infonavit.employer([_seg()])["employer"] == D("500") * 15 * D("0.04")


def _notice(**over):
    n = {"id": 9, "credit_number": "C1", "notice_type": "RETENCION", "discount_method": "PERCENTAGE",
         "discount_value": "20", "effective_from": date(2026, 1, 1), "effective_to": None, "status": "RECORDED",
         "authority_reference": "SYNTHETIC"}
    n.update(over)
    return n


def _credits(notices, rules=None):
    from app.modules.payroll.engine.jurisdictions.mexico import infonavit

    rates = copy.deepcopy(h.SYN_RATES)
    for k, v in (rules or {}).items():
        rates[k] = h.txt(v)
    return infonavit.credits(notices, START, END, [_seg()], h.content(rates=rates))


PCT_RULE = {"mx_infonavit_percentage_basis": "SBC_TIMES_DAYS"}
FIX_RULE = {"mx_infonavit_fixed_amount_basis": "DAILY_TIMES_DAYS"}


def test_no_notice_no_deduction():
    assert _credits([], PCT_RULE)["employee"] == 0


def test_percentage_and_fixed_amount_with_their_basis_rules():
    assert _credits([_notice()], PCT_RULE)["employee"] == D("500") * 15 * D("0.20")
    fixed = _notice(discount_method="FIXED_AMOUNT", discount_value="10")
    assert _credits([fixed], FIX_RULE)["employee"] == D("150")


def test_methods_without_a_rule_block_q7():
    assert _blocked(_credits, [_notice()]).key == "MX_INFONAVIT_METHOD_UNSUPPORTED"
    for method in ("VSM", "UMA_FACTOR", None):
        assert _blocked(_credits, [_notice(discount_method=method)], PCT_RULE).key == "MX_INFONAVIT_METHOD_UNSUPPORTED"
    assert _blocked(_credits, [_notice()], {"mx_infonavit_percentage_basis": "X"}).key == "MX_RULE_UNRECOGNISED"


def test_notice_windows():
    assert _credits([_notice(effective_to=date(2026, 5, 31))], PCT_RULE)["employee"] == 0   # ended before
    assert _blocked(_credits, [_notice(effective_from=date(2026, 6, 5))], PCT_RULE).key == "MX_INFONAVIT_PARTIAL_PERIOD"
    two = [_notice(effective_to=date(2026, 6, 7), status="SUPERSEDED"),
           _notice(id=10, notice_type="MODIFICACION", effective_from=date(2026, 6, 8))]
    assert _blocked(_credits, two, PCT_RULE).key == "MX_INFONAVIT_PARTIAL_PERIOD"
    assert _credits([_notice(notice_type="SUSPENSION", discount_method=None)], PCT_RULE)["employee"] == 0
