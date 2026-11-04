"""New Zealand P3 engine modules, one by one (pure; no database).

Values come from new_zealand_content (spec-stated rows) plus clearly labelled
TEST fixtures for what the specification leaves to gate G1 (see
_nz_engine_helpers). TEST fixtures are not statutory content.
"""
from datetime import date
from decimal import Decimal as D

import pytest

from app.modules.payroll.engine.jurisdictions.new_zealand import (
    acc_earner_levy, child_support, components, deduction_precedence, errors as E, esct, kiwisaver,
    minimum_wage, paye, student_loan)
from app.modules.payroll.engine.jurisdictions.new_zealand.errors import NZCalculationBlockedError
from app.modules.payroll.engine.jurisdictions.new_zealand.pack import NzPack, floor_cent, normalise_frequency
from tests._nz_engine_helpers import build_pack, ctx, kiwisaver as ks_row, notice, tax_profile

PAYDAY = date(2026, 4, 8)


def _pack(**kw):
    rate_map, slabs = build_pack(**kw)
    return NzPack(rate_map, slabs, 1, PAYDAY)


def _blocked(fn, key):
    with pytest.raises(NZCalculationBlockedError) as raised:
        fn()
    assert raised.value.key == key or str(raised.value.key).startswith(key), raised.value.key
    return raised.value


# ── pack ────────────────────────────────────────────────────────────────────
def test_errors_block_cleanly_with_key_and_country():
    pack = _pack()
    error = _blocked(lambda: pack.block(E.keyed(E.TABLE_EMPTY, "x"), "why"), "NZ_TABLE_EMPTY:x")
    assert "New Zealand calculation blocked (NZ_TABLE_EMPTY:x): why" in str(error)


def test_row_missing_and_out_of_window_block():
    pack = _pack()
    _blocked(lambda: pack.row("no_such_key"), "NZ_ROW_MISSING:no_such_key")
    early = NzPack(build_pack()[0], [], 1, date(2026, 3, 31))
    _blocked(lambda: early.amount("nz_ks_default_rate"), "NZ_ROW_MISSING:nz_ks_default_rate")   # NZ-008


def test_pending_label_blocks_even_when_values_exist():
    pack = NzPack(*build_pack(pending=True), 1, PAYDAY)
    _blocked(lambda: pack.amount("nz_acc_earner_levy_rate"), E.PACK_UNSIGNED)


def test_an_empty_value_blocks_never_zero():
    pack = _pack(overrides={"nz_ks_employer_max_age": None})
    _blocked(lambda: pack.amount("nz_ks_employer_max_age"), "NZ_ROW_MISSING:nz_ks_employer_max_age")


def test_rounding_vocabulary_and_events():
    pack = _pack(overrides={"nz_paye_rounding": "DOWN_DOLLAR"})
    assert pack.rounder("nz_paye_rounding")(D("10.99")) == D("10")
    assert pack.rounder("nz_acc_rounding")(D("1.005")) == D("1.01")
    assert [e["key"] for e in pack.rounding_events] == ["nz_paye_rounding", "nz_acc_rounding"]
    _blocked(lambda: _pack(overrides={"nz_sl_rounding": "PENDING_G1"}).rounder("nz_sl_rounding"),
             "NZ_ROUNDING_PENDING:nz_sl_rounding")


def test_table_empty_blocks_with_its_name_and_used_rows_are_recorded():
    pack = _pack(drop_tables=("NZ_PAYE_METHOD",))
    _blocked(lambda: pack.table("NZ_PAYE_METHOD", "paye_main_method"), "NZ_TABLE_EMPTY:paye_main_method")
    pack.amount("nz_sl_rate")
    pack.amount("nz_sl_rate")
    assert [u["id"] for u in pack.used()] == ["nz_sl_rate"]


@pytest.mark.parametrize("value,expected", [("Weekly", "WEEKLY"), ("Fortnightly", "FORTNIGHTLY"),
                                            ("FourWeekly", "FOUR_WEEKLY"), ("Monthly", "MONTHLY"),
                                            ("Daily", "")])
def test_frequency_aliases(value, expected):
    assert normalise_frequency(value) == expected


def test_floor_cent():
    assert floor_cent(D("797.228")) == D("797.22")


# ── components ──────────────────────────────────────────────────────────────
def test_default_components_and_separate_bases():
    pack = _pack()
    c = ctx(gross=D("3200"), basic=D("3000"), overtime=D("200"))
    comps = components.pay_components(c, pack)
    assert comps == [("SALARY", D("3000")), ("OVERTIME", D("200"))]
    classes = components.earning_classes(pack)
    assert components.obligation_base("PAYE", comps, classes, pack)["base"] == D("3200")


