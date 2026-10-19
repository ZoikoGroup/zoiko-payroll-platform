"""Brazil (ZP-BR-ENG-001) Phase 0 scaffolding — registry, hook contract,
fail-closed behaviour, and zero change for every other jurisdiction.

`app.*` is imported inside each test (never at module level) so collecting
this file cannot bind the app to the .env database before conftest's
in-memory SQLite fixture is in place."""

from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

SA_A = SimpleNamespace(id=961, organization_id=None, role="super_admin", is_active=True)
ORG_ADMIN = SimpleNamespace(id=962, organization_id=1, role="org_admin", is_active=True)
BASE = "/api/super-admin/compliance/brazil"

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


def _ctx(country="BR", **extra):
    from app.modules.payroll.engine.base import PayrollContext

    return PayrollContext(gross=Decimal("5000"), basic=Decimal("5000"), country=country, **extra)


# ── Registry (jurisdiction.py) ───────────────────────────────────────────────

def test_br_tax_schema_is_registered_schema_only():
    from app.core.jurisdiction import (
        ALL_COUNTRY_NAME_TO_CODE, CODE_TO_COUNTRY_NAME, JURISDICTION_TAX_SCHEMAS, REGISTRATION_COUNTRIES,
        get_jurisdiction_code,
    )

    schema = JURISDICTION_TAX_SCHEMAS["BR"]
    assert schema["currency"] == "BRL"
    assert [f["key"] for f in schema["fields"]] == ["cnpj", "cnae"]
    assert [f["key"] for f in schema["fields"] if f["primary"]] == ["cnpj"]
    assert CODE_TO_COUNTRY_NAME["BR"] == "Brazil"
    for name in ("Brazil", "brasil", "República Federativa do Brasil", "BR"):
        assert get_jurisdiction_code(name) == "BR"
    assert ALL_COUNTRY_NAME_TO_CODE["brazil"] == "BR"
    # Same rule as NL / SA / HK / MX: no self-service registration until G1–G8.
    assert "Brazil" not in REGISTRATION_COUNTRIES


def test_br_schema_patterns_are_format_only():
    import re

    from app.core.jurisdiction import JURISDICTION_TAX_SCHEMAS

    fields = {f["key"]: f for f in JURISDICTION_TAX_SCHEMAS["BR"]["fields"]}
    cnpj, cnae = re.compile(fields["cnpj"]["pattern"]), re.compile(fields["cnae"]["pattern"])
    assert cnpj.match(fields["cnpj"]["example"]) and cnae.match(fields["cnae"]["example"])
    assert cnpj.match("12ABC34501DE35")              # alphanumeric CNPJ format (from July 2026)
    assert not cnpj.match("12ABC34501DEAB")          # check digits are always numeric
    assert not cnpj.match("1122233300018")           # 13 characters
    assert not cnae.match("620150")                  # 6 digits


def test_service_normalizes_brazil_names():
    from app.modules.payroll import service

    for name in ("Brazil", "brasil", "BR"):
        assert service._normalize_country(name) == "BR"


def test_br_not_in_enterprise_supported_countries():
    from app.modules.payroll.enterprise.service import SUPPORTED_COUNTRY_CODES

    assert "BR" not in SUPPORTED_COUNTRY_CODES


def test_tax_schema_endpoint_lists_brazil(db):
    with _http(db, None) as c:
        r = c.get("/api/jurisdictions/tax-schemas")
    assert r.status_code == 200
    assert {"code": "BR", "name": "Brazil"} in r.json()["countries"]


def test_currency_maps():
    from app.modules.payroll import service

    assert service._get_currency_code("BR") == "BRL"
    assert service._get_currency_symbol("BR") == "R$"
    assert service._get_currency_code("NL") == "EUR" and service._get_currency_symbol("NL") == "€"
    assert service._get_currency_code("US") == "USD"


# ── Evidence register / content identifiers ──────────────────────────────────

