"""BR-E1 regression: a Brazil payslip calculated through the REAL path —
brazil_service.calc_inputs -> engine.resolver.build_context_from_employee ->
calculate_payroll — not the golden harness (which wraps the inputs itself and
so never saw the flat-dict TypeError that broke every in-app calculation).
"""
from datetime import date
from decimal import Decimal

import pytest

from tests.test_brazil_employee_profile import _configured, _er_svc, _org, _profile, br_on  # noqa: F401


def _risk(db, org, est):
    row = _er_svc().create_risk_assignment(db, org.id, est["id"], {
        "calendar_year": 2026, "rat_pct": "2", "fap_factor": "1.0000", "evidence_ref": "FAP 2026 publication"}, 801)
    _er_svc().activate_risk_assignment(db, org.id, row["id"], 802)


def _setup(db):
    org = _org(db)
    emp, est = _configured(db, org)
    _risk(db, org, est)
    _profile(db, org, emp.id, br_establishment_id=est["id"], br_esocial_category="101", br_irrf_dependents_count=0)
    return org, emp


MONTHLY = {"basic": Decimal("5000.00"), "hra": Decimal("0"), "special": Decimal("0"),
           "allowances": Decimal("0"), "overtime": Decimal("0"), "additional": Decimal("0")}


def _calculate(db, emp, monthly):
    from app.modules.payroll import jurisdiction_hooks
    from app.modules.payroll.engine.resolver import build_context_from_employee, calculate_payroll

    inputs = jurisdiction_hooks.call("BR", "calc_inputs", db, None, emp, None, as_of=date(2026, 3, 31), monthly=monthly)
    assert set(inputs) == {"brazil_inputs", "brazil_organization_id"}      # PayrollContext FIELDS, not a flat dict
    ctx = build_context_from_employee(emp, gross=monthly["basic"], basic=monthly["basic"], country="BR",
                                      rate_map={}, slabs=[], brazil_inputs=inputs, pay_date=date(2026, 3, 31),
                                      period_start=date(2026, 3, 1), period_end=date(2026, 3, 31))
    return inputs, calculate_payroll(ctx, "standard")


def test_brazil_payslip_calculates_through_the_real_resolver(db, br_on):  # noqa: F811
    org, emp = _setup(db)
    inputs, result = _calculate(db, emp, MONTHLY)
    assert inputs["brazil_inputs"]["contract_salary"] == "5000.00"          # the MONTHLY basic
    assert inputs["brazil_inputs"]["earnings"] == [{"rubricCode": "BR_SALARIO_BASE", "amount": "5000.00"}]
    br = result.br_result
    # 2026 INSS on 5,000: 1,621 x 7.5% + (2,902.84-1,621) x 9% + (4,354.27-2,902.84) x 12% + (5,000-4,354.27) x 14%
    assert Decimal(br["br_inss_employee"]) == Decimal("501.51")
    assert br["trace"]["contract_salary"] == "5000.00" and br["trace"]["bases"]["base_cp"] == "5000.00"


def test_unmapped_components_block_instead_of_guessing(db, br_on):  # noqa: F811
    from app.modules.payroll.engine.countries.brazil import BrazilCalculationBlockedError

    org, emp = _setup(db)
    with pytest.raises(BrazilCalculationBlockedError) as exc:
        _calculate(db, emp, {**MONTHLY, "hra": Decimal("800.00")})
    assert exc.value.key == "BR_UNMAPPED_EARNING" and "hra" in str(exc.value)


def test_missing_monthly_components_block(db, br_on):  # noqa: F811
    from app.modules.payroll import jurisdiction_hooks
    from app.modules.payroll.engine.countries.brazil import BrazilCalculationBlockedError

    org, emp = _setup(db)
    with pytest.raises(BrazilCalculationBlockedError) as exc:
        jurisdiction_hooks.call("BR", "calc_inputs", db, None, emp, None, as_of=date(2026, 3, 31))
    assert exc.value.key == "BR_MISSING_INPUT"
