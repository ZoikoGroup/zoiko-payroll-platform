"""Mexico special-payment rule objects (completion programme W1-3) —
engine/countries/mexico_rules.py. SYNTHETIC content stands in for the pack
(a tiny Content double); the transcribed wording and its pages are checked by
`verify_mexico_sources.py compare` and test_mexico_content.py."""

import datetime as dt
from decimal import Decimal

import pytest


def _r():
    from app.modules.payroll.engine.countries import mexico_rules

    return mexico_rules


class _Content:
    """SYNTHETIC: UMA 100, zone minimum wages 200 / 300, a two-bracket monthly tariff."""

    def __init__(self):
        self.tariff = [{"lower": Decimal("0.01"), "upper": Decimal("10000"), "fixed": Decimal("0"),
                        "rate": Decimal("0.10"), "rate_pct": Decimal("10")},
                       {"lower": Decimal("10000.01"), "upper": None, "fixed": Decimal("1000"),
                        "rate": Decimal("0.20"), "rate_pct": Decimal("20")}]

    def amount(self, key):
        return {"mx_uma_daily": Decimal("100")}[key]

    def min_wage(self, code, zone=None):
        return {"GENERAL": Decimal("200"), "ZLFN": Decimal("300")}[code]

    def isr_tariff(self, period):
        assert period == "MONTHLY"
        return self.tariff


def _facts(**kw):
    out = {"content": _Content(), "zone": "GENERAL", "daily_salary": Decimal("500"), "year_to_date_exempt": {},
           "pay_date": dt.date(2026, 12, 15)}
    out.update(kw)
    return out


def _codes(exc):
    return [k for k, _ in exc.value.reasons]


@pytest.fixture
def decided(monkeypatch):
    r = _r()
    monkeypatch.setattr(r, "MX_EXEMPTION_WAGE_REFERENCE", "UMA")
    monkeypatch.setattr(r, "MX_SPECIAL_PAY_WITHHOLDING_METHOD", "RLISR_174")
    monkeypatch.setattr(r, "MX_MONTHLY_ORDINARY_INCOME_DAYS", "30")
    return r


def test_every_switch_is_undecided_and_blocks_with_its_own_code():
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    r = _r()
    assert (r.MX_EXEMPTION_WAGE_REFERENCE, r.MX_SPECIAL_PAY_WITHHOLDING_METHOD, r.MX_MONTHLY_ORDINARY_INCOME_DAYS) \
        == (None, None, None)
    rule = r.SPECIAL_PAY_RULES["AGUINALDO"]
    with pytest.raises(MXBlock) as exc:
        rule.exempt("AGUINALDO", Decimal("1000"), _facts())
    assert _codes(exc) == ["MX_EXEMPTION_WAGE_REFERENCE_UNDECIDED"]
    with pytest.raises(MXBlock) as exc:
        rule.standalone_isr(Decimal("1000"), _facts())
    assert _codes(exc) == ["MX_SPECIAL_PAY_METHOD_UNDECIDED"]
    with pytest.raises(MXBlock) as exc:
        r.monthly_ordinary_income(_facts())
    assert _codes(exc) == ["MX_MONTHLY_ORDINARY_INCOME_UNDECIDED"]


def test_art93_xiv_caps_per_calendar_year_in_the_chosen_wage(decided, monkeypatch):
    r = decided
    agui, prima, ptu = (r.SPECIAL_PAY_RULES[k] for k in ("AGUINALDO", "VACATION_PREMIUM", "PTU"))
    assert agui.exempt("AGUINALDO", Decimal("5000"), _facts()) == Decimal("3000")          # 30 × UMA 100
    assert agui.exempt("AGUINALDO", Decimal("2000"), _facts()) == Decimal("2000")          # below the cap
    assert prima.exempt("VACATION_PREMIUM", Decimal("5000"), _facts()) == Decimal("1500")  # 15 × 100
    assert ptu.exempt("PTU", Decimal("5000"), _facts()) == Decimal("1500")
    # what earlier payments of the same concept used in the year is not available again
    used = _facts(year_to_date_exempt={"VACATION_PREMIUM": Decimal("1200")})
    assert prima.exempt("VACATION_PREMIUM", Decimal("5000"), used) == Decimal("300")
    used = _facts(year_to_date_exempt={"VACATION_PREMIUM": Decimal("1500")})
    assert prima.exempt("VACATION_PREMIUM", Decimal("5000"), used) == Decimal("0")
    # the zone reading counts the cap in the worker's zone minimum wage (RLISR Art. 167)
    monkeypatch.setattr(r, "MX_EXEMPTION_WAGE_REFERENCE", "ZONE_MIN_WAGE")
    assert agui.exempt("AGUINALDO", Decimal("9000"), _facts()) == Decimal("6000")          # 30 × 200
    assert agui.exempt("AGUINALDO", Decimal("9500"), _facts(zone="ZLFN", daily_salary=Decimal("900"))) \
        == Decimal("9000")                                                                   # 30 × 300


