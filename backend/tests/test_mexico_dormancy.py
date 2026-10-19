"""Mexico Phase 4a — dormancy. Merging to main deploys to production, so with
MX_TENANT_ONBOARDING_ENABLED off (the default, unset in production):

  * every /api/payroll/mexico/... organisation route refuses;
  * no organisation can become Mexican — not through Organization.country
    (org admin or Super Admin), not through the payroll company
    jurisdiction, not through the Organization.country back-fill;
  * sign-up and MX employee creation keep refusing Mexico;
  * nothing changes for any other country.

With the flag on, the organisation API still admits only Mexican
organisations. SYNTHETIC data, in-memory SQLite."""

from datetime import date
from decimal import Decimal
import pytest

from tests._mx_employer_helpers import ORG_BASE, SUPER_ADMIN, enable_mx_onboarding, http, make_org, principal

ORG_ROUTES = [  # every route on mexico_org_router, one call each (ids need not exist: the guard answers first)
    ("GET", "/employers"), ("POST", "/employers"), ("GET", "/employers/1"), ("POST", "/employers/1/versions"),
    ("POST", "/employers/1/establishments"), ("PUT", "/establishments/1/deactivate"),
    ("POST", "/employers/1/imss-registrations"), ("PUT", "/imss-registrations/1/infonavit"),
    ("PUT", "/imss-registrations/1/close"), ("POST", "/imss-registrations/1/risk-premiums"),
    ("PUT", "/risk-premiums/1/approve"), ("POST", "/employers/1/isn-registrations"), ("PUT", "/isn-registrations/1/close"),
    ("POST", "/employers/1/labor-policies"), ("PUT", "/labor-policies/1/activate"),
    ("GET", "/labor-policies/1/floor-check?on=2026-03-01"), ("GET", "/collective-agreements"),
    ("POST", "/employers/1/credentials"), ("PUT", "/credentials/1/revoke"), ("POST", "/credentials/1/certificate"),
    ("GET", "/readiness?on=2026-03-01"),
    # Phase 4b employee routes — dormant the same way
    ("GET", "/employees/1"), ("GET", "/employees/1/readiness?on=2026-03-01"),
    ("POST", "/employees/1/infonavit-notices"),
    # Phase 6 run routes — dormant the same way
    ("GET", "/runs/1/preflight"), ("POST", "/runs/1/preflight/1/acknowledge"), ("GET", "/runs/1/status"),
    ("POST", "/runs/1/reset"), ("GET", "/employees/1/hours"), ("POST", "/employees/1/hours"),
    ("POST", "/hours/1/approve"), ("POST", "/employees/1/opening-balances"), ("POST", "/opening-balances/1/approve"),
    # Phase 7 CFDI routes — dormant the same way
    ("GET", "/runs/1/cfdi"), ("POST", "/runs/1/cfdi/generate"), ("POST", "/cfdi/outbox/process"),
    ("GET", "/cfdi/documents/1"), ("POST", "/cfdi/documents/1/status-query"),
    ("POST", "/cfdi/documents/1/confirm-retry"), ("POST", "/cfdi/documents/1/cancel"), ("POST", "/cfdi/reconcile"),
    ("GET", "/cfdi/cancellation-reasons"),
]


def _call(c, method, path):
    kwargs = {"json": {}} if method in ("POST", "PUT") and not path.endswith("/certificate") else {}
    if path.endswith("/certificate"):
        kwargs = {"content": b"\x30\x00", "headers": {"Content-Type": "application/octet-stream"}}
    return c.request(method, f"{ORG_BASE}{path}", **kwargs)


def test_the_flag_defaults_off():
    from app.config import Settings

    assert Settings.model_fields["MX_TENANT_ONBOARDING_ENABLED"].default is False


def test_every_route_is_listed():
    """ORG_ROUTES covers every (method, path) mounted on mexico_org_router."""
    import re

    from app.main import app

    def shape(path):
        return re.sub(r"\{[a-z_]+\}|(?<=/)\d+(?=/|$)", "{id}", path.split("?")[0])

    mounted = {(m, shape(r.path)) for r in app.routes if getattr(r, "path", "").startswith(ORG_BASE + "/")
               for m in r.methods if m != "HEAD"}
    assert mounted == {(m, shape(ORG_BASE + p)) for m, p in ORG_ROUTES}


@pytest.mark.parametrize("method,path", ORG_ROUTES)
def test_flag_off_every_org_route_refuses_even_for_a_mexican_org(db, method, path):
    t = make_org(db)                                            # payroll jurisdiction MX
    for role in ("org_admin", "payroll_admin"):
        with http(db, principal(t.org.id, role=role)) as c:
            r = _call(c, method, path)
        assert r.status_code == 403 and "not open for onboarding" in r.json()["message"], (role, r.text)


def test_flag_off_writes_nothing(db):
    from app.modules.payroll.models import PayrollMxEmployerProfile

    t = make_org(db)
    with http(db, principal(t.org.id)) as c:
        c.post(f"{ORG_BASE}/employers", json={"rfc": "ABC010101AB1"})
    assert db.query(PayrollMxEmployerProfile).count() == 0


