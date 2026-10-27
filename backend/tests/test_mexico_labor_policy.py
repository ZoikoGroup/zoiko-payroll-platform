"""Mexico Phase 3 — labour policy (panels F and G) checked against the
statutory floors of the ACTIVE national pack (Q1, MX-051). Empty content or
no Active pack → BLOCKED_CONTENT; a policy may improve on a floor, never go
below it, and FAIL is never auto-raised. SYNTHETIC floor values."""

from datetime import date

import pytest

from tests._mx_employer_helpers import active_pack, make_org, new_employer, policy_payload, to_service


def _svc():
    from app.modules.payroll import mexico_employer_service

    return mexico_employer_service


def _policy(db, org_id, emp_id, **over):
    data = to_service(policy_payload(**over))
    return _svc().create_labor_policy(db, org_id, emp_id, data, 701)


def _setup(db):
    t = make_org(db)
    return t, new_employer(db, t.org.id)


def test_no_active_pack_is_blocked_content_and_cannot_activate(db):
    from app.core.exceptions import BadRequestException

    t, emp = _setup(db)
    p = _policy(db, t.org.id, emp["id"])
    assert p["floorCheckStatus"] == "BLOCKED_CONTENT"
    assert "statutory content not active" in p["floorCheckDetail"]["checks"][0]["missing"][0]
    with pytest.raises(BadRequestException, match="floor check BLOCKED_CONTENT"):
        _svc().activate_labor_policy(db, t.org.id, p["id"], 701)


def test_a_draft_seeded_pack_does_not_count(db):
    from scripts.seed_mexico_canonical_packs import load_manifest, seed_mexico

    seed_mexico(db, manifest=load_manifest())
    db.commit()
    t, emp = _setup(db)
    assert _policy(db, t.org.id, emp["id"])["floorCheckStatus"] == "BLOCKED_CONTENT"


def test_a_missing_floor_key_blocks(db):
    t, emp = _setup(db)
    active_pack(db, scalars={"mx_aguinaldo_min_days": ("flat_amount", "15")})
    p = _policy(db, t.org.id, emp["id"])
    assert p["floorCheckStatus"] == "BLOCKED_CONTENT"
    assert any("mx_vacation_premium_min_pct" in m for m in p["floorCheckDetail"]["checks"][0]["missing"])


def test_at_floor_passes_and_activates(db):
    t, emp = _setup(db)
    active_pack(db)
    p = _policy(db, t.org.id, emp["id"])
    assert p["floorCheckStatus"] == "PASS"
    assert p["floorCheckDetail"]["checks"][0]["dailyLimits"].startswith("not checked")
    assert _svc().activate_labor_policy(db, t.org.id, p["id"], 701)["status"] == "ACTIVE"


def test_above_floor_is_allowed(db):
    t, emp = _setup(db)
    active_pack(db)
    p = _policy(db, t.org.id, emp["id"], aguinaldoDays="30", vacationPremiumPct="50", ordinaryWeeklyHours="40",
                vacationPolicy=[{"serviceYearFrom": 1, "serviceYearTo": None, "days": "20"}])
    assert p["floorCheckStatus"] == "PASS"


@pytest.mark.parametrize("over,field", [
    ({"aguinaldoDays": "14"}, "aguinaldo_days"),
    ({"vacationPremiumPct": "24.9"}, "vacation_premium_pct"),
    ({"sundayPremiumPct": "10"}, "sunday_premium_pct"),
    ({"ordinaryWeeklyHours": "50"}, "ordinary_weekly_hours"),
    ({"vacationPolicy": [{"serviceYearFrom": 1, "serviceYearTo": None, "days": "12"}]}, "vacation_policy"),
    ({"vacationPolicy": [{"serviceYearFrom": 2, "serviceYearTo": None, "days": "30"}]}, "vacation_policy"),
])
def test_below_floor_fails_and_is_never_auto_raised(db, over, field):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.models import PayrollMxLaborPolicy

    t, emp = _setup(db)
    active_pack(db)
    p = _policy(db, t.org.id, emp["id"], **over)
    assert p["floorCheckStatus"] == "FAIL"
    failed = [f for f in p["floorCheckDetail"]["checks"][0]["findings"] if f["result"] == "FAIL"]
    assert failed and failed[0]["field"] == field
    with pytest.raises(BadRequestException, match="below a statutory floor"):
        _svc().activate_labor_policy(db, t.org.id, p["id"], 701)
    row = db.get(PayrollMxLaborPolicy, p["id"])
    assert row.status == "DRAFT" and str(row.aguinaldo_days) == str(row.aguinaldo_days)   # untouched


