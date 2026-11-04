"""New Zealand Phase 4: hooks, versioned records, IRD vault, calculation inputs,
snapshots and run binding (ZP-NZ-ENG-001; SQLite, no external services)."""
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.config import settings
from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import jurisdiction_hooks
from app.modules.payroll import new_zealand_service as nz
from app.modules.payroll import nz_ird_number as ird
from app.modules.payroll.models import (
    PayrollEmployee, PayrollNzAccumulatorEntry, PayrollNzAuthorityDeduction, PayrollNzIrdAccessEvent,
    PayrollRun, PayrollStatus, PayslipItem,
)

IRD = "49091850"
OTHER_IRD = "136410132"
HOOKS = ("calc_inputs", "before_run_transition", "statutory_profile_errors", "statutory_profile_values",
         "pack_activation_refusal", "retention_settings", "service_registry_transition", "statutory_summary",
         "statutory_editors", "template_activation_refusal", "pack_holidays", "payment_treatment",
         "payslip_hold_view")


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setattr(settings, "NZ_IRD_KEYRING", json.dumps({"1": "a" * 32}))
    monkeypatch.setattr(settings, "NZ_IRD_FINGERPRINT_KEY", "f" * 32)


@pytest.fixture()
def employee(db, organization):
    row = PayrollEmployee(organization_id=organization.id, employee_code="NZ-1", name="Aroha Ngata",
                          date_of_birth=date(1996, 5, 1), country_code="NZ")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _employer_payload(**kw):
    body = {"effective_from": date(2026, 4, 1), "legal_name": "Kiwi Test Ltd", "filing_method": "PAYDAY_GATEWAY",
            "remittance_class": "MONTHLY"}
    body.update(kw)
    return body


def _approved(row_factory, approver, *args):
    row = row_factory()
    approver(*args, row.id, 2)
    return row


# ── hooks ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", HOOKS)
def test_every_hook_resolves(name):
    assert callable(jurisdiction_hooks.get("NZ", name))


def test_retention_hook_takes_no_arguments_and_scopes_the_employee(db, organization, employee):
    from app.modules.payroll import retention_service

    cfg = retention_service.settings("NZ")
    assert cfg.country == "NZ" and cfg.period_decision == "D-7"
    cfg.validate_employee(db, employee.id, organization.id)
    with pytest.raises(NotFoundException):
        cfg.validate_employee(db, employee.id, organization.id + 1)


def test_template_refusal_pack_holidays_summary_and_registry():
    assert nz._nz_template_activation_refusal(None, SimpleNamespace(jurisdiction_country="NZ", report_type="X"))
    assert nz._nz_template_activation_refusal(None, SimpleNamespace(jurisdiction_country="US", report_type="W2")) \
        is None
    assert nz.nz_unmet_requirements(None)


def test_summary_and_holidays_with_no_pack(db):
    summary = nz.statutory_summary(db)
    assert summary["available"] is False and summary["jurisdiction"] == "NZ"
    assert "public_holidays" in summary["emptyAuthorityTables"]
    assert nz._nz_pack_holidays(db, 2026) == []


# ── versioned records with a second person's approval ──────────────────────
def test_employer_profile_versions_are_four_eyes_and_supersede(db, organization):
    first = nz.record_nz_employer_profile(db, organization.id, _employer_payload(), 1, "initial setup")
    db.commit()
    assert first.status == "DRAFT"
    with pytest.raises(BadRequestException, match="four-eyes"):
        nz.approve_nz_employer_profile(db, organization.id, first.id, 1)
    nz.approve_nz_employer_profile(db, organization.id, first.id, 2)
    second = nz.record_nz_employer_profile(db, organization.id, _employer_payload(effective_from=date(2026, 7, 1)),
                                           1, "change of filing method")
    nz.approve_nz_employer_profile(db, organization.id, second.id, 2)
    assert first.status == "SUPERSEDED" and first.effective_to == date(2026, 6, 30)
    assert second.previous_version_id == first.id