def test_flag_on_admits_a_mexican_org_and_refuses_any_other(db, monkeypatch):
    enable_mx_onboarding(monkeypatch)
    mx, nl, none = make_org(db), make_org(db, name="NL", code="NLX", country="NL"), make_org(db, name="N", code="NONE", country=None)
    with http(db, principal(mx.org.id)) as c:
        assert c.get(f"{ORG_BASE}/employers").status_code == 200
    for other in (nl, none):
        with http(db, principal(other.org.id, user_id=880)) as c:
            r = c.get(f"{ORG_BASE}/employers")
        assert r.status_code == 403 and "only available to organisations whose payroll jurisdiction is Mexico" in r.text


def test_flag_on_super_admin_and_employee_still_refused(db, monkeypatch):
    enable_mx_onboarding(monkeypatch)
    t = make_org(db)
    with http(db, SUPER_ADMIN) as c:
        assert c.get(f"{ORG_BASE}/employers").status_code == 403
    with http(db, principal(t.org.id, role="employee")) as c:
        assert c.get(f"{ORG_BASE}/employers").status_code == 403


# ── Organization.country → Mexico (org admin and Super Admin) ─────────────

@pytest.mark.parametrize("value", ["Mexico", "MX", "méxico"])
def test_flag_off_organization_country_cannot_become_mexico(db, value):
    from app.modules.payroll.engine.tax_resolver import get_jurisdiction_change_block_reason

    assert "not open for onboarding" in get_jurisdiction_change_block_reason(db, "India", value)
    assert "not open for onboarding" in get_jurisdiction_change_block_reason(db, None, value)


def test_mexico_branch_does_not_touch_other_changes(db):
    from app.modules.payroll.engine.tax_resolver import get_jurisdiction_change_block_reason

    assert get_jurisdiction_change_block_reason(db, "Mexico", "Mexico") is None        # already Mexican: unchanged
    for old, new in (("India", "United States"), ("India", "Germany"), (None, "France"), ("Mexico", "India")):
        assert get_jurisdiction_change_block_reason(db, old, new) is None, (old, new)


def test_singapore_gate_unchanged_by_the_mexico_branch(db):
    """The registry-gated countries keep their own answer (none of these is
    PLANNED-free on an empty DB, so each must still refuse with ITS reason)."""
    from app.modules.payroll.engine.tax_resolver import get_jurisdiction_change_block_reason

    for country in ("Singapore", "Hong Kong", "Netherlands"):
        reason = get_jurisdiction_change_block_reason(db, "India", country)
        assert reason is None or "not open for onboarding" not in reason, country


def test_organization_update_routes_refuse_mexico(db):
    from app.modules.organizations.models import Organization

    t = make_org(db, country=None)
    with http(db, principal(t.org.id)) as c:
        r = c.put("/api/organizations/me", json={"country": "Mexico"})
    assert r.status_code == 400 and "not open for onboarding" in r.text
    assert db.get(Organization, t.org.id).country != "Mexico"


def test_flag_on_organization_country_may_become_mexico(db, monkeypatch):
    from app.modules.payroll.engine.tax_resolver import get_jurisdiction_change_block_reason

    enable_mx_onboarding(monkeypatch)
    assert get_jurisdiction_change_block_reason(db, "India", "Mexico") is None


# ── payroll company jurisdiction and the back-fill ────────────────────────

def _company(db, org_id, value):
    from app.modules.payroll import service
    from app.modules.payroll.schemas import CompanyDetailsUpdate

    return service.update_company_details(db, org_id, CompanyDetailsUpdate(jurisdictionCountry=value))


@pytest.mark.parametrize("value", ["MX", "Mexico"])
def test_flag_off_company_jurisdiction_cannot_become_mexico(db, value):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    t = make_org(db, country=None)
    service.get_company_details(db, t.org.id)
    with pytest.raises(BadRequestException, match="not open for onboarding"):
        _company(db, t.org.id, value)
    assert (service.get_company_details(db, t.org.id).jurisdiction_country or "") not in ("MX", "Mexico")


def test_company_jurisdiction_other_countries_and_the_lock_unchanged(db):
    from fastapi import HTTPException

    from app.modules.payroll import service

    t = make_org(db, country=None)
    service.get_company_details(db, t.org.id)
    assert _company(db, t.org.id, "NL").jurisdiction_country == "NL"           # other countries: unchanged
    with pytest.raises(HTTPException) as exc:                                    # the lock still answers first
        _company(db, t.org.id, "MX")
    assert exc.value.status_code == 423


def test_flag_on_company_jurisdiction_may_become_mexico(db, monkeypatch):
    enable_mx_onboarding(monkeypatch)
    t = make_org(db, country=None)
    assert _company(db, t.org.id, "MX").jurisdiction_country == "MX"


def test_flag_off_backfill_never_makes_an_org_mexican(db):
    from app.modules.organizations.models import Organization
    from app.modules.payroll import service

    t = make_org(db, country=None)
    db.get(Organization, t.org.id).country = "Mexico"                         # e.g. set before Phase 4a
    db.commit()
    assert (service.get_company_details(db, t.org.id).jurisdiction_country or "") not in ("MX", "Mexico")