def test_vacation_payout_has_no_exemption(decided):
    rule = decided.SPECIAL_PAY_RULES["VACATION_PAYOUT"]
    assert rule.exempt("VACATION_PAYOUT", Decimal("4000"), _facts()) == Decimal("0")
    assert rule.combine_with_ordinary is True


def test_a_minimum_wage_worker_blocks_under_art93_i(decided):
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    with pytest.raises(MXBlock) as exc:
        decided.SPECIAL_PAY_RULES["AGUINALDO"].exempt("AGUINALDO", Decimal("3000"), _facts(daily_salary=Decimal("200")))
    assert _codes(exc) == ["MX_ART93_I_NOT_MODELLED"]


def test_year_to_date_exempt_must_be_supplied(decided):
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    with pytest.raises(MXBlock) as exc:
        decided.SPECIAL_PAY_RULES["PTU"].exempt("PTU", Decimal("3000"), _facts(year_to_date_exempt=None))
    assert _codes(exc) == ["MX_YEAR_TO_DATE_EXEMPT_MISSING"]


@pytest.mark.parametrize("start,end,years", [
    ("2020-03-01", "2026-03-01", 6),      # exact anniversaries
    ("2020-03-01", "2026-09-01", 6),      # exactly six months more: not "más de seis meses"
    ("2020-03-01", "2026-09-02", 7),      # one day more than six months: a full year
    ("2026-01-10", "2026-07-11", 1),      # under a year but more than six months
    ("2026-01-10", "2026-05-10", 0),
])
def test_art93_xiii_years_of_service_round_up_past_six_months(start, end, years):
    assert _r().years_of_service_art93_xiii(start, end) == years


def test_art93_xiii_cap_is_shared_by_every_separation_payment(decided):
    r = decided
    facts = _facts(seniority_date="2020-01-01", separation_date="2026-01-01", separation_total=Decimal("90000"))
    cap = Decimal("90") * Decimal("100") * 6                                               # 54,000
    prima = r.SPECIAL_PAY_RULES["SEPARATION_SENIORITY_PREMIUM"].exempt(
        "SEPARATION_SENIORITY_PREMIUM", Decimal("30000"), facts)
    indem = r.SPECIAL_PAY_RULES["SEPARATION_INDEMNITY"].exempt("SEPARATION_INDEMNITY", Decimal("60000"), facts)
    assert prima + indem == cap and (prima, indem) == (Decimal("18000"), Decimal("36000"))   # pro rata
    small = _facts(seniority_date="2020-01-01", separation_date="2026-01-01", separation_total=Decimal("10000"))
    assert r.SPECIAL_PAY_RULES["SEPARATION_PAYMENT"].exempt("SEPARATION_PAYMENT", Decimal("10000"), small) \
        == Decimal("10000")
    assert all(r.SPECIAL_PAY_RULES[k].combine_with_ordinary is False for k in r.SEPARATION_CONCEPTS)


def test_rlisr_174_withholding_follows_fractions_i_to_v(decided):
    """SYNTHETIC tariff: 10% to 10,000 then 1,000 + 20%. Daily salary 300 × 30 = 9,000 ordinary."""
    r = decided
    rule = r.SPECIAL_PAY_RULES["AGUINALDO"]
    taxable = Decimal("36500")
    monthly = taxable / 365 * Decimal("30.4")                                               # fr. I: 3,040
    assert monthly == Decimal("3040")
    t_with = Decimal("1000") + (Decimal("9000") + monthly - Decimal("10000.01")) * Decimal("0.20")
    t_without = (Decimal("9000") - Decimal("0.01")) * Decimal("0.10")
    expected = taxable * ((t_with - t_without) / monthly)                                    # fr. III–V
    assert rule.standalone_isr(taxable, _facts(daily_salary=Decimal("300"))) == expected
    assert rule.standalone_isr(Decimal("0"), _facts()) == Decimal("0")
    with pytest.raises(Exception):
        r.SPECIAL_PAY_RULES["SEPARATION_INDEMNITY"].standalone_isr(taxable, _facts())


