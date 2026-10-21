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

Status: DRAFT, transcribed from saved official sources (docs/brazil/sources/,
SOURCES_MANIFEST.csv); every row cites its source code and stays [PENDING G1]
until the human gate-G1 review. Values are dated (2026 only); a date outside
the content raises BrazilContentMissing (BR_CONTENT_YEAR_UNAVAILABLE). The
engine still BLOCKS every calculation. The eSocial rubric incidence codes are
NOT yet verified (Tabela 03 not saved — BR-K3) and are never seeded into a
pack. Known issues: docs/brazil/BRAZIL_PHASE_0_GAP_ASSESSMENT.md §7.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

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

# Additional saved official sources the spec register does not list by name
# (docs/brazil/sources/SOURCES_MANIFEST.csv). A4 is the primary legal act
# behind S1/S5; it is a scanned PDF without a text layer, so S1/S5 (the INSS
# pages reproducing it) are what each row cites.
ADDENDUM_SOURCE_REFERENCES = (
    ("A1", "Presidency — Law 15.270/2025 (monthly IR reduction, art. 3-A of Lei 9.250)"),
    ("A2", "Presidency — Law 8.212/1991, art. 22 (employer contribution, financial add-on)"),
    ("A3", "Presidency — Law 8.036/1990, art. 15 (FGTS 8%, apprentice 2%)"),
    ("A4", "MPS/MF — Portaria Interministerial nº 13, de 9 de janeiro de 2026"),
    ("A5", "Presidency — Law 7.418/1985, art. 4 (Vale-Transporte max deduction 6%)"),
    ("A6", "Presidency — Law 5.452/1943 (CLT original), arts. 59 & 73"),
    ("A7", "Presidency — Law 605/1949 (DSR on overtime and variable pay)"),
)
ALL_SOURCE_CODES = SOURCE_CODES + tuple(code for code, _ in ADDENDUM_SOURCE_REFERENCES)

# Every row is transcribed from a saved, VERIFIED source and stays marked
# pending until the human gate-G1 statutory review signs it.
PENDING_G1 = "[PENDING G1]"

# TaxSlab discriminators (rule_type). countries/brazil.py and the Super Admin
# pack-rows view read only rows whose rule_type starts with "BR_"; Brazil is NOT
# a _NO_TAX_SLAB_COUNTRIES country (INSS and IRRF are bracket tables).
BR_INSS_BAND_RULE = "BR_INSS_BAND"
BR_IRRF_TABLE_RULE = "BR_IRRF_TABLE"
BR_IRRF_REDUCTION_RULE = "BR_IRRF_REDUCTION"
BR_MIN_WAGE_RULE = "BR_MIN_WAGE"
BR_SAL_FAMILIA_RULE = "BR_SAL_FAMILIA"
BR_FGTS_RATE_RULE = "BR_FGTS_RATE"
BR_CPP_RATE_RULE = "BR_CPP_RATE"
BR_VT_RATE_RULE = "BR_VT_RATE"
BR_LABOR_RULE = "BR_LABOR"
BR_SLAB_RULES = (BR_INSS_BAND_RULE, BR_IRRF_TABLE_RULE, BR_IRRF_REDUCTION_RULE, BR_MIN_WAGE_RULE,
                 BR_SAL_FAMILIA_RULE, BR_FGTS_RATE_RULE, BR_CPP_RATE_RULE, BR_VT_RATE_RULE, BR_LABOR_RULE)


class ContentRow(NamedTuple):
    """One statutory row. Amounts in R$; rate_pct is a PERCENT (7.5 = 7.5%),
    never a fraction. min/max bound the band the row applies to (None = open)."""
    rule_type: str
    key: str
    label: str
    min_amount: Optional[Decimal]
    max_amount: Optional[Decimal]
    rate_pct: Optional[Decimal]
    flat_amount: Optional[Decimal]
    effective_from: date
    effective_to: Optional[date]
    source: str


_Y26 = (date(2026, 1, 1), date(2026, 12, 31))
D = Decimal


def _row(rule, key, label, source, *, lo=None, hi=None, rate=None, flat=None, window=_Y26):
    return ContentRow(rule, key, label, D(lo) if lo is not None else None, D(hi) if hi is not None else None,
                      D(rate) if rate is not None else None, D(flat) if flat is not None else None,
                      window[0], window[1], source)


