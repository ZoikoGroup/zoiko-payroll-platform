"""Belgium (ZP-BE-ENG-001) Block B3: run lifecycle, ledger at commit (G-29),
four-eyes and commit idempotency (G-18), corrections, payment batches (D13) and
the spec §11 payslip content.

SYNTHETIC TEST ONLY packs and records (tests/_be_engine_helpers.py). Seams: the
synthetic pack replaces the canonical resolver (the real Draft pack is never
signed or activated) and the fake business-code generator replaces the
PostgreSQL advisory lock on SQLite. Users: a = preparer / record creator,
b = approver, c = authorizer."""
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from tests._be_engine_helpers import PAY, build_pack

EMPLOYER_IBAN = "BE68539007547034"          # published example IBAN (valid check digits), TEST ONLY
EMPLOYEE_IBAN = "BE71096123456769"          # published example IBAN (valid check digits), TEST ONLY
NISS = "12312312312"                        # privacy-scan: allow (synthetic TEST ONLY value)


@pytest.fixture
def world(db, monkeypatch):
    import json as _json

    from app.config import settings
    from app.modules.payroll.models import CompanyComplianceDetails, PayrollEmployee
    from tests._mx_employer_helpers import make_org

    monkeypatch.setattr(settings, "BE_IDENTIFIER_KEYRING", _json.dumps({"1": "k" * 32}))
    monkeypatch.setattr(settings, "BE_IDENTIFIER_FINGERPRINT_KEY", "f" * 32)
    t = make_org(db, name="Lifecycle BV", code="BELIFE", admins=3, country="BE")
    details = db.query(CompanyComplianceDetails).filter_by(organization_id=t.org.id).one()
    details.settlement_acc = EMPLOYER_IBAN
    employee = PayrollEmployee(organization_id=t.org.id, employee_code="BE1", name="White Collar", country_code="BE",
                               employment_type="Full-time", pay_frequency="Monthly", ctc=Decimal("12000"),
                               basic=Decimal("12000"), hra=Decimal("0"), date_of_joining=date(2025, 1, 1),
                               compliance_fields={"iban": EMPLOYEE_IBAN})
    db.add(employee)
    db.commit()
    w = SimpleNamespace(db=db, org=t.org.id, a=t.users[0].id, b=t.users[1].id, c=t.users[2].id, employee=employee)
    _patch(monkeypatch)
    _setup_employer(w)
    _setup_employee(w, employee, "EMPLOYEE")
    return w


def _patch(monkeypatch):
    from app.core import code_generation
    from app.modules.payroll import belgium_service as be
    from app.modules.payroll import service
    from app.modules.payroll.engine.jurisdictions.belgium.pack import BePack

    rate_map, slabs = build_pack()

    def row(values):
        numbers = ("min_amount", "max_amount", "rate_pct", "flat_amount", "employee_rate_pct", "employer_rate_pct")
        out = {"tax_regime": None, "assessment_basis": None, "min_amount": "0", "max_amount": None, "rate_pct": "0",
               "flat_amount": None, **values}
        return SimpleNamespace(**{k: (Decimal(v) if k in numbers and v is not None else v) for k, v in out.items()})

    objects = ({k: row(v) for k, v in rate_map.items()}, [row(v) for v in slabs])
    real = service._resolve_effective_rate_inputs
    monkeypatch.setattr(service, "_resolve_effective_rate_inputs",
                        lambda db, org, country, *a, **k: (*objects, [], None)
                        if (country or "").upper() in ("BE", "BELGIUM") else real(db, org, country, *a, **k))
    monkeypatch.setattr(be, "_be_pack_for", lambda db, org, on: BePack(rate_map, slabs, org, on))
    counter = iter(range(1, 10_000))
    monkeypatch.setattr(code_generation, "generate_business_code",
                        lambda db, org, prefix, *a, **k: f"TEST{prefix}{next(counter):05d}")


def _two_step(w, record, approve, *args):
    row = record(*args)
    w.db.commit()
    out = approve(w.db, w.org, row.id, w.b)
    w.db.commit()
    return out


