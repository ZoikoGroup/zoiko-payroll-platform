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
    assert _codes(exc) == ["MX_FINIQUITO_ORDINARY_INCOME_UNSUPPORTED"]


def test_every_termination_rule_quotes_its_wording():
    r = _r()
    for rule in list(r.TERMINATION_REASONS.values()) + [r.FINIQUITO_RULE]:
        assert rule.citations and all("'" in ref and "PDF p" in ref for _src, ref in rule.citations)
