"""
engine/countries/mexico_content.py
----------------------------------
Mexico statutory content (ZP-MX-ENG-001 v1.0) — pure data, no ORM, no
framework. scripts/seed_mexico_canonical_packs.py writes it into Draft
canonical packs; countries/mexico.py only ever reads the rows those packs
resolve to by pay date / contribution period (MX-003, MX-004), never these
constants directly.

Phase 1 tooling (value-free): every structure below exists, every content
table is EMPTY. Values are added only at transcription, each one taken from a
source file saved under docs/mexico/sources/ (SOURCES_MANIFEST.csv, SHA-256),
flagged needs_g1 and cited by source code — never inferred. A table that is
still empty makes its *_in_force helper raise MexicoContentMissing, so
nothing downstream can mistake "not transcribed" for "zero".

Every *_in_force helper takes the legal date as a REQUIRED argument and never
reads the server clock (MX-004).
"""

from __future__ import annotations

import datetime as _dt
from datetime import date
from decimal import Decimal
from typing import NamedTuple, Optional

SPEC = "ZP-MX-ENG-001 v1.0"
PACK_STATUS = "Draft"  # seeds never create anything else

# (pack id, legal interval start, legal interval end)
MX_2026 = ("MX-PAYROLL-2026", date(2026, 1, 1), date(2026, 12, 31))
# State Impuesto Sobre Nóminas overlays: one pack per state (MX-047),
# parent_pack_id -> the national pack. CDMX only until further states are
# confirmed (Phase 0 decision 7).
MX_ISN_PACK_ID_FORMAT = "MX-ISN-{state}-2026"
MX_ISN_STATES_IN_SCOPE = ("CDMX",)

# TaxSlab discriminators (rule_type). countries/mexico.py reads only rows
# whose rule_type starts with "MX_" (Phase 0 gap assessment §4: MX is NOT a
# _NO_TAX_SLAB_COUNTRIES country).
MX_ISR_TARIFF_RULE = "MX_ISR_TARIFF"
MX_CEAV_BAND_RULE = "MX_CEAV_BAND"
MX_MIN_WAGE_RULE = "MX_MIN_WAGE"
MX_VACATION_DAYS_RULE = "MX_VACATION_DAYS"
MX_WORKWEEK_RULE = "MX_WORKWEEK"
MX_SLAB_RULES = (MX_ISR_TARIFF_RULE, MX_CEAV_BAND_RULE, MX_MIN_WAGE_RULE, MX_VACATION_DAYS_RULE, MX_WORKWEEK_RULE)

# Art. 96 payment periods (spec §4: daily/work-output, 7-, 10-, 15-day and
# monthly) — TaxSlab.filing_status of an MX_ISR_TARIFF row.
MX_ISR_PERIODS = ("DAILY", "WEEKLY_7", "DECENAL_10", "QUINCENAL_15", "MONTHLY")

# Only this year's CEAV bands are seeded into MX-PAYROLL-2026; the full
# 2023–2030 schedule stays content-only (Phase 1 decision Q4, MX-029).
MX_CEAV_SEEDED_YEAR = 2026
MX_CEAV_SCHEDULE_YEARS = tuple(range(2023, 2031))

# Label marker every seeded row carries until the human G1 review signs it.
PENDING_G1 = "[PENDING G1]"
PENDING_G2 = "[PENDING G2]"