def _setup_employer(w):
    from app.modules.payroll import belgium_service as be

    reg = _two_step(w, be.record_be_employer_registration, be.approve_be_employer_registration, w.db, w.org,
                    {"effective_from": "2026-01-01", "legal_name": "Lifecycle BV", "enterprise_number": "0999999999",
                     "employer_category_code": "X1", "onss_special_160_status": "NOT_APPLICABLE",
                     "special_160_evidence_ref": "TEST ONLY workforce count"}, w.a, "setup")
    be.verify_be_employer_registration(w.db, w.org, reg.id, w.b, "VERIFIED", "checked")
    for name in ("basic", "hra", "special_allowance"):
        _two_step(w, be.record_be_component_mapping, be.approve_be_component_mapping, w.db, w.org,
                  {"platform_component_source": "PLATFORM_FIELD", "platform_component_key": name,
                   "be_component": "SALARY", "effective_from": "2026-01-01"}, w.a, "mapping")


def _setup_employee(w, employee, category):
    from app.modules.payroll import belgium_service as be

    _two_step(w, be.record_be_worker_profile, be.approve_be_worker_profile, w.db, w.org, employee.id,
              {"effective_from": "2026-01-01", "worker_category": category, "onss_worker_code": "W1",
               "residency": "RESIDENT", "pay_basis": "SALARIED"}, w.a, "hire")
    _two_step(w, be.record_be_work_schedule, be.approve_be_work_schedule, w.db, w.org, employee.id,
              {"effective_from": "2026-01-01", "regime": "EFFECTIVE", "weekly_hours": "38"}, w.a, "hire")
    _two_step(w, be.record_be_employment_classification, be.approve_be_employment_classification, w.db, w.org,
              employee.id, {"effective_from": "2026-01-01", "employment_line": "MAIN", "joint_committee": "200",
                            "function_class": "B", "seniority_months": 0, "contract_type": "INDEFINITE"}, w.a, "hire")


def _run(w, created_by=None):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollRun

    run = PayrollRun(organization_id=w.org, period_label="Mar 2026", period_start=date(2026, 3, 1), period_end=PAY,
                     pay_date=PAY, created_by=created_by or w.a)
    w.db.add(run)
    w.db.commit()
    service.generate_payslips_for_run(w.db, run, w.org)
    w.db.refresh(run)
    return run


def _advance(w, run, actor):
    from app.modules.payroll import service

    return service.advance_payroll_run_status(w.db, run.id, actor, w.org)


def _status(run):
    return str(getattr(run.status, "value", run.status))


def _acknowledge_all(w, run, actor=None):
    from app.modules.payroll import belgium_service as be

    for p in be.be_run_preflight(w.db, run):
        if p.get("exception") and p["severity"] == "BLOCK":
            be.acknowledge_be_run_exception(w.db, w.org, run.id, {"employeeId": p["employeeId"], "code": p["code"],
                                                                  "reason": "TEST ONLY reviewed"}, actor or w.a)
    w.db.commit()


def _approve(w, run):
    _advance(w, run, w.a)                       # Draft -> Review
    _acknowledge_all(w, run)
    return _advance(w, run, w.b)                # Review -> Approved (commit)


def _entries(w, **filters):
    from app.modules.payroll.models import PayrollBeAccumulatorEntry

    return w.db.query(PayrollBeAccumulatorEntry).filter_by(**filters).order_by(PayrollBeAccumulatorEntry.id).all()


# ── preflight, exceptions, four-eyes, ledger at commit ─────────────────────
def test_approval_needs_a_clear_preflight_and_acknowledged_exceptions(world):
    from app.modules.payroll import belgium_service as be

    w = world
    run = _run(w)
    assert _entries(w) == []                                              # G-29: nothing at generation
    view = be.be_run_preflight_view(w.db, w.org, run.id)
    assert {p["code"] for p in view["blocking"]} == {"BE_BSSC_PENDING", "BE_SECTOR_AGREEMENT_MISSING:MAIN"}
    assert not view["approvable"]
    assert {p["code"] for p in view["pending"]} == {"BE_DIMONA_IN_PENDING"}  # placeholder, never blocks
    _advance(w, run, w.a)
    with pytest.raises(HTTPException, match="BE_BSSC_PENDING"):
        _advance(w, run, w.b)
    _acknowledge_all(w, run)
    assert be.be_run_preflight_view(w.db, w.org, run.id)["approvable"]
    with pytest.raises(HTTPException, match="preparer"):
        _advance(w, run, w.a)                                             # four-eyes (G-18)
    _advance(w, run, w.b)
    w.db.refresh(run)
    assert _status(run) == "Approved"
    stored = run.be_approval_fingerprint
    assert stored["fingerprint"] == be.be_approval_fingerprint(w.db, run) and stored["approvedBy"] == w.b
    assert sorted(a["code"] for a in stored["acknowledgements"]) == ["BE_BSSC_PENDING", "BE_SECTOR_AGREEMENT_MISSING:MAIN"]
    entries = _entries(w, run_id=run.id)
    assert entries and all(e.entry_kind == "RUN" for e in entries)               # G-29: at commit
    assert be.post_be_accumulators(w.db, run, w.b) == 0                          # idempotent
    assert be.be_ytd_snapshot(w.db, w.org, w.employee.id, None, date(2026, 4, 30))["WITHHOLDING"] == Decimal("78.00")


