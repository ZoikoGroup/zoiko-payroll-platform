"""Belgium (ZP-BE-ENG-001) Block A1: statutory setup through the service layer.

Versioned records (employer registration, establishment unit, worker profile,
work schedule, employment classification) with four-eyes approval, received
declarations, the identifier vault (masked everywhere, single-use reveal), the
one-active indexes and the dormant, Belgium-only organisation router.

Every identifier below is SYNTHETIC TEST ONLY data (right digit count, no real
person); no statutory value is used anywhere."""
import json
import logging
from datetime import date
from types import SimpleNamespace

import pytest

from app.core.exceptions import BadRequestException, NotFoundException

NISS = "12312312312"  # privacy-scan: allow (synthetic TEST ONLY value)
ONSS = "9876543"  # privacy-scan: allow (synthetic TEST ONLY value)
KBO = "0999.999.999"  # privacy-scan: allow (synthetic TEST ONLY value)


@pytest.fixture
def world(db, monkeypatch):
    from app.config import settings
    from app.modules.payroll.models import PayrollEmployee
    from tests._mx_employer_helpers import make_org

    monkeypatch.setattr(settings, "BE_IDENTIFIER_KEYRING", json.dumps({"1": "k" * 32}))
    monkeypatch.setattr(settings, "BE_IDENTIFIER_FINGERPRINT_KEY", "f" * 32)
    t = make_org(db, name="Test BV", code="BESETUP", admins=2, country="BE")
    employee = PayrollEmployee(organization_id=t.org.id, employee_code="BE1", name="Test Worker", country_code="BE")
    db.add(employee)
    db.commit()
    return SimpleNamespace(db=db, org=t.org.id, a=t.users[0].id, b=t.users[1].id, employee=employee)


def _svc():
    from app.modules.payroll import belgium_service as be

    return be


def _registration(w, approve=True, **over):
    be = _svc()
    payload = {"effective_from": "2026-01-01", "legal_name": "Test BV", "enterprise_number": KBO,
               "legal_language": "nl", "employer_category_code": "x1"}
    payload.update(over)
    row = be.record_be_employer_registration(w.db, w.org, payload, w.a, "initial setup")
    w.db.commit()
    return be.approve_be_employer_registration(w.db, w.org, row.id, w.b) if approve else row


def _profile(w, **over):
    be = _svc()
    payload = {"effective_from": "2026-01-01", "worker_category": "employee", "residency": "resident"}
    payload.update(over)
    row = be.record_be_worker_profile(w.db, w.org, w.employee.id, payload, w.a, "hire")
    w.db.commit()
    return be.approve_be_worker_profile(w.db, w.org, row.id, w.b)


# ── versioned records and four-eyes ────────────────────────────────────────
def test_registration_is_a_draft_until_a_second_person_approves(world):
    be, w = _svc(), world
    row = _registration(w, approve=False)
    assert row.status == "DRAFT" and row.enterprise_number == "0999999999"
    assert row.legal_language == "NL" and row.employer_category_code == "X1"
    with pytest.raises(Exception, match="(?i)four|approv|same"):
        be.approve_be_employer_registration(w.db, w.org, row.id, w.a)
    w.db.rollback()
    assert be.approve_be_employer_registration(w.db, w.org, row.id, w.b).status == "ACTIVE"
    with pytest.raises(BadRequestException, match="outcome"):
        be.verify_be_employer_registration(w.db, w.org, row.id, w.b, "maybe", "checked")
    assert be.verify_be_employer_registration(w.db, w.org, row.id, w.b, "verified",
                                              "checked against KBO").verification_state == "VERIFIED"


@pytest.mark.parametrize("bad, message", [({"enterprise_number": "12"}, "enterprise_number"),
                                          ({"legal_language": "EN"}, "legal_language"),
                                          ({"employer_category_code": "!!"}, "employer_category_code"),
                                          ({"mandate_refs": {"secret": "x"}}, "mandate_refs"),
                                          ({"status": "ACTIVE"}, "unknown field"),
                                          ({"effective_to": "2025-01-01"}, "effective_to"),
                                          ({"effective_from": "first of May"}, "ISO date")])
