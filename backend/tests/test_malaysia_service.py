"""Malaysia service layer (ZP-MY-ENG-001 Phase 5): versioned records with
four-eyes approval (employer registration, worker profile, work assignment),
tax declarations (MY-010), the identifier vault (spec §15, MY-029),
calculation inputs selected by the pay date and period (MY-006), freeze /
replay, the run gates, the year-to-date ledger and the 13 platform hooks.
Statutory amounts come from the TEST pack in tests/_my_engine_helpers.py."""
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.exceptions import BadRequestException, NotFoundException
from tests._my_engine_helpers import build_pack

PAY_DATE = date(2026, 3, 31)
PERIOD = (date(2026, 3, 1), date(2026, 3, 31))
NRIC = "900101145678"           # synthetic: valid date + place code; MyKad has no check digit


@pytest.fixture
def world(db, monkeypatch):
    from app.config import settings
    from app.modules.payroll.models import PayrollEmployee
    from tests._mx_employer_helpers import make_org

    monkeypatch.setattr(settings, "MY_IDENTIFIER_KEYRING", json.dumps({"1": "k" * 32}))
    monkeypatch.setattr(settings, "MY_IDENTIFIER_FINGERPRINT_KEY", "f" * 32)
    t = make_org(db, name="Syarikat Ujian Sdn Bhd", code="MYSVC", admins=2, country="MY")
    employee = PayrollEmployee(organization_id=t.org.id, employee_code="MY1", name="Test Worker", country_code="MY")
    db.add(employee)
    db.commit()
    return SimpleNamespace(db=db, org=t.org.id, a=t.users[0].id, b=t.users[1].id, employee=employee)


@pytest.fixture
def with_pcb(monkeypatch):
    """Stand-in PCB (Phase 4 builds the real one from the HASiL specification)."""
    from app.modules.payroll.engine.jurisdictions.malaysia import pcb

    monkeypatch.setattr(pcb, "compute", lambda pack, **_: {"pcb": Decimal("100.00"), "trace": {"stub": True}})


def _registration(w, **over):
    from app.modules.payroll import malaysia_service as my

    payload = {"effective_from": "2026-01-01", "legal_name": "Syarikat Ujian Sdn Bhd", "hasil_employer_no": "E 1234567",
               "epf_employer_no": "12345678", "perkeso_employer_code": "A1234567", "hrd_category": "compulsory",
               "hrd_registration_no": "HRD123", "hrd_category_from": "2025-01-01",
               "hrd_category_evidence_ref": "HRD Corp letter 2025"}
    payload.update(over)
    row = my.record_my_employer_registration(w.db, w.org, payload, w.a, "initial setup")
    my.approve_my_employer_registration(w.db, w.org, row.id, w.b)
    my.verify_my_employer_registration(w.db, w.org, row.id, w.b, "verified", "checked against HASiL / EPF letters")
    return row


def _profile(w, **over):
    from app.modules.payroll import malaysia_service as my

    payload = {"effective_from": "2026-01-01", "contract_type": "contract_of_service", "pay_frequency": "monthly",
               "citizenship": "CITIZEN", "date_of_birth": "1990-01-01", "tax_residence": "RESIDENT",
               "residence_evidence_ref": "residence review 2026", "residence_from": "2026-01-01",
               "epf_member_class": "MY_PR_BELOW_60", "socso_category": "EI_AND_INVALIDITY", "eis_state": "COVERED",
               "manual_worker": False, "normal_hours_week": "45"}
    payload.update(over)
    row = my.record_my_worker_profile(w.db, w.org, w.employee.id, payload, w.a, "hire")
    return my.approve_my_worker_profile(w.db, w.org, row.id, w.b)


def _assignment(w, territory="PENINSULAR_LABUAN", state="SGR", start="2026-01-01"):
    from app.modules.payroll import malaysia_service as my

    row = my.record_my_work_assignment(w.db, w.org, w.employee.id, {
        "effective_from": start, "labour_territory": territory, "holiday_state": state,
        "assignment_reason": "HIRE"}, w.a, "hire")
    return my.approve_my_work_assignment(w.db, w.org, row.id, w.b)


def _declaration(w, kind, value=None, start="2026-01-01", approve=True):
    from app.modules.payroll import malaysia_service as my

    row = my.record_my_declaration(w.db, w.org, w.employee.id, {
        "declaration_type": kind, "value": value or {}, "received_at": "2025-12-20T10:00:00",
        "effective_from": start, "source_channel": "PAPER", "evidence_ref": f"scan-{kind}"}, w.a)
    return my.approve_my_declaration(w.db, w.org, row.id, w.b) if approve else row


def _setup(w):
    _registration(w)
    _profile(w)
    _assignment(w)
    w.db.commit()


