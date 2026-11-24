"""Spain (ZP-ES-ENG-001, docs/spain): the simplified, ordinary-country scaffold.

Spain has no dormancy module, no four-eyes service, no registry-row
requirement and no extra gates (owner decision D1/D2). Registration opens
exactly like Jamaica's and the United Arab Emirates': once an Active canonical
pack with rates exists. Synthetic data only; app modules are imported inside
tests (DB-binding hazard).
"""
from datetime import date
from decimal import Decimal

import pytest

ALIASES = ["Spain", "spain", " SPAIN ", "España", "españa", "Espana", "Kingdom of Spain", "Reino de España", "ES"]


def _es_pack(db, status="Draft", pack_id="ES-TEST"):
    from app.modules.payroll.models import JurisdictionPack

    pack = JurisdictionPack(pack_id=pack_id, jurisdiction_country="ES", pack_type="tax", version="1.0",
                            status=status, effective_from=date(2026, 1, 1))
    db.add(pack)
    db.commit()
    db.refresh(pack)
    return pack


def _probe_rate(db, pack):
    from app.modules.payroll.models import ContributionRate

    db.add(ContributionRate(organization_id=None, jurisdiction_country="ES", jurisdiction_pack_id=pack.id,
                            component_key="es_probe", label="probe", employee_share="4.7%", employer_share="23.6%",
                            total="28.3%", employee_rate_pct=Decimal("0.047"), employer_rate_pct=Decimal("0.236")))
    db.commit()


def test_every_alias_resolves_to_es_and_registration_lists_it():
    from app.core.jurisdiction import REGISTRATION_COUNTRIES, get_jurisdiction_code

    for value in ALIASES:
        assert get_jurisdiction_code(value) == "ES", value
    assert "Spain" in REGISTRATION_COUNTRIES


def test_bare_es_is_not_an_alias():
    """"es" is also a Brazilian state code (Espirito Santo); only the code
    "ES" itself resolves, through the tax-schema table."""
    from app.core.jurisdiction import ALL_COUNTRY_NAME_TO_CODE

    assert "es" not in ALL_COUNTRY_NAME_TO_CODE


@pytest.mark.parametrize("value", ["Spain", "España", "Kingdom of Spain"])
def test_payroll_normaliser_uses_the_alias_path(value):
    from app.core.jurisdiction import ALL_COUNTRY_NAME_TO_CODE
    from app.modules.payroll.service import _normalize_country

    assert ALL_COUNTRY_NAME_TO_CODE[value.lower()] == "ES"
    assert _normalize_country(value) == "ES"                      # never the truncated "SP"


def test_country_name_and_schema():
    from app.core.jurisdiction import ALL_CODE_TO_COUNTRY_NAME, JURISDICTION_TAX_SCHEMAS, validate_tax_identifiers

    assert ALL_CODE_TO_COUNTRY_NAME["ES"] == "Spain"
    schema = JURISDICTION_TAX_SCHEMAS["ES"]
    assert schema["label"] == "NIF" and schema["currency"] == "EUR"
    fields = {f["key"]: f for f in schema["fields"]}
    assert list(fields) == ["nif", "ccc"]
    assert fields["nif"]["primary"] is True and fields["ccc"]["primary"] is False
    examples = {k: f["example"] for k, f in fields.items()}
    assert validate_tax_identifiers("ES", examples) == (examples, [])
    assert validate_tax_identifiers("ES", {"nif": "B123"})[1]                  # too short
    assert validate_tax_identifiers("ES", {"nif": "B1234567!"})[1]             # not alphanumeric


def test_super_admin_lists_spain(db):
    from app.modules.super_admin.service import list_known_jurisdictions

    codes = {j["code"]: j["name"] for j in list_known_jurisdictions(db)}
    assert codes["ES"] == "Spain"


# ── no gates (D1 / D2) ───────────────────────────────────────────────────────
def test_no_gate_modules_hooks_or_flags():
    import importlib.util

    from app.config import settings
    from app.modules.payroll import jurisdiction_hooks

    for module in ("app.modules.payroll.spain_service", "app.modules.payroll.spain_dormancy"):
        assert importlib.util.find_spec(module) is None, module
    assert not jurisdiction_hooks.has_module("ES")
    assert not hasattr(settings, "ES_TENANT_ONBOARDING_ENABLED")


def test_only_canonical_pack_only_never_a_governance_list():
    from app.modules.payroll import service
    from app.modules.payroll.engine.tax_resolver import _REGISTRY_ROW_REQUIRED_COUNTRIES

    assert "ES" in service._CANONICAL_PACK_ONLY_COUNTRIES
    for name in ("_APPROVER_NOT_ACTIVATOR_COUNTRIES", "_SELF_APPROVAL_REFUSED_COUNTRIES",
                 "_REFUSAL_AUDIT_COUNTRIES", "_PACK_TRANSITION_GRAPH_COUNTRIES"):
        names = getattr(service, name, None)
        if names is not None:
            assert "ES" not in names, name
    assert "ES" not in _REGISTRY_ROW_REQUIRED_COUNTRIES


def test_generic_pack_editing_works_for_es(db):
    from app.modules.payroll import service
    from app.modules.payroll.schemas import CanonicalContributionRateUpsert

    pack = _es_pack(db)
    rate = service.upsert_canonical_contribution_rate(db, CanonicalContributionRateUpsert(
        jurisdictionPackId=pack.id, jurisdictionCountry="ES", componentKey="es_probe", label="probe"), actor_id=1)
    assert rate.component_key == "es_probe"


# ── registration gate: an Active pack with rates, like Jamaica (D1) ──────────
def test_registration_requires_an_active_pack_with_rates(db):
    from app.modules.payroll.engine.tax_resolver import get_jurisdiction_change_block_reason, \
        get_jurisdiction_onboarding_block_reason

    assert get_jurisdiction_onboarding_block_reason(db, "Spain")                 # no pack at all
    assert get_jurisdiction_change_block_reason(db, "India", "Spain") is None    # no extra ES gate
    _probe_rate(db, _es_pack(db))
    assert get_jurisdiction_onboarding_block_reason(db, "España")                # a Draft pack is not enough
    _probe_rate(db, _es_pack(db, status="Active", pack_id="ES-ACTIVE"))
    assert get_jurisdiction_onboarding_block_reason(db, "Spain") is None