def test_registration_validation(world, bad, message):
    with pytest.raises(BadRequestException, match=message):
        _registration(world, approve=False, **bad)


def test_every_change_needs_a_reason(world):
    be, w = _svc(), world
    with pytest.raises(BadRequestException, match="reason"):
        be.record_be_employer_registration(w.db, w.org, {"effective_from": "2026-01-01", "legal_name": "X",
                                                         "enterprise_number": KBO}, w.a, " ")


def test_a_new_version_supersedes_the_old_one_and_an_earlier_one_refuses(world):
    be, w = _svc(), world
    first = _profile(w)
    second = _profile(w, effective_from="2026-06-01", worker_category="MANUAL")
    assert first.status == "SUPERSEDED" and first.effective_to == date(2026, 5, 31)
    assert second.status == "ACTIVE" and second.previous_version_id == first.id
    late = be.record_be_worker_profile(w.db, w.org, w.employee.id, {"effective_from": "2026-03-01",
                                                                    "worker_category": "EMPLOYEE"}, w.a, "x")
    with pytest.raises(BadRequestException, match="on or after"):
        be.approve_be_worker_profile(w.db, w.org, late.id, w.b)
    assert be._one_active(w.db, be._models().PayrollBeWorkerProfile, w.org, date(2026, 7, 1), "profile",
                          employee_id=w.employee.id).id == second.id


def test_profile_validation(world):
    be, w = _svc(), world
    for bad, message in (({"worker_category": "PILOT"}, "worker_category"), ({"residency": "MARS"}, "residency"),
                         ({"onss_worker_code": "TOO-LONG"}, "onss_worker_code"),
                         ({"niss_vault_id": 999999}, "Belgian identifier")):
        payload = {"effective_from": "2026-01-01", "worker_category": "EMPLOYEE", **bad}
        with pytest.raises((BadRequestException, NotFoundException), match=message):
            be.record_be_worker_profile(w.db, w.org, w.employee.id, payload, w.a, "x")


def test_establishment_unit_belongs_to_a_registration_of_the_organisation(world):
    be, w = _svc(), world
    registration = _registration(w)
    unit = be.record_be_establishment_unit(w.db, w.org, {"registration_id": registration.id, "unit_number": "2.000",
                                                         "name": "Site A", "effective_from": "2026-01-01"},
                                           w.a, "site")
    w.db.commit()
    assert unit.unit_number == "2000" and unit.legal_entity_id == registration.legal_entity_id
    assert be.approve_be_establishment_unit(w.db, w.org, unit.id, w.b).status == "ACTIVE"
    with pytest.raises(NotFoundException):
        be.record_be_establishment_unit(w.db, w.org + 999, {"registration_id": registration.id, "unit_number": "1",
                                                            "name": "X", "effective_from": "2026-01-01"}, w.a, "x")
    with pytest.raises(BadRequestException, match="unit_number"):
        be.record_be_establishment_unit(w.db, w.org, {"registration_id": registration.id, "unit_number": "A1",
                                                      "name": "X", "effective_from": "2026-01-01"}, w.a, "x")


def test_schedules_keep_their_own_lineage_per_employment_line(world):
    be, w = _svc(), world
    first = be.record_be_work_schedule(w.db, w.org, w.employee.id, {"effective_from": "2026-01-01",
                                                                    "regime": "effective", "weekly_hours": "38"},
                                       w.a, "line 1")
    other = be.record_be_work_schedule(w.db, w.org, w.employee.id, {"effective_from": "2026-01-01",
                                                                    "regime": "AVERAGE", "weekly_hours": "10"},
                                       w.a, "line 2")
    w.db.commit()
    be.approve_be_work_schedule(w.db, w.org, first.id, w.b)
    be.approve_be_work_schedule(w.db, w.org, other.id, w.b)
    successor = be.record_be_work_schedule(w.db, w.org, w.employee.id, {
        "effective_from": "2026-04-01", "regime": "EFFECTIVE", "weekly_hours": "30", "supersedes_id": first.id},
        w.a, "part time")
    w.db.commit()
    be.approve_be_work_schedule(w.db, w.org, successor.id, w.b)
    assert first.status == "SUPERSEDED" and first.effective_to == date(2026, 3, 31)
    assert other.status == "ACTIVE" and other.effective_to is None          # the other line is untouched
    for bad, message in (({"regime": "FLEX"}, "regime"), ({"weekly_hours": "0"}, "above zero"),
                         ({"weekly_hours": "lots"}, "decimal")):
        payload = {"effective_from": "2026-01-01", "regime": "EFFECTIVE", "weekly_hours": "38", **bad}
        with pytest.raises(BadRequestException, match=message):
            be.record_be_work_schedule(w.db, w.org, w.employee.id, payload, w.a, "x")