def test_lft_87_aguinaldo_fraction_and_payable_by():
    rule = _r().AGUINALDO_RULE
    assert rule.fraction(2026, dt.date(2020, 5, 1), None) == Decimal("1")
    assert rule.fraction(2026, dt.date(2026, 7, 1), None) == Decimal(184) / Decimal(365)        # 1 Jul – 31 Dec
    assert rule.fraction(2026, dt.date(2025, 1, 1), dt.date(2026, 1, 31)) == Decimal(31) / Decimal(365)
    assert rule.fraction(2028, dt.date(2028, 1, 1), dt.date(2028, 6, 30)) == Decimal(182) / Decimal(366)
    assert rule.fraction(2026, dt.date(2027, 1, 1), None) == Decimal("0")
    assert rule.payable_by(2026) == dt.date(2026, 12, 19)


def test_every_rule_quotes_its_wording():
    r = _r()
    for rule in list(r.SPECIAL_PAY_RULES.values()) + [r.AGUINALDO_RULE]:
        assert rule.citations and all("'" in ref and "PDF p" in ref for _src, ref in rule.citations)
        assert (rule.source, rule.source_ref) == rule.citations[0]


# ── W1-3b: termination reasons and the finiquito rule ──

_POLICY = {"aguinaldo_days": "15", "vacation_premium_pct": "25",
           "vacation_policy": [{"serviceYearFrom": 1, "serviceYearTo": None, "days": "12"}]}
_FACTOR = (Decimal("365") + Decimal("15") + Decimal("12") * Decimal("25") / 100) / Decimal("365")


def _tfacts(**kw):
    out = _facts(seniority_date=dt.date(2020, 1, 1), termination_date=dt.date(2026, 1, 1), contract_type_code="01",
                 labor_policy=_POLICY)
    out.update(kw)
    return out


@pytest.fixture
def decided_b(decided, monkeypatch):
    monkeypatch.setattr(decided, "MX_INDEMNITY_SALARY_BASIS", "POLICY_INTEGRATED")
    monkeypatch.setattr(decided, "MX_SERVICE_YEARS_COUNT", "PROPORTIONAL")
    monkeypatch.setattr(decided, "MX_SENIORITY_PREMIUM_WAGE_REFERENCE", "ZONE_MIN_WAGE")
    return decided


def _comps(r, code, facts):
    return {c["code"]: c["amount"] for c in r.TERMINATION_REASONS[code].separation_components(facts)}


def test_w13b_switches_are_undecided_and_block_with_their_own_codes():
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    r = _r()
    assert (r.MX_INDEMNITY_SALARY_BASIS, r.MX_SERVICE_YEARS_COUNT, r.MX_SENIORITY_PREMIUM_WAGE_REFERENCE) \
        == (None, None, None)
    for fn, code in ((lambda: r.indemnity_daily_salary(_tfacts()), "MX_INDEMNITY_SALARY_UNDECIDED"),
                     (lambda: r.service_years("2020-01-01", "2026-01-01"), "MX_SERVICE_YEARS_COUNT_UNDECIDED"),
                     (lambda: r.seniority_premium_daily_salary(_tfacts()),
                      "MX_SENIORITY_PREMIUM_WAGE_REFERENCE_UNDECIDED")):
        with pytest.raises(MXBlock) as exc:
            fn()
        assert _codes(exc) == [code]


def test_service_years_proportional_or_completed(decided_b, monkeypatch):
    r = decided_b
    assert r.service_years("2020-01-01", "2026-01-01") == Decimal("6")
    assert r.service_years("2020-01-01", "2026-07-02") == Decimal("6") + Decimal(182) / Decimal(365)
    monkeypatch.setattr(r, "MX_SERVICE_YEARS_COUNT", "COMPLETED")
    assert r.service_years("2020-01-01", "2026-07-02") == Decimal("6")


def test_seniority_premium_salary_is_bounded_by_arts_485_486(decided_b, monkeypatch):
    r = decided_b
    assert r.seniority_premium_daily_salary(_tfacts(daily_salary=Decimal("150"))) == Decimal("200")   # floor
    assert r.seniority_premium_daily_salary(_tfacts(daily_salary=Decimal("350"))) == Decimal("350")
    assert r.seniority_premium_daily_salary(_tfacts(daily_salary=Decimal("900"))) == Decimal("400")   # 2 × 200
    monkeypatch.setattr(r, "MX_SENIORITY_PREMIUM_WAGE_REFERENCE", "UMA")
    assert r.seniority_premium_daily_salary(_tfacts(daily_salary=Decimal("900"))) == Decimal("200")   # 2 × UMA 100


