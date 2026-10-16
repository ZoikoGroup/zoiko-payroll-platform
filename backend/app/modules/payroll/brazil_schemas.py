"""
modules/payroll/brazil_schemas.py
---------------------------------
Pydantic schemas for Brazil (CLT) Payroll onboarding, establishments,
rubrics, and statutory profiles (ZP-BR-ENG-001).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


# ── 1. Employer Profile Schemas ───────────────────────────────────────────────

class BREmployerProfileBase(BaseModel):
    cnpj_root: str = Field(..., min_length=8, max_length=8, description="8-character root CNPJ (alphanumeric-aware)")
    legal_name: str = Field(..., max_length=255, description="Corporate legal name (Razão Social)")
    trade_name: Optional[str] = Field(None, max_length=255, description="Trade name (Nome Fantasia)")
    tax_classification: str = Field(..., min_length=2, max_length=2, description="eSocial Table 08 tax classification code")
    cnae_preponderant: str = Field(..., min_length=7, max_length=7, description="7-digit primary economic activity code")
    cprb_opted: bool = Field(False, description="Opted into CPRB transition regime (Law 14.973/2024)")
    cprb_rate_pct: Optional[Decimal] = Field(None, description="CPRB gross-revenue percentage if applicable")
    esocial_environment: str = Field("RESTRICTED_PRODUCTION", description="RESTRICTED_PRODUCTION or PRODUCTION")
    esocial_cert_alias: Optional[str] = Field(None, description="Vault secret reference for PKCS#12 A1 certificate")
    contact_name: str = Field(..., max_length=120)
    contact_cpf: str = Field(..., min_length=11, max_length=11)
    contact_email: str = Field(..., max_length=120)
    contact_phone: Optional[str] = Field(None, max_length=20)


class BREmployerProfileCreate(BREmployerProfileBase):
    pass


class BREmployerProfileUpdate(BaseModel):
    legal_name: Optional[str] = None
    trade_name: Optional[str] = None
    tax_classification: Optional[str] = None
    cnae_preponderant: Optional[str] = None
    cprb_opted: Optional[bool] = None
    cprb_rate_pct: Optional[Decimal] = None
    esocial_environment: Optional[str] = None
    esocial_cert_alias: Optional[str] = None
    contact_name: Optional[str] = None
    contact_cpf: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    status: Optional[str] = None


class BREmployerProfileResponse(BREmployerProfileBase):
    id: int
    organization_id: int
    esocial_active_version: str
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ── 2. Establishment Schemas ──────────────────────────────────────────────────

class BREstablishmentBase(BaseModel):
    cnpj: str = Field(..., min_length=14, max_length=14, description="Full 14-character alphanumeric CNPJ")
    establishment_name: str = Field(..., max_length=255)
    is_headquarters: bool = Field(False)
    cnae: str = Field(..., min_length=7, max_length=7)
    rat_pct: Decimal = Field(..., description="1.00, 2.00, or 3.00")
    fap_factor: Decimal = Field(Decimal("1.0000"), ge=Decimal("0.5000"), le=Decimal("2.0000"))
    fpas_code: str = Field(..., min_length=3, max_length=3)
    third_party_code: str = Field(..., min_length=4, max_length=4)
    third_party_pct: Decimal = Field(...)
    lotacao_code: str = Field(..., max_length=30)
    postal_code: str = Field(..., min_length=8, max_length=8)
    street_address: str = Field(..., max_length=255)
    neighborhood: str = Field(..., max_length=100)
    city_ibge_code: str = Field(..., min_length=7, max_length=7)
    state_uf: str = Field(..., min_length=2, max_length=2)
    judicial_process_id: Optional[str] = None


class BREstablishmentCreate(BREstablishmentBase):
    pass


class BREstablishmentUpdate(BaseModel):
    establishment_name: Optional[str] = None
    cnae: Optional[str] = None
    rat_pct: Optional[Decimal] = None
    fap_factor: Optional[Decimal] = None
    fpas_code: Optional[str] = None
    third_party_code: Optional[str] = None
    third_party_pct: Optional[Decimal] = None
    lotacao_code: Optional[str] = None
    postal_code: Optional[str] = None
    street_address: Optional[str] = None
    neighborhood: Optional[str] = None
    city_ibge_code: Optional[str] = None
    state_uf: Optional[str] = None
    judicial_process_id: Optional[str] = None


class BREstablishmentResponse(BREstablishmentBase):
    id: int
    employer_profile_id: int
    adjusted_rat_pct: Optional[Decimal] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── 3. Rubric Schemas ─────────────────────────────────────────────────────────

class BRRubricBase(BaseModel):
    rubric_code: str = Field(..., max_length=30)
    rubric_name: str = Field(..., max_length=255)
    nature_code: str = Field(..., min_length=4, max_length=4, description="eSocial Table 03 Nature Code")
    rubric_type: str = Field(..., description="EARNING, DEDUCTION, or INFORMATIONAL")
    cod_inc_cp: str = Field(..., min_length=2, max_length=2, description="Social security incidence")
    cod_inc_irrf: str = Field(..., min_length=2, max_length=2, description="IRRF incidence")
    cod_inc_fgts: str = Field(..., min_length=2, max_length=2, description="FGTS incidence")
    valid_from: date
    valid_to: Optional[date] = None


class BRRubricCreate(BRRubricBase):
    pass


class BRRubricUpdate(BaseModel):
    rubric_name: Optional[str] = None
    nature_code: Optional[str] = None
    rubric_type: Optional[str] = None
    cod_inc_cp: Optional[str] = None
    cod_inc_irrf: Optional[str] = None
    cod_inc_fgts: Optional[str] = None
    valid_to: Optional[date] = None


class BRRubricResponse(BRRubricBase):
    id: int
    organization_id: int
    is_system_standard: bool
    version: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── 4. Statutory Profile Schemas ──────────────────────────────────────────────

class BRStatutoryProfileBase(BaseModel):
    establishment_id: int
    effective_from: date
    effective_to: Optional[date] = None
    esocial_category: str = Field("101", description="101 CLT Ordinary, 103 Apprentice, etc.")
    cbo_code: str = Field(..., min_length=6, max_length=6, description="6-digit CBO job code")
    contract_type: str = Field("INDEFINITE", description="INDEFINITE, DETERMINED, or INTERMITTENT")
    weekly_hours: Decimal = Field(Decimal("44.00"))
    concurrent_inss_flag: bool = Field(False)
    concurrent_inss_base_external: Decimal = Field(Decimal("0.00"))
    concurrent_inss_deducted_external: Decimal = Field(Decimal("0.00"))
    irrf_dependents_count: int = Field(0, ge=0)
    salario_familia_dependents_count: int = Field(0, ge=0)
    simplified_irrf_opt_out: bool = Field(False)
    alimony_deduction_fixed: Decimal = Field(Decimal("0.00"), ge=Decimal("0.00"))
    alimony_deduction_pct: Decimal = Field(Decimal("0.00"), ge=Decimal("0.00"), le=Decimal("100.00"))
    vale_transporte_elected: bool = Field(False)
    vale_transporte_daily_cost: Decimal = Field(Decimal("0.00"), ge=Decimal("0.00"))


class BRStatutoryProfileCreate(BRStatutoryProfileBase):
    pass


class BRStatutoryProfileUpdate(BaseModel):
    establishment_id: Optional[int] = None
    effective_to: Optional[date] = None
    esocial_category: Optional[str] = None
    cbo_code: Optional[str] = None
    contract_type: Optional[str] = None
    weekly_hours: Optional[Decimal] = None
    concurrent_inss_flag: Optional[bool] = None
    concurrent_inss_base_external: Optional[Decimal] = None
    concurrent_inss_deducted_external: Optional[Decimal] = None
    irrf_dependents_count: Optional[int] = None
    salario_familia_dependents_count: Optional[int] = None
    simplified_irrf_opt_out: Optional[bool] = None
    alimony_deduction_fixed: Optional[Decimal] = None
    alimony_deduction_pct: Optional[Decimal] = None
    vale_transporte_elected: Optional[bool] = None
    vale_transporte_daily_cost: Optional[Decimal] = None
    status: Optional[str] = None


class BRStatutoryProfileResponse(BRStatutoryProfileBase):
    id: int
    employee_id: int
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)



# ── 5. Readiness (Phase 0) ────────────────────────────────────────────────────
# camelCase response, like netherlands_schemas.py / mexico_schemas.py.

class BRGateState(BaseModel):
    gate: str
    label: str
    state: str  # OPEN / SUBMITTED / SIGNED


class BRReadinessResponse(BaseModel):
    jurisdiction: str
    spec: str
    available: bool
    engineVersion: str
    phase: int
    gates: List[BRGateState]
    note: str
