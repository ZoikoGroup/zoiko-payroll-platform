"""Belgium (ZP-BE-ENG-001) Block A2: the applicability resolver (spec §2).

One test per §2 blocking row, plus manual vs white-collar, several
establishment units, a mid-period classification change and the read-only
resolve endpoint. The pack is SYNTHETIC TEST ONLY content (made-up codes such as
"X1" / "W1"); no statutory value appears anywhere."""
import json
from datetime import date
from types import SimpleNamespace

import pytest

PAY = date(2026, 3, 31)
TEST = "TEST ONLY"

SCOPE = {
    "be_onss_supported_employer_categories": "X1",
    "be_onss_supported_worker_codes": "W1,W2",
    "be_supported_worker_categories": "MANUAL,EMPLOYEE",
    "be_supported_contract_types": "INDEFINITE,FIXED_TERM",
    "be_supported_pay_frequencies": "MONTHLY",
    "be_supported_pay_bases": "SALARIED",
    "be_onss_manual_base_categories": "MANUAL",
}


def _row(key, text, label=TEST, start="2026-01-01", end=None):
    return {"component_key": key, "label": label, "text_value": text, "effective_from": start, "effective_to": end}


def _pack(on=PAY, **over):
    from app.modules.payroll.engine.jurisdictions.belgium.pack import BePack

    rows = {key: _row(key, value) for key, value in SCOPE.items()}
    for key, value in over.items():
        if value is None:
            rows.pop(key, None)
        else:
            rows[key] = value if isinstance(value, dict) else _row(key, value)
    return BePack(rows, [], 1, on)


def _registration(**over):
    row = {"id": 1, "legal_entity_id": None, "status": "ACTIVE", "verification_state": "VERIFIED",
           "employer_category_code": "X1", "onss_special_160_status": "NOT_APPLICABLE",
           "effective_from": "2026-01-01", "effective_to": None,
           "evidence_ref": "kbo-extract"}
    row.update(over)
    return row


def _profile(**over):
    row = {"id": 2, "status": "ACTIVE", "worker_category": "EMPLOYEE", "onss_worker_code": "W1",
           "residency": "RESIDENT", "special_status": None, "pay_basis": "SALARIED", "effective_from": "2026-01-01",
           "effective_to": None}
    row.update(over)
    return row


def _classification(line="MAIN", **over):
    row = {"id": 3, "employment_line": line, "status": "ACTIVE", "joint_committee": "200", "sub_committee": None,
           "collective_agreement_id": 30, "function_class": "B", "seniority_months": 24,
           "establishment_unit_id": None, "work_schedule_id": None, "effective_from": "2026-01-01",
           "effective_to": None, "contract_type": "INDEFINITE", "contract_start_date": "2026-01-01",
           "contract_end_date": None}
    row.update(over)
    return row


def _agreement(**over):
    row = {"id": 30, "agreement_code": "BE-PC-200-1.0", "jurisdiction_country": "BE", "status": "Active",
           "effective_from": "2026-01-01", "effective_to": None}
    row.update(over)
    return row


def _schedule(**over):
    row = {"id": 40, "status": "ACTIVE", "regime": "EFFECTIVE", "weekly_hours": "38", "effective_from": "2026-01-01",
           "effective_to": None}
    row.update(over)
    return row


def _resolve(pack=None, **over):
    from app.modules.payroll.engine.jurisdictions.belgium import applicability

    kwargs = dict(registration=_registration(), profile=_profile(), classifications=[_classification()],
                  schedules=[_schedule()], units={}, agreements={30: _agreement()}, declarations=[],
                  pay_frequency="Monthly")
    kwargs.update(over)
    return applicability.resolve(pack if pack is not None else _pack(), PAY, **kwargs)


def _codes(result):
    return [b["code"] for b in result["blocking"]]


def test_a_complete_evidenced_setup_resolves():
    result = _resolve()
    assert result["decision"] == "RESOLVED" and result["blocking"] == [] and result["exceptions"] == []
    assert result["confidence"] == "EVIDENCED"
    assert result["employer"]["employerCategory"] == "X1"
    worker = result["worker"]
    assert (worker["workerCategory"], worker["workerCode"], worker["contractType"], worker["payFrequency"],
            worker["payBasis"]) == ("EMPLOYEE", "W1", "INDEFINITE", "MONTHLY", "SALARIED")
    assert result["employer"]["special160Status"] == "NOT_APPLICABLE"
    (line,) = result["employmentLines"]
    assert line["jointCommittee"] == "200" and line["agreement"]["agreementCode"] == "BE-PC-200-1.0"
    assert line["schedule"]["id"] == 40
    assert {u["id"] for u in result["usedRows"]} >= set(SCOPE)
    json.dumps(result)                                   # serialisable as-is


