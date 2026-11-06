"""Poland service layer (ZP-PL-ENG-001 Phase 4): versioned records with four-eyes
approval, statements (PL-005 / PL-007 / PL-010), the identifier vault (spec §13,
PL-025), calculation inputs selected by the pay date, freeze / replay, the run
gates, the year-to-date ledger and the 13 platform hooks."""
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.exceptions import BadRequestException, NotFoundException
from tests._pl_engine_helpers import build_pack

PAY_DATE = date(2026, 3, 31)
PESEL = "44051401359"
NRS = "PL61109010140000071219812874"  # privacy-scan: allow (published example account, not real)


@pytest.fixture
def world(db, monkeypatch):
    from app.config import settings
    from app.modules.payroll.models import PayrollEmployee
    from tests._mx_employer_helpers import make_org

    monkeypatch.setattr(settings, "PL_IDENTIFIER_KEYRING", json.dumps({"1": "k" * 32}))
    monkeypatch.setattr(settings, "PL_IDENTIFIER_FINGERPRINT_KEY", "f" * 32)
    t = make_org(db, name="Spółka Testowa", code="PLSVC", admins=2, country="PL")
    employee = PayrollEmployee(organization_id=t.org.id, employee_code="PL1", name="Jan Kowalski", country_code="PL")
    db.add(employee)
    db.commit()
    return SimpleNamespace(db=db, org=t.org.id, a=t.users[0].id, b=t.users[1].id, employee=employee)


def _registration(w, **over):
    from app.modules.payroll import poland_service as pl

    payload = {"effective_from": "2026-01-01", "legal_name": "Spółka Testowa sp. z o.o.", "nip": "526-104-08-28",
               "regon": "123456785", "zus_deadline_class": "day_15", "accident_rate_pct": "1.67",
               "accident_rate_source": "ZUS_NOTICE", "accident_rate_from": "2025-04-01",
               "accident_rate_to": "2026-03-31", "accident_rate_evidence_ref": "ZUS notice 2025",
               "fp_fs_applicable": True, "fgsp_applicable": True}
    payload.update(over)
    row = pl.record_pl_employer_registration(w.db, w.org, payload, w.a, "initial setup")
    pl.approve_pl_employer_registration(w.db, w.org, row.id, w.b)
    pl.verify_pl_employer_registration(w.db, w.org, row.id, w.b, "verified", "checked against KRS / ZUS")
    return row


def _profile(w, **over):
    from app.modules.payroll import poland_service as pl

    payload = {"effective_from": "2026-01-01", "contract_type": "umowa_o_prace", "insurance_title_code": "011000",
               "cov_pension": True, "cov_disability": True, "cov_sickness": True, "cov_accident": True,
               "cov_health": True, "other_titles_declared": False, "a1_certificate": False, "is_student": False,
               "is_pensioner": False, "pay_frequency": "monthly", "fte_numerator": 1, "fte_denominator": 1,
               "service_credit_months": 60}
    payload.update(over)
    row = pl.record_pl_worker_profile(w.db, w.org, w.employee.id, payload, w.a, "hire")
    return pl.approve_pl_worker_profile(w.db, w.org, row.id, w.b)


def _statement(w, kind, value=None, start="2026-01-01", approve=True):
    from app.modules.payroll import poland_service as pl

    row = pl.record_pl_declaration(w.db, w.org, w.employee.id, {
        "declaration_type": kind, "value": value or {}, "received_at": "2025-12-20T10:00:00",
        "effective_from": start, "source_channel": "PAPER", "evidence_ref": f"scan-{kind}"}, w.a)
    return pl.approve_pl_declaration(w.db, w.org, row.id, w.b) if approve else row


def _ppk(w, state="ENROLLED"):
    from app.modules.payroll import poland_service as pl

    row = pl.record_pl_ppk_participation(w.db, w.org, w.employee.id, {
        "effective_from": "2026-01-01", "state": state, "enrolment_date": "2026-01-01"}, w.a, "auto-enrolment")
    return pl.approve_pl_ppk_participation(w.db, w.org, row.id, w.b)