# ── versioned records and four-eyes ────────────────────────────────────────
def test_registration_needs_a_second_approver_and_hrd_evidence(world):
    from app.modules.payroll import malaysia_service as my

    w = world
    row = my.record_my_employer_registration(w.db, w.org, {
        "effective_from": "2026-01-01", "legal_name": "X", "hasil_employer_no": "e-123 4567",
        "hrd_category": "NOT_REGISTERED"}, w.a, "setup")
    assert row.status == "DRAFT" and row.hasil_employer_no == "E1234567"
    w.db.commit()
    with pytest.raises(Exception, match="(?i)four|approv|same"):
        my.approve_my_employer_registration(w.db, w.org, row.id, w.a)
    assert my.approve_my_employer_registration(w.db, w.org, row.id, w.b).status == "ACTIVE"
    base = {"effective_from": "2026-02-01", "legal_name": "X", "hasil_employer_no": "E1234567"}
    for bad, message in (({"hrd_category": "COMPULSORY"}, "HRD category needs"),
                         ({"hrd_category": "HEADCOUNT_10"}, "hrd_category"),
                         ({"hrd_category": "NOT_REGISTERED", "hasil_employer_no": "E12/34"}, "letters or digits")):
        with pytest.raises(BadRequestException, match=message):
            my.record_my_employer_registration(w.db, w.org, {**base, **bad}, w.a, "setup")
    with pytest.raises(BadRequestException, match="reason"):
        my.record_my_employer_registration(w.db, w.org, base, w.a, "")
    with pytest.raises(BadRequestException, match="unknown field"):
        my.record_my_employer_registration(w.db, w.org, {**base, "status": "ACTIVE"}, w.a, "setup")


def test_profile_rules_and_supersession(world):
    from app.modules.payroll import malaysia_service as my

    w = world
    first = _profile(w)
    second = _profile(w, effective_from="2026-06-01", eis_state="EXEMPT_HISTORY")
    assert first.status == "SUPERSEDED" and first.effective_to == date(2026, 5, 31)
    assert second.status == "ACTIVE"
    base = {"effective_from": "2026-07-01", "contract_type": "CONTRACT_OF_SERVICE", "pay_frequency": "MONTHLY"}
    with pytest.raises(BadRequestException, match="MY-007"):
        my.record_my_worker_profile(w.db, w.org, w.employee.id, {**base, "tax_residence": "RESIDENT"}, w.a, "x")
    with pytest.raises(BadRequestException, match="work pass"):
        my.record_my_worker_profile(w.db, w.org, w.employee.id, {**base, "citizenship": "NON_CITIZEN"}, w.a, "x")
    with pytest.raises(BadRequestException, match="epf_member_class"):
        my.record_my_worker_profile(w.db, w.org, w.employee.id, {**base, "epf_member_class": "MY_65"}, w.a, "x")
    draft = my.record_my_worker_profile(w.db, w.org, w.employee.id, base, w.a, "x")
    assert draft.tax_residence == "REVIEW_REQUIRED"                                 # never inferred


def test_assignment_territory_must_match_the_holiday_state(world):
    from app.modules.payroll import malaysia_service as my

    w = world
    assert _assignment(w, "SABAH", "SBH").labour_territory == "SABAH"
    assert _assignment(w, "PENINSULAR_LABUAN", "LBN", start="2026-04-01").holiday_state == "LBN"   # Labuan
    with pytest.raises(BadRequestException, match="MY-003"):
        my.record_my_work_assignment(w.db, w.org, w.employee.id, {
            "effective_from": "2026-05-01", "labour_territory": "SARAWAK", "holiday_state": "SGR",
            "assignment_reason": "TRANSFER"}, w.a, "transfer")


def test_another_organisation_cannot_touch_the_records(world):
    from app.modules.payroll import malaysia_service as my

    w = world
    row = _profile(w)
    with pytest.raises(NotFoundException):
        my.approve_my_worker_profile(w.db, w.org + 999, row.id, w.b)
    with pytest.raises(NotFoundException):
        my.record_my_worker_profile(w.db, w.org + 999, w.employee.id, {
            "effective_from": "2026-01-01", "contract_type": "CONTRACT_OF_SERVICE", "pay_frequency": "MONTHLY"},
            w.a, "x")