def test_records_refuse_unknown_fields_missing_reasons_and_bad_values(db, organization, employee):
    with pytest.raises(BadRequestException, match="unknown field"):
        nz.record_nz_employer_profile(db, organization.id, _employer_payload(status="ACTIVE"), 1, "x")
    with pytest.raises(BadRequestException, match="reason"):
        nz.record_nz_employer_profile(db, organization.id, _employer_payload(), 1, "  ")
    with pytest.raises(BadRequestException, match="first New Zealand release"):
        nz.record_nz_tax_profile(db, organization.id, employee.id, {
            "effective_from": date(2026, 4, 1), "ird_number_state": "PENDING", "tax_code": "WT",
            "tax_code_source": "IR330_DECLARATION"}, 1, "x")
    with pytest.raises(BadRequestException, match="tailored"):
        nz.record_nz_tax_profile(db, organization.id, employee.id, {
            "effective_from": date(2026, 4, 1), "ird_number_state": "PENDING", "tax_code": "STC",
            "tax_code_source": "IRD_NOTICE"}, 1, "x")
    with pytest.raises(BadRequestException, match="IRD number on file"):
        nz.record_nz_tax_profile(db, organization.id, employee.id, {
            "effective_from": date(2026, 4, 1), "ird_number_state": "VALID", "tax_code": "M",
            "tax_code_source": "IR330_DECLARATION"}, 1, "x")
    with pytest.raises(NotFoundException):
        nz.record_nz_employer_profile(db, organization.id, _employer_payload(legal_entity_id=999), 1, "x")
    with pytest.raises(BadRequestException, match="suspension"):
        nz.record_nz_kiwisaver_election(db, organization.id, employee.id, {
            "effective_from": date(2026, 4, 1), "membership_state": "SAVINGS_SUSPENSION"}, 1, "x")


def test_verification_needs_the_employer_ird_number_and_a_second_person(db, organization):
    draft = nz.record_nz_employer_profile(db, organization.id, _employer_payload(), 1, "setup")
    nz.set_nz_employer_ird(db, organization.id, draft.id, OTHER_IRD, 1)
    nz.approve_nz_employer_profile(db, organization.id, draft.id, 2)
    db.commit()
    with pytest.raises(BadRequestException, match="four-eyes"):
        nz.verify_nz_employer_profile(db, organization.id, draft.id, 1, "VERIFIED", "checked with IR")
    nz.verify_nz_employer_profile(db, organization.id, draft.id, 2, "VERIFIED", "checked with IR")
    assert draft.verification_state == "VERIFIED"
    bare = nz.record_nz_employer_profile(db, organization.id, _employer_payload(effective_from=date(2026, 8, 1)),
                                         1, "setup")
    nz.approve_nz_employer_profile(db, organization.id, bare.id, 2)
    with pytest.raises(BadRequestException, match="IRD number must be on file"):
        nz.verify_nz_employer_profile(db, organization.id, bare.id, 2, "VERIFIED", "x")


# ── IRD vault ───────────────────────────────────────────────────────────────
def test_ird_vault_stores_ciphertext_only_and_refuses_duplicates(db, organization, employee):
    row = nz.create_nz_ird_number(db, organization.id, "EMPLOYEE", IRD, 1, employee_id=employee.id)
    assert IRD not in row.ciphertext and "049091850" not in row.ciphertext and row.key_version == 1
    assert ird.decrypt(row.ciphertext, row.key_version, nz._nz_vault_owner(row)) == "049091850"
    with pytest.raises(BadRequestException, match="already"):
        nz.create_nz_ird_number(db, organization.id, "EMPLOYEE", IRD, 1, employee_id=employee.id)
    view = nz.nz_ird_view(row)
    assert view["onFile"] and not any(ch.isdigit() for ch in view["masked"])
    with pytest.raises(BadRequestException) as invalid:
        nz.create_nz_ird_number(db, organization.id, "EMPLOYER", "136410133", 1)
    assert "136410133" not in str(invalid.value)


def test_reveal_is_requested_approved_by_another_person_and_used_once(db, organization, employee):
    row = nz.create_nz_ird_number(db, organization.id, "EMPLOYEE", IRD, 1, employee_id=employee.id)
    with pytest.raises(BadRequestException, match="request"):
        nz.reveal_nz_ird_number(db, organization.id, row.id, 1)
    db.commit()
    nz.request_nz_ird_reveal(db, organization.id, row.id, "payday filing correction", 1)
    db.commit()
    with pytest.raises(BadRequestException, match="four-eyes"):
        nz.approve_nz_ird_reveal(db, organization.id, row.id, 1)
    nz.approve_nz_ird_reveal(db, organization.id, row.id, 2)
    with pytest.raises(BadRequestException, match="requested"):
        nz.reveal_nz_ird_number(db, organization.id, row.id, 3)
    assert nz.reveal_nz_ird_number(db, organization.id, row.id, 1)["irdNumber"] == "049091850"
    with pytest.raises(BadRequestException, match="already been used"):
        nz.reveal_nz_ird_number(db, organization.id, row.id, 1)
    actions = [e.action for e in db.query(PayrollNzIrdAccessEvent).order_by(PayrollNzIrdAccessEvent.id)]
    assert actions == ["CREATE", "REVEAL_REQUESTED", "REVEAL_APPROVED", "REVEALED"]
    nz.delete_nz_ird_number(db, organization.id, row.id, 1, "employee left")
    assert row.ciphertext is None and row.status == "DELETED"


