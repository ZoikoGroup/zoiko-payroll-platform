"""Mexico Phase 4b — per-employee readiness: explicit `on`, items mapped to
the spec §22 gates (or unmapped), blocked while content / catalogs / sources
are missing, the employer summary line, and LIVE never reachable.
SYNTHETIC data."""

from datetime import date
from decimal import Decimal

import pytest

from tests._mx_employer_helpers import (
    ORG_BASE, SA_BASE, SUPER_ADMIN, active_pack, enable_mx_onboarding, http, make_org, mx_workplace, new_mx_employee,
    principal, save_mx_profile,
)


@pytest.fixture(autouse=True)
def _flag(monkeypatch):
    enable_mx_onboarding(monkeypatch)


def _items(r):
    return {i["key"]: i for i in r["items"]}


def _ready(db, org_id, emp_id, on=date(2026, 3, 1)):
    from app.modules.payroll import mexico_employee_service as svc

    return svc.employee_readiness(db, org_id, emp_id, on)


def test_on_is_required_and_no_profile_is_not_started(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import mexico_employee_service as svc

    t = make_org(db)
    emp = new_mx_employee(db, t.org.id)
    with pytest.raises(BadRequestException, match="explicit date"):
        svc.employee_readiness(db, t.org.id, emp.id, None)
    r = _ready(db, t.org.id, emp.id)
    assert _items(r)["mx_profile"]["status"] == "NOT_STARTED" and r["liveEligible"] is False


def test_items_and_gates_while_content_is_empty(db):
    from app.modules.payroll import mexico_employer_service as esvc

    t = make_org(db)
    emp = new_mx_employee(db, t.org.id)
    w = mx_workplace(db, t.org.id)
    save_mx_profile(db, emp, t.org.id, mx_establishment_id=w.establishment["id"],
                    mx_imss_registration_id=w.registration["id"], mx_contract_type_code="01",
                    mx_daily_salary=Decimal("500"))
    r = _ready(db, t.org.id, emp.id)
    i = _items(r)
    assert i["identifiers"]["status"] == "BLOCKED" and "S31/S32" in i["identifiers"]["detail"]
    assert i["mx_contract_type_code"]["status"] == "BLOCKED" and "S28" in i["mx_contract_type_code"]["detail"]
    assert i["imss_registration"]["status"] == "PASS"
    assert i["isn_state"]["status"] == "BLOCKED" and "not activated" in i["isn_state"]["detail"]
    assert i["min_wage_zone"]["status"] == "BLOCKED" and i["salary_minimum"]["status"] == "BLOCKED"
    assert i["identity_token_key"]["status"] == "BLOCKED"            # dev fallback in tests ≠ a dedicated key
    for item in r["items"]:
        assert item["gateBasis"] == {g: esvc.GATE_DEFINITIONS[g] for g in item["gates"]}
    assert r["liveEligible"] is False


def test_salary_vs_minimum_with_synthetic_active_content(db):
    from app.modules.payroll.engine.countries import mexico_content as c
    from app.modules.payroll.models import TaxSlab

    t = make_org(db)
    emp = new_mx_employee(db, t.org.id)
    w = mx_workplace(db, t.org.id)
    pack = active_pack(db)
    db.add(TaxSlab(jurisdiction_pack_id=pack.id, jurisdiction_country="MX", rule_type=c.MX_MIN_WAGE_RULE,
                   filing_status="GENERAL", min_amount=Decimal("0"), flat_amount=Decimal("300"), rate_pct=Decimal("0"),
                   rate_label="SYNTHETIC", tax_formula="SYNTHETIC"))
    db.commit()
    c_list = (c.ZlfnMunicipality("BCN", "Tijuana", "S9", "SYNTHETIC"),)
    import app.modules.payroll.engine.countries.mexico_content as content
    original = content.MX_ZLFN_MUNICIPALITIES
    content.MX_ZLFN_MUNICIPALITIES = c_list
    try:
        save_mx_profile(db, emp, t.org.id, mx_establishment_id=w.establishment["id"], mx_daily_salary=Decimal("250"))
        below = _items(_ready(db, t.org.id, emp.id))["salary_minimum"]
        save_mx_profile(db, emp, t.org.id, effective_from=date(2026, 4, 1), mx_daily_salary=Decimal("350"))
        above = _items(_ready(db, t.org.id, emp.id, on=date(2026, 4, 1)))["salary_minimum"]
    finally:
        content.MX_ZLFN_MUNICIPALITIES = original
    assert below["status"] == "BLOCKED" and "below the minimum" in below["detail"]
    assert above["status"] == "PASS"


def test_unsupported_work_state_is_blocked_mx045(db):
    t = make_org(db)
    emp = new_mx_employee(db, t.org.id)
    w = mx_workplace(db, t.org.id, state="JAL", municipality="Guadalajara")
    save_mx_profile(db, emp, t.org.id, mx_establishment_id=w.establishment["id"])
    item = _items(_ready(db, t.org.id, emp.id))["isn_state"]
    assert item["status"] == "BLOCKED" and "MX-045" in item["detail"]


def test_employer_readiness_shows_the_employee_exceptions_line(db):
    from app.modules.payroll import mexico_employer_service as esvc

    t = make_org(db)
    emp = new_mx_employee(db, t.org.id)
    w = mx_workplace(db, t.org.id)
    save_mx_profile(db, emp, t.org.id, mx_establishment_id=w.establishment["id"])
    r = esvc.organisation_readiness(db, t.org.id, date(2026, 3, 1))["employers"][0]
    line = next(i for i in r["items"] if i["key"] == "employee_exceptions")
    assert line["status"] == "BLOCKED" and "1 of 1" in line["detail"] and line["gateMapping"] == "unmapped"


def test_super_admin_readiness_never_evaluates_the_employee_exceptions_line(db):
    """ZP-PRIV: the same employer seen by a platform principal (masked view and
    the per-gate summary) does not read employee rows — the line is not
    evaluated, so it is never PASS and the employer is never live-eligible."""
    from app.modules.payroll import mexico_employer_service as esvc

    t = make_org(db)
    emp = new_mx_employee(db, t.org.id)
    w = mx_workplace(db, t.org.id)
    save_mx_profile(db, emp, t.org.id, mx_establishment_id=w.establishment["id"])
    on = date(2026, 3, 1)
    org_view = esvc.organisation_readiness(db, t.org.id, on)["employers"][0]
    sa_view = esvc.organisation_readiness(db, t.org.id, on, masked=True)["employers"][0]
    line = lambda r: next(i for i in r["items"] if i["key"] == "employee_exceptions")  # noqa: E731
    assert line(org_view)["status"] == "BLOCKED" and "1 of 1" in line(org_view)["detail"]
    assert line(sa_view)["status"] == "NOT_STARTED" and "not shown to platform users" in line(sa_view)["detail"]
    assert "1 of 1" not in str(sa_view) and sa_view["liveEligible"] is False
    summary = esvc.readiness_summary(db, on)
    assert summary["employers"][0]["liveEligible"] is False


def test_readiness_routes_org_and_super_admin(db):
    t = make_org(db)
    emp = new_mx_employee(db, t.org.id)
    save_mx_profile(db, emp, t.org.id)
    with http(db, principal(t.org.id)) as c:
        assert c.get(f"{ORG_BASE}/employees/{emp.id}/readiness").status_code == 422
        assert c.get(f"{ORG_BASE}/employees/{emp.id}/readiness", params={"on": "2026-03-01"}).status_code == 200
    with http(db, SUPER_ADMIN) as c:
        # ZP-PRIV: one employee's record is worker-level data — Super Admin is refused.
        r = c.get(f"{SA_BASE}/employees/{emp.id}", params={"organization_id": t.org.id, "on": "2026-03-01"})
        assert r.status_code == 403 and "RFC" not in r.text and "CURP" not in r.text