# ── tax declarations (MY-010) ──────────────────────────────────────────────
def test_declarations_need_evidence_valid_values_and_one_tax_year(world):
    from app.modules.payroll import malaysia_service as my

    w = world
    base = {"declaration_type": "ZAKAT", "value": {"amount": "50"}, "received_at": "2025-12-20",
            "effective_from": "2026-01-01", "source_channel": "PAPER", "evidence_ref": "scan"}
    with pytest.raises(BadRequestException, match="evidence_ref"):
        my.record_my_declaration(w.db, w.org, w.employee.id, {**base, "evidence_ref": None}, w.a)
    with pytest.raises(BadRequestException, match="amount"):
        my.record_my_declaration(w.db, w.org, w.employee.id, {**base, "value": {"amount": "0"}}, w.a)
    with pytest.raises(BadRequestException, match="HASiL reference"):
        my.record_my_declaration(w.db, w.org, w.employee.id,
                                 {**base, "declaration_type": "CP38", "value": {"amount": "200"}}, w.a)
    with pytest.raises(BadRequestException, match="one tax year"):
        my.record_my_declaration(w.db, w.org, w.employee.id, {**base, "effective_to": "2027-01-31"}, w.a)
    row = my.record_my_declaration(w.db, w.org, w.employee.id, base, w.a)
    assert (row.status, row.tax_year) == ("RECEIVED", 2026)
    w.db.commit()
    with pytest.raises(Exception):
        my.approve_my_declaration(w.db, w.org, row.id, w.a)                         # four-eyes


def test_a_new_declaration_supersedes_and_history_is_kept(world):
    from app.modules.payroll import malaysia_service as my

    w = world
    old = _declaration(w, "ZAKAT", {"amount": "50"})
    new = _declaration(w, "ZAKAT", {"amount": "80"}, start="2026-04-01")
    assert (old.status, old.effective_to, old.superseded_by_id) == ("SUPERSEDED", date(2026, 3, 31), new.id)
    withdrawn = my.withdraw_my_declaration(w.db, w.org, new.id, w.a, "employee stopped", "2026-08-31")
    assert withdrawn.status == "WITHDRAWN" and withdrawn.effective_to == date(2026, 8, 31)
    _declaration(w, "ZAKAT", {"amount": "60"}, start="2026-09-01")
    with pytest.raises(BadRequestException, match="already starts"):
        _declaration(w, "ZAKAT", {"amount": "10"}, start="2026-02-01")


def test_approved_tp3_posts_evidenced_prior_employer_entries(world):
    from app.modules.payroll import malaysia_service as my

    w = world
    with pytest.raises(BadRequestException, match="TP3 accumulators"):
        _declaration(w, "TP3", {"priorEmployer": "Old Co", "accumulators": {"EPF_EE": "100"}}, approve=False)
    _declaration(w, "TP3", {"priorEmployer": "Old Co", "accumulators": {"PCB_GROSS_NORMAL": "12000",
                                                                        "PCB_PAID": "300"}}, start="2026-02-01")
    ytd = my.my_ytd_snapshot(w.db, w.org, w.employee.id, None, PAY_DATE)
    assert ytd["PCB_GROSS_NORMAL"] == Decimal("12000") and ytd["PCB_PAID"] == Decimal("300")
    assert ytd["EPF_EE"] == Decimal("0")                                            # every key present
    tp3 = w.db.query(my._models().PayrollMyTaxDeclaration).filter_by(declaration_type="TP3").one()
    with pytest.raises(BadRequestException, match="reversing"):
        my.withdraw_my_declaration(w.db, w.org, tp3.id, w.a, "mistake", "2026-02-28")


# ── identifier vault (spec §15, MY-029) ────────────────────────────────────
def test_vault_stores_ciphertext_only_and_masks_everywhere(world):
    from app.modules.payroll import malaysia_service as my
    from app.modules.payroll.models import PayrollMyIdentifierAccessEvent, PayrollMyIdentifierVault

    w = world
    row = my.create_my_identifier(w.db, w.org, "nric", "900101-14-5678", w.a, employee_id=w.employee.id)
    stored = w.db.get(PayrollMyIdentifierVault, row.id)
    assert NRIC not in (stored.ciphertext or "") and NRIC not in stored.fingerprint
    view = my.identifier_view(stored)
    assert view["onFile"] and not any(ch.isdigit() for ch in view["masked"])
    assert NRIC not in json.dumps(my.list_my_identifiers(w.db, w.org, w.employee.id))
    assert NRIC not in json.dumps(my.employee_summary(w.db, w.org, w.employee.id), default=str)
    with pytest.raises(BadRequestException, match="already"):
        my.create_my_identifier(w.db, w.org, "NRIC", NRIC, w.a, employee_id=w.employee.id)
    with pytest.raises(BadRequestException) as raised:
        my.create_my_identifier(w.db, w.org, "NRIC", "901301145678", w.a, employee_id=w.employee.id)
    assert "901301145678" not in str(raised.value.detail)
    assert w.db.query(PayrollMyIdentifierAccessEvent).filter_by(vault_id=row.id, action="CREATE").count() == 1
    profile = _profile(w, nric_vault_id=row.id)
    assert profile.nric_vault_id == row.id
    with pytest.raises(BadRequestException, match="does not belong"):
        _profile(w, effective_from="2026-02-01", tin_vault_id=row.id)               # an NRIC is not a TIN


