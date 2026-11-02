"""Japan Phase 5: organisation writers, approvals, run binding and My Number
vault boundary (ZP-JP-ENG-001)."""

from datetime import date, datetime
from decimal import Decimal
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.config import settings
from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import japan_my_number as mn
from app.modules.payroll import japan_service as jp
from app.modules.payroll.models import (
    PayrollEmployee, PayrollJpEmployerRegistration, PayrollJpResidentTaxAssessment,
    PayrollJpWorkerTaxProfile, PayrollRun, PayslipItem, PayrollStatus,
)

KEY = "a" * 32
FINGERPRINT_KEY = "f" * 32
WEIGHTS = (6, 5, 4, 3, 2, 7, 6, 5, 4, 3, 2)


def _number(body="12345678901"):
    total = sum(int(digit) * weight for digit, weight in zip(body, WEIGHTS))
    check = 11 - (total % 11)
    return body + str(0 if check >= 10 else check)


@pytest.fixture()
def employee(db, organization):
    row = PayrollEmployee(organization_id=organization.id, employee_code="JP-1", name="Hanako Sato")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _employer(organization, effective_from=date(2026, 1, 1)):
    return {
        "effective_from": effective_from,
        "health_insurer_type": "KYOKAI_KENPO",
        "health_insurer_prefecture": "13",
        "ei_industry_class": "GENERAL",
    }


def test_employer_registration_versions_are_four_eyes_and_supersede(db, organization):
    first = jp.record_employer_registration(db, organization.id, _employer(organization), 1)
    db.commit()
    assert first.status == "DRAFT"
    with pytest.raises(BadRequestException, match="four-eyes"):
        jp.approve_employer_registration(db, organization.id, first.id, 1)
    assert first.status == "DRAFT"

    jp.approve_employer_registration(db, organization.id, first.id, 2)
    db.commit()
    assert first.status == "ACTIVE" and first.approved_by_id == 2

    second = jp.record_employer_registration(
        db, organization.id, _employer(organization, date(2027, 1, 1)), 1)
    jp.approve_employer_registration(db, organization.id, second.id, 2)
    db.commit()
    assert second.status == "ACTIVE"
    assert first.status == "SUPERSEDED" and first.effective_to == date(2026, 12, 31)


def test_worker_tax_profile_and_unknown_fields_fail_closed(db, organization, employee):
    profile = jp.record_worker_tax_profile(
        db, organization.id, employee.id,
        {"effective_from": date(2026, 1, 1), "residency_status": "RESIDENT",
         "declaration_class": "PRIMARY", "dependants_count": 1}, 1)
    jp.approve_worker_tax_profile(db, organization.id, profile.id, 2)
    db.commit()
    assert profile.status == "ACTIVE" and profile.dependants_count == 1

    with pytest.raises(BadRequestException, match="unknown field"):
        jp.record_worker_tax_profile(
            db, organization.id, employee.id,
            {"effective_from": date(2026, 1, 1), "resident_tax_estimate": "1"}, 1)


def test_resident_tax_notice_needs_exactly_twelve_amounts(db, organization, employee):
    amounts = {f"2026-{month:02d}": "1000" for month in range(1, 13)}
    body = {
        "municipality_code": "131016", "fiscal_notice_year": 2026, "notice_id": "N-1",
        "received_on": date(2026, 5, 20), "first_deduction_month": date(2026, 6, 1),
        "monthly_amounts": amounts, "total_amount": "12000", "source_hash": "a" * 64,
    }
    row = jp.record_resident_tax_assessment(db, organization.id, employee.id, body, 1)
    jp.approve_resident_tax_assessment(db, organization.id, row.id, 2)
    db.commit()
    assert row.status == "APPROVED" and row.version == 1
    assert len(row.monthly_amounts) == 12

    with pytest.raises(BadRequestException, match="exactly twelve"):
        jp.record_resident_tax_assessment(
            db, organization.id, employee.id,
            {**body, "monthly_amounts": {"2026-01": "1000"}, "notice_id": "N-2"}, 1)