def test_classification_is_per_employment_line_and_checks_its_references(world):
    be, w = _svc(), world
    row = be.record_be_employment_classification(w.db, w.org, w.employee.id, {
        "effective_from": "2026-01-01", "employment_line": "MAIN", "joint_committee": "200",
        "sub_committee": "a1", "seniority_months": 12}, w.a, "hire")
    w.db.commit()
    assert row.sub_committee == "A1"
    assert be.approve_be_employment_classification(w.db, w.org, row.id, w.b).status == "ACTIVE"
    second_line = be.record_be_employment_classification(w.db, w.org, w.employee.id, {
        "effective_from": "2026-01-01", "employment_line": "SECOND", "joint_committee": "124"}, w.a, "second job")
    w.db.commit()
    assert be.approve_be_employment_classification(w.db, w.org, second_line.id, w.b).status == "ACTIVE"
    assert row.status == "ACTIVE"
    for bad, err in (({"joint_committee": "abc"}, BadRequestException),
                     ({"joint_committee": None, "sub_committee": "A1"}, BadRequestException),
                     ({"seniority_months": -1}, BadRequestException),
                     ({"establishment_unit_id": 999999}, NotFoundException),
                     ({"work_schedule_id": 999999}, NotFoundException),
                     ({"collective_agreement_id": 999999}, NotFoundException)):
        payload = {"effective_from": "2026-02-01", "employment_line": "MAIN", **bad}
        with pytest.raises(err):
            be.record_be_employment_classification(w.db, w.org, w.employee.id, payload, w.a, "x")


def test_records_are_for_belgian_employees_of_the_organisation_only(world):
    from app.modules.payroll.models import PayrollEmployee

    be, w = _svc(), world
    foreign = PayrollEmployee(organization_id=w.org, employee_code="NL1", name="Other", country_code="NL")
    w.db.add(foreign)
    w.db.commit()
    with pytest.raises(NotFoundException, match="Belgian employee"):
        be.record_be_worker_profile(w.db, w.org, foreign.id, {"effective_from": "2026-01-01",
                                                              "worker_category": "EMPLOYEE"}, w.a, "x")
    with pytest.raises(NotFoundException):
        be.record_be_worker_profile(w.db, w.org + 999, w.employee.id, {"effective_from": "2026-01-01",
                                                                       "worker_category": "EMPLOYEE"}, w.a, "x")
    row = _profile(w)
    with pytest.raises(NotFoundException):
        be.approve_be_worker_profile(w.db, w.org + 999, row.id, w.b)


# ── one-active indexes (database backstop) ─────────────────────────────────
def test_the_database_refuses_two_open_active_profiles(world):
    from sqlalchemy.exc import IntegrityError

    be, w = _svc(), world
    P = be._models().PayrollBeWorkerProfile
    for start in (date(2026, 1, 1), date(2026, 2, 1)):
        w.db.add(P(organization_id=w.org, employee_id=w.employee.id, effective_from=start,
                   worker_category="EMPLOYEE", status="ACTIVE"))
    with pytest.raises(IntegrityError):
        w.db.flush()
    w.db.rollback()


