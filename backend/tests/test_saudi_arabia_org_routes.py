"""tests/test_saudi_arabia_org_routes.py
--------------------------------------
Org-scoped Saudi Arabia ledger routes (/api/payroll/saudi-arabia/...) used by
the org Compliance Centre: GOSI liability, EOS ledger, final settlement, WPS
and the org-wide correction list. They are thin twins of the Super Admin
routes and call the same saudi_arabia_service functions; what is tested here
is the org scoping — the caller's own organisation only, and an explicit
organizationId that differs is refused (403).

Route functions are called directly with the caller as current_user (the
dependency-level role/writeable checks are FastAPI's own and are asserted on
the route registration instead).
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


def _other_org(db):
    from app.modules.organizations.models import Organization

    org = Organization(organization_name="Other Org", organization_code="OTHERORG")
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def _user(org, user_id=11):
    return SimpleNamespace(id=user_id, organization_id=org.id)


def _employee(db, org, code="E1", joining=date(2020, 1, 1)):
    from app.modules.payroll.models import PayrollEmployee

    emp = PayrollEmployee(organization_id=org.id, employee_code=code, name=f"Emp {code}",
                          date_of_joining=joining, basic=Decimal("10000"), country_code="SA")
    db.add(emp)
    db.flush()
    return emp


def _run(db, org, status="Approved"):
    from app.modules.payroll.models import PayrollRun

    run = PayrollRun(organization_id=org.id, period_label="Mar 2026", period_start=date(2026, 3, 1),
                     period_end=date(2026, 3, 31), pay_date=date(2026, 3, 31), status=status)
    db.add(run)
    db.flush()
    return run


def _payslip(db, org, run, emp, snapshot=None, net="8000"):
    from app.modules.payroll.models import PayslipItem

    item = PayslipItem(payroll_run_id=run.id, employee_id=emp.id, organization_id=org.id,
                       employee_name=emp.name, country_code="SA", gross_pay=Decimal("10000"),
                       net_pay=Decimal(net), sa_calculation_snapshot=snapshot or {
                           # The engine's real stored shape (saudi_arabia.calculate()["sa_result"]).
                           "sa_contribution_month": "2026-03", "sa_contributory_wage": "10000",
                           "employee_pension": "950", "employer_pension": "1050",
                           "social_security": "75", "employer_social_security": "75",
                           "employer_occupational_hazard": "200"})
    db.add(item)
    db.flush()
    return item


def test_all_org_routes_are_registered_with_the_right_guards():
    from app.modules.payroll.router import payroll_router

    expected = {
        ("GET", "/saudi-arabia/gosi-liabilities"), ("POST", "/saudi-arabia/runs/{run_id}/gosi-liability"),
        ("GET", "/saudi-arabia/eos-ledger"), ("POST", "/saudi-arabia/runs/{run_id}/eos-accrual"),
        ("GET", "/saudi-arabia/final-settlements"), ("POST", "/saudi-arabia/final-settlements"),
        ("POST", "/saudi-arabia/final-settlements/{settlement_id}/approve"),
        ("POST", "/saudi-arabia/final-settlements/{settlement_id}/pay"),
        ("GET", "/saudi-arabia/wps-files"), ("POST", "/saudi-arabia/runs/{run_id}/wps-file"),
        ("GET", "/saudi-arabia/wps-files/{wps_file_id}/observations"),
        ("POST", "/saudi-arabia/wps-files/{wps_file_id}/accepted"),
        ("POST", "/saudi-arabia/wps-files/{wps_file_id}/rejected"),
        ("GET", "/saudi-arabia/corrections"),
    }
    routes = {}
    for r in payroll_router.routes:
        for m in getattr(r, "methods", set()):
            routes[(m, r.path.replace(payroll_router.prefix, "", 1))] = r
    missing = expected - set(routes)
    assert not missing, missing
    for (method, path), route in routes.items():
        if (method, path) not in expected:
            continue
        deps = {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}
        assert "get_current_payroll_operator" in deps, path
        if method == "POST":
            # require_writeable_workspace() returns an inner _check function
            assert any(getattr(d.call, "__qualname__", "").startswith("require_writeable_workspace")
                       for d in route.dependant.dependencies), path


def test_gosi_liability_is_scoped_to_the_callers_org(db, organization):
    from app.modules.payroll import router

    other = _other_org(db)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))

    built = router.build_sa_gosi_liability_org(run.id, db=db, current_user=_user(organization))
    assert built.total_due == Decimal("2350")
    assert [r.id for r in router.list_sa_gosi_liabilities_org(None, db=db, current_user=_user(organization))] == [built.id]
    assert router.list_sa_gosi_liabilities_org(None, db=db, current_user=_user(other)) == []
    with pytest.raises(HTTPException) as exc:
        router.list_sa_gosi_liabilities_org(other.id, db=db, current_user=_user(organization))
    assert exc.value.status_code == 403
    with pytest.raises(Exception):
        router.build_sa_gosi_liability_org(run.id, db=db, current_user=_user(other))  # not their run


def test_wps_routes_build_list_observe_and_accept(db, organization):
    from app.modules.payroll import router

    other = _other_org(db)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))

    built = router.build_sa_wps_file_org(run.id, db=db, current_user=_user(organization))
    file_id = built["file"].id
    assert [f.id for f in router.list_sa_wps_files_org(None, db=db, current_user=_user(organization))] == [file_id]
    assert router.list_sa_wps_files_org(None, db=db, current_user=_user(other)) == []
    observations = router.list_sa_wps_observations_org(file_id, None, db=db, current_user=_user(organization))
    assert isinstance(observations, list)
    with pytest.raises(Exception):
        router.list_sa_wps_observations_org(file_id, None, db=db, current_user=_user(other))
    accepted = router.accept_sa_wps_file_org(file_id, db=db, current_user=_user(organization))
    assert accepted.status == "ACCEPTED"


def test_final_settlement_routes_create_approve_pay(db, organization):
    from app.modules.payroll import router, saudi_arabia_service as svc
    from app.modules.payroll.models import ContributionRate, JurisdictionPack
    from app.modules.payroll.schemas import SaFinalSettlementCreateRequest, SaFinalSettlementPayRequest

    pack = JurisdictionPack(pack_id="SA-PAYROLL-2026", version="1.0", jurisdiction_country="SA", pack_type="tax",
                            effective_from=date(2026, 1, 1), status="Active")
    db.add(pack)
    db.flush()
    for key, flat, text in (("sa_eos_first_5_years_months", Decimal("0.5"), None),
                            ("sa_eos_after_5_years_months", Decimal("1.0"), None),
                            ("sa_eos_resign_frac_under_2", None, "0"), ("sa_eos_resign_frac_2_to_5", None, "1/3"),
                            ("sa_eos_resign_frac_5_to_10", None, "2/3"), ("sa_eos_resign_frac_10_plus", None, "1")):
        db.add(ContributionRate(organization_id=None, component_key=key, label=key, employee_share="-",
                                employer_share="-", total="-", flat_amount=flat, text_value=text,
                                jurisdiction_country="SA", jurisdiction_pack_id=pack.id))
    db.flush()
    emp = _employee(db, organization)
    svc.create_sa_contract_version(db, organization.id, emp.id, {
        "effectiveFrom": "2026-01-01", "contractType": "UNLIMITED", "basicWage": "10000"})

    data = SaFinalSettlementCreateRequest(employeeId=emp.id, terminationDate=date(2026, 2, 1),
                                          terminationType="TERMINATION", noticePeriodDays=30, repatriationPay=Decimal("500"))
    row = router.build_sa_final_settlement_org(data, db=db, current_user=_user(organization, user_id=1))
    assert row.status == "DRAFT"
    listed = router.list_sa_final_settlements_org(None, None, db=db, current_user=_user(organization))
    assert [s.id for s in listed] == [row.id]
    approved = router.approve_sa_final_settlement_org(row.id, db=db, current_user=_user(organization, user_id=2))
    assert approved.status == "APPROVED"
    paid = router.pay_sa_final_settlement_org(row.id, SaFinalSettlementPayRequest(paymentReference="REF-1"),
                                              db=db, current_user=_user(organization, user_id=2))
    assert paid.status == "PAID"


def test_org_corrections_lists_only_this_orgs_correction_deltas(db, organization):
    from app.modules.payroll import router

    other = _other_org(db)
    run = _run(db, organization)
    emp = _employee(db, organization)
    original = _payslip(db, organization, run, emp)
    correction_run = _run(db, organization)          # a correction delta lives in its own run
    delta = _payslip(db, organization, correction_run, emp, snapshot={"correction": {
        "originalPayslipId": original.id, "deltas": {"net": "-100"}, "totalsAll": {"net": "7900"}}})
    other_run = _run(db, other)
    other_emp = _employee(db, other, code="O1")
    other_original = _payslip(db, other, other_run, other_emp)
    _payslip(db, other, _run(db, other), other_emp, snapshot={"correction": {"originalPayslipId": other_original.id}})
    db.commit()

    rows = router.list_sa_org_corrections(None, db=db, current_user=_user(organization))
    assert [r["payslipId"] for r in rows] == [delta.id]
    assert rows[0]["originalPayslipId"] == original.id
    assert rows[0]["countryCode"] == "SA"
    assert rows[0]["deltas"] == {"net": "-100"}
    with pytest.raises(HTTPException):
        router.list_sa_org_corrections(other.id, db=db, current_user=_user(organization))
