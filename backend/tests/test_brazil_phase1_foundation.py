"""
tests/test_brazil_phase1_foundation.py
--------------------------------------
Foundation verification suite for Brazil (CLT) Payroll (ZP-BR-ENG-001):
  - Database schema & ORM modeling (constraints included)
  - Modulo 11 algorithmic verification for CPF, PIS/NIS, and CNPJ
  - Employee compliance validation strategy (BREmployeeValidation)
  - Bank routing & payment mode resolution for Brazil (PIX / TED / COMPE)
  - 2026 Statutory constants & idempotent rubric seeding

`app.*` is imported inside each test (never at module level) so collecting
this file cannot bind the app to the .env database before conftest's
in-memory SQLite `db` fixture is in place (the 2026 conftest race that once
wrote test rows into the live database).

Known draft defects are tracked in docs/brazil/BRAZIL_PHASE_0_GAP_ASSESSMENT.md
§7; tests marked xfail(strict=True) assert the CORRECT value and turn into a
failure the moment the defect is fixed, forcing the marker's removal.
"""

from datetime import date
from decimal import Decimal

import pytest


def _employer(organization_id=1, **extra):
    from app.modules.payroll.models import PayrollBrEmployerProfile

    values = dict(
        organization_id=organization_id,
        cnpj_root="12345678",
        legal_name="Zoiko Tecnologia Brasil Ltda",
        trade_name="Zoiko Payroll Brasil",
        tax_classification="99",
        cnae_preponderant="6201501",
        cprb_opted=False,
        esocial_environment="RESTRICTED_PRODUCTION",
        contact_name="Diretor de Folha",
        contact_cpf="12345678909",
        contact_email="payroll.br@zoiko.com",
        status="DRAFT",
    )
    values.update(extra)
    return PayrollBrEmployerProfile(**values)


def _establishment(employer_profile_id, **extra):
    from app.modules.payroll.models import PayrollBrEstablishment

    values = dict(
        employer_profile_id=employer_profile_id,
        cnpj="12345678000195",
        establishment_name="Matriz Sao Paulo",
        is_headquarters=True,
        cnae="6201501",
        rat_pct=Decimal("2.00"),
        fap_factor=Decimal("1.0000"),
        fpas_code="507",
        third_party_code="0079",
        third_party_pct=Decimal("5.80"),
        lotacao_code="LOT_MATRIZ_SP",
        postal_code="01310100",
        street_address="Av Paulista, 1000",
        neighborhood="Bela Vista",
        city_ibge_code="3550308",
        state_uf="SP",
    )
    values.update(extra)
    return PayrollBrEstablishment(**values)


# ── 1. Database & ORM Model Verification ──────────────────────────────────────

def test_brazil_orm_models_instantiation(db):
    """All four Brazil tables can be created and written; payslip snapshot columns exist."""
    from app.modules.payroll.models import PayrollBrRubric, PayslipItem

    profile = _employer()
    db.add(profile)
    db.flush()
    assert profile.id is not None

    establishment = _establishment(profile.id)
    db.add(establishment)
    db.flush()
    assert establishment.id is not None

    rubric = PayrollBrRubric(
        organization_id=1,
        rubric_code="BR_SALARIO_BASE",
        rubric_name="Salário Base Mensal",
        nature_code="1000",
        rubric_type="EARNING",
        cod_inc_cp="11",
        cod_inc_irrf="11",
        cod_inc_fgts="11",
        is_system_standard=True,
        version=1,
        valid_from=date(2026, 1, 1),
    )
    db.add(rubric)
    db.flush()
    assert rubric.id is not None

    for column in ("br_base_inss", "br_inss_employee", "br_base_irrf", "br_irrf", "br_irrf_reduction",
                   "br_salario_familia", "br_vale_transporte_deduction", "br_base_fgts", "br_fgts_deposit",
                   "br_cpp_employer", "br_rat_adjusted", "br_third_parties", "br_calculation_snapshot"):
        assert hasattr(PayslipItem, column), column


