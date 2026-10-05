"""
tests/test_hong_kong_tenant_support.py
--------------------------------------
Backend support for the Hong Kong tenant UI (gap-closure D-11, D-12, D-16):

  * the employer readiness dashboard is built from the SAME checks as the run
    preflight and the calculator, so it can never say READY for something the
    payroll would block;
  * the IR56 employee-copy delivery is recorded once, with evidence;
  * HK salary bank routing (HKICL bank + branch code) without changing any other
    country's routing.

app.* is imported lazily (collection-order hazard, see conftest.py).
"""

from datetime import date
from types import SimpleNamespace

import pytest

from tests.test_hong_kong_e2e import MAKER, CHECKER, hk, _employee, _month, _other_org, _profile  # noqa: F401


def _readiness(db, org, today=date(2026, 6, 15)):
    from app.modules.payroll import service

    return service.hk_employer_readiness(db, org.id, today=today)


def _codes(result, severity=None):
    return {c["code"] for c in result["checks"] if severity is None or c["severity"] == severity}


# ── D-12 readiness ──────────────────────────────────────────────────────

def test_readiness_reports_the_pack_in_force_and_no_blocks_for_a_complete_employer(db, hk):
    out = _readiness(db, hk.org)
    assert out["pack"]["packId"] == "HK-PAYROLL-2026" and out["pack"]["yearOfAssessment"] == "2026/27"
    assert "BLOCK" not in {c["severity"] for c in out["checks"]}, out["checks"]
    assert out["status"] in ("CLEAR", "REVIEW")
    assert out["workforce"] == {"hongKongEmployees": 1, "withoutStatutoryProfile": 0}
    assert out["salariesTax"].startswith("Employee-assessed")


def test_readiness_blocks_exactly_what_the_engine_blocks(db, hk):
    """An employee without a profile version is BLOCKED on readiness AND the
    calculator refuses them — the two can never disagree."""
    from app.modules.payroll import service
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import HongKongCalculationBlockedError
    from app.modules.payroll.models import PayrollRun

    bare = _employee(db, hk.org.id, "HKNOPROF", date_of_joining=date(2025, 1, 1))
    out = _readiness(db, hk.org)
    assert out["status"] == "BLOCKED"
    assert [c for c in out["checks"] if c["code"] == "HK_PROFILE_MISSING"][0]["employeeId"] == bare.id
    run = PayrollRun(organization_id=hk.org.id, period_label="x", period_start=date(2026, 6, 1),
                     period_end=date(2026, 6, 30), pay_date=date(2026, 6, 30))
    db.add(run)
    db.commit()
    with pytest.raises(HongKongCalculationBlockedError, match="statutory profile"):
        values = service._hk_dry_run_trace(db, run, bare, {}, "standard", [], False)
        if values[1] is not None:
            raise values[1]


def test_readiness_flags_missing_registration_identity_and_expired_insurance(db, hk):
    from app.modules.payroll.models import CompanyComplianceDetails

    comp = db.query(CompanyComplianceDetails).filter_by(organization_id=hk.org.id).one()
    comp.tax_identifiers = {"br_number": "12345678", "ec_insurance_policy_number": "EC-1", "ec_insurance_expiry": "2026-01-31"}
    hk.emp.compliance_fields = {}
    db.commit()
    out = _readiness(db, hk.org)
    blocks = _codes(out, "BLOCK")
    assert {"HK_REGISTRATION_MISSING:ird_employer_file_number", "HK_EC_INSURANCE_EXPIRED", "HK_IDENTITY_MISSING"} <= blocks
    assert "HK_REGISTRATION_MISSING:empf_employer_account" in _codes(out, "WARN")


def test_readiness_without_an_active_pack_is_blocked(db, hk):
    for p in hk.packs:
        p.status = "Draft"
    db.commit()
    out = _readiness(db, hk.org)
    assert "HK_PACK_NOT_ACTIVE" in _codes(out, "BLOCK") and out["pack"] is None


def test_readiness_surfaces_an_overdue_ir56g_as_a_block(db, hk):
    from app.modules.payroll import hk_service

    hk_service.identify_departure(db, hk.org.id, hk.emp.id, date(2026, 6, 30), MAKER.id, identified_on=date(2026, 5, 1))
    out = _readiness(db, hk.org, today=date(2026, 6, 15))       # deadline 30 May has passed
    assert "HK_IR56G_DUE" in _codes(out, "BLOCK")