def test_content_identifiers_and_evidence_register():
    from app.modules.payroll.engine.countries import brazil_content as c

    assert c.SPEC == "ZP-BR-ENG-001 v1.0"
    assert c.SOURCE_CODES == tuple(f"S{i}" for i in range(1, 21))
    assert all(title for _, title in c.SOURCE_REFERENCES)
    assert c.PACK_STATUS == "Draft"
    assert c.BR_2026 == ("BR-PAYROLL-2026", date(2026, 1, 1), date(2026, 12, 31))
    assert [g for g, _ in c.GATES] == [f"G{i}" for i in range(1, 9)]


# ── Engine dispatch and fail-closed calculation ─────────────────────────────

def test_blocked_error_is_the_handled_compliance_error():
    from app.modules.payroll.engine.countries.brazil import BrazilCalculationBlockedError
    from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError

    err = BrazilCalculationBlockedError("BR_X", "reason", 7)
    assert isinstance(err, MissingComplianceConfigurationError)
    assert (err.key, err.country, err.organization_id, err.reason) == ("BR_X", "BR", 7, "reason")


def test_standard_dispatches_br_to_brazil_calculator_not_generic():
    from app.modules.payroll.engine import standard
    from app.modules.payroll.engine.countries import brazil

    assert standard._COUNTRY_CALC["BR"] is brazil.calculate
    assert standard._COUNTRY_CALC["BR"] is not standard._calc_generic


def test_br_calculation_blocks_in_every_mode():
    """Even with every employer input supplied, no Brazilian payroll is
    calculated at Phase 0 — the draft engine is unreachable."""
    from app.modules.payroll.engine.countries.brazil import BrazilCalculationBlockedError
    from app.modules.payroll.engine.resolver import calculate_payroll

    inputs = {"brazil_inputs": {"rat_pct": "2", "fap_factor": "1.0", "third_party_pct": "5.8"}}
    for mode in ("standard", "enterprise"):
        with pytest.raises(BrazilCalculationBlockedError) as exc:
            calculate_payroll(_ctx(**inputs), mode)
        assert exc.value.key == "BR_ENGINE_NOT_CERTIFIED"
    with pytest.raises(BrazilCalculationBlockedError) as exc:
        calculate_payroll(_ctx(), "simple")
    assert exc.value.key == "BR_SIMPLE_MODE_UNSUPPORTED"


def test_brazil_calculator_ignores_other_countries():
    from app.modules.payroll.engine.countries import brazil

    assert brazil.calculate(_ctx(country="US")) == {}


def test_br_context_and_result_fields_default_to_empty():
    from app.modules.payroll.engine.base import PayrollResult

    ctx = _ctx(country="US")
    assert ctx.brazil_inputs == {} and ctx.brazil_is_apprentice is False
    for name in ("brazil_statutory_profile", "brazil_establishment", "brazil_employer_profile",
                 "brazil_organization_id"):
        assert getattr(ctx, name) is None, name
    assert PayrollResult.__dataclass_fields__["br_result"].default is None


def test_brazil_inputs_reach_the_context():
    import inspect

    from app.modules.payroll.engine.resolver import build_context_from_employee

    assert "brazil_inputs" in inspect.signature(build_context_from_employee).parameters


def test_other_countries_still_calculate():
    from app.modules.payroll.engine.resolver import calculate_payroll

    result = calculate_payroll(_ctx(country="US"), "standard")
    assert result.br_result is None
    assert result.br_inss_employee == Decimal("0")


# ── jurisdiction_hooks contract ─────────────────────────────────────────────

def test_br_hook_module_registered_with_full_contract():
    from app.modules.payroll import brazil_service, jurisdiction_hooks

    assert jurisdiction_hooks._MODULES["BR"] == "app.modules.payroll.brazil_service"
    assert set(brazil_service.JURISDICTION_HOOKS) == _HOOK_KEYS
    for name in _HOOK_KEYS:
        assert callable(jurisdiction_hooks.get("BR", name)), name