def test_the_database_refuses_two_open_active_registrations_for_the_organisation(world):
    from sqlalchemy.exc import IntegrityError

    be, w = _svc(), world
    R = be._models().PayrollBeEmployerRegistration
    for start in (date(2026, 1, 1), date(2026, 2, 1)):
        w.db.add(R(organization_id=w.org, effective_from=start, legal_name="X", enterprise_number="0999999999",
                   status="ACTIVE"))
    with pytest.raises(IntegrityError):
        w.db.flush()
    w.db.rollback()


# ── declarations ────────────────────────────────────────────────────────────
def _declaration(w, start="2026-01-01", value=None):
    be = _svc()
    row = be.record_be_declaration(w.db, w.org, w.employee.id, {
        "declaration_type": "family_situation", "value": value or {"note": "TEST ONLY"},
        "received_at": "2025-12-20T10:00:00", "effective_from": start, "source_channel": "paper",
        "evidence_ref": "scan-TEST"}, w.a)
    w.db.commit()
    return row


def test_declarations_are_received_then_approved_superseded_and_withdrawn(world):
    be, w = _svc(), world
    first = _declaration(w)
    assert first.status == "RECEIVED" and first.declaration_type == "FAMILY_SITUATION"
    with pytest.raises(Exception, match="(?i)four|approv|same"):
        be.approve_be_declaration(w.db, w.org, first.id, w.a)
    w.db.rollback()
    be.approve_be_declaration(w.db, w.org, first.id, w.b)
    second = _declaration(w, start="2026-07-01")
    be.approve_be_declaration(w.db, w.org, second.id, w.b)
    assert first.status == "SUPERSEDED" and first.superseded_by_id == second.id
    assert first.effective_to == date(2026, 6, 30)
    with pytest.raises(BadRequestException, match="before"):
        be.withdraw_be_declaration(w.db, w.org, second.id, w.a, "left", "2026-01-01")
    assert be.withdraw_be_declaration(w.db, w.org, second.id, w.a, "left", "2026-09-30").status == "WITHDRAWN"


def test_declarations_need_evidence_and_known_types(world):
    be, w = _svc(), world
    base = {"declaration_type": "FAMILY_SITUATION", "received_at": "2025-12-20T10:00:00",
            "effective_from": "2026-01-01", "source_channel": "PAPER", "evidence_ref": "scan"}
    for bad, message in (({"evidence_ref": None}, "evidence_ref"), ({"declaration_type": "X"}, "declaration_type"),
                         ({"source_channel": "PIGEON"}, "source_channel"), ({"value": ["x"]}, "object")):
        with pytest.raises(BadRequestException, match=message):
            be.record_be_declaration(w.db, w.org, w.employee.id, {**base, **bad}, w.a)


# ── identifier vault ────────────────────────────────────────────────────────
def test_vault_stores_ciphertext_only_and_masks_everywhere(world, caplog):
    from app.modules.payroll.models import PayrollBeIdentifierAccessEvent, PayrollBeIdentifierVault, TaxConfigurationAudit

    be, w = _svc(), world
    caplog.set_level(logging.DEBUG)
    row = be.create_be_identifier(w.db, w.org, "niss", "123.123.123-12", w.a, employee_id=w.employee.id)
    profile = _profile(w, niss_vault_id=row.id)
    w.db.commit()
    stored = w.db.get(PayrollBeIdentifierVault, row.id)
    assert NISS not in (stored.ciphertext or "") and NISS not in stored.fingerprint
    view = be.identifier_view(stored)
    assert view["onFile"] and not any(ch.isdigit() for ch in view["masked"])
    responses = [be.list_be_identifiers(w.db, w.org, w.employee.id), be.employee_summary(w.db, w.org, w.employee.id),
                 be._json_safe(be._facts(profile))]
    for response in responses:
        assert NISS not in json.dumps(response, default=str)
    audits = w.db.query(TaxConfigurationAudit).all()
    assert audits and all(NISS not in json.dumps([a.old_value, a.new_value, a.reason], default=str) for a in audits)
    events = w.db.query(PayrollBeIdentifierAccessEvent).filter_by(vault_id=row.id).all()
    assert [e.action for e in events] == ["CREATE"]
    with pytest.raises(BadRequestException, match="already"):
        be.create_be_identifier(w.db, w.org, "NISS", NISS, w.a, employee_id=w.employee.id)
    with pytest.raises(BadRequestException) as raised:
        be.create_be_identifier(w.db, w.org, "NISS", "1231231231", w.a, employee_id=w.employee.id)
    assert "1231231231" not in str(raised.value.detail)
    assert NISS not in caplog.text and "1231231231" not in caplog.text