# ── authority notices ───────────────────────────────────────────────────────
def _notice_meta(**kw):
    meta = {"deduction_type": "CHILD_SUPPORT", "notice_id": "CS-1", "issuer": "INLAND_REVENUE",
            "received_at": "2026-03-20T09:00:00", "effective_from": "2026-04-01", "amount_per_payday": "150",
            "protected_earnings_policy": "IRD_PROTECTED_NET"}
    meta.update(kw)
    return meta


def test_notices_are_hashed_versioned_and_never_store_the_file(db, organization, employee):
    first = nz.import_nz_authority_notice(db, organization.id, employee.id, _notice_meta(), b"NOTICE-A", 1)
    assert len(first.file_hash) == 64 and first.version == 1
    assert nz.import_nz_authority_notice(db, organization.id, employee.id, _notice_meta(), b"NOTICE-A", 1).id \
        == first.id
    nz.approve_nz_authority_notice(db, organization.id, first.id, 2)
    second = nz.import_nz_authority_notice(db, organization.id, employee.id, _notice_meta(amount_per_payday="175"),
                                           b"NOTICE-B", 1)
    assert (second.version, second.replaces_id) == (2, first.id)
    db.commit()
    with pytest.raises(BadRequestException, match="four-eyes"):
        nz.approve_nz_authority_notice(db, organization.id, second.id, 1)
    nz.approve_nz_authority_notice(db, organization.id, second.id, 2)
    assert first.status == "SUPERSEDED" and second.status == "APPROVED"
    columns = {c.name for c in PayrollNzAuthorityDeduction.__table__.columns}
    assert not {"body", "file", "content", "narrative"} & columns


def test_opening_balance_needs_evidence_and_a_second_person(db, organization, employee):
    with pytest.raises(BadRequestException, match="evidence"):
        nz.request_nz_opening_balance(db, organization.id, employee.id, {
            "obligation": "ACC_LIABLE_EARNINGS", "amount": "50000", "tax_year": "2026-27", "reason": "migration"}, 1)
    request = nz.request_nz_opening_balance(db, organization.id, employee.id, {
        "obligation": "ACC_LIABLE_EARNINGS", "amount": "50000", "tax_year": "2026-27",
        "evidence_ref": "incumbent-ytd.pdf", "reason": "migration"}, 1)
    db.commit()
    with pytest.raises(BadRequestException, match="four-eyes"):
        nz.approve_nz_opening_balance(db, organization.id, request["requestId"], 1)
    entry = nz.approve_nz_opening_balance(db, organization.id, request["requestId"], 2)
    assert (entry.entry_kind, entry.amount, entry.approved_by_id) == ("OPENING_BALANCE", Decimal("50000"), 2)
    with pytest.raises(BadRequestException, match="already"):
        nz.approve_nz_opening_balance(db, organization.id, request["requestId"], 2)


# ── calculation inputs, selected by the payday ──────────────────────────────
@pytest.fixture()
def pack_in_force(monkeypatch):
    pack = SimpleNamespace(tax_year="2026-27", effective_from=date(2026, 4, 1))
    monkeypatch.setattr(nz, "_nz_pack_in_force", lambda db, on: ({}, [], pack))
    return pack


def _tax_profile(db, organization, employee, start, code):
    row = nz.record_nz_tax_profile(db, organization.id, employee.id, {
        "effective_from": start, "ird_number_state": "PENDING", "tax_code": code,
        "tax_code_source": "IR330_DECLARATION", "min_wage_category": "ADULT"}, 1, "declaration")
    nz.approve_nz_tax_profile(db, organization.id, row.id, 2)
    return row


def test_calc_inputs_select_records_by_payday_not_period_end(db, organization, employee, pack_in_force):
    _tax_profile(db, organization, employee, date(2026, 3, 1), "M")
    _tax_profile(db, organization, employee, date(2026, 4, 8), "M SL")
    run = SimpleNamespace(pay_date=date(2026, 4, 8), period_start=date(2026, 3, 26), period_end=date(2026, 4, 7),
                          nz_payment_kind=None)
    inputs = nz.calc_inputs(db, run, employee)
    assert inputs["nz_tax_profile"]["tax_code"] == "M SL"
    assert inputs["nz_pay_date"] == date(2026, 4, 8) and inputs["nz_payment_kind"] == "REGULAR"
    with pytest.raises(BadRequestException, match="pay date"):
        nz.calc_inputs(db, None, employee)


