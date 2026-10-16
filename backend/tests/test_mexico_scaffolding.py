"""Mexico (ZP-MX-ENG-001) Phase 0 scaffolding — registry, hook contract,
fail-closed behaviour, and zero change for every other jurisdiction.

`app.*` is imported inside each test (never at module level) so collecting
this file cannot bind the app to the .env database before conftest's
in-memory SQLite fixture is in place."""

from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

SA_A = SimpleNamespace(id=951, organization_id=None, role="super_admin", is_active=True)
ORG_ADMIN = SimpleNamespace(id=952, organization_id=1, role="org_admin", is_active=True)
BASE = "/api/super-admin/compliance/mexico"

_HOOK_KEYS = {
    "retention_settings", "service_registry_transition", "statutory_summary", "pack_activation_refusal",
    "statutory_editors", "template_activation_refusal", "calc_inputs", "payment_treatment",
    "before_run_transition", "pack_holidays", "statutory_profile_errors", "statutory_profile_values",
    "payslip_hold_view",
}


@contextmanager
def _http(db, principal):
    from tests.test_hong_kong_governance import _http as hk_http

    with hk_http(db, principal) as client:
        yield client


def _ctx(country="MX", **extra):
    from app.modules.payroll.engine.base import PayrollContext

    return PayrollContext(gross=Decimal("20000"), basic=Decimal("20000"), country=country, **extra)


# ── Registry (jurisdiction.py) ───────────────────────────────────────────────

def test_mx_tax_schema_is_registered_schema_only():
    from app.core.jurisdiction import (
        ALL_COUNTRY_NAME_TO_CODE, CODE_TO_COUNTRY_NAME, JURISDICTION_TAX_SCHEMAS, REGISTRATION_COUNTRIES,
        get_jurisdiction_code,
    )

    schema = JURISDICTION_TAX_SCHEMAS["MX"]
    assert schema["currency"] == "MXN"
    assert [f["key"] for f in schema["fields"]] == ["rfc", "registro_patronal"]
    assert [f["key"] for f in schema["fields"] if f["primary"]] == ["rfc"]
    assert CODE_TO_COUNTRY_NAME["MX"] == "Mexico"
    for name in ("Mexico", "méxico", "Estados Unidos Mexicanos"):
        assert get_jurisdiction_code(name) == "MX"
    assert ALL_COUNTRY_NAME_TO_CODE["mexico"] == "MX"
    # Phase 0 decision 1: no self-service registration until G1–G8.
    assert "Mexico" not in REGISTRATION_COUNTRIES


def test_mx_schema_patterns_are_format_only():
    import re

    from app.core.jurisdiction import JURISDICTION_TAX_SCHEMAS

    fields = {f["key"]: f for f in JURISDICTION_TAX_SCHEMAS["MX"]["fields"]}
    rfc, reg = re.compile(fields["rfc"]["pattern"]), re.compile(fields["registro_patronal"]["pattern"])
    assert rfc.match(fields["rfc"]["example"]) and reg.match(fields["registro_patronal"]["example"])
    assert rfc.match("ÑA&010101AB1")                 # Ñ and & are valid RFC letters
    assert not rfc.match("ABCD010101AB1")            # 13 chars = a person's RFC, not a legal entity's
    assert not reg.match("Y123456710")               # 10 chars
    assert not reg.match("Y12345671011")             # 12 chars


def test_mx_not_in_enterprise_supported_countries():
    from app.modules.payroll.enterprise.service import SUPPORTED_COUNTRY_CODES

    assert "MX" not in SUPPORTED_COUNTRY_CODES


def test_tax_schema_endpoint_lists_mexico(db):
    with _http(db, None) as c:
        r = c.get("/api/jurisdictions/tax-schemas")
    assert r.status_code == 200
    assert {"code": "MX", "name": "Mexico"} in r.json()["countries"]


def test_currency_maps():
    from app.modules.payroll import service

    assert service._get_currency_code("MX") == "MXN"
    assert service._get_currency_symbol("MX") == "MX$"
    assert service._get_currency_code("NL") == "EUR" and service._get_currency_symbol("NL") == "€"
    assert service._get_currency_code("US") == "USD"


# ── Evidence register / content skeleton ─────────────────────────────────────