def test_dismissal_and_rescission_reasons_compute_their_lft_components(decided_b):
    r = decided_b
    daily = Decimal("500") * _FACTOR                                 # Art. 89 integrated
    premium = Decimal("12") * 6 * Decimal("400")                     # 12 days × 6 years × capped salary
    assert _comps(r, "LFT_47_RESCISSION_BY_EMPLOYER", _tfacts()) == {"SENIORITY_PREMIUM": premium}
    assert _comps(r, "LFT_48_DISMISSAL_INDEMNIFIED", _tfacts()) == {"INDEMNITY_3_MONTHS": 90 * daily,
                                                                   "SENIORITY_PREMIUM": premium}
    full = {"INDEMNITY_ART50_YEARS": 20 * 6 * daily, "INDEMNITY_3_MONTHS": 90 * daily, "SENIORITY_PREMIUM": premium}
    assert _comps(r, "LFT_49_NO_REINSTATEMENT", _tfacts()) == full
    assert _comps(r, "LFT_51_RESCISSION_BY_WORKER", _tfacts()) == full
    assert _comps(r, "LFT_53_III_END_OF_TERM", _tfacts()) == {}
    assert _comps(r, "LFT_54_INCAPACITY", _tfacts()) == {"ONE_MONTH_ART54": 30 * daily, "SENIORITY_PREMIUM": premium}


def test_fixed_term_contracts_follow_art_50_i_and_get_no_seniority_premium(decided_b):
    r = decided_b
    daily = Decimal("500") * _FACTOR
    short = _tfacts(contract_type_code="03", seniority_date=dt.date(2026, 1, 1), termination_date=dt.date(2026, 4, 10))
    assert _comps(r, "LFT_49_NO_REINSTATEMENT", short) == {"INDEMNITY_ART50_YEARS": Decimal(100) / 2 * daily,
                                                           "INDEMNITY_3_MONTHS": 90 * daily}
    long = _tfacts(contract_type_code="03", seniority_date=dt.date(2023, 1, 1), termination_date=dt.date(2026, 1, 1))
    assert _comps(r, "LFT_49_NO_REINSTATEMENT", long)["INDEMNITY_ART50_YEARS"] == (180 + 20 * 2) * daily
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    with pytest.raises(MXBlock) as exc:
        _comps(r, "LFT_49_NO_REINSTATEMENT", _tfacts(contract_type_code="02"))
    assert _codes(exc) == ["MX_TERMINATION_CONTRACT_UNSUPPORTED"]


def test_voluntary_separation_pays_the_premium_only_from_15_years(decided_b):
    r = decided_b
    assert _comps(r, "LFT_162_VOLUNTARY_SEPARATION", _tfacts()) == {}
    old = _tfacts(seniority_date=dt.date(2010, 1, 1))
    assert _comps(r, "LFT_162_VOLUNTARY_SEPARATION", old) == {"SENIORITY_PREMIUM": Decimal("12") * 16 * Decimal("400")}


def test_finiquito_vacation_owed_completed_and_proportional():
    rule = _r().FINIQUITO_RULE
    years = [{"service_year": 1, "start": dt.date(2025, 1, 1), "end": dt.date(2026, 1, 1), "complete": True,
              "policy_days": Decimal("12"), "opening": Decimal("0"), "taken": Decimal("10"), "paid_out": Decimal("0")},
             {"service_year": 2, "start": dt.date(2026, 1, 1), "end": dt.date(2026, 7, 1), "complete": False,
              "policy_days": Decimal("14"), "opening": Decimal("0"), "taken": Decimal("0"), "paid_out": Decimal("0")}]
    owed = rule.vacation_days_owed(years, dt.date(2026, 7, 1))
    assert owed == {1: Decimal("2"), 2: Decimal("14") * Decimal(182) / Decimal(365)}


def test_finiquito_isr_separation_rate_and_the_below_salary_tariff(decided_b):
    r = decided_b
    rule = r.FINIQUITO_RULE
    facts = _facts(daily_salary=Decimal("400"))                      # monthly ordinary 12,000 (D-09 = 30)
    t_month = Decimal("1000") + (Decimal("12000") - Decimal("10000.01")) * Decimal("0.20")
    big = rule.isr({"SEPARATION_INDEMNITY": Decimal("50000")}, facts)
    assert big == Decimal("50000") * (t_month / Decimal("12000"))
    small = rule.isr({"SEPARATION_INDEMNITY": Decimal("5000")}, facts)
    assert small == (Decimal("5000") - Decimal("0.01")) * Decimal("0.10")
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    with pytest.raises(MXBlock) as exc:
        rule.isr({"VACATION_PAYOUT": Decimal("100")}, facts)
    assert _codes(exc) == ["MX_FINIQUITO_ORDINARY_METHOD_UNDECIDED"]          # A17 built; the method is D-22