def test_accumulators_are_explicit_zero_then_sum_before_the_payday(db, organization, employee, pack_in_force):
    acc = nz._nz_accumulators(db, organization.id, employee.id, None, "2026-27", date(2026, 4, 8))
    assert acc["ACC_LIABLE_EARNINGS"] == Decimal("0") and set(acc) == set(nz.ACCUMULATOR_OBLIGATIONS)
    db.execute(PayrollNzAccumulatorEntry.__table__.insert().values(
        organization_id=organization.id, employee_id=employee.id, tax_year="2026-27",
        obligation="ACC_LIABLE_EARNINGS", pay_date=date(2026, 4, 8), amount=Decimal("3000"), entry_kind="RUN",
        payslip_item_id=99999))
    later = nz._nz_accumulators(db, organization.id, employee.id, None, "2026-27", date(2026, 4, 22))
    same_day = nz._nz_accumulators(db, organization.id, employee.id, None, "2026-27", date(2026, 4, 8))
    assert (later["ACC_LIABLE_EARNINGS"], same_day["ACC_LIABLE_EARNINGS"]) == (Decimal("3000"), Decimal("0"))
    assert nz._nz_accumulators(db, organization.id, employee.id, None, None, date(2026, 4, 8)) is None


def test_hours_come_from_the_work_pattern_when_no_attendance(db, organization, employee):
    pattern = nz.record_nz_work_pattern(db, organization.id, employee.id, {
        "effective_from": date(2026, 4, 1), "pattern_type": "FIXED", "hours_source": "CONTRACT",
        "contracted_hours_per_week": "40", "weekly_schedule": {"MON": 8, "TUE": 8, "WED": 8, "THU": 8,
                                                               "FRI": 8}}, 1, "contract")
    hours, source = nz._nz_hours(db, organization.id, employee.id, date(2026, 4, 1), date(2026, 4, 14), pattern)
    assert (hours, source) == (Decimal("80.00"), "WORK_PATTERN")
    assert nz._nz_hours(db, organization.id, employee.id, None, None, pattern) == (None, None)


# ── snapshot, replay and run binding ────────────────────────────────────────
def test_freeze_and_replay_reproduce_the_result_hash():
    from app.modules.payroll.engine.resolver import calculate_payroll
    from tests._nz_engine_helpers import ctx, notice, tax_profile

    context = ctx(nz_tax_profile=tax_profile(tax_code="M SL"), nz_authority_deductions=[notice()])
    original = calculate_payroll(context, "standard").nz_result
    frozen = nz.nz_freeze_context(context, "standard")
    replayed = nz.nz_replay(json.loads(json.dumps(frozen))).nz_result
    assert replayed["hashes"] == original["hashes"] and replayed["netPay"] == "1195.85"
    snapshot = nz.nz_payslip_snapshot({"nz_result": original}, frozen)
    assert snapshot["frozenContext"]["version"] == 1


def _run_with_item(db, organization, employee, snapshot):
    run = PayrollRun(organization_id=organization.id, period_label="Apr 2026", period_start=date(2026, 3, 26),
                     period_end=date(2026, 4, 8), pay_date=date(2026, 4, 8), status="Review")
    db.add(run)
    db.flush()
    item = PayslipItem(payroll_run_id=run.id, employee_id=employee.id, organization_id=organization.id,
                       employee_name=employee.name, country_code="NZ", nz_calculation_snapshot=snapshot)
    db.add(item)
    db.commit()
    return run, item


def _snapshot(exceptions=(), net="1000.00"):
    return {"netPay": net, "exceptions": list(exceptions), "hashes": {"resultHash": net},
            "accumulatorDeltas": {"ACC_LIABLE_EARNINGS": "3000.00", "PAYE": "600.79"}}


def _verified_employer(db, organization):
    draft = nz.record_nz_employer_profile(db, organization.id, _employer_payload(), 1, "setup")
    nz.set_nz_employer_ird(db, organization.id, draft.id, OTHER_IRD, 1)
    nz.approve_nz_employer_profile(db, organization.id, draft.id, 2)
    nz.verify_nz_employer_profile(db, organization.id, draft.id, 2, "VERIFIED", "checked")
    return draft