BR_CONTENT_ROWS: Tuple[ContentRow, ...] = (
    # ── 1. Employee INSS — progressive bands, by competence month (S1) ────────
    _row(BR_INSS_BAND_RULE, "B1", "Até R$ 1.621,00 — 7,5%", "S1", lo="0.00", hi="1621.00", rate="7.5"),
    _row(BR_INSS_BAND_RULE, "B2", "De R$ 1.621,01 a R$ 2.902,84 — 9%", "S1", lo="1621.00", hi="2902.84", rate="9"),
    _row(BR_INSS_BAND_RULE, "B3", "De R$ 2.902,85 até R$ 4.354,27 — 12%", "S1", lo="2902.84", hi="4354.27", rate="12"),
    _row(BR_INSS_BAND_RULE, "B4", "De R$ 4.354,28 até R$ 8.475,55 — 14%", "S1", lo="4354.27", hi="8475.55", rate="14"),
    # ── 2. IRRF monthly table on the base de cálculo + deductions (S2) ────────
    _row(BR_IRRF_TABLE_RULE, "T1", "Até R$ 2.428,80 — isento", "S2", lo="0.00", hi="2428.80", rate="0", flat="0.00"),
    _row(BR_IRRF_TABLE_RULE, "T2", "De R$ 2.428,81 até R$ 2.826,65 — 7,5%", "S2", lo="2428.80", hi="2826.65",
         rate="7.5", flat="182.16"),
    _row(BR_IRRF_TABLE_RULE, "T3", "De R$ 2.826,66 até R$ 3.751,05 — 15%", "S2", lo="2826.65", hi="3751.05",
         rate="15", flat="394.16"),
    _row(BR_IRRF_TABLE_RULE, "T4", "De R$ 3.751,06 até R$ 4.664,68 — 22,5%", "S2", lo="3751.05", hi="4664.68",
         rate="22.5", flat="675.49"),
    _row(BR_IRRF_TABLE_RULE, "T5", "Acima de R$ 4.664,68 — 27,5%", "S2", lo="4664.68", rate="27.5", flat="908.73"),
    _row(BR_IRRF_TABLE_RULE, "DEDUCTION_DEPENDENT", "Dedução mensal por dependente", "S2", flat="189.59"),
    _row(BR_IRRF_TABLE_RULE, "DEDUCTION_SIMPLIFIED", "Limite mensal de desconto simplificado", "S2", flat="607.20"),
    # ── 3. IRRF 2026 monthly reduction on GROSS taxable income (A1, S2, S3) ───
    # Applied after the table (BR-013). The basis is the taxable INCOME, "e não o
    # da base de cálculo" (Receita example 5, S3) — decision D2.
    _row(BR_IRRF_REDUCTION_RULE, "ZERO_BAND", "Rendimentos até R$ 5.000,00 — redução até R$ 312,89",
         "A1", lo="0.00", hi="5000.00", flat="312.89"),
    _row(BR_IRRF_REDUCTION_RULE, "PHASE_OUT", "R$ 5.000,01 a R$ 7.350,00 — 978,62 − 0,133145 × rendimentos",
         "A1", lo="5000.00", hi="7350.00", rate="13.3145", flat="978.62"),
    # ── 4. Minimum wage (S4) ──────────────────────────────────────────────────
    _row(BR_MIN_WAGE_RULE, "MONTHLY", "Salário mínimo mensal", "S4", flat="1621.00"),
    _row(BR_MIN_WAGE_RULE, "DAILY", "Salário mínimo diário", "S4", flat="54.04"),
    _row(BR_MIN_WAGE_RULE, "HOURLY", "Salário mínimo horário", "S4", flat="7.37"),
    # ── 5. Salário-família (S5) — total salário de contribuição, all jobs ─────
    _row(BR_SAL_FAMILIA_RULE, "QUOTA", "Cota por filho ou equiparado — remuneração até R$ 1.980,38", "S5",
         lo="0.00", hi="1980.38", flat="67.54"),
    # ── 6. FGTS (A3) — employer deposit, never deducted from net ──────────────
    _row(BR_FGTS_RATE_RULE, "ORDINARY", "FGTS — 8% da remuneração", "A3", rate="8"),
    _row(BR_FGTS_RATE_RULE, "APPRENTICE", "FGTS — contrato de aprendizagem 2%", "A3", rate="2"),
    # ── 7. Employer CPP (A2) and the 2026 CPRB transition (S8) ────────────────
    _row(BR_CPP_RATE_RULE, "STANDARD", "CPP — 20% (Lei 8.212 art. 22 I)", "A2", rate="20"),
    _row(BR_CPP_RATE_RULE, "FINANCIAL_ADDON", "CPP adicional instituições financeiras — 2,5% (art. 22 §1)", "A2",
         rate="2.5"),
    _row(BR_CPP_RATE_RULE, "CPRB_2026", "CPRB 2026 — 50% das alíquotas do art. 22 I (Lei 14.973 art. 9-A II)", "S8",
         rate="10"),
    _row(BR_CPP_RATE_RULE, "CPRB_2026_REVENUE_FACTOR", "CPRB 2026 — 60% das alíquotas dos arts. 7-A/8-A", "S8",
         rate="60"),
    # ── 8. Vale-Transporte max deduction 6% (A5, Lei 7.418/1985 art. 4) ────────
    _row(BR_VT_RATE_RULE, "MAX_DEDUCTION", "Vale-Transporte — desconto máximo 6% do salário-base", "A5", rate="6"),
    # ── 9. Working-time rules (A6 CLT arts. 59/73, A7 Lei 605/1949) ───────────
    _row(BR_LABOR_RULE, "OVERTIME_50", "Hora extra 50% (CLT art. 59 §1)", "A6", rate="50"),
    _row(BR_LABOR_RULE, "OVERTIME_100", "Hora extra 100% (CLT art. 59 §1 — domingos/feriados)", "A6", rate="100"),
    _row(BR_LABOR_RULE, "NIGHT_PREMIUM", "Adicional noturno 20% (CLT art. 73)", "A6", rate="20"),
    _row(BR_LABOR_RULE, "NIGHT_HOUR_MINUTES", "Hora noturna legal 52m30s (CLT art. 73)", "A6", flat="52.5"),
    _row(BR_LABOR_RULE, "DSR", "DSR sobre variáveis (Lei 605/1949 art. 7)", "A7", flat="1"),
)