def _setup(w):
    _registration(w)
    _profile(w)
    _ppk(w)
    _statement(w, "PIT2", {"allocation": "full"})
    w.db.commit()


# ── versioned records and four-eyes ────────────────────────────────────────
def test_registration_needs_a_second_approver_and_valid_identifiers(world):
    from app.modules.payroll import poland_service as pl

    w = world
    row = pl.record_pl_employer_registration(w.db, w.org, {
        "effective_from": "2026-01-01", "legal_name": "X", "nip": "5261040828", "zus_deadline_class": "DAY_15"},
        w.a, "setup")
    assert row.status == "DRAFT" and row.zus_deadline_class == "DAY_15"
    w.db.commit()                       # the API commits each step; a refused approval rolls back + audits
    with pytest.raises(Exception, match="(?i)four|approv|same"):
        pl.approve_pl_employer_registration(w.db, w.org, row.id, w.a)
    assert pl.approve_pl_employer_registration(w.db, w.org, row.id, w.b).status == "ACTIVE"
    for bad, message in (({"nip": "5261040827"}, "NIP"), ({"regon": "123456786"}, "REGON"),
                         ({"zus_deadline_class": "DAY_10"}, "zus_deadline_class"),
                         ({"accident_rate_pct": "1.67"}, "accident rate")):
        payload = {"effective_from": "2026-02-01", "legal_name": "X", "nip": "5261040828",
                   "zus_deadline_class": "DAY_15", **bad}
        with pytest.raises(BadRequestException, match=message):
            pl.record_pl_employer_registration(w.db, w.org, payload, w.a, "setup")
    with pytest.raises(BadRequestException, match="reason"):
        pl.record_pl_employer_registration(w.db, w.org, {"effective_from": "2026-01-01"}, w.a, "")
    with pytest.raises(BadRequestException, match="unknown field"):
        pl.record_pl_employer_registration(w.db, w.org, {"effective_from": "2026-01-01", "status": "ACTIVE"},
                                           w.a, "setup")


def test_a_new_profile_version_supersedes_the_old_one(world):
    from app.modules.payroll import poland_service as pl

    w = world
    first = _profile(w)
    second = _profile(w, effective_from="2026-06-01", cov_sickness=False)
    assert first.status == "SUPERSEDED" and first.effective_to == date(2026, 5, 31)
    assert second.status == "ACTIVE"
    with pytest.raises(BadRequestException, match="FEP"):
        pl.record_pl_worker_profile(w.db, w.org, w.employee.id, {"effective_from": "2026-07-01",
                                                                 "contract_type": "UMOWA_O_PRACE",
                                                                 "fep_qualifying": True}, w.a, "x")
    with pytest.raises(BadRequestException, match="6-digit"):
        pl.record_pl_worker_profile(w.db, w.org, w.employee.id, {"effective_from": "2026-07-01",
                                                                 "contract_type": "UMOWA_O_PRACE",
                                                                 "insurance_title_code": "0110"}, w.a, "x")


def test_another_organisation_cannot_touch_the_records(world):
    from app.modules.payroll import poland_service as pl

    w = world
    row = _profile(w)
    with pytest.raises(NotFoundException):
        pl.approve_pl_worker_profile(w.db, w.org + 999, row.id, w.b)
    with pytest.raises(NotFoundException):
        pl.record_pl_worker_profile(w.db, w.org + 999, w.employee.id, {"effective_from": "2026-01-01",
                                                                       "contract_type": "UMOWA_O_PRACE"}, w.a, "x")


