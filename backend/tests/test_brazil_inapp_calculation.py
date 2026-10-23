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


def test_vale_transporte_uses_the_working_days_of_the_month(db, br_on):  # noqa: F811
    """BR-E3: the VT benefit is daily cost x working days (March 2026: 22
    Mon-Fri days, minus unpaid leave); the deduction was capped at ONE day."""
    from app.modules.payroll.models import PayrollBrValeTransporteElection

    org, emp = _setup(db)
    db.add(PayrollBrValeTransporteElection(organization_id=org.id, employee_id=emp.id, elected=True,
                                           daily_cost=Decimal("10.00"), effective_from=date(2026, 1, 1),
                                           status="ACTIVE", evidence_ref="VT declaration"))
    db.commit()
    inputs, result = _calculate(db, emp, MONTHLY)
    assert inputs["brazil_inputs"]["vt_benefit"] == Decimal("220.00")
    assert Decimal(result.br_result["br_vale_transporte_deduction"]) == Decimal("220.00")   # < 6% of 5,000
    inputs, _ = _calculate(db, emp, {**MONTHLY, "unpaid_leave_days": 2})
    assert inputs["brazil_inputs"]["vt_benefit"] == Decimal("200.00")


@pytest.mark.parametrize("country, field", [("BR", "brCalculationSnapshot"), ("SA", "saCalculationSnapshot")])
def test_payslip_response_carries_the_country_snapshot(country, field):
    """BR-E5: the BR snapshot was never emitted (the breakdown panel never
    rendered); SA's was emitted but stripped by the response model."""
    from app.modules.payroll.schemas import PayslipItemResponse

    assert field in PayslipItemResponse.model_fields
    snap = {"br_inss_employee": "501.51"} if country == "BR" else {"employee_pension": "950"}
    dumped = PayslipItemResponse.model_construct(**{field: snap}).model_dump()
    assert dumped[field] == snap



def test_serialized_brazil_payslip_carries_the_snapshot(db, br_on):  # noqa: F811
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollRun, PayslipItem

    org, emp = _setup(db)
    run = PayrollRun(organization_id=org.id, period_label="2026-03", period_start=date(2026, 3, 1),
                     period_end=date(2026, 3, 31), pay_date=date(2026, 3, 31))
    db.add(run)
    db.flush()
    item = PayslipItem(payroll_run_id=run.id, employee_id=emp.id, organization_id=org.id, employee_name=emp.name,
                       country_code="BR", gross_pay=Decimal("5000"), net_pay=Decimal("4000"),
                       br_calculation_snapshot={"br_inss_employee": "501.51"})
    db.add(item)
    db.flush()
    payload = service._serialize_payslip(item, run, country="BR")
    assert payload["brCalculationSnapshot"] == {"br_inss_employee": "501.51"}