def test_reveal_is_requested_approved_by_another_person_and_single_use(world):
    from app.modules.payroll import malaysia_service as my

    w = world
    row = my.create_my_identifier(w.db, w.org, "NRIC", NRIC, w.a, employee_id=w.employee.id)
    with pytest.raises(BadRequestException, match="request"):
        my.reveal_my_identifier(w.db, w.org, row.id, w.a)
    with pytest.raises(BadRequestException, match="reason"):
        my.request_my_identifier_reveal(w.db, w.org, row.id, "", w.a)
    my.request_my_identifier_reveal(w.db, w.org, row.id, "EPF registration", w.a)
    w.db.commit()
    with pytest.raises(Exception):
        my.approve_my_identifier_reveal(w.db, w.org, row.id, w.a)                   # four-eyes
    my.approve_my_identifier_reveal(w.db, w.org, row.id, w.b)
    with pytest.raises(BadRequestException, match="requested"):
        my.reveal_my_identifier(w.db, w.org, row.id, w.b)                           # only the requester
    assert my.reveal_my_identifier(w.db, w.org, row.id, w.a)["value"] == NRIC
    with pytest.raises(BadRequestException, match="already been used"):
        my.reveal_my_identifier(w.db, w.org, row.id, w.a)
    deleted = my.delete_my_identifier(w.db, w.org, row.id, w.a, "left the company")
    assert deleted.ciphertext is None and my.identifier_view(deleted)["masked"] is None


def test_vault_refuses_without_keys(world, monkeypatch):
    from app.config import settings
    from app.modules.payroll import malaysia_service as my

    monkeypatch.setattr(settings, "MY_IDENTIFIER_FINGERPRINT_KEY", "")
    with pytest.raises(BadRequestException, match="FINGERPRINT_KEY"):
        my.create_my_identifier(world.db, world.org, "NRIC", NRIC, world.a, employee_id=world.employee.id)


# ── calculation inputs -> engine, freeze / replay ──────────────────────────
def _context(inputs, gross="5000"):
    from app.modules.payroll.engine.base import PayrollContext

    rate_map, slabs = build_pack()
    return PayrollContext(gross=Decimal(gross), basic=Decimal(gross), country="MY", rate_map=rate_map,
                          slabs=slabs, pay_date=PAY_DATE, **inputs)


def test_inputs_from_the_records_drive_the_engine(world, with_pcb):
    from app.modules.payroll import malaysia_service as my
    from app.modules.payroll.engine.resolver import calculate_payroll

    w = world
    _setup(w)
    _declaration(w, "ZAKAT", {"amount": "50"})
    inputs = my.calc_inputs(w.db, None, w.employee, None, as_of=PAY_DATE, period=PERIOD)
    assert inputs["my_profile"]["status"] == "ACTIVE" and inputs["my_assignment"]["labour_territory"] == \
        "PENINSULAR_LABUAN"
    assert (inputs["my_period_start"], inputs["my_period_end"]) == PERIOD
    assert [d["declaration_type"] for d in inputs["my_declarations"]] == ["ZAKAT"]
    result = calculate_payroll(_context(inputs), "standard")
    assert result.net_pay == Decimal("4315.35") and result.my_result["my_epf"]["employee"] == "550.00"


def test_inputs_need_a_pay_date_and_missing_records_block(world):
    from app.modules.payroll import malaysia_service as my
    from app.modules.payroll.engine.countries.malaysia import MYCalculationBlockedError, calculate

    w = world
    with pytest.raises(BadRequestException, match="pay date"):
        my.calc_inputs(w.db, None, w.employee, None)
    inputs = my.calc_inputs(w.db, None, w.employee, None, as_of=PAY_DATE, period=PERIOD)
    assert inputs["my_profile"] is None and inputs["my_registration"] is None and inputs["my_assignment"] is None
    with pytest.raises(MYCalculationBlockedError, match="MY_PROFILE_MISSING"):
        calculate(_context(inputs))
    _setup(w)
    without_period = my.calc_inputs(w.db, None, w.employee, None, as_of=PAY_DATE)    # the preview has none
    assert without_period["my_period_start"] is None
    with pytest.raises(MYCalculationBlockedError, match="MY_PERIOD_MISSING"):
        calculate(_context(without_period))


def test_freeze_and_replay_reproduce_the_same_hashes(world, with_pcb):
    from app.modules.payroll import malaysia_service as my
    from app.modules.payroll.engine.resolver import calculate_payroll

    w = world
    _setup(w)
    vault = my.create_my_identifier(w.db, w.org, "NRIC", NRIC, w.a, employee_id=w.employee.id)
    _profile(w, effective_from="2026-02-01", nric_vault_id=vault.id)
    ctx = _context(my.calc_inputs(w.db, None, w.employee, None, as_of=PAY_DATE, period=PERIOD))
    original = calculate_payroll(ctx, "standard")
    frozen = json.loads(json.dumps(my.my_freeze_context(ctx, "standard")))       # through JSON, as stored
    replayed = my.my_replay(frozen)
    assert replayed.net_pay == original.net_pay
    assert replayed.my_result["hashes"] == original.my_result["hashes"]
    assert NRIC not in json.dumps(frozen) and "nric_vault_id" not in json.dumps(frozen)
    snapshot = my.my_payslip_snapshot(original, frozen)
    assert snapshot["frozenContext"] == frozen and snapshot["my_net"] == "4315.35"