# ── statements (PL-005 / PL-007 / PL-010) ──────────────────────────────────
def test_statements_need_evidence_and_valid_values(world):
    from app.modules.payroll import poland_service as pl

    w = world
    base = {"declaration_type": "PIT2", "value": {"allocation": "FULL"}, "received_at": "2025-12-20",
            "effective_from": "2026-01-01", "source_channel": "PAPER", "evidence_ref": "scan"}
    with pytest.raises(BadRequestException, match="evidence_ref"):
        pl.record_pl_declaration(w.db, w.org, w.employee.id, {**base, "evidence_ref": None}, w.a)
    with pytest.raises(BadRequestException, match="FULL, HALF or THIRD"):
        pl.record_pl_declaration(w.db, w.org, w.employee.id, {**base, "value": {"allocation": "QUARTER"}}, w.a)
    with pytest.raises(BadRequestException, match="otherSourcesIncome"):
        pl.record_pl_declaration(w.db, w.org, w.employee.id,
                                 {**base, "declaration_type": "PPK_REDUCED_RATE", "value": {"ratePct": "0.5"}}, w.a)
    row = pl.record_pl_declaration(w.db, w.org, w.employee.id, base, w.a)
    assert row.status == "RECEIVED" and row.received_at.year == 2025
    with pytest.raises(Exception):
        pl.approve_pl_declaration(w.db, w.org, row.id, w.a)                          # four-eyes


def test_a_new_statement_supersedes_and_history_is_kept(world):
    from app.modules.payroll import poland_service as pl

    w = world
    old = _statement(w, "PIT2", {"allocation": "FULL"})
    new = _statement(w, "PIT2", {"allocation": "HALF"}, start="2026-04-01")
    assert (old.status, old.effective_to, old.superseded_by_id) == ("SUPERSEDED", date(2026, 3, 31), new.id)
    withdrawn = pl.withdraw_pl_declaration(w.db, w.org, new.id, w.a, "employee withdrew", "2026-08-31")
    assert withdrawn.status == "WITHDRAWN" and withdrawn.effective_to == date(2026, 8, 31)
    _statement(w, "PIT2", {"allocation": "FULL"}, start="2026-09-01")
    with pytest.raises(BadRequestException, match="already starts"):
        _statement(w, "PIT2", {"allocation": "FULL"}, start="2026-02-01")       # never back-dated over a later one


def test_approved_prior_employer_cap_posts_evidenced_ledger_entries(world):
    from app.modules.payroll import poland_service as pl

    w = world
    _statement(w, "PRIOR_EMPLOYER_CAP", {"pensionBase": "100000", "disabilityBase": "90000"}, start="2026-02-01")
    ytd = pl.pl_ytd_snapshot(w.db, w.org, w.employee.id, None, PAY_DATE)
    assert ytd["ZUS_CAP_PENSION_BASE"] == Decimal("100000") and ytd["ZUS_CAP_DISABILITY_BASE"] == Decimal("90000")
    assert ytd["PIT_TAXABLE_INCOME"] == Decimal("0")                               # every key present
    view = pl.pl_annual_cap_view(w.db, w.org, w.employee.id, 2026)
    assert {e["kind"] for e in view["entries"]} == {"PRIOR_EMPLOYER"}
    assert all(e["evidenceRef"] for e in view["entries"])


def test_ppk_opt_out_needs_an_approved_statement(world):
    from app.modules.payroll import poland_service as pl

    w = world
    with pytest.raises(BadRequestException, match="PPK_OPT_OUT"):
        pl.record_pl_ppk_participation(w.db, w.org, w.employee.id, {"effective_from": "2026-01-01",
                                                                    "state": "OPTED_OUT"}, w.a, "x")
    statement = _statement(w, "PPK_OPT_OUT")
    row = pl.record_pl_ppk_participation(w.db, w.org, w.employee.id, {
        "effective_from": "2026-01-01", "state": "OPTED_OUT", "opt_out_declaration_id": statement.id,
        "next_reenrolment_date": "2026-03-01"}, w.a, "opt-out")
    pl.approve_pl_ppk_participation(w.db, w.org, row.id, w.b)
    assert pl.pl_ppk_reenrolment_due(w.db, w.org, date(2026, 3, 1))[0]["employeeId"] == w.employee.id
    assert pl.pl_ppk_reenrolment_due(w.db, w.org, date(2026, 2, 28)) == []