def test_explicit_zero_salary_is_respected_and_unknown_component_blocks():
    pack = _pack()
    comps = components.pay_components(ctx(nz_components={"SALARY": 0, "OVERTIME": 3000}), pack)
    assert comps == [("OVERTIME", D("3000"))]
    _blocked(lambda: components.pay_components(ctx(nz_components={"TIPS": 5}), pack), E.COMPONENTS_INVALID)


def test_components_exceeding_gross_block():
    _blocked(lambda: components.pay_components(ctx(gross=D("100"), basic=D("3000")), _pack()), E.COMPONENTS_INVALID)


def test_review_component_blocks_and_lump_sum_path_blocks():
    pack = _pack()
    classes = components.earning_classes(pack)
    _blocked(lambda: components.obligation_base("PAYE", [("ALLOWANCE", D("50"))], classes, pack),
             "NZ_EARNING_CLASS_REVIEW:PAYE:ALLOWANCE")
    _blocked(lambda: components.obligation_base("PAYE", [("BONUS", D("50"))], classes, pack),
             E.LUMP_SUM_UNSUPPORTED)
    assert components.obligation_base("MIN_WAGE", [], classes, pack)["base"] == D("0")


# ── PAYE ────────────────────────────────────────────────────────────────────
def _code(code, pack=None):
    pack = pack or _pack()
    return paye.resolve_tax_code(tax_profile(tax_code=code), pack), pack


@pytest.mark.parametrize("code", ["M", "ME", "M SL", "ME SL", "SB", "S", "SH", "ST", "SA", "SB SL", "SA SL"])
def test_supported_codes_calculate(code):
    tc, pack = _code(code)
    assert paye.calculate_paye(D("1000"), tc, tax_profile(tax_code=code), "FORTNIGHTLY", PAYDAY, pack).paye >= 0


@pytest.mark.parametrize("code", ["CAE", "EDW", "NSW", "WT"])
def test_refused_codes(code):
    _blocked(lambda: _code(code), f"NZ_TAX_CODE_REFUSED:{code}")


def test_unknown_code_is_never_mapped():
    _blocked(lambda: _code("XYZ"), E.TAX_CODE_UNSUPPORTED)


def test_missing_ird_number_requires_nd_and_nd_requires_no_notification():
    pack = _pack()
    _blocked(lambda: paye.resolve_tax_code(tax_profile(tax_code="M", ird_number_state="MISSING"), pack),
             E.TAX_CODE_UNSUPPORTED)
    _blocked(lambda: paye.resolve_tax_code(tax_profile(tax_code="ND"), pack), E.TAX_CODE_UNSUPPORTED)
    profile = tax_profile(tax_code="ND", tax_code_source="NO_NOTIFICATION", ird_number_state="MISSING")
    tc = paye.resolve_tax_code(profile, pack)
    assert paye.calculate_paye(D("1000"), tc, profile, "WEEKLY", PAYDAY, pack).paye == D("450.00")   # TEST 45%


def test_main_paye_fortnightly_worked_example():
    tc, pack = _code("M")
    result = paye.calculate_paye(D("3000"), tc, tax_profile(), "FORTNIGHTLY", PAYDAY, pack)
    assert (result.paye, result.branch, result.period_factor) == (D("600.79"), "MAIN", D("26"))


@pytest.mark.parametrize("annual,tax", [("15600", "1638.00"), ("15601", "1638.175"), ("53500", "8270.50"),
                                        ("78100", "15650.50"), ("180000", "49277.50"), ("180001", "49277.89")])
def test_band_edges(annual, tax):
    pack = _pack()
    total, _steps = paye.band_tax(D(annual), pack.table("NZ_PAYE_BAND", "paye_bands"))
    assert total == D(tax)


@pytest.mark.parametrize("freq,factor", [("WEEKLY", 52), ("FORTNIGHTLY", 26), ("FOUR_WEEKLY", 13), ("MONTHLY", 12)])
def test_every_frequency_uses_its_method_row(freq, factor):
    tc, pack = _code("M")
    gross = D("78000") / factor
    result = paye.calculate_paye(gross, tc, tax_profile(), freq, PAYDAY, pack)
    assert result.period_factor == factor


