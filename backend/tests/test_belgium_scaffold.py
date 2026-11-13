"""Belgium (ZP-BE-ENG-001) Phase 1: fail-closed scaffold and jurisdiction registration.

Belgium is a known jurisdiction that can never calculate, can never reach the
generic calculator or simple mode, cannot be onboarded, and has no employees
unless dormancy / canary allows it. SYNTHETIC data, in-memory SQLite. App
modules are imported inside each test (collection-order DB-binding hazard)."""
from decimal import Decimal
from types import SimpleNamespace

import pytest

# ISO 13616 published example IBAN (not a real account).
BE_IBAN = "BE68539007547034"  # privacy-scan: allow
BE_IBAN_BAD_CHECK = BE_IBAN[:-1] + "5"
PL_IBAN = "PL61109010140000071219812874"  # privacy-scan: allow

ALIASES = ["Belgium", "belgium", " BELGIUM ", "Belgique", "België", "belgie", "Belgien", "Kingdom of Belgium",
           "Royaume de Belgique", "Koninkrijk België", "BEL", "BE"]
HOOK_NAMES = ("calc_inputs", "before_run_transition", "statutory_profile_errors", "statutory_profile_values",
              "pack_activation_refusal", "retention_settings", "service_registry_transition", "statutory_summary",
              "statutory_editors", "template_activation_refusal", "pack_holidays", "payment_treatment",
              "payslip_hold_view")
G21 = "Belgium: employee records cannot be deleted until Belgian statutory retention rules are approved (spec §15)."


def _be_pack(db, status="Draft", pack_type="tax", pack_id="BE-TEST"):
    from app.modules.payroll.models import JurisdictionPack

    pack = JurisdictionPack(pack_id=pack_id, jurisdiction_country="BE", pack_type=pack_type, version="1.0",
                            status=status)
    db.add(pack)
    db.commit()
    db.refresh(pack)
    return pack


def _registry_row(db, availability="PLANNED"):
    from app.modules.billing.models import JurisdictionServiceRegistry

    row = JurisdictionServiceRegistry(country="BE", availability=availability,
                                      payment_execution_responsibility="NOT_OFFERED",
                                      filing_responsibility="NOT_OFFERED", remittance_responsibility="NOT_OFFERED")
    db.add(row)
    db.commit()
    return row


# ── jurisdiction identity ──────────────────────────────────────────────────
@pytest.mark.parametrize("value", ALIASES)
def test_every_alias_resolves_to_be(value):
    from app.core.jurisdiction import REGISTRATION_COUNTRIES, get_jurisdiction_code

    assert get_jurisdiction_code(value) == "BE"
    assert "Belgium" not in REGISTRATION_COUNTRIES                    # never registrable while dormant


def test_bare_be_is_not_a_free_text_alias():
    # "be" is never an alias ("BE" is also a Swiss canton). The schema KEY "BE"
    # matches case-insensitively in get_jurisdiction_code for every country
    # (shared behaviour, e.g. "pl" -> PL), which Phase 1 does not change.
    from app.core.jurisdiction import ALL_COUNTRY_NAME_TO_CODE

    assert "be" not in ALL_COUNTRY_NAME_TO_CODE


@pytest.mark.parametrize("value", ["Belgium", "belgique", "België"])
def test_payroll_normaliser_uses_the_alias_path(value):
    from app.core.jurisdiction import ALL_COUNTRY_NAME_TO_CODE
    from app.modules.payroll.service import _normalize_country

    assert ALL_COUNTRY_NAME_TO_CODE[value.lower()] == "BE"           # resolved by alias, not [:2]
    assert _normalize_country(value) == "BE"


def test_country_name_and_schema():
    from app.core.jurisdiction import CODE_TO_COUNTRY_NAME, JURISDICTION_TAX_SCHEMAS, validate_tax_identifiers

    assert CODE_TO_COUNTRY_NAME["BE"] == "Belgium"
    schema = JURISDICTION_TAX_SCHEMAS["BE"]
    assert schema["label"] == "Enterprise number / ONSS number" and schema["currency"] == "EUR"
    fields = {f["key"]: f for f in schema["fields"]}
    assert list(fields) == ["enterprise_number", "onss_employer_number"]   # NISS is never an org field
    assert fields["enterprise_number"]["primary"] is True and fields["onss_employer_number"]["primary"] is False
    examples = {k: f["example"] for k, f in fields.items()}
    assert validate_tax_identifiers("BE", examples) == (examples, [])
    assert validate_tax_identifiers("BE", {"enterprise_number": "abc"})[1]


