"""
engine/countries/brazil_content.py
----------------------------------
Statutory content and reference constants for Brazil (CLT) Payroll according
to specification ZP-BR-ENG-001 (Priority Market #12) — pure data, no ORM, no
framework (rubric seeding lives in brazil_service). The single copy: the
former modules/payroll/brazil_content.py was removed in Phase 2.

Baseline: 2026 Statutory Year
  - Minimum Wage: Decree 12.797/2025 (R$ 1,621.00/mo, R$ 54.04/day, R$ 7.37/hr)
  - Employee INSS: Portaria Interministerial MPS/MF 2026 progressive brackets & teto
  - IRRF: Receita Federal 2026 monthly progressive table & Law 15.270/2025 reduction
  - Salário-Família: Decree 12.797/2025 (R$ 67.54 quota, R$ 1,980.38 ceiling)
  - Rubric Catalog: eSocial S-1.3 Table 03 Naturezas & statutory incidences

Status: DRAFT, unsigned, not read by any payroll path (the engine blocks).
Phase 1 dates every value by tax year, derives the INSS maximum from the
brackets, re-verifies the rubric incidence codes against the official eSocial
tables, cites a saved, VERIFIED source for every row and seeds Draft canonical
packs. Known issues: docs/brazil/BRAZIL_PHASE_0_GAP_ASSESSMENT.md §7.
"""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

# Content identification & versioning (Rule BR-003, BR-004)
BRAZIL_SPEC_VERSION = "ZP-BR-ENG-001 v1.0"
SPEC = BRAZIL_SPEC_VERSION
BRAZIL_TAX_YEAR = 2026
BRAZIL_EFFECTIVE_DATE = date(2026, 1, 1)
PACK_STATUS = "Draft"  # seeds never create anything else

# (pack id, legal interval start, legal interval end) — seeded in Phase 1.
BR_2026 = ("BR-PAYROLL-2026", date(2026, 1, 1), date(2026, 12, 31))

# Evidence register — spec §25 "Official evidence register — reviewed for
# 2026 design", codes and titles verbatim.
SOURCE_REFERENCES = (
    ("S1", "INSS — 2026 contribution table"),
    ("S2", "Receita Federal — Taxation 2026"),
    ("S3", "Receita Federal — 2026 IR reduction examples"),
    ("S4", "Presidency — Decree 12.797/2025"),
    ("S5", "INSS — Salary-family 2026"),
    ("S6", "Receita Federal — Employer Social Security"),
    ("S7", "eSocial — 2026 Table 04 / contribution codes"),
    ("S8", "Presidency — Law 14.973/2024"),
    ("S9", "Federal Government — re-oneration guidance"),
    ("S10", "eSocial — Technical documentation"),
    ("S11", "eSocial — S-1.3 layouts through NT 07/2026"),
    ("S12", "eSocial — Manual S-1.3"),
    ("S13", "FGTS — Employer collection"),
    ("S14", "MTE — FGTS Digital"),
    ("S15", "FGTS Digital Manual 2026"),
    ("S16", "MTE — Worker rights overview"),
    ("S17", "MTE — Frequently asked questions"),
    ("S18", "MTE — Vacation FAQ"),
    ("S19", "Receita Federal — 2026 tax agenda"),
    ("S20", "MTE — FGTS Digital current manuals"),
)
SOURCE_CODES = tuple(code for code, _ in SOURCE_REFERENCES)

# Release gates (spec §24). Live Brazilian payroll stays disabled until every
# gate is evidenced and the registry row leaves PLANNED.
GATES = (
    ("G1", "Federal calculation"),
    ("G2", "Employer contributions"),
    ("G3", "eSocial"),
    ("G4", "DCTFWeb"),
    ("G5", "FGTS Digital"),
    ("G6", "Labor/CCT"),
    ("G7", "Security/privacy"),
    ("G8", "Parallel payroll"),
)

# ── 1. 2026 National Minimum Wage (Decree 12.797/2025) ────────────────────────
MINIMUM_WAGE_MONTHLY = Decimal("1621.00")
MINIMUM_WAGE_DAILY = Decimal("54.04")
MINIMUM_WAGE_HOURLY = Decimal("7.37")

# ── 2. 2026 Employee INSS Progressive Table ──────────────────────────────────
# Progressive brackets: (lower_bound, upper_bound, marginal_rate, max_bracket_contribution)
INSS_CEILING = Decimal("8475.55")
MAX_INSS_CONTRIBUTION = Decimal("951.62")