def test_me_applies_the_annual_credit_and_needs_its_table():
    tc, pack = _code("ME")
    m_tc, _ = _code("M", pack)
    weekly = D("40000") / 52
    me = paye.calculate_paye(weekly, tc, tax_profile(tax_code="ME"), "WEEKLY", PAYDAY, pack).paye
    m = paye.calculate_paye(weekly, m_tc, tax_profile(), "WEEKLY", PAYDAY, pack).paye
    assert m - me == D("10.00")                                          # TEST 520 / 52
    no_ietc = _pack(drop_tables=("NZ_IETC",))
    tc2 = paye.resolve_tax_code(tax_profile(tax_code="ME"), no_ietc)
    _blocked(lambda: paye.calculate_paye(weekly, tc2, tax_profile(tax_code="ME"), "WEEKLY", PAYDAY, no_ietc),
             "NZ_TABLE_EMPTY:ietc_parameters")


def test_secondary_sl_code_uses_its_base_code_rate():
    tc, pack = _code("SH SL")
    assert paye.calculate_paye(D("1000"), tc, tax_profile(tax_code="SH SL"), "WEEKLY", PAYDAY, pack).paye == D("300.00")


def test_stc_window():
    pack = _pack()
    profile = tax_profile(tax_code="STC", tailored_certificate_ref="C1", tailored_rate_pct=D("21"),
                          tailored_valid_from=date(2026, 4, 1), tailored_valid_to=date(2026, 6, 30))
    tc = paye.resolve_tax_code(profile, pack)
    assert paye.calculate_paye(D("1000"), tc, profile, "WEEKLY", PAYDAY, pack).paye == D("210.00")
    _blocked(lambda: paye.calculate_paye(D("1000"), tc, profile, "WEEKLY", date(2026, 7, 1), pack),
             E.STC_OUT_OF_WINDOW)


def test_shipped_main_method_table_is_empty_and_blocks():
    tc, pack = _code("M", _pack(drop_tables=("NZ_PAYE_METHOD",)))
    _blocked(lambda: paye.calculate_paye(D("1000"), tc, tax_profile(), "WEEKLY", PAYDAY, pack),
             "NZ_TABLE_EMPTY:paye_main_method")


# ── ACC levy ────────────────────────────────────────────────────────────────
def test_acc_levy_and_cap():
    pack = _pack()
    assert acc_earner_levy.calculate_levy(D("3000"), {"ACC_LIABLE_EARNINGS": 0}, pack).levy == D("52.50")
    crossing = acc_earner_levy.calculate_levy(D("3000"), {"ACC_LIABLE_EARNINGS": D("155641")}, pack)
    assert (crossing.liable, crossing.levy, crossing.cap_crossed) == (D("1000"), D("17.50"), True)
    after = acc_earner_levy.calculate_levy(D("3000"), {"ACC_LIABLE_EARNINGS": D("156641")}, pack)
    assert (after.liable, after.levy, after.cap_reached_before) == (D("0"), D("0.00"), True)


def test_acc_missing_accumulator_blocks():
    for accumulators in (None, {}, {"ACC_LIABLE_EARNINGS": None}):
        _blocked(lambda: acc_earner_levy.calculate_levy(D("1"), accumulators, _pack()), E.ACC_ACCUMULATOR_MISSING)


def test_two_paydays_reach_the_cap_exactly():
    pack = _pack()
    first = acc_earner_levy.calculate_levy(D("100000"), {"ACC_LIABLE_EARNINGS": 0}, pack)
    second = acc_earner_levy.calculate_levy(D("100000"), {"ACC_LIABLE_EARNINGS": first.ytd_after}, pack)
    assert second.ytd_after == D("156641")


# ── student loan ────────────────────────────────────────────────────────────
def _sl(base, code="M SL", frequency="FORTNIGHTLY", profile=None, notices=(), pack=None):
    pack = pack or _pack()
    profile = profile or tax_profile(tax_code=code)
    tc = paye.resolve_tax_code(profile, pack)
    return student_loan.calculate_student_loan(D(base), tc, profile, frequency, PAYDAY, list(notices), pack)


@pytest.mark.parametrize("freq,threshold", [("WEEKLY", "464"), ("FORTNIGHTLY", "928"),
                                            ("FOUR_WEEKLY", "1856"), ("MONTHLY", "2010.66")])
def test_main_threshold_by_frequency(freq, threshold):
    assert _sl(threshold, frequency=freq).deduction == D("0")
    assert _sl(str(D(threshold) + 100), frequency=freq).deduction == D("12.00")