# ── run gates and the ledger ───────────────────────────────────────────────
def _run_with_payslip(w, status="Processed"):
    from app.modules.payroll import malaysia_service as my
    from app.modules.payroll.engine.resolver import calculate_payroll
    from app.modules.payroll.models import PayrollRun, PayslipItem

    ctx = _context(my.calc_inputs(w.db, None, w.employee, None, as_of=PAY_DATE, period=PERIOD))
    result = calculate_payroll(ctx, "standard")
    run = PayrollRun(organization_id=w.org, period_label="Mar 2026", period_start=PERIOD[0],
                     period_end=PERIOD[1], pay_date=PAY_DATE, status=status)
    w.db.add(run)
    w.db.flush()
    item = PayslipItem(payroll_run_id=run.id, employee_id=w.employee.id, organization_id=w.org,
                       employee_name=w.employee.name, country_code="MY", gross_pay=Decimal("5000"),
                       my_calculation_snapshot=my.my_payslip_snapshot(result, my.my_freeze_context(ctx)))
    w.db.add(item)
    w.db.commit()
    return run, item


def test_run_calc_inputs_take_the_period_from_the_run(world):
    from app.modules.payroll import malaysia_service as my

    w = world
    run = SimpleNamespace(pay_date=PAY_DATE, period_start=PERIOD[0], period_end=PERIOD[1])
    inputs = my.calc_inputs(w.db, run, w.employee, None)
    assert (inputs["my_pay_date"], inputs["my_period_start"], inputs["my_period_end"]) == (PAY_DATE, *PERIOD)


def test_approval_is_refused_while_preflight_finds_problems(world, with_pcb):
    from fastapi import HTTPException

    from app.modules.payroll import malaysia_service as my
    from app.modules.payroll.models import PayrollStatus

    w = world
    _setup(w)
    run, _item = _run_with_payslip(w)
    codes = {p["code"] for p in my.my_run_preflight(w.db, run)}
    assert {"CONTENT_PACK_OUT_OF_DATE", "MISSING_IDENTIFIER"} <= codes             # no Active pack, no NRIC
    assert "MY_TAX_RESIDENCE_REVIEW" not in codes and "MY_ASSIGNMENT_MISSING" not in codes
    with pytest.raises(HTTPException) as raised:
        my.before_run_transition(w.db, run, PayrollStatus.APPROVED, w.b)
    assert raised.value.status_code == 409 and "MISSING_IDENTIFIER" in raised.value.detail


def test_preflight_flags_review_residence_expired_pass_and_no_assignment(world, with_pcb):
    from app.modules.payroll import malaysia_service as my

    w = world
    _registration(w)
    _profile(w, citizenship="NON_CITIZEN", work_pass_type="EMPLOYMENT_PASS", work_pass_valid_to="2026-02-28",
             epf_member_class="NONMY_POST_1998", socso_category="FOREIGN_WORKER", eis_state="FOREIGN_EXCLUDED",
             tax_residence=None, residence_evidence_ref=None, residence_from=None)
    w.db.commit()
    from app.modules.payroll.models import PayrollRun, PayslipItem

    run = PayrollRun(organization_id=w.org, period_label="Mar 2026", period_start=PERIOD[0], period_end=PERIOD[1],
                     pay_date=PAY_DATE, status="Processed")
    w.db.add(run)
    w.db.flush()
    w.db.add(PayslipItem(payroll_run_id=run.id, employee_id=w.employee.id, organization_id=w.org,
                         employee_name=w.employee.name, country_code="MY", gross_pay=Decimal("5000")))
    w.db.commit()
    codes = {p["code"] for p in my.my_run_preflight(w.db, run)}
    assert {"MY_SNAPSHOT_MISSING", "MY_ASSIGNMENT_MISSING", "MY_TAX_RESIDENCE_REVIEW", "MY_WORK_PASS_EXPIRED"} <= codes