def test_reveal_is_requested_approved_by_another_person_and_single_use(world, caplog):
    be, w = _svc(), world
    caplog.set_level(logging.DEBUG)
    row = be.create_be_identifier(w.db, w.org, "BIS", NISS, w.a, employee_id=w.employee.id)
    with pytest.raises(BadRequestException, match="request"):
        be.reveal_be_identifier(w.db, w.org, row.id, w.a)
    with pytest.raises(BadRequestException, match="reason"):
        be.request_be_identifier_reveal(w.db, w.org, row.id, "", w.a)
    be.request_be_identifier_reveal(w.db, w.org, row.id, "Dimona check", w.a)
    w.db.commit()
    with pytest.raises(Exception):
        be.approve_be_identifier_reveal(w.db, w.org, row.id, w.a)                    # four-eyes
    w.db.rollback()
    be.approve_be_identifier_reveal(w.db, w.org, row.id, w.b)
    with pytest.raises(BadRequestException, match="already been approved"):
        be.approve_be_identifier_reveal(w.db, w.org, row.id, w.b)
    with pytest.raises(BadRequestException, match="requested"):
        be.reveal_be_identifier(w.db, w.org, row.id, w.b)                            # only the requester
    assert be.reveal_be_identifier(w.db, w.org, row.id, w.a)["value"] == NISS
    with pytest.raises(BadRequestException, match="already been used"):
        be.reveal_be_identifier(w.db, w.org, row.id, w.a)
    assert NISS not in caplog.text
    deleted = be.delete_be_identifier(w.db, w.org, row.id, w.a, "left the company")
    assert deleted.ciphertext is None and be.identifier_view(deleted)["masked"] is None
    with pytest.raises(BadRequestException, match="deleted"):
        be.request_be_identifier_reveal(w.db, w.org, row.id, "again", w.a)
    again = be.create_be_identifier(w.db, w.org, "BIS", NISS, w.a, employee_id=w.employee.id)
    assert again.id != row.id                                                       # re-collectable after delete


def test_employer_onss_number_links_only_to_a_draft_registration(world):
    be, w = _svc(), world
    active = _registration(w)
    with pytest.raises(BadRequestException, match="DRAFT"):
        be.set_be_employer_onss(w.db, w.org, active.id, ONSS, w.a)
    draft = _registration(w, approve=False, effective_from="2026-07-01")
    vault = be.set_be_employer_onss(w.db, w.org, draft.id, ONSS, w.a)
    assert draft.onss_number_vault_id == vault.id and vault.identifier_type == "ONSS" and vault.employee_id is None
    assert ONSS not in json.dumps(be.identifier_view(vault)) and ONSS not in json.dumps(
        be._json_safe(be._facts(draft)))


def test_vault_refuses_without_keys_and_unknown_types(world, monkeypatch):
    from app.config import settings

    be, w = _svc(), world
    with pytest.raises(BadRequestException, match="NISS, BIS or ONSS"):
        be.create_be_identifier(w.db, w.org, "PESEL", NISS, w.a, employee_id=w.employee.id)
    monkeypatch.setattr(settings, "BE_IDENTIFIER_FINGERPRINT_KEY", "")
    with pytest.raises(BadRequestException, match="FINGERPRINT_KEY"):
        be.create_be_identifier(w.db, w.org, "NISS", NISS, w.a, employee_id=w.employee.id)
    monkeypatch.setattr(settings, "BE_IDENTIFIER_FINGERPRINT_KEY", "f" * 32)
    monkeypatch.setattr(settings, "BE_IDENTIFIER_KEYRING", "")
    with pytest.raises(BadRequestException, match="KEYRING"):
        be.create_be_identifier(w.db, w.org, "NISS", NISS, w.a, employee_id=w.employee.id)


