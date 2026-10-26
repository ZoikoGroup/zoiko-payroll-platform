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
        version=1,
        effective_from=date(2026, 1, 1),
        cnpj_root="12345678",
        legal_name="Zoiko Tecnologia Brasil Ltda",
        trade_name="Zoiko Payroll Brasil",
        tax_classification="99",
        cnae_preponderant="6201501",
        esocial_environment="RESTRICTED_PRODUCTION",
        contact_name="Diretor de Folha",
        contact_cpf="12345678909",
        contact_email="payroll.br@zoiko.com",
        status="ACTIVE",
    )
    values.update(extra)
    return PayrollBrEmployerProfile(**values)


def _establishment(employer, **extra):
    from app.modules.payroll.models import PayrollBrEstablishment

    values = dict(
        organization_id=employer.organization_id,
        employer_profile_id=employer.id,
        cnpj="12345678000195",
        establishment_name="Matriz Sao Paulo",
        is_headquarters=True,
        cnae="6201501",
        fpas_code="507",
        third_party_code="0079",
        third_party_pct=Decimal("5.80"),
        fpas_evidence_ref="FPAS declaration (test)",
        lotacao_code="LOT_MATRIZ_SP",
        postal_code="01310100",
        street_address="Av Paulista, 1000",
        neighborhood="Bela Vista",
        city_ibge_code="3550308",
        state_uf="SP",
        active_from=date(2026, 1, 1),
    )
    values.update(extra)
    return PayrollBrEstablishment(**values)


# ── 1. Database & ORM Model Verification ──────────────────────────────────────

def test_brazil_orm_models_instantiation(db):
    """The Brazil tables can be created and written; payslip snapshot columns exist."""
    from app.modules.payroll.models import PayrollBrRubric, PayslipItem

    profile = _employer()
    db.add(profile)
    db.flush()
    assert profile.id is not None

    establishment = _establishment(profile)
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


def test_one_open_version_per_employer_chain(db):
    """Phase 3: an organisation may hold several legal employers (CNPJ roots),
    but each chain has exactly one OPEN version and unique version numbers."""
    from sqlalchemy.exc import IntegrityError

    db.add(_employer(organization_id=7))
    db.add(_employer(organization_id=7, cnpj_root="87654321"))       # another legal employer: allowed
    db.flush()
    db.add(_employer(organization_id=7, version=2, effective_from=date(2026, 6, 1)))   # second OPEN version
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    db.add(_employer(organization_id=8))
    db.flush()
    db.add(_employer(organization_id=8, effective_from=date(2026, 6, 1), effective_to=date(2026, 6, 30)))  # dup v1
    with pytest.raises(IntegrityError):
        db.flush()


def test_establishment_cnpj_unique_per_employer_not_platform_wide(db):
    """Same CNPJ under two employers is allowed (no cross-tenant disclosure);
    twice under one employer is refused."""
    from sqlalchemy.exc import IntegrityError

    a, b = _employer(organization_id=11), _employer(organization_id=12)
    db.add_all([a, b])
    db.flush()
    db.add_all([_establishment(a), _establishment(b)])
    db.flush()
    db.add(_establishment(a, establishment_name="Duplicate", is_headquarters=False))
    with pytest.raises(IntegrityError):
        db.flush()


def test_one_active_headquarters_per_employer(db):
    from sqlalchemy.exc import IntegrityError

    employer = _employer(organization_id=13)
    db.add(employer)
    db.flush()
    db.add(_establishment(employer))
    db.flush()
    db.add(_establishment(employer, cnpj="12345678000276", is_headquarters=False))      # a branch: fine
    db.flush()
    db.add(_establishment(employer, cnpj="12345678000357", is_headquarters=True))       # a second active HQ
    with pytest.raises(IntegrityError):
        db.flush()


@pytest.mark.parametrize("bad", [
    {"rat_pct": Decimal("1.50")},
    {"fap_factor": Decimal("0.4999")},
    {"fap_factor": Decimal("2.0001")},
    {"status": "OPEN"},
    {"calendar_year": 2025},
])
def test_risk_assignment_checks(db, bad):
    from sqlalchemy.exc import IntegrityError

    from app.modules.payroll.models import PayrollBrRiskAssignment

    employer = _employer(organization_id=21)
    db.add(employer)
    db.flush()
    establishment = _establishment(employer)
    db.add(establishment)
    db.flush()
    values = dict(organization_id=21, establishment_id=establishment.id, calendar_year=2026, rat_pct=Decimal("2"),
                  fap_factor=Decimal("1.0000"), evidence_ref="FAP notice (test)", status="DRAFT")
    values.update(bad)
    db.add(PayrollBrRiskAssignment(**values))
    with pytest.raises(IntegrityError):
        db.flush()