@pytest.mark.parametrize("canton", ["CH-BE", "BE"])
def test_swiss_canton_values_never_resolve_as_belgium(canton, monkeypatch):
    from datetime import date

    from app.core.jurisdiction import get_jurisdiction_code
    from app.modules.payroll import belgium_service, jurisdiction_hooks, service
    from app.modules.payroll.engine.countries.switzerland_content import CH_CANTONS
    from app.modules.payroll.schemas import EmployeeStatutoryProfileCreate
    from app.modules.payroll.switzerland_service import ch_statutory_profile_errors

    assert "CH-BE" in {code for code, _name in CH_CANTONS}              # Bern
    assert get_jurisdiction_code("CH-BE") is None
    assert service._normalize_country("CH") == "CH" and not jurisdiction_hooks.has_module("CH")
    called = []
    monkeypatch.setattr(belgium_service, "_be_statutory_profile_errors", lambda data: called.append(data) or ["x"])
    data = EmployeeStatutoryProfileCreate(effective_from=date(2026, 1, 1), ch_work_canton=canton,
                                          ch_residence_canton=canton)
    errors = ch_statutory_profile_errors(data)
    if canton == "CH-BE":
        assert errors == []
        service._validate_statutory_profile_fields("CH", data)            # the CH path, unchanged
    else:
        assert errors and all("CH-XX canton code" in e for e in errors)  # a bare "BE" is a malformed canton
    assert called == []                                                    # never the Belgium module


# ── fail-closed calculation dispatch ───────────────────────────────────────
# Block A3: standard / enterprise now run the Belgian engine, which still
# blocks (here: no pay date / no records) - never the generic calculator.
@pytest.mark.parametrize("mode, code", [("simple", "BE_SIMPLE_MODE_UNSUPPORTED"),
                                        ("standard", "BE_"), ("enterprise", "BE_")])
def test_every_calculation_mode_is_blocked_and_never_generic(mode, code, monkeypatch):
    from app.modules.payroll.engine import standard
    from app.modules.payroll.engine.base import PayrollContext
    from app.modules.payroll.engine.countries.belgium import BECalculationBlockedError
    from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError
    from app.modules.payroll.engine.resolver import calculate_payroll

    generic_calls = []
    monkeypatch.setattr(standard, "_calc_generic", lambda ctx: generic_calls.append(ctx) or {})
    with pytest.raises(BECalculationBlockedError) as raised:
        calculate_payroll(PayrollContext(gross=Decimal("4000"), basic=Decimal("4000"), country="BE"), mode)
    assert isinstance(raised.value, MissingComplianceConfigurationError)
    assert raised.value.key == code if mode == "simple" else raised.value.key.startswith(code)
    assert raised.value.key != "BE_ENGINE_NOT_BUILT"
    assert generic_calls == []


def test_belgium_is_registered_fail_closed():
    from app.modules.payroll.engine import standard
    from app.modules.payroll.engine.base import PayrollResult
    from app.modules.payroll.engine.countries import belgium
    from app.modules.payroll.engine.tax_resolver import _REGISTRY_ROW_REQUIRED_COUNTRIES

    assert standard._COUNTRY_CALC["BE"] is belgium.calculate
    assert standard._COUNTRY_CALC["BE"] is not standard._calc_generic
    assert "BE" in _REGISTRY_ROW_REQUIRED_COUNTRIES
    assert PayrollResult.__dataclass_fields__["be_result"].default is None


def test_shared_governance_tuples_include_belgium():
    from app.modules.payroll import service

    for name in ("_CANONICAL_PACK_ONLY_COUNTRIES", "_APPROVER_NOT_ACTIVATOR_COUNTRIES",
                 "_SELF_APPROVAL_REFUSED_COUNTRIES", "_REFUSAL_AUDIT_COUNTRIES", "_PACK_TRANSITION_GRAPH_COUNTRIES"):
        assert "BE" in getattr(service, name), name
    assert service._GATED_PACK_COUNTRY_NAMES["BE"] == "Belgium"