def test_my_number_is_row_bound_and_deletion_nulls_ciphertext(db, organization, employee,
                                                              monkeypatch):
    monkeypatch.setattr(settings, "JP_MY_NUMBER_KEYRING", json.dumps({"1": KEY}))
    monkeypatch.setattr(settings, "JP_MY_NUMBER_FINGERPRINT_KEY", FINGERPRINT_KEY)
    number = _number()

    row = jp.create_my_number(db, organization.id, employee.id,
                              {"myNumber": number, "subjectType": "EMPLOYEE"}, 1)
    db.commit()
    assert number not in (row.ciphertext or "")
    owner = mn.vault_owner(organization.id, employee.id, row.id)
    assert mn.decrypt(row.ciphertext, row.key_version, owner=owner) == number

    with pytest.raises(mn.MyNumberError):
        mn.decrypt(row.ciphertext, row.key_version,
                   owner=mn.vault_owner(organization.id, employee.id + 1, row.id))

    request = jp.request_my_number_reveal(db, organization.id, row.id, "Year-end filing", 1)
    db.commit()
    with pytest.raises(BadRequestException, match="four-eyes"):
        jp.approve_my_number_reveal(db, organization.id, row.id, 1)
    jp.approve_my_number_reveal(db, organization.id, row.id, 2)
    db.commit()
    assert request.action == "REVEAL_REQUESTED"
    assert jp.reveal_my_number(db, organization.id, row.id, 2)["myNumber"] == number

    jp.delete_my_number(db, organization.id, row.id, 2)
    db.commit()
    assert row.status == "DELETED" and row.ciphertext is None
    assert jp.list_my_numbers(db, organization.id, employee.id)[0]["masked"] == mn.masked()


def _snapshot(employee_id, value="1"):
    return {"jp_calculation_snapshot": {"employeeId": employee_id, "jp_result": {"jp_wht": value}}}


def test_run_approval_binds_every_frozen_japan_snapshot(db, organization, employee):
    run = PayrollRun(organization_id=organization.id, period_label="Jun 2026",
                     period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
                     pay_date=date(2026, 6, 25), status="REVIEW")
    db.add(run)
    db.flush()
    slip = PayslipItem(payroll_run_id=run.id, employee_id=employee.id,
                       organization_id=organization.id, employee_name=employee.name,
                       country_code="JP", jp_calculation_snapshot=_snapshot(employee.id))
    db.add(slip)
    db.commit()

    # Phase 8: the run's exceptions need a second person's approval first.
    from app.modules.payroll import japan_lifecycle
    with pytest.raises(HTTPException):
        jp.before_run_transition(db, run, PayrollStatus.APPROVED, 1)
    for exception in japan_lifecycle.jp_run_exceptions(db, run):
        japan_lifecycle.approve_jp_run_exception(
            db, organization_id=organization.id, run_id=run.id, key=exception["key"], approver_id=2)
    jp.before_run_transition(db, run, PayrollStatus.APPROVED, 1)
    assert run.jp_approval_fingerprint

    slip.jp_calculation_snapshot = _snapshot(employee.id, value="2")
    db.commit()
    with pytest.raises(HTTPException) as excinfo:
        jp.before_run_transition(db, run, PayrollStatus.AUTHORIZED, 1)
    assert excinfo.value.status_code == 409


def test_missing_snapshot_blocks_japan_approval(db, organization, employee):
    run = PayrollRun(organization_id=organization.id, period_label="Jun 2026",
                     period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
                     pay_date=date(2026, 6, 25), status="REVIEW")
    db.add(run)
    db.flush()
    db.add(PayslipItem(payroll_run_id=run.id, employee_id=employee.id,
                       organization_id=organization.id, employee_name=employee.name,
                       country_code="JP", jp_calculation_snapshot=None))
    db.commit()
    with pytest.raises(HTTPException) as excinfo:
        jp.before_run_transition(db, run, PayrollStatus.APPROVED, 1)
    assert excinfo.value.status_code == 409
    assert "no frozen JP calculation snapshot" in excinfo.value.detail