# ── §2 row: ONSS employer category ──────────────────────────────────────────
@pytest.mark.parametrize("registration, code", [
    (None, "BE_REGISTRATION_MISSING"),
    (_registration(status="DRAFT"), "BE_REGISTRATION_NOT_ACTIVE"),
    (_registration(effective_to="2026-02-28"), "BE_REGISTRATION_NOT_ACTIVE"),
    (_registration(verification_state="UNVERIFIED"), "BE_REGISTRATION_UNVERIFIED"),
    (_registration(employer_category_code="Z9"), "BE_EMPLOYER_CATEGORY_UNSUPPORTED:Z9"),
    (_registration(employer_category_code=None), "BE_FACT_MISSING:employer_category"),
])
def test_unknown_or_expired_employer_category_blocks(registration, code):
    result = _resolve(registration=registration)
    assert result["decision"] == "BLOCKED" and code in _codes(result)


# ── §2 row: manual vs white-collar / worker category and code ──────────────
@pytest.mark.parametrize("profile, code", [
    (None, "BE_PROFILE_MISSING"),
    (_profile(status="DRAFT"), "BE_PROFILE_NOT_ACTIVE"),
    (_profile(worker_category="STUDENT"), "BE_WORKER_CATEGORY_UNSUPPORTED:STUDENT"),
    (_profile(onss_worker_code="W9"), "BE_WORKER_CODE_UNSUPPORTED:W9"),
    (_profile(onss_worker_code=None), "BE_FACT_MISSING:worker_code"),
    (_profile(residency=None), "BE_FACT_MISSING:residency"),
    (_profile(residency="NON_RESIDENT"), "BE_NON_RESIDENT_UNSUPPORTED"),                      # G-27
])
def test_worker_category_and_code_must_be_signed_and_evidenced(profile, code):
    assert code in _codes(_resolve(profile=profile))


def test_manual_worker_is_on_the_manual_base_and_white_collar_is_not():
    manual = _resolve(profile=_profile(worker_category="MANUAL"))
    white = _resolve(profile=_profile(worker_category="EMPLOYEE"))
    assert manual["decision"] == white["decision"] == "RESOLVED"
    assert manual["worker"]["onssManualBase"] is True and white["worker"]["onssManualBase"] is False


# ── §2 row: special status ─────────────────────────────────────────────────
@pytest.mark.parametrize("status", ["STUDENT", "FLEXI", "OCCASIONAL"])
def test_a_special_status_never_uses_ordinary_rules(status):
    result = _resolve(profile=_profile(special_status=status))
    assert f"BE_SPECIAL_STATUS_UNSUPPORTED:{status}" in _codes(result)


# ── contract (G-23, on the line) / pay frequency / pay basis (G-22, on the profile)
@pytest.mark.parametrize("over, code", [
    ({"classifications": [_classification(contract_type="STUDENT")]}, "BE_CONTRACT_UNSUPPORTED:STUDENT"),
    ({"classifications": [_classification(contract_type=None)]}, "BE_FACT_MISSING:contract_type"),
    ({"pay_frequency": "FourWeekly"}, "BE_FREQUENCY_UNSUPPORTED:FOURWEEKLY"),
    ({"pay_frequency": "Weekly"}, "BE_FREQUENCY_UNSUPPORTED:WEEKLY"),
    ({"profile": _profile(pay_basis="HOURLY")}, "BE_PAY_BASIS_UNSUPPORTED:HOURLY"),
    ({"profile": _profile(pay_basis=None)}, "BE_FACT_MISSING:pay_basis"),
    ({"registration": _registration(onss_special_160_status="UNKNOWN")}, "BE_SPECIAL_160_UNKNOWN"),     # G-25
])
def test_unsupported_contract_frequency_basis_or_unknown_special_status_blocks(over, code):
    assert code in _codes(_resolve(**over))


def test_the_contract_and_its_dates_travel_on_the_line():
    (line,) = _resolve(classifications=[_classification(contract_type="FIXED_TERM",
                                                        contract_end_date="2026-12-31")])["employmentLines"]
    assert (line["contractType"], line["contractStart"], line["contractEnd"]) == \
        ("FIXED_TERM", "2026-01-01", "2026-12-31")