def test_backfill_for_other_countries_unchanged(db):
    from app.modules.organizations.models import Organization
    from app.modules.payroll import service

    t = make_org(db, country=None)
    db.get(Organization, t.org.id).country = "Netherlands"
    db.commit()
    assert service.get_company_details(db, t.org.id).jurisdiction_country == "NL"


def test_an_org_already_mexican_keeps_its_jurisdiction(db):
    from app.modules.payroll import service

    t = make_org(db)                                                             # MX before Phase 4a
    assert service.get_company_details(db, t.org.id).jurisdiction_country == "MX"


# ── sign-up and employees keep refusing Mexico (pinned) ───────────────────

def test_signup_paths_refuse_mexico(db):
    from app.core.jurisdiction import REGISTRATION_COUNTRIES
    from app.modules.payroll.engine.tax_resolver import get_jurisdiction_onboarding_block_reason

    assert "Mexico" not in REGISTRATION_COUNTRIES and "MX" not in REGISTRATION_COUNTRIES
    assert get_jurisdiction_onboarding_block_reason(db, "Mexico") is not None


def test_mx_employee_creation_refused_with_the_unchanged_message_while_the_flag_is_off(db):
    """Phase 4b registers the Mexico strategy in a DORMANT map: with the flag
    off (production) creation is refused exactly as before 4b, and the
    "Supported: …" list every other country sees never names MX. (With the
    flag on, creation works — tests/test_mexico_employee_validation.py.)"""
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.employee_validation import _STRATEGIES
    from app.modules.payroll.schemas import EmployeeCreate

    t = make_org(db)
    fields = set(EmployeeCreate.model_fields)
    data = {k: v for k, v in {"name": "Probe", "employee_code": "MX-1", "country_code": "MX", "ctc": Decimal("1"),
                              "basic": Decimal("1"), "hra": Decimal("0"), "date_of_joining": date(2026, 1, 1),
                              "date_of_birth": date(1990, 1, 1), "pay_frequency": "Monthly",
                              "email": "probe@example.com"}.items() if k in fields}
    with pytest.raises(BadRequestException) as exc:
        service.create_employee(db, EmployeeCreate(**data), t.org.id)
    assert exc.value.message == f"Unsupported country code 'MX'. Supported: {', '.join(_STRATEGIES)}."
    assert "MX" not in _STRATEGIES


def test_dormancy_helper_never_treats_blank_as_mexico():
    from app.modules.payroll import mexico_dormancy as d

    assert not d.is_mexico(None) and not d.is_mexico("") and not d.is_mexico("India")
    assert d.is_mexico("MX") and d.is_mexico("Mexico") and d.is_mexico("méxico")
    assert d.entering_mexico_refusal("", "India") is None


# ── pin: the 4a branch in tax_resolver cannot change any other country ────

@pytest.mark.parametrize("flag", [False, True])
def test_jurisdiction_change_gate_is_identical_for_every_non_mexican_pair(db, monkeypatch, flag):
    """get_jurisdiction_change_block_reason with the Mexico branch removed
    must answer exactly as it does with it, for every pair of non-Mexican
    registration countries (names and codes) and blank — so Phase 4a can only
    ever change an answer whose new country is Mexico."""
    from app.core.jurisdiction import REGISTRATION_COUNTRIES, get_jurisdiction_code
    from app.modules.payroll import mexico_dormancy
    from app.modules.payroll.engine.tax_resolver import get_jurisdiction_change_block_reason

    if flag:
        enable_mx_onboarding(monkeypatch)
    countries = [c for c in REGISTRATION_COUNTRIES if get_jurisdiction_code(c) != "MX"]
    values = [None, ""] + countries + [get_jurisdiction_code(c) for c in countries if get_jurisdiction_code(c)]
    with_branch = {(o, n): get_jurisdiction_change_block_reason(db, o, n) for o in values for n in values}
    monkeypatch.setattr(mexico_dormancy, "entering_mexico_refusal", lambda old, new: None)
    without_branch = {(o, n): get_jurisdiction_change_block_reason(db, o, n) for o in values for n in values}
    assert with_branch == without_branch
    assert len(with_branch) > 100


def test_the_mexico_branch_only_fires_for_a_change_into_mexico(db, monkeypatch):
    from app.modules.payroll import mexico_dormancy
    from app.modules.payroll.engine.tax_resolver import get_jurisdiction_change_block_reason

    calls = []
    real = mexico_dormancy.entering_mexico_refusal
    monkeypatch.setattr(mexico_dormancy, "entering_mexico_refusal",
                        lambda old, new: calls.append((old, new)) or real(old, new))
    assert get_jurisdiction_change_block_reason(db, "India", "Germany") is None
    assert get_jurisdiction_change_block_reason(db, "India", "Mexico") == mexico_dormancy.DORMANT_MESSAGE
    assert calls == [("India", "Germany"), ("India", "Mexico")]