def test_japan_router_is_dormant_until_onboarding_is_enabled(db, organization, monkeypatch):
    from app.modules.payroll import japan_dormancy, japan_org_router, service

    user = SimpleNamespace(id=1, organization_id=organization.id)
    monkeypatch.setattr(japan_dormancy, "onboarding_enabled", lambda: False)
    with pytest.raises(NotFoundException):
        japan_org_router.require_japan_tenant(user, db)

    monkeypatch.setattr(japan_dormancy, "onboarding_enabled", lambda: True)
    monkeypatch.setattr(service, "_resolve_org_country", lambda _db, _org: "US")
    with pytest.raises(NotFoundException):
        japan_org_router.require_japan_tenant(user, db)

    monkeypatch.setattr(service, "_resolve_org_country", lambda _db, _org: "JP")
    assert japan_org_router.require_japan_tenant(user, db) is None


def test_summary_and_template_hooks_stay_fail_closed(db):
    summary = jp.statutory_summary(db)
    assert summary["available"] is False
    assert summary["jurisdiction"] == "JP"
    assert jp._jp_template_activation_refusal(
        db, SimpleNamespace(jurisdiction_country="JP", report_type="WITHHOLDING"), 1)
    assert jp._jp_template_activation_refusal(
        db, SimpleNamespace(jurisdiction_country="US", report_type="W2"), 1) is None


def test_assessment_money_is_stored_verbatim_not_derived():
    assert jp._money("12000", "total") == Decimal("12000")
    with pytest.raises(BadRequestException):
        jp._money("12,000", "total")

def _prior_run(db, organization, employee, pay_date, *, status=PayrollStatus.PAID.value,
               kind="BONUS", health_base=None, pension_base=None, wht_base=None):
    run = PayrollRun(organization_id=organization.id, period_label=str(pay_date),
                     period_start=pay_date.replace(day=1), period_end=pay_date,
                     pay_date=pay_date, status=status)
    db.add(run)
    db.flush()
    snapshot = {"jp_payment_kind": kind}
    if kind == "BONUS" or health_base is not None or pension_base is not None:
        snapshot["jp_bonus"] = {
            "jp_bonus_health_sba_base": health_base or "0",
            "jp_bonus_pension_sba_base": pension_base or "0",
        }
    if wht_base is not None:
        snapshot["jp_wht_base"] = wht_base
    db.add(PayslipItem(payroll_run_id=run.id, employee_id=employee.id,
                       organization_id=organization.id, employee_name=employee.name,
                       country_code="JP", jp_calculation_snapshot=snapshot))
    db.commit()
    return run


def test_bonus_priors_read_nested_cap_bases(db, organization, employee):
    _prior_run(db, organization, employee, date(2026, 5, 25),
               health_base="230000", pension_base="300000")
    _prior_run(db, organization, employee, date(2026, 6, 10),
               health_base="100000", pension_base="200000")

    priors = jp._jp_bonus_priors(db, organization.id, employee.id, date(2026, 6, 25))
    assert priors["ytd_health_sba"] == Decimal("330000")
    assert priors["month_pension_sba"] == Decimal("200000")


def test_bonus_paid_inside_a_salary_payment_counts_toward_the_caps(db, organization, employee):
    _prior_run(db, organization, employee, date(2026, 5, 25), kind="SALARY",
               health_base="230000", pension_base="300000", wht_base="256050")
    _prior_run(db, organization, employee, date(2026, 6, 10), kind="SALARY",
               health_base="100000", pension_base="200000")

    priors = jp._jp_bonus_priors(db, organization.id, employee.id, date(2026, 6, 25))
    assert priors["ytd_health_sba"] == Decimal("330000")
    assert priors["month_pension_sba"] == Decimal("200000")