def test_content_skeleton_declares_no_statutory_values():
    from app.modules.payroll.engine.countries import mexico_content as c

    assert c.SOURCE_CODES == tuple(f"S{i}" for i in range(1, 24))
    assert all(title for _, title in c.SOURCE_REFERENCES)
    assert c.PACK_STATUS == "Draft"
    assert c.MX_2026 == ("MX-PAYROLL-2026", date(2026, 1, 1), date(2026, 12, 31))
    assert c.MX_ISN_STATES_IN_SCOPE == ("CDMX",)
    assert [g for g, _ in c.GATES] == [f"G{i}" for i in range(1, 9)]
    # Phase 1 tooling names the parameter keys; every content table stays empty
    # until transcription from the saved official sources.
    assert all(k.startswith("mx_") for k in c.MX_PARAMETER_KEYS)
    assert c.MX_SCALAR_CONTENT == () and c.MX_ISR_TARIFFS == ()
    assert all(rt.startswith("MX_") for rt in (c.MX_ISR_TARIFF_RULE, c.MX_CEAV_BAND_RULE, c.MX_MIN_WAGE_RULE,
                                               c.MX_VACATION_DAYS_RULE, c.MX_WORKWEEK_RULE))


# ── Engine dispatch and fail-closed calculation ─────────────────────────────

def test_blocked_error_is_the_handled_compliance_error():
    from app.modules.payroll.engine.countries.mexico import MexicoCalculationBlockedError
    from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError

    err = MexicoCalculationBlockedError("MX_X", "reason", 7)
    assert isinstance(err, MissingComplianceConfigurationError)
    assert (err.key, err.country, err.organization_id, err.reason) == ("MX_X", "MX", 7, "reason")


def test_standard_dispatches_mx_to_mexico_calculator_not_generic():
    from app.modules.payroll.engine import standard
    from app.modules.payroll.engine.countries import mexico

    assert standard._COUNTRY_CALC["MX"] is mexico.calculate
    assert standard._COUNTRY_CALC["MX"] is not standard._calc_generic


def test_mx_calculation_blocks_in_every_mode():
    from app.modules.payroll.engine.countries.mexico import MexicoCalculationBlockedError
    from app.modules.payroll.engine.resolver import calculate_payroll

    for mode in ("standard", "enterprise"):
        with pytest.raises(MexicoCalculationBlockedError) as exc:
            calculate_payroll(_ctx(), mode)
        assert exc.value.key == "MX_ENGINE_NOT_IMPLEMENTED"
    with pytest.raises(MexicoCalculationBlockedError) as exc:
        calculate_payroll(_ctx(), "simple")
    assert exc.value.key == "MX_SIMPLE_MODE_UNSUPPORTED"


def test_mexico_calculator_ignores_other_countries():
    from app.modules.payroll.engine.countries import mexico

    assert mexico.calculate(_ctx(country="US")) == {}


def test_mx_context_and_result_fields_default_to_none():
    from app.modules.payroll.engine.base import PayrollResult

    ctx = _ctx(country="US")
    for name in ("mx_payroll_date", "mx_payment_period", "mx_profile", "mx_employer", "mx_registration",
                 "mx_risk_premium", "mx_sbc", "mx_infonavit_notices", "mx_isn_state_pack", "mx_classifications",
                 "mx_labor_policy", "mx_ytd", "mx_employee_id", "mx_organization_id"):
        assert getattr(ctx, name) is None, name
    assert PayrollResult.__dataclass_fields__["mx_result"].default is None


def test_mexico_inputs_reach_the_context():
    import inspect

    from app.modules.payroll.engine.resolver import build_context_from_employee

    assert "mexico_inputs" in inspect.signature(build_context_from_employee).parameters


def test_other_countries_still_calculate():
    from app.modules.payroll.engine.resolver import calculate_payroll

    result = calculate_payroll(_ctx(country="US"), "standard")
    assert result.mx_result is None


# ── jurisdiction_hooks contract ─────────────────────────────────────────────

def test_mx_hook_module_registered_with_full_contract():
    from app.modules.payroll import jurisdiction_hooks, mexico_service

    assert jurisdiction_hooks._MODULES["MX"] == "app.modules.payroll.mexico_service"
    # The 13 shared hooks, plus Mexico's optional Phase 2 approval gate.
    assert set(mexico_service.JURISDICTION_HOOKS) == _HOOK_KEYS | {"pack_approval_refusal"}
    for name in _HOOK_KEYS | {"pack_approval_refusal"}:
        assert callable(jurisdiction_hooks.get("MX", name)), name


def test_other_hook_modules_unchanged():
    from app.modules.payroll import jurisdiction_hooks

    assert jurisdiction_hooks._MODULES == {
        "HK": "app.modules.payroll.hong_kong_service",
        "SA": "app.modules.payroll.saudi_arabia_service",
        "NL": "app.modules.payroll.netherlands_service",
        "MX": "app.modules.payroll.mexico_service",
        # Brazil (ZP-BR-ENG-001) Phase 0, merged from venu — fail-closed module.
        "BR": "app.modules.payroll.brazil_service",
    }