def test_approval_needs_snapshots_a_verified_employer_and_no_exceptions(db, organization, employee, pack_in_force):
    run, item = _run_with_item(db, organization, employee, None)
    with pytest.raises(HTTPException) as refused:
        nz.before_run_transition(db, run, PayrollStatus.APPROVED, 1)
    assert refused.value.status_code == 409 and "NZ_SNAPSHOT_MISSING" in refused.value.detail
    assert "NZ_EMPLOYER_PROFILE_MISSING" in refused.value.detail
    _verified_employer(db, organization)
    item.nz_calculation_snapshot = _snapshot(exceptions=[{"code": "NZ_MIN_WAGE_FAIL"}])
    db.commit()
    with pytest.raises(HTTPException, match="NZ_MIN_WAGE_FAIL"):
        nz.before_run_transition(db, run, PayrollStatus.APPROVED, 1)
    item.nz_calculation_snapshot = _snapshot()
    db.commit()
    nz.before_run_transition(db, run, PayrollStatus.APPROVED, 1)
    assert run.nz_approval_fingerprint


def test_fingerprint_guards_later_steps_and_paid_posts_the_ledger_once(db, organization, employee, pack_in_force):
    _verified_employer(db, organization)
    run, item = _run_with_item(db, organization, employee, _snapshot())
    nz.before_run_transition(db, run, PayrollStatus.APPROVED, 1)
    item.nz_calculation_snapshot = _snapshot(net="999.00")
    db.commit()
    with pytest.raises(HTTPException) as changed:
        nz.before_run_transition(db, run, PayrollStatus.AUTHORIZED, 1)
    assert changed.value.status_code == 409
    item.nz_calculation_snapshot = _snapshot()
    db.commit()
    nz.before_run_transition(db, run, PayrollStatus.PAID, 1)
    nz.before_run_transition(db, run, PayrollStatus.PAID, 1)                    # a retry posts nothing
    entries = db.query(PayrollNzAccumulatorEntry).filter(PayrollNzAccumulatorEntry.run_id == run.id).all()
    assert sorted((e.obligation, e.amount) for e in entries) == [
        ("ACC_LIABLE_EARNINGS", Decimal("3000.00")), ("PAYE", Decimal("600.79"))]
    assert {e.tax_year for e in entries} == {"2026-27"}


def test_non_nz_runs_are_untouched(db, organization, employee):
    run = PayrollRun(organization_id=organization.id, period_label="Apr 2026", period_start=date(2026, 4, 1),
                     period_end=date(2026, 4, 30), pay_date=date(2026, 4, 30), status="Review")
    db.add(run)
    db.commit()
    assert nz.before_run_transition(db, run, PayrollStatus.APPROVED, 1) is None


# ── dormancy and employee validation ────────────────────────────────────────
def test_router_is_dormant_until_onboarding_is_enabled(db, organization, monkeypatch):
    from app.modules.payroll import nz_dormancy, nz_org_router, service

    user = SimpleNamespace(id=1, organization_id=organization.id)
    monkeypatch.setattr(nz_dormancy, "onboarding_enabled", lambda: False)
    with pytest.raises(NotFoundException):
        nz_org_router.require_nz_tenant(user, db)
    monkeypatch.setattr(nz_dormancy, "onboarding_enabled", lambda: True)
    monkeypatch.setattr(service, "_resolve_org_country", lambda _db, _org: "JP")
    with pytest.raises(NotFoundException):
        nz_org_router.require_nz_tenant(user, db)
    monkeypatch.setattr(service, "_resolve_org_country", lambda _db, _org: "NZ")
    assert nz_org_router.require_nz_tenant(user, db) is None


def test_every_nz_route_is_behind_the_dormancy_guard():
    from app.modules.payroll.nz_org_router import require_nz_tenant, router

    assert len(router.routes) == 32
    assert any(dep.dependency is require_nz_tenant for dep in router.dependencies)
    assert all(route.path.startswith("/new-zealand/") for route in router.routes)


def test_employee_validation_is_dormant_and_refuses_ird_fields(monkeypatch):
    from app.modules.payroll import employee_validation as ev, nz_dormancy

    monkeypatch.setattr(nz_dormancy, "onboarding_enabled", lambda: False)
    assert ev.is_supported_employee_country("NZ") is False
    monkeypatch.setattr(nz_dormancy, "onboarding_enabled", lambda: True)
    assert ev.is_supported_employee_country("NZ") is True
    with pytest.raises(BadRequestException, match="IRD vault"):
        ev.NZEmployeeValidation.validate({"ird_number": IRD})
    assert ev.NZEmployeeValidation.validate({}) == {}
