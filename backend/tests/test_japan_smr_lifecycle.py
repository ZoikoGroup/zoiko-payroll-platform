"""Synthetic Japan Phase 4 SMR lifecycle tests (ZP-JP-ENG-001 §5/§11, S7).

Every value here is invented for the test: the grade table, the payment base
days and the grade gap are fixtures, not statutory figures.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll.engine.countries import japan
from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError
from app.modules.payroll.engine.jurisdictions.japan import smr_lifecycle as lc
from tests.test_japan_engine import D, _base_rate_map

_BANDS = ((1, 0, 100000, 98000), (2, 100000, 200000, 150000),
          (3, 200000, 300000, 250000), (4, 300000, None, 320000))


def _grades(kind="HEALTH", bands=_BANDS):
    return [SimpleNamespace(rule_type="JP_SMR_GRADE", filing_status=kind, tax_table_number=grade,
                            min_amount=D(low), max_amount=None if high is None else D(high),
                            flat_amount=D(smr), effective_from=None, effective_to=None)
            for grade, low, high, smr in bands]


def _pack(min_days="17", gap="2"):
    rate_map = _base_rate_map()
    rate_map["jp_smr_min_payment_base_days"].flat_amount = None if min_days is None else D(min_days)
    rate_map["jp_smr_adhoc_grade_gap"].flat_amount = None if gap is None else D(gap)
    return japan._Pack(rate_map, 7)


def _pay(*entries):
    return [{"month": month, "amount": D(amount), "base_days": days} for month, amount, days in entries]


def _blocked(fn, *args, **kwargs):
    with pytest.raises(MissingComplianceConfigurationError) as exc:
        fn(*args, **kwargs)
    return exc.value.key


# ── annual determination ───────────────────────────────────────────────────
def test_annual_determination_averages_the_counted_months():
    pay = _pay(("2026-04", 210000, 20), ("2026-05", 230000, 20), ("2026-06", 250000, 10))
    result = lc.annual_determination(pay, 2026, "HEALTH", _grades(), _pack())
    assert result.months_counted == ["2026-04", "2026-05"]       # June is below the base days
    assert result.average == D(220000)
    assert (result.grade, result.smr) == (3, D(250000))
    assert (result.effective_from, result.effective_to) == (date(2026, 9, 1), date(2027, 8, 31))
    assert result.report_month == "2026-07"
    assert result.status == lc.REVIEW_REQUIRED
    assert result.basis == "ANNUAL_DETERMINATION"


def test_health_and_pension_grades_come_from_their_own_tables():
    pay = _pay(("2026-04", 900000, 20), ("2026-05", 900000, 20), ("2026-06", 900000, 20))
    pension = _grades("PENSION", ((1, 0, 500000, 400000), (2, 500000, None, 650000)))
    slabs = _grades() + pension
    assert lc.annual_determination(pay, 2026, "HEALTH", slabs, _pack()).smr == D(320000)
    assert lc.annual_determination(pay, 2026, "PENSION", slabs, _pack()).smr == D(650000)


@pytest.mark.parametrize("pay,pack,slabs,key", [
    (_pay(("2026-04", 1, 20), ("2026-05", 1, 20)), None, None, "jp_smr_pay_history"),
    (_pay(("2026-04", 1, 5), ("2026-05", 1, 5), ("2026-06", 1, 5)), None, None,
     "JP_SMR_INSURER_DETERMINATION"),
    (_pay(("2026-04", 1, 20), ("2026-04", 1, 20), ("2026-06", 1, 20)), None, None, "jp_smr_pay_history"),
    (_pay(("2026-04", 1, 20), ("2026-05", 1, 20), ("2026-06", 1, 20)), "no-days", None,
     "jp_smr_min_payment_base_days"),
    (_pay(("2026-04", 1, 20), ("2026-05", 1, 20), ("2026-06", 1, 20)), None, [], "jp_smr_grades_health"),
    (_pay(("2026-04", 150000, 20), ("2026-05", 150000, 20), ("2026-06", 150000, 20)), None, "overlap",
     "jp_smr_grades_health"),
])
def test_annual_determination_blocks_instead_of_guessing(pay, pack, slabs, key):
    pack = _pack(min_days=None) if pack == "no-days" else _pack()
    if slabs == "overlap":
        slabs = _grades() + _grades(bands=((9, 100000, 200000, 151000),))
    elif slabs is None:
        slabs = _grades()
    assert _blocked(lc.annual_determination, pay, 2026, "HEALTH", slabs, pack) == key


def test_shipped_content_blocks_the_determination():
    # jp_smr_min_payment_base_days ships empty by design.
    pack = japan._Pack(_base_rate_map(), 7)
    pay = _pay(("2026-04", 1, 20), ("2026-05", 1, 20), ("2026-06", 1, 20))
    assert _blocked(lc.annual_determination, pay, 2026, "HEALTH", _grades(), pack) == \
        "jp_smr_min_payment_base_days"


# ── ad hoc revision candidates ─────────────────────────────────────────────
def _adhoc_pay(start_year, start_month, amount, days=(20, 20, 20)):
    out = []
    for offset, day_count in enumerate(days):
        index = start_year * 12 + start_month - 1 + offset
        out.append((f"{index // 12}-{index % 12 + 1:02d}", amount, day_count))
    return _pay(*out)


def test_adhoc_candidate_is_review_required_from_the_fourth_month():
    result = lc.adhoc_revision_candidate(date(2026, 4, 1), "UP", _adhoc_pay(2026, 4, 250000),
                                         1, "HEALTH", _grades(), _pack())
    assert result.status == lc.REVIEW_REQUIRED
    assert (result.grade, result.smr) == (3, D(250000))
    assert result.effective_from == date(2026, 7, 1)
    assert result.months == ["2026-04", "2026-05", "2026-06"]


def test_adhoc_candidate_across_the_year_end():
    result = lc.adhoc_revision_candidate(date(2026, 11, 1), "UP", _adhoc_pay(2026, 11, 250000),
                                         1, "HEALTH", _grades(), _pack())
    assert result.effective_from == date(2027, 2, 1)
    assert result.months == ["2026-11", "2026-12", "2027-01"]


@pytest.mark.parametrize("direction,current,amount,status", [
    ("UP", 2, 250000, lc.NO_REVISION),          # one grade only; the gap is 2
    ("DOWN", 1, 250000, lc.NO_REVISION),        # pay fell but the grade rose
    ("DOWN", 4, 150000, lc.REVIEW_REQUIRED),
])
def test_adhoc_candidate_needs_the_gap_in_the_same_direction(direction, current, amount, status):
    result = lc.adhoc_revision_candidate(date(2026, 4, 1), direction, _adhoc_pay(2026, 4, amount),
                                         current, "HEALTH", _grades(), _pack())
    assert result.status == status


def test_adhoc_candidate_needs_every_month_to_reach_the_base_days():
    result = lc.adhoc_revision_candidate(date(2026, 4, 1), "UP",
                                         _adhoc_pay(2026, 4, 250000, days=(20, 16, 20)),
                                         1, "HEALTH", _grades(), _pack())
    assert result.status == lc.NOT_ELIGIBLE
    assert "2026-05" in result.reason


@pytest.mark.parametrize("args,pack,key", [
    ((None, "UP", 1), None, "jp_smr_change_month"),
    ((date(2026, 4, 1), "SIDEWAYS", 1), None, "jp_smr_change_direction"),
    ((date(2026, 4, 1), "UP", None), None, "jp_smr_current_grade"),
    ((date(2026, 4, 1), "UP", 1), "no-gap", "jp_smr_adhoc_grade_gap"),
])
def test_adhoc_candidate_blocks_on_missing_facts(args, pack, key):
    change, direction, current = args
    pack = _pack(gap=None) if pack == "no-gap" else _pack()
    assert _blocked(lc.adhoc_revision_candidate, change, direction, _adhoc_pay(2026, 4, 250000),
                    current, "HEALTH", _grades(), pack) == key


# ── care state and exemptions ──────────────────────────────────────────────
@pytest.mark.parametrize("born,state", [
    (date(1987, 6, 2), "NOT_COVERED"),          # 38 on 2026-06-01
    (date(1986, 6, 1), "COVERED"),              # 40
    (date(1961, 6, 2), "COVERED"),              # 64
    (date(1961, 6, 1), "NOT_COVERED"),          # 65
])
def test_care_state_follows_the_content_age_band(born, state):
    assert lc.care_state_on(born, date(2026, 6, 1), _pack()) == state


def test_care_state_needs_a_date_of_birth():
    assert _blocked(lc.care_state_on, None, date(2026, 6, 1), _pack()) == "jp_date_of_birth"


def test_exemption_events_in_month():
    events = [
        SimpleNamespace(event_type="MATERNITY_EXEMPTION", submission_status="CREATED",
                        effective_from=date(2026, 6, 30), effective_to=None),
        SimpleNamespace(event_type="CHILDCARE_EXEMPTION", submission_status="REJECTED",
                        effective_from=date(2026, 6, 1), effective_to=None),
        SimpleNamespace(event_type="CHILDCARE_EXEMPTION", submission_status="APPROVED",
                        effective_from=date(2026, 7, 1), effective_to=None),
        SimpleNamespace(event_type="BONUS", submission_status="APPROVED",
                        effective_from=date(2026, 6, 1), effective_to=None),
    ]
    assert lc.exemption_events_in_month(events, date(2026, 6, 15)) == ["MATERNITY_EXEMPTION"]
    assert lc.exemption_events_in_month([], date(2026, 6, 15)) == []


# ── persistence: record / four-eyes approve / apply ────────────────────────
@pytest.fixture()
def enrollment(db, organization):
    from app.modules.payroll.models import PayrollJpSocialInsuranceEnrollment

    row = PayrollJpSocialInsuranceEnrollment(
        organization_id=organization.id, employee_id=501, effective_from=date(2026, 1, 1),
        health_eligible=True, pension_eligible=True, smr_health_grade=20, smr_pension_grade=20,
        smr_health_amount=D(300000), smr_pension_amount=D(300000), smr_basis="QUALIFICATION",
        care_state="NOT_COVERED", child_support_state="EXEMPT", status="ACTIVE", created_by_id=1)
    db.add(row)
    db.commit()
    return row


def _revision(db, organization, **kw):
    from app.modules.payroll import japan_lifecycle as jl

    event = jl.record_event(
        db, organization_id=organization.id, employee_id=501, event_type=kw.get("event_type",
                                                                              "ANNUAL_DETERMINATION"),
        effective_from=kw.get("effective_from", date(2026, 9, 1)), actor_id=1,
        payload=kw.get("payload", {"smr_health_grade": 22, "smr_health_amount": "340000",
                                   "smr_pension_grade": 22, "smr_pension_amount": "340000"}))
    db.commit()
    return event


def test_revision_is_approved_by_a_second_person_and_applied_as_a_new_version(db, organization,
                                                                              enrollment):
    from app.modules.payroll import japan_lifecycle as jl

    event = _revision(db, organization)
    with pytest.raises(BadRequestException, match="four-eyes"):
        jl.approve_event(db, organization_id=organization.id, event_id=event.id, actor_id=1)
    jl.approve_event(db, organization_id=organization.id, event_id=event.id, actor_id=2)
    assert event.submission_status == "APPROVED" and event.approved_by_id == 2

    new = jl.apply_approved_event(db, organization_id=organization.id, event_id=event.id, actor_id=2)
    db.commit()
    assert (new.smr_health_amount, new.smr_pension_grade) == (D(340000), 22)
    assert new.effective_from == date(2026, 9, 1) and new.previous_version_id == enrollment.id
    assert new.smr_basis == "ANNUAL_DETERMINATION" and new.status == "ACTIVE"
    assert new.care_state == "NOT_COVERED" and new.health_eligible is True
    db.refresh(enrollment)
    # The earlier version keeps its own months and SMR; it is only end-dated.
    assert enrollment.effective_to == date(2026, 8, 31) and enrollment.smr_health_amount == D(300000)
    assert event.enrollment_id == new.id

    with pytest.raises(BadRequestException, match="already been applied"):
        jl.apply_approved_event(db, organization_id=organization.id, event_id=event.id, actor_id=2)


def test_unapproved_revision_is_never_applied(db, organization, enrollment):
    from app.modules.payroll import japan_lifecycle as jl

    event = _revision(db, organization)
    with pytest.raises(BadRequestException, match="APPROVED"):
        jl.apply_approved_event(db, organization_id=organization.id, event_id=event.id, actor_id=2)


def test_revision_needs_exactly_one_enrollment_in_force(db, organization):
    from app.modules.payroll import japan_lifecycle as jl

    event = _revision(db, organization)
    jl.approve_event(db, organization_id=organization.id, event_id=event.id, actor_id=2)
    with pytest.raises(BadRequestException, match="0 ACTIVE enrolments"):
        jl.apply_approved_event(db, organization_id=organization.id, event_id=event.id, actor_id=2)


@pytest.mark.parametrize("kw,match", [
    ({"payload": {"smr_health_grade": 22}}, "both smr_health_grade"),
    ({"payload": {}}, "health or pension grade"),
    ({"event_type": "BONUS"}, "calculated bonus"),
    ({"event_type": "PROMOTION"}, "event_type must be"),
    ({"event_type": "CHILDCARE_EXEMPTION", "payload": None}, "evidence reference"),
])
def test_record_event_validates(db, organization, kw, match):
    with pytest.raises(BadRequestException, match=match):
        _revision(db, organization, **kw)


def test_events_of_another_organization_are_not_found(db, organization, enrollment):
    from app.core.exceptions import NotFoundException
    from app.modules.payroll import japan_lifecycle as jl

    event = _revision(db, organization)
    with pytest.raises(NotFoundException):
        jl.approve_event(db, organization_id=organization.id + 1, event_id=event.id, actor_id=2)


def test_bonus_obligation_is_recorded_once_from_the_calculation(db, organization):
    from app.modules.payroll import japan_lifecycle as jl
    from tests.test_japan_bonus import _ctx

    jp_result = japan.calculate(_ctx())["jp_result"]
    first = jl.record_bonus_obligation(db, organization_id=organization.id, employee_id=501,
                                       jp_result=jp_result, paid_on=date(2026, 6, 15), actor_id=1)
    assert (first.sba_amount, first.report_due_on) == (D(500000), date(2026, 6, 20))
    assert first.event_type == "BONUS" and first.submission_status == "CREATED"
    again = jl.record_bonus_obligation(db, organization_id=organization.id, employee_id=501,
                                       jp_result=jp_result, paid_on=date(2026, 6, 15), actor_id=1)
    assert again.id == first.id

    changed = dict(jp_result, jp_bonus=dict(jp_result["jp_bonus"], jp_bonus_sba="400000"))
    with pytest.raises(BadRequestException, match="already recorded"):
        jl.record_bonus_obligation(db, organization_id=organization.id, employee_id=501,
                                   jp_result=changed, paid_on=date(2026, 6, 15), actor_id=1)
    with pytest.raises(BadRequestException, match="no bonus"):
        jl.record_bonus_obligation(db, organization_id=organization.id, employee_id=501,
                                   jp_result={"jp_bonus": None}, paid_on=date(2026, 6, 15), actor_id=1)
