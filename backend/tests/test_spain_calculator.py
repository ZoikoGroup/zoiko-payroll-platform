"""Spain (ZP-ES-ENG-001, docs/spain) Phase 5: the country calculator and its wiring.

IRPF is Phase 4 (the AEAT document): until then the real irpf.compute BLOCKS
(pinned below). The other tests replace it with a fixed stand-in (as
test_malaysia_engine stubs PCB) so the Social Security path, the payslip lines
and the breakdown can be proven end to end through the standard dispatcher.
Expected figures are hand-calculated from the seeded spec values. Pure."""
import json
from datetime import date
from decimal import Decimal

import pytest

from app.modules.payroll.engine.jurisdictions.spain import errors as E
from app.modules.payroll.engine.jurisdictions.spain import irpf as IRPF
from tests.test_spain_social_security import rate_map

BASE_FACTS = {"contract_type": "INDEFINITE", "contribution_group": "5", "extra_pay_policy": "PRORATED_12",
              "work_pattern": "FULL_TIME", "at_ep_rate": "0.015"}
STUB_IRPF = Decimal("500.00")


def d(value):
    return Decimal(str(value))


@pytest.fixture()
def stub_irpf(monkeypatch):
    seen = []

    def fake(*, pay_date, monthly_gross, monthly_ss_employee, facts, rate_map):
        seen.append({"pay_date": pay_date, "gross": monthly_gross, "ss": monthly_ss_employee})
        return {"version": IRPF.version_for(pay_date), "rate": d("0.10"), "amount": STUB_IRPF, "stub": True}

    monkeypatch.setattr(IRPF, "compute", fake)
    return seen


def ctx_for(facts=None, *, basic=3000, additional=0, overtime=0, pay_date=date(2026, 7, 31), **kwargs):
    from app.modules.payroll.engine.base import PayrollContext

    basic, additional, overtime = d(basic), d(additional), d(overtime)
    values = dict(country="ES", gross=basic + additional + overtime, basic=basic, overtime=overtime,
                  additional_compensation=additional, pay_date=pay_date, rate_map=rate_map(),
                  es_facts={**BASE_FACTS, **(facts or {})},
                  period_start=pay_date.replace(day=1), period_end=pay_date, date_of_joining=date(2024, 1, 1))
    values.update(kwargs)
    return PayrollContext(**values)


def calc(ctx):
    from app.modules.payroll.engine.countries import spain

    return spain.calculate(ctx)


# ── IRPF is not invented: it blocks until Phase 4 ────────────────────────────
@pytest.mark.parametrize("pay_date, version", [(date(2026, 9, 9), "IRPF-2026-A"), (date(2026, 9, 10), "IRPF-2026-B")])
def test_irpf_blocks_until_the_aeat_document_is_configured(pay_date, version):
    with pytest.raises(E.ESCalculationBlockedError) as raised:
        calc(ctx_for(pay_date=pay_date, period_start=pay_date.replace(day=1)))
    assert raised.value.key == "ES_RATE_MISSING:irpf"
    assert version in str(raised.value)


def test_irpf_version_boundary_is_10_september_2026():
    assert IRPF.version_for(date(2026, 9, 9)) == "IRPF-2026-A"
    assert IRPF.version_for(date(2026, 9, 10)) == "IRPF-2026-B"


# ── F1 through the standard dispatcher ───────────────────────────────────────
def test_f1_payslip_lines_net_and_employer_cost(stub_irpf):
    from app.modules.payroll.engine.resolver import calculate_payroll

    result = calculate_payroll(ctx_for(basic=5500), "standard")
    assert result.social_security == d("332.34")                    # 331.58 ordinary + 0.76 solidarity
    assert result.tds == STUB_IRPF
    assert result.net_pay == d("4667.66")                           # 5,500 - 332.34 - 500
    assert result.employer_social_security == d("1567.35")         # 1,563.52 + 3.83 solidarity
    assert result.employer_occupational_hazard == d("76.52")
    assert result.employer_payroll_tax == d("0")
    snapshot = json.loads(json.dumps(result.es_result))
    assert snapshot["bases"]["common"] == "5101.20" and snapshot["bases"]["excess_over_maximum"] == "398.80"
    assert snapshot["solidarity"]["tranches"][0]["employer"] == "3.83"
    assert snapshot["irpf"]["version"] == "IRPF-2026-A"
    assert snapshot["employer_cost"] == {"social_security": "1567.35", "at_ep": "76.52",
                                         "short_contract_surcharge": "0", "total": "1643.87"}
    assert stub_irpf[0]["ss"] == d("332.34") and stub_irpf[0]["gross"] == d("5500.00")


def test_employer_costs_never_reduce_net(stub_irpf):
    result = calc(ctx_for(basic=3000))
    employee = result["social_security"] + result["tds"]
    assert json.loads(json.dumps(result["es_result"]))["employee_deductions"]["total"] == format(employee, "f")
    assert result["employer_social_security"] > employee                # employer side is larger and separate