def test_finiquito_vacation_payout_is_withheld_against_the_month(decided_b, monkeypatch):
    """Completion A17 / D-22: vacation paid out is ordinary income of the month
    (LISR Art. 96). SYNTHETIC monthly tariff: 10% to 10,000, then 1,000 + 20%."""
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    r = decided_b
    rule = r.FINIQUITO_RULE
    facts = _facts(daily_salary=Decimal("400"))
    facts["month_to_date"] = {"taxable": Decimal("8000"), "subsidy_applied": Decimal("0"),
                              "isr_withheld": Decimal("700")}
    tariff = lambda x: (x - Decimal("0.01")) * Decimal("0.10") if x <= Decimal("10000") else         Decimal("1000") + (x - Decimal("10000.01")) * Decimal("0.20")                       # noqa: E731
    monkeypatch.setattr(r, "MX_FINIQUITO_ORDINARY_WITHHOLDING", "INCREMENTAL_MONTHLY")
    assert rule.isr({"VACATION_PAYOUT": Decimal("4000")}, facts) == tariff(Decimal("12000")) - tariff(Decimal("8000"))
    monkeypatch.setattr(r, "MX_FINIQUITO_ORDINARY_WITHHOLDING", "MONTHLY_TOTAL_LESS_WITHHELD")
    assert rule.isr({"VACATION_PAYOUT": Decimal("4000")}, facts) == tariff(Decimal("12000")) - Decimal("700")
    facts["month_to_date"]["isr_withheld"] = Decimal("5000")                        # more already withheld
    assert rule.isr({"VACATION_PAYOUT": Decimal("4000")}, facts) == Decimal("0")
    del facts["month_to_date"]["isr_withheld"]
    with pytest.raises(MXBlock) as exc:
        rule.isr({"VACATION_PAYOUT": Decimal("4000")}, facts)
    assert _codes(exc) == ["MX_SPECIAL_PAY_FACT_MISSING"]
    monkeypatch.setattr(r, "MX_FINIQUITO_ORDINARY_WITHHOLDING", "GUESS")
    with pytest.raises(MXBlock) as exc:
        rule.isr({"VACATION_PAYOUT": Decimal("4000")}, facts)
    assert _codes(exc) == ["MX_RULE_UNRECOGNISED"]


def test_every_termination_rule_quotes_its_wording():
    r = _r()
    for rule in list(r.TERMINATION_REASONS.values()) + [r.FINIQUITO_RULE]:
        assert rule.citations and all("'" in ref and "PDF p" in ref for _src, ref in rule.citations)


# ── W1-4: PTU and the annual adjustment ──

def _w(eid, days, base, excl=None, history=None):
    return {"employee_id": eid, "days": Decimal(days), "salary_by_kind": {"PTU_WAGE_BASE": Decimal(base)},
            "operator_exclusion": excl, "ptu_history": history or {}}


def test_ptu_splits_half_by_days_half_by_salary_and_excludes_operator_reasons():
    rule = _r().PTU_RULE
    out = rule.allocate(Decimal("10000"), [_w(1, 300, 90000), _w(2, 100, 10000), _w(3, 365, 500000, "LFT_127_I_DIRECTOR")],
                        2026)
    by = {w["employee_id"]: w for w in out["workers"]}
    assert by[1]["days_share"] == Decimal("5000") * 300 / 400 and by[1]["salary_share"] == Decimal("5000") * 9 / 10
    assert by[2]["days_share"] == Decimal("5000") / 4 and by[2]["salary_share"] == Decimal("500")
    assert by[3] == {"employee_id": 3, "eligible": False, "exclusion_reason": "LFT_127_I_DIRECTOR",
                     "days_share": 0, "salary_share": 0, "cap_reference": None, "cap_applied": False,
                     "final_amount": 0}
    assert by[1]["final_amount"] + by[2]["final_amount"] + out["residue"] == Decimal("10000")
    assert set(_r().PTU_EXCLUSION_REASONS) == {"LFT_127_I_DIRECTOR", "LFT_127_VI_DOMESTIC",
                                               "LFT_127_VII_EVENTUAL_UNDER_60_DAYS"}


def test_ptu_cap_is_the_more_favourable_of_three_months_and_the_history_average(monkeypatch):
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    r = _r()
    # daily cash salary 100 → three months = 9,000; this share (≈ 12,500) exceeds it
    workers = [_w(1, 100, 10000), _w(2, 300, 10000)]
    with pytest.raises(MXBlock) as exc:
        r.PTU_RULE.allocate(Decimal("25000"), workers, 2026)
    assert _codes(exc) == ["MX_PTU_CAP_EXCESS_UNDECIDED"]
    monkeypatch.setattr(r, "MX_PTU_CAP_EXCESS", "UNDISTRIBUTED")
    out = r.PTU_RULE.allocate(Decimal("25000"), workers, 2026)
    w1 = next(w for w in out["workers"] if w["employee_id"] == 1)
    assert w1["cap_applied"] and w1["final_amount"] == Decimal("9000")
    assert sum(w["final_amount"] for w in out["workers"]) + out["residue"] == Decimal("25000")
    # three full years of history above three months' salary: the average is the cap (more favourable)
    rich = [_w(1, 100, 10000, history={2023: 15000, 2024: 15000, 2025: 15000}), _w(2, 300, 10000)]
    w1 = next(w for w in r.PTU_RULE.allocate(Decimal("25000"), rich, 2026)["workers"] if w["employee_id"] == 1)
    assert not w1["cap_applied"]
    # fewer than three years, and the two averages lead to different caps: D-14 blocks
    short = [_w(1, 100, 10000, history={2025: 15000}), _w(2, 300, 10000)]
    with pytest.raises(MXBlock) as exc:
        r.PTU_RULE.allocate(Decimal("25000"), short, 2026)
    assert _codes(exc) == ["MX_PTU_HISTORY_AVERAGE_UNDECIDED"]