class BrazilContentMissing(LookupError):
    """No Brazil statutory content covers the requested date — the caller must
    BLOCK (BR_CONTENT_YEAR_UNAVAILABLE), never fall back to another year."""


def rows_in_force(rule_type: str, as_of: date) -> Tuple[ContentRow, ...]:
    """The rows of one rule in force on `as_of` (IRRF: the PAYMENT date, BR-014;
    INSS/FGTS: the competence month's first day). Raises when none exist."""
    if not isinstance(as_of, date):
        raise TypeError("as_of must be a date")
    rows = tuple(r for r in BR_CONTENT_ROWS if r.rule_type == rule_type and r.effective_from <= as_of
                 and (r.effective_to is None or as_of <= r.effective_to))
    if not rows:
        raise BrazilContentMissing(f"BR_CONTENT_YEAR_UNAVAILABLE: no {rule_type} content in force on {as_of.isoformat()}")
    return rows


def row_in_force(rule_type: str, key: str, as_of: date) -> ContentRow:
    for row in rows_in_force(rule_type, as_of):
        if row.key == key:
            return row
    raise BrazilContentMissing(f"BR_CONTENT_YEAR_UNAVAILABLE: no {rule_type}/{key} in force on {as_of.isoformat()}")


def _pct(row: ContentRow) -> Decimal:
    return row.rate_pct / D("100")


# ── Derived constants (2026) — kept for the draft engine and existing callers ─
_AS_OF_2026 = date(2026, 1, 1)

# 1. Minimum wage
MINIMUM_WAGE_MONTHLY = row_in_force(BR_MIN_WAGE_RULE, "MONTHLY", _AS_OF_2026).flat_amount
MINIMUM_WAGE_DAILY = row_in_force(BR_MIN_WAGE_RULE, "DAILY", _AS_OF_2026).flat_amount
MINIMUM_WAGE_HOURLY = row_in_force(BR_MIN_WAGE_RULE, "HOURLY", _AS_OF_2026).flat_amount