# Evidence register — spec §22 "Official evidence register — reviewed for
# 2026 design", codes and titles verbatim.
SOURCE_REFERENCES = (
    ("S1", "SAT — RMF 2026 / Annex 8"),
    ("S2", "SAT — Annex 8 RMF 2026"),
    ("S3", "DOF — 2026 employment-subsidy decree"),
    ("S4", "SAT — Payroll receipt / CFDI"),
    ("S5", "SAT — salary withholding remittance"),
    ("S6", "INEGI — UMA 2026"),
    ("S7", "INEGI — UMA 2025"),
    ("S8", "CONASAMI — 2026 minimum wages"),
    ("S9", "DOF — 2026 minimum wage resolution"),
    ("S10", "IMSS — Social Security Law"),
    ("S11", "2020 pension-reform decree"),
    ("S12", "IMSS — SUA"),
    ("S13", "IMSS — affiliation movements"),
    ("S14", "IMSS — work-risk premium"),
    ("S15", "INFONAVIT — employer contribution"),
    ("S16", "INFONAVIT — SUA"),
    ("S17", "STPS — 40-hour workweek transition"),
    ("S18", "DOF — workweek reform transition"),
    ("S19", "PROFEDET — vacations"),
    ("S20", "PROFEDET — aguinaldo"),
    ("S21", "SAT — PTU 2026"),
    ("S22", "Mexico City Fiscal Code 2026"),
    ("S23", "DOF — 2025 Federal Personal Data Protection Law"),
)
SOURCE_CODES = tuple(code for code, _ in SOURCE_REFERENCES)
# Extension of the §22 register — docs/mexico/MEXICO_SPEC_ADDENDUM_SOURCES.md,
# PENDING SPEC-OWNER APPROVAL.
ADDENDUM_SOURCE_REFERENCES = (
    ("S24", "Ley del Impuesto sobre la Renta (LISR), Art. 93"),
    ("S25", "Reglamento de la LISR (RLISR), Art. 174"),
    ("S26", "Ley Federal del Trabajo (LFT)"),
    ("S27", "Ley del INFONAVIT (LIFNVT), Art. 29"),
    ("S28", "SAT — Complemento de Nómina 1.2 catalog workbook + nomina12.xsd"),
    ("S29", "Reglamento de la LSS en materia de Afiliación, Clasificación de Empresas, Recaudación y "
            "Fiscalización (RACERF)"),
    ("S30", "SAT — CFDI 4.0 catalog workbook (catCFDI: c_RegimenFiscal, c_CodigoPostal) — Anexo 20"),
    ("S31", "RENAPO — CURP structure and check-digit rules (instructivo normativo)"),
    ("S32", "IMSS — NSS (Número de Seguridad Social) structure and check digit"),
    ("S33", "Banco de México / ABM — CLABE 18-digit structure and check digit"),
)
ALL_SOURCE_CODES = SOURCE_CODES + tuple(code for code, _ in ADDENDUM_SOURCE_REFERENCES)

# Release gates (spec §22). Live Mexican payroll stays disabled until every
# gate is evidenced and the registry row leaves PLANNED.
GATES = (
    ("G1", "ISR / CFDI"),
    ("G2", "IMSS / SUA"),
    ("G3", "INFONAVIT"),
    ("G4", "State ISN"),
    ("G5", "Labor"),
    ("G6", "External operations"),
    ("G7", "Security/privacy"),
    ("G8", "Parallel payroll"),
)