def test_ptu_payment_deadline_is_60_days_after_the_annual_return():
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    rule = _r().PTU_RULE
    assert rule.payment_deadline(2026, {"taxpayer_type": "MORAL"}) == dt.date(2027, 3, 31) + dt.timedelta(days=60)
    assert rule.payment_deadline(2026, {"taxpayer_type": "FISICA"}) == dt.date(2027, 4, 30) + dt.timedelta(days=60)
    with pytest.raises(MXBlock):
        rule.payment_deadline(2026, {"id": 1})


def test_annual_adjustment_eligibility_follows_art_97():
    rule = _r().ANNUAL_ADJUSTMENT_RULE
    base = {"date_of_joining": dt.date(2020, 1, 1), "date_of_leaving": None, "annual_gross": Decimal("300000")}
    assert rule.eligibility(base, 2026) == (True, None)
    assert rule.eligibility({**base, "date_of_joining": dt.date(2026, 1, 1)}, 2026) == (True, None)
    assert rule.eligibility({**base, "date_of_joining": dt.date(2026, 1, 2)}, 2026)[0] is False
    assert rule.eligibility({**base, "date_of_leaving": dt.date(2026, 11, 30)}, 2026)[0] is False
    assert rule.eligibility({**base, "date_of_leaving": dt.date(2026, 12, 1)}, 2026) == (True, None)
    assert rule.eligibility({**base, "annual_gross": Decimal("400000.00")}, 2026) == (True, None)
    assert rule.eligibility({**base, "annual_gross": Decimal("400000.01")}, 2026)[0] is False


def test_annual_isr_is_the_art_152_tariff_less_the_subsidy_never_below_zero():
    rule = _r().ANNUAL_ADJUSTMENT_RULE
    # 2026 annual tariff, bracket 2: 194.59 + (50,000 − 10,135.12) × 6.40%
    tax = Decimal("194.59") + (Decimal("50000") - Decimal("10135.12")) * Decimal("0.064")
    assert rule.annual_isr(Decimal("50000"), 2026, {"subsidy_due_total": Decimal("0")}) == tax
    assert rule.annual_isr(Decimal("50000"), 2026, {"subsidy_due_total": Decimal("1000")}) == tax - 1000
    assert rule.annual_isr(Decimal("50000"), 2026, {"subsidy_due_total": Decimal("99999")}) == 0
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    with pytest.raises(MXBlock):
        rule.annual_isr(Decimal("50000"), 2025, {"subsidy_due_total": Decimal("0")})     # no 2025 table


def test_annual_difference_owed_in_full_refund_against_withholdings():
    rule = _r().ANNUAL_ADJUSTMENT_RULE
    assert rule.apply_in_run(Decimal("500"), Decimal("300"), {}) == {"withheld": Decimal("800"), "carry_forward": 0}
    assert rule.apply_in_run(Decimal("500"), Decimal("-200"), {}) == {"withheld": Decimal("300"), "carry_forward": 0}
    assert rule.apply_in_run(Decimal("500"), Decimal("-800"), {}) == {"withheld": 0, "carry_forward": Decimal("-300")}



# ── W3-3: contribution days with absences and incapacity (LSS Art. 31; Ley INFONAVIT Art. 29) ──

def test_lss_31_branch_days():
    r = _r().CONTRIBUTION_DAYS_RULE
    days = {b: r.branch_days(b, Decimal("15"), Decimal("3"), Decimal("2"))
            for b in ("EM_FIXED_QUOTA", "EM_EXCESS", "EM_CASH", "EM_PENSIONER", "IV", "GUARDERIAS", "RETIRO", "CEAV",
                      "RIESGOS_TRABAJO", "INFONAVIT")}
    # sickness & maternity keep absence days, lose incapacity days
    assert all(days[b] == 13 for b in ("EM_FIXED_QUOTA", "EM_EXCESS", "EM_CASH", "EM_PENSIONER"))
    # retiro (and INFONAVIT) keep incapacity days, lose absence days
    assert days["RETIRO"] == days["INFONAVIT"] == 12
    # every other branch loses both
    assert all(days[b] == 10 for b in ("IV", "GUARDERIAS", "CEAV", "RIESGOS_TRABAJO"))
    assert r.branch_days("IV", Decimal("5"), Decimal("4"), Decimal("4")) == 0           # never negative