# ── onboarding and country-change gates ────────────────────────────────────
def test_onboarding_refused_without_registry_row(db):
    from app.modules.payroll.engine.tax_resolver import get_jurisdiction_onboarding_block_reason

    assert get_jurisdiction_onboarding_block_reason(db, "Belgium")


def test_onboarding_refused_with_planned_row(db):
    from app.modules.payroll.engine.tax_resolver import get_jurisdiction_onboarding_block_reason

    _registry_row(db)
    assert get_jurisdiction_onboarding_block_reason(db, "BE")


def test_onboarding_refused_with_planned_row_and_an_active_canonical_pack(db):
    from app.modules.payroll.engine.tax_resolver import get_jurisdiction_onboarding_block_reason
    from app.modules.payroll.models import ContributionRate

    _registry_row(db)
    pack = _be_pack(db, status="Active", pack_id="BE-ACTIVE")
    db.add(ContributionRate(organization_id=None, jurisdiction_country="BE", jurisdiction_pack_id=pack.id,
                            component_key="be_probe", label="probe [PENDING G1]", employee_share="—",
                            employer_share="—", total="—"))
    db.commit()
    assert get_jurisdiction_onboarding_block_reason(db, "Belgium")


def test_moving_an_existing_org_into_belgium_is_refused_while_dormant(db):
    from app.modules.payroll.belgium_dormancy import DORMANT_MESSAGE
    from app.modules.payroll.engine.tax_resolver import get_jurisdiction_change_block_reason

    assert get_jurisdiction_change_block_reason(db, "India", "Belgium") == DORMANT_MESSAGE
    assert get_jurisdiction_change_block_reason(db, None, "BE") == DORMANT_MESSAGE
    assert get_jurisdiction_change_block_reason(db, "Belgium", "Belgium") is None   # already Belgian


@pytest.mark.parametrize("value", ["BE", "Belgium"])
def test_company_jurisdiction_cannot_become_belgium(db, value):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.schemas import CompanyDetailsUpdate
    from tests._mx_employer_helpers import make_org

    t = make_org(db, name="BE Test Org", code="BETEST", country=None)
    service.get_company_details(db, t.org.id)
    with pytest.raises(BadRequestException, match="Belgium is not open"):
        service.update_company_details(db, t.org.id, CompanyDetailsUpdate(jurisdictionCountry=value))
    assert (service.get_company_details(db, t.org.id).jurisdiction_country or "") not in ("BE", "Belgium")


def test_backfill_never_makes_an_org_belgian(db):
    from app.modules.organizations.models import Organization
    from app.modules.payroll import service
    from tests._mx_employer_helpers import make_org

    t = make_org(db, name="BE Backfill Org", code="BEBACK", country=None)
    db.get(Organization, t.org.id).country = "Belgium"
    db.commit()
    assert (service.get_company_details(db, t.org.id).jurisdiction_country or "") not in ("BE", "Belgium")


def test_e2e_belgium_listed_in_tax_schemas_but_org_cannot_select_it(db):
    from app.modules.organizations.models import Organization
    from tests._mx_employer_helpers import http, make_org, principal

    _registry_row(db)                                                    # PLANNED, and dormant
    t = make_org(db, name="BE E2E Org", code="BEE2E", country=None)
    before = db.get(Organization, t.org.id).country
    with http(db, principal(t.org.id)) as c:
        listing = c.get("/api/jurisdictions/tax-schemas")
        assert listing.status_code == 200
        body = listing.json()
        assert {"code": "BE", "name": "Belgium"} in body["countries"] and "BE" in body["schemas"]
        r = c.put("/api/organizations/me", json={"country": "Belgium"})
    assert r.status_code == 400 and "not open for onboarding" in r.text
    db.expire_all()
    assert db.get(Organization, t.org.id).country == before


# ── employee validation (dormant) ──────────────────────────────────────────
def test_belgium_is_not_an_employee_country_while_dormant():
    from app.modules.payroll.employee_validation import _STRATEGIES, _dormant_strategy, is_supported_employee_country

    assert "BE" not in _STRATEGIES
    assert _dormant_strategy("BE") is None
    assert is_supported_employee_country("BE") is False