# ── Scalar engine parameter keys ──────────────────────────────────────────
# key -> (kind, label, scope). Names only — every one comes from a concept
# the spec itself names (§2, §5, §7–§10, §15, §17, Phase 0 decision 4); no
# value is implied. The seed refuses a content row whose key is not listed.
# Special-pay ISR exemption keys (LISR Art. 93 / RLISR Art. 174, S24/S25)
# are named at transcription from the saved text, not anticipated here.
# scope: "national" rows live in MX-PAYROLL-2026; "state" rows live in a
# state ISN pack and are never required of the national pack.
MX_PARAMETER_KEYS = {
    # UMA (spec §2; S6/S7) — dated rows: the 2025 value until 31 Jan 2026.
    "mx_uma_daily": ("amount", "UMA — daily", "national"),
    "mx_uma_monthly": ("amount", "UMA — monthly", "national"),
    "mx_uma_annual": ("amount", "UMA — annual", "national"),
    # Employment subsidy (spec §5; S3) — formula content, dated rows.
    "mx_subsidy_rate_pct": ("employee_pct", "Employment subsidy — % of monthly UMA", "national"),
    "mx_subsidy_income_ceiling_monthly": ("amount", "Employment subsidy — monthly income ceiling", "national"),
    "mx_subsidy_period_days_divisor": ("amount", "Employment subsidy — days divisor for periods < 1 month", "national"),
    # SBC ceiling (spec §7; S10) as a multiple of the UMA in force (MX-021).
    "mx_sbc_max_uma_multiple": ("amount", "SBC maximum — multiple of UMA", "national"),
    # IMSS branches (spec §8; S10) — each branch and side is its own row (MX-023).
    "mx_imss_em_fixed_quota_er_pct": ("employer_pct", "IMSS E&M fixed quota — employer % of daily UMA", "national"),
    "mx_imss_em_excess_threshold_uma": ("amount", "IMSS E&M excess — threshold in UMA", "national"),
    "mx_imss_em_excess_er_pct": ("employer_pct", "IMSS E&M excess over threshold — employer", "national"),
    "mx_imss_em_excess_ee_pct": ("employee_pct", "IMSS E&M excess over threshold — employee", "national"),
    "mx_imss_em_cash_er_pct": ("employer_pct", "IMSS E&M cash benefits — employer", "national"),
    "mx_imss_em_cash_ee_pct": ("employee_pct", "IMSS E&M cash benefits — employee", "national"),
    "mx_imss_em_pensioner_er_pct": ("employer_pct", "IMSS E&M pensioner medical — employer", "national"),
    "mx_imss_em_pensioner_ee_pct": ("employee_pct", "IMSS E&M pensioner medical — employee", "national"),
    "mx_imss_iv_er_pct": ("employer_pct", "IMSS Invalidez y Vida — employer", "national"),
    "mx_imss_iv_ee_pct": ("employee_pct", "IMSS Invalidez y Vida — employee", "national"),
    "mx_imss_guarderias_er_pct": ("employer_pct", "IMSS Guarderías y Prestaciones Sociales — employer", "national"),
    "mx_imss_retiro_er_pct": ("employer_pct", "IMSS Retiro — employer", "national"),
    "mx_imss_ceav_ee_pct": ("employee_pct", "IMSS Cesantía y Vejez — employee", "national"),
    # CEAV lowest band (Phase 0 decision 4) — which minimum wage anchors the
    # "1.00 minimum wage" band. A text parameter, [PENDING G2] until SUA
    # reconciliation; Phase 5 blocks only ZLFN employees in that band.
    "mx_ceav_lowest_band_min_wage_ref": ("text", "CEAV lowest band — minimum-wage reference", "national"),
    # INFONAVIT (spec §10; S27, S15 cross-check).
    "mx_infonavit_er_pct": ("employer_pct", "INFONAVIT housing contribution — employer", "national"),
    # Benefit floors (spec §17; S26, S19/S20 cross-checks).
    "mx_aguinaldo_min_days": ("amount", "Aguinaldo — statutory minimum days", "national"),
    "mx_vacation_premium_min_pct": ("employee_pct", "Vacation premium — statutory minimum %", "national"),
    "mx_sunday_premium_min_pct": ("employee_pct", "Sunday premium — statutory minimum %", "national"),
    # Work-risk premium range (MX-024; Phase 3 Q3) — the legal minimum and
    # maximum an employer's registration-scoped premium may take. Expected in
    # LSS Art. 74 (S10); confirmed from the saved text at transcription. An
    # employer premium is never approved while either is missing.
    "mx_risk_premium_min_pct": ("employer_pct", "Work-risk premium — legal minimum %", "national"),
    "mx_risk_premium_max_pct": ("employer_pct", "Work-risk premium — legal maximum %", "national"),
    # Phase 5 engine rules (names only; each value is transcribed from its
    # source — the vocabularies are listed in engine/jurisdictions/mexico).
    # Text rules: rounding (Q2) and the SBC floor (Q5) are REQUIRED for
    # activation (MX_REQUIRED_TEXT_KEYS); the others BLOCK only the case that needs them.
    "mx_rounding_rule": ("text", "Monetary rounding — mode and quantum (e.g. MODE:QUANTUM)", "national"),
    "mx_sbc_min_rule": ("text", "SBC floor rule (S10)", "national"),
    "mx_subsidy_remainder_rule": ("text", "Employment subsidy above ISR — remainder handling (S3)", "national"),
    "mx_infonavit_percentage_basis": ("text", "INFONAVIT credit, PERCENTAGE method — basis (S27/S15)", "national"),
    "mx_infonavit_fixed_amount_basis": ("text", "INFONAVIT credit, FIXED_AMOUNT method — basis (S27/S15)", "national"),
    # Overtime tiers (spec §16; S26 / S18) — dated rows, the reform phases them.
    "mx_overtime_double_weekly_max_hours": ("amount", "Overtime — hours per week paid at the first tier", "national"),
    "mx_overtime_double_multiplier": ("amount", "Overtime — first-tier pay multiplier", "national"),
    "mx_overtime_triple_multiplier": ("amount", "Overtime — second-tier pay multiplier", "national"),
    # State ISN (spec §15; S22 for CDMX) — lives in MX-ISN-<STATE>-2026 only.
    "mx_isn_rate_pct": ("employer_pct", "State ISN — rate", "state"),
}
MX_PARAMETER_KINDS = ("amount", "employee_pct", "employer_pct", "text")
MX_PENDING_G2_KEYS = ("mx_ceav_lowest_band_min_wage_ref",)
# Text rules the national pack must carry before it can be activated
# (Phase 5 Q11); every other text key blocks only the case that needs it.
MX_REQUIRED_TEXT_KEYS = ("mx_rounding_rule", "mx_sbc_min_rule")
# Non-text keys the engine BLOCKS on per case (overtime is paid only from
# approved hours) — not required for activation.
MX_PER_CASE_KEYS = ("mx_overtime_double_weekly_max_hours", "mx_overtime_double_multiplier",
                    "mx_overtime_triple_multiplier")


