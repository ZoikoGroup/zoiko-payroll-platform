"""
tests/test_switzerland_fak_floor_absence.py
-------------------------------------------
CH Step 11 — family allowances (FAK), wage floors and absence-benefit events.

Engine: FAK paid only per APPROVED entitlement at the canton amount (a canton
amount below the federal minimum blocks, never substituted), differential
entitlements, the employer FAK contribution and the Valais-only employee
share; wage floors applied only within scope (canton minimum by work canton,
GAV / NAV by assignment) with grade / experience scales, a shortfall blocks and
no floor is an explicit NO_MANDATORY_FLOOR line; absence allowances and top-ups
as their own classified earning types.
Service/API: the resolver's per-period facts, entitlement four-eyes approval,
absence-event CRUD.

Every amount, rate and agreement here is SYNTHETIC.
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.payroll.engine.countries.switzerland import SwitzerlandCalculationBlockedError, calculate
from app.modules.payroll.engine.countries.switzerland_content import (
    CH_AHV, CH_ALV, CH_EO, CH_IV, CH_UVG, CH_WAGE_FLOOR,
)
from tests.test_hong_kong_governance import _http
from tests.test_switzerland_engine import _amount_row, _full_ctx
from tests.test_switzerland_resolver import _resolve, world  # noqa: F401 (fixture)

FEDERAL = (CH_AHV, CH_IV, CH_EO, CH_ALV)


def _classified(extra=None, wage_floor=None):
    """base_salary counts everywhere; `extra` = {earning_type: included} for
    every federal obligation and UVG."""
    row = {"base_salary": True, **(extra or {})}
    out = {obl: dict(row) for obl in FEDERAL + (CH_UVG,)}
    if wage_floor is not None:
        out[CH_WAGE_FLOOR] = wage_floor
    return out


def _ctx(salary="10000", **kw):
    ctx = _full_ctx(earnings={"base_salary": Decimal(salary)}, classification=kw.pop("classification", _classified()),
                    scheme_rules={"admin_cost_pct": "1.0"}, work_canton=kw.pop("work_canton", "CH-ZH"),
                    fak_rules=kw.pop("fak_rules", None))
    ctx.ch_canton_rate_maps = kw.pop("canton_maps", {
        "CH-ZH": {"ch_fak_child": _amount_row("250"), "ch_fak_education": _amount_row("300")},
        "CH-GE": {"ch_fak_child": _amount_row("300"), "ch_fak_education": _amount_row("400")},
    })
    for k, v in kw.items():
        setattr(ctx, k, v)
    return ctx


def _ent(eid, kind="CHILD", basis="PRIMARY", canton=None, primary=None):
    return {"id": eid, "allowance_type": kind, "entitlement_basis": basis, "canton": canton, "primary_amount": primary}


# ── FAK ──────────────────────────────────────────────────────────────────

def test_canton_amount_above_federal_minimum_is_paid_per_entitlement():
    out = calculate(_ctx(ch_fak_entitlements=[_ent(1), _ent(2), _ent(3, "EDUCATION")]))
    assert out["ch_fak_child_total"] == Decimal("500")              # 2 x ZH 250 (federal minimum 215)
    assert out["ch_fak_education_total"] == Decimal("300")
    assert out["ch_family_allowance_total"] == Decimal("800")
    paid = out["ch_calculation_trace"]["fak"]["entitlements"]
    assert [p["entitlement_id"] for p in paid] == [1, 2, 3]
    assert paid[0]["canton_amount"] == "250" and paid[0]["federal_minimum"] == "215"
    assert out["ch_employee_total"] == Decimal("685.00")             # an allowance is never a deduction


def test_children_on_the_profile_without_an_approved_entitlement_are_not_paid():
    ctx = _ctx()
    ctx.ch_children_count, ctx.ch_students_count = 3, 2
    out = calculate(ctx)
    assert out["ch_family_allowance_total"] == Decimal("0")
    assert out["ch_calculation_trace"]["fak"]["entitlements"] == []


def test_canton_amount_below_federal_minimum_blocks_and_is_never_substituted():
    maps = {"CH-ZH": {"ch_fak_child": _amount_row("200")}}           # below the 215 federal minimum
    with pytest.raises(SwitzerlandCalculationBlockedError) as exc:
        calculate(_ctx(canton_maps=maps, ch_fak_entitlements=[_ent(1)]))
    assert exc.value.key == "ch_fak_below_federal_minimum" and "never substituted" in exc.value.reason


@pytest.mark.parametrize("ctx_kw, key", [
    ({"canton_maps": {"CH-ZH": {}}}, "ch_fak_child:CH-ZH"),           # canton amount not configured
    ({"ch_fak_entitlements": [_ent(1, "BIRTH")]}, "ch_fak_birth"),    # no configured amount -> never invented
    ({"ch_fak_entitlements": [_ent(1, basis="DIFFERENTIAL")]}, "ch_fak_differential:1"),
])
def test_fak_gaps_block(ctx_kw, key):
    kw = {"ch_fak_entitlements": [_ent(1)], **ctx_kw}
    with pytest.raises(SwitzerlandCalculationBlockedError) as exc:
        calculate(_ctx(**kw))
    assert exc.value.key == key


def test_fak_federal_minimum_required_for_an_entitlement():
    ctx = _ctx(ch_fak_entitlements=[_ent(1)])
    del ctx.rate_map["ch_fak_child_min"]
    with pytest.raises(SwitzerlandCalculationBlockedError) as exc:
        calculate(ctx)
    assert exc.value.key == "ch_fak_child_min"
    ctx.ch_fak_entitlements = []                                      # no entitlement: the minimum is not read
    assert calculate(ctx)["ch_family_allowance_total"] == Decimal("0")


def test_differential_entitlement_pays_only_the_difference():
    out = calculate(_ctx(ch_fak_entitlements=[_ent(1, basis="DIFFERENTIAL", canton="CH-GE", primary="215")]))
    assert out["ch_fak_child_total"] == Decimal("85")                 # GE 300 - 215 paid by the primary fund
    paid = out["ch_calculation_trace"]["fak"]["entitlements"][0]
    assert paid["basis"] == "DIFFERENTIAL" and paid["canton"] == "CH-GE" and paid["primary_amount"] == "215"
    out = calculate(_ctx(ch_fak_entitlements=[_ent(1, basis="DIFFERENTIAL", canton="CH-GE", primary="350")]))
    assert out["ch_fak_child_total"] == Decimal("0")                  # never negative


def test_employee_fak_share_only_where_the_canton_configures_it():
    from tests.test_switzerland_engine import _rate_row

    zh = calculate(_ctx(fak_rules={"employer_pct": "1.2", "employee_pct": "0.5"}))
    assert zh["ch_fak_employer"] == Decimal("120.00") and zh["ch_fak_employee"] == Decimal("0")   # scheme alone: none
    maps = {"CH-VS": {"ch_fak_employee_pct": _rate_row("0.17", "0")}}
    vs = calculate(_ctx(work_canton="CH-VS", canton_maps=maps))
    assert vs["ch_fak_employer"] == Decimal("120.00") and vs["ch_fak_employee"] == Decimal("17.00")
    assert vs["ch_employee_total"] == zh["ch_employee_total"] + Decimal("17.00")
    sides = {(ln["obligation"], ln["side"]) for ln in vs["ch_calculation_trace"]["lines"]}
    assert {("ch_fak", "employer"), ("ch_fak", "employee")} <= sides


def test_missing_fak_scheme_blocks():
    ctx = _ctx()
    del ctx.ch_fak_scheme_rules
    with pytest.raises(SwitzerlandCalculationBlockedError) as exc:
        calculate(ctx)
    assert exc.value.key == "ch_fak_scheme"


# ── wage floor ───────────────────────────────────────────────────────────

GE_MIN = {"id": 11, "agreement_type": "CH_CANTON_MINIMUM", "agreement_code": "CH-GE-MIN", "version": "1.0",
          "canton": "CH-GE", "assigned": False, "wage_floor": {"basis": "HOURLY", "amount": "24.00", "scales": []}}
GAV = {"id": 12, "agreement_type": "CH_GAV", "agreement_code": "CH-GAV-TEST", "version": "2.0", "canton": None,
       "assigned": True, "wage_floor": {"basis": "MONTHLY", "scales": [
           {"grade": "I", "amount": "3800"}, {"grade": "I", "experience_years_from": "5", "amount": "4200"},
           {"grade": "II", "amount": "4600"}]}}


def _floor_ctx(salary, agreements, work_canton="CH-GE", **kw):
    return _ctx(salary=salary, work_canton=work_canton, ch_wage_floor_agreements=agreements,
                classification=_classified(wage_floor={"base_salary": True}), **kw)


def test_no_floor_in_scope_is_an_explicit_line_with_its_basis():
    out = calculate(_floor_ctx("2000", [GE_MIN], work_canton="CH-ZH"))      # Geneva minimum, worker in Zurich
    floor = out["ch_calculation_trace"]["wage_floor"]
    assert floor["rule"] == "NO_MANDATORY_FLOOR" and "no federal statutory minimum wage" in floor["basis"]
    assert floor["skipped"] == [{"agreement_code": "CH-GE-MIN",
                                 "reason": "canton minimum for CH-GE; the worker works in CH-ZH"}]
    line = [ln for ln in out["ch_calculation_trace"]["lines"] if ln["obligation"] == CH_WAGE_FLOOR]
    assert len(line) == 1 and line[0]["rate_or_rule"] == "NO_MANDATORY_FLOOR"


def test_geneva_minimum_applies_only_after_the_scope_matches():
    ctx = _floor_ctx("4000", [GE_MIN], ch_period_hours=Decimal("173.33"))   # 4000 / 173.33 = 23.08 < 24
    with pytest.raises(SwitzerlandCalculationBlockedError) as exc:
        calculate(ctx)
    assert exc.value.key == "ch_wage_floor_shortfall" and "no automatic top-up" in exc.value.reason
    out = calculate(_floor_ctx("4500", [GE_MIN], ch_period_hours=Decimal("173.33")))
    check = out["ch_calculation_trace"]["wage_floor"]["checks"][0]
    assert check["agreement_code"] == "CH-GE-MIN" and check["pay_rate"] == "25.96" and check["floor"] == "24.00"
    assert out["ch_ahv_employee"] == Decimal("195.75")                     # a check, never an adjustment
    with pytest.raises(SwitzerlandCalculationBlockedError) as exc:
        calculate(_floor_ctx("4500", [GE_MIN]))                            # hourly floor without hours
    assert exc.value.key == "ch_period_hours"


def test_gav_floor_by_grade_and_experience():
    with pytest.raises(SwitzerlandCalculationBlockedError) as exc:          # grade I, 6 yrs -> 4200 floor
        calculate(_floor_ctx("4000", [GAV], ch_grade="I", ch_experience_years=Decimal("6")))
    assert exc.value.key == "ch_wage_floor_shortfall" and "4200" in exc.value.reason
    out = calculate(_floor_ctx("4000", [GAV], ch_grade="I", ch_experience_years=Decimal("2")))   # 3800 floor
    assert out["ch_calculation_trace"]["wage_floor"]["checks"][0]["floor"] == "3800"
    with pytest.raises(SwitzerlandCalculationBlockedError) as exc:          # grade II -> 4600
        calculate(_floor_ctx("4500", [GAV], ch_grade="II", ch_experience_years=Decimal("0")))
    assert exc.value.key == "ch_wage_floor_shortfall"
    with pytest.raises(SwitzerlandCalculationBlockedError) as exc:          # no scale matches, no base amount
        calculate(_floor_ctx("9000", [GAV], ch_grade="III"))
    assert exc.value.key == "ch_wage_floor_scale:CH-GAV-TEST"


def test_unassigned_gav_is_out_of_scope_and_both_floors_must_hold():
    out = calculate(_floor_ctx("3000", [{**GAV, "assigned": False}], ch_grade="I"))
    assert out["ch_calculation_trace"]["wage_floor"]["rule"] == "NO_MANDATORY_FLOOR"
    out = calculate(_floor_ctx("4500", [GE_MIN, GAV], ch_grade="I", ch_experience_years=Decimal("1"),
                               ch_period_hours=Decimal("173.33")))
    assert [c["agreement_code"] for c in out["ch_calculation_trace"]["wage_floor"]["checks"]] == [
        "CH-GE-MIN", "CH-GAV-TEST"]


def test_countable_pay_needs_its_own_classification():
    ctx = _ctx(salary="4500", work_canton="CH-GE", ch_wage_floor_agreements=[GE_MIN], ch_period_hours=Decimal("170"))
    with pytest.raises(SwitzerlandCalculationBlockedError) as exc:
        calculate(ctx)
    assert exc.value.key == "ch_classification:ch_wage_floor:base_salary"


# ── absence-benefit earnings ─────────────────────────────────────────────

ABSENCE_CLASSES = {"CH_EO_ALLOWANCE": True, "CH_UVG_DAILY": False, "CH_EMPLOYER_TOPUP": True}


def test_absence_allowances_are_their_own_classified_earning_types():
    events = [{"event_id": 7, "event_type": "MATERNITY", "allowance": Decimal("2200"), "topup": Decimal("300")},
              {"event_id": 8, "event_type": "ACCIDENT_UVG", "allowance": Decimal("1000"), "topup": Decimal("0")}]
    ctx = _ctx(classification=_classified(ABSENCE_CLASSES), ch_absence_earnings=events)
    out = calculate(ctx)
    assert out["ch_calculation_trace"]["bases"][CH_AHV] == "12500.00"   # salary + EO allowance + top-up, not UVG daily
    assert out["ch_ahv_employee"] == Decimal("543.75")
    assert out["ch_absence_earnings_total"] == Decimal("3500")
    applied = out["ch_calculation_trace"]["absence"]
    assert [(a["event_id"], a["earning_type"]) for a in applied] == [(7, "CH_EO_ALLOWANCE"), (8, "CH_UVG_DAILY")]
    assert set(out["ch_calculation_trace"]["input_hash"]) and ctx.earnings == {"base_salary": Decimal("10000")}


def test_absence_earning_without_classification_blocks():
    events = [{"event_id": 8, "event_type": "ACCIDENT_UVG", "allowance": Decimal("1000"), "topup": Decimal("0")}]
    with pytest.raises(SwitzerlandCalculationBlockedError) as exc:
        calculate(_ctx(ch_absence_earnings=events))
    assert exc.value.key == "ch_classification:ch_ahv:CH_UVG_DAILY"


@pytest.mark.parametrize("ctx_kw, key", [
    ({"ch_absence_earnings": [{"event_id": 9, "event_type": "ILLNESS_CO", "allowance": Decimal("50")}]},
     "ch_absence_event:9"),
    ({"ch_absence_earnings": [{"event_id": 9, "event_type": "HOLIDAY", "allowance": Decimal("50")}]},
     "ch_absence_event:9"),
])
def test_absence_event_gaps_block(ctx_kw, key):
    with pytest.raises(SwitzerlandCalculationBlockedError) as exc:
        calculate(_ctx(classification=_classified(ABSENCE_CLASSES), **ctx_kw))
    assert exc.value.key == key


def test_absence_earning_types_cannot_be_entered_manually():
    ctx = _ctx(classification=_classified(ABSENCE_CLASSES),
               ch_absence_earnings=[{"event_id": 7, "event_type": "MATERNITY", "allowance": Decimal("1")}])
    ctx.earnings = {"base_salary": Decimal("10000"), "CH_EO_ALLOWANCE": Decimal("500")}
    with pytest.raises(SwitzerlandCalculationBlockedError) as exc:
        calculate(ctx)
    assert exc.value.key == "ch_absence_earning:CH_EO_ALLOWANCE"


# ── resolver: per-period facts ────────────────────────────────────────────

def _rule(db, component, earning_type, included=True):
    from app.modules.payroll.models import TaxabilityRule

    db.add(TaxabilityRule(jurisdiction_country="CH", earning_type=earning_type, tax_component=component,
                          is_taxable=included, status="Approved", effective_from=date(2026, 1, 1)))


def test_resolver_passes_only_approved_entitlements_with_their_canton_pack(db, world):
    from app.modules.payroll.models import ChFamilyAllowanceEntitlement

    common = dict(organization_id=world.org.id, employee_id=world.employee.id, allowance_type="CHILD",
                  period_from=date(2026, 1, 1))
    db.add_all([ChFamilyAllowanceEntitlement(status="APPROVED", **common),
                ChFamilyAllowanceEntitlement(status="REQUESTED", **common),
                ChFamilyAllowanceEntitlement(status="APPROVED", entitlement_basis="DIFFERENTIAL", canton="CH-GE",
                                             precedence_evidence={"primary_amount": "215"}, **common)])
    db.commit()
    out = _resolve(db, world)
    assert out["ready"] is True
    ents = out["inputs"]["fakEntitlements"]
    assert [(e["canton"], e["entitlement_basis"], e["primary_amount"]) for e in ents] == [
        ("CH-ZH", "PRIMARY", None), ("CH-GE", "DIFFERENTIAL", "215")]
    assert set(out["inputs"]["fakCantonPacks"]) == {"CH-ZH", "CH-GE"}


def test_resolver_blocks_an_entitlement_paid_from_a_canton_without_an_active_pack(db, world):
    from app.modules.payroll.models import ChFamilyAllowanceEntitlement

    db.add(ChFamilyAllowanceEntitlement(organization_id=world.org.id, employee_id=world.employee.id,
                                        allowance_type="CHILD", status="APPROVED", canton="CH-BS",
                                        period_from=date(2026, 1, 1)))
    db.commit()
    assert [b["key"] for b in _resolve(db, world)["blocked"]] == ["ch_fak_canton_pack:CH-BS"]


def test_resolver_apportions_absence_events_to_the_period_and_demands_classification(db, world):
    from app.modules.payroll.models import ChAbsenceBenefitEvent

    db.add(ChAbsenceBenefitEvent(organization_id=world.org.id, employee_id=world.employee.id, event_type="MATERNITY",
                                 period_from=date(2026, 3, 17), period_to=date(2026, 6, 22),
                                 daily_allowance_rate=Decimal("150"), employer_topup_amount=Decimal("980")))
    db.commit()
    out = _resolve(db, world)
    assert out["inputs"]["absenceEarnings"] == [{"event_id": out["inputs"]["absenceEventIds"][0],
                                                 "event_type": "MATERNITY", "days": 15,
                                                 "allowance": Decimal("2250"), "topup": Decimal("150.00")}]
    keys = {b["key"] for b in out["blocked"]}
    assert "ch_taxability:ch_ahv:CH_EO_ALLOWANCE" in keys and "ch_taxability:ch_ahv:CH_EMPLOYER_TOPUP" in keys
    for component in ("ch_ahv", "ch_iv", "ch_eo", "ch_alv", "ch_uvg", "ch_bvg", "ch_ktg", "ch_qst"):
        _rule(db, component, "CH_EO_ALLOWANCE")
        _rule(db, component, "CH_EMPLOYER_TOPUP")
    db.commit()
    assert _resolve(db, world)["ready"] is True


@pytest.mark.parametrize("event_kw, reason", [
    ({"event_type": "ACCIDENT_UVG", "period_to": date(2026, 4, 30)}, "no daily allowance rate"),
    ({"event_type": "ILLNESS_CO", "employer_topup_amount": Decimal("500")}, "end date"),
])
def test_resolver_absence_gaps_block(db, world, event_kw, reason):
    from app.modules.payroll.models import ChAbsenceBenefitEvent

    db.add(ChAbsenceBenefitEvent(organization_id=world.org.id, employee_id=world.employee.id,
                                 period_from=date(2026, 3, 1), **event_kw))
    db.commit()
    blocked = _resolve(db, world)["blocked"]
    assert blocked[0]["key"].startswith("ch_absence_event:") and reason in blocked[0]["reason"]


def test_resolver_demands_wage_floor_classification_once_a_floor_applies(db, world):
    from app.modules.payroll.models import CollectiveAgreement

    db.add(CollectiveAgreement(jurisdiction_country="CH", jurisdiction_state="CH-ZH", agreement_code="CH-ZH-MIN-T",
                               name="TEST", agreement_type="CH_CANTON_MINIMUM", version="1.0", status="Active",
                               effective_from=date(2026, 1, 1),
                               modules={"wage_floor": {"basis": "MONTHLY", "amount": "4000"}}))
    db.commit()
    out = _resolve(db, world)
    assert [b["key"] for b in out["blocked"]] == ["ch_taxability:ch_wage_floor"]
    assert out["inputs"]["wageFloorAgreements"][0]["agreement_code"] == "CH-ZH-MIN-T"
    _rule(db, CH_WAGE_FLOOR, "base_salary")
    db.commit()
    assert _resolve(db, world)["ready"] is True


# ── API: entitlements (four-eyes) + absence events ───────────────────────

ORG = "/api/payroll/switzerland"


@pytest.fixture()
def people(db, organization):
    from app.modules.payroll.models import PayrollEmployee

    emp = PayrollEmployee(organization_id=organization.id, employee_code="CH9", name="Test Worker")
    db.add(emp)
    db.commit()
    mk = lambda i: SimpleNamespace(id=i, organization_id=organization.id, role="org_admin", is_active=True)  # noqa: E731
    return SimpleNamespace(employee=emp, a=mk(501), b=mk(502), c=mk(503))


def _h():
    import uuid

    return {"Idempotency-Key": uuid.uuid4().hex}


def test_entitlement_four_eyes_and_fund_decision(db, people):
    body = {"employeeId": people.employee.id, "allowanceType": "CHILD", "periodFrom": "2026-01-01", "canton": "CH-ZH"}
    with _http(db, people.a) as c:
        ent = c.post(f"{ORG}/family-allowances", json=body, headers=_h()).json()
        assert ent["status"] == "REQUESTED"
        assert c.post(f"{ORG}/family-allowances/{ent['id']}/approve", headers=_h()).status_code == 400   # author
    with _http(db, people.b) as c:
        res = c.post(f"{ORG}/family-allowances/{ent['id']}/approve", headers=_h())
        assert res.status_code == 400 and "fundDecisionReference" in res.text
        assert c.put(f"{ORG}/family-allowances/{ent['id']}", json={"fundDecisionReference": "FAK-ZH-1"},
                     headers=_h()).status_code == 200
        assert c.post(f"{ORG}/family-allowances/{ent['id']}/approve", headers=_h()).status_code == 400  # now an editor
    with _http(db, people.c) as c:
        assert c.post(f"{ORG}/family-allowances/{ent['id']}/approve", headers=_h()).json()["status"] == "APPROVED"
        assert c.put(f"{ORG}/family-allowances/{ent['id']}", json={"periodTo": "2026-12-31"},
                     headers=_h()).status_code == 400                                            # approved = frozen
        assert c.delete(f"{ORG}/family-allowances/{ent['id']}", headers=_h()).status_code == 400


def test_entitlement_input_rules(db, people):
    base = {"employeeId": people.employee.id, "allowanceType": "CHILD", "periodFrom": "2026-01-01"}
    with _http(db, people.a) as c:
        assert c.post(f"{ORG}/family-allowances", json={**base, "entitlementBasis": "DIFFERENTIAL"},
                      headers=_h()).status_code == 422                        # needs the primary fund's amount
        assert c.post(f"{ORG}/family-allowances", json={**base, "primaryFundAmount": "10"},
                      headers=_h()).status_code == 422                        # PRIMARY has no primary amount
        assert c.post(f"{ORG}/family-allowances", json={**base, "employeeId": 999999},
                      headers=_h()).status_code == 404
        diff = c.post(f"{ORG}/family-allowances", json={**base, "entitlementBasis": "DIFFERENTIAL",
                                                        "primaryFundAmount": "215", "canton": "CH-GE"},
                      headers=_h()).json()
        assert diff["primaryFundAmount"] == "215"
        assert c.delete(f"{ORG}/family-allowances/{diff['id']}", headers=_h()).json()["deleted"] is True


def test_absence_event_crud(db, people):
    body = {"employeeId": people.employee.id, "eventType": "ACCIDENT_UVG", "periodFrom": "2026-03-01",
            "dailyAllowanceRate": "120"}
    with _http(db, people.a) as c:
        assert c.post(f"{ORG}/absence-events", json={**body, "eventType": "ILLNESS_CO"},
                      headers=_h()).status_code == 422                        # no insurer allowance on ILLNESS_CO
        ev = c.post(f"{ORG}/absence-events", json=body, headers=_h()).json()
        assert ev["status"] == "OPEN" and ev["allowanceEarningType"] == "CH_UVG_DAILY"
        res = c.put(f"{ORG}/absence-events/{ev['id']}", json={"periodTo": "2026-03-20", "status": "CLOSED"},
                    headers=_h())
        assert res.json()["status"] == "CLOSED"
        assert c.put(f"{ORG}/absence-events/{ev['id']}", json={"dailyAllowanceRate": "1"},
                     headers=_h()).status_code == 400                         # closed = frozen
        assert c.delete(f"{ORG}/absence-events/{ev['id']}", headers=_h()).status_code == 400
        assert [e["id"] for e in c.get(f"{ORG}/absence-events").json()] == [ev["id"]]
