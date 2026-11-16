"""Malaysia Phase 11: payslip lines, report fields and pay-component mapping.

  * the payslip PDF / payslip templates itemise PCB and the employee EPF /
    SOCSO / EIS from the frozen snapshot, so the lines add up to the stored
    total deductions (Poland's PIT / ZUS / health / PPK the same way);
  * custom reports offer the Malaysian snapshot fields and label the reused
    columns with Malaysian names;
  * a run's salary structure maps to Malaysian pay components (basic, fixed
    allowances, overtime, variable extras) and each is classified per
    obligation by the signed earning classes — REVIEW still blocks.
"""
from decimal import Decimal

import pytest

from app.modules.payroll.engine.countries import malaysia
from app.modules.payroll.engine.countries.malaysia import MYCalculationBlockedError
from tests._my_engine_helpers import build_pack, ctx


def _lines(data, country):
    from app.modules.payroll.service import payslip_line_items

    full = {"basicPay": 0, "hra": 0, "specialAllowance": 0, **data}
    _earnings, deductions = payslip_line_items(full, country)
    return deductions


@pytest.fixture
def with_pcb(monkeypatch):
    from app.modules.payroll.engine.jurisdictions.malaysia import pcb

    monkeypatch.setattr(pcb, "compute", lambda pack, **_: {"pcb": Decimal("100.00"), "trace": {"stub": True}})


# ── payslip lines ──────────────────────────────────────────────────────────
def test_malaysian_payslip_lines_reconcile_to_total_deductions(with_pcb):
    from app.modules.payroll import malaysia_service as my
    from app.modules.payroll.engine.resolver import calculate_payroll

    result = calculate_payroll(ctx(), "standard")
    snapshot = {k: v for k, v in my.my_payslip_snapshot(result).items() if k != "frozenContext"}
    data = {"country": "MY", "tds": float(result.tds), "totalDeductions": float(result.total_deductions),
            "basicSalary": 5000, "salary": 5000, "myCalculationSnapshot": snapshot}
    lines = _lines(data, "MY")
    assert lines == [("PCB / MTD", 100.0), ("EPF (Employee)", 550.0), ("SOCSO (Employee)", 24.75),
                     ("EIS (Employee)", 9.9)]
    assert round(sum(v for _l, v in lines), 2) == float(result.total_deductions) == 684.65
    assert ("TDS", 100.0) not in lines                                            # never India's term


def test_polish_payslip_lines_reconcile_to_total_deductions():
    from app.modules.payroll import poland_service as pl
    from app.modules.payroll.engine.resolver import calculate_payroll
    from tests._pl_engine_helpers import ctx as pl_ctx

    result = calculate_payroll(pl_ctx(), "standard")
    snapshot = pl.pl_payslip_snapshot(result)
    data = {"country": "PL", "tds": float(result.tds), "totalDeductions": float(result.total_deductions),
            "plCalculationSnapshot": snapshot}
    lines = _lines(data, "PL")
    labels = [label for label, _v in lines]
    assert labels[0] == "PIT Advance (zaliczka)" and "Health contribution (zdrowotna)" in labels
    assert any(label.startswith("ZUS Pension") for label in labels)
    assert round(sum(v for _l, v in lines), 2) == float(result.total_deductions)


def test_other_countries_and_missing_snapshots_are_unchanged():
    assert _lines({"country": "MY", "tds": 0, "totalDeductions": 0}, "MY") == []
    assert _lines({"country": "IN", "tds": 120, "pf": 300}, "IN") == [("TDS", 120.0), ("Provident Fund (PF)", 300.0)]


