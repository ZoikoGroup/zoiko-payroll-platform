"""United Arab Emirates (ZP-AE-ENG-001): the simplified, ordinary-country scaffold.

The UAE has no dormancy module, no four-eyes service, no registry-row
requirement and no extra gates. Registration opens exactly like Jamaica's:
once an Active canonical pack with rates exists. The calculator is registered
in the standard dispatcher so it can never fall through to the generic one.
Synthetic data only; app modules are imported inside tests (DB-binding hazard).
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

AE_IBAN = "AE070331234567890123456"  # privacy-scan: allow (ISO 13616 registry example)
AE_IBAN_BAD_CHECK = AE_IBAN[:-1] + "7"
BE_IBAN = "BE68539007547034"  # privacy-scan: allow

ALIASES = ["United Arab Emirates", "united arab emirates", " UNITED ARAB EMIRATES ", "The United Arab Emirates",
           "UAE", "uae", "U.A.E.", "u.a.e", "The UAE", "Emirates", "AE"]


def _ae_pack(db, status="Draft", pack_id="AE-TEST"):
    from app.modules.payroll.models import JurisdictionPack

    pack = JurisdictionPack(pack_id=pack_id, jurisdiction_country="AE", pack_type="tax", version="1.0",
                            status=status, effective_from=date(2026, 1, 1))
    db.add(pack)
    db.commit()
    db.refresh(pack)
    return pack


def test_every_alias_resolves_to_ae_and_registration_lists_it():
    from app.core.jurisdiction import REGISTRATION_COUNTRIES, get_jurisdiction_code

    for value in ALIASES:
        assert get_jurisdiction_code(value) == "AE"
    assert "United Arab Emirates" in REGISTRATION_COUNTRIES


def test_bare_ae_and_english_words_are_not_aliases():
    from app.core.jurisdiction import ALL_COUNTRY_NAME_TO_CODE

    assert "ae" not in ALL_COUNTRY_NAME_TO_CODE
    assert "are" not in ALL_COUNTRY_NAME_TO_CODE


@pytest.mark.parametrize("value", ["United Arab Emirates", "UAE", "Emirates"])
def test_payroll_normaliser_uses_the_alias_path(value):
    from app.core.jurisdiction import ALL_COUNTRY_NAME_TO_CODE
    from app.modules.payroll.service import _normalize_country

    assert ALL_COUNTRY_NAME_TO_CODE[value.lower()] == "AE"
    assert _normalize_country(value) == "AE"


def test_country_name_and_schema():
    from app.core.jurisdiction import ALL_CODE_TO_COUNTRY_NAME, JURISDICTION_TAX_SCHEMAS, validate_tax_identifiers

    assert ALL_CODE_TO_COUNTRY_NAME["AE"] == "United Arab Emirates"
    schema = JURISDICTION_TAX_SCHEMAS["AE"]
    assert schema["label"] == "MOHRE establishment ID" and schema["currency"] == "AED"
    fields = {f["key"]: f for f in schema["fields"]}
    assert list(fields) == ["mohre_establishment_id", "gpssa_employer_number"]
    assert fields["mohre_establishment_id"]["primary"] is True and fields["gpssa_employer_number"]["primary"] is False
    examples = {k: f["example"] for k, f in fields.items()}
    assert validate_tax_identifiers("AE", examples) == (examples, [])
    assert validate_tax_identifiers("AE", {"mohre_establishment_id": "!"})[1]


def test_super_admin_lists_the_uae(db):
    from app.modules.super_admin.service import list_known_jurisdictions

    codes = {j["code"]: j["name"] for j in list_known_jurisdictions(db)}
    assert codes["AE"] == "United Arab Emirates"


# ── no P1/P2 gates remain ──────────────────────────────────────────────────
def test_no_gate_modules_or_hooks_exist():
    import importlib.util

    from app.modules.payroll import jurisdiction_hooks

    for module in ("app.modules.payroll.uae_service", "app.modules.payroll.uae_dormancy",
                   "scripts.seed_uae_registry"):
        spec = importlib.util.find_spec(module) if "." in module else None
        if module.startswith("scripts."):
            from pathlib import Path

            assert not (Path(__file__).resolve().parents[1] / "scripts" / "seed_uae_registry.py").exists()
        else:
            assert spec is None, module
    assert not jurisdiction_hooks.has_module("AE")


def test_no_uae_governance_or_dormancy_lists():
    from app.config import settings
    from app.modules.payroll import service
    from app.modules.payroll.employee_validation import _STRATEGIES, is_supported_employee_country
    from app.modules.payroll.engine.tax_resolver import _REGISTRY_ROW_REQUIRED_COUNTRIES

    for name in ("_APPROVER_NOT_ACTIVATOR_COUNTRIES", "_SELF_APPROVAL_REFUSED_COUNTRIES",
                 "_REFUSAL_AUDIT_COUNTRIES", "_PACK_TRANSITION_GRAPH_COUNTRIES",
                 "_REGISTRY_ROW_REQUIRED_COUNTRIES"):
        names = service.__dict__.get(name) if hasattr(service, name) else None
        if names is not None:
            assert "AE" not in names, name
    assert "AE" not in _REGISTRY_ROW_REQUIRED_COUNTRIES
    assert not hasattr(settings, "AE_TENANT_ONBOARDING_ENABLED")
    assert not hasattr(settings, "AE_CANARY_ORG_IDS")
    assert is_supported_employee_country("AE") is True
    assert _STRATEGIES["AE"].country_code == "AE"


def test_generic_pack_editing_and_approval_work_for_ae(db):
    from app.modules.payroll import service
    from app.modules.payroll.schemas import CanonicalContributionRateUpsert

    pack = _ae_pack(db)
    rate = service.upsert_canonical_contribution_rate(db, CanonicalContributionRateUpsert(
        jurisdictionPackId=pack.id, jurisdictionCountry="AE", componentKey="ae_probe", label="probe"), actor_id=1)
    assert rate.component_key == "ae_probe"
    service.set_jurisdiction_pack_approver(db, pack.id, actor_id=7) if hasattr(
        service, "set_jurisdiction_pack_approver") else None


# ── registration gate: an Active pack, like Jamaica ───────────────────────
def test_registration_requires_an_active_pack_with_rates(db):
    from app.modules.payroll.engine.tax_resolver import get_jurisdiction_change_block_reason, \
        get_jurisdiction_onboarding_block_reason
    from app.modules.payroll.models import ContributionRate

    assert get_jurisdiction_onboarding_block_reason(db, "United Arab Emirates")
    assert get_jurisdiction_change_block_reason(db, "India", "UAE") is None  # no extra AE gate
    draft = _ae_pack(db)
    db.add(ContributionRate(organization_id=None, jurisdiction_country="AE", jurisdiction_pack_id=draft.id,
                            component_key="ae_probe", label="probe", employee_share="5%", employer_share="15%",
                            total="20%", employee_rate_pct=Decimal("0.05"), employer_rate_pct=Decimal("0.15")))
    db.commit()
    assert get_jurisdiction_onboarding_block_reason(db, "UAE")
    active = _ae_pack(db, status="Active", pack_id="AE-ACTIVE")
    db.add(ContributionRate(organization_id=None, jurisdiction_country="AE", jurisdiction_pack_id=active.id,
                            component_key="ae_probe", label="probe", employee_share="5%", employer_share="15%",
                            total="20%", employee_rate_pct=Decimal("0.05"), employer_rate_pct=Decimal("0.15")))
    db.commit()
    assert get_jurisdiction_onboarding_block_reason(db, "UAE") is None


# ── calculator dispatch ────────────────────────────────────────────────────
def test_uae_is_registered_and_never_generic():
    from app.modules.payroll.engine import standard
    from app.modules.payroll.engine.countries import uae

    assert standard._COUNTRY_CALC["AE"] is uae.calculate
    assert standard._COUNTRY_CALC["AE"] is not standard._calc_generic


def test_simple_mode_is_blocked(monkeypatch):
    from app.modules.payroll.engine import standard
    from app.modules.payroll.engine.base import PayrollContext
    from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError
    from app.modules.payroll.engine.resolver import calculate_payroll

    generic_calls = []
    monkeypatch.setattr(standard, "_calc_generic", lambda ctx: generic_calls.append(ctx) or {})
    with pytest.raises(MissingComplianceConfigurationError) as raised:
        calculate_payroll(PayrollContext(country="AE", gross=Decimal("10000"), basic=Decimal("6000")), "simple")
    assert raised.value.key == "AE_SIMPLE_MODE_UNSUPPORTED"
    assert generic_calls == []


# ── employee fields (no duplicate tables) ──────────────────────────────────
def test_uae_employee_combination_rules():
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.employee_validation import AEEmployeeValidation as AE

    assert AE.validate({"nationality_category": "uae_national", "pension_scheme": "gpssa_law_57_2023",
                        "pension_contribution_salary": "15,000"}) == {
        "nationality_category": "UAE_NATIONAL", "pension_scheme": "GPSSA_LAW_57_2023",
        "pension_contribution_salary": "15000"}
    assert AE.validate({"nationality_category": "expatriate", "eos_regime": "traditional"}) == {
        "nationality_category": "EXPATRIATE", "eos_regime": "TRADITIONAL"}
    for bad in (
        {"nationality_category": "gcc_national"},
        {"nationality_category": "expatriate", "gcc_country": "OM", "eos_regime": "traditional"},
        {"nationality_category": "uae_national", "eos_regime": "traditional"},
        {"nationality_category": "expatriate", "eos_regime": "savings_scheme"},
        {"nationality_category": "uae_national", "pension_scheme": "none"},
    ):
        with pytest.raises(BadRequestException):
            AE.validate(bad)


def test_iban_and_emirates_id_validation():
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.employee_validation import AEEmployeeValidation as AE

    assert AE.validate({"iban": " ".join(AE_IBAN[i:i + 4] for i in range(0, len(AE_IBAN), 4)),
                        "nationality_category": "EXPATRIATE", "eos_regime": "TRADITIONAL"})["iban"] == AE_IBAN
    for bad in (AE_IBAN_BAD_CHECK, BE_IBAN):
        with pytest.raises(BadRequestException) as raised:
            AE.validate({"iban": bad})
        assert bad not in str(raised.value)
    assert AE.validate({"emirates_id": "784-1990-1234567-1", "nationality_category": "EXPATRIATE",
                        "eos_regime": "TRADITIONAL"})["emirates_id"] == "784199012345671"


def test_bank_routing_uses_the_uae_iban():
    from app.modules.payroll import bank_routing

    assert "AE" in bank_routing.ROUTING_COUNTRIES
    assert bank_routing.ROUTING_FIELDS["AE"] == [{"key": "iban", "label": "IBAN"}]
    assert bank_routing.BTF_ROUTING_LABEL["AE"] == "IBAN"
    assert bank_routing.PAYMENT_MODE_LABEL["AE"] == "WPS"
    employee = SimpleNamespace(country="AE", compliance_fields={"iban": AE_IBAN})
    assert bank_routing.btf_routing_value(employee, "AE") == AE_IBAN