def test_paid_posts_the_ledger_once_and_needs_the_approved_fingerprint(world, with_pcb):
    from fastapi import HTTPException

    from app.modules.payroll import malaysia_service as my
    from app.modules.payroll.models import PayrollMyAccumulatorEntry, PayrollStatus

    w = world
    _setup(w)
    run, item = _run_with_payslip(w)
    with pytest.raises(HTTPException, match="no longer matches"):
        my.before_run_transition(w.db, run, PayrollStatus.PAID, w.b)               # never approved
    run.my_approval_fingerprint = my.my_approval_fingerprint(w.db, run)
    my.before_run_transition(w.db, run, PayrollStatus.PAID, w.b)
    my.before_run_transition(w.db, run, PayrollStatus.PAID, w.b)                   # idempotent
    entries = w.db.query(PayrollMyAccumulatorEntry).filter_by(payslip_item_id=item.id).all()
    assert {e.accumulator: str(e.amount) for e in entries}["EPF_EE"] == "550.00"
    assert len(entries) == len(item.my_calculation_snapshot["accumulatorDeltas"])
    assert my.my_ytd_snapshot(w.db, w.org, w.employee.id, None, date(2026, 4, 30))["HRD_LEVY"] == Decimal("50")
    assert my.my_ytd_snapshot(w.db, w.org, w.employee.id, None, PAY_DATE)["HRD_LEVY"] == Decimal("0")
    item.my_calculation_snapshot = {**item.my_calculation_snapshot, "my_net": "1.00"}
    w.db.commit()
    with pytest.raises(HTTPException, match="no longer matches"):
        my.before_run_transition(w.db, run, PayrollStatus.AUTHORIZED, w.b)


# ── hooks, governance, dormancy ────────────────────────────────────────────
def test_all_thirteen_hooks_are_registered():
    from app.modules.payroll import jurisdiction_hooks, malaysia_service, poland_service

    assert jurisdiction_hooks.has_module("MY")
    names = set(poland_service.JURISDICTION_HOOKS)
    assert set(malaysia_service.JURISDICTION_HOOKS) == names and len(names) == 13
    for name in names:
        assert callable(jurisdiction_hooks.get("MY", name))


def test_retention_template_activation_and_summary_hooks(world):
    from app.modules.payroll import jurisdiction_hooks, retention_service

    w = world
    settings = retention_service.settings("MY")
    assert settings.country == "MY" and settings.period_decision == "D-8"
    template = SimpleNamespace(jurisdiction_country="MY", report_type="MY_PCB_MONTHLY")
    assert "G3" in jurisdiction_hooks.call("MY", "template_activation_refusal", w.db, template, None)
    assert jurisdiction_hooks.call("MY", "template_activation_refusal", w.db,
                                   SimpleNamespace(jurisdiction_country="PL", report_type="PL_DRA"), None) is None
    pack = SimpleNamespace(jurisdiction_country="MY", id=0, pack_id="MY-PAYROLL-2026")
    assert jurisdiction_hooks.call("MY", "pack_activation_refusal", w.db, pack, None)
    assert jurisdiction_hooks.call("MY", "statutory_editors", w.db, pack) == set()
    summary = jurisdiction_hooks.call("MY", "statutory_summary", w.db)
    assert summary["available"] is False and [u["key"] for u in summary["unmet"]][:2] == ["MY-GATES", "MY-PCB"]


def test_malaysia_cannot_be_opened_before_the_gates(world):
    from app.modules.payroll import jurisdiction_hooks

    with pytest.raises(Exception):
        jurisdiction_hooks.call("MY", "service_registry_transition", world.db, "AVAILABLE", "launch", world.a)


def test_router_is_dormant_and_malaysia_only(world, monkeypatch):
    from app.config import settings
    from app.modules.payroll.my_org_router import require_my_tenant
    from tests._mx_employer_helpers import make_org, principal

    w = world
    with pytest.raises(NotFoundException):
        require_my_tenant(principal(w.org), w.db)
    monkeypatch.setattr(settings, "MY_CANARY_ORG_IDS", str(w.org))                 # canary: this org only
    assert require_my_tenant(principal(w.org), w.db) is None
    monkeypatch.setattr(settings, "MY_TENANT_ONBOARDING_ENABLED", True)
    other = make_org(w.db, name="Other", code="MYOTHER", country="PL")
    with pytest.raises(NotFoundException, match="only available"):
        require_my_tenant(principal(other.org.id), w.db)


def test_router_exposes_identifiers_only_masked():
    from app.modules.payroll.my_org_router import router

    paths = {(sorted(r.methods)[0], r.path) for r in router.routes}
    assert ("POST", "/malaysia/identifiers/{vault_id}/reveal") in paths
    assert ("POST", "/malaysia/employees/{employee_id}/work-assignments") in paths
    assert all(p.startswith("/malaysia/") for _m, p in paths)


# ── Phase 6: labour inputs, leave / holidays without a pack ────────────────
def test_calc_inputs_carry_every_assignment_of_the_period(world):
    from app.modules.payroll import malaysia_service as my

    w = world
    _setup(w)
    _assignment(w, "SABAH", "SBH", start="2026-03-16")                            # transfer mid-March
    inputs = my.calc_inputs(w.db, None, w.employee, None, as_of=PAY_DATE, period=PERIOD)
    assert inputs["my_assignment"]["labour_territory"] == "SABAH"
    assert [a["labour_territory"] for a in inputs["my_assignments"]] == ["PENINSULAR_LABUAN", "SABAH"]
    april = my.calc_inputs(w.db, None, w.employee, None, as_of=date(2026, 4, 30),
                           period=(date(2026, 4, 1), date(2026, 4, 30)))
    assert [a["labour_territory"] for a in april["my_assignments"]] == ["SABAH"]