# ── §2 row: Joint Committee / sub-committee ─────────────────────────────────
def test_missing_classification_blocks():
    assert "BE_CLASSIFICATION_MISSING" in _codes(_resolve(classifications=[]))
    assert "BE_CLASSIFICATION_MISSING" in _codes(_resolve(classifications=[_classification(status="DRAFT")]))


def test_missing_joint_committee_blocks():
    result = _resolve(classifications=[_classification(joint_committee=None, collective_agreement_id=None)])
    assert "BE_JOINT_COMMITTEE_MISSING:MAIN" in _codes(result)


@pytest.mark.parametrize("agreement", [
    _agreement(status="Draft"), _agreement(effective_to="2026-02-28"), _agreement(agreement_code="BE-PC-124-1.0"),
    _agreement(jurisdiction_country="NL"), _agreement(agreement_code="SE-SECTOR-TEKNIK-2026"),
])
def test_a_non_active_or_wrong_committee_agreement_blocks(agreement):
    assert "BE_AGREEMENT_INVALID:MAIN" in _codes(_resolve(agreements={30: agreement}))


def test_a_sub_committee_agreement_must_match_the_classification():
    sub = _agreement(agreement_code="BE-PC-200-A1-1.0")
    assert _resolve(agreements={30: sub}, classifications=[_classification(sub_committee="A1")])["decision"] \
        == "RESOLVED"
    assert "BE_AGREEMENT_INVALID:MAIN" in _codes(_resolve(agreements={30: sub}))


def test_a_linked_agreement_that_does_not_exist_blocks():
    assert "BE_AGREEMENT_INVALID:MAIN" in _codes(_resolve(agreements={}))


# ── §2 row: function / class / seniority (exceptions, not blocks) ──────────
def test_missing_scale_inputs_raise_exceptions_without_blocking():
    result = _resolve(classifications=[_classification(function_class=None, collective_agreement_id=None)])
    assert result["decision"] == "RESOLVED" and result["confidence"] == "EVIDENCED_WITH_EXCEPTIONS"
    assert {e["code"] for e in result["exceptions"]} == {"BE_SCALE_INPUT_MISSING:MAIN",
                                                         "BE_SECTOR_AGREEMENT_MISSING:MAIN"}


# ── §2 row: employment line / schedule ──────────────────────────────────────
def test_schedule_missing_or_ambiguous_blocks_and_a_linked_one_is_used():
    assert "BE_SCHEDULE_MISSING:MAIN" in _codes(_resolve(schedules=[]))
    assert "BE_SCHEDULE_MISSING:MAIN" in _codes(_resolve(schedules=[_schedule(status="DRAFT")]))
    two = [_schedule(), _schedule(id=41, weekly_hours="10")]
    assert "BE_SCHEDULE_AMBIGUOUS:MAIN" in _codes(_resolve(schedules=two))
    linked = _resolve(schedules=two, classifications=[_classification(work_schedule_id=41)])
    assert linked["decision"] == "RESOLVED" and linked["employmentLines"][0]["schedule"]["weeklyHours"] == "10"
    assert "BE_SCHEDULE_MISSING:MAIN" in _codes(_resolve(classifications=[_classification(work_schedule_id=99)]))


def test_several_establishment_units_and_the_one_line_scope():
    """Units of the registration are resolved per line; release 1 calculates
    exactly one employment line per employee per pay period (G-27), so two
    lines on two units block while each line on its own unit resolves."""
    units = {50: {"id": 50, "registration_id": 1, "unit_number": "2000", "status": "ACTIVE",
                  "effective_from": "2026-01-01", "effective_to": None},
             51: {"id": 51, "registration_id": 1, "unit_number": "2001", "status": "ACTIVE",
                  "effective_from": "2026-01-01", "effective_to": None}}
    lines = [_classification("MAIN", establishment_unit_id=50, work_schedule_id=40),
             _classification("SECOND", id=4, establishment_unit_id=51, work_schedule_id=41)]
    two = _resolve(classifications=lines, units=units, schedules=[_schedule(), _schedule(id=41)])
    assert "BE_MULTI_LINE_UNSUPPORTED" in _codes(two)
    assert [(l["employmentLine"], l["unit"]["unitNumber"]) for l in two["employmentLines"]] == \
        [("MAIN", "2000"), ("SECOND", "2001")]                                 # each line keeps its own unit
    for line, unit in ((lines[0], "2000"), (lines[1], "2001")):
        one = _resolve(classifications=[line], units=units, schedules=[_schedule(), _schedule(id=41)])
        assert one["decision"] == "RESOLVED" and one["employmentLines"][0]["unit"]["unitNumber"] == unit
    foreign = dict(units[51], registration_id=99)
    assert "BE_UNIT_INVALID:SECOND" in _codes(_resolve(classifications=lines[1:], units={51: foreign},
                                                       schedules=[_schedule(id=41)]))
    assert "BE_UNIT_INVALID:MAIN" in _codes(_resolve(classifications=lines[:1], units={},
                                                     schedules=[_schedule()]))