# ── Content row shapes ────────────────────────────────────────────────────
# Every row cites its source code (S1–S27) and a page / article reference
# inside that saved file, and carries needs_g1 until the human G1 review.

class ScalarRow(NamedTuple):
    key: str                          # MX_PARAMETER_KEYS name
    employee_pct: Optional[str]
    employer_pct: Optional[str]
    flat_amount: Optional[str]
    text_value: Optional[str]
    effective_from: Optional[date]    # row-level legal window (None = pack window)
    effective_to: Optional[date]
    source: str                       # S-code
    source_ref: str                   # page / article in the saved file
    needs_g1: bool = True
    pending_g2: bool = False


class IsrBracket(NamedTuple):
    period: str                       # MX_ISR_PERIODS
    lower: str                        # límite inferior
    upper: Optional[str]              # límite superior; None = "en adelante"
    fixed_quota: str                  # cuota fija
    rate_pct: str                     # % sobre excedente del límite inferior
    effective_from: Optional[date]
    effective_to: Optional[date]
    source: str
    source_ref: str
    needs_g1: bool = True


class MinWageRow(NamedTuple):
    code: str                         # GENERAL / ZLFN / professional code
    kind: str                         # ZONE / PROFESSION
    description: str
    daily_amount: str
    zone: Optional[str]               # zone a professional minimum applies in
    effective_from: Optional[date]
    effective_to: Optional[date]
    source: str
    source_ref: str
    needs_g1: bool = True


class ZlfnMunicipality(NamedTuple):
    state: str
    municipality: str
    source: str
    source_ref: str


class CeavBand(NamedTuple):
    year: int
    lower_multiple: str
    lower_unit: str                   # "SM" / "UMA", as the decree states it
    upper_multiple: Optional[str]     # None = open-ended top band
    upper_unit: Optional[str]
    employer_pct: str
    effective_from: date
    effective_to: date
    source: str
    source_ref: str
    needs_g1: bool = True


class WorkweekRow(NamedTuple):
    ordinary_weekly_max_hours: str
    overtime_rules: tuple             # ((name, value), …) exactly as the decree words them
    effective_from: date
    effective_to: Optional[date]
    source: str
    source_ref: str
    needs_g1: bool = True


class VacationDaysRow(NamedTuple):
    service_year_from: int
    service_year_to: Optional[int]    # None = open-ended
    days: str
    effective_from: Optional[date]
    effective_to: Optional[date]
    source: str
    source_ref: str
    needs_g1: bool = True


# ── Content tables — EMPTY until "start transcription" ────────────────────
MX_SCALAR_CONTENT: tuple = ()
MX_ISR_TARIFFS: tuple = ()
MX_MIN_WAGES: tuple = ()
MX_ZLFN_MUNICIPALITIES: tuple = ()
MX_CEAV_SCHEDULE: tuple = ()          # 2023–2030; only MX_CEAV_SEEDED_YEAR is seeded
MX_WORKWEEK: tuple = ()
MX_VACATION_DAYS: tuple = ()
MX_ISN_CONTENT: dict = {state: () for state in MX_ISN_STATES_IN_SCOPE}   # state -> tuple[ScalarRow]

