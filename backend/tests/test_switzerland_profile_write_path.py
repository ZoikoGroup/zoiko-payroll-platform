"""CH-E1 regression: a Swiss worker's ch_* facts are written through the real
statutory-profile save path (service.create_employee_statutory_profile_version),
validated, carried forward between versions — and the worker then calculates.
Before, the schema and the save path ignored every ch_* field, so the only way
to get a calculable Swiss worker was to insert the profile row directly (as
the other CH test fixtures still do).
"""
from datetime import date
from decimal import Decimal as D

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import service
from app.modules.payroll.models import PayrollEmployee, PayslipItem
from app.modules.payroll.schemas import EmployeeStatutoryProfileCreate
from tests.test_switzerland_service_integration import _run, ch  # noqa: F401


def _new_worker(db, ch):  # noqa: F811
    emp = PayrollEmployee(organization_id=ch.org.id, employee_code="CH-002", name="Second Worker", country_code="CH",
                          ctc=D("96000"), basic=D("96000"), hra=D("0"), date_of_birth=date(1988, 3, 1),
                          date_of_joining=date(2025, 1, 1), pay_frequency="Monthly")
    db.add(emp)
    db.commit()
    return emp


def _save(db, ch, emp, **fields):  # noqa: F811
    data = EmployeeStatutoryProfileCreate(countryCode="CH", **fields)
    return service.create_employee_statutory_profile_version(db, emp.id, ch.org.id, data, actor_id=801)


FULL = dict(effectiveFrom="2026-01-01", chWorkCanton="ch-zh", chResidenceCanton="CH-ZH", chResidenceCountry="ch",
            chQstSubject="yes", chQstCanton="CH-ZH", chQstTariffCode="a", chChildrenCount=0, chChurchTax=False,
            chUvgRiskClass="A1", chWeeklyHours="42")


def test_profile_written_through_the_api_path_is_calculable(db, ch):  # noqa: F811
    emp = _new_worker(db, ch)
    row = _save(db, ch, emp, chBvgPlanSchemeId=ch.bvg.id, chUvgPolicySchemeId=ch.uvg.id, **FULL)
    assert (row.ch_work_canton, row.ch_residence_country, row.ch_qst_subject, row.ch_qst_tariff_code) == \
        ("CH-ZH", "CH", "YES", "A")                                     # normalised upper-case
    assert row.ch_uvg_policy_scheme_id == ch.uvg.id
    run = _run(db, ch.org, 3)
    service.generate_payslips_for_run(db, run, ch.org.id)
    item = db.query(PayslipItem).filter_by(payroll_run_id=run.id, employee_id=emp.id).one()
    assert item.ch_calculation_snapshot and D(str(item.net_pay)) > 0     # resolved and calculated, not blocked


def test_fields_not_sent_carry_forward(db, ch):  # noqa: F811
    emp = _new_worker(db, ch)
    _save(db, ch, emp, chBvgPlanSchemeId=ch.bvg.id, chUvgPolicySchemeId=ch.uvg.id, **FULL)
    second = _save(db, ch, emp, effectiveFrom="2026-06-01", chChildrenCount=1)
    assert second.ch_children_count == 1
    assert (second.ch_work_canton, second.ch_qst_tariff_code, second.ch_uvg_policy_scheme_id) == \
        ("CH-ZH", "A", ch.uvg.id)


@pytest.mark.parametrize("bad", [
    {"chWorkCanton": "ZH"}, {"chQstSubject": "MAYBE"}, {"chResidenceCountry": "CHE"},
    {"chWeeklyHours": "0"}, {"chOtherEmploymentPct": "120"}, {"chChildrenCount": -1},
])
def test_invalid_facts_are_refused(db, ch, bad):  # noqa: F811
    emp = _new_worker(db, ch)
    with pytest.raises(BadRequestException):
        _save(db, ch, emp, **{**FULL, **bad})


def test_scheme_must_be_the_right_type_and_organisation(db, ch):  # noqa: F811
    emp = _new_worker(db, ch)
    with pytest.raises(BadRequestException, match="UVG_POLICY"):
        _save(db, ch, emp, chUvgPolicySchemeId=ch.bvg.id, **FULL)       # a BVG plan is not a UVG policy