def test_lss_31_limits_block():
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    r = _r().CONTRIBUTION_DAYS_RULE
    r.check(Decimal("7"), Decimal("10"), 1)                                             # fewer than 8: fine
    for args, code in (((Decimal("8"), Decimal("0"), 1), "MX_ABSENCE_ART37_NOT_MODELLED"),
                       ((Decimal("1"), Decimal("0"), 2), "MX_ABSENCE_SEGMENT_UNKNOWN"),
                       ((Decimal("0"), Decimal("1"), 2), "MX_ABSENCE_SEGMENT_UNKNOWN")):
        with pytest.raises(MXBlock) as exc:
            r.check(*args)
        assert _codes(exc) == [code]
    r.check(Decimal("0"), Decimal("0"), 2)                                              # nothing to place


# ── W3-4: LISR Art. 93 exemptions for ordinary earnings ──

def test_overtime_exemption_is_half_the_first_tier_capped_at_five_wages_a_week(decided):
    r = decided
    rule = r.ORDINARY_EXEMPTION_RULES["LISR_93_I_OVERTIME"]
    weeks = [{"first_tier_amount": Decimal("600")}, {"first_tier_amount": Decimal("1400")}]
    # UMA 100 (decided): week 1 50% of 600 = 300; week 2 50% of 1,400 = 700, capped at 5 x 100 = 500
    assert rule.exempt("OVERTIME", Decimal("2500"), _facts(overtime_weeks=weeks)) == Decimal("800")
    assert rule.exempt("OVERTIME", Decimal("500"), _facts(overtime_weeks=weeks)) == Decimal("500")   # never above the line
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    with pytest.raises(MXBlock) as exc:
        rule.exempt("OVERTIME", Decimal("100"), _facts())
    assert _codes(exc) == ["MX_EXEMPTION_FACT_MISSING"]
    with pytest.raises(MXBlock) as exc:
        rule.exempt("SUNDAY_PREMIUM", Decimal("100"), _facts(overtime_weeks=weeks))
    assert _codes(exc) == ["MX_EXEMPTION_RULE_KIND_MISMATCH"]


def test_sunday_premium_exemption_is_one_wage_per_sunday(decided):
    rule = decided.ORDINARY_EXEMPTION_RULES["LISR_93_XIV_SUNDAY_PREMIUM"]
    assert rule.exempt("SUNDAY_PREMIUM", Decimal("500"), _facts(sundays_worked=2)) == Decimal("200")
    assert rule.exempt("SUNDAY_PREMIUM", Decimal("150"), _facts(sundays_worked=2)) == Decimal("150")


def test_ordinary_exemptions_wait_for_d07_and_block_minimum_wage_workers():
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    rule = _r().ORDINARY_EXEMPTION_RULES["LISR_93_XIV_SUNDAY_PREMIUM"]
    with pytest.raises(MXBlock) as exc:
        rule.exempt("SUNDAY_PREMIUM", Decimal("500"), _facts(sundays_worked=1))
    assert _codes(exc) == ["MX_EXEMPTION_WAGE_REFERENCE_UNDECIDED"]
    with pytest.raises(MXBlock) as exc:
        rule.exempt("SUNDAY_PREMIUM", Decimal("500"), _facts(sundays_worked=1, daily_salary=Decimal("200")))
    assert _codes(exc) == ["MX_ART93_I_NOT_MODELLED"]


def test_classify_applies_the_named_ordinary_exemption(decided):
    """A PARTIAL classification naming a transcribed key: the rule's exempt part
    is taken off the ISR base; an unknown key still blocks."""
    import datetime as _dt
    from app.modules.payroll.engine.jurisdictions.mexico import classification
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    row = {"id": 1, "version": 1, "status": "ACTIVE", "effective_from": "2026-01-01", "effective_to": None,
           "cfdi_node_type": "PERCEPCION", "isr_treatment": "PARTIAL", "isr_exempt_rule_key": "LISR_93_XIV_SUNDAY_PREMIUM",
           "sbc_treatment": "VARIABLE", "infonavit_included": True, "isn_default_included": True}
    line = [{"code": "PD", "kind": "SUNDAY_PREMIUM", "amount": Decimal("500")}]
    (out,) = classification.classify(line, {"PD": row}, _dt.date(2026, 6, 30), "CDMX", _facts(sundays_worked=2))
    assert (out["isr_exempt"], out["isr_taxable"]) == (Decimal("200"), Decimal("300"))
    with pytest.raises(MXBlock) as exc:
        classification.classify(line, {"PD": dict(row, isr_exempt_rule_key="SYN_UNKNOWN")}, _dt.date(2026, 6, 30), "CDMX",
                                _facts(sundays_worked=2))
    assert exc.value.key == "MX_EXEMPTION_RULE_MISSING"