def test_salary_plus_bonus_loads_prior_bonus_figures(db, organization, employee, monkeypatch):
    employee.compliance_fields = {"jp_components": {"BONUS": "500000"}}
    db.commit()
    called = []
    monkeypatch.setattr(jp, "_jp_one_active", lambda *_a, **_k: None)
    monkeypatch.setattr(jp, "_jp_events_for_month", lambda *_a, **_k: [])
    monkeypatch.setattr(jp, "_jp_bonus_priors", lambda *_a, **_k: called.append(True) or {
        "ytd_health_sba": Decimal("1"), "month_pension_sba": Decimal("2"),
        "prior_month_pay_after_si": Decimal("3"),
    })

    inputs = jp.resolve_jp_calc_inputs(db, organization.id, employee, date(2026, 6, 25))
    assert called
    assert inputs["jp_payment_kind"] == "SALARY"
    assert inputs["jp_prior_month_pay_after_si"] == Decimal("3")


def test_prior_salary_is_previous_calendar_month_only(db, organization, employee):
    _prior_run(db, organization, employee, date(2026, 2, 25), kind="SALARY", wht_base="999999")
    _prior_run(db, organization, employee, date(2026, 3, 25), kind="SALARY", wht_base="300000")

    priors = jp._jp_bonus_priors(db, organization.id, employee.id, date(2026, 4, 25))
    assert priors["prior_month_pay_after_si"] == Decimal("300000")

    assert jp._jp_bonus_priors(
        db, organization.id, employee.id, date(2026, 5, 25))["prior_month_pay_after_si"] is None


def test_bonus_priors_ignore_draft_and_include_same_day_earlier_run(db, organization, employee):
    first = _prior_run(db, organization, employee, date(2026, 6, 25),
                       health_base="100000", pension_base="100000")
    current = _prior_run(db, organization, employee, date(2026, 6, 25),
                         health_base="0", pension_base="0")
    _prior_run(db, organization, employee, date(2026, 6, 25), status=PayrollStatus.DRAFT.value,
               health_base="999999", pension_base="999999")

    priors = jp._jp_bonus_priors(db, organization.id, employee.id, date(2026, 6, 25),
                                 current_run_id=current.id)
    assert priors["ytd_health_sba"] == Decimal("100000")
    assert priors["month_pension_sba"] == Decimal("100000")
    assert first.id != current.id


def test_payment_kind_is_run_level_not_employee_level(db, organization, employee, monkeypatch):
    employee.compliance_fields = {"jp_components": {"BONUS": "500000"},
                                  "jp_payment_kind": "BONUS"}
    db.commit()
    monkeypatch.setattr(jp, "_jp_one_active", lambda *_a, **_k: None)
    monkeypatch.setattr(jp, "_jp_events_for_month", lambda *_a, **_k: [])
    monkeypatch.setattr(jp, "_jp_bonus_priors", lambda *_a, **_k: {})

    plain = PayrollRun(organization_id=organization.id, period_label="Jul 2026",
                       period_start=date(2026, 7, 1), period_end=date(2026, 7, 31),
                       pay_date=date(2026, 7, 25), status="Draft", jp_payment_kind=None)
    bonus = PayrollRun(organization_id=organization.id, period_label="Jul 2026 bonus",
                       period_start=date(2026, 7, 1), period_end=date(2026, 7, 31),
                       pay_date=date(2026, 7, 25), status="Draft", jp_payment_kind="BONUS")

    assert jp.resolve_jp_calc_inputs(
        db, organization.id, employee, date(2026, 7, 25), run=plain)["jp_payment_kind"] == "SALARY"
    assert jp.resolve_jp_calc_inputs(
        db, organization.id, employee, date(2026, 7, 25), run=bonus)["jp_payment_kind"] == "BONUS"