# ── identifier vault (spec §13, PL-025) ────────────────────────────────────
def test_vault_stores_ciphertext_only_and_masks_everywhere(world):
    from app.modules.payroll import poland_service as pl
    from app.modules.payroll.models import PayrollPlIdentifierAccessEvent, PayrollPlIdentifierVault

    w = world
    row = pl.create_pl_identifier(w.db, w.org, "pesel", "440514-01359", w.a, employee_id=w.employee.id)
    stored = w.db.get(PayrollPlIdentifierVault, row.id)
    assert PESEL not in (stored.ciphertext or "") and PESEL not in stored.fingerprint
    view = pl.identifier_view(stored)
    assert view["onFile"] and not any(ch.isdigit() for ch in view["masked"])
    assert PESEL not in json.dumps(pl.list_pl_identifiers(w.db, w.org, w.employee.id))
    assert PESEL not in json.dumps(pl.employee_summary(w.db, w.org, w.employee.id), default=str)
    with pytest.raises(BadRequestException, match="already"):
        pl.create_pl_identifier(w.db, w.org, "PESEL", PESEL, w.a, employee_id=w.employee.id)
    with pytest.raises(BadRequestException) as raised:
        pl.create_pl_identifier(w.db, w.org, "PESEL", "44051401358", w.a, employee_id=w.employee.id)
    assert "44051401358" not in str(raised.value.detail)
    assert w.db.query(PayrollPlIdentifierAccessEvent).filter_by(vault_id=row.id, action="CREATE").count() == 1


def test_reveal_is_requested_approved_by_another_person_and_single_use(world):
    from app.modules.payroll import poland_service as pl

    w = world
    row = pl.create_pl_identifier(w.db, w.org, "PESEL", PESEL, w.a, employee_id=w.employee.id)
    with pytest.raises(BadRequestException, match="request"):
        pl.reveal_pl_identifier(w.db, w.org, row.id, w.a)
    with pytest.raises(BadRequestException, match="reason"):
        pl.request_pl_identifier_reveal(w.db, w.org, row.id, "", w.a)
    pl.request_pl_identifier_reveal(w.db, w.org, row.id, "ZUS registration ZUA", w.a)
    w.db.commit()                       # the API commits each step; a refused approval rolls back + audits
    with pytest.raises(Exception):
        pl.approve_pl_identifier_reveal(w.db, w.org, row.id, w.a)                    # four-eyes
    pl.approve_pl_identifier_reveal(w.db, w.org, row.id, w.b)
    with pytest.raises(BadRequestException, match="requested"):
        pl.reveal_pl_identifier(w.db, w.org, row.id, w.b)                            # only the requester
    assert pl.reveal_pl_identifier(w.db, w.org, row.id, w.a)["value"] == PESEL
    with pytest.raises(BadRequestException, match="already been used"):
        pl.reveal_pl_identifier(w.db, w.org, row.id, w.a)
    deleted = pl.delete_pl_identifier(w.db, w.org, row.id, w.a, "left the company")
    assert deleted.ciphertext is None and pl.identifier_view(deleted)["masked"] is None


def test_employer_nrs_links_only_to_a_draft_registration(world):
    from app.modules.payroll import poland_service as pl

    w = world
    active = _registration(w)
    with pytest.raises(BadRequestException, match="DRAFT"):
        pl.set_pl_employer_nrs(w.db, w.org, active.id, NRS, w.a)
    draft = pl.record_pl_employer_registration(w.db, w.org, {
        "effective_from": "2026-07-01", "legal_name": "X", "nip": "5261040828", "zus_deadline_class": "DAY_15"},
        w.a, "new version")
    vault = pl.set_pl_employer_nrs(w.db, w.org, draft.id, NRS, w.a)
    assert draft.nrs_vault_id == vault.id and vault.identifier_type == "NRS" and vault.employee_id is None