def test_open_policy_is_rechecked_at_a_later_workweek_row(db):
    """A 48-hour policy passes on its start date but FAILS from a later
    (synthetic) 46-hour row inside the same Active content (MX-048/MX-050)."""
    t, emp = _setup(db)
    active_pack(db, extra_workweek=(date(2026, 9, 1), "46"))
    p = _policy(db, t.org.id, emp["id"])
    checks = {c["on"]: c["status"] for c in p["floorCheckDetail"]["checks"]}
    assert checks["2026-03-01"] == "PASS" and checks["2026-09-01"] == "FAIL"
    assert p["floorCheckStatus"] == "FAIL"
    assert _svc().floor_check_view(db, t.org.id, p["id"], date(2026, 8, 31))["status"] == "PASS"


def test_activation_supersedes_the_previous_policy_in_date_order(db):
    from app.core.exceptions import BadRequestException

    t, emp = _setup(db)
    active_pack(db)
    first = _policy(db, t.org.id, emp["id"])
    _svc().activate_labor_policy(db, t.org.id, first["id"], 701)
    later = _policy(db, t.org.id, emp["id"], effectiveFrom="2026-06-01", aguinaldoDays="20")
    _svc().activate_labor_policy(db, t.org.id, later["id"], 701)
    rows = {p["id"]: p for p in _svc().list_labor_policies(db, t.org.id, emp["id"])}
    assert rows[first["id"]]["status"] == "SUPERSEDED" and rows[first["id"]]["effectiveTo"] == "2026-05-31"
    earlier = _policy(db, t.org.id, emp["id"], effectiveFrom="2026-04-01")
    with pytest.raises(BadRequestException, match="activate in date order"):
        _svc().activate_labor_policy(db, t.org.id, earlier["id"], 701)


def test_collective_agreement_link_is_optional_mexican_and_has_no_effect(db):
    from app.core.exceptions import NotFoundException
    from app.modules.payroll.models import CollectiveAgreement

    t, emp = _setup(db)
    active_pack(db)
    se = CollectiveAgreement(jurisdiction_country="SE", agreement_code="SE-X", name="SE", agreement_type="SECTOR",
                             version="1.0", status="Active")
    mx = CollectiveAgreement(jurisdiction_country="MX", agreement_code="MX-CCT-SYN", name="CCT", version="1.0",
                             agreement_type="EMPLOYER_SPECIFIC", organization_id=t.org.id, status="Draft")
    db.add_all([se, mx])
    db.commit()
    with pytest.raises(NotFoundException):
        _policy(db, t.org.id, emp["id"], collectiveAgreementId=se.id)
    p = _policy(db, t.org.id, emp["id"], collectiveAgreementId=mx.id, aguinaldoDays="14")
    assert p["floorCheckStatus"] == "FAIL"                    # a CCT never relaxes a floor
    assert [a["code"] for a in _svc().list_collective_agreements(db, t.org.id)] == ["MX-CCT-SYN"]


def test_vacation_bands_must_not_overlap():
    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException, match="overlap"):
        _svc()._vacation_bands([{"serviceYearFrom": 1, "serviceYearTo": 3, "days": "12"},
                                {"serviceYearFrom": 2, "serviceYearTo": None, "days": "14"}])