def test_pending_content_and_resolver_blockers_cannot_be_acknowledged(world, monkeypatch):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import belgium_service as be

    w = world
    run = _run(w)
    monkeypatch.setattr(be, "_be_pack_for", lambda db, org, on: None)
    view = be.be_run_preflight_view(w.db, w.org, run.id)
    assert "BE_PACK_MISSING" in {p["code"] for p in view["blocking"]}
    with pytest.raises(BadRequestException, match="not raised"):
        be.acknowledge_be_run_exception(w.db, w.org, run.id, {"employeeId": w.employee.id, "code": "BE_PACK_MISSING",
                                                              "reason": "x"}, w.a)
    _advance(w, run, w.a)
    _acknowledge_all(w, run)
    with pytest.raises(HTTPException, match="BE_PACK_MISSING"):
        _advance(w, run, w.b)


def test_a_creator_of_the_inputs_cannot_approve(world):
    w = world
    run = _run(w, created_by=w.c)                                   # c prepared the run; a created the records
    _advance(w, run, w.c)
    _acknowledge_all(w, run, w.c)
    with pytest.raises(HTTPException, match="created a Belgian record"):
        _advance(w, run, w.a)
    _advance(w, run, w.b)
    assert _status(run) == "Approved"


def test_a_retried_approval_never_advances_twice_and_the_fingerprint_guards_authorization(world):
    w = world
    run = _approve(w, _run(w))
    with pytest.raises(HTTPException, match="other than its approver"):
        _advance(w, run, w.b)                                       # the approver's retry / double click (G-18)
    w.db.refresh(run)
    assert _status(run) == "Approved"
    item = w.db.query(__import__("app.modules.payroll.models", fromlist=["PayslipItem"]).PayslipItem).filter_by(
        payroll_run_id=run.id).one()
    original = dict(item.be_calculation_snapshot)
    item.be_calculation_snapshot = {**original, "be_net": "1.00"}           # an input / result changed after approval
    w.db.commit()
    with pytest.raises(HTTPException, match="fingerprint"):
        _advance(w, run, w.c)
    item.be_calculation_snapshot = original
    w.db.commit()
    _advance(w, run, w.c)
    w.db.refresh(run)
    assert _status(run) == "Authorized"


def test_a_non_belgian_run_is_untouched_by_the_belgian_hook(db):
    from app.modules.payroll import jurisdiction_hooks as jh

    run = SimpleNamespace(id=987654, created_by=1, pay_date=PAY)
    assert jh.call("BE", "before_run_transition", db, run, "APPROVED", 1) is None