def test_vault_refuses_without_keys(world, monkeypatch):
    from app.config import settings
    from app.modules.payroll import poland_service as pl

    monkeypatch.setattr(settings, "PL_IDENTIFIER_FINGERPRINT_KEY", "")
    with pytest.raises(BadRequestException, match="FINGERPRINT_KEY"):
        pl.create_pl_identifier(world.db, world.org, "PESEL", PESEL, world.a, employee_id=world.employee.id)


# ── calculation inputs -> engine, freeze / replay ──────────────────────────
def _context(w, inputs):
    from app.modules.payroll.engine.base import PayrollContext

    rate_map, slabs = build_pack()
    return PayrollContext(gross=Decimal("8000"), basic=Decimal("8000"), country="PL", rate_map=rate_map,
                          slabs=slabs, pay_date=PAY_DATE, **inputs)


def test_inputs_from_the_records_reproduce_the_golden_result(world):
    from app.modules.payroll import poland_service as pl
    from app.modules.payroll.engine.resolver import calculate_payroll

    w = world
    _setup(w)
    inputs = pl.calc_inputs(w.db, None, w.employee, None, as_of=PAY_DATE)
    assert inputs["pl_profile"]["status"] == "ACTIVE" and inputs["pl_registration"]["status"] == "ACTIVE"
    assert [d["declaration_type"] for d in inputs["pl_declarations"]] == ["PIT2"]
    result = calculate_payroll(_context(w, inputs), "standard")
    assert result.net_pay == Decimal("5608.91") and result.tds == Decimal("513.00")      # golden f1


def test_inputs_need_a_pay_date(world):
    from app.modules.payroll import poland_service as pl

    with pytest.raises(BadRequestException, match="pay date"):
        pl.calc_inputs(world.db, None, world.employee, None)


def test_missing_records_stay_missing_and_the_engine_blocks(world):
    from app.modules.payroll import poland_service as pl
    from app.modules.payroll.engine.countries.poland import PLCalculationBlockedError, calculate

    w = world
    inputs = pl.calc_inputs(w.db, None, w.employee, None, as_of=PAY_DATE)
    assert inputs["pl_profile"] is None and inputs["pl_registration"] is None and inputs["pl_ppk"] is None
    with pytest.raises(PLCalculationBlockedError, match="PL_PROFILE_MISSING"):
        calculate(_context(w, inputs))


def test_freeze_and_replay_reproduce_the_same_hashes(world):
    from app.modules.payroll import poland_service as pl
    from app.modules.payroll.engine.resolver import calculate_payroll

    w = world
    _setup(w)
    pl.create_pl_identifier(w.db, w.org, "PESEL", PESEL, w.a, employee_id=w.employee.id)
    ctx = _context(w, pl.calc_inputs(w.db, None, w.employee, None, as_of=PAY_DATE))
    original = calculate_payroll(ctx, "standard")
    frozen = json.loads(json.dumps(pl.pl_freeze_context(ctx, "standard")))         # through JSON, as stored
    replayed = pl.pl_replay(frozen)
    assert replayed.net_pay == original.net_pay
    assert replayed.pl_result["hashes"] == original.pl_result["hashes"]
    assert PESEL not in json.dumps(frozen) and "pesel_vault_id" not in json.dumps(frozen)
    snapshot = pl.pl_payslip_snapshot(original, frozen)
    assert snapshot["frozenContext"] == frozen and snapshot["pl_net"] == "5608.91"