def test_flag_makes_belgium_an_employee_country(monkeypatch):
    from app.config import settings
    from app.modules.payroll.employee_validation import is_supported_employee_country

    monkeypatch.setattr(settings, "BE_TENANT_ONBOARDING_ENABLED", True)
    assert is_supported_employee_country("BE") is True


def test_canary_makes_belgium_an_employee_country(monkeypatch):
    from app.config import settings
    from app.modules.payroll.employee_validation import is_supported_employee_country

    monkeypatch.setattr(settings, "BE_CANARY_ORG_IDS", "4242")
    assert is_supported_employee_country("BE") is True


def test_dormant_strategy_never_uses_mexicos_flag(monkeypatch):
    from app.config import settings
    from app.modules.payroll.employee_validation import _dormant_strategy

    monkeypatch.setattr(settings, "MX_TENANT_ONBOARDING_ENABLED", True)
    assert _dormant_strategy("MX") is not None                           # Mexico's flag is really on
    assert _dormant_strategy("BE") is None                               # ...and Belgium stays dormant


@pytest.fixture
def be_strategy(monkeypatch):
    from app.config import settings
    from app.modules.payroll.employee_validation import BEEmployeeValidation, get_employee_validation_strategy

    monkeypatch.setattr(settings, "BE_TENANT_ONBOARDING_ENABLED", True)
    strategy = get_employee_validation_strategy("BE")
    assert strategy is BEEmployeeValidation
    return strategy


def test_belgian_employee_has_iban_only(be_strategy):
    spaced = " ".join(BE_IBAN.lower()[i:i + 4] for i in range(0, len(BE_IBAN), 4))
    assert be_strategy.validate({"iban": spaced}) == {"iban": BE_IBAN}
    assert be_strategy.validate({}) == {}
    assert set(be_strategy.FIELD_SPECS) == {"iban"}


@pytest.mark.parametrize("key", ["niss", "INSZ", "national_id", "rijksregisternummer", "tax_number"])
def test_niss_is_vault_only_and_never_echoed(be_strategy, key):
    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException) as raised:
        be_strategy.validate({key: "85073003328"})
    text = str(getattr(raised.value, "detail", None) or raised.value)
    assert "identifier vault" in text and "85073003328" not in text


@pytest.mark.parametrize("iban", [BE_IBAN_BAD_CHECK, PL_IBAN])
def test_invalid_belgian_iban_is_refused_without_echo(be_strategy, iban):
    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException) as raised:
        be_strategy.validate({"iban": iban})
    text = str(getattr(raised.value, "detail", None) or raised.value)
    assert "Belgian IBAN" in text and iban not in text


def test_bank_routing_uses_the_belgian_iban_over_sepa():
    from app.modules.payroll import bank_routing

    assert "BE" in bank_routing.ROUTING_COUNTRIES
    assert bank_routing.ROUTING_FIELDS["BE"] == [{"key": "iban", "label": "IBAN"}]
    assert bank_routing.BTF_ROUTING_LABEL["BE"] == "IBAN"
    assert bank_routing.PAYMENT_MODE_LABEL["BE"] == "SEPA"
    employee = SimpleNamespace(country="BE", compliance_fields={"iban": BE_IBAN})
    assert bank_routing.btf_routing_value(employee, "BE") == BE_IBAN


# ── jurisdiction hooks ─────────────────────────────────────────────────────
def test_all_13_hooks_resolve():
    from app.modules.payroll import belgium_service, jurisdiction_hooks, poland_service

    assert jurisdiction_hooks._MODULES["BE"] == "app.modules.payroll.belgium_service"
    assert set(belgium_service.JURISDICTION_HOOKS) == set(HOOK_NAMES) == set(poland_service.JURISDICTION_HOOKS)
    for name in HOOK_NAMES:
        assert callable(jurisdiction_hooks.get("BE", name)), name
    for optional in ("before_pack_status", "pack_approval_refusal", "evidence_review_refusal"):
        assert not jurisdiction_hooks.declares("BE", optional)