def test_one_employer_profile_per_organization(db):
    from sqlalchemy.exc import IntegrityError

    db.add(_employer(organization_id=7))
    db.flush()
    db.add(_employer(organization_id=7, cnpj_root="87654321"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_establishment_cnpj_unique_per_employer_not_platform_wide(db):
    """Same CNPJ under two employers is allowed (no cross-tenant disclosure);
    twice under one employer is refused."""
    from sqlalchemy.exc import IntegrityError

    a, b = _employer(organization_id=11), _employer(organization_id=12)
    db.add_all([a, b])
    db.flush()
    db.add_all([_establishment(a.id), _establishment(b.id)])
    db.flush()
    db.add(_establishment(a.id, establishment_name="Duplicate"))
    with pytest.raises(IntegrityError):
        db.flush()


@pytest.mark.parametrize("bad", [
    {"rat_pct": Decimal("1.50")},
    {"fap_factor": Decimal("0.4999")},
    {"fap_factor": Decimal("2.0001")},
])
def test_establishment_risk_checks(db, bad):
    from sqlalchemy.exc import IntegrityError

    employer = _employer(organization_id=21)
    db.add(employer)
    db.flush()
    db.add(_establishment(employer.id, **bad))
    with pytest.raises(IntegrityError):
        db.flush()


@pytest.mark.parametrize("bad", [
    {"esocial_category": "102"},
    {"weekly_hours": Decimal("45.00")},
    {"contract_type": "PERMANENT"},
    {"status": "UNKNOWN"},
])
def test_statutory_profile_checks(db, bad):
    from sqlalchemy.exc import IntegrityError

    from app.modules.payroll.models import PayrollBrStatutoryProfile

    employer = _employer(organization_id=31)
    db.add(employer)
    db.flush()
    establishment = _establishment(employer.id)
    db.add(establishment)
    db.flush()
    values = dict(employee_id=1, establishment_id=establishment.id, effective_from=date(2026, 1, 1),
                  cbo_code="212405")
    values.update(bad)
    db.add(PayrollBrStatutoryProfile(**values))
    with pytest.raises(IntegrityError):
        db.flush()


# ── 2. Algorithmic Identifier Verification ────────────────────────────────────

def test_cpf_validation_known_vectors():
    """Verify Modulo 11 check digit algorithm for CPF."""
    from app.modules.payroll.employee_validation import cpf_is_valid

    for cpf in ["52998224725", "11144477735", "00000000191", "529.982.247-25", " 111.444.777-35 "]:
        assert cpf_is_valid(cpf) is True, f"Expected {cpf} to be valid"
    for cpf in ["11111111111", "00000000000", "52998224726", "52998224715", "123456789", "123456789012",
                "", None, "abcdefghijk"]:
        assert cpf_is_valid(cpf) is False, f"Expected {cpf} to be invalid"


def test_pis_validation_known_vectors():
    """Verify Modulo 11 check digit algorithm for PIS/PASEP/NIS."""
    from app.modules.payroll.employee_validation import pis_is_valid

    for pis in ["12042827110", "17033259504", "120.42827.11-0", " 170.33259.50-4 "]:
        assert pis_is_valid(pis) is True, f"Expected {pis} to be valid"
    for pis in ["12042827115", "17033259509", "1234567890", "123456789012", "", None]:
        assert pis_is_valid(pis) is False, f"Expected {pis} to be invalid"


def test_cnpj_validation_known_vectors():
    """Verify Modulo 11 check digit algorithm for CNPJ (numeric and alphanumeric)."""
    from app.modules.payroll.employee_validation import cnpj_is_valid

    for cnpj in ["11222333000181", "12345678000195", "11.222.333/0001-81", " 12.345.678/0001-95 "]:
        assert cnpj_is_valid(cnpj) is True, f"Expected {cnpj} to be valid"
    for cnpj in ["11222333000182", "12345678000199", "1234567890123", "123456789012345", "", None]:
        assert cnpj_is_valid(cnpj) is False, f"Expected {cnpj} to be invalid"


# ── 3. Strategy & Compliance Validation ───────────────────────────────────────

def test_br_employee_validation_strategy():
    """Verify BREmployeeValidation registers and validates Brazil employees correctly."""
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.employee_validation import BREmployeeValidation, get_employee_validation_strategy

    strategy = get_employee_validation_strategy("BR")
    assert strategy is BREmployeeValidation
    assert strategy.country_code == "BR"
    assert strategy.duplicate_field == "cpf"
    assert "cpf" in strategy.SENSITIVE_FIELDS
    assert "pis_nis" in strategy.SENSITIVE_FIELDS

    cleaned = strategy.validate({
        "cpf": "529.982.247-25",
        "pis_nis": "120.42827.11-0",
        "pix_key_type": "CPF",
        "pix_key": "52998224725",
        "bank_compe": "001",
        "bank_agency": "1234",
        "bank_account": "56789",
        "bank_account_type": "CORRENTE",
    })
    assert cleaned["cpf"] == "52998224725"
    assert cleaned["pis_nis"] == "12042827110"
    assert cleaned["bank_compe"] == "001"

    with pytest.raises(BadRequestException):
        strategy.validate({"pis_nis": "12042827110"})
    with pytest.raises(BadRequestException, match="CPF fails"):
        strategy.validate({"cpf": "52998224720", "pis_nis": "12042827110"})
    with pytest.raises(BadRequestException, match="PIS/NIS fails"):
        strategy.validate({"cpf": "52998224725", "pis_nis": "12042827119"})


def test_sensitive_masking_for_brazil():
    """CPF and PIS/NIS are masked in compliance fields. (PIX key masking —
    a PIX key is often the CPF itself — is known gap BR-K6, Phase 4.)"""
    from app.modules.payroll.employee_validation import mask_compliance_fields

    masked = mask_compliance_fields({"cpf": "52998224725", "pis_nis": "12042827116"})
    assert masked["cpf"] != "52998224725" and masked["cpf"].endswith("4725")
    assert masked["pis_nis"] != "12042827116" and masked["pis_nis"].endswith("7116")


# ── 4. Bank Routing Resolution ────────────────────────────────────────────────

def test_brazil_bank_routing():
    """Bank routing registration and labels for Brazil. (bank_account is
    missing from the routing fields — known gap BR-K6, Phase 4.)"""
    from app.modules.payroll.bank_routing import (
        PAYMENT_MODE_LABEL, ROUTING_COUNTRIES, ROUTING_FIELDS, resolve_routing,
    )

    assert "BR" in ROUTING_COUNTRIES
    assert "BR" in ROUTING_FIELDS
    assert PAYMENT_MODE_LABEL.get("BR") == "PIX / TED"

    class MockEmployee:
        country_code = "BR"
        compliance_fields = {"pix_key": "12345678909", "bank_compe": "341", "bank_agency": "0987"}

    routing = resolve_routing(MockEmployee())
    assert [r["key"] for r in routing] == ["pix_key", "bank_compe", "bank_agency"]
    assert [r["value"] for r in routing] == ["12345678909", "341", "0987"]


# ── 5. 2026 Statutory Constants & Rubric Seeding ──────────────────────────────

def test_2026_statutory_baseline_constants():
    """2026 constants as drafted (Decree 12.797/2025 and the 2026 tables).
    Not yet signed: Phase 1 re-verifies each against its S-source."""
    from app.modules.payroll import brazil_content as c

    assert c.MINIMUM_WAGE_MONTHLY == Decimal("1621.00")
    assert c.MINIMUM_WAGE_DAILY == Decimal("54.04")
    assert c.MINIMUM_WAGE_HOURLY == Decimal("7.37")
    assert c.INSS_CEILING == Decimal("8475.55")
    assert len(c.INSS_2026_BRACKETS) == 4
    assert c.IRRF_DEPENDENT_DEDUCTION == Decimal("189.59")
    assert c.IRRF_SIMPLIFIED_MONTHLY_DEDUCTION == Decimal("607.20")
    assert c.IRRF_2026_REDUCTION_ZERO_CEILING == Decimal("5000.00")
    assert c.IRRF_2026_REDUCTION_MAX_ZERO == Decimal("312.89")
    assert c.SALARIO_FAMILIA_CEILING == Decimal("1980.38")
    assert c.SALARIO_FAMILIA_QUOTA == Decimal("67.54")
    assert c.STANDARD_CPP_RATE == Decimal("0.20")
    assert c.FGTS_ORDINARY_RATE == Decimal("0.08")
    assert c.FGTS_APPRENTICE_RATE == Decimal("0.02")


@pytest.mark.xfail(strict=True, reason="Known defect BR-K1 (INSS maximum 951.62) — fixed in Phase 1")
def test_inss_maximum_agrees_with_the_brackets():
    """The maximum employee contribution must equal the four 2026 brackets
    summed to the ceiling, rounded once (D1): 988.0914 → 988.09."""
    from decimal import ROUND_HALF_UP

    from app.modules.payroll import brazil_content as c

    full = sum((upper - lower) * rate for lower, upper, rate, _ in c.INSS_2026_BRACKETS)
    assert c.MAX_INSS_CONTRIBUTION == full.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) == Decimal("988.09")


def test_seed_brazil_statutory_content_idempotency(db):
    """seed_brazil_statutory_content seeds all 14 draft rubrics once. (The
    incidence codes themselves are unverified — known gap BR-K3, Phase 1.)"""
    from app.modules.payroll.brazil_content import STANDARD_SYSTEM_RUBRICS, seed_brazil_statutory_content
    from app.modules.payroll.models import PayrollBrRubric

    org_id = 42
    created = seed_brazil_statutory_content(db, organization_id=org_id)
    assert created == len(STANDARD_SYSTEM_RUBRICS) == 14

    rubrics = db.query(PayrollBrRubric).filter(PayrollBrRubric.organization_id == org_id).all()
    assert len(rubrics) == 14
    assert all(r.is_system_standard is True for r in rubrics)
    assert all(len(r.nature_code) == 4 and len(r.cod_inc_cp) == len(r.cod_inc_irrf) == len(r.cod_inc_fgts) == 2
               for r in rubrics)

    assert seed_brazil_statutory_content(db, organization_id=org_id) == 0
    assert db.query(PayrollBrRubric).filter(PayrollBrRubric.organization_id == org_id).count() == 14