# ── corrections ────────────────────────────────────────────────────────────
def test_a_correction_is_linked_never_mutates_and_posts_correction_entries(world):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import belgium_service as be
    from app.modules.payroll.models import PayrollRun, PayslipItem

    w = world
    draft = _run(w)
    draft_item = w.db.query(PayslipItem).filter_by(payroll_run_id=draft.id).one()
    with pytest.raises(BadRequestException, match="committed"):
        be.create_be_correction(w.db, w.org, draft_item.id, {"reason": "x", "evidenceRef": "e",
                                                             "inputDelta": {"gross": "1100"}}, w.a)
    w.db.delete(draft_item)
    w.db.commit()
    run = _approve(w, _run(w))
    original = w.db.query(PayslipItem).filter_by(payroll_run_id=run.id).one()
    before = json.dumps(original.be_calculation_snapshot, sort_keys=True)
    with pytest.raises(BadRequestException, match="evidence"):
        be.create_be_correction(w.db, w.org, original.id, {"reason": "late raise", "inputDelta": {"gross": "1100"}},
                                w.a)
    out = be.create_be_correction(w.db, w.org, original.id, {
        "reason": "late raise", "evidenceRef": "TEST ONLY letter", "payDate": "2026-04-30",
        "inputDelta": {"gross": "1100", "basic": "1100"}}, w.a)
    w.db.commit()
    assert json.dumps(original.be_calculation_snapshot, sort_keys=True) == before            # untouched
    fix = w.db.get(PayslipItem, out["payslipItemId"])
    snap = fix.be_calculation_snapshot
    assert (snap["correctionOf"], snap["reason"], snap["evidenceRef"]) == (original.id, "late raise",
                                                                           "TEST ONLY letter")
    assert Decimal(snap["grossDelta"]) == Decimal("100") and Decimal(out["netDelta"]) > 0
    with pytest.raises(BadRequestException, match="still open"):
        be.create_be_correction(w.db, w.org, original.id, {"reason": "again", "evidenceRef": "e",
                                                           "inputDelta": {"gross": "1200"}}, w.a)
    with pytest.raises(BadRequestException, match="original payslip"):
        be.create_be_correction(w.db, w.org, fix.id, {"reason": "x", "evidenceRef": "e",
                                                      "inputDelta": {"gross": "1"}}, w.a)
    correction_run = w.db.get(PayrollRun, out["runId"])
    _acknowledge_all(w, correction_run)
    _advance(w, correction_run, w.b)                                              # Review -> Approved (four-eyes)
    corrections = _entries(w, payslip_item_id=fix.id)
    assert corrections and all(e.entry_kind == "CORRECTION" for e in corrections)
    originals = {e.accumulator: e.id for e in _entries(w, payslip_item_id=original.id)}
    assert all(e.reverses_id == originals.get(e.accumulator) for e in corrections)
    ytd = be.be_ytd_snapshot(w.db, w.org, w.employee.id, None, date(2026, 5, 1))
    assert ytd["ONSS_EMPLOYEE_BASE"] == Decimal("1100")                           # original 1000 + delta 100


# ── payment (D13) ──────────────────────────────────────────────────────────
def test_the_salary_batch_is_built_validated_approved_and_reconciled(world):
    from app.modules.payroll import belgium_payment_service as pay
    from app.modules.payroll import jurisdiction_hooks as jh
    from app.modules.payroll.bank_export.sepa_pain001 import validate_against_xsd
    from app.modules.payroll.models import PayslipItem

    w = world
    run = _run(w)
    with pytest.raises(pay.PaymentServiceError, match="approved"):
        pay.create_salary_payment_batch(w.db, w.org, run.id, w.a)
    _approve(w, run)
    preview = pay.salary_payment_preview(w.db, w.org, run.id)
    assert [p["amount"] for p in preview["payable"]] == [Decimal("852.00")] and preview["exceptions"] == []
    batch = pay.create_salary_payment_batch(w.db, w.org, run.id, w.a, today=date(2026, 3, 1))
    w.db.commit()
    validate_against_xsd(batch.pain001_xml)                                   # pain.001.001.09 schema
    assert EMPLOYEE_IBAN in batch.pain001_xml and batch.status == "DRAFT"
    assert pay.create_salary_payment_batch(w.db, w.org, run.id, w.a, today=date(2026, 3, 1)).id == batch.id
    with pytest.raises(pay.PaymentServiceError, match="approves"):
        pay.batch_file(w.db, w.org, batch.id)
    with pytest.raises(pay.PaymentServiceError, match="four-eyes"):
        pay.approve_payment_batch(w.db, w.org, batch.id, w.a)
    pay.approve_payment_batch(w.db, w.org, batch.id, w.b)
    assert pay.batch_file(w.db, w.org, batch.id)[1] == batch.pain001_xml
    pay.submit_payment_batch(w.db, w.org, batch.id, w.a)
    pay.record_bank_result(w.db, w.org, batch.id, "ACCEPTED")
    pay.reconcile_payment_batch(w.db, w.org, batch.id)
    view = pay.batch_view(w.db, w.org, batch.id)
    assert view["status"] == "SETTLED" and {i["status"] for i in view["items"]} == {"SETTLED"}
    assert EMPLOYEE_IBAN not in json.dumps(view)                                # masked outside the file
    items = w.db.query(PayslipItem).filter_by(payroll_run_id=run.id).all()
    assert jh.call("BE", "payment_treatment", w.db, w.org, run, items) == {items[0].id: "BE_PAYMENT_BATCH"}
    with pytest.raises(pay.PaymentServiceError, match="already"):
        pay.create_salary_payment_batch(w.db, w.org, run.id, w.a, idempotency_key="another", today=date(2026, 3, 1))