# ── organisation router: dormant, Belgium only, masked ─────────────────────
def test_router_is_dormant_and_belgium_only(world, monkeypatch):
    from app.config import settings
    from app.modules.payroll.be_org_router import require_be_tenant
    from tests._mx_employer_helpers import make_org, principal

    w = world
    monkeypatch.setattr(settings, "BE_TENANT_ONBOARDING_ENABLED", False)
    monkeypatch.setattr(settings, "BE_CANARY_ORG_IDS", "")
    with pytest.raises(NotFoundException, match="not open"):
        require_be_tenant(principal(w.org), w.db)
    monkeypatch.setattr(settings, "BE_CANARY_ORG_IDS", str(w.org))
    assert require_be_tenant(principal(w.org), w.db) is None
    monkeypatch.setattr(settings, "BE_CANARY_ORG_IDS", "")
    monkeypatch.setattr(settings, "BE_TENANT_ONBOARDING_ENABLED", True)
    assert require_be_tenant(principal(w.org), w.db) is None
    other = make_org(w.db, name="Other", code="BEOTHER", country="NL")
    with pytest.raises(NotFoundException, match="only available"):
        require_be_tenant(principal(other.org.id), w.db)


def test_router_is_mounted_and_every_route_is_guarded():
    from app.modules.payroll.be_org_router import require_be_tenant, router
    from app.modules.payroll.router import payroll_router

    paths = {(sorted(r.methods)[0], r.path) for r in router.routes}
    assert ("POST", "/belgium/identifiers/{vault_id}/reveal") in paths
    assert all(p.startswith("/belgium/") for _m, p in paths)
    assert any(d.dependency is require_be_tenant for d in router.dependencies)
    mounted = {getattr(r, "path", "") for r in payroll_router.routes}
    assert any(p.endswith("/belgium/employer-registrations") for p in mounted)
    assert not any("{organization_id}" in p or "org_id" in p for _m, p in paths)


# ── Block A4 support routes: picker + choice lists (read-only, no personal data)
def test_options_come_from_the_catalogue(world):
    from app.modules.payroll.be_org_router import be_org_options
    from app.modules.payroll.engine.countries import belgium_content as content
    from tests._mx_employer_helpers import principal

    out = be_org_options(principal(world.org))
    assert out["workerCategories"] == list(content.WORKER_CATEGORIES)
    assert out["scheduleRegimes"] == list(content.SCHEDULE_REGIMES)
    assert out["declarationTypes"] == list(content.DECLARATION_TYPES)
    assert out["employeeIdentifierTypes"] == ["NISS", "BIS"]


def test_joint_committee_picker_lists_platform_definitions_only(world):
    from app.modules.payroll.be_org_router import be_list_joint_committees
    from app.modules.payroll.models import CollectiveAgreement
    from tests._mx_employer_helpers import principal

    w = world
    w.db.add_all([CollectiveAgreement(organization_id=None, jurisdiction_country="BE", agreement_code="BE-PC-200-1.0",
                                      name="TEST ONLY committee", agreement_type="SECTOR", status="Active"),
                  CollectiveAgreement(organization_id=w.org, jurisdiction_country="BE",
                                      agreement_code="BE-PC-124-1.0", name="TEST ONLY org copy",
                                      agreement_type="SECTOR", status="Active")])
    w.db.commit()
    rows = be_list_joint_committees(principal(w.org), w.db)
    assert [(r["agreementCode"], r["jointCommittee"]) for r in rows] == [("BE-PC-200-1.0", "200")]