def test_a_mid_period_classification_change():
    from app.modules.payroll.engine.jurisdictions.belgium import applicability

    old = _classification(status="SUPERSEDED", effective_to="2026-03-14", joint_committee="124",
                          collective_agreement_id=None)
    new = _classification(id=5, effective_from="2026-03-15")
    common = dict(registration=_registration(), profile=_profile(), schedules=[_schedule()],
                  agreements={30: _agreement()}, pay_frequency="Monthly")
    early = applicability.resolve(_pack(on=date(2026, 3, 10)), date(2026, 3, 10), classifications=[old, new],
                                  **common)
    assert early["employmentLines"][0]["jointCommittee"] == "124"           # the pay date picks the version
    late = applicability.resolve(_pack(), PAY, classifications=[old, new], **common)
    assert late["employmentLines"][0]["jointCommittee"] == "200" and late["decision"] == "RESOLVED"
    split = applicability.resolve(_pack(), PAY, classifications=[old, new], period_start=date(2026, 3, 1), **common)
    assert "BE_MID_PERIOD_CLASSIFICATION_CHANGE:MAIN" in _codes(split)
    whole = applicability.resolve(_pack(), PAY, classifications=[old, new], period_start=date(2026, 3, 15), **common)
    assert whole["decision"] == "RESOLVED"


# ── §2: any required content pending ────────────────────────────────────────
@pytest.mark.parametrize("key", sorted(SCOPE))
def test_pending_not_supported_or_missing_scope_content_blocks(key):
    pending = _resolve(pack=_pack(**{key: _row(key, SCOPE[key], label="x [PENDING G1]")}))
    assert f"BE_CONTENT_PENDING:{key}" in _codes(pending)
    refused = _resolve(pack=_pack(**{key: "NOT_SUPPORTED"}))
    assert f"BE_FEATURE_BLOCKED:{key}" in _codes(refused)
    missing = _resolve(pack=_pack(**{key: None}))
    assert f"BE_ROW_MISSING:{key}" in _codes(missing)


def test_no_pack_blocks():
    from app.modules.payroll.engine.jurisdictions.belgium import applicability

    result = applicability.resolve(None, PAY)
    assert _codes(result) == ["BE_PACK_MISSING"] and result["decision"] == "BLOCKED"


def test_every_reason_is_collected_and_require_raises_the_first():
    from app.modules.payroll.engine.jurisdictions.belgium import applicability
    from app.modules.payroll.engine.jurisdictions.belgium.errors import BECalculationBlockedError

    result = _resolve(registration=None, profile=_profile(worker_category="STUDENT"), schedules=[])
    assert len(result["blocking"]) >= 3
    with pytest.raises(BECalculationBlockedError) as raised:
        applicability.require(result, 7)
    assert raised.value.key == "BE_REGISTRATION_MISSING" and "more blocking" in raised.value.reason
    assert applicability.require(_resolve())["decision"] == "RESOLVED"


def test_only_approved_declarations_in_force_are_used():
    declarations = [
        {"id": 60, "declaration_type": "FAMILY_SITUATION", "status": "APPROVED", "value": {"note": TEST},
         "effective_from": "2026-01-01", "effective_to": None},
        {"id": 61, "declaration_type": "DEPENDANTS", "status": "RECEIVED", "value": {},
         "effective_from": "2026-01-01", "effective_to": None},
        {"id": 62, "declaration_type": "NON_RESIDENT_STATUS", "status": "APPROVED", "value": {},
         "effective_from": "2026-06-01", "effective_to": None},
    ]
    assert list(_resolve(declarations=declarations)["declarations"]) == ["FAMILY_SITUATION"]