# 2. Employee INSS: (lower, upper, marginal rate as a fraction, full-band contribution).
INSS_2026_BRACKETS: Tuple[Tuple[Decimal, Decimal, Decimal, Decimal], ...] = tuple(
    (r.min_amount, r.max_amount, _pct(r), (r.max_amount - r.min_amount) * _pct(r))
    for r in rows_in_force(BR_INSS_BAND_RULE, _AS_OF_2026)
)
INSS_CEILING = INSS_2026_BRACKETS[-1][1]


def inss_maximum(brackets=INSS_2026_BRACKETS) -> Decimal:
    """Maximum employee contribution = every band filled to the ceiling, the
    exact total rounded ONCE (decision D1). Never stored separately (BR-K1)."""
    return sum((b[3] for b in brackets), D("0")).quantize(D("0.01"), rounding=ROUND_HALF_UP)


MAX_INSS_CONTRIBUTION = inss_maximum()
# Published 2026 maximum (INSS / secondary press, reconciled against S1's bands).
# A content edit that changes the bands without this figure fails at import.
PUBLISHED_INSS_MAXIMUM_2026 = D("988.09")
if MAX_INSS_CONTRIBUTION != PUBLISHED_INSS_MAXIMUM_2026:  # pragma: no cover - content guard
    raise RuntimeError(f"Brazil INSS maximum {MAX_INSS_CONTRIBUTION} disagrees with the published "
                       f"{PUBLISHED_INSS_MAXIMUM_2026} — the S1 bands were edited inconsistently")

# 3. IRRF: (lower, upper|None, rate fraction, parcela a deduzir)
IRRF_2026_TABLE: Tuple[Tuple[Decimal, Optional[Decimal], Decimal, Decimal], ...] = tuple(
    (r.min_amount, r.max_amount, _pct(r), r.flat_amount)
    for r in rows_in_force(BR_IRRF_TABLE_RULE, _AS_OF_2026) if r.key.startswith("T")
)
IRRF_DEPENDENT_DEDUCTION = row_in_force(BR_IRRF_TABLE_RULE, "DEDUCTION_DEPENDENT", _AS_OF_2026).flat_amount
IRRF_SIMPLIFIED_MONTHLY_DEDUCTION = row_in_force(BR_IRRF_TABLE_RULE, "DEDUCTION_SIMPLIFIED", _AS_OF_2026).flat_amount

_zero_band = row_in_force(BR_IRRF_REDUCTION_RULE, "ZERO_BAND", _AS_OF_2026)
_phase_out = row_in_force(BR_IRRF_REDUCTION_RULE, "PHASE_OUT", _AS_OF_2026)
IRRF_2026_REDUCTION_ZERO_CEILING = _zero_band.max_amount
IRRF_2026_REDUCTION_MAX_ZERO = _zero_band.flat_amount
IRRF_2026_REDUCTION_PHASE_CEILING = _phase_out.max_amount
IRRF_2026_REDUCTION_A = _phase_out.flat_amount
IRRF_2026_REDUCTION_B = _pct(_phase_out)

# 4. Salário-família
_sf = row_in_force(BR_SAL_FAMILIA_RULE, "QUOTA", _AS_OF_2026)
SALARIO_FAMILIA_CEILING = _sf.max_amount
SALARIO_FAMILIA_QUOTA = _sf.flat_amount

# 5. Employer CPP, CPRB transition, FGTS
STANDARD_CPP_RATE = _pct(row_in_force(BR_CPP_RATE_RULE, "STANDARD", _AS_OF_2026))
FINANCIAL_SECTOR_CPP_ADDON = _pct(row_in_force(BR_CPP_RATE_RULE, "FINANCIAL_ADDON", _AS_OF_2026))
CPRB_2026_CPP_RATE = _pct(row_in_force(BR_CPP_RATE_RULE, "CPRB_2026", _AS_OF_2026))
CPRB_2026_REVENUE_FACTOR = _pct(row_in_force(BR_CPP_RATE_RULE, "CPRB_2026_REVENUE_FACTOR", _AS_OF_2026))
if CPRB_2026_CPP_RATE != STANDARD_CPP_RATE * D("0.5"):  # pragma: no cover - content guard
    raise RuntimeError("CPRB 2026 CPP rate must be 50% of the standard CPP rate (Lei 14.973, S8)")