# ── W3-5: interfaces for the decision- / source-blocked seams, and A16 ──

def _content_with(**extra):
    from tests import _mx_engine_helpers as h

    rates = dict(h.SYN_RATES)
    rates.update({k: h.txt(v) for k, v in extra.items()})
    return h.content(rates=rates)


def test_hourly_rate_waits_for_d17_then_uses_the_lft_61_length():
    from app.modules.payroll.engine.jurisdictions.mexico import labor
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    with pytest.raises(MXBlock) as exc:
        labor.hourly_rate(_content_with(), {"workday_type_code": "01"}, Decimal("600"))
    assert _codes(exc) == ["MX_HOURLY_RATE_RULE_MISSING"]
    c = _content_with(mx_hourly_rate_rule="DAILY_SALARY_OVER_JORNADA_HOURS")
    assert labor.hourly_rate(c, {"workday_type_code": "01"}, Decimal("600")) == Decimal("75")       # 600 / 8
    assert labor.hourly_rate(c, {"workday_type_code": "02"}, Decimal("700")) == Decimal("100")      # 700 / 7
    assert labor.hourly_rate(c, {"workday_type_code": "03"}, Decimal("750")) == Decimal("100")      # 750 / 7.5
    with pytest.raises(MXBlock) as exc:
        labor.hourly_rate(c, {"workday_type_code": "08"}, Decimal("600"))
    assert _codes(exc) == ["MX_WORKDAY_TYPE_UNSUPPORTED"]
    assert labor.hourly_rate(c, {"hourly_rate": "90"}, Decimal("600")) == Decimal("90")              # supplied wins
    from app.modules.payroll.engine.countries import mexico_content as content

    assert {k: v[0] for k, v in content.MX_JORNADA_DAILY_HOURS.items()} == {"01": "8", "02": "7", "03": "7.5"}


def test_infonavit_proration_counts_only_the_days_each_notice_is_in_force():
    import datetime as _dt
    from app.modules.payroll.engine.jurisdictions.mexico import infonavit
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    seg = [{"start": _dt.date(2026, 6, 1), "end": _dt.date(2026, 6, 30), "days": Decimal("30"), "sbc": Decimal("500")}]
    notice = {"credit_number": "C1", "notice_type": "RETENCION", "discount_method": "PERCENTAGE", "discount_value": "20",
              "effective_from": "2026-06-11", "effective_to": None, "id": 1}
    rules = dict(mx_infonavit_percentage_basis="SBC_TIMES_DAYS")
    with pytest.raises(MXBlock) as exc:                                                        # no rule: blocks
        infonavit.credits([notice], _dt.date(2026, 6, 1), _dt.date(2026, 6, 30), seg, _content_with(**rules))
    assert _codes(exc) == ["MX_INFONAVIT_PARTIAL_PERIOD"]
    c = _content_with(mx_infonavit_partial_period_rule="PRORATE_BY_DAYS_IN_FORCE", **rules)
    out = infonavit.credits([notice], _dt.date(2026, 6, 1), _dt.date(2026, 6, 30), seg, c)
    assert out["employee"] == Decimal("500") * 20 * Decimal("20") / 100                         # 20 days in force
    overlap = [notice, dict(notice, id=2, effective_from="2026-06-20")]
    with pytest.raises(MXBlock) as exc:
        infonavit.credits(overlap, _dt.date(2026, 6, 1), _dt.date(2026, 6, 30), seg, c)
    assert _codes(exc) == ["MX_INFONAVIT_NOTICE_OVERLAP"]


def test_min_wage_no_withholding_rule_is_transcribed_from_lisr_96():
    from app.modules.payroll.engine.countries import mexico_content as c

    (row,) = [r for r in c.MX_SCALAR_CONTENT if r.key == "mx_min_wage_no_withholding_rule"]
    assert row.text_value == "NO_WITHHOLDING_ZONE_MIN_WAGE_ONLY" and row.source == "S24/S24_DIP_LISR.pdf"
    assert c.MX_SBC_FIXED_INTEGRATION_RULE is None and c.MX_FIXED_DAYS_TERMINATION_RULE is None   # D-18, D-19
