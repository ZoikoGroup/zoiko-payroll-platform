"""
tests/test_singapore_phase67_ir8a_guard.py
------------------------------------------
Phase 6.7 (G3) — once IRAS has ACKNOWLEDGED an organization's IR8A for an
income year, a further filing is an IRAS "Modify previously submitted data"
Revision (full values) or Amendment (differences only) — IRAS Quick Guide on
the Submit Employment Income Records digital service, 15 Sep 2025. Zoiko has
no revision/amendment workflow yet (design: docs/SINGAPORE_G3_IR8A_AMENDMENT_
AND_AIS_DECISION.md), so a new extract can be prepared for reference but is
never recorded as another submission. The refusal is audited. A REJECTED
filing may still be resubmitted; other organizations and other years are
unaffected. app.* imports are lazy (tests/_db_safety.py).
"""

from datetime import date
from decimal import Decimal

import pytest


def _extract(db, org, template, year, emp_code):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollStatus, PayslipItem
    from tests.test_singapore import MAKER, _run, _sg_employee

    emp = _sg_employee(db, org.id, emp_code)
    run = _run(db, org, date(year, 3, 31), f"IR8A {org.id} {year} {emp_code}")
    run.status = PayrollStatus.APPROVED
    db.add(PayslipItem(payroll_run_id=run.id, employee_id=emp.id, organization_id=org.id, employee_name=emp.name,
                       country_code="SG", gross_pay=Decimal("6000"), employee_pension=Decimal("1200")))
    db.commit()
    return service.generate_sg_ir8a(db, org.id, template.id, year, actor_id=MAKER.id)


def _file(db, org, report, outcome):
    from app.modules.payroll import service
    from tests.test_singapore import CHECKER

    service.transition_sg_ir8a(db, org.id, report.id, "SUBMITTED_MANUALLY", actor_id=CHECKER.id, reference=f"MYTAX-{report.id}")
    return service.transition_sg_ir8a(db, org.id, report.id, outcome, actor_id=CHECKER.id, reference=f"IRAS-{report.id}")


def _template(db):
    from tests.test_singapore import _ir8a_template

    return _ir8a_template(db)


def test_after_acknowledgement_a_new_extract_is_never_recorded_as_another_submission(db, organization):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import GeneratedReport, TaxConfigurationAudit
    from tests.test_singapore import CHECKER

    template = _template(db)
    first = _extract(db, organization, template, 2026, "G3A")
    _file(db, organization, first, "ACKNOWLEDGED")
    again = _extract(db, organization, template, 2026, "G3B")                        # reference extract: allowed
    with pytest.raises(BadRequestException, match="Revision or Amendment"):
        service.transition_sg_ir8a(db, organization.id, again.id, "SUBMITTED_MANUALLY", actor_id=CHECKER.id,
                                   reference="MYTAX-2")
    db.expire_all()
    assert db.query(GeneratedReport).get(first.id).status == "ACKNOWLEDGED"        # acknowledged evidence untouched
    assert db.query(GeneratedReport).get(again.id).status == "Generated"            # still EXPORT_READY
    [row] = db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "sg_ir8a",
                                                   TaxConfigurationAudit.action == "refused").all()
    assert (row.entity_id, row.actor_id, row.new_value["acknowledgedReportId"]) == (again.id, CHECKER.id, first.id)


def test_a_rejected_filing_can_still_be_resubmitted(db, organization):
    from app.modules.payroll import service
    from tests.test_singapore import CHECKER

    template = _template(db)
    first = _extract(db, organization, template, 2026, "G3R")
    _file(db, organization, first, "REJECTED")
    again = _extract(db, organization, template, 2026, "G3S")
    out = service.transition_sg_ir8a(db, organization.id, again.id, "SUBMITTED_MANUALLY", actor_id=CHECKER.id,
                                     reference="MYTAX-RESUBMIT")
    assert out["submissionStatus"] == "SUBMITTED_MANUALLY"


def test_another_organizations_acknowledgement_does_not_block(db, organization):
    from app.modules.payroll import service
    from tests.test_singapore import CHECKER, _other_org

    template = _template(db)
    other = _other_org(db, "G3OTHER")
    _file(db, other, _extract(db, other, template, 2026, "G3O"), "ACKNOWLEDGED")
    mine = _extract(db, organization, template, 2026, "G3M")
    out = service.transition_sg_ir8a(db, organization.id, mine.id, "SUBMITTED_MANUALLY", actor_id=CHECKER.id,
                                     reference="MYTAX-MINE")
    assert out["submissionStatus"] == "SUBMITTED_MANUALLY"


def test_an_acknowledged_different_year_does_not_block(db, organization):
    from app.modules.payroll import service
    from tests.test_singapore import CHECKER

    template = _template(db)
    _file(db, organization, _extract(db, organization, template, 2025, "G3Y"), "ACKNOWLEDGED")
    this_year = _extract(db, organization, template, 2026, "G3Z")
    out = service.transition_sg_ir8a(db, organization.id, this_year.id, "SUBMITTED_MANUALLY", actor_id=CHECKER.id,
                                     reference="MYTAX-2026")
    assert out["submissionStatus"] == "SUBMITTED_MANUALLY"
