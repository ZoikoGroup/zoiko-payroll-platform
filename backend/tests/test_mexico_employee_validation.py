"""Mexico Phase 4b — employee identifiers (spec §12 Identity, MX-036, MX-061):
RFC (física) / CURP / NSS / CLABE formats, FORMAT_ONLY (no check digit
without S31–S33), masking in every response, the masked duplicate-CURP 409,
per-organisation duplicates — and pins proving no other country changed
(strategy list, duplicate message, sensitive-field set, bank routing).
SYNTHETIC identifiers."""

import pytest

from tests._mx_employer_helpers import MX_IDS, enable_mx_onboarding, make_org, new_mx_employee


@pytest.fixture(autouse=True)
def _flag(monkeypatch):
    enable_mx_onboarding(monkeypatch)


def _strategy():
    from app.modules.payroll.employee_validation import MXEmployeeValidation

    return MXEmployeeValidation


def test_valid_identifiers_are_normalised():
    cleaned = _strategy().validate({"rfc": "abcd010101ab1", "curp": "abcd-010101-hdfxyz01", "nss": "123 456 789 01",
                                    "clabe": "002 180 700 012 345 678"})
    assert cleaned == {"rfc": "ABCD010101AB1", "curp": "ABCD010101HDFXYZ01", "nss": "12345678901",
                       "clabe": "002180700012345678"}


@pytest.mark.parametrize("field,value,msg", [
    ("rfc", "ABC010101AB1", "13-character persona física RFC"),      # a moral RFC is not an employee RFC
    ("rfc", "ABCD011301AB1", "real date"),
    ("curp", "ABCD010101HDFXYZ0", "18 letters or digits"),
    ("nss", "1234567890", "11 digits"),
    ("clabe", "12345", "18 digits"),
])
def test_format_errors(field, value, msg):
    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException, match=msg):
        _strategy().validate({**MX_IDS, field: value})


def test_rfc_curp_nss_are_required_clabe_is_optional():
    from app.core.exceptions import BadRequestException

    for field in ("rfc", "curp", "nss"):
        with pytest.raises(BadRequestException, match=f"{field} is required for MX"):
            _strategy().validate({k: v for k, v in MX_IDS.items() if k != field})
    assert "clabe" not in _strategy().validate(MX_IDS)


def test_identifiers_are_masked_in_responses(db):
    from app.modules.payroll.employee_validation import mask_compliance_fields

    t = make_org(db)
    emp = new_mx_employee(db, t.org.id, clabe="002180700012345678")
    shown = mask_compliance_fields(emp.compliance_fields)
    for field in ("rfc", "curp", "nss", "clabe"):
        assert shown[field] != emp.compliance_fields[field] and shown[field].endswith(emp.compliance_fields[field][-4:])


def test_duplicate_curp_is_refused_with_a_masked_value_and_allowed_in_another_org(db):
    from fastapi import HTTPException

    a, b = make_org(db), make_org(db, name="Other", code="OTHER")
    new_mx_employee(db, a.org.id)
    with pytest.raises(HTTPException) as exc:
        new_mx_employee(db, a.org.id, code="MX-002", email="emp2@example.com", rfc="WXYZ010101AB1", nss="10987654321")
    assert exc.value.status_code == 409
    assert MX_IDS["curp"] not in exc.value.detail and MX_IDS["curp"][-4:] in exc.value.detail
    new_mx_employee(db, b.org.id)                                        # per-organisation check


def test_flag_off_mexico_still_unsupported():
    from app.config import settings
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.employee_validation import (
        _STRATEGIES, get_employee_validation_strategy, is_supported_employee_country,
    )

    settings.MX_TENANT_ONBOARDING_ENABLED = False
    try:
        assert not is_supported_employee_country("MX")
        with pytest.raises(BadRequestException) as exc:
            get_employee_validation_strategy("MX")
        assert exc.value.message == f"Unsupported country code 'MX'. Supported: {', '.join(_STRATEGIES)}."
    finally:
        settings.MX_TENANT_ONBOARDING_ENABLED = True


# ── pins: nothing changed for any other country ──────────────────────────

def test_strategy_map_and_message_unchanged():
    from app.modules.payroll.employee_validation import _DORMANT_STRATEGIES, _STRATEGIES

    assert list(_STRATEGIES) == ["IN", "US", "UK", "AU", "CA", "DE", "BB", "KY", "DO", "GY", "JM", "BS", "TT", "PR",
                                 "FR", "IE", "SG", "HK", "SE", "IT", "CH", "SA", "NL",
                                 "BR"]  # Brazil (ZP-BR-ENG-001), merged from venu
    assert list(_DORMANT_STRATEGIES) == ["MX"]
    assert all(not getattr(cls, "MASK_DUPLICATE_VALUE", False) for cls in _STRATEGIES.values())


def test_other_countries_duplicate_message_is_byte_identical(db):
    """OOS-7 is NOT fixed here: HK still answers with the raw value, exactly as before 4b."""
    from fastapi import HTTPException

    from app.modules.organizations.models import Organization
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollEmployee

    org = Organization(organization_name="o", organization_code="PIN7")
    db.add(org)
    db.flush()
    db.add(PayrollEmployee(organization_id=org.id, employee_code="E1", name="A", country_code="HK",
                           compliance_fields={"hkid": "A1234563"}))
    db.commit()
    with pytest.raises(HTTPException) as exc:
        service.check_duplicate_employee_identifiers(db, org.id, None, "HK", None, {"hkid": "A1234563"})
    assert exc.value.detail == "An employee with HKID 'A1234563' already exists in this organization."


def test_sensitive_field_set_only_gains_mexican_keys():
    from app.modules.payroll.employee_validation import _STRATEGIES, SENSITIVE_COMPLIANCE_FIELDS

    before = frozenset(f for cls in _STRATEGIES.values() for f in cls.SENSITIVE_FIELDS)
    assert SENSITIVE_COMPLIANCE_FIELDS - before == {"rfc", "curp", "nss", "clabe"}
    for cls in _STRATEGIES.values():                                     # no other country uses these keys
        assert not {"rfc", "curp", "nss", "clabe"} & set(cls.FIELD_SPECS), cls.country_code


def test_bank_routing_other_countries_unchanged():
    from app.modules.payroll import bank_routing as br

    # Brazil (ZP-BR-ENG-001) follows Mexico at the end, merged from venu.
    assert br.ROUTING_COUNTRIES[:-2] == ("IN", "UK", "US", "CA", "DE", "AU", "BB", "KY", "DO", "GY", "JM", "BS", "TT",
                                         "PR", "FR", "IE", "HK", "NL") and br.ROUTING_COUNTRIES[-2:] == ("MX", "BR")
    assert br.ROUTING_FIELDS["MX"] == [{"key": "clabe", "label": "CLABE"}]
    assert (br.BTF_ROUTING_LABEL["MX"], br.PAYMENT_MODE_LABEL["MX"]) == ("CLABE", "SPEI")
    from app.modules.payroll.employee_validation import mask_routing

    rows = [{"key": "iban", "value": "NL00ZOIK0000000001"}, {"key": "sort_code", "value": "123456"},
            {"key": "clabe", "value": "002180700012345678"}]
    masked = mask_routing(rows)
    assert masked[1]["value"] == "123456" and masked[0]["value"] != rows[0]["value"]
    assert masked[2]["value"].endswith("5678") and masked[2]["value"] != rows[2]["value"]