def test_freeze_keeps_overtime_events_and_assignments(world, with_pcb):
    from app.modules.payroll import malaysia_service as my

    w = world
    _setup(w)
    ctx = _context(my.calc_inputs(w.db, None, w.employee, None, as_of=PAY_DATE, period=PERIOD))
    ctx.my_overtime_events = [{"event_ref": "T-1", "day_type": "WORKDAY", "date": "2026-03-10", "hours": "4",
                               "normal_daily_hours": "8"}]
    frozen = json.loads(json.dumps(my.my_freeze_context(ctx)))
    thawed = my.my_thaw_context(frozen)
    assert thawed.my_overtime_events == ctx.my_overtime_events
    assert [a["labour_territory"] for a in thawed.my_assignments] == ["PENINSULAR_LABUAN"]


def test_leave_and_holidays_need_an_active_pack(world):
    from app.modules.payroll import jurisdiction_hooks
    from app.modules.payroll import malaysia_service as my

    w = world
    _setup(w)
    with pytest.raises(BadRequestException, match="No active Malaysia rule pack"):
        my.my_leave_entitlement(w.db, w.org, w.employee.id, "2026-03-31")
    with pytest.raises(BadRequestException, match="No active Malaysia rule pack"):
        my.my_holiday_calendar(w.db, w.org, w.employee.id, 2026)
    assert jurisdiction_hooks.call("MY", "pack_holidays", w.db, 2026) == []         # never a guessed list


def test_router_exposes_the_labour_routes():
    from app.modules.payroll.my_org_router import router

    paths = {(sorted(r.methods)[0], r.path) for r in router.routes}
    assert ("GET", "/malaysia/employees/{employee_id}/leave-entitlement") in paths
    assert ("GET", "/malaysia/employees/{employee_id}/holidays") in paths
    for method, path in (("POST", "/malaysia/employees/{employee_id}/employer-events"),
                         ("POST", "/malaysia/employer-events/{row_id}/submitted"),
                         ("POST", "/malaysia/employer-events/{row_id}/clearance-hold"),
                         ("POST", "/malaysia/clearance-holds/{hold_id}/release-approve")):
        assert (method, path) in paths


# ── Phase 7: employer events and tax-clearance holds (MY-019 / MY-020) ─────
@pytest.fixture
def signed_pack(monkeypatch):
    """Due dates / hold maximum from a signed TEST pack (30 / 30 / 30 / 30 / 90 days)."""
    from app.modules.payroll import malaysia_service as my
    from app.modules.payroll.engine.jurisdictions.malaysia.pack import MyPack

    rate_map, slabs = build_pack()
    monkeypatch.setattr(my, "_signed_pack", lambda db, org, on: MyPack(rate_map, slabs, org, on))


def _event(w, kind="CP22A", on="2026-06-30", clearance=True):
    from app.modules.payroll import malaysia_service as my

    return my.record_my_employer_event(w.db, w.org, w.employee.id, {
        "event_type": kind, "event_date": on, "clearance_required": clearance, "evidence_ref": "resignation letter"},
        w.a, "employee resigned")


def test_event_due_dates_come_from_signed_content(world, signed_pack):
    w = world
    assert (_event(w, "CP22", "2026-03-01", False).due_date) == date(2026, 3, 31)      # 30 days after start
    assert (_event(w, "CP22A", "2026-06-30").due_date) == date(2026, 5, 31)           # 30 days before cessation
    assert (_event(w, "CP21", "2026-06-30").due_date) == date(2026, 5, 31)
    assert (_event(w, "DEATH_NOTICE", "2026-04-01", False).due_date) == date(2026, 5, 1)
    with pytest.raises(BadRequestException, match="CP22A or CP21"):
        _event(w, "CP22", "2026-03-01", True)


def test_without_a_signed_pack_the_due_date_stays_empty_and_preflight_refuses(world):
    from app.modules.payroll import malaysia_service as my

    w = world
    row = _event(w)
    assert row.due_date is None and row.due_rule.startswith("PENDING")
    codes = [c for c, _m in my.my_event_problems(w.db, w.org, w.employee.id, PAY_DATE)]
    assert codes == ["MY_EVENT_DUE_UNKNOWN", "MY_CLEARANCE_HOLD_REQUIRED"]
    with pytest.raises(BadRequestException, match="never open-ended"):
        my.open_my_clearance_hold(w.db, w.org, row.id, w.a, "2026-06-01", "departing")