# Filing-calendar due-date rules (Phase 2). Each is transcribed only from
# the saved primary-law text (LISR Art. 96 / S24, LSS Arts. 39 and 74 / S10,
# Ley del INFONAVIT Art. 35 / S27, LFT Arts. 87 and 122 / S26, current CDMX
# Fiscal Code / S22) — a rule not confirmed in the saved text is not listed.
class FilingRule(NamedTuple):
    report_type: str                  # e.g. MX_ISR_WITHHOLDING
    period_label_format: str          # e.g. "{year}-{month:02d}"
    frequency: str                    # MONTHLY / BIMONTHLY / ANNUAL
    due_rule: str                     # rule wording, as the law states it
    due_day: Optional[int]            # day of the following month / of the due month
    due_month: Optional[int]          # fixed month for ANNUAL rules
    state: Optional[str]              # set only for a state ISN filing
    source: str
    source_ref: str
    needs_g1: bool = True


MX_FILING_CALENDAR: tuple = ()        # EMPTY until each rule is confirmed in its saved source


# Validity window of an employer's annual work-risk premium (Phase 3 Q3,
# MX-024/MX-026). Spec MX-026 says the premium is determined in February and
# applies to the following IMSS premium period; the exact start (expected 1
# March, ending the day before the next start) is transcribed from whichever
# saved source states it — S10 (LSS), S14 or S29 (RACERF) — never from the
# spec text. None = not transcribed: no premium can be approved.
class RiskPremiumPeriodRule(NamedTuple):
    start_month: int                  # first month of the premium period
    start_day: int                    # first day; the period ends the day before the next start
    source: str
    source_ref: str
    needs_g1: bool = True


MX_RISK_PREMIUM_PERIOD: Optional[RiskPremiumPeriodRule] = None


# The 32 federal entities (ISO 3166-2:MX subdivisions; Mexico City keeps the
# "CDMX" code its ISN pack already uses). Geography, not statutory content.
MX_FEDERAL_ENTITIES = (
    ("AGU", "Aguascalientes"), ("BCN", "Baja California"), ("BCS", "Baja California Sur"),
    ("CAM", "Campeche"), ("CHP", "Chiapas"), ("CHH", "Chihuahua"), ("CDMX", "Ciudad de México"),
    ("COA", "Coahuila"), ("COL", "Colima"), ("DUR", "Durango"), ("GUA", "Guanajuato"), ("GRO", "Guerrero"),
    ("HID", "Hidalgo"), ("JAL", "Jalisco"), ("MEX", "Estado de México"), ("MIC", "Michoacán"),
    ("MOR", "Morelos"), ("NAY", "Nayarit"), ("NLE", "Nuevo León"), ("OAX", "Oaxaca"), ("PUE", "Puebla"),
    ("QUE", "Querétaro"), ("ROO", "Quintana Roo"), ("SLP", "San Luis Potosí"), ("SIN", "Sinaloa"),
    ("SON", "Sonora"), ("TAB", "Tabasco"), ("TAM", "Tamaulipas"), ("TLA", "Tlaxcala"), ("VER", "Veracruz"),
    ("YUC", "Yucatán"), ("ZAC", "Zacatecas"),
)

# Documented source-wins exceptions (Phase 1 plan §6 change 1): an ISR row
# that fails the quota-arithmetic check but matches S2 exactly.
# (period, bracket index starting at 1) -> transcription-log reference.
MX_ISR_ARITHMETIC_EXCEPTIONS: dict = {}

# Phase 6 (D3): SAT c_PeriodicidadPago code (S28 catalog) -> Art. 96 payment
# period (MX_ISR_PERIODS). EMPTY until transcribed from the saved S28 catalog
# workbook; while empty every Mexican calculation BLOCKS
# (MX_PAY_FREQUENCY_MAPPING_MISSING) — a code is never read as a period by guess.
MX_PAY_FREQUENCY_ISR_PERIOD: dict = {}


# ── Date-selected readers (MX-004) ────────────────────────────────────────

class MexicoContentMissing(LookupError):
    """No transcribed content covers the requested date — fail closed."""


def _check_date(as_of) -> None:
    # _dt.date, not the module-level name: a test may stand in a clock-less
    # `date` to prove no helper reads the server clock.
    if not isinstance(as_of, _dt.date):
        raise TypeError("as_of must be a date (the pay date / contribution period), never implied")