def test_type_a_hooks_fail_closed(db):
    from fastapi import HTTPException

    from app.core.exceptions import BadRequestException
    from app.modules.payroll import jurisdiction_hooks as jh
    from app.modules.payroll.engine.countries.belgium import BECalculationBlockedError

    # Block A3: calc_inputs exists; without a pay date it refuses.
    with pytest.raises(BadRequestException, match="pay date"):
        jh.call("BE", "calc_inputs", db, None, SimpleNamespace(organization_id=1), None)
    assert jh.call("BE", "statutory_profile_errors", SimpleNamespace())
    with pytest.raises(BadRequestException):
        jh.call("BE", "statutory_profile_values", db, None, None, None)
    # Phase 3A: an unseeded BE pack is refused; editors are a set (see test_belgium_super_admin.py).
    pack = _be_pack(db, pack_id="BE-EMPTY")
    assert "no statutory content" in jh.call("BE", "pack_activation_refusal", db, pack)
    assert jh.call("BE", "template_activation_refusal", db, SimpleNamespace(jurisdiction_country="BE"), 1)
    assert jh.call("BE", "statutory_editors", db, pack) == set()
    # Block B3 (D13): Belgian payslips leave the generic bank file; they are paid
    # only through an approved Belgian payment batch.
    assert jh.call("BE", "payment_treatment", db, 1, SimpleNamespace(id=1),
                   [SimpleNamespace(id=7, country_code="BE"), SimpleNamespace(id=8, country_code="NL")]) ==         {7: "BE_PAYMENT_BATCH"}


def test_specified_inert_values(db):
    from app.modules.payroll import jurisdiction_hooks as jh

    assert jh.call("BE", "pack_holidays", db, 2026) == []
    summary = jh.call("BE", "statutory_summary", db)            # Block C2: real gate states; not certified
    assert summary["country"] == "BE" and summary["status"] == "NOT_CERTIFIED" and summary["available"] is False
    assert summary["gates"] == {g: "NOT MET" for g in ("G1", "G2", "G3", "G4", "G5", "G6", "G7")}
    assert jh.call("BE", "payslip_hold_view", SimpleNamespace(country_code="BE")) is None


def test_loop_hooks_are_inert_for_runs_without_belgian_items(db):
    from app.modules.payroll import jurisdiction_hooks as jh

    run = SimpleNamespace(id=987654)                                     # no payslips at all
    assert jh.call("BE", "before_run_transition", db, run, "APPROVED", 1) is None
    assert jh.call("BE", "payment_treatment", db, 1, run, [SimpleNamespace(country_code="IN")]) == {}


def test_retention_loop_unchanged_for_other_countries(db, monkeypatch):
    """retention_service._report_country asks EVERY registered module for its
    settings on each report download: Belgium answers (never raises) and only
    claims Belgian reports; every other country's outcome is identical."""
    from app.modules.payroll import jurisdiction_hooks, retention_service

    cfg = retention_service.settings("BE")
    assert cfg.country == "BE" and cfg.categories == ()
    assert cfg.decision_state(db, cfg.period_decision) == "OPEN"
    reports = [SimpleNamespace(jurisdiction_country=c, report_type=t) for c, t in (
        ("US", "US_W2"), ("IN", "IN_FORM16"), ("NL", "NL_X"), ("PL", "PL_PIT11"), ("HK", "HK_IR56B"),
        ("NZ", "NZ_EI"), ("JP", "JP_X"), ("", "SA_GOSI"), ("CH", "CH_LA"))]
    with_be = [retention_service._report_country(r) for r in reports]
    monkeypatch.setattr(jurisdiction_hooks, "_MODULES",
                        {k: v for k, v in jurisdiction_hooks._MODULES.items() if k != "BE"})
    without_be = [retention_service._report_country(r) for r in reports]
    assert with_be == without_be and "BE" not in with_be
    monkeypatch.undo()
    assert retention_service._report_country(SimpleNamespace(jurisdiction_country="BE", report_type="X")) == "BE"
    assert retention_service._report_country(SimpleNamespace(jurisdiction_country="", report_type="BE_281_10")) == "BE"


def test_legal_hold_lookup_is_inert_for_belgium(db):
    from app.modules.payroll import retention_service

    assert retention_service.active_legal_holds(db, "BE", 1, None) == []