def test_submission_is_recorded_by_a_second_person_and_cancel_needs_a_reason(world, signed_pack):
    from app.modules.payroll import malaysia_service as my

    w = world
    row = _event(w, "CP22", "2026-03-01", False)
    w.db.commit()
    with pytest.raises(BadRequestException, match="receipt"):
        my.submit_my_employer_event(w.db, w.org, row.id, w.b, "2026-03-20", "", "scan")
    with pytest.raises(Exception, match="(?i)four|approv|same"):
        my.submit_my_employer_event(w.db, w.org, row.id, w.a, "2026-03-20", "R-1", "scan")
    w.db.rollback()
    done = my.submit_my_employer_event(w.db, w.org, row.id, w.b, "2026-03-20", "R-1", "scan")
    assert (done.status, done.receipt_ref) == ("SUBMITTED", "R-1")
    other = _event(w, "CP22", "2026-04-01", False)
    with pytest.raises(BadRequestException, match="reason"):
        my.cancel_my_employer_event(w.db, w.org, other.id, w.a, "")
    assert my.cancel_my_employer_event(w.db, w.org, other.id, w.a, "entered twice").status == "CANCELLED"


def test_overdue_events_and_missing_holds_stop_approval(world, signed_pack, with_pcb):
    from fastapi import HTTPException

    from app.modules.payroll import malaysia_service as my
    from app.modules.payroll.models import PayrollStatus

    w = world
    _setup(w)
    _event(w, "CP22", "2026-01-15", False)                                           # due 14 Feb, still OPEN
    _event(w, "CP21", "2026-06-30")                                                  # needs a hold
    run, _item = _run_with_payslip(w)
    codes = {p["code"] for p in my.my_run_preflight(w.db, run)}
    assert {"MY_EVENT_OVERDUE", "MY_CLEARANCE_HOLD_REQUIRED"} <= codes
    with pytest.raises(HTTPException, match="MY_EVENT_OVERDUE"):
        my.before_run_transition(w.db, run, PayrollStatus.APPROVED, w.b)


def test_a_hold_withholds_the_payslip_and_is_released_by_a_second_person(world, signed_pack, with_pcb):
    from app.modules.payroll import jurisdiction_hooks
    from app.modules.payroll import malaysia_service as my

    w = world
    _setup(w)
    event = _event(w, "CP21", "2026-04-30")
    hold = my.open_my_clearance_hold(w.db, w.org, event.id, w.a, "2026-03-01", "leaving Malaysia")
    assert (hold.state, hold.hold_until) == ("HELD", date(2026, 5, 30))               # + 90 signed days
    with pytest.raises(BadRequestException, match="already has an open"):
        my.open_my_clearance_hold(w.db, w.org, event.id, w.a, "2026-03-02", "again")
    run, item = _run_with_payslip(w)
    item.net_pay = Decimal("4315.35")
    out = jurisdiction_hooks.call("MY", "payment_treatment", w.db, w.org, run, [item])
    assert out[item.id][0] == "HELD"
    view = jurisdiction_hooks.call("MY", "payslip_hold_view", item)
    assert view == {"status": "HELD", "amount": "4315.35", "holdId": hold.id,
                    "basis": "Malaysia tax-clearance hold (CP22A / CP21) - money remains owed to the employee"}
    assert "MY_CLEARANCE_HOLD_REQUIRED" not in {c for c, _m in my.my_event_problems(w.db, w.org, w.employee.id,
                                                                                    PAY_DATE)}
    with pytest.raises(BadRequestException, match="clearance reference"):
        my.request_my_hold_release(w.db, w.org, hold.id, w.a, "", "")
    my.request_my_hold_release(w.db, w.org, hold.id, w.a, "HASiL clearance letter 123", "scan")
    w.db.commit()
    with pytest.raises(Exception, match="(?i)four|approv|same"):
        my.approve_my_hold_release(w.db, w.org, hold.id, w.a)
    w.db.rollback()
    released = my.approve_my_hold_release(w.db, w.org, hold.id, w.b)
    assert released.state == "RELEASED" and my.hold_view(w.db, released)["heldTotal"] == "0"
    assert jurisdiction_hooks.call("MY", "payment_treatment", w.db, w.org, run, [item]) == {}   # paid next file
    assert my.employee_summary(w.db, w.org, w.employee.id)["clearanceHolds"][0]["state"] == "RELEASED"


def test_a_hold_past_its_maximum_is_flagged_and_stops_withholding(world, signed_pack, with_pcb):
    from app.modules.payroll import malaysia_service as my

    w = world
    _setup(w)
    event = _event(w, "CP22A", "2026-01-31")
    my.open_my_clearance_hold(w.db, w.org, event.id, w.a, "2025-12-01", "retiring")    # held until 1 Mar 2026
    run, item = _run_with_payslip(w)
    assert my.my_payment_treatment(w.db, w.org, run, [item]) == {}
    assert "MY_CLEARANCE_HOLD_EXPIRED" in {c for c, _m in my.my_event_problems(w.db, w.org, w.employee.id,
                                                                               PAY_DATE)}