def _row_in_window(eff_from, eff_to, as_of: date) -> bool:
    if eff_from is not None and as_of < eff_from:
        return False
    if eff_to is not None and as_of > eff_to:
        return False
    return True


def _require(rows, what: str, as_of: date):
    if not rows:
        raise MexicoContentMissing(f"no transcribed Mexico content for {what} on {as_of.isoformat()}")
    return rows


def scalar_rows_in_force(as_of: date) -> dict:
    """{key: ScalarRow} for national scalar rows legally in force on `as_of`.
    Two rows of one key in force on the same date is a content error."""
    _check_date(as_of)
    out = {}
    for row in MX_SCALAR_CONTENT:
        if _row_in_window(row.effective_from, row.effective_to, as_of):
            if row.key in out:
                raise ValueError(f"two {row.key} rows in force on {as_of.isoformat()}")
            out[row.key] = row
    return _require(out, "scalar parameters", as_of)


def _scalar_value(row: ScalarRow):
    for value in (row.flat_amount, row.employee_pct, row.employer_pct):
        if value is not None:
            return Decimal(value)
    return row.text_value


def uma_in_force(as_of: date) -> dict:
    """{"daily", "monthly", "annual"} UMA values in force on `as_of` — the
    2025 UMA until 31 Jan 2026, the 2026 UMA from 1 Feb (MX-004, MX-021)."""
    _check_date(as_of)
    rows = {k: r for k, r in scalar_rows_in_force(as_of).items() if k.startswith("mx_uma_")}
    out = {key[len("mx_uma_"):]: _scalar_value(row) for key, row in _require(rows, "UMA", as_of).items()}
    return out


def subsidy_in_force(as_of: date) -> dict:
    """Employment-subsidy parameters in force on `as_of` (MX-012/MX-013)."""
    _check_date(as_of)
    rows = {k: r for k, r in scalar_rows_in_force(as_of).items() if k.startswith("mx_subsidy_")}
    return {key: _scalar_value(row) for key, row in _require(rows, "employment subsidy", as_of).items()}


def isr_tariff_in_force(period: str, as_of: date) -> list:
    """Art. 96 brackets for one payment period, ordered by lower limit (MX-008)."""
    _check_date(as_of)
    if period not in MX_ISR_PERIODS:
        raise ValueError(f"unknown ISR payment period {period!r}")
    rows = [b for b in MX_ISR_TARIFFS
            if b.period == period and _row_in_window(b.effective_from, b.effective_to, as_of)]
    return sorted(_require(rows, f"ISR tariff {period}", as_of), key=lambda b: Decimal(b.lower))


def min_wages_in_force(as_of: date) -> list:
    _check_date(as_of)
    rows = [w for w in MX_MIN_WAGES if _row_in_window(w.effective_from, w.effective_to, as_of)]
    return _require(rows, "minimum wages", as_of)


def ceav_bands_in_force(as_of: date) -> list:
    """The CEAV employer bands of the year `as_of` falls in, selected by
    date from the full 2023–2030 schedule (MX-029)."""
    _check_date(as_of)
    rows = [b for b in MX_CEAV_SCHEDULE if _row_in_window(b.effective_from, b.effective_to, as_of)]
    return sorted(_require(rows, "CEAV bands", as_of), key=lambda b: Decimal(b.lower_multiple))


def workweek_in_force(as_of: date) -> WorkweekRow:
    """The statutory weekly maximum in force on `as_of` — 2026 vs the staged
    2027–2030 reductions are selected by date, never by server date (MX-048)."""
    _check_date(as_of)
    rows = [w for w in MX_WORKWEEK if _row_in_window(w.effective_from, w.effective_to, as_of)]
    rows = _require(rows, "workweek limits", as_of)
    if len(rows) > 1:
        raise ValueError(f"two workweek rows in force on {as_of.isoformat()}")
    return rows[0]


def vacation_days_in_force(as_of: date) -> list:
    _check_date(as_of)
    rows = [v for v in MX_VACATION_DAYS if _row_in_window(v.effective_from, v.effective_to, as_of)]
    return sorted(_require(rows, "vacation schedule", as_of), key=lambda v: v.service_year_from)