def test_other_hook_modules_unchanged():
    """Only BR was added; every other module mapping is exactly as before.
    (Merging main brings MX — this test must then list it too.)"""
    from app.modules.payroll import jurisdiction_hooks

    others = {k: v for k, v in jurisdiction_hooks._MODULES.items() if k != "BR"}
    assert others.get("HK") == "app.modules.payroll.hong_kong_service"
    assert others.get("SA") == "app.modules.payroll.saudi_arabia_service"
    assert others.get("NL") == "app.modules.payroll.netherlands_service"


def test_activation_and_template_refusals(db):
    from app.modules.payroll import jurisdiction_hooks

    pack = SimpleNamespace(jurisdiction_country="BR", pack_type="tax")
    assert "refused" in jurisdiction_hooks.call("BR", "pack_activation_refusal", db, pack)
    assert "refused" in jurisdiction_hooks.call("BR", "template_activation_refusal", db, pack, 1)
    assert jurisdiction_hooks.call("BR", "statutory_editors", db, pack) == set()


def test_calc_inputs_and_run_approval_block(db):
    from app.modules.payroll import jurisdiction_hooks
    from app.modules.payroll.engine.countries.brazil import BrazilCalculationBlockedError
    from app.modules.payroll.models import PayrollStatus

    employee = SimpleNamespace(organization_id=5, country_code="BR")
    with pytest.raises(BrazilCalculationBlockedError):
        jurisdiction_hooks.call("BR", "calc_inputs", db, None, employee, None, as_of=date(2026, 2, 1))
    run = SimpleNamespace(organization_id=5)
    for status in (PayrollStatus.APPROVED, PayrollStatus.AUTHORIZED, PayrollStatus.PAID):
        with pytest.raises(BrazilCalculationBlockedError):
            jurisdiction_hooks.call("BR", "before_run_transition", db, run, status, 1)
    for status in (PayrollStatus.DRAFT, PayrollStatus.REVIEW):    # moving back is never blocked
        assert jurisdiction_hooks.call("BR", "before_run_transition", db, run, status, 1) is None


def test_profile_hooks_refuse_brazilian_profiles(db):
    from app.modules.payroll import jurisdiction_hooks

    assert jurisdiction_hooks.call("BR", "statutory_profile_errors", SimpleNamespace())
    assert jurisdiction_hooks.call("BR", "statutory_profile_values", db, None, None, None) == {}
    assert jurisdiction_hooks.call("BR", "payslip_hold_view", SimpleNamespace()) is None
    assert jurisdiction_hooks.call("BR", "pack_holidays", db, 2026) == []
    assert jurisdiction_hooks.call("BR", "payment_treatment", db, 1, None, []) == {}


def test_registry_cannot_open_before_gates(db):
    from app.core.exceptions import BadRequestException
    from app.modules.billing.models import JurisdictionServiceRegistry
    from app.modules.payroll import jurisdiction_hooks

    db.add(JurisdictionServiceRegistry(country="BR", availability="PLANNED"))
    db.commit()
    with pytest.raises(BadRequestException):
        jurisdiction_hooks.call("BR", "service_registry_transition", db, "AVAILABLE", "go live", actor_id=1)
    row = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == "BR").one()
    assert row.availability == "PLANNED"


def test_retention_settings_never_break_other_countries_reports(db):
    """retention_service._report_country asks every registered module for its
    settings on each report download — Brazil must answer, not raise."""
    from app.modules.payroll import retention_service

    cfg = retention_service.settings("BR")
    assert cfg.country == "BR" and cfg.categories == ()
    assert retention_service._report_country(SimpleNamespace(jurisdiction_country="US", report_type="US_W2")) is None
    assert retention_service._report_country(SimpleNamespace(jurisdiction_country="BR", report_type="X")) == "BR"
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
    assert body["jurisdiction"] == "BR" and body["available"] is False and body["phase"] == 0
    assert [g["gate"] for g in body["gates"]] == [f"G{i}" for i in range(1, 9)]
    assert {g["state"] for g in body["gates"]} == {"OPEN"}


def test_shared_statutory_summary_route_serves_brazil(db):
    with _http(db, SA_A) as c:
        r = c.get("/api/super-admin/compliance/jurisdictions/BR/statutory-summary")
    assert r.status_code == 200 and r.json()["jurisdiction"] == "BR"