# ── run gates and the ledger ───────────────────────────────────────────────
def _run_with_payslip(w, status="Processed"):
    from app.modules.payroll import poland_service as pl
    from app.modules.payroll.engine.resolver import calculate_payroll
    from app.modules.payroll.models import PayrollRun, PayslipItem

    ctx = _context(w, pl.calc_inputs(w.db, None, w.employee, None, as_of=PAY_DATE))
    result = calculate_payroll(ctx, "standard")
    run = PayrollRun(organization_id=w.org, period_label="Mar 2026", period_start=date(2026, 3, 1),
                     period_end=PAY_DATE, pay_date=PAY_DATE, status=status)
    w.db.add(run)
    w.db.flush()
    item = PayslipItem(payroll_run_id=run.id, employee_id=w.employee.id, organization_id=w.org,
                       employee_name=w.employee.name, country_code="PL", gross_pay=Decimal("8000"),
                       pl_calculation_snapshot=pl.pl_payslip_snapshot(result, pl.pl_freeze_context(ctx)))
    w.db.add(item)
    w.db.commit()
    return run, item


def test_approval_is_refused_while_preflight_finds_problems(world):
    from fastapi import HTTPException

    from app.modules.payroll import poland_service as pl
    from app.modules.payroll.models import PayrollStatus

    w = world
    _setup(w)
    run, _item = _run_with_payslip(w)
    codes = {p["code"] for p in pl.pl_run_preflight(w.db, run)}
    assert {"CONTENT_PACK_OUT_OF_DATE", "MISSING_IDENTIFIER"} <= codes             # no Active pack, no PESEL
    with pytest.raises(HTTPException) as raised:
        pl.before_run_transition(w.db, run, PayrollStatus.APPROVED, w.b)
    assert raised.value.status_code == 409 and "MISSING_IDENTIFIER" in raised.value.detail


def test_paid_posts_the_ledger_once_and_needs_the_approved_fingerprint(world):
    from fastapi import HTTPException

    from app.modules.payroll import poland_service as pl
    from app.modules.payroll.models import PayrollPlAccumulatorEntry, PayrollStatus

    w = world
    _setup(w)
    run, item = _run_with_payslip(w)
    with pytest.raises(HTTPException, match="no longer matches"):
        pl.before_run_transition(w.db, run, PayrollStatus.PAID, w.b)               # never approved
    run.pl_approval_fingerprint = pl.pl_approval_fingerprint(w.db, run)
    pl.before_run_transition(w.db, run, PayrollStatus.PAID, w.b)
    pl.before_run_transition(w.db, run, PayrollStatus.PAID, w.b)                   # idempotent
    entries = w.db.query(PayrollPlAccumulatorEntry).filter_by(payslip_item_id=item.id).all()
    assert {e.accumulator: str(e.amount) for e in entries}["PIT_TAXABLE_INCOME"] == "6773.00"
    assert len(entries) == len(item.pl_calculation_snapshot["accumulatorDeltas"])
    assert pl.pl_ytd_snapshot(w.db, w.org, w.employee.id, None, date(2026, 4, 30))["PIT_ADVANCE"] == Decimal("513")
    assert pl.pl_ytd_snapshot(w.db, w.org, w.employee.id, None, PAY_DATE)["PIT_ADVANCE"] == Decimal("0")
    item.pl_calculation_snapshot = {**item.pl_calculation_snapshot, "pl_net": "1.00"}
    w.db.commit()
    with pytest.raises(HTTPException, match="no longer matches"):
        pl.before_run_transition(w.db, run, PayrollStatus.AUTHORIZED, w.b)


# ── hooks, governance, dormancy ────────────────────────────────────────────
def test_all_thirteen_hooks_are_registered():
    from app.modules.payroll import jurisdiction_hooks, poland_service

    from app.modules.payroll import new_zealand_service

    assert jurisdiction_hooks.has_module("PL")
    names = set(new_zealand_service.JURISDICTION_HOOKS)
    assert set(poland_service.JURISDICTION_HOOKS) == names
    for name in names:
        assert callable(jurisdiction_hooks.get("PL", name))