def isn_rows_in_force(state: str, as_of: date) -> dict:
    """{key: ScalarRow} of a state's ISN pack content in force on `as_of`."""
    _check_date(as_of)
    if state not in MX_ISN_CONTENT:
        raise MexicoContentMissing(f"state {state!r} has no ISN content pack (MX-045)")
    out = {r.key: r for r in MX_ISN_CONTENT[state] if _row_in_window(r.effective_from, r.effective_to, as_of)}
    return _require(out, f"ISN {state}", as_of)


IN_FORCE_HELPERS = (
    scalar_rows_in_force, uma_in_force, subsidy_in_force, min_wages_in_force, ceav_bands_in_force,
    workweek_in_force, vacation_days_in_force,
)


# ── Expected pack content (activation gate 1b-1) ──────────────────────────
# The exact rows a pack must carry, derived from this module the same way the
# seed writes them. Signatures are value tuples, compared as multisets: every
# expected row present, nothing extra.

def _d(value):
    return None if value is None else Decimal(str(value)).normalize()


def _overlaps(eff_from, eff_to, start, end) -> bool:
    return (eff_from is None or eff_from <= end) and (eff_to is None or eff_to >= start)


def rate_signature(key, employee_pct, employer_pct, flat_amount, text_value, effective_from, effective_to) -> tuple:
    return ("RATE", key, _d(employee_pct), _d(employer_pct), _d(flat_amount), text_value or None,
            effective_from, effective_to)


def slab_signature(rule_type, filing_status, min_amount, max_amount, flat_amount, rate_pct, effective_from,
                   effective_to, tax_table_number=None) -> tuple:
    return ("SLAB", rule_type, filing_status, _d(min_amount), _d(max_amount), _d(flat_amount), _d(rate_pct),
            effective_from, effective_to, tax_table_number or None)


def expected_national_signatures(start: date, end: date) -> list:
    _check_date(start)
    _check_date(end)
    out = [rate_signature(r.key, r.employee_pct, r.employer_pct, r.flat_amount, r.text_value, r.effective_from,
                          r.effective_to)
           for r in MX_SCALAR_CONTENT if _overlaps(r.effective_from, r.effective_to, start, end)]
    out += [slab_signature(MX_ISR_TARIFF_RULE, b.period, b.lower, b.upper, b.fixed_quota, b.rate_pct,
                           b.effective_from, b.effective_to)
            for b in MX_ISR_TARIFFS if _overlaps(b.effective_from, b.effective_to, start, end)]
    out += [slab_signature(MX_MIN_WAGE_RULE, w.code, "0", None, w.daily_amount, "0", w.effective_from, w.effective_to)
            for w in MX_MIN_WAGES if _overlaps(w.effective_from, w.effective_to, start, end)]
    out += [slab_signature(MX_CEAV_BAND_RULE, f"{b.lower_multiple}{b.lower_unit}", b.lower_multiple, b.upper_multiple,
                           None, b.employer_pct, b.effective_from, b.effective_to, str(b.year))
            for b in MX_CEAV_SCHEDULE if b.year == MX_CEAV_SEEDED_YEAR]
    out += [slab_signature(MX_WORKWEEK_RULE, "WEEKLY_MAX", "0", None, w.ordinary_weekly_max_hours, "0",
                           w.effective_from, w.effective_to)
            for w in MX_WORKWEEK if _overlaps(w.effective_from, w.effective_to, start, end)]
    out += [slab_signature(MX_VACATION_DAYS_RULE, f"YEAR_{v.service_year_from}", str(v.service_year_from),
                           str(v.service_year_to) if v.service_year_to is not None else None, v.days, "0",
                           v.effective_from, v.effective_to)
            for v in MX_VACATION_DAYS if _overlaps(v.effective_from, v.effective_to, start, end)]
    return out


def expected_state_signatures(state: str, start: date, end: date) -> list:
    _check_date(start)
    _check_date(end)
    return [rate_signature(r.key, r.employee_pct, r.employer_pct, r.flat_amount, r.text_value, r.effective_from,
                           r.effective_to)
            for r in MX_ISN_CONTENT.get(state, ()) if _overlaps(r.effective_from, r.effective_to, start, end)]


# Art. 96 tariffs have 11 brackets per payment period (spec §4 monthly table).
MX_ISR_BRACKETS_PER_PERIOD = 11