INSS_2026_BRACKETS: Tuple[Tuple[Decimal, Decimal, Decimal, Decimal], ...] = (
    (Decimal("0.00"), Decimal("1621.00"), Decimal("0.075"), Decimal("121.58")),
    (Decimal("1621.00"), Decimal("2902.84"), Decimal("0.090"), Decimal("115.37")),
    (Decimal("2902.84"), Decimal("4354.27"), Decimal("0.120"), Decimal("174.17")),
    (Decimal("4354.27"), Decimal("8475.55"), Decimal("0.140"), Decimal("577.02")),
)

# ── 3. 2026 IRRF Monthly Progressive Table & Deductions ──────────────────────
# Deductions
IRRF_DEPENDENT_DEDUCTION = Decimal("189.59")
IRRF_SIMPLIFIED_MONTHLY_DEDUCTION = Decimal("607.20")

# Progressive brackets: (lower_bound, upper_bound, rate, parcel_to_deduct)
IRRF_2026_TABLE: Tuple[Tuple[Decimal, Optional[Decimal], Decimal, Decimal], ...] = (
    (Decimal("0.00"), Decimal("2428.80"), Decimal("0.000"), Decimal("0.00")),
    (Decimal("2428.80"), Decimal("2826.65"), Decimal("0.075"), Decimal("182.16")),
    (Decimal("2826.65"), Decimal("3751.05"), Decimal("0.150"), Decimal("394.16")),
    (Decimal("3751.05"), Decimal("4664.68"), Decimal("0.225"), Decimal("675.49")),
    (Decimal("4664.68"), None, Decimal("0.275"), Decimal("908.73")),
)

# 2026 Monthly IRRF Reduction (Law 15.270/2025 - Rule BR-013)
# Up to R$ 5,000.00: max reduction R$ 312.89 -> net tax = R$ 0.00
# R$ 5,000.01 to R$ 7,350.00: 978.62 - (0.133145 * taxable_earnings)
# Above R$ 7,350.00: R$ 0.00
IRRF_2026_REDUCTION_ZERO_CEILING = Decimal("5000.00")
IRRF_2026_REDUCTION_MAX_ZERO = Decimal("312.89")
IRRF_2026_REDUCTION_PHASE_CEILING = Decimal("7350.00")
IRRF_2026_REDUCTION_A = Decimal("978.62")
IRRF_2026_REDUCTION_B = Decimal("0.133145")

# ── 4. 2026 Salário-Família (Decree 12.797/2025) ──────────────────────────────
SALARIO_FAMILIA_CEILING = Decimal("1980.38")
SALARIO_FAMILIA_QUOTA = Decimal("67.54")

# ── 5. Standard Employer Social Security, FGTS & Risk Rates ──────────────────
STANDARD_CPP_RATE = Decimal("0.20")              # 20% ordinary private-sector CPP
FINANCIAL_SECTOR_CPP_ADDON = Decimal("0.025")    # +2.5% for financial institutions
CPRB_2026_CPP_RATE = Decimal("0.10")             # 50% transition relief on covered payroll (10%)
CPRB_2026_SERVICE_RETENTION = Decimal("0.035")   # 3.5% retention on covered services

FGTS_ORDINARY_RATE = Decimal("0.08")             # 8% standard CLT
FGTS_APPRENTICE_RATE = Decimal("0.02")           # 2% apprentice
FGTS_TERMINATION_FINE_RATE = Decimal("0.40")     # 40% dismissal without cause
FGTS_MUTUAL_TERMINATION_FINE_RATE = Decimal("0.20") # 20% mutual agreement (Art. 484-A)

VALE_TRANSPORTE_MAX_DEDUCTION_PCT = Decimal("0.06") # 6% of base salary