def test_secondary_whole_payment_and_non_sl_code():
    assert _sl("1000", code="S SL").deduction == D("120.00")
    assert _sl("5000", code="M").deduction == D("0")


def test_certificates_and_extra_notice():
    rate = tax_profile(tax_code="M SL", sl_certificate_type="SPECIAL_DEDUCTION_RATE", sl_certificate_ref="C",
                       sl_certificate_rate_pct=D("5"), sl_certificate_valid_from=date(2026, 4, 1))
    assert _sl("1000", profile=rate).deduction == D("50.00")
    nil = tax_profile(tax_code="M SL", sl_certificate_type="NIL_DEDUCTION", sl_certificate_ref="N",
                      sl_certificate_valid_from=date(2026, 4, 1))
    assert _sl("5000", profile=nil).deduction == D("0")
    expired = dict(rate, sl_certificate_valid_to=date(2026, 4, 7))
    assert _sl("1028", profile=expired).basis == "MAIN_THRESHOLD"
    extra = notice(deduction_type="STUDENT_LOAN_EXTRA", amount_per_payday=D("25"))
    assert _sl("1028", notices=[extra]).deduction == D("37.00")


# ── KiwiSaver / ESCT ────────────────────────────────────────────────────────
def _ks(election, dob=date(1996, 5, 1), base="3000", pay_date=PAYDAY, pack=None):
    return kiwisaver.calculate_kiwisaver(D(base), election, dob, pay_date, pack or _pack())


def test_default_rate_employer_minimum_and_esct():
    r = _ks(ks_row())
    assert (r.employee, r.employer_gross, r.esct, r.employer_net) == (D("105.00"), D("105.00"), D("31.50"), D("73.50"))
    assert r.compulsory_employer and r.destination == "INLAND_REVENUE"


def test_payday_before_1_april_2026_blocks():
    pack = NzPack(*build_pack(), 1, date(2026, 3, 31))
    # No 2026-27 row (rates, rounding) is in force for a 31 March payday: blocked, never the 1 April rate.
    _blocked(lambda: _ks(ks_row(effective_from=date(2026, 3, 1)), pay_date=date(2026, 3, 31), pack=pack),
             E.ROW_MISSING)


def test_employee_rates_reduction_and_suspension():
    assert _ks(ks_row(employee_rate_pct=D("6"))).employee == D("180.00")
    _blocked(lambda: _ks(ks_row(employee_rate_pct=D("5"))), E.KS_RATE_UNSUPPORTED)
    reduced = _ks(ks_row(reduction_ref="IR-1", reduction_from=date(2026, 4, 1)))
    assert reduced.reduction_applied and reduced.employee == D("90.00") and reduced.employer_rate == D("3.5")
    matched = _ks(ks_row(reduction_ref="IR-1", reduction_from=date(2026, 4, 1), employer_matches_reduction=True))
    assert matched.employer_gross == D("90.00")
    suspended = _ks(ks_row(membership_state="SAVINGS_SUSPENSION", suspension_ref="S1",
                           suspension_from=date(2026, 4, 1)))
    assert suspended.status == "SUSPENDED" and suspended.employee == D("0")
    _blocked(lambda: _ks(ks_row(membership_state="SAVINGS_SUSPENSION")), E.KS_SUSPENSION_UNEVIDENCED)
    lapsed = _ks(ks_row(membership_state="SAVINGS_SUSPENSION", suspension_ref="S1",
                        suspension_from=date(2025, 1, 1), suspension_to=date(2026, 3, 31)))
    assert lapsed.status == "CONTRIBUTING" and lapsed.employee == D("105.00")


def test_ages_and_employer_rules():
    assert _ks(ks_row(), dob=date(2010, 3, 1)).compulsory_employer                       # 16-year-old member
    over = _ks(ks_row(), dob=date(1950, 1, 1))
    assert not over.compulsory_employer and over.employer_gross == D("0")
    _blocked(lambda: _ks(ks_row(), dob=None), E.KS_AGE_UNKNOWN)
    _blocked(lambda: _ks(ks_row(employer_rate_pct=D("3"))), E.KS_EMPLOYER_RATE_BELOW_MINIMUM)
    _blocked(lambda: _ks(ks_row(employer_contribution_treatment="PAYE_ALTERNATIVE")),
             E.KS_PAYE_ALTERNATIVE_UNSUPPORTED)
    fund = _ks(ks_row(settlement_destination="COMPLYING_FUND", complying_fund_ref="FUND-1"))
    assert (fund.destination, fund.complying_fund_ref) == ("COMPLYING_FUND", "FUND-1")
    assert _ks(ks_row(membership_state="OPTED_OUT")).employee == D("0")
    assert _ks(None).status == "NOT_MEMBER"