@pytest.mark.parametrize("bad", [
    {"br_esocial_category": "102"},
    {"br_weekly_hours": Decimal("45.00")},
    {"br_contract_type": "PERMANENT"},
    {"br_cbo_code": "12"},
    {"br_irrf_dependents_count": 2},
])
def test_statutory_profile_checks(db, bad):
    """Phase 4b: the CLT profile lives on the shared EmployeeStatutoryProfile's
    br_* block, so the field checks are app-level (brazil_employee_service
    .statutory_profile_errors) rather than the old dedicated-table constraints."""
    from types import SimpleNamespace

    from app.modules.payroll import brazil_employee_service as emp

    values = {"br_esocial_category": "101", "br_weekly_hours": Decimal("44.00"),
              "br_contract_type": "INDEFINITE", "br_cbo_code": "212405",
              "br_irrf_dependents_count": 0}
    values.update(bad)
    assert emp.statutory_profile_errors(SimpleNamespace(**values))


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

    from app.config import settings

    original = settings.BR_TENANT_ONBOARDING_ENABLED
    settings.BR_TENANT_ONBOARDING_ENABLED = True          # Phase 3: the validator is dormant by default
    try:
        strategy = get_employee_validation_strategy("BR")
    finally:
        settings.BR_TENANT_ONBOARDING_ENABLED = original
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
    """CPF, PIS/NIS, PIX key and bank account are masked in compliance fields
    (BR-K6 closed in Phase 4)."""
    from app.modules.payroll.employee_validation import mask_compliance_fields

    masked = mask_compliance_fields({
        "cpf": "52998224725",
        "pis_nis": "12042827116",
        "pix_key": "52998224725",
        "bank_account": "12345678",
    })
    assert masked["cpf"] != "52998224725" and masked["cpf"].endswith("4725")
    assert masked["pis_nis"] != "12042827116" and masked["pis_nis"].endswith("7116")
    assert masked["pix_key"] != "52998224725" and masked["pix_key"].endswith("4725")
    assert masked["bank_account"] != "12345678" and masked["bank_account"].endswith("5678")


# ── 4. Bank Routing Resolution ────────────────────────────────────────────────

def test_brazil_bank_routing():
    """Bank routing registration and labels for Brazil (bank_account added to
    the routing block in Phase 4 — BR-K6)."""
    from app.modules.payroll.bank_routing import (
        PAYMENT_MODE_LABEL, ROUTING_COUNTRIES, ROUTING_FIELDS, resolve_routing,
    )

    assert "BR" in ROUTING_COUNTRIES
    assert "BR" in ROUTING_FIELDS
    assert PAYMENT_MODE_LABEL.get("BR") == "PIX / TED"

    class MockEmployee:
        country_code = "BR"
        compliance_fields = {"pix_key": "12345678909", "bank_compe": "341", "bank_agency": "0987",
                             "bank_account": "12345678"}

    routing = resolve_routing(MockEmployee())
    # Phase 4.1 adds the ISPB (full TED / CNAB routing).
    assert [r["key"] for r in routing] == ["pix_key", "bank_compe", "bank_agency", "bank_account", "bank_ispb"]
    assert [r["value"] for r in routing] == ["12345678909", "341", "0987", "12345678", ""]   # no ISPB on file


# ── 5. 2026 Statutory Constants & Rubric Seeding ──────────────────────────────

def test_2026_statutory_baseline_constants():
    """2026 constants as drafted (Decree 12.797/2025 and the 2026 tables).
    Not yet signed: Phase 1 re-verifies each against its S-source."""
    from app.modules.payroll.engine.countries import brazil_content as c

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
def test_inss_maximum_agrees_with_the_brackets():
    """The maximum employee contribution must equal the four 2026 brackets
    summed to the ceiling, rounded once (D1): 988.0914 → 988.09."""
    from decimal import ROUND_HALF_UP

    from app.modules.payroll.engine.countries import brazil_content as c

    full = sum((upper - lower) * rate for lower, upper, rate, _ in c.INSS_2026_BRACKETS)
    assert c.MAX_INSS_CONTRIBUTION == full.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) == Decimal("988.09")


def test_seed_brazil_statutory_content_idempotency(db):
    """seed_brazil_statutory_content seeds all 14 draft rubrics once. (The
    incidence codes themselves are unverified — known gap BR-K3, Phase 1.)"""
    from app.modules.payroll.brazil_service import seed_brazil_statutory_content
    from app.modules.payroll.engine.countries.brazil_content import STANDARD_SYSTEM_RUBRICS
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