FGTS_ORDINARY_RATE = _pct(row_in_force(BR_FGTS_RATE_RULE, "ORDINARY", _AS_OF_2026))
FGTS_APPRENTICE_RATE = _pct(row_in_force(BR_FGTS_RATE_RULE, "APPRENTICE", _AS_OF_2026))

# Not yet sourced from a saved, VERIFIED document — kept for the draft engine
# only and NEVER seeded into a pack (Phase 7 / Phase 10 will source them).
CPRB_2026_SERVICE_RETENTION = D("0.035")         # UNSOURCED
FGTS_TERMINATION_FINE_RATE = D("0.40")           # UNSOURCED (Phase 7)
FGTS_MUTUAL_TERMINATION_FINE_RATE = D("0.20")    # UNSOURCED (Phase 7)
VALE_TRANSPORTE_MAX_DEDUCTION_PCT = D("0.06")    # UNSOURCED (Phase 5, Lei 7.418)


# ── Date-driven accessors (Phase 5 — BR-001 fail-closed) ──────────────────────
# The constants above are pinned to 2026 (_AS_OF_2026) for the draft engine and
# existing callers. The Phase 5 engine resolves each rule from the row actually
# in force on the correct date (INSS/FGTS/SF/min-wage: the competence month's
# first day; IRRF: the payment date — BR-014) and BLOCKS via BrazilContentMissing
# when no row covers it, never falling back to another year. Every accessor
# returns the same shape the pinned constants do, so the engine treats the two
# identically.

def inss_brackets(as_of: date) -> Tuple[Tuple[Decimal, Decimal, Decimal, Decimal], ...]:
    """(lower, upper, marginal rate as a FRACTION, full-band contribution) rows
    of the employee INSS table in force on `as_of`."""
    return tuple((r.min_amount, r.max_amount, _pct(r), (r.max_amount - r.min_amount) * _pct(r))
                 for r in rows_in_force(BR_INSS_BAND_RULE, as_of))


def inss_ceiling(as_of: date) -> Decimal:
    return inss_brackets(as_of)[-1][1]


def inss_maximum_on(as_of: date) -> Decimal:
    """The employee-INSS maximum, summed over the bands in force on `as_of` and
    rounded once (decision D1)."""
    total = D("0")
    for row in rows_in_force(BR_INSS_BAND_RULE, as_of):
        total += (row.max_amount - row.min_amount) * _pct(row)
    return total.quantize(D("0.01"), rounding=ROUND_HALF_UP)


def irrf_table(as_of: date) -> Tuple[Tuple[Decimal, Optional[Decimal], Decimal, Decimal], ...]:
    """(lower, upper, marginal rate as a FRACTION, deductible parcel) rows of
    the monthly IRRF table in force on the PAYMENT date `as_of` (BR-014)."""
    return tuple((r.min_amount, r.max_amount, _pct(r), r.flat_amount)
                 for r in rows_in_force(BR_IRRF_TABLE_RULE, as_of) if r.key.startswith("T"))


def irrf_deduction_dependent(as_of: date) -> Decimal:
    return row_in_force(BR_IRRF_TABLE_RULE, "DEDUCTION_DEPENDENT", as_of).flat_amount


def irrf_deduction_simplified(as_of: date) -> Decimal:
    return row_in_force(BR_IRRF_TABLE_RULE, "DEDUCTION_SIMPLIFIED", as_of).flat_amount


def irrf_reduction_params(as_of: date) -> Tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    """(zero_ceiling, max_zero_reduction, phase_ceiling, A, B) for the Law
    15.270/2025 monthly reduction in force on the payment date `as_of`."""
    zero = row_in_force(BR_IRRF_REDUCTION_RULE, "ZERO_BAND", as_of)
    phase = row_in_force(BR_IRRF_REDUCTION_RULE, "PHASE_OUT", as_of)
    return (zero.max_amount, zero.flat_amount, phase.max_amount, phase.flat_amount, _pct(phase))


