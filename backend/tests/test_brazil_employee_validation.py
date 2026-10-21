"""Brazil (ZP-BR-ENG-001) Phase 4 — PIX key validation, PIX/account masking
and the routing block. Closes BR-K6 (PIX masking; bank_account in routing).

The BREmployeeValidation class is exercised directly: its registration gate
(BR_TENANT_ONBOARDING_ENABLED) is covered by test_brazil_phase1_foundation.
"""
import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll.employee_validation import (
    BREmployeeValidation, PIX_KEY_TYPES, mask_pix_key, mask_routing, pix_key_is_valid,
)

VALID_PIX = {
    "CPF": "52998224725",
    "CNPJ": "11222333000181",
    "EMAIL": "joao.silva@banco.com.br",
    "PHONE": "+5511998765432",
    "RANDOM": "123e4567-e89b-42d3-a456-426614174000",
}
INVALID_PIX = {
    "CPF": "529.982.247-20",
    "CNPJ": "11222333000180",
    "EMAIL": "joao@@bank",
    "PHONE": "119987",
    "RANDOM": "not-a-uuid",
}


def test_pix_key_types_registered():
    assert PIX_KEY_TYPES == ("CPF", "CNPJ", "EMAIL", "PHONE", "RANDOM")
    assert {"pix_key", "bank_account"} <= set(BREmployeeValidation.SENSITIVE_FIELDS)


@pytest.mark.parametrize("kind", PIX_KEY_TYPES)
def test_pix_key_is_valid_per_type(kind):
    assert pix_key_is_valid(VALID_PIX[kind], kind) is True
    assert pix_key_is_valid(VALID_PIX[kind], kind.lower()) is True   # type is case-insensitive
    assert pix_key_is_valid(INVALID_PIX[kind], kind) is False
    assert pix_key_is_valid(VALID_PIX[kind], None) is False          # type required
    assert pix_key_is_valid("", kind) is False


def test_strategy_accepts_valid_pix():
    cleaned = BREmployeeValidation.validate({
        "cpf": "529.982.247-25",
        "pis_nis": "120.42827.11-0",
        "pix_key_type": "email",
        "pix_key": "joao@bank.com",
    })
    assert cleaned["pix_key_type"] == "EMAIL"
    assert cleaned["pix_key"] == "joao@bank.com"


@pytest.mark.parametrize("kind", PIX_KEY_TYPES)
def test_strategy_rejects_pix_mismatched_to_type(kind):
    with pytest.raises(BadRequestException, match="PIX key"):
        BREmployeeValidation.validate({
            "cpf": "52998224725",
            "pis_nis": "12042827110",
            "pix_key_type": kind,
            "pix_key": INVALID_PIX[kind],
        })


def test_strategy_requires_type_when_key_present():
    with pytest.raises(BadRequestException, match="requires pix_key_type"):
        BREmployeeValidation.validate({
            "cpf": "52998224725",
            "pis_nis": "12042827110",
            "pix_key": "joao@bank.com",
        })


def test_pix_absent_is_optional():
    cleaned = BREmployeeValidation.validate({"cpf": "52998224725", "pis_nis": "12042827110"})
    assert "pix_key" not in cleaned and "pix_key_type" not in cleaned


def test_mask_pix_key_per_type():
    assert mask_pix_key("52998224725", "CPF").endswith("4725")
    assert mask_pix_key("52998224725", "CPF") != "52998224725"
    assert mask_pix_key("123e4567-e89b-12d3-a456-426614174000", "RANDOM").endswith("4000")
    assert mask_pix_key("+5511998765432", "PHONE").endswith("5432")
    assert mask_pix_key("joao@bank.com", "EMAIL") == "j***@bank.com"
    assert mask_pix_key("joao@bank.com") == "j***@bank.com"     # "@" implies EMAIL when type omitted
    assert mask_pix_key(None) is None and mask_pix_key("") is None


def test_mask_routing_brasil():
    rows = [
        {"key": "pix_key", "label": "PIX Key", "value": "joao@bank.com"},
        {"key": "bank_compe", "label": "Bank COMPE", "value": "341"},
        {"key": "bank_agency", "label": "Agency", "value": "0987"},
        {"key": "bank_account", "label": "Account", "value": "12345678"},
    ]
    masked = {r["key"]: r["value"] for r in mask_routing(rows)}
    assert masked["pix_key"] == "j***@bank.com"
    assert masked["bank_compe"] == "341"            # routing codes stay visible
    assert masked["bank_agency"] == "0987"
    assert masked["bank_account"].endswith("5678") and masked["bank_account"] != "12345678"