def test_retention_registry_template_and_activation_hooks(world):
    from app.modules.payroll import jurisdiction_hooks, retention_service

    w = world
    settings = retention_service.settings("PL")
    assert settings.country == "PL" and settings.period_decision == "D-7"
    template = SimpleNamespace(jurisdiction_country="PL", report_type="PL_DRA")
    assert "G4" in jurisdiction_hooks.call("PL", "template_activation_refusal", w.db, template, None)
    assert jurisdiction_hooks.call("PL", "template_activation_refusal", w.db,
                                   SimpleNamespace(jurisdiction_country="ZA", report_type="ZA_EMP201"), None) is None
    pack = SimpleNamespace(jurisdiction_country="PL", id=0, pack_id="PL-PAYROLL-2026")
    assert "no statutory content" in jurisdiction_hooks.call("PL", "pack_activation_refusal", w.db, pack, None)
    summary = jurisdiction_hooks.call("PL", "statutory_summary", w.db)
    assert summary["available"] is False and [u["key"] for u in summary["unmet"]][:2] == ["G1", "G2"]


def test_poland_cannot_be_opened_before_the_gates(world):
    from app.modules.payroll import jurisdiction_hooks

    with pytest.raises(Exception):
        jurisdiction_hooks.call("PL", "service_registry_transition", world.db, "AVAILABLE", "launch", world.a)


def test_router_is_dormant_and_poland_only(world, monkeypatch):
    from app.config import settings
    from app.modules.payroll.pl_org_router import require_pl_tenant
    from tests._mx_employer_helpers import make_org, principal

    w = world
    with pytest.raises(NotFoundException, match="not open"):
        require_pl_tenant(principal(w.org), w.db)
    monkeypatch.setattr(settings, "PL_TENANT_ONBOARDING_ENABLED", True)
    assert require_pl_tenant(principal(w.org), w.db) is None
    other = make_org(w.db, name="Other", code="PLOTHER", country="MX")
    with pytest.raises(NotFoundException, match="only available"):
        require_pl_tenant(principal(other.org.id), w.db)


def test_router_exposes_identifiers_only_masked():
    from app.modules.payroll.pl_org_router import router

    paths = {(sorted(r.methods)[0], r.path) for r in router.routes}
    assert ("POST", "/poland/identifiers/{vault_id}/reveal") in paths
    assert all("/poland/" in p for _m, p in paths)


# ── Phase 5: annual leave entitlement through the service ──────────────────
def test_leave_entitlement_needs_a_profile_and_an_active_pack(world):
    from app.modules.payroll import poland_service as pl

    w = world
    with pytest.raises(BadRequestException, match="worker profile"):
        pl.pl_leave_entitlement(w.db, w.org, w.employee.id, "2026-03-31")
    _profile(w)
    with pytest.raises(BadRequestException, match="rule pack"):
        pl.pl_leave_entitlement(w.db, w.org, w.employee.id, "2026-03-31")      # the seeded pack is still Draft


def test_leave_entitlement_from_an_active_signed_pack(world):
    from app.modules.payroll import poland_service as pl
    from app.modules.payroll.models import ContributionRate, TaxSlab

    w = world
    _profile(w, service_credit_months=130)
    pack = pl.seed_poland_pack(w.db)
    for row in w.db.query(ContributionRate).filter_by(jurisdiction_pack_id=pack.id):
        row.label = row.label.replace(pl.PENDING_G1_SUFFIX, "")                  # simulate the G1 signature
    pack.status = "Active"
    w.db.commit()
    assert w.db.query(TaxSlab).filter_by(jurisdiction_pack_id=pack.id).count() > 0
    out = pl.pl_leave_entitlement(w.db, w.org, w.employee.id, "2026-03-31")
    assert (out["tier"], out["days"]) == ("SENIOR", "26")