def salario_familia_params(as_of: date) -> Tuple[Decimal, Decimal]:
    """(ceiling, quota-per-dependent) in force on the competence month."""
    sf = row_in_force(BR_SAL_FAMILIA_RULE, "QUOTA", as_of)
    return (sf.max_amount, sf.flat_amount)


def minimum_wage(as_of: date, key: str = "MONTHLY") -> Decimal:
    """The statutory minimum wage (MONTHLY/DAILY/HOURLY) in force on `as_of`."""
    return row_in_force(BR_MIN_WAGE_RULE, key, as_of).flat_amount


def fgts_rates(as_of: date) -> Tuple[Decimal, Decimal]:
    """(ordinary, apprentice) FGTS deposit rates as FRACTIONS on `as_of`."""
    return (_pct(row_in_force(BR_FGTS_RATE_RULE, "ORDINARY", as_of)),
            _pct(row_in_force(BR_FGTS_RATE_RULE, "APPRENTICE", as_of)))


def cpp_rates(as_of: date) -> Tuple[Decimal, Decimal, Decimal]:
    """(standard, financial add-on, CPRB-2026 transition) employer CPP rates as
    FRACTIONS in force on `as_of`."""
    return (_pct(row_in_force(BR_CPP_RATE_RULE, "STANDARD", as_of)),
            _pct(row_in_force(BR_CPP_RATE_RULE, "FINANCIAL_ADDON", as_of)),
            _pct(row_in_force(BR_CPP_RATE_RULE, "CPRB_2026", as_of)))


def vale_transporte_max_deduction_pct(as_of: date) -> Decimal:
    """Vale-Transporte maximum deduction as a FRACTION (0.06 = 6%) in force on
    the competence month."""
    return _pct(row_in_force(BR_VT_RATE_RULE, "MAX_DEDUCTION", as_of))


def labor_rates(as_of: date) -> Tuple[Decimal, Decimal, Decimal, Decimal, bool]:
    """(overtime_50_pct, overtime_100_pct, night_premium_pct, night_hour_minutes, dsr_flag)
    as FRACTIONS/flag in force on the competence month."""
    ot_50 = _pct(row_in_force(BR_LABOR_RULE, "OVERTIME_50", as_of))
    ot_100 = _pct(row_in_force(BR_LABOR_RULE, "OVERTIME_100", as_of))
    night = _pct(row_in_force(BR_LABOR_RULE, "NIGHT_PREMIUM", as_of))
    night_min = row_in_force(BR_LABOR_RULE, "NIGHT_HOUR_MINUTES", as_of).flat_amount
    dsr = bool(row_in_force(BR_LABOR_RULE, "DSR", as_of).flat_amount)
    return (ot_50, ot_100, night, night_min, dsr)


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



# ── Content signature (BR-003, BR-K7) ─────────────────────────────────────────
# One SHA-256 over EVERY statutory row and every rubric, serialised canonically
# (sorted keys, decimal strings). Stamped on the seeded pack's change summary
# and, from Phase 6, on every payslip snapshot; any change to any value changes
# the hash.

def _canonical(value):
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, date):
        return value.isoformat()
    return value


def content_payload() -> dict:
    return {
        "spec": BRAZIL_SPEC_VERSION,
        "rows": [{k: _canonical(v) for k, v in row._asdict().items()} for row in BR_CONTENT_ROWS],
        "rubrics": [dict(sorted(r.items())) for r in STANDARD_SYSTEM_RUBRICS],
    }


def calculate_content_hash(payload: Optional[dict] = None) -> str:
    """Deterministic SHA-256 over the whole Brazil content (BR-003)."""
    text = json.dumps(payload if payload is not None else content_payload(), sort_keys=True,
                      ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


CONTENT_HASH = calculate_content_hash()


def cited_sources() -> set:
    """Every source code a statutory row cites — each must be VERIFIED in
    docs/brazil/sources/SOURCES_MANIFEST.csv before a pack can be seeded."""
    return {row.source for row in BR_CONTENT_ROWS}