def test_an_employee_without_a_valid_iban_blocks_the_batch_unless_excluded(world):
    from app.modules.payroll import belgium_payment_service as pay

    w = world
    w.employee.compliance_fields = {"iban": "BE00000000000000"}
    w.db.commit()
    run = _approve(w, _run(w))
    with pytest.raises(pay.PaymentServiceError, match="check digits"):
        pay.create_salary_payment_batch(w.db, w.org, run.id, w.a, today=date(2026, 3, 1))
    with pytest.raises(pay.PaymentServiceError, match="No employee"):
        pay.create_salary_payment_batch(w.db, w.org, run.id, w.a, exclusions={w.employee.id: "paid by cheque"},
                                        today=date(2026, 3, 1))


# ── a full synthetic white-collar and manual-worker month (§11 payslip) ─────
def test_a_white_collar_and_a_manual_worker_month_end_to_end(world):
    from app.modules.payroll import belgium_payment_service as pay
    from app.modules.payroll import belgium_service as be
    from app.modules.payroll import service
    from app.modules.payroll.bank_export.sepa_pain001 import validate_against_xsd
    from app.modules.payroll.models import PayrollEmployee, PayslipItem

    w = world
    manual = PayrollEmployee(organization_id=w.org, employee_code="BE2", name="Manual Worker", country_code="BE",
                             employment_type="Full-time", pay_frequency="Monthly", ctc=Decimal("12000"),
                             basic=Decimal("12000"), hra=Decimal("0"), date_of_joining=date(2025, 1, 1),
                             compliance_fields={"iban": EMPLOYEE_IBAN})
    w.db.add(manual)
    w.db.commit()
    _setup_employee(w, manual, "MANUAL")
    be.create_be_identifier(w.db, w.org, "NISS", NISS, w.a, employee_id=w.employee.id)
    w.db.commit()
    preview = service.preview_payroll_run(w.db, w.org, [w.employee.id, manual.id], "BE",
                                          period_start=date(2026, 3, 1), period_end=PAY, pay_date=PAY)
    rows = preview["employees"] if isinstance(preview, dict) and "employees" in preview else preview["results"]
    run = _approve(w, _run(w))
    items = {i.employee_id: i for i in w.db.query(PayslipItem).filter_by(payroll_run_id=run.id)}
    assert {Decimal(str(r["monthlyNet"])) for r in rows} == {Decimal(str(i.net_pay)) for i in items.values()}
    white, man = items[w.employee.id].be_calculation_snapshot, items[manual.id].be_calculation_snapshot
    assert white["trace"]["onss"]["manualBase"] is False and man["trace"]["onss"]["manualBase"] is True
    assert man["obligationDeltas"]["HOLIDAY_FUND_QUARTERLY"] == "110.00"
    for slip, item in ((white, items[w.employee.id]), (man, items[manual.id])):     # spec §11 minimum content
        view = service._serialize_payslip(item, run)["beCalculationSnapshot"]
        for key in ("bases", "be_onss_employer", "be_funds", "be_social_work_bonus", "be_withholding_regular",
                    "be_net", "sector", "documentVersion", "decision"):
            assert key in view, key
        assert view["sector"]["jointCommittee"] == "200" and view["documentVersion"] == "BE-PAYSLIP-1"
        assert NISS not in json.dumps(view) and "frozenContext" not in view
    assert white["identifierMasked"] and not any(ch.isdigit() for ch in white["identifierMasked"])
    assert man["identifierMasked"] is None
    batch = pay.create_salary_payment_batch(w.db, w.org, run.id, w.a, today=date(2026, 3, 1))
    validate_against_xsd(batch.pain001_xml)
    assert len(pay.batch_view(w.db, w.org, batch.id)["items"]) == 2
    assert NISS not in batch.pain001_xml


def test_the_individual_account_template_is_seeded_inactive(db):
    from app.modules.payroll import belgium_service as be
    from app.modules.payroll import jurisdiction_hooks as jh

    row = be.seed_be_individual_account_template(db, "2026")
    assert (row.document_scope, row.status, row.jurisdiction_country) == ("EMPLOYEE", "Draft", "BE")
    assert be.seed_be_individual_account_template(db, "2026").id == row.id
    assert jh.call("BE", "template_activation_refusal", db, row, 1)