# ── 6. Mandatory System Rubric Matrix (eSocial Table 03 - Rule BR-005) ────────
STANDARD_SYSTEM_RUBRICS: List[Dict[str, Any]] = [
    {
        "rubric_code": "BR_SALARIO_BASE",
        "rubric_name": "Salário Base Mensal",
        "nature_code": "1000",
        "rubric_type": "EARNING",
        "cod_inc_cp": "11",    # Base de cálculo mensal
        "cod_inc_irrf": "11",  # Remuneração mensal
        "cod_inc_fgts": "11",  # Base de cálculo mensal
    },
    {
        "rubric_code": "BR_DSR",
        "rubric_name": "Descanso Semanal Remunerado",
        "nature_code": "1002",
        "rubric_type": "EARNING",
        "cod_inc_cp": "11",
        "cod_inc_irrf": "11",
        "cod_inc_fgts": "11",
    },
    {
        "rubric_code": "BR_HORA_EXTRA_50",
        "rubric_name": "Hora Extra 50%",
        "nature_code": "1003",
        "rubric_type": "EARNING",
        "cod_inc_cp": "11",
        "cod_inc_irrf": "11",
        "cod_inc_fgts": "11",
    },
    {
        "rubric_code": "BR_HORA_EXTRA_100",
        "rubric_name": "Hora Extra 100%",
        "nature_code": "1004",
        "rubric_type": "EARNING",
        "cod_inc_cp": "11",
        "cod_inc_irrf": "11",
        "cod_inc_fgts": "11",
    },
    {
        "rubric_code": "BR_ADIC_NOTURNO",
        "rubric_name": "Adicional Noturno",
        "nature_code": "1202",
        "rubric_type": "EARNING",
        "cod_inc_cp": "11",
        "cod_inc_irrf": "11",
        "cod_inc_fgts": "11",
    },
    {
        "rubric_code": "BR_SAL_FAMILIA",
        "rubric_name": "Salário-Família",
        "nature_code": "1409",
        "rubric_type": "EARNING",
        "cod_inc_cp": "00",    # Não é base de cálculo
        "cod_inc_irrf": "00",  # Isento
        "cod_inc_fgts": "00",  # Não é base de cálculo
    },
    {
        "rubric_code": "BR_13_ADIANT",
        "rubric_name": "13º Salário - 1ª Parcela (Adiantamento)",
        "nature_code": "5001",
        "rubric_type": "EARNING",
        "cod_inc_cp": "00",    # Não incide INSS na 1ª parcela
        "cod_inc_irrf": "00",  # Não incide IRRF na 1ª parcela
        "cod_inc_fgts": "12",  # Incide FGTS 13º salário
    },
    {
        "rubric_code": "BR_13_FINAL",
        "rubric_name": "13º Salário - 2ª Parcela (Quitação)",
        "nature_code": "5002",
        "rubric_type": "EARNING",
        "cod_inc_cp": "12",    # Base de cálculo do 13º
        "cod_inc_irrf": "12",  # 13º salário - tributação exclusiva
        "cod_inc_fgts": "12",  # Base de cálculo do 13º
    },
    {
        "rubric_code": "BR_FERIAS_GOZO",
        "rubric_name": "Férias Gozadas",
        "nature_code": "1020",
        "rubric_type": "EARNING",
        "cod_inc_cp": "11",
        "cod_inc_irrf": "13",  # Férias - tributação exclusiva
        "cod_inc_fgts": "11",
    },
    {
        "rubric_code": "BR_FERIAS_TERCO",
        "rubric_name": "1/3 Constitucional de Férias",
        "nature_code": "1021",
        "rubric_type": "EARNING",
        "cod_inc_cp": "11",
        "cod_inc_irrf": "13",
        "cod_inc_fgts": "11",
    },
    {
        "rubric_code": "BR_INSS_EMP",
        "rubric_name": "INSS Empregado",
        "nature_code": "9201",
        "rubric_type": "DEDUCTION",
        "cod_inc_cp": "00",
        "cod_inc_irrf": "31",  # Dedução do rendimento tributável
        "cod_inc_fgts": "00",
    },
    {
        "rubric_code": "BR_IRRF",
        "rubric_name": "IRRF Retido na Fonte",
        "nature_code": "9203",
        "rubric_type": "DEDUCTION",
        "cod_inc_cp": "00",
        "cod_inc_irrf": "00",
        "cod_inc_fgts": "00",
    },
    {
        "rubric_code": "BR_DESC_VT",
        "rubric_name": "Desconto Vale-Transporte",
        "nature_code": "9215",
        "rubric_type": "DEDUCTION",
        "cod_inc_cp": "00",
        "cod_inc_irrf": "00",
        "cod_inc_fgts": "00",
    },
    {
        "rubric_code": "BR_PENSAO_ALIM",
        "rubric_name": "Pensão Alimentícia Judicial",
        "nature_code": "9230",
        "rubric_type": "DEDUCTION",
        "cod_inc_cp": "00",
        "cod_inc_irrf": "33",  # Dedução do rendimento tributável
        "cod_inc_fgts": "00",
    },
]


def calculate_content_hash() -> str:
    """Computes a deterministic SHA256 signature for 2026 Brazil content (Rule BR-003)."""
    raw = (
        f"{BRAZIL_SPEC_VERSION}|{BRAZIL_TAX_YEAR}|{MINIMUM_WAGE_MONTHLY}|"
        f"{INSS_CEILING}|{MAX_INSS_CONTRIBUTION}|{IRRF_DEPENDENT_DEDUCTION}|"
        f"{IRRF_SIMPLIFIED_MONTHLY_DEDUCTION}|{SALARIO_FAMILIA_CEILING}|"
        f"{SALARIO_FAMILIA_QUOTA}|{STANDARD_CPP_RATE}|{FGTS_ORDINARY_RATE}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


CONTENT_HASH = calculate_content_hash()