# ── the read-only endpoint ──────────────────────────────────────────────────
@pytest.fixture
def world(db):
    from app.modules.payroll.models import PayrollEmployee
    from tests._mx_employer_helpers import make_org

    t = make_org(db, name="Resolve BV", code="BERESOLVE", admins=2, country="BE")
    employee = PayrollEmployee(organization_id=t.org.id, employee_code="BE1", name="Test Worker", country_code="BE",
                               employment_type="Full-time", pay_frequency="Monthly")
    db.add(employee)
    db.commit()
    return SimpleNamespace(db=db, org=t.org.id, a=t.users[0].id, b=t.users[1].id, employee=employee)


def _setup(w):
    from app.modules.payroll import belgium_service as be

    def two_step(record, approve, *args):
        row = record(*args)
        w.db.commit()
        return approve(w.db, w.org, row.id, w.b)

    reg = two_step(be.record_be_employer_registration, be.approve_be_employer_registration, w.db, w.org,
                   {"effective_from": "2026-01-01", "legal_name": "Resolve BV", "enterprise_number": "0999999999",
                    "employer_category_code": "X1", "onss_special_160_status": "NOT_APPLICABLE",
                    "special_160_evidence_ref": "TEST ONLY workforce count"}, w.a, "setup")
    be.verify_be_employer_registration(w.db, w.org, reg.id, w.b, "VERIFIED", "checked")
    two_step(be.record_be_worker_profile, be.approve_be_worker_profile, w.db, w.org, w.employee.id,
             {"effective_from": "2026-01-01", "worker_category": "EMPLOYEE", "onss_worker_code": "W1",
              "residency": "RESIDENT", "pay_basis": "SALARIED"}, w.a, "hire")
    two_step(be.record_be_work_schedule, be.approve_be_work_schedule, w.db, w.org, w.employee.id,
             {"effective_from": "2026-01-01", "regime": "EFFECTIVE", "weekly_hours": "38"}, w.a, "hire")
    two_step(be.record_be_employment_classification, be.approve_be_employment_classification, w.db, w.org,
             w.employee.id, {"effective_from": "2026-01-01", "employment_line": "MAIN", "joint_committee": "200",
                             "function_class": "B", "seniority_months": 0, "contract_type": "INDEFINITE"}, w.a, "hire")
    w.db.commit()


def test_the_endpoint_reads_the_records_and_writes_nothing(world, monkeypatch):
    from app.modules.payroll import belgium_service as be
    from app.modules.payroll.be_org_router import be_resolve_classification
    from app.modules.payroll.models import TaxConfigurationAudit
    from tests._mx_employer_helpers import principal

    w = world
    _setup(w)
    monkeypatch.setattr(be, "_be_pack_for", lambda db, org, on: _pack(on=on))
    before = w.db.query(TaxConfigurationAudit).count()
    out = be_resolve_classification({"employeeId": w.employee.id, "payDate": "2026-03-31", "payBasis": "HOURLY"},
                                    principal(w.org), w.db)
    assert out["decision"] == "RESOLVED", out["blocking"]
    # the recorded profile and classification are the sources (G-22 / G-23): a payBasis in the body is ignored
    assert out["worker"]["payBasis"] == "SALARIED" and out["worker"]["contractType"] == "INDEFINITE"
    assert out["employeeId"] == w.employee.id
    assert {e["code"] for e in out["exceptions"]} == {"BE_SECTOR_AGREEMENT_MISSING:MAIN"}
    assert w.db.query(TaxConfigurationAudit).count() == before and not w.db.new and not w.db.dirty
    json.dumps(out)


def test_the_endpoint_blocks_without_an_active_pack(world):
    from app.modules.payroll import belgium_service as be

    w = world
    _setup(w)
    assert _codes(be.resolve_be_classification(w.db, w.org, w.employee.id, "2026-03-31")) == ["BE_PACK_MISSING"]


def test_the_endpoint_validates_its_input(world):
    from app.core.exceptions import BadRequestException, NotFoundException
    from app.modules.payroll import belgium_service as be

    w = world
    with pytest.raises(BadRequestException, match="payDate"):
        be.resolve_be_classification(w.db, w.org, w.employee.id, "soon")
    with pytest.raises(BadRequestException, match="periodStart"):
        be.resolve_be_classification(w.db, w.org, w.employee.id, "2026-03-31", period_start="2026-04-01")
    with pytest.raises(NotFoundException):
        be.resolve_be_classification(w.db, w.org + 999, w.employee.id, "2026-03-31")