# ── report fields ──────────────────────────────────────────────────────────
def test_reports_offer_malaysian_fields_with_malaysian_labels():
    from app.modules.payroll.service import get_available_report_data_fields

    fields = {f["key"]: f for f in get_available_report_data_fields("MY")}
    assert fields["tds"]["label"] == "PCB / MTD"
    assert fields["employer_payroll_tax"]["label"] == "HRD Levy (Employer)"
    for key in ("my_calculation_snapshot.my_epf.employee", "my_calculation_snapshot.my_socso.employer",
                "my_calculation_snapshot.my_eis.employee", "my_calculation_snapshot.my_hrd",
                "my_calculation_snapshot.trace.labour.territory.territory"):
        assert key in fields, key
    assert not any("nric" in k.lower() or "tin" in k.lower().split(".") for k in fields)


def test_report_paths_read_the_frozen_snapshot(with_pcb):
    from app.modules.payroll import malaysia_service as my
    from app.modules.payroll.engine.resolver import calculate_payroll
    from app.modules.payroll.service import _report_json_path_value

    snapshot = my.my_payslip_snapshot(calculate_payroll(ctx(), "standard"))
    assert _report_json_path_value(snapshot, ["my_epf", "employee"]) == "550.00"
    assert _report_json_path_value(snapshot, ["trace", "bases", "EPF", "base"]) == "5000.00"
    assert _report_json_path_value(snapshot, ["trace", "labour", "territory", "territory"]) == "PENINSULAR_LABUAN"


# ── pay-component mapping ──────────────────────────────────────────────────
def test_the_salary_structure_maps_to_malaysian_components():
    from app.modules.payroll.engine.jurisdictions.malaysia.bases import platform_components
    from app.modules.payroll.engine.base import PayrollContext

    c = PayrollContext(gross=Decimal("5300"), basic=Decimal("4000"), hra=Decimal("600"),
                       special_allowance=Decimal("400"), overtime=Decimal("0"),
                       additional_compensation=Decimal("300"), country="MY")
    assert platform_components(c) == {"BASIC_SALARY": Decimal("4000"), "FIXED_ALLOWANCE": Decimal("1000"),
                                      "VARIABLE_ALLOWANCE": Decimal("300")}
    bad = PayrollContext(gross=Decimal("100"), basic=Decimal("4000"), country="MY")
    assert platform_components(bad) is None


def _structure_ctx(pack, **extra):
    return ctx(gross="5000", pack=pack, basic=Decimal("4000"), hra=Decimal("600"),
               special_allowance=Decimal("400"), my_components=None, **extra)


def test_an_unsigned_allowance_treatment_blocks_only_the_obligations_that_need_it():
    error = None
    with pytest.raises(MYCalculationBlockedError) as raised:
        malaysia.calculate(_structure_ctx(build_pack()))
    error = raised.value
    assert error.blocked["EPF"]["code"] == "MY_EARNING_CLASS_REVIEW:EPF:FIXED_ALLOWANCE"
    assert "HRD" not in error.blocked                                             # HRD: fixed allowances INCLUDED
    assert error.partial["components"] == {"BASIC_SALARY": "4000.00", "FIXED_ALLOWANCE": "1000.00"}


def test_with_signed_treatments_a_structured_salary_calculates(with_pcb):
    signed = {(o, "FIXED_ALLOWANCE"): "INCLUDED" for o in ("PCB_NORMAL", "EPF", "SOCSO", "EIS")}
    signed.update({("PCB_ADDITIONAL", "FIXED_ALLOWANCE"): "EXCLUDED", ("MIN_WAGE_BASIC", "FIXED_ALLOWANCE"): "EXCLUDED",
                   ("OT_RATE_BASE", "FIXED_ALLOWANCE"): "EXCLUDED"})
    r = malaysia.calculate(_structure_ctx(build_pack(treatments=signed)))["my_result"]
    assert r["trace"]["components"] == {"BASIC_SALARY": "4000.00", "FIXED_ALLOWANCE": "1000.00"}
    assert r["my_epf"]["employee"] == "550.00" and r["trace"]["bases"]["MIN_WAGE_BASIC"]["base"] == "4000.00"
