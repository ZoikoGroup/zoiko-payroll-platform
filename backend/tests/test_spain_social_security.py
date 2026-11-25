"""Spain (ZP-ES-ENG-001, docs/spain) Phase 3: the Social Security rule modules.

Fixtures F1, F2, F4 and F5 from spec §21, plus group minimums, partial months,
overtime, AT/EP, SMI and every block. Expected figures are hand-calculated from
the spec's §2/§4/§5 values (the seeded pack rows), each line rounded half-up to
the cent. The pack is read from spain_content, so a changed seed value shows up
here as a failing figure rather than a silent drift. Pure: no database."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.payroll.engine.countries import spain_content as C
from app.modules.payroll.engine.jurisdictions.spain import bases as B
from app.modules.payroll.engine.jurisdictions.spain import errors as E
from app.modules.payroll.engine.jurisdictions.spain import extra_pay as X
from app.modules.payroll.engine.jurisdictions.spain import labour as L
from app.modules.payroll.engine.jurisdictions.spain import social_security as SS
from app.modules.payroll.engine.jurisdictions.spain import solidarity as SOL

AT_EP = "0.015"   # synthetic employer premium for the tests (ES-008: no universal rate exists)


def rate_map(**changes):
    result = {}
    for key, _label, employee, employer, flat, text, row_from, _source in C.RATES:
        result[key] = SimpleNamespace(
            component_key=key,
            employee_rate_pct=Decimal(employee) if employee is not None else None,
            employer_rate_pct=Decimal(employer) if employer is not None else None,
            flat_amount=Decimal(flat) if flat is not None else None,
            text_value=text, effective_from=row_from)
    for key, row in changes.items():
        if row is None:
            result.pop(key, None)
        else:
            result[key] = row
    return result


def d(value):
    return Decimal(str(value))


def run(ordinary, *, overtime=0, prorrata=0, group=5, factor=Decimal(1), contract="INDEFINITE", kind=None,
        at_ep=AT_EP, rates=None):
    rates = rates if rates is not None else rate_map()
    bases = B.compute(ordinary_pay=d(ordinary), overtime_pay=d(overtime), extra_prorrata=d(prorrata), group=group,
                      factor=factor, rate_map=rates)
    ss = SS.compute(bases=bases, contract_type=contract, overtime_kind=kind, employer_at_ep_rate=at_ep, rate_map=rates)
    sol = SOL.compute(remuneration_with_overtime=bases["remuneration_with_overtime"], factor=factor, rate_map=rates)
    return bases, ss, sol


def by_family(ss):
    return {line["family"]: line for line in ss["lines"]}


# ── F1: €5,500 — capped base, excess in solidarity tranche 1 ────────────────
def test_f1_base_is_capped_and_excess_enters_tranche_1():
    bases, ss, sol = run(5500)
    assert bases["common"] == bases["at_ep"] == d("5101.20")
    assert bases["excess_over_maximum"] == d("398.80") == sol["excess"]
    lines = by_family(ss)
    assert (lines["common_contingencies"]["employee"], lines["common_contingencies"]["employer"]) == (
        d("239.76"), d("1203.88"))
    assert (lines["mei"]["employee"], lines["mei"]["employer"]) == (d("7.65"), d("38.26"))
    assert (lines["unemployment"]["employee"], lines["unemployment"]["employer"]) == (d("79.07"), d("280.57"))
    assert (lines["fogasa"]["employee"], lines["fogasa"]["employer"]) == (d("0"), d("10.20"))
    assert (lines["training"]["employee"], lines["training"]["employer"]) == (d("5.10"), d("30.61"))
    assert lines["at_ep"]["employer"] == d("76.52") == ss["at_ep_employer"]
    assert ss["employee_total"] == d("331.58")
    assert ss["employer_total"] == d("1563.52")                                 # AT/EP reported separately
    t1, t2, t3 = sol["tranches"]
    assert (t1["amount"], t1["employee"], t1["employer"]) == (d("398.80"), d("0.76"), d("3.83"))
    assert t2["amount"] == t3["amount"] == d("0")
    assert (sol["employee_total"], sol["employer_total"]) == (d("0.76"), d("3.83"))


# ── F2: €8,000 — the excess splits across all three tranches ────────────────
def test_f2_excess_splits_across_three_tranches():
    bases, _ss, sol = run(8000)
    assert bases["common"] == d("5101.20")
    t1, t2, t3 = sol["tranches"]
    assert (t1["amount"], t1["employee"], t1["employer"]) == (d("510.12"), d("0.97"), d("4.90"))
    assert (t2["amount"], t2["employee"], t2["employer"]) == (d("2040.48"), d("4.29"), d("21.22"))
    assert (t3["amount"], t3["employee"], t3["employer"]) == (d("348.20"), d("0.84"), d("4.25"))
    assert t1["amount"] + t2["amount"] + t3["amount"] == sol["excess"] == d("2898.80")
    assert (sol["employee_total"], sol["employer_total"]) == (d("6.10"), d("30.37"))


@pytest.mark.parametrize("pay, t1", [("5101.20", "0"), ("5101.21", "0.01"), ("5611.32", "510.12"),
                                     ("5611.33", "510.12")])
def test_solidarity_tranche_boundaries_to_the_cent(pay, t1):
    _b, _ss, sol = run(pay)
    assert sol["tranches"][0]["amount"] == d(t1)
    assert sol["tranches"][1]["amount"] == (d("0.01") if pay == "5611.33" else d("0"))


# ── F4: temporary contract under 30 days ────────────────────────────────────
def test_f4_temporary_rates_and_short_contract_surcharge():
    _b, ss, _s = run(1500, contract="TEMPORARY")
    unemployment = by_family(ss)["unemployment"]
    assert unemployment["key"] == "es_unemployment_temporary"
    assert (unemployment["employee"], unemployment["employer"]) == (d("24.00"), d("100.50"))
    surcharge = L.short_contract_surcharge(contract_type="TEMPORARY", date_of_joining=date(2026, 7, 1),
                                           date_of_leaving=date(2026, 7, 20), period_start=date(2026, 7, 1),
                                           period_end=date(2026, 7, 31), exception=None, rate_map=rate_map())
    assert surcharge == {"applies": True, "amount": d("33.62"), "contract_days": 20}


@pytest.mark.parametrize("joining, leaving, exception, contract", [
    (date(2026, 7, 1), date(2026, 7, 30), None, "TEMPORARY"),          # 30 days: not "under 30"
    (date(2026, 7, 1), date(2026, 7, 20), "YES", "TEMPORARY"),         # statutory exception
    (date(2026, 7, 1), date(2026, 7, 20), None, "INDEFINITE"),         # not a fixed-term contract
    (date(2026, 7, 1), date(2026, 8, 5), None, "TEMPORARY"),           # ends after this period
])
def test_no_surcharge_outside_the_rule(joining, leaving, exception, contract):
    result = L.short_contract_surcharge(contract_type=contract, date_of_joining=joining, date_of_leaving=leaving,
                                        period_start=date(2026, 7, 1), period_end=date(2026, 7, 31),
                                        exception=exception, rate_map=rate_map())
    assert result["applies"] is False and result["amount"] == d("0")


# ── F5: 14 payments — prorrata in the base, never counted twice ─────────────
def test_f5_separate_extras_are_prorated_into_the_base_once():
    prorrata = X.monthly_prorrata("SEPARATE_14", "4000")
    assert prorrata == d("333.33")
    ordinary_month, _ss, _s = run(2000, prorrata=prorrata)
    payment_month, _ss2, _s2 = run(2000, prorrata=prorrata)     # the cash extra pay is gross, never a base input
    assert ordinary_month["common"] == payment_month["common"] == d("2333.33")
    assert X.monthly_prorrata("PRORATED_12", None) == d("0")    # already inside the 12 salaries


@pytest.mark.parametrize("policy, amount", [(None, "4000"), ("SOMETIMES", "4000"), ("SEPARATE_14", None),
                                            ("SEPARATE_14", "0")])
def test_extra_pay_facts_block_when_missing(policy, amount):
    with pytest.raises(E.ESCalculationBlockedError) as raised:
        X.monthly_prorrata(policy, amount)
    assert raised.value.key.startswith(E.EMPLOYEE_FACT_MISSING)


# ── bases: minimum, partial month, overtime ──────────────────────────────────
def test_pay_below_the_group_minimum_is_raised_to_it():
    bases, ss, _s = run(1000, group=5)
    assert bases["common"] == bases["at_ep"] == d("1424.40") and bases["raised_to_minimum"] is True
    assert by_family(ss)["common_contingencies"]["employee"] == d("66.95")          # 1,424.40 x 4.70%


def test_partial_month_prorates_minimum_maximum_and_solidarity_thresholds():
    factor = B.period_factor(15, 31)
    assert factor == d("0.5")
    bases, _ss, sol = run(3000, factor=factor)
    assert (bases["minimum"], bases["maximum"], bases["common"]) == (d("712.20"), d("2550.60"), d("2550.60"))
    assert sol["excess"] == d("449.40") and sol["tranches"][0]["amount"] == d("255.06")
    assert B.period_factor(31, 31) == B.period_factor(28, 28) == d("1")            # a whole month is 1


def test_overtime_is_outside_the_common_base_inside_at_ep_with_its_own_contribution():
    bases, ss, _s = run(3000, overtime=200)
    assert (bases["common"], bases["at_ep"]) == (d("3000.00"), d("3200.00"))
    overtime = by_family(ss)["overtime"]
    assert (overtime["key"], overtime["employee"], overtime["employer"]) == ("es_overtime_other", d("9.40"), d("47.20"))
    _b, ss_fm, _s2 = run(3000, overtime=200, kind="FORCE_MAJEURE")
    fm = by_family(ss_fm)["overtime"]
    assert (fm["key"], fm["employee"], fm["employer"]) == ("es_overtime_force_majeure", d("4.00"), d("24.00"))


def test_employer_amounts_never_enter_the_employee_total():
    _b, ss, _s = run(3000)
    assert ss["employee_total"] == sum((l["employee"] for l in ss["lines"]), d(0))
    assert by_family(ss)["fogasa"]["employee"] == by_family(ss)["at_ep"]["employee"] == d("0")


# ── blocks: nothing is guessed ───────────────────────────────────────────────
def test_groups_1_to_3_block_until_their_minimum_is_configured():
    with pytest.raises(E.ESCalculationBlockedError) as raised:
        run(3000, group=2)
    assert raised.value.key == "ES_RATE_MISSING:es_base_min_group_2"
    extra = SimpleNamespace(component_key="es_base_min_group_2", employee_rate_pct=None, employer_rate_pct=None,
                            flat_amount=Decimal("1500"), text_value=None, effective_from=None)
    bases, _ss, _s = run(1000, group=2, rates=rate_map(es_base_min_group_2=extra))
    assert bases["common"] == d("1500.00")


@pytest.mark.parametrize("group, code", [(9, "ES_DAILY_GROUP_NOT_SUPPORTED:9"), (0, "ES_EMPLOYEE_FACT_MISSING"),
                                         ("x", "ES_EMPLOYEE_FACT_MISSING"), (None, "ES_EMPLOYEE_FACT_MISSING")])
def test_contribution_group_validation(group, code):
    with pytest.raises(E.ESCalculationBlockedError) as raised:
        B.contribution_group(group)
    assert raised.value.key.startswith(code)


@pytest.mark.parametrize("at_ep", [None, "", "abc", "-0.01", "1.5"])
def test_missing_or_invalid_at_ep_rate_blocks(at_ep):
    with pytest.raises(E.ESCalculationBlockedError) as raised:
        run(3000, at_ep=at_ep)
    assert raised.value.key == E.AT_EP_RATE_MISSING


def test_missing_contract_type_and_missing_pack_rows_block():
    with pytest.raises(E.ESCalculationBlockedError) as raised:
        run(3000, contract=None)
    assert raised.value.key == "ES_EMPLOYEE_FACT_MISSING:contract_type"
    for key in ("es_mei", "es_fogasa", "es_base_max_monthly", "es_solidarity_t1_upper"):
        with pytest.raises(E.ESCalculationBlockedError) as raised:
            run(8000, rates=rate_map(**{key: None}))
        assert raised.value.key == f"ES_RATE_MISSING:{key}", key


def test_smi_annual_comparison():
    with pytest.raises(E.ESCalculationBlockedError) as raised:
        L.smi_check(monthly_salary="1000", extra_pay_policy="PRORATED_12", extra_pay_annual_amount=None,
                    rate_map=rate_map())
    assert raised.value.key == E.BELOW_SMI
    ok = L.smi_check(monthly_salary="1221", extra_pay_policy="SEPARATE_14", extra_pay_annual_amount="2442",
                     rate_map=rate_map())
    assert ok == {"annual_equivalent": d("17094.00"), "smi_annual": d("17094")}      # 14 x 1,221 exactly


def test_modules_are_pure():
    import inspect

    from app.modules.payroll.engine.jurisdictions.spain import bases, extra_pay, labour, params, social_security, \
        solidarity

    for module in (bases, extra_pay, labour, params, social_security, solidarity):
        source = inspect.getsource(module)
        for forbidden in ("sqlalchemy", "Session", "date.today", "datetime.now", "requests"):
            assert forbidden not in source, (module.__name__, forbidden)