# ── F5: the extra-pay month adds cash, never base ────────────────────────────
def test_f5_extra_pay_month_cash_is_gross_but_not_base(stub_irpf):
    facts = {"extra_pay_policy": "SEPARATE_14", "extra_pay_annual_amount": "4000", "extra_pay_months": "6,12"}
    june = calc(ctx_for(facts, basic=2000, additional=2000, pay_date=date(2026, 6, 30)))
    july = calc(ctx_for(facts, basic=2000, pay_date=date(2026, 7, 31)))
    j, k = june["es_result"], july["es_result"]
    assert j["inputs"]["extra_pay_month"] is True and j["pay"]["extra_pay_cash"] == "2000.00"
    assert j["bases"]["common"] == k["bases"]["common"] == "2333.33"      # 2,000 + 4,000 / 12 both months
    assert j["pay"]["gross"] == "4000.00"
    assert j["social_security"]["employee_total"] == k["social_security"]["employee_total"]


def test_additional_compensation_outside_an_extra_pay_month_is_ordinary_pay(stub_irpf):
    result = calc(ctx_for(basic=3000, additional=500))
    assert result["es_result"]["bases"]["common"] == "3500.00"


# ── F4: short temporary contract ending this month ───────────────────────────
def test_f4_surcharge_is_employer_cost_on_the_payslip(stub_irpf):
    result = calc(ctx_for({"contract_type": "TEMPORARY"}, basic=1500, date_of_joining=date(2026, 7, 1),
                          date_of_leaving=date(2026, 7, 20)))
    assert result["employer_payroll_tax"] == d("33.62")
    snapshot = result["es_result"]
    assert snapshot["inputs"]["unemployment_key"] == "es_unemployment_temporary"
    assert snapshot["inputs"]["days_in_alta"] == 20
    assert snapshot["bases"]["factor"] == format(d(20) / d(30), "f")      # partial month: 20 days in alta
    assert snapshot["employer_cost"]["short_contract_surcharge"] == "33.62"


# ── pay adjustments ──────────────────────────────────────────────────────────
def test_unpaid_days_reduce_the_contributable_pay(stub_irpf):
    result = calc(ctx_for(basic=3000, unpaid_leave_days=3))
    assert result["es_result"]["pay"]["unpaid_deduction"] == "300.00"
    assert result["es_result"]["bases"]["common"] == "2700.00"


def test_overtime_is_gross_and_in_the_at_ep_base_only(stub_irpf):
    result = calc(ctx_for(basic=3000, overtime=200))
    bases = result["es_result"]["bases"]
    assert (bases["common"], bases["at_ep"]) == ("3000.00", "3200.00")


# ── blocks ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("facts, code", [
    ({"work_pattern": "PART_TIME"}, E.PART_TIME_NOT_SUPPORTED),
    ({"contribution_group": "9"}, "ES_DAILY_GROUP_NOT_SUPPORTED:9"),
    ({"contribution_group": None}, "ES_EMPLOYEE_FACT_MISSING:contribution_group"),
    ({"contract_type": None}, "ES_EMPLOYEE_FACT_MISSING:contract_type"),
    ({"extra_pay_policy": None}, "ES_EMPLOYEE_FACT_MISSING:extra_pay_policy"),
    ({"at_ep_rate": None}, E.AT_EP_RATE_MISSING),
    ({"extra_pay_policy": "SEPARATE_14", "extra_pay_annual_amount": "2000", "extra_pay_months": "x"},
     "ES_EMPLOYEE_FACT_MISSING:extra_pay_months"),
])
def test_missing_or_unsupported_facts_block(stub_irpf, facts, code):
    with pytest.raises(E.ESCalculationBlockedError) as raised:
        calc(ctx_for(facts))
    assert raised.value.key == code


def test_below_smi_blocks(stub_irpf):
    with pytest.raises(E.ESCalculationBlockedError) as raised:
        calc(ctx_for(basic=1000))
    assert raised.value.key == E.BELOW_SMI


def test_simple_mode_is_blocked():
    from app.modules.payroll.engine.resolver import calculate_payroll

    with pytest.raises(E.ESCalculationBlockedError) as raised:
        calculate_payroll(ctx_for(), "simple")
    assert raised.value.key == "ES_SIMPLE_MODE_UNSUPPORTED"


def test_spain_is_registered_and_never_generic():
    from app.modules.payroll.engine import standard
    from app.modules.payroll.engine.countries import spain

    assert standard._COUNTRY_CALC["ES"] is spain.calculate
    assert standard._COUNTRY_CALC["ES"] is not standard._calc_generic


def test_context_and_payslip_wiring():
    import inspect
    from types import SimpleNamespace

    from app.modules.payroll import service
    from app.modules.payroll.engine.resolver import build_context_from_employee

    employee = SimpleNamespace(compliance_fields={**BASE_FACTS}, work_state="Community of Madrid",
                               date_of_joining=date(2024, 1, 1), date_of_leaving=None, employment_type=None)
    ctx = build_context_from_employee(employee, gross=d(3000), basic=d(3000), country="ES")
    assert ctx.es_facts["contract_type"] == "INDEFINITE" and ctx.es_facts["work_state"] == "Community of Madrid"
    assert build_context_from_employee(employee, gross=d(3000), basic=d(3000), country="AE").es_facts is None
    assert '"es_calculation_snapshot": result.es_result' in inspect.getsource(service._compute_payslip_values)