def test_readiness_is_tenant_scoped(db, hk):
    other = _other_org(db, "HKOTHER")
    out = _readiness(db, other)
    assert out["workforce"]["hongKongEmployees"] == 0 and out["taxClearance"]["openCases"] == 0


# ── D-11 employee copies ────────────────────────────────────────────────

def test_employee_copy_is_recorded_once_with_evidence(db, hk):
    from app.core.exceptions import BadRequestException, NotFoundException
    from app.modules.payroll import hk_service

    case = hk_service.create_event_cases(db, hk.org.id, hk.emp.id, MAKER.id)[0]      # IR56E, status DUE
    with pytest.raises(BadRequestException, match="no completed form"):
        hk_service.record_employee_copy_delivered(db, hk.org.id, case.id, "handed over", MAKER.id)
    case.status = "FILED"
    db.commit()
    with pytest.raises(BadRequestException, match="evidence"):
        hk_service.record_employee_copy_delivered(db, hk.org.id, case.id, "", MAKER.id)
    with pytest.raises(NotFoundException):
        hk_service.record_employee_copy_delivered(db, _other_org(db, "HKX").id, case.id, "x", MAKER.id)
    done = hk_service.record_employee_copy_delivered(db, hk.org.id, case.id, "email 2026-06-01", MAKER.id)
    assert hk_service.serialize_ird_case(done)["employeeCopyDeliveredAt"]
    with pytest.raises(BadRequestException, match="already recorded"):
        hk_service.record_employee_copy_delivered(db, hk.org.id, case.id, "again", MAKER.id)


def test_bir56a_has_no_employee_copy(db, hk):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hk_service
    from app.modules.payroll.models import HkgIrdReportingCase

    cover = HkgIrdReportingCase(organization_id=hk.org.id, form_type="BIR56A", year_of_assessment="2025/26", status="FILED")
    db.add(cover)
    db.commit()
    with pytest.raises(BadRequestException, match="no employee copy"):
        hk_service.record_employee_copy_delivered(db, hk.org.id, cover.id, "x", MAKER.id)


# ── D-16 bank routing ───────────────────────────────────────────────────

def test_hk_bank_routing_uses_hkicl_bank_and_branch_codes():
    from app.modules.payroll import bank_routing as br

    emp = SimpleNamespace(country_code="HK", ifsc=None, compliance_fields={"bank_code": "004", "branch_code": "123"})
    assert br.resolve_routing(emp) == [{"key": "bank_code", "label": "Bank code", "value": "004"},
                                       {"key": "branch_code", "label": "Branch code", "value": "123"}]
    assert (br.btf_routing_value(emp), br.btf_routing_label("HK")) == ("004-123", "Bank-Branch Code")
    assert br.payment_mode_label("HK") == "Bank Transfer"            # no rail is asserted for HK


def test_other_countries_bank_routing_is_unchanged():
    from app.modules.payroll import bank_routing as br

    assert br.ROUTING_COUNTRIES[:6] == ("IN", "UK", "US", "CA", "DE", "AU")
    assert [br.btf_routing_label(c) for c in ("IN", "UK", "US", "CA", "DE", "AU")] == [
        "IFSC", "Sort Code", "ABA Routing #", "Transit No.", "IBAN", "BSB"]


@pytest.mark.parametrize("fields,ok", [({"bank_code": "004", "branch_code": "123"}, True),
                                       ({"bank_code": "04"}, False), ({"branch_code": "12A"}, False)])
def test_hk_bank_code_validation(fields, ok):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.employee_validation import HKEmployeeValidation

    if ok:
        assert HKEmployeeValidation.validate(fields) == fields
    else:
        with pytest.raises(BadRequestException):
            HKEmployeeValidation.validate(fields)


def test_readiness_exposes_the_pack_parameters_the_calculator_resolves(db, hk):
    """D-6: the tenant Tax Configuration view reads the pack in force from here,
    so it can only ever show the values the calculator actually uses."""
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    out = _readiness(db, hk.org)
    rates, slabs, _pack = resolve_tax_configuration(db, "HK", payroll_date=date(2026, 6, 15))
    assert {p["componentKey"] for p in out["parameters"]} == {r.component_key for r in rates}
    assert all(p["sourceDocumentId"] for p in out["parameters"])
    assert {b["ruleType"] for b in out["salariesTaxBands"]} == {"HK_SALARIES_TAX_PROGRESSIVE", "HK_SALARIES_TAX_STANDARD"}
    assert not any("tds" == p["componentKey"] for p in out["parameters"])