# ── Block B decisions recorded through the four-eyes records ───────────────
def test_decision_fields_are_validated_on_their_records(world):
    be, w = _svc(), world
    with pytest.raises(BadRequestException, match="special_160_evidence_ref"):                      # G-25
        _registration(w, approve=False, onss_special_160_status="APPLIES")
    with pytest.raises(BadRequestException, match="onss_special_160_status"):
        _registration(w, approve=False, onss_special_160_status="MAYBE")
    reg = _registration(w, approve=False, onss_special_160_status="applies",
                        special_160_evidence_ref="TEST ONLY workforce count")
    assert reg.onss_special_160_status == "APPLIES"
    default = _registration(w, approve=False, effective_from="2026-02-01", legal_entity_id=None)
    assert default.onss_special_160_status == "UNKNOWN"
    with pytest.raises(BadRequestException, match="pay_basis"):                                     # G-22
        be.record_be_worker_profile(w.db, w.org, w.employee.id, {"effective_from": "2026-01-01",
                                                                 "worker_category": "EMPLOYEE", "pay_basis": "DAILY"},
                                    w.a, "x")
    assert _profile(w, pay_basis="hourly").pay_basis == "HOURLY"
    base = {"effective_from": "2026-01-01", "employment_line": "MAIN"}
    with pytest.raises(BadRequestException, match="contract_type"):                                 # G-23
        be.record_be_employment_classification(w.db, w.org, w.employee.id, {**base, "contract_type": "PERMANENT"},
                                               w.a, "x")
    with pytest.raises(BadRequestException, match="contract_end_date"):
        be.record_be_employment_classification(w.db, w.org, w.employee.id, {
            **base, "contract_type": "FIXED_TERM", "contract_start_date": "2026-06-01",
            "contract_end_date": "2026-01-01"}, w.a, "x")
    row = be.record_be_employment_classification(w.db, w.org, w.employee.id, {
        **base, "contract_type": "fixed_term", "contract_start_date": "2026-01-01", "contract_end_date": "2026-12-31"},
        w.a, "x")
    assert (row.contract_type, row.contract_end_date) == ("FIXED_TERM", date(2026, 12, 31))


def test_component_mappings_are_versioned_with_four_eyes(world):
    be, w = _svc(), world
    payload = {"platform_component_source": "policy_allowance", "platform_component_key": "transport",
               "be_component": "reimbursement", "effective_from": "2026-01-01"}
    row = be.record_be_component_mapping(w.db, w.org, payload, w.a, "map transport")
    w.db.commit()
    assert (row.platform_component_source, row.be_component, row.status) == ("POLICY_ALLOWANCE", "REIMBURSEMENT",
                                                                              "DRAFT")
    assert be.be_component_mapping_index(w.db, w.org, date(2026, 3, 31)) == {}                     # DRAFT never counts
    with pytest.raises(Exception, match="(?i)four|approv|same"):
        be.approve_be_component_mapping(w.db, w.org, row.id, w.a)
    w.db.rollback()
    be.approve_be_component_mapping(w.db, w.org, row.id, w.b)
    assert be.be_component_mapping_index(w.db, w.org, date(2026, 3, 31)) == {
        "POLICY_ALLOWANCE:transport": "REIMBURSEMENT"}
    newer = be.record_be_component_mapping(w.db, w.org, {**payload, "be_component": "BONUS",
                                                         "effective_from": "2026-06-01"}, w.a, "remap")
    w.db.commit()
    be.approve_be_component_mapping(w.db, w.org, newer.id, w.b)
    assert row.status == "SUPERSEDED" and row.effective_to == date(2026, 5, 31)
    assert be.be_component_mapping_index(w.db, w.org, date(2026, 3, 31))["POLICY_ALLOWANCE:transport"] == "REIMBURSEMENT"
    assert be.be_component_mapping_index(w.db, w.org, date(2026, 7, 1))["POLICY_ALLOWANCE:transport"] == "BONUS"
    for bad, message in (({"be_component": "TIPS"}, "be_component"),
                         ({"platform_component_source": "SPREADSHEET"}, "platform_component_source"),
                         ({"platform_component_source": "PLATFORM_FIELD", "platform_component_key": "bonus"},
                          "platform_component_key"),
                         ({"platform_component_key": "Has Spaces"}, "platform_component_key")):
        with pytest.raises(BadRequestException, match=message):
            be.record_be_component_mapping(w.db, w.org, {**payload, **bad}, w.a, "x")
    with pytest.raises(NotFoundException):
        be.approve_be_component_mapping(w.db, w.org + 999, newer.id, w.b)