def test_shipped_max_age_is_empty_and_blocks():
    _blocked(lambda: _ks(ks_row(), pack=_pack(overrides={"nz_ks_employer_max_age": None})),
             "NZ_ROW_MISSING:nz_ks_employer_max_age")


@pytest.mark.parametrize("amount,rate", [("0", "10.5"), ("18720", "10.5"), ("18721", "17.5"),
                                         ("93720", "30"), ("216001", "39")])
def test_esct_band_edges(amount, rate):
    pack = _pack()
    assert esct.band_rate(D(amount), pack.table("NZ_ESCT_BAND", "esct_bands")) == D(rate)


def test_esct_rate_must_match_its_basis():
    _blocked(lambda: _ks(ks_row(esct_rate_pct=D("17.5"))), E.ESCT_RATE_UNRESOLVED)
    _blocked(lambda: _ks(ks_row(esct_basis_amount=None)), E.ESCT_RATE_UNRESOLVED)


# ── child support ───────────────────────────────────────────────────────────
def _cs(net, notices, pack=None):
    return child_support.calculate_child_support(D(net), notices, PAYDAY, pack or _pack())


def test_child_support_normal_and_capped_with_floor():
    assert _cs("2000", [notice(amount_per_payday=D("300"))]).deduction == D("300")
    capped = _cs("1993.07", [notice()])
    assert (capped.deduction, capped.shortfall, capped.variation_code) == (D("797.22"), D("102.78"), "TESTV")
    assert capped.protected_net >= D("1993.07") * D("0.6")


def test_child_support_variation_table_and_out_of_scope_notices():
    no_rows = _pack(drop_tables=("NZ_CS_VARIATION",))
    _blocked(lambda: _cs("100", [notice()], no_rows), "NZ_TABLE_EMPTY:cs_variation_codes")
    wrong_trigger = _pack(drop_tables=("NZ_CS_VARIATION",), extra_slabs=[
        dict(rule_type="NZ_CS_VARIATION", filing_status="OTHER", tax_formula="SOMETHING_ELSE")])
    _blocked(lambda: _cs("100", [notice()], wrong_trigger), E.CS_VARIATION_CODE_MISSING)
    assert _cs("5000", [notice()], no_rows).shortfall == D("0")
    assert _cs("5000", [notice(), notice(id=32, notice_id="CS-2")]).deduction == D("1800")
    assert _cs("5000", [notice(effective_from=date(2026, 5, 1))]).deduction == D("0")
    _blocked(lambda: _cs("5000", [notice(deduction_type="COURT_ATTACHMENT")]), E.CS_NOTICE_INVALID)


# ── precedence / minimum wage ───────────────────────────────────────────────
def test_precedence_rules():
    assert deduction_precedence.precedence(_pack())[-1] == "CHILD_SUPPORT"
    _blocked(lambda: deduction_precedence.precedence(_pack(overrides={"nz_deduction_precedence": "PENDING_G1"})),
             E.PRECEDENCE_PENDING)
    _blocked(lambda: deduction_precedence.precedence(_pack(overrides={"nz_deduction_precedence": "PAYE,ACC_LEVY"})),
             E.PRECEDENCE_PENDING)
    bad = "CHILD_SUPPORT,PAYE,ACC_LEVY,STUDENT_LOAN,KS_EMPLOYEE"
    _blocked(lambda: deduction_precedence.precedence(_pack(overrides={"nz_deduction_precedence": bad})),
             E.PRECEDENCE_PENDING)


def test_minimum_wage_outcomes_never_change_pay():
    pack = _pack()
    assert minimum_wage.check_minimum_wage(D("958"), D("40"), "X", "ADULT", pack).status == "PASS"
    fail = minimum_wage.check_minimum_wage(D("957.60"), D("40"), "X", "ADULT", pack)
    assert fail.status == "FAIL" and fail.shortfall == D("0.40")
    assert minimum_wage.check_minimum_wage(D("766.40"), D("40"), "X", "STARTING_OUT", pack).status == "PASS"
    for category, hours in ((None, D("40")), ("EXEMPTION_PERMIT", D("40")), ("ADULT", None)):
        assert minimum_wage.check_minimum_wage(D("1"), hours, None, category, pack).status == "UNDETERMINABLE"
    assert minimum_wage.exception_for(fail)["code"] == E.EXC_MIN_WAGE_FAIL