def test_activation_and_template_refusals(db):
    from app.modules.payroll import jurisdiction_hooks
    from scripts.seed_mexico_canonical_packs import seed_mexico

    pack = seed_mexico(db, manifest={})["national"]                 # Draft, empty content
    assert "refused" in jurisdiction_hooks.call("MX", "pack_activation_refusal", db, pack)
    assert "refused" in jurisdiction_hooks.call("MX", "template_activation_refusal", db, pack, 1)
    assert jurisdiction_hooks.call("MX", "statutory_editors", db, pack) == set()


def test_calc_inputs_and_run_approval_block(db):
    from app.modules.payroll import jurisdiction_hooks
    from app.modules.payroll.engine.countries.mexico import MexicoCalculationBlockedError
    from app.modules.payroll.models import PayrollStatus

    employee = SimpleNamespace(organization_id=5, country_code="MX")
    with pytest.raises(MexicoCalculationBlockedError):
        jurisdiction_hooks.call("MX", "calc_inputs", db, None, employee, None, as_of=date(2026, 2, 1))
    run = SimpleNamespace(organization_id=5)
    for status in (PayrollStatus.APPROVED, PayrollStatus.AUTHORIZED, PayrollStatus.PAID):
        with pytest.raises(MexicoCalculationBlockedError):
            jurisdiction_hooks.call("MX", "before_run_transition", db, run, status, 1)
    for status in (PayrollStatus.DRAFT, PayrollStatus.REVIEW):    # moving back is never blocked
        assert jurisdiction_hooks.call("MX", "before_run_transition", db, run, status, 1) is None


def test_profile_hooks_are_phase_4b_and_other_hooks_stay_inert(db):
    """Phase 4b replaced the Phase 0 profile refusal with real validation
    (tests/test_mexico_statutory_profile.py); an empty profile has no errors."""
    from app.modules.payroll import jurisdiction_hooks

    assert jurisdiction_hooks.call("MX", "statutory_profile_errors", SimpleNamespace()) == []
    assert jurisdiction_hooks.call("MX", "payslip_hold_view", SimpleNamespace()) is None
    assert jurisdiction_hooks.call("MX", "pack_holidays", db, 2026) == []
    assert jurisdiction_hooks.call("MX", "payment_treatment", db, 1, None, []) == {}


def test_registry_cannot_open_before_gates(db):
    from app.core.exceptions import BadRequestException
    from app.modules.billing.models import JurisdictionServiceRegistry
    from app.modules.payroll import jurisdiction_hooks

    db.add(JurisdictionServiceRegistry(country="MX", availability="PLANNED"))
    db.commit()
    with pytest.raises(BadRequestException):
        jurisdiction_hooks.call("MX", "service_registry_transition", db, "AVAILABLE", "go live", actor_id=1)
    row = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == "MX").one()
    assert row.availability == "PLANNED"


def test_retention_settings_never_break_other_countries_reports(db):
    """retention_service._report_country asks every registered module for its
    settings on each report download — Mexico must answer, not raise."""
    from app.modules.payroll import retention_service

    cfg = retention_service.settings("MX")
    assert cfg.country == "MX" and cfg.categories == ()
    assert retention_service._report_country(SimpleNamespace(jurisdiction_country="US", report_type="US_W2")) is None
    assert retention_service._report_country(SimpleNamespace(jurisdiction_country="MX", report_type="X")) == "MX"
    assert retention_service._report_country(SimpleNamespace(jurisdiction_country="NL", report_type="NL_X")) == "NL"


# ── Super Admin router ──────────────────────────────────────────────────────

def test_readiness_route_is_super_admin_only(db):
    with _http(db, ORG_ADMIN) as c:
        assert c.get(f"{BASE}/readiness").status_code == 403


def test_readiness_route_reports_every_gate_open(db):
    with _http(db, SA_A) as c:
        r = c.get(f"{BASE}/readiness")
    assert r.status_code == 200
    body = r.json()
    assert body["jurisdiction"] == "MX" and body["available"] is False and body["phase"] == 4
    assert [g["gate"] for g in body["gates"]] == [f"G{i}" for i in range(1, 9)]
    assert {g["state"] for g in body["gates"]} == {"OPEN"}


def test_shared_statutory_summary_route_serves_mexico(db):
    with _http(db, SA_A) as c:
        r = c.get("/api/super-admin/compliance/jurisdictions/MX/statutory-summary")
    assert r.status_code == 200 and r.json()["jurisdiction"] == "MX"