def test_delete_employee_refused_for_a_canary_belgian_employee(db, monkeypatch):
    from fastapi import HTTPException

    from app.config import settings
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollEmployee
    from tests._mx_employer_helpers import make_org

    t = make_org(db, name="BE Canary Org", code="BECAN", country=None)
    monkeypatch.setattr(settings, "BE_CANARY_ORG_IDS", str(t.org.id))
    be = PayrollEmployee(organization_id=t.org.id, employee_code="BE1", name="Synthetic Worker", country_code="BE")
    other = PayrollEmployee(organization_id=t.org.id, employee_code="IN1", name="Synthetic Other", country_code="IN")
    db.add_all([be, other])
    db.commit()
    with pytest.raises(HTTPException) as raised:
        service.delete_employee(db, be.id, t.org.id)
    assert raised.value.status_code == 409 and raised.value.detail == G21
    assert db.get(PayrollEmployee, be.id) is not None
    service.delete_employee(db, other.id, t.org.id)                     # non-BE: unaffected
    db.expire_all()
    assert db.get(PayrollEmployee, other.id) is None


def test_registry_cannot_open_belgium_and_the_refusal_is_audited(db):
    from app.core.exceptions import BadRequestException
    from app.modules.billing.models import JurisdictionServiceRegistry
    from app.modules.payroll import service
    from app.modules.payroll.models import TaxConfigurationAudit

    _registry_row(db)
    with pytest.raises(BadRequestException, match="Statutory content"):    # Block C2: the real red gates
        service.transition_jurisdiction_service_registry(db, "BE", "AVAILABLE", "go live", actor_id=1)
    row = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == "BE").one()
    assert row.availability == "PLANNED"
    audit = (db.query(TaxConfigurationAudit)
             .filter(TaxConfigurationAudit.entity_type == "jurisdiction_service_registry",
                     TaxConfigurationAudit.action == "refused").all())
    assert len(audit) == 1 and "Statutory content" in audit[0].reason            # Block C2: real gates


# ── pack governance ────────────────────────────────────────────────────────
def test_generic_statutory_edits_are_refused_for_a_belgian_pack(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.schemas import CanonicalContributionRateUpsert, CanonicalTaxSlabUpsert

    pack = _be_pack(db)
    with pytest.raises(BadRequestException, match="Compliance → Belgium"):
        service.upsert_canonical_contribution_rate(db, CanonicalContributionRateUpsert(
            jurisdictionPackId=pack.id, jurisdictionCountry="BE", componentKey="be_probe", label="probe"), actor_id=1)
    with pytest.raises(BadRequestException, match="Compliance → Belgium"):
        service.upsert_canonical_tax_slab(db, CanonicalTaxSlabUpsert(
            jurisdictionPackId=pack.id, jurisdictionCountry="BE", minAmount=Decimal("0"), ratePct=Decimal("0"),
            rateLabel="probe"), actor_id=1)


def test_pack_activation_is_refused_for_an_unseeded_pack(db):
    # Phase 3A replaced the Phase 1 "approval always refused" stub with the real
    # statutory_editors set; activation of an empty pack is still refused.
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    pack = _be_pack(db, pack_id="BE-APPROVE")
    with pytest.raises(BadRequestException):
        service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=7)
    db.refresh(pack)
    assert pack.status != "Active"


# ── registry seed script ───────────────────────────────────────────────────
def test_seed_script_is_idempotent(db):
    from app.modules.billing.models import JurisdictionServiceRegistry
    from scripts.seed_belgium_registry import seed_belgium_registry

    assert seed_belgium_registry(db) == "PLANNED"
    db.commit()
    assert seed_belgium_registry(db) == "PLANNED"
    db.commit()
    rows = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == "BE").all()
    assert len(rows) == 1 and rows[0].availability == "PLANNED"


def test_seed_script_never_flips_an_existing_row(db):
    from app.modules.billing.models import JurisdictionServiceRegistry
    from scripts.seed_belgium_registry import seed_belgium_registry

    _registry_row(db, availability="AVAILABLE")                          # hypothetical, set by hand
    assert seed_belgium_registry(db) == "AVAILABLE"
    db.commit()
    rows = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == "BE").all()
    assert len(rows) == 1 and rows[0].availability == "AVAILABLE"