def test_run_preflight_accepts_its_own_frozen_snapshot(db, organization, employee):
    from app.modules.payroll import japan_org_router

    run = PayrollRun(organization_id=organization.id, period_label="Jun 2026",
                     period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
                     pay_date=date(2026, 6, 25), status="Review")
    db.add(run)
    db.flush()
    db.add(PayslipItem(payroll_run_id=run.id, employee_id=employee.id,
                       organization_id=organization.id, employee_name=employee.name,
                       country_code="JP", jp_calculation_snapshot=_snapshot(employee.id)["jp_calculation_snapshot"]))
    db.commit()

    result = japan_org_router.run_preflight(
        run.id, current_user=SimpleNamespace(id=1, organization_id=organization.id), db=db)
    assert result["status"] == "OK"
    assert result["checks"] == [{"severity": "INFO", "code": "JP_NOT_APPROVED",
                                 "message": "The run has no stored Japan approval fingerprint yet."}]

def test_resident_tax_notice_rejects_null_or_impossible_month(db, organization, employee):
    amounts = {f"2026-{month:02d}": "1000" for month in range(1, 13)}
    body = {
        "municipality_code": "131016", "fiscal_notice_year": 2026, "notice_id": "N-1",
        "received_on": date(2026, 5, 20), "first_deduction_month": date(2026, 6, 1),
        "monthly_amounts": amounts, "total_amount": "12000", "source_hash": "a" * 64,
    }
    with pytest.raises(BadRequestException, match="must be an amount"):
        jp.record_resident_tax_assessment(
            db, organization.id, employee.id,
            {**body, "monthly_amounts": {**amounts, "2026-01": None}}, 1)
    bad_month = dict(amounts)
    bad_month.pop("2026-12")
    bad_month["2026-13"] = "1000"
    with pytest.raises(BadRequestException, match="YYYY-MM"):
        jp.record_resident_tax_assessment(
            db, organization.id, employee.id,
            {**body, "monthly_amounts": bad_month}, 1)


def test_unbound_my_number_ciphertext_is_never_revealed(db, organization, employee, monkeypatch):
    # Owner binding only: an unbound ciphertext (e.g. copied in from another
    # row) is refused rather than revealed.
    monkeypatch.setattr(settings, "JP_MY_NUMBER_KEYRING", json.dumps({"1": KEY}))
    monkeypatch.setattr(settings, "JP_MY_NUMBER_FINGERPRINT_KEY", FINGERPRINT_KEY)
    from app.modules.payroll.models import PayrollJpMyNumberVault

    number = _number()
    ciphertext, version = mn.encrypt(number)
    row = PayrollJpMyNumberVault(
        organization_id=organization.id, employee_id=employee.id,
        subject_type="EMPLOYEE", subject_ref="self", ciphertext=ciphertext,
        key_version=version, fingerprint=mn.fingerprint(number),
        purpose="TAX_SOCIAL_INSURANCE", collected_at=datetime.utcnow(),
        status="ACTIVE", created_by_id=1)
    db.add(row)
    db.commit()
    jp.request_my_number_reveal(db, organization.id, row.id, "Legacy row", 1)
    db.commit()
    jp.approve_my_number_reveal(db, organization.id, row.id, 2)
    db.commit()
    with pytest.raises(BadRequestException, match="could not be decrypted"):
        jp.reveal_my_number(db, organization.id, row.id, 2)


def test_retention_hook_takes_no_arguments_and_scopes_the_employee(db, organization, employee):
    # The platform calls retention_settings() with no arguments; a hook that
    # needs one breaks the retention report for every country.
    from app.modules.payroll import retention_service

    cfg = retention_service.settings("JP")
    assert cfg.country == "JP"
    with pytest.raises(NotFoundException):
        cfg.validate_employee(db, employee.id, organization.id + 1)      # another tenant
    with pytest.raises(NotFoundException):
        cfg.validate_employee(db, employee.id, organization.id)          # not a Japan employee
    employee.country_code = "JP"
    db.commit()
    cfg.validate_employee(db, employee.id, organization.id)
