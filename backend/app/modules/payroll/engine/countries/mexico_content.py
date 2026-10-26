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

from . import mexico_rules as _rules   # W1-3: rule objects (special pay), written at transcription

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
    ("S34", "DOF 27-01-2016 — constitutional decree on minimum-wage de-indexation (UMA), Transitorio Tercero"),
    ("S35", "Código Fiscal de la Federación (CFF), Arts. 12 and 20"),
    ("S36", "Ley del ISSSTE, Art. 21 (RCV and housing-fund payment periodicity)"),
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
    # No core-engine reader: required so the pack carries the full S6 UMA set;
    # transcribed rules (annual adjustment, PTU) read it through `content`.
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
    # W3-1: periods shorter than a month — the month's subsidy never exceeds the monthly amount (S3).
    "mx_subsidy_monthly_cap_rule": ("text", "Employment subsidy — monthly cap across a month's payments (S3)",
                                    "national"),
    "mx_infonavit_percentage_basis": ("text", "INFONAVIT credit, PERCENTAGE method — basis (S27/S15)", "national"),
    "mx_infonavit_fixed_amount_basis": ("text", "INFONAVIT credit, FIXED_AMOUNT method — basis (S27/S15)", "national"),
    # Overtime tiers (spec §16; S26 / S18) — dated rows, the reform phases them.
    "mx_overtime_double_weekly_max_hours": ("amount", "Overtime — hours per week paid at the first tier", "national"),
    "mx_overtime_double_multiplier": ("amount", "Overtime — first-tier pay multiplier", "national"),
    "mx_overtime_triple_multiplier": ("amount", "Overtime — second-tier pay multiplier", "national"),
    # W3-2: work on a rest day (LFT Arts. 73, 75) — daily salaries paid on top of the rest day's own salary.
    "mx_rest_day_work_multiplier": ("amount", "Rest-day work — extra daily salaries per day worked", "national"),
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
                    "mx_overtime_triple_multiplier", "mx_rest_day_work_multiplier")


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


# ── Content tables — EMPTY until transcribed ──────────────────────────────
# Batch 1 (2026-10-26): ISR tariffs, UMA, employment subsidy and the pay-
# frequency map. Every other table stays EMPTY until its batch.
# Scalar rows — Batch 1, transcribed 2026-10-26 [PENDING G1]. Dated rows: the
# selector picks the row in force on the legal date (MX-004).
_S6 = "S6/S6_INEGI_UMA_2026.pdf"
_S7 = "S7/S7_INEGI_UMA_2025.pdf"
_S3 = "S3/S3_DOF_Decreto_subsidio_empleo_31122025.html"
_S9 = "S9/S9_DOF_Resolucion_salarios_minimos_2026.html"
_S10 = "S10/S10_IMSS_LSS.pdf"
_S11 = "S11/S11_DIP_LSS_ref25_16dic20.pdf"
_S18 = "S18/S18_DOF_Decreto_LFT_jornada_01052026.html"
_S26 = "S26/S26_DIP_LFT.pdf"
_S27 = "S27/S27_DIP_LIFNVT.pdf"
_UMA25 = (date(2025, 2, 1), date(2026, 1, 31))   # S7: in force from 1 Feb 2025; S6: replaced from 1 Feb 2026
_UMA26 = (date(2026, 2, 1), None)                # S6: in force from 1 Feb 2026
MX_SCALAR_CONTENT: tuple = (
    # UMA (spec §2) — INEGI bulletins, Cuadro 1 "Valor de la UMA" (diario, mensual, anual)
    ScalarRow("mx_uma_daily", None, None, "113.14", None, *_UMA25, _S7,
              "INEGI bulletin 9 Jan 2025, p. 1, Cuadro 1 (diario); in force from 1 Feb 2025; end per S6"),
    ScalarRow("mx_uma_monthly", None, None, "3439.46", None, *_UMA25, _S7,
              "INEGI bulletin 9 Jan 2025, p. 1, Cuadro 1 (mensual); in force from 1 Feb 2025; end per S6"),
    ScalarRow("mx_uma_annual", None, None, "41273.52", None, *_UMA25, _S7,
              "INEGI bulletin 9 Jan 2025, p. 1, Cuadro 1 (anual); in force from 1 Feb 2025; end per S6"),
    ScalarRow("mx_uma_daily", None, None, "117.31", None, *_UMA26, _S6,
              "INEGI bulletin 8 Jan 2026, p. 1, Cuadro 1 (diario); in force from 1 Feb 2026"),
    ScalarRow("mx_uma_monthly", None, None, "3566.22", None, *_UMA26, _S6,
              "INEGI bulletin 8 Jan 2026, p. 1, Cuadro 1 (mensual); in force from 1 Feb 2026"),
    ScalarRow("mx_uma_annual", None, None, "42794.64", None, *_UMA26, _S6,
              "INEGI bulletin 8 Jan 2026, p. 1, Cuadro 1 (anual); in force from 1 Feb 2026"),
    # Employment subsidy (spec §5) — DOF 31-12-2025 decree, in force 1 Jan 2026 (Transitorio PRIMERO)
    ScalarRow("mx_subsidy_rate_pct", "15.59", None, None, None, date(2026, 1, 1), date(2026, 1, 31), _S3,
              "Transitorio SEGUNDO: January 2026, Art. Segundo paras 1, 3-5 — monthly UMA x 15.59% in place of 15.02%"),
    ScalarRow("mx_subsidy_rate_pct", "15.02", None, None, None, date(2026, 2, 1), None, _S3,
              "Art. Segundo, para 1 as reformed: monthly subsidy = monthly UMA x 15.02% (also paras 3-5)"),
    ScalarRow("mx_subsidy_income_ceiling_monthly", None, None, "11492.66", None, date(2026, 1, 1), None, _S3,
              "Art. Segundo, para 1 as reformed: monthly income not exceeding $11,492.66"),
    ScalarRow("mx_subsidy_period_days_divisor", None, None, "30.4", None, date(2026, 1, 1), None, _S3,
              "Art. Segundo, para 3 as reformed: periods under a month — (monthly UMA x %) / 30.4 x days"),
    # Batch 2: the remainder rule is in the BASE decree (DOF 01-05-2024), Art. Segundo para 2, which neither
    # the 31-12-2024 nor the 31-12-2025 decree reformed (both reform paras 1, 3, 4, 5 only). Wording mapped to
    # the engine vocabulary (subsidy.REMAINDER_RULES) — log TL-SUB-2.
    ScalarRow("mx_subsidy_remainder_rule", None, None, None, "NOT_PAYABLE", date(2026, 1, 1), None,
              "S3/S3_DOF_Decreto_subsidio_empleo_01052024.html",
              "Art. Segundo para 2: 'la diferencia no podra aplicarse contra el impuesto que resulte a su cargo "
              "posteriormente, ni se entregara cantidad alguna por concepto del subsidio para el empleo'"),
    # W3-2 (2026-10-26) [PENDING G1]: work on a rest day — log TL-LFT-2.
    ScalarRow("mx_rest_day_work_multiplier", None, None, "2", None, None, None, _S26,
              "Art. 75 para 2: 'tendran derecho a que se les pague, independientemente del salario que les corresponda "
              "por el descanso obligatorio, un salario doble por el servicio prestado', PDF p. 24; Art. 73: 'un "
              "salario doble por el servicio prestado' on a weekly rest day, PDF p. 23 (read as 2 daily salaries "
              "on top of the rest day's own, TL-LFT-2)"),
    # W3-1 (2026-10-26) [PENDING G1]: the monthly cap for periods under a month — log TL-SUB-3.
    ScalarRow("mx_subsidy_monthly_cap_rule", None, None, None, "CAP_AT_MONTHLY_AMOUNT", date(2026, 1, 1), None, _S3,
              "Art. Segundo para 4 as reformed: 'Cuando los pagos por salarios sean por periodos menores a un mes, la "
              "cantidad del subsidio para el empleo que corresponda a la persona trabajadora, no podra exceder el "
              "monto mensual maximo' (read as the month's payments together, TL-SUB-3)"),
    # ── Batch 2 (2026-10-26) [PENDING G1] ──
    # IMSS (spec §8): S10 LSS, consolidated, last reform DOF 15-01-2026. Rates
    # written in words in the LSS are read as numbers (log TL-IMSS-1). Rows
    # marked DERIVED are not printed anywhere: computed from the printed base
    # and the printed annual steps (MX_DERIVED_VALUES, log TL-IMSS-2).
    ScalarRow("mx_imss_em_fixed_quota_er_pct", None, "20.40", None, None, None, None, _S10,
              "DERIVED: Art. 106 I (13.9% of the daily minimum wage) + 1995 LSS Transitorio DECIMO NOVENO "
              "(+0.65 points each 1 July 1998-2007, 10 steps), PDF pp. 35, 110"),
    ScalarRow("mx_imss_em_excess_threshold_uma", None, None, "3", None, None, None, _S10,
              "Art. 106 II: SBC above 'tres veces el salario minimo general diario' (minimum wage read as UMA "
              "under S34 Transitorio Tercero: see TL-IMSS-3), PDF p. 35"),
    ScalarRow("mx_imss_em_excess_er_pct", None, "1.10", None, None, None, None, _S10,
              "DERIVED: Art. 106 II (6% employer) - Transitorio DECIMO NOVENO (0.49 points each 1 July 1998-2007), "
              "PDF pp. 35, 110"),
    ScalarRow("mx_imss_em_excess_ee_pct", "0.40", None, None, None, None, None, _S10,
              "DERIVED: Art. 106 II (2% worker) - Transitorio DECIMO NOVENO (0.16 points each 1 July 1998-2007), "
              "PDF pp. 35, 110"),
    ScalarRow("mx_imss_em_cash_er_pct", None, "0.70", None, None, None, None, _S10,
              "DERIVED: Art. 107 (quota of 1% of SBC; I. employer pays 70% of it), PDF p. 35"),
    ScalarRow("mx_imss_em_cash_ee_pct", "0.25", None, None, None, None, None, _S10,
              "DERIVED: Art. 107 (quota of 1% of SBC; II. worker pays 25% of it), PDF p. 35"),
    ScalarRow("mx_imss_em_pensioner_er_pct", None, "1.05", None, None, None, None, _S10,
              "Art. 25 para 2: employer 'uno punto cero cinco por ciento' of SBC, PDF p. 10"),
    ScalarRow("mx_imss_em_pensioner_ee_pct", "0.375", None, None, None, None, None, _S10,
              "Art. 25 para 2: worker 'cero punto trescientos setenta y cinco por ciento' of SBC, PDF p. 10"),
    ScalarRow("mx_imss_iv_er_pct", None, "1.75", None, None, None, None, _S10,
              "Art. 147: employer 'uno punto setenta y cinco por ciento' of SBC, PDF p. 45"),
    ScalarRow("mx_imss_iv_ee_pct", "0.625", None, None, None, None, None, _S10,
              "Art. 147: worker 'cero punto seiscientos veinticinco por ciento' of SBC, PDF p. 45"),
    ScalarRow("mx_imss_guarderias_er_pct", None, "1", None, None, None, None, _S10,
              "Art. 211: 'uno por ciento sobre el salario base de cotizacion', PDF p. 62"),
    ScalarRow("mx_imss_retiro_er_pct", None, "2", None, None, None, None, _S10,
              "Art. 168 I: employer 'dos por ciento del salario base de cotizacion', PDF p. 51"),
    ScalarRow("mx_imss_ceav_ee_pct", "1.125", None, None, None, None, None, _S10,
              "Art. 168 II b): worker 'uno punto ciento veinticinco por ciento' of SBC, PDF p. 51"),
    ScalarRow("mx_sbc_max_uma_multiple", None, None, "25", None, None, None, _S10,
              "Art. 28: upper limit 'veinticinco veces el salario minimo general' (minimum wage read as UMA "
              "under S34 Transitorio Tercero: see TL-IMSS-3), PDF p. 11"),
    # ── W1-1 (2026-10-26) [PENDING G1] ── the SBC floor (Q5) and the INFONAVIT PERCENTAGE credit basis (Q7),
    # each mapped onto the engine vocabulary (sbc.SBC_MIN_RULES, infonavit.BASIS_RULES) — log TL-SBC-1, TL-INF-2.
    ScalarRow("mx_sbc_min_rule", None, None, None, "RAISE_TO_ZONE_MIN_WAGE", None, None, _S10,
              "Art. 28: SBC 'como limite inferior el salario minimo general del area geografica respectiva' "
              "(a lower limit: an SBC below it is raised to the zone minimum wage, TL-SBC-1), PDF p. 11"),
    ScalarRow("mx_risk_premium_min_pct", None, "0.5", None, None, None, None, _S10,
              "Art. 74 para 2: minimum premium 'cero punto cinco por ciento' of SBC, PDF p. 26"),
    ScalarRow("mx_risk_premium_max_pct", None, "15", None, None, None, None, _S10,
              "Art. 74 para 2: maximum premium 'quince por ciento' of SBC, PDF p. 26"),
    # INFONAVIT (spec §10): S27 Ley del INFONAVIT, last reform DOF 21-02-2025
    ScalarRow("mx_infonavit_er_pct", None, "5", None, None, None, None, _S27,
              "Art. 29 II: employer contribution 'cinco por ciento sobre el salario de los trabajadores', PDF p. 16"),
    ScalarRow("mx_infonavit_percentage_basis", None, None, None, "SBC_TIMES_DAYS", None, None, _S27,
              "Art. 29 III: 'La integracion y calculo de la base salarial para efectos de los descuentos sera la "
              "contenida en la fraccion II del presente articulo'; fr. II: base per 'la Ley del Seguro Social' "
              "(the SBC; the percentage applies to SBC x days of the period, TL-INF-2), PDF p. 16"),
    # Benefit floors (spec §17): S26 LFT, consolidated, last reform DOF 14-05-2026
    ScalarRow("mx_aguinaldo_min_days", None, None, "15", None, None, None, _S26,
              "Art. 87: aguinaldo 'equivalente a quince dias de salario, por lo menos', PDF p. 25"),
    ScalarRow("mx_vacation_premium_min_pct", "25", None, None, None, None, None, _S26,
              "Art. 80: vacation premium 'no menor de veinticinco por ciento', PDF p. 24"),
    ScalarRow("mx_sunday_premium_min_pct", "25", None, None, None, None, None, _S26,
              "Art. 71 para 2 (reformed DOF 01-05-2026): 'prima adicional de un veinticinco por ciento, por lo "
              "menos', PDF p. 23"),
    # Overtime (spec §16): S18 decree DOF 01-05-2026. First-tier weekly hours by year (Transitorio Cuarto);
    # the multipliers read "cien por ciento mas" / "doscientos por ciento mas" as x2 / x3 (TL-WW-2).
    ScalarRow("mx_overtime_double_weekly_max_hours", None, None, "9", None, date(2026, 1, 1), date(2027, 12, 31),
              _S18, "Transitorio Cuarto: 2026 and 2027 - 9 overtime hours (Art. 66 limit)"),
    ScalarRow("mx_overtime_double_weekly_max_hours", None, None, "10", None, date(2028, 1, 1), date(2028, 12, 31),
              _S18, "Transitorio Cuarto: 2028 - 10 overtime hours"),
    ScalarRow("mx_overtime_double_weekly_max_hours", None, None, "11", None, date(2029, 1, 1), date(2029, 12, 31),
              _S18, "Transitorio Cuarto: 2029 - 11 overtime hours"),
    ScalarRow("mx_overtime_double_weekly_max_hours", None, None, "12", None, date(2030, 1, 1), None,
              _S18, "Transitorio Cuarto: 2030 - 12 overtime hours; Art. 66 as reformed: 'doce horas en una semana'"),
    ScalarRow("mx_overtime_double_multiplier", None, None, "2", None, None, None, _S18,
              "Art. 66 as reformed: overtime paid 'un cien por ciento mas de lo fijado para las horas ordinarias' "
              "(read as x2 the ordinary hourly pay, TL-WW-2)"),
    ScalarRow("mx_overtime_triple_multiplier", None, None, "3", None, None, None, _S18,
              "Art. 68 para 2 as reformed: overtime above the Art. 66 limit (max 4 h/week) paid 'un doscientos "
              "por ciento mas' (read as x3, TL-WW-2)"),
)

# ISR — Art. 96 retention tariffs (S2: Anexo 8 RMF 2026, section B "Tarifas aplicables a retenciones",
# I–V, each "correspondiente a 2026"). Transcribed 2026-10-26 [PENDING G1]; controls in
# docs/mexico/MEXICO_PHASE_1_TRANSCRIPTION_LOG.md (blind second transcription, machine extraction,
# arithmetic tests).
_S2 = 'S2/S2_SAT_Anexo8_RMF2026.pdf'
_ISR_FROM, _ISR_TO = date(2026, 1, 1), date(2026, 12, 31)
MX_ISR_TARIFFS: tuple = (
    # B.I — DAILY
    IsrBracket('DAILY', '0.01', '27.78', '0.00', '1.92', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.I, PDF p. 4'),
    IsrBracket('DAILY', '27.79', '235.81', '0.53', '6.40', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.I, PDF p. 4'),
    IsrBracket('DAILY', '235.82', '414.41', '13.85', '10.88', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.I, PDF p. 4'),
    IsrBracket('DAILY', '414.42', '481.73', '33.28', '16.00', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.I, PDF p. 4'),
    IsrBracket('DAILY', '481.74', '576.76', '44.05', '17.92', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.I, PDF p. 4'),
    IsrBracket('DAILY', '576.77', '1163.25', '61.08', '21.36', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.I, PDF p. 4'),
    IsrBracket('DAILY', '1163.26', '1833.44', '186.35', '23.52', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.I, PDF p. 4'),
    IsrBracket('DAILY', '1833.45', '3500.35', '343.98', '30.00', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.I, PDF p. 4'),
    IsrBracket('DAILY', '3500.36', '4667.13', '844.05', '32.00', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.I, PDF p. 4'),
    IsrBracket('DAILY', '4667.14', '14001.38', '1217.42', '34.00', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.I, PDF p. 4'),
    IsrBracket('DAILY', '14001.39', None, '4391.07', '35.00', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.I, PDF p. 4'),
    # B.II — WEEKLY_7
    IsrBracket('WEEKLY_7', '0.01', '194.46', '0.00', '1.92', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.II, PDF p. 4-5'),
    IsrBracket('WEEKLY_7', '194.47', '1650.67', '3.71', '6.40', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.II, PDF p. 4-5'),
    IsrBracket('WEEKLY_7', '1650.68', '2900.87', '96.95', '10.88', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.II, PDF p. 4-5'),
    IsrBracket('WEEKLY_7', '2900.88', '3372.11', '232.96', '16.00', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.II, PDF p. 4-5'),
    IsrBracket('WEEKLY_7', '3372.12', '4037.32', '308.35', '17.92', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.II, PDF p. 4-5'),
    IsrBracket('WEEKLY_7', '4037.33', '8142.75', '427.56', '21.36', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.II, PDF p. 4-5'),
    IsrBracket('WEEKLY_7', '8142.76', '12834.08', '1304.45', '23.52', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.II, PDF p. 4-5'),
    IsrBracket('WEEKLY_7', '12834.09', '24502.45', '2407.86', '30.00', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.II, PDF p. 4-5'),
    IsrBracket('WEEKLY_7', '24502.46', '32669.91', '5908.35', '32.00', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.II, PDF p. 4-5'),
    IsrBracket('WEEKLY_7', '32669.92', '98009.66', '8521.94', '34.00', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.II, PDF p. 4-5'),
    IsrBracket('WEEKLY_7', '98009.67', None, '30737.49', '35.00', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.II, PDF p. 4-5'),
    # B.III — DECENAL_10
    IsrBracket('DECENAL_10', '0.01', '277.80', '0.00', '1.92', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.III, PDF p. 5'),
    IsrBracket('DECENAL_10', '277.81', '2358.10', '5.30', '6.40', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.III, PDF p. 5'),
    IsrBracket('DECENAL_10', '2358.11', '4144.10', '138.50', '10.88', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.III, PDF p. 5'),
    IsrBracket('DECENAL_10', '4144.11', '4817.30', '332.80', '16.00', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.III, PDF p. 5'),
    IsrBracket('DECENAL_10', '4817.31', '5767.60', '440.50', '17.92', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.III, PDF p. 5'),
    IsrBracket('DECENAL_10', '5767.61', '11632.50', '610.80', '21.36', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.III, PDF p. 5'),
    IsrBracket('DECENAL_10', '11632.51', '18334.40', '1863.50', '23.52', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.III, PDF p. 5'),
    IsrBracket('DECENAL_10', '18334.41', '35003.50', '3439.80', '30.00', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.III, PDF p. 5'),
    IsrBracket('DECENAL_10', '35003.51', '46671.30', '8440.50', '32.00', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.III, PDF p. 5'),
    IsrBracket('DECENAL_10', '46671.31', '140013.80', '12174.20', '34.00', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.III, PDF p. 5'),
    IsrBracket('DECENAL_10', '140013.81', None, '43910.70', '35.00', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.III, PDF p. 5'),
    # B.IV — QUINCENAL_15
    IsrBracket('QUINCENAL_15', '0.01', '416.70', '0.00', '1.92', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.IV, PDF p. 5-6'),
    IsrBracket('QUINCENAL_15', '416.71', '3537.15', '7.95', '6.40', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.IV, PDF p. 5-6'),
    IsrBracket('QUINCENAL_15', '3537.16', '6216.15', '207.75', '10.88', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.IV, PDF p. 5-6'),
    IsrBracket('QUINCENAL_15', '6216.16', '7225.95', '499.20', '16.00', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.IV, PDF p. 5-6'),
    IsrBracket('QUINCENAL_15', '7225.96', '8651.40', '660.75', '17.92', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.IV, PDF p. 5-6'),
    IsrBracket('QUINCENAL_15', '8651.41', '17448.75', '916.20', '21.36', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.IV, PDF p. 5-6'),
    IsrBracket('QUINCENAL_15', '17448.76', '27501.60', '2795.25', '23.52', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.IV, PDF p. 5-6'),
    IsrBracket('QUINCENAL_15', '27501.61', '52505.25', '5159.70', '30.00', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.IV, PDF p. 5-6'),
    IsrBracket('QUINCENAL_15', '52505.26', '70006.95', '12660.75', '32.00', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.IV, PDF p. 5-6'),
    IsrBracket('QUINCENAL_15', '70006.96', '210020.70', '18261.30', '34.00', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.IV, PDF p. 5-6'),
    IsrBracket('QUINCENAL_15', '210020.71', None, '65866.05', '35.00', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.IV, PDF p. 5-6'),
    # B.V — MONTHLY
    IsrBracket('MONTHLY', '0.01', '844.59', '0.00', '1.92', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.V, PDF p. 6'),
    IsrBracket('MONTHLY', '844.60', '7168.51', '16.22', '6.40', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.V, PDF p. 6'),
    IsrBracket('MONTHLY', '7168.52', '12598.02', '420.95', '10.88', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.V, PDF p. 6'),
    IsrBracket('MONTHLY', '12598.03', '14644.64', '1011.68', '16.00', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.V, PDF p. 6'),
    IsrBracket('MONTHLY', '14644.65', '17533.64', '1339.14', '17.92', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.V, PDF p. 6'),
    IsrBracket('MONTHLY', '17533.65', '35362.83', '1856.84', '21.36', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.V, PDF p. 6'),
    IsrBracket('MONTHLY', '35362.84', '55736.68', '5665.16', '23.52', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.V, PDF p. 6'),
    IsrBracket('MONTHLY', '55736.69', '106410.50', '10457.09', '30.00', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.V, PDF p. 6'),
    IsrBracket('MONTHLY', '106410.51', '141880.66', '25659.23', '32.00', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.V, PDF p. 6'),
    IsrBracket('MONTHLY', '141880.67', '425641.99', '37009.69', '34.00', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.V, PDF p. 6'),
    IsrBracket('MONTHLY', '425642.00', None, '133488.54', '35.00', _ISR_FROM, _ISR_TO, _S2, 'Anexo 8 RMF 2026 (DOF 28-12-2025), B.V, PDF p. 6'),
)
# LISR Art. 97 / 152 ANNUAL tariff (W1-4, 2026-10-26) [PENDING G1]: S2 Anexo 8 section C "Tarifa para el cálculo
# del impuesto correspondiente a los ejercicios 2025 y 2026", II (2026), PDF pp. 18-19. Module-direct: read only
# by the annual-adjustment rule (mexico_rules), never seeded into a period pack. Log TL-ANN-1.
MX_ISR_ANNUAL_TARIFFS: dict = {   # fiscal year -> tuple[IsrBracket] (period "ANNUAL")
    2026: (
        IsrBracket('ANNUAL', '0.01', '10135.11', '0', '1.92', date(2026, 1, 1), date(2026, 12, 31), _S2,
                   'Anexo 8 RMF 2026 (DOF 28-12-2025), C.II, PDF p. 18'),
        IsrBracket('ANNUAL', '10135.12', '86022.11', '194.59', '6.40', date(2026, 1, 1), date(2026, 12, 31), _S2,
                   'Anexo 8 RMF 2026 (DOF 28-12-2025), C.II, PDF p. 18'),
        IsrBracket('ANNUAL', '86022.12', '151176.19', '5051.37', '10.88', date(2026, 1, 1), date(2026, 12, 31), _S2,
                   'Anexo 8 RMF 2026 (DOF 28-12-2025), C.II, PDF p. 18'),
        IsrBracket('ANNUAL', '151176.20', '175735.66', '12140.13', '16.00', date(2026, 1, 1), date(2026, 12, 31), _S2,
                   'Anexo 8 RMF 2026 (DOF 28-12-2025), C.II, PDF p. 18'),
        IsrBracket('ANNUAL', '175735.67', '210403.69', '16069.64', '17.92', date(2026, 1, 1), date(2026, 12, 31), _S2,
                   'Anexo 8 RMF 2026 (DOF 28-12-2025), C.II, PDF p. 18'),
        IsrBracket('ANNUAL', '210403.70', '424353.97', '22282.14', '21.36', date(2026, 1, 1), date(2026, 12, 31), _S2,
                   'Anexo 8 RMF 2026 (DOF 28-12-2025), C.II, PDF p. 18'),
        IsrBracket('ANNUAL', '424353.98', '668840.14', '67981.92', '23.52', date(2026, 1, 1), date(2026, 12, 31), _S2,
                   'Anexo 8 RMF 2026 (DOF 28-12-2025), C.II, PDF p. 18'),
        IsrBracket('ANNUAL', '668840.15', '1276925.98', '125485.07', '30.00', date(2026, 1, 1), date(2026, 12, 31), _S2,
                   'Anexo 8 RMF 2026 (DOF 28-12-2025), C.II, PDF p. 19'),
        IsrBracket('ANNUAL', '1276925.99', '1702567.97', '307910.81', '32.00', date(2026, 1, 1), date(2026, 12, 31), _S2,
                   'Anexo 8 RMF 2026 (DOF 28-12-2025), C.II, PDF p. 19'),
        IsrBracket('ANNUAL', '1702567.98', '5107703.92', '444116.23', '34.00', date(2026, 1, 1), date(2026, 12, 31), _S2,
                   'Anexo 8 RMF 2026 (DOF 28-12-2025), C.II, PDF p. 19'),
        IsrBracket('ANNUAL', '5107703.93', None, '1601862.46', '35.00', date(2026, 1, 1), date(2026, 12, 31), _S2,
                   'Anexo 8 RMF 2026 (DOF 28-12-2025), C.II, PDF p. 19'),
    ),
}


MX_MIN_WAGES: tuple = (
    # S9: DOF 09-12-2025 CONASAMI resolution, in force from 1 Jan 2026 [PENDING G1]
    MinWageRow("GENERAL", "ZONE", "Zona del Salario Minimo General", "315.04", None, date(2026, 1, 1), None, _S9,
               "Resolutivo TERCERO: ZSMG 315.04 pesos por jornada diaria, from 1 Jan 2026"),
    MinWageRow("ZLFN", "ZONE", "Zona Libre de la Frontera Norte", "440.87", None, date(2026, 1, 1), None, _S9,
               "Resolutivo TERCERO: ZLFN 440.87 pesos por jornada diaria, from 1 Jan 2026"),
    # Resolutivo OCTAVO: professional minimums, one row per zone (codes PROF_nn = the table's No.)
    MinWageRow('PROF_01', "PROFESSION", 'Albañilería, oficial de', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 1, ZLFN"),
    MinWageRow('PROF_01', "PROFESSION", 'Albañilería, oficial de', '363.44', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 1, GENERAL"),
    MinWageRow('PROF_02', "PROFESSION", 'Boticas, farmacias y droguería, dependiente(a) de mostrador en', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 2, ZLFN"),
    MinWageRow('PROF_02', "PROFESSION", 'Boticas, farmacias y droguería, dependiente(a) de mostrador en', '321.26', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 2, GENERAL"),
    MinWageRow('PROF_03', "PROFESSION", 'Buldozer y/o traxcavo, operador(a) de', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 3, ZLFN"),
    MinWageRow('PROF_03', "PROFESSION", 'Buldozer y/o traxcavo, operador(a) de', '380.74', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 3, GENERAL"),
    MinWageRow('PROF_04', "PROFESSION", 'Cajero(a) de máquina registradora', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 4, ZLFN"),
    MinWageRow('PROF_04', "PROFESSION", 'Cajero(a) de máquina registradora', '326.84', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 4, GENERAL"),
    MinWageRow('PROF_05', "PROFESSION", 'Cantinero(a) preparador de bebidas', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 5, ZLFN"),
    MinWageRow('PROF_05', "PROFESSION", 'Cantinero(a) preparador de bebidas', '333.52', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 5, GENERAL"),
    MinWageRow('PROF_06', "PROFESSION", 'Carpintero(a) de obra negra', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 6, ZLFN"),
    MinWageRow('PROF_06', "PROFESSION", 'Carpintero(a) de obra negra', '363.44', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 6, GENERAL"),
    MinWageRow('PROF_07', "PROFESSION", 'Carpintero(a) en la fabricación y reparación de muebles, oficial', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 7, ZLFN"),
    MinWageRow('PROF_07', "PROFESSION", 'Carpintero(a) en la fabricación y reparación de muebles, oficial', '357.45', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 7, GENERAL"),
    MinWageRow('PROF_08', "PROFESSION", 'Cocinero(a), mayor(a) en restaurantes, fondas y demás establecimientos de preparación y venta de alimentos', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 8, ZLFN"),
    MinWageRow('PROF_08', "PROFESSION", 'Cocinero(a), mayor(a) en restaurantes, fondas y demás establecimientos de preparación y venta de alimentos', '368.05', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 8, GENERAL"),
    MinWageRow('PROF_09', "PROFESSION", 'Colchones, oficial en fabricación y reparación de', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 9, ZLFN"),
    MinWageRow('PROF_09', "PROFESSION", 'Colchones, oficial en fabricación y reparación de', '336.83', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 9, GENERAL"),
    MinWageRow('PROF_10', "PROFESSION", 'Colocador(a) de mosaicos y azulejos, oficial', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 10, ZLFN"),
    MinWageRow('PROF_10', "PROFESSION", 'Colocador(a) de mosaicos y azulejos, oficial', '356.19', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 10, GENERAL"),
    MinWageRow('PROF_11', "PROFESSION", 'Construcción de edificios y casas habitación, yesero(a) en', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 11, ZLFN"),
    MinWageRow('PROF_11', "PROFESSION", 'Construcción de edificios y casas habitación, yesero(a) en', '339.20', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 11, GENERAL"),
    MinWageRow('PROF_12', "PROFESSION", 'Cortador(a) en talleres y fábricas de manufactura de calzado, oficial', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 12, ZLFN"),
    MinWageRow('PROF_12', "PROFESSION", 'Cortador(a) en talleres y fábricas de manufactura de calzado, oficial', '330.31', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 12, GENERAL"),
    MinWageRow('PROF_13', "PROFESSION", 'Costurero(a) en confección de ropa en talleres o fábricas', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 13, ZLFN"),
    MinWageRow('PROF_13', "PROFESSION", 'Costurero(a) en confección de ropa en talleres o fábricas', '326.38', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 13, GENERAL"),
    MinWageRow('PROF_14', "PROFESSION", 'Costurero(a) en confección de ropa en trabajo a domicilio', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 14, ZLFN"),
    MinWageRow('PROF_14', "PROFESSION", 'Costurero(a) en confección de ropa en trabajo a domicilio', '334.94', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 14, GENERAL"),
    MinWageRow('PROF_15', "PROFESSION", 'Chofer acomodador(a) de automóviles en estacionamientos', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 15, ZLFN"),
    MinWageRow('PROF_15', "PROFESSION", 'Chofer acomodador(a) de automóviles en estacionamientos', '341.42', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 15, GENERAL"),
    MinWageRow('PROF_16', "PROFESSION", 'Chofer de camión de carga en general', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 16, ZLFN"),
    MinWageRow('PROF_16', "PROFESSION", 'Chofer de camión de carga en general', '370.90', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 16, GENERAL"),
    MinWageRow('PROF_17', "PROFESSION", 'Chofer de camioneta de carga en general', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 17, ZLFN"),
    MinWageRow('PROF_17', "PROFESSION", 'Chofer de camioneta de carga en general', '360.39', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 17, GENERAL"),
    MinWageRow('PROF_18', "PROFESSION", 'Chofer operador(a) de vehículos con grúa', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 18, ZLFN"),
    MinWageRow('PROF_18', "PROFESSION", 'Chofer operador(a) de vehículos con grúa', '346.67', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 18, GENERAL"),
    MinWageRow('PROF_19', "PROFESSION", 'Draga, operador(a) de', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 19, ZLFN"),
    MinWageRow('PROF_19', "PROFESSION", 'Draga, operador(a) de', '384.25', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 19, GENERAL"),
    MinWageRow('PROF_20', "PROFESSION", 'Ebanista en fabricación y reparación de muebles, oficial', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 20, ZLFN"),
    MinWageRow('PROF_20', "PROFESSION", 'Ebanista en fabricación y reparación de muebles, oficial', '362.61', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 20, GENERAL"),
    MinWageRow('PROF_21', "PROFESSION", 'Electricista instalador(a) y reparador(a) de instalaciones eléctricas, oficial', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 21, ZLFN"),
    MinWageRow('PROF_21', "PROFESSION", 'Electricista instalador(a) y reparador(a) de instalaciones eléctricas, oficial', '356.19', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 21, GENERAL"),
    MinWageRow('PROF_22', "PROFESSION", 'Electricista en la reparación de automóviles y camiones, oficial', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 22, ZLFN"),
    MinWageRow('PROF_22', "PROFESSION", 'Electricista en la reparación de automóviles y camiones, oficial', '359.63', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 22, GENERAL"),
    MinWageRow('PROF_23', "PROFESSION", 'Electricista reparador(a) de motores y/o generadores en talleres de servicio, oficial', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 23, ZLFN"),
    MinWageRow('PROF_23', "PROFESSION", 'Electricista reparador(a) de motores y/o generadores en talleres de servicio, oficial', '346.67', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 23, GENERAL"),
    MinWageRow('PROF_24', "PROFESSION", 'Empleado(a) de góndola, anaquel o sección en tienda de autoservicio', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 24, ZLFN"),
    MinWageRow('PROF_24', "PROFESSION", 'Empleado(a) de góndola, anaquel o sección en tienda de autoservicio', '320.32', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 24, GENERAL"),
    MinWageRow('PROF_25', "PROFESSION", 'Encargado(a) de bodega y/o almacén', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 25, ZLFN"),
    MinWageRow('PROF_25', "PROFESSION", 'Encargado(a) de bodega y/o almacén', '331.76', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 25, GENERAL"),
    MinWageRow('PROF_26', "PROFESSION", 'Ferreterías y tlapalerías, dependiente(a) en', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 26, ZLFN"),
    MinWageRow('PROF_26', "PROFESSION", 'Ferreterías y tlapalerías, dependiente(a) en', '338.38', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 26, GENERAL"),
    MinWageRow('PROF_27', "PROFESSION", 'Fogonero(a) de calderas de vapor', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 27, ZLFN"),
    MinWageRow('PROF_27', "PROFESSION", 'Fogonero(a) de calderas de vapor', '349.22', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 27, GENERAL"),
    MinWageRow('PROF_28', "PROFESSION", 'Gasolinero(a), oficial', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 28, ZLFN"),
    MinWageRow('PROF_28', "PROFESSION", 'Gasolinero(a), oficial', '326.38', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 28, GENERAL"),
    MinWageRow('PROF_29', "PROFESSION", 'Herrería, oficial de', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 29, ZLFN"),
    MinWageRow('PROF_29', "PROFESSION", 'Herrería, oficial de', '351.59', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 29, GENERAL"),
    MinWageRow('PROF_30', "PROFESSION", 'Hojalatero(a) en la reparación de automóviles y camiones, oficial', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 30, ZLFN"),
    MinWageRow('PROF_30', "PROFESSION", 'Hojalatero(a) en la reparación de automóviles y camiones, oficial', '357.45', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 30, GENERAL"),
    MinWageRow('PROF_31', "PROFESSION", 'Jornalero(a) agrícola y/o trabajador(a) del campo', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 31, ZLFN"),
    MinWageRow('PROF_31', "PROFESSION", 'Jornalero(a) agrícola y/o trabajador(a) del campo', '356.16', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 31, GENERAL"),
    MinWageRow('PROF_32', "PROFESSION", 'Lubricador(a) de automóviles, camiones y otros vehículos de motor', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 32, ZLFN"),
    MinWageRow('PROF_32', "PROFESSION", 'Lubricador(a) de automóviles, camiones y otros vehículos de motor', '328.83', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 32, GENERAL"),
    MinWageRow('PROF_33', "PROFESSION", 'Manejador(a) en granja avícola', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 33, ZLFN"),
    MinWageRow('PROF_33', "PROFESSION", 'Manejador(a) en granja avícola', '316.85', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 33, GENERAL"),
    MinWageRow('PROF_34', "PROFESSION", 'Maquinaria agrícola, operador(a) de', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 34, ZLFN"),
    MinWageRow('PROF_34', "PROFESSION", 'Maquinaria agrícola, operador(a) de', '365.24', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 34, GENERAL"),
    MinWageRow('PROF_35', "PROFESSION", 'Máquinas para madera en general, oficial operador(a) de', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 35, ZLFN"),
    MinWageRow('PROF_35', "PROFESSION", 'Máquinas para madera en general, oficial operador(a) de', '349.22', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 35, GENERAL"),
    MinWageRow('PROF_36', "PROFESSION", 'Mecánico(a) en reparación de automóviles y camiones, oficial', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 36, ZLFN"),
    MinWageRow('PROF_36', "PROFESSION", 'Mecánico(a) en reparación de automóviles y camiones, oficial', '375.35', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 36, GENERAL"),
    MinWageRow('PROF_37', "PROFESSION", 'Montador(a) en talleres y fábricas de calzado, oficial', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 37, ZLFN"),
    MinWageRow('PROF_37', "PROFESSION", 'Montador(a) en talleres y fábricas de calzado, oficial', '330.31', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 37, GENERAL"),
    MinWageRow('PROF_38', "PROFESSION", 'Peluquero(a) y cultor(a) de belleza', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 38, ZLFN"),
    MinWageRow('PROF_38', "PROFESSION", 'Peluquero(a) y cultor(a) de belleza', '341.42', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 38, GENERAL"),
    MinWageRow('PROF_39', "PROFESSION", 'Pintor(a) de automóviles y camiones, oficial', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 39, ZLFN"),
    MinWageRow('PROF_39', "PROFESSION", 'Pintor(a) de automóviles y camiones, oficial', '351.59', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 39, GENERAL"),
    MinWageRow('PROF_40', "PROFESSION", 'Pintor(a) de casas, edificios y construcciones en general, oficial', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 40, ZLFN"),
    MinWageRow('PROF_40', "PROFESSION", 'Pintor(a) de casas, edificios y construcciones en general, oficial', '349.22', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 40, GENERAL"),
    MinWageRow('PROF_41', "PROFESSION", 'Planchador(a) a máquina en tintorerías, lavandería y establecimientos similares', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 41, ZLFN"),
    MinWageRow('PROF_41', "PROFESSION", 'Planchador(a) a máquina en tintorerías, lavandería y establecimientos similares', '326.84', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 41, GENERAL"),
    MinWageRow('PROF_42', "PROFESSION", 'Plomero(a) en instalaciones sanitarias, oficial', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 42, ZLFN"),
    MinWageRow('PROF_42', "PROFESSION", 'Plomero(a) en instalaciones sanitarias, oficial', '349.84', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 42, GENERAL"),
    MinWageRow('PROF_43', "PROFESSION", 'Radiotécnico(a) reparador(a) de aparatos eléctricos y electrónicos, oficial', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 43, ZLFN"),
    MinWageRow('PROF_43', "PROFESSION", 'Radiotécnico(a) reparador(a) de aparatos eléctricos y electrónicos, oficial', '362.61', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 43, GENERAL"),
    MinWageRow('PROF_44', "PROFESSION", 'Recamarero(a) en hoteles, moteles y otros establecimientos de hospedaje', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 44, ZLFN"),
    MinWageRow('PROF_44', "PROFESSION", 'Recamarero(a) en hoteles, moteles y otros establecimientos de hospedaje', '320.32', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 44, GENERAL"),
    MinWageRow('PROF_45', "PROFESSION", 'Refaccionaria de automóviles y camiones, dependiente(a) de mostrador en', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 45, ZLFN"),
    MinWageRow('PROF_45', "PROFESSION", 'Refaccionaria de automóviles y camiones, dependiente(a) de mostrador en', '331.76', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 45, GENERAL"),
    MinWageRow('PROF_46', "PROFESSION", 'Reparador(a) de aparatos eléctricos para el hogar, oficial', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 46, ZLFN"),
    MinWageRow('PROF_46', "PROFESSION", 'Reparador(a) de aparatos eléctricos para el hogar, oficial', '345.36', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 46, GENERAL"),
    MinWageRow('PROF_47', "PROFESSION", 'Reportero(a) en prensa diaria impresa', '705.46', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 47, ZLFN"),
    MinWageRow('PROF_47', "PROFESSION", 'Reportero(a) en prensa diaria impresa', '705.46', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 47, GENERAL"),
    MinWageRow('PROF_48', "PROFESSION", 'Reportero(a) gráfico(a) en prensa diaria impresa', '705.46', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 48, ZLFN"),
    MinWageRow('PROF_48', "PROFESSION", 'Reportero(a) gráfico(a) en prensa diaria impresa', '705.46', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 48, GENERAL"),
    MinWageRow('PROF_49', "PROFESSION", 'Repostero(a) o pastelero(a)', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 49, ZLFN"),
    MinWageRow('PROF_49', "PROFESSION", 'Repostero(a) o pastelero(a)', '363.44', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 49, GENERAL"),
    MinWageRow('PROF_50', "PROFESSION", 'Sastrería en trabajo a domicilio, oficial de', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 50, ZLFN"),
    MinWageRow('PROF_50', "PROFESSION", 'Sastrería en trabajo a domicilio, oficial de', '365.24', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 50, GENERAL"),
    MinWageRow('PROF_51', "PROFESSION", 'Secretario(a) auxiliar', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 51, ZLFN"),
    MinWageRow('PROF_51', "PROFESSION", 'Secretario(a) auxiliar', '374.60', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 51, GENERAL"),
    MinWageRow('PROF_52', "PROFESSION", 'Soldador(a) con soplete o con arco eléctrico', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 52, ZLFN"),
    MinWageRow('PROF_52', "PROFESSION", 'Soldador(a) con soplete o con arco eléctrico', '359.63', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 52, GENERAL"),
    MinWageRow('PROF_53', "PROFESSION", 'Tablajero(a) y/o carnicero(a) en mostrador', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 53, ZLFN"),
    MinWageRow('PROF_53', "PROFESSION", 'Tablajero(a) y/o carnicero(a) en mostrador', '341.42', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 53, GENERAL"),
    MinWageRow('PROF_54', "PROFESSION", 'Tapicero(a) de vestiduras de automóviles, oficial', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 54, ZLFN"),
    MinWageRow('PROF_54', "PROFESSION", 'Tapicero(a) de vestiduras de automóviles, oficial', '346.67', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 54, GENERAL"),
    MinWageRow('PROF_55', "PROFESSION", 'Tapicero(a) en reparación de muebles, oficial', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 55, ZLFN"),
    MinWageRow('PROF_55', "PROFESSION", 'Tapicero(a) en reparación de muebles, oficial', '346.67', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 55, GENERAL"),
    MinWageRow('PROF_56', "PROFESSION", 'Trabajador(a) del hogar', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 56, ZLFN"),
    MinWageRow('PROF_56', "PROFESSION", 'Trabajador(a) del hogar', '342.47', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 56, GENERAL"),
    MinWageRow('PROF_57', "PROFESSION", 'Trabajador(a) social, técnico(a) en', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 57, ZLFN"),
    MinWageRow('PROF_57', "PROFESSION", 'Trabajador(a) social, técnico(a) en', '405.82', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 57, GENERAL"),
    MinWageRow('PROF_58', "PROFESSION", 'Vaquero(a) ordeñador a máquina', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 58, ZLFN"),
    MinWageRow('PROF_58', "PROFESSION", 'Vaquero(a) ordeñador a máquina', '320.32', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 58, GENERAL"),
    MinWageRow('PROF_59', "PROFESSION", 'Velador(a)', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 59, ZLFN"),
    MinWageRow('PROF_59', "PROFESSION", 'Velador(a)', '326.38', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 59, GENERAL"),
    MinWageRow('PROF_60', "PROFESSION", 'Vendedor(a) de piso de aparatos de uso doméstico', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 60, ZLFN"),
    MinWageRow('PROF_60', "PROFESSION", 'Vendedor(a) de piso de aparatos de uso doméstico', '334.94', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 60, GENERAL"),
    MinWageRow('PROF_61', "PROFESSION", 'Zapatero(a) en talleres de reparación de calzado, oficial', '440.87', 'ZLFN', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 61, ZLFN"),
    MinWageRow('PROF_61', "PROFESSION", 'Zapatero(a) en talleres de reparación de calzado, oficial', '330.31', 'GENERAL', date(2026, 1, 1), None, _S9, "Resolutivo OCTAVO, No. 61, GENERAL"),
)
MX_ZLFN_MUNICIPALITIES: tuple = (
    # S9 Resolutivo PRIMERO: the municipalities that form the ZLFN [PENDING G1]
    ZlfnMunicipality('BCN', 'Ensenada', _S9, "Resolutivo PRIMERO (Baja California)"),
    ZlfnMunicipality('BCN', 'Playas de Rosarito', _S9, "Resolutivo PRIMERO (Baja California)"),
    ZlfnMunicipality('BCN', 'Mexicali', _S9, "Resolutivo PRIMERO (Baja California)"),
    ZlfnMunicipality('BCN', 'Tecate', _S9, "Resolutivo PRIMERO (Baja California)"),
    ZlfnMunicipality('BCN', 'Tijuana', _S9, "Resolutivo PRIMERO (Baja California)"),
    ZlfnMunicipality('BCN', 'San Quintín', _S9, "Resolutivo PRIMERO (Baja California)"),
    ZlfnMunicipality('BCN', 'San Felipe', _S9, "Resolutivo PRIMERO (Baja California)"),
    ZlfnMunicipality('SON', 'San Luis Río Colorado', _S9, "Resolutivo PRIMERO (Sonora)"),
    ZlfnMunicipality('SON', 'Puerto Peñasco', _S9, "Resolutivo PRIMERO (Sonora)"),
    ZlfnMunicipality('SON', 'General Plutarco Elías Calles', _S9, "Resolutivo PRIMERO (Sonora)"),
    ZlfnMunicipality('SON', 'Caborca', _S9, "Resolutivo PRIMERO (Sonora)"),
    ZlfnMunicipality('SON', 'Altar', _S9, "Resolutivo PRIMERO (Sonora)"),
    ZlfnMunicipality('SON', 'Sáric', _S9, "Resolutivo PRIMERO (Sonora)"),
    ZlfnMunicipality('SON', 'Nogales', _S9, "Resolutivo PRIMERO (Sonora)"),
    ZlfnMunicipality('SON', 'Santa Cruz', _S9, "Resolutivo PRIMERO (Sonora)"),
    ZlfnMunicipality('SON', 'Cananea', _S9, "Resolutivo PRIMERO (Sonora)"),
    ZlfnMunicipality('SON', 'Naco', _S9, "Resolutivo PRIMERO (Sonora)"),
    ZlfnMunicipality('SON', 'Agua Prieta', _S9, "Resolutivo PRIMERO (Sonora)"),
    ZlfnMunicipality('CHH', 'Janos', _S9, "Resolutivo PRIMERO (Chihuahua)"),
    ZlfnMunicipality('CHH', 'Ascensión', _S9, "Resolutivo PRIMERO (Chihuahua)"),
    ZlfnMunicipality('CHH', 'Juárez', _S9, "Resolutivo PRIMERO (Chihuahua)"),
    ZlfnMunicipality('CHH', 'Práxedis G. Guerrero', _S9, "Resolutivo PRIMERO (Chihuahua)"),
    ZlfnMunicipality('CHH', 'Guadalupe', _S9, "Resolutivo PRIMERO (Chihuahua)"),
    ZlfnMunicipality('CHH', 'Coyame del Sotol', _S9, "Resolutivo PRIMERO (Chihuahua)"),
    ZlfnMunicipality('CHH', 'Ojinaga', _S9, "Resolutivo PRIMERO (Chihuahua)"),
    ZlfnMunicipality('CHH', 'Manuel Benavides', _S9, "Resolutivo PRIMERO (Chihuahua)"),
    ZlfnMunicipality('COA', 'Ocampo', _S9, "Resolutivo PRIMERO (Coahuila de Zaragoza)"),
    ZlfnMunicipality('COA', 'Acuña', _S9, "Resolutivo PRIMERO (Coahuila de Zaragoza)"),
    ZlfnMunicipality('COA', 'Zaragoza', _S9, "Resolutivo PRIMERO (Coahuila de Zaragoza)"),
    ZlfnMunicipality('COA', 'Jiménez', _S9, "Resolutivo PRIMERO (Coahuila de Zaragoza)"),
    ZlfnMunicipality('COA', 'Piedras Negras', _S9, "Resolutivo PRIMERO (Coahuila de Zaragoza)"),
    ZlfnMunicipality('COA', 'Nava', _S9, "Resolutivo PRIMERO (Coahuila de Zaragoza)"),
    ZlfnMunicipality('COA', 'Guerrero', _S9, "Resolutivo PRIMERO (Coahuila de Zaragoza)"),
    ZlfnMunicipality('COA', 'Hidalgo', _S9, "Resolutivo PRIMERO (Coahuila de Zaragoza)"),
    ZlfnMunicipality('NLE', 'Anáhuac', _S9, "Resolutivo PRIMERO (Nuevo León)"),
    ZlfnMunicipality('TAM', 'Nuevo Laredo', _S9, "Resolutivo PRIMERO (Tamaulipas)"),
    ZlfnMunicipality('TAM', 'Guerrero', _S9, "Resolutivo PRIMERO (Tamaulipas)"),
    ZlfnMunicipality('TAM', 'Mier', _S9, "Resolutivo PRIMERO (Tamaulipas)"),
    ZlfnMunicipality('TAM', 'Miguel Alemán', _S9, "Resolutivo PRIMERO (Tamaulipas)"),
    ZlfnMunicipality('TAM', 'Camargo', _S9, "Resolutivo PRIMERO (Tamaulipas)"),
    ZlfnMunicipality('TAM', 'Gustavo Díaz Ordaz', _S9, "Resolutivo PRIMERO (Tamaulipas)"),
    ZlfnMunicipality('TAM', 'Reynosa', _S9, "Resolutivo PRIMERO (Tamaulipas)"),
    ZlfnMunicipality('TAM', 'Río Bravo', _S9, "Resolutivo PRIMERO (Tamaulipas)"),
    ZlfnMunicipality('TAM', 'Valle Hermoso', _S9, "Resolutivo PRIMERO (Tamaulipas)"),
    ZlfnMunicipality('TAM', 'Matamoros', _S9, "Resolutivo PRIMERO (Tamaulipas)"),
)
MX_CEAV_SCHEDULE: tuple = (          # 2023-2030; only MX_CEAV_SEEDED_YEAR is seeded
    # S11: DOF 16-12-2020 decree, Transitorio Segundo table — a scanned IMAGE (PDF p. 7, DOF p. 32), no
    # text layer: read by eye; the 2030 column equals the S10 Art. 168 II a) text table (TL-CEAV-1) [PENDING G1]
    CeavBand(2023, '1.0', 'SM', '1.0', 'SM', '3.150', date(2023, 1, 1), date(2023, 12, 31), _S11, "Transitorio Segundo table, 2023 column (PDF p. 7, image)"),
    CeavBand(2023, '1.01', 'SM', '1.50', 'UMA', '3.281', date(2023, 1, 1), date(2023, 12, 31), _S11, "Transitorio Segundo table, 2023 column (PDF p. 7, image)"),
    CeavBand(2023, '1.51', 'UMA', '2.00', 'UMA', '3.575', date(2023, 1, 1), date(2023, 12, 31), _S11, "Transitorio Segundo table, 2023 column (PDF p. 7, image)"),
    CeavBand(2023, '2.01', 'UMA', '2.50', 'UMA', '3.751', date(2023, 1, 1), date(2023, 12, 31), _S11, "Transitorio Segundo table, 2023 column (PDF p. 7, image)"),
    CeavBand(2023, '2.51', 'UMA', '3.00', 'UMA', '3.869', date(2023, 1, 1), date(2023, 12, 31), _S11, "Transitorio Segundo table, 2023 column (PDF p. 7, image)"),
    CeavBand(2023, '3.01', 'UMA', '3.50', 'UMA', '3.953', date(2023, 1, 1), date(2023, 12, 31), _S11, "Transitorio Segundo table, 2023 column (PDF p. 7, image)"),
    CeavBand(2023, '3.51', 'UMA', '4.00', 'UMA', '4.016', date(2023, 1, 1), date(2023, 12, 31), _S11, "Transitorio Segundo table, 2023 column (PDF p. 7, image)"),
    CeavBand(2023, '4.01', 'UMA', None, None, '4.241', date(2023, 1, 1), date(2023, 12, 31), _S11, "Transitorio Segundo table, 2023 column (PDF p. 7, image)"),
    CeavBand(2024, '1.0', 'SM', '1.0', 'SM', '3.150', date(2024, 1, 1), date(2024, 12, 31), _S11, "Transitorio Segundo table, 2024 column (PDF p. 7, image)"),
    CeavBand(2024, '1.01', 'SM', '1.50', 'UMA', '3.413', date(2024, 1, 1), date(2024, 12, 31), _S11, "Transitorio Segundo table, 2024 column (PDF p. 7, image)"),
    CeavBand(2024, '1.51', 'UMA', '2.00', 'UMA', '4.000', date(2024, 1, 1), date(2024, 12, 31), _S11, "Transitorio Segundo table, 2024 column (PDF p. 7, image)"),
    CeavBand(2024, '2.01', 'UMA', '2.50', 'UMA', '4.353', date(2024, 1, 1), date(2024, 12, 31), _S11, "Transitorio Segundo table, 2024 column (PDF p. 7, image)"),
    CeavBand(2024, '2.51', 'UMA', '3.00', 'UMA', '4.588', date(2024, 1, 1), date(2024, 12, 31), _S11, "Transitorio Segundo table, 2024 column (PDF p. 7, image)"),
    CeavBand(2024, '3.01', 'UMA', '3.50', 'UMA', '4.756', date(2024, 1, 1), date(2024, 12, 31), _S11, "Transitorio Segundo table, 2024 column (PDF p. 7, image)"),
    CeavBand(2024, '3.51', 'UMA', '4.00', 'UMA', '4.882', date(2024, 1, 1), date(2024, 12, 31), _S11, "Transitorio Segundo table, 2024 column (PDF p. 7, image)"),
    CeavBand(2024, '4.01', 'UMA', None, None, '5.331', date(2024, 1, 1), date(2024, 12, 31), _S11, "Transitorio Segundo table, 2024 column (PDF p. 7, image)"),
    CeavBand(2025, '1.0', 'SM', '1.0', 'SM', '3.150', date(2025, 1, 1), date(2025, 12, 31), _S11, "Transitorio Segundo table, 2025 column (PDF p. 7, image)"),
    CeavBand(2025, '1.01', 'SM', '1.50', 'UMA', '3.544', date(2025, 1, 1), date(2025, 12, 31), _S11, "Transitorio Segundo table, 2025 column (PDF p. 7, image)"),
    CeavBand(2025, '1.51', 'UMA', '2.00', 'UMA', '4.426', date(2025, 1, 1), date(2025, 12, 31), _S11, "Transitorio Segundo table, 2025 column (PDF p. 7, image)"),
    CeavBand(2025, '2.01', 'UMA', '2.50', 'UMA', '4.954', date(2025, 1, 1), date(2025, 12, 31), _S11, "Transitorio Segundo table, 2025 column (PDF p. 7, image)"),
    CeavBand(2025, '2.51', 'UMA', '3.00', 'UMA', '5.307', date(2025, 1, 1), date(2025, 12, 31), _S11, "Transitorio Segundo table, 2025 column (PDF p. 7, image)"),
    CeavBand(2025, '3.01', 'UMA', '3.50', 'UMA', '5.559', date(2025, 1, 1), date(2025, 12, 31), _S11, "Transitorio Segundo table, 2025 column (PDF p. 7, image)"),
    CeavBand(2025, '3.51', 'UMA', '4.00', 'UMA', '5.747', date(2025, 1, 1), date(2025, 12, 31), _S11, "Transitorio Segundo table, 2025 column (PDF p. 7, image)"),
    CeavBand(2025, '4.01', 'UMA', None, None, '6.422', date(2025, 1, 1), date(2025, 12, 31), _S11, "Transitorio Segundo table, 2025 column (PDF p. 7, image)"),
    CeavBand(2026, '1.0', 'SM', '1.0', 'SM', '3.150', date(2026, 1, 1), date(2026, 12, 31), _S11, "Transitorio Segundo table, 2026 column (PDF p. 7, image)"),
    CeavBand(2026, '1.01', 'SM', '1.50', 'UMA', '3.676', date(2026, 1, 1), date(2026, 12, 31), _S11, "Transitorio Segundo table, 2026 column (PDF p. 7, image)"),
    CeavBand(2026, '1.51', 'UMA', '2.00', 'UMA', '4.851', date(2026, 1, 1), date(2026, 12, 31), _S11, "Transitorio Segundo table, 2026 column (PDF p. 7, image)"),
    CeavBand(2026, '2.01', 'UMA', '2.50', 'UMA', '5.556', date(2026, 1, 1), date(2026, 12, 31), _S11, "Transitorio Segundo table, 2026 column (PDF p. 7, image)"),
    CeavBand(2026, '2.51', 'UMA', '3.00', 'UMA', '6.026', date(2026, 1, 1), date(2026, 12, 31), _S11, "Transitorio Segundo table, 2026 column (PDF p. 7, image)"),
    CeavBand(2026, '3.01', 'UMA', '3.50', 'UMA', '6.361', date(2026, 1, 1), date(2026, 12, 31), _S11, "Transitorio Segundo table, 2026 column (PDF p. 7, image)"),
    CeavBand(2026, '3.51', 'UMA', '4.00', 'UMA', '6.613', date(2026, 1, 1), date(2026, 12, 31), _S11, "Transitorio Segundo table, 2026 column (PDF p. 7, image)"),
    CeavBand(2026, '4.01', 'UMA', None, None, '7.513', date(2026, 1, 1), date(2026, 12, 31), _S11, "Transitorio Segundo table, 2026 column (PDF p. 7, image)"),
    CeavBand(2027, '1.0', 'SM', '1.0', 'SM', '3.150', date(2027, 1, 1), date(2027, 12, 31), _S11, "Transitorio Segundo table, 2027 column (PDF p. 7, image)"),
    CeavBand(2027, '1.01', 'SM', '1.50', 'UMA', '3.807', date(2027, 1, 1), date(2027, 12, 31), _S11, "Transitorio Segundo table, 2027 column (PDF p. 7, image)"),
    CeavBand(2027, '1.51', 'UMA', '2.00', 'UMA', '5.276', date(2027, 1, 1), date(2027, 12, 31), _S11, "Transitorio Segundo table, 2027 column (PDF p. 7, image)"),
    CeavBand(2027, '2.01', 'UMA', '2.50', 'UMA', '6.157', date(2027, 1, 1), date(2027, 12, 31), _S11, "Transitorio Segundo table, 2027 column (PDF p. 7, image)"),
    CeavBand(2027, '2.51', 'UMA', '3.00', 'UMA', '6.745', date(2027, 1, 1), date(2027, 12, 31), _S11, "Transitorio Segundo table, 2027 column (PDF p. 7, image)"),
    CeavBand(2027, '3.01', 'UMA', '3.50', 'UMA', '7.164', date(2027, 1, 1), date(2027, 12, 31), _S11, "Transitorio Segundo table, 2027 column (PDF p. 7, image)"),
    CeavBand(2027, '3.51', 'UMA', '4.00', 'UMA', '7.479', date(2027, 1, 1), date(2027, 12, 31), _S11, "Transitorio Segundo table, 2027 column (PDF p. 7, image)"),
    CeavBand(2027, '4.01', 'UMA', None, None, '8.603', date(2027, 1, 1), date(2027, 12, 31), _S11, "Transitorio Segundo table, 2027 column (PDF p. 7, image)"),
    CeavBand(2028, '1.0', 'SM', '1.0', 'SM', '3.150', date(2028, 1, 1), date(2028, 12, 31), _S11, "Transitorio Segundo table, 2028 column (PDF p. 7, image)"),
    CeavBand(2028, '1.01', 'SM', '1.50', 'UMA', '3.939', date(2028, 1, 1), date(2028, 12, 31), _S11, "Transitorio Segundo table, 2028 column (PDF p. 7, image)"),
    CeavBand(2028, '1.51', 'UMA', '2.00', 'UMA', '5.701', date(2028, 1, 1), date(2028, 12, 31), _S11, "Transitorio Segundo table, 2028 column (PDF p. 7, image)"),
    CeavBand(2028, '2.01', 'UMA', '2.50', 'UMA', '6.759', date(2028, 1, 1), date(2028, 12, 31), _S11, "Transitorio Segundo table, 2028 column (PDF p. 7, image)"),
    CeavBand(2028, '2.51', 'UMA', '3.00', 'UMA', '7.464', date(2028, 1, 1), date(2028, 12, 31), _S11, "Transitorio Segundo table, 2028 column (PDF p. 7, image)"),
    CeavBand(2028, '3.01', 'UMA', '3.50', 'UMA', '7.967', date(2028, 1, 1), date(2028, 12, 31), _S11, "Transitorio Segundo table, 2028 column (PDF p. 7, image)"),
    CeavBand(2028, '3.51', 'UMA', '4.00', 'UMA', '8.345', date(2028, 1, 1), date(2028, 12, 31), _S11, "Transitorio Segundo table, 2028 column (PDF p. 7, image)"),
    CeavBand(2028, '4.01', 'UMA', None, None, '9.694', date(2028, 1, 1), date(2028, 12, 31), _S11, "Transitorio Segundo table, 2028 column (PDF p. 7, image)"),
    CeavBand(2029, '1.0', 'SM', '1.0', 'SM', '3.150', date(2029, 1, 1), date(2029, 12, 31), _S11, "Transitorio Segundo table, 2029 column (PDF p. 7, image)"),
    CeavBand(2029, '1.01', 'SM', '1.50', 'UMA', '4.070', date(2029, 1, 1), date(2029, 12, 31), _S11, "Transitorio Segundo table, 2029 column (PDF p. 7, image)"),
    CeavBand(2029, '1.51', 'UMA', '2.00', 'UMA', '6.126', date(2029, 1, 1), date(2029, 12, 31), _S11, "Transitorio Segundo table, 2029 column (PDF p. 7, image)"),
    CeavBand(2029, '2.01', 'UMA', '2.50', 'UMA', '7.360', date(2029, 1, 1), date(2029, 12, 31), _S11, "Transitorio Segundo table, 2029 column (PDF p. 7, image)"),
    CeavBand(2029, '2.51', 'UMA', '3.00', 'UMA', '8.183', date(2029, 1, 1), date(2029, 12, 31), _S11, "Transitorio Segundo table, 2029 column (PDF p. 7, image)"),
    CeavBand(2029, '3.01', 'UMA', '3.50', 'UMA', '8.770', date(2029, 1, 1), date(2029, 12, 31), _S11, "Transitorio Segundo table, 2029 column (PDF p. 7, image)"),
    CeavBand(2029, '3.51', 'UMA', '4.00', 'UMA', '9.211', date(2029, 1, 1), date(2029, 12, 31), _S11, "Transitorio Segundo table, 2029 column (PDF p. 7, image)"),
    CeavBand(2029, '4.01', 'UMA', None, None, '10.784', date(2029, 1, 1), date(2029, 12, 31), _S11, "Transitorio Segundo table, 2029 column (PDF p. 7, image)"),
    CeavBand(2030, '1.0', 'SM', '1.0', 'SM', '3.150', date(2030, 1, 1), date(2030, 12, 31), _S11, "Transitorio Segundo table, 2030 column (PDF p. 7, image)"),
    CeavBand(2030, '1.01', 'SM', '1.50', 'UMA', '4.202', date(2030, 1, 1), date(2030, 12, 31), _S11, "Transitorio Segundo table, 2030 column (PDF p. 7, image)"),
    CeavBand(2030, '1.51', 'UMA', '2.00', 'UMA', '6.552', date(2030, 1, 1), date(2030, 12, 31), _S11, "Transitorio Segundo table, 2030 column (PDF p. 7, image)"),
    CeavBand(2030, '2.01', 'UMA', '2.50', 'UMA', '7.962', date(2030, 1, 1), date(2030, 12, 31), _S11, "Transitorio Segundo table, 2030 column (PDF p. 7, image)"),
    CeavBand(2030, '2.51', 'UMA', '3.00', 'UMA', '8.902', date(2030, 1, 1), date(2030, 12, 31), _S11, "Transitorio Segundo table, 2030 column (PDF p. 7, image)"),
    CeavBand(2030, '3.01', 'UMA', '3.50', 'UMA', '9.573', date(2030, 1, 1), date(2030, 12, 31), _S11, "Transitorio Segundo table, 2030 column (PDF p. 7, image)"),
    CeavBand(2030, '3.51', 'UMA', '4.00', 'UMA', '10.077', date(2030, 1, 1), date(2030, 12, 31), _S11, "Transitorio Segundo table, 2030 column (PDF p. 7, image)"),
    CeavBand(2030, '4.01', 'UMA', None, None, '11.875', date(2030, 1, 1), date(2030, 12, 31), _S11, "Transitorio Segundo table, 2030 column (PDF p. 7, image)"),
)
MX_WORKWEEK: tuple = (
    # S18: DOF 01-05-2026 decree, Transitorio Segundo (ordinary week, from 1 Jan of each year) and Cuarto
    # (overtime hours); Arts. 66 / 68 as reformed (premiums) [PENDING G1]
    WorkweekRow('48', (("overtime_weekly_hours", '9'), ("overtime_premium", "cien por ciento mas"), ("excess_weekly_hours_max", "4"), ("excess_premium", "doscientos por ciento mas")), date(2026, 1, 1), date(2026, 12, 31), _S18,
                "Transitorio Segundo: 2026 - 48 h; Transitorio Cuarto: 9 overtime h; Arts. 66, 68"),
    WorkweekRow('46', (("overtime_weekly_hours", '9'), ("overtime_premium", "cien por ciento mas"), ("excess_weekly_hours_max", "4"), ("excess_premium", "doscientos por ciento mas")), date(2027, 1, 1), date(2027, 12, 31), _S18,
                "Transitorio Segundo: 2027 - 46 h; Transitorio Cuarto: 9 overtime h; Arts. 66, 68"),
    WorkweekRow('44', (("overtime_weekly_hours", '10'), ("overtime_premium", "cien por ciento mas"), ("excess_weekly_hours_max", "4"), ("excess_premium", "doscientos por ciento mas")), date(2028, 1, 1), date(2028, 12, 31), _S18,
                "Transitorio Segundo: 2028 - 44 h; Transitorio Cuarto: 10 overtime h; Arts. 66, 68"),
    WorkweekRow('42', (("overtime_weekly_hours", '11'), ("overtime_premium", "cien por ciento mas"), ("excess_weekly_hours_max", "4"), ("excess_premium", "doscientos por ciento mas")), date(2029, 1, 1), date(2029, 12, 31), _S18,
                "Transitorio Segundo: 2029 - 42 h; Transitorio Cuarto: 11 overtime h; Arts. 66, 68"),
    WorkweekRow('40', (("overtime_weekly_hours", '12'), ("overtime_premium", "cien por ciento mas"), ("excess_weekly_hours_max", "4"), ("excess_premium", "doscientos por ciento mas")), date(2030, 1, 1), None, _S18,
                "Transitorio Segundo: 2030 - 40 h; Transitorio Cuarto: 12 overtime h; Arts. 66, 68"),
)
MX_VACATION_DAYS: tuple = (
    # S26 LFT Art. 76 (reformed DOF 27-12-2022), PDF p. 24: 12 working days after the first year, +2 per
    # subsequent year up to 20, then +2 per five years of service from the sixth year. DERIVED from that
    # wording (no table is printed), to year 50; a longer service finds no row and blocks (TL-VAC-1) [PENDING G1]
    VacationDaysRow(1, 1, "12", None, None, _S26, "Art. 76 (DERIVED: year 1)"),
    VacationDaysRow(2, 2, "14", None, None, _S26, "Art. 76 (DERIVED: year 2)"),
    VacationDaysRow(3, 3, "16", None, None, _S26, "Art. 76 (DERIVED: year 3)"),
    VacationDaysRow(4, 4, "18", None, None, _S26, "Art. 76 (DERIVED: year 4)"),
    VacationDaysRow(5, 5, "20", None, None, _S26, "Art. 76 (DERIVED: year 5)"),
    VacationDaysRow(6, 10, "22", None, None, _S26, "Art. 76 (DERIVED: years 6-10)"),
    VacationDaysRow(11, 15, "24", None, None, _S26, "Art. 76 (DERIVED: years 11-15)"),
    VacationDaysRow(16, 20, "26", None, None, _S26, "Art. 76 (DERIVED: years 16-20)"),
    VacationDaysRow(21, 25, "28", None, None, _S26, "Art. 76 (DERIVED: years 21-25)"),
    VacationDaysRow(26, 30, "30", None, None, _S26, "Art. 76 (DERIVED: years 26-30)"),
    VacationDaysRow(31, 35, "32", None, None, _S26, "Art. 76 (DERIVED: years 31-35)"),
    VacationDaysRow(36, 40, "34", None, None, _S26, "Art. 76 (DERIVED: years 36-40)"),
    VacationDaysRow(41, 45, "36", None, None, _S26, "Art. 76 (DERIVED: years 41-45)"),
    VacationDaysRow(46, 50, "38", None, None, _S26, "Art. 76 (DERIVED: years 46-50)"),
)
# State ISN — W1-2 (2026-10-26) [PENDING G1]: S22, the SAF consolidated "CODIGO FISCAL 2026" (VERIFIED by a
# logged direct download; latest reform Gaceta 19-12-2025, which does not touch Arts. 156-158). Log TL-ISN-1.
_S22 = "S22/S22_SAF_Codigo_Fiscal_CDMX_2026.pdf"
MX_ISN_CONTENT: dict = {   # state -> tuple[ScalarRow]
    "CDMX": (
        ScalarRow("mx_isn_rate_pct", None, "4", None, None, None, None, _S22,
                  "Art. 158: 'se determinara, aplicando la tasa del 4% sobre el monto total de las erogaciones "
                  "realizadas por concepto de remuneraciones al trabajo personal subordinado', PDF p. 91"),
    ),
}
assert set(MX_ISN_CONTENT) == set(MX_ISN_STATES_IN_SCOPE)

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


# W1-5 (2026-10-26) [PENDING G1]: monthly due dates on the 17th, each from its own saved text (log TL-CAL-1).
# INFONAVIT (W2-5): Ley INFONAVIT Art. 35 says monthly, but its 1997 Transitorio SEXTO keeps payments bimonthly
# until the ISSSTE law makes them monthly; the ISSSTE law (S36 Art. 21) still pays the housing fund "por bimestres
# vencidos", so the condition is not met: BIMONTHLY, the 17th of the month after each bimester (log TL-CAL-4).
# IMSS is NOT listed either: LSS Art. 39 makes quotas monthly (17th of the next month), but the 1997 LSS
# Transitorio VIGESIMO SEPTIMO keeps retiro / CEAV bimonthly "hasta en tanto no se homologuen los periodos de pago
# de las Leyes del ISSSTE e INFONAVIT" (S36 Art. 21: still bimonthly), and one IMSS liability carries every branch
# — one date would misstate it (gap register A18: split the RCV branches into their own liability).
# Only a rule whose source is VERIFIED is seeded as a live due date (seed_statutory_report_templates).
MX_FILING_CALENDAR: tuple = (
    FilingRule("MX_ISR_WITHHOLDING", "{year}-{month:02d}", "MONTHLY",
               "withholdings remitted by the 17th of the month after the withholding period", 17, None, None,
               "S35/S35_DIP_CFF.pdf",
               "Art. 6 I: 'en los casos de retencion o de recaudacion de contribuciones'; 'las enteraran a mas tardar "
               "el dia 17 del mes de calendario inmediato posterior al de terminacion del periodo de la retencion', "
               "PDF p. 4"),
    FilingRule("MX_INFONAVIT", "{year}-{month:02d}", "BIMONTHLY",
               "INFONAVIT contributions and credit discounts paid by the 17th of the month after each bimester", 17,
               None, None, "S27/S27_DIP_LIFNVT.pdf",
               "Art. 35: 'a mas tardar los dias diecisiete del mes inmediato siguiente', PDF p. 22; 1997 Transitorio "
               "SEXTO: 'continuara siendo de forma bimestral hasta que en la Ley del Instituto de Seguridad y "
               "Servicios Sociales de los Trabajadores del Estado se establezca que la periodicidad de pagos se "
               "realizara mensualmente', PDF p. 57 (the ISSSTE law, S36 Art. 21 p. 11, still pays by bimester: log TL-CAL-4)"),
    FilingRule("MX_ISN_RETURN", "{year}-{month:02d}", "MONTHLY",
               "CDMX payroll tax paid by return by the 17th of the following month", 17, None, "CDMX",
               "S22/S22_SAF_Codigo_Fiscal_CDMX_2026.pdf",
               "Art. 159: 'se pagara mediante declaracion, que presentaran a traves de los medios electronicos que "
               "establezca la Secretaria, a mas tardar el dia diecisiete del mes siguiente', PDF p. 91"),
)


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


# W1-5 [PENDING G1]: RACERF Art. 32 III (S29) — log TL-CAL-2.
MX_RISK_PREMIUM_PERIOD: Optional[RiskPremiumPeriodRule] = RiskPremiumPeriodRule(
    3, 1, "S29/S29_DIP_RACERF.pdf",
    "Art. 32 III: 'tendra vigencia desde el primero de marzo del ano siguiente a aquel en que concluyo el periodo "
    "computado y hasta el dia ultimo de febrero del ano subsecuente', PDF p. 12")


# Phase 8 (D3): the IMSS affiliation-movement deadline (MX-025: "ordinary
# movements are generally due within five business days") is transcribed from
# its saved source (S13, with S10) — never from the spec text. Business days
# exclude the official holidays of MX_OFFICIAL_HOLIDAYS, which must list the
# event's year (a year with no transcribed list = no due date). Both EMPTY
# until transcribed: every movement is then DUE_DATE_UNSOURCED, and the shared
# weekend-only business-day helper is never used instead.
class MovementDeadlineRule(NamedTuple):
    business_days: int                # counted from the day after the event date
    source: str
    source_ref: str
    needs_g1: bool = True


# W1-5 [PENDING G1]: LSS Art. 15 I (S10) — five business days, counted from the day after the event (RACERF
# Art. 57, S29, for bajas; LSS Art. 34 I for salary changes). Which days are NOT business days (LFT Art. 74 /
# 715 or CFF Art. 12) is DECISIONS_PENDING D-16, so MX_OFFICIAL_HOLIDAYS stays EMPTY and every movement is
# still DUE_DATE_UNSOURCED until it is decided — log TL-CAL-3.
MX_IMSS_MOVEMENT_DEADLINE: Optional[MovementDeadlineRule] = MovementDeadlineRule(
    5, "S10/S10_IMSS_LSS.pdf",
    "Art. 15 I: 'comunicar sus altas y bajas, las modificaciones de su salario y los demas datos, dentro de plazos "
    "no mayores de cinco dias habiles', PDF p. 6")
MX_OFFICIAL_HOLIDAYS: dict = {}       # year -> (tuple of dates, source, source_ref); EMPTY until transcribed

# Phase 8: which filing-calendar report type (payroll_statutory_filing_calendar,
# seeded only from verified MX_FILING_CALENDAR rules) dates each authority
# liability. Names match the Mexico report templates — structural, not law.
MX_LIABILITY_REPORT_TYPES = {"SAT_ISR": "MX_ISR_WITHHOLDING", "IMSS": "MX_IMSS", "INFONAVIT": "MX_INFONAVIT",
                             "ISN": "MX_ISN_RETURN"}

# Phase 8 B7 (as Phase 7 §4.2): when a channel may call an authority-status
# NOT_FOUND "definitive" — provider/portal-specific, NO default. EMPTY: never
# definitive, so every retry after UNKNOWN needs an operator's confirmation.
MX_AUTHORITY_RETRY_CONFIG: dict = {}  # channel -> {"min_wait_seconds": int, "min_not_found_checks": int}

# Phase 9b (D2 / D3): special payments. Each entry is a small RULE OBJECT
# written at transcription from the saved text — never anticipated here — and
# carrying its own `source` / `source_ref` (engine/jurisdictions/mexico/
# special_pay.py defines the interfaces). EMPTY: every special payment BLOCKS
# (MX_SPECIAL_PAY_RULE_MISSING / MX_AGUINALDO_RULE_MISSING /
# MX_ISN_SPECIAL_PAY_RULE_MISSING); none falls back to the ordinary tariff (MX-009).
MX_SPECIAL_PAY_RULES: dict = dict(_rules.SPECIAL_PAY_RULES)   # W1-3a; concept (AGUINALDO / VACATION_PREMIUM / VACATION_PAYOUT / PTU / SEPARATION_SENIORITY_PREMIUM / SEPARATION_PAYMENT / SEPARATION_INDEMNITY) -> SpecialPayRule (S24 / S25)
MX_AGUINALDO_RULE = _rules.AGUINALDO_RULE   # W1-3a (LFT Art. 87); AguinaldoRule — proportion for part of a year + payable-by date (S26 LFT Art. 87)
MX_SPECIAL_PAY_ISN_INCLUSION: dict = {   # (state, concept) -> (included: bool, source, source_ref) — state ISN content
    # W1-2 (2026-10-26) [PENDING G1]: S22 Arts. 156 (what counts as remuneration) and 157 (what is not taxed),
    # PDF pp. 89-91 (log TL-ISN-2). NOT listed, so they block (MX_ISN_SPECIAL_PAY_RULE_MISSING): VACATION_PAYOUT,
    # SEPARATION_PAYMENT and SEPARATION_INDEMNITY — neither article names them (DECISIONS_PENDING D-06, G4).
    ("CDMX", "AGUINALDO"): (True, "S22/S22_SAF_Codigo_Fiscal_CDMX_2026.pdf",
                            "Art. 156 V: 'Gratificaciones y aguinaldos', PDF p. 89"),
    ("CDMX", "VACATION_PREMIUM"): (True, "S22/S22_SAF_Codigo_Fiscal_CDMX_2026.pdf",
                                   "Art. 156 III: 'Premios, primas, bonos, estimulos e incentivos' (the vacation "
                                   "premium read as a 'prima', TL-ISN-2), PDF p. 89"),
    ("CDMX", "SEPARATION_SENIORITY_PREMIUM"): (True, "S22/S22_SAF_Codigo_Fiscal_CDMX_2026.pdf",
                                               "Art. 156 VII: 'Primas de antiguedad', PDF p. 89"),
    ("CDMX", "PTU"): (False, "S22/S22_SAF_Codigo_Fiscal_CDMX_2026.pdf",
                      "Art. 157 XIII: 'Las participaciones en las utilidades de la empresa' (not taxed), PDF p. 91"),
}

# Phase 9c (D5): termination. The reason CATALOG — code -> TerminationReason
# rule object (label, the separation components the reason triggers: indemnity,
# seniority premium, ... — LFT Arts. 47–53, 162, S26) — and the FINIQUITO rule
# (vacation days owed at termination, LFT Arts. 76–81, and the withholding of a
# finiquito paid on its own, LISR / RLISR — S24 / S25). Interfaces in
# engine/jurisdictions/mexico/termination.py. EMPTY: no termination can be
# recorded (MX_TERMINATION_RULE_MISSING) and no finiquito calculated
# (MX_FINIQUITO_RULE_MISSING); an operator never chooses a tax treatment (MX-057).
MX_TERMINATION_REASONS: dict = dict(_rules.TERMINATION_REASONS)   # W1-3b; reason code -> TerminationReason (S26)
MX_FINIQUITO_RULE = _rules.FINIQUITO_RULE   # W1-3b; FiniquitoRule (S26 + S24 / S25)

# Phase 9d (plan 9d D2-D8): PTU. The employer enters the distributable amount
# (never derived, MX-054); the RULE OBJECT decides the split, which days and
# salary count, eligibility, the caps, the rounding residue and the payment
# deadline (LFT Arts. 117-131 - S26; windows - S21). The operator-exclusion
# CATALOG lists the reasons an operator may assert, with evidence and a second
# approver. Interfaces in engine/jurisdictions/mexico/ptu.py. EMPTY: no PTU is
# allocated (MX_PTU_RULE_MISSING) and no operator exclusion is recorded
# (MX_PTU_EXCLUSION_RULE_MISSING).
MX_PTU_RULE = _rules.PTU_RULE         # W1-4; PtuRule (S26 / S21)
MX_PTU_EXCLUSION_REASONS: dict = dict(_rules.PTU_EXCLUSION_REASONS)   # W1-4; reason code -> PtuExclusionReason (label, source, source_ref) - S26

# Phase 9e (plan 9e D1-D10): the annual ISR adjustment (LISR Art. 97 / 152 -
# S24). The RULE OBJECT decides eligibility, the annual ISR and how a
# difference is applied in a later run; the CATALOG lists the exclusions an
# operator may assert (with evidence and a second approver). Interfaces in
# engine/jurisdictions/mexico/annual_adjustment.py. EMPTY: nothing is computed
# (MX_ANNUAL_ADJUSTMENT_RULE_MISSING) and no operator exclusion is recorded
# (MX_ANNUAL_ADJUSTMENT_EXCLUSION_RULE_MISSING).
MX_ANNUAL_ADJUSTMENT_RULE = _rules.ANNUAL_ADJUSTMENT_RULE   # W1-4; AnnualAdjustmentRule (S24)
MX_ANNUAL_ADJUSTMENT_EXCLUSION_REASONS: dict = dict(_rules.ANNUAL_ADJUSTMENT_EXCLUSION_REASONS)   # W1-4; reason code -> exclusion reason (label, source, source_ref)

# W3-3: contribution days per branch with absences / incapacity (LSS Art. 31; Ley INFONAVIT Art. 29).
# None = absence or incapacity days BLOCK (MX_ABSENCE_RULES_MISSING). Interface: check(absence, incapacity,
# segment_count); branch_days(branch, days, absence, incapacity) -> Decimal.
MX_CONTRIBUTION_DAYS_RULE = _rules.CONTRIBUTION_DAYS_RULE

# W3-4: LISR Art. 93 exemptions for ordinary earnings, keyed by the classification's isr_exempt_rule_key
# (treatment EXEMPT / PARTIAL). A key missing here BLOCKS (MX_EXEMPTION_RULE_MISSING).
# Interface: rule.exempt(kind, amount, facts) -> Decimal in [0, amount].
MX_ORDINARY_EXEMPTION_RULES: dict = dict(_rules.ORDINARY_EXEMPTION_RULES)


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
# Read by the transcription check (tests/test_mexico_content.py), not by the
# engine: a bracket listed here is accepted although its quota arithmetic does
# not close, because the saved source states it so (Phase 11d, gap register A14).
# Batch 1 (2026-10-26): S2 prints the 7-, 10- and 15-day tables as the
# daily table (B.I) x days — every upper limit and quota is exactly B.I x
# days — so their quotas do not close under the previous-bracket formula.
# Source wins: the values are kept as printed; the x-days relationship is
# tested exactly instead (transcription log TL-ISR-2).
MX_ISR_ARITHMETIC_EXCEPTIONS: dict = {
    ('WEEKLY_7', 2): "TL-ISR-2",
    ('WEEKLY_7', 3): "TL-ISR-2",
    ('WEEKLY_7', 7): "TL-ISR-2",
    ('WEEKLY_7', 9): "TL-ISR-2",
    ('WEEKLY_7', 11): "TL-ISR-2",
    ('DECENAL_10', 2): "TL-ISR-2",
    ('DECENAL_10', 3): "TL-ISR-2",
    ('DECENAL_10', 4): "TL-ISR-2",
    ('DECENAL_10', 7): "TL-ISR-2",
    ('DECENAL_10', 8): "TL-ISR-2",
    ('DECENAL_10', 9): "TL-ISR-2",
    ('DECENAL_10', 11): "TL-ISR-2",
    ('QUINCENAL_15', 2): "TL-ISR-2",
    ('QUINCENAL_15', 3): "TL-ISR-2",
    ('QUINCENAL_15', 4): "TL-ISR-2",
    ('QUINCENAL_15', 5): "TL-ISR-2",
    ('QUINCENAL_15', 7): "TL-ISR-2",
    ('QUINCENAL_15', 8): "TL-ISR-2",
    ('QUINCENAL_15', 9): "TL-ISR-2",
    ('QUINCENAL_15', 11): "TL-ISR-2",
}


# Batch 2 (2026-10-26): values no saved source prints, computed from printed
# components (log TL-IMSS-2, TL-VAC-1). The machine extraction looks for the
# components; tests recompute each value from them.
MX_DERIVED_VALUES: dict = {
    "mx_imss_em_fixed_quota_er_pct": {"base": "13.9", "step": "0.65", "steps": 10, "direction": 1,
                                      "source": "S10 Art. 106 I + 1995 Transitorio DECIMO NOVENO"},
    "mx_imss_em_excess_er_pct": {"base": "6", "step": "0.49", "steps": 10, "direction": -1,
                                 "source": "S10 Art. 106 II + 1995 Transitorio DECIMO NOVENO"},
    "mx_imss_em_excess_ee_pct": {"base": "2", "step": "0.16", "steps": 10, "direction": -1,
                                 "source": "S10 Art. 106 II + 1995 Transitorio DECIMO NOVENO"},
    "mx_imss_em_cash_er_pct": {"quota": "1", "share": "70", "source": "S10 Art. 107 I"},
    "mx_imss_em_cash_ee_pct": {"quota": "1", "share": "25", "source": "S10 Art. 107 II"},
    # overtime pay 'un cien / doscientos por ciento mas' of the ordinary hourly pay = 1 + premium / 100 (TL-WW-2)
    "mx_overtime_double_multiplier": {"premium": "100", "source": "S18 Art. 66 as reformed"},
    "mx_overtime_triple_multiplier": {"premium": "200", "source": "S18 Art. 68 as reformed"},
}
# The CEAV schedule is a scanned image in S11 (no text layer): its 2030 column
# is checked against the S10 Art. 168 II a) text table instead.
# The numbers the Art. 76 vacation rule is worded with (12 days, +2 per year,
# up to 20, from the sixth year +2 per five years): the machine extraction
# finds these, and a test rebuilds the derived rows from them (TL-VAC-1).
MX_VACATION_RULE_NUMBERS = ("12", "2", "20", "5")
MX_CEAV_TEXT_CROSSCHECK = ("S10/S10_IMSS_LSS.pdf", 2030, "Art. 168 II a) table (the final schedule), PDF p. 51")

# Phase 6 (D3): SAT c_PeriodicidadPago code (S28 catalog) -> Art. 96 payment
# period (MX_ISR_PERIODS). EMPTY until transcribed from the saved S28 catalog
# workbook; while empty every Mexican calculation BLOCKS
# (MX_PAY_FREQUENCY_MAPPING_MISSING) — a code is never read as a period by guess.
MX_PAY_FREQUENCY_ISR_PERIOD: dict = {
    "02": "WEEKLY_7",        # Semanal   — S2 B.II "periodo de 7 días"
    "04": "QUINCENAL_15",    # Quincenal — S2 B.IV "periodo de 15 días"
    "05": "MONTHLY",         # Mensual   — S2 B.V "pagos provisionales mensuales"
    "10": "DECENAL_10",      # Decenal   — S2 B.III "periodo de 10 días"
}
# Batch 1, transcribed 2026-10-26 [PENDING G1]. Each mapped code cites the
# catalog row (S28 c_PeriodicidadPago v1.1) and the S2 table whose heading
# names that period. NOT mapped, so they block: 01 Diario (S2 B.I is the
# tariff "en función de la cantidad de trabajo realizado y no de días
# laborados ... calculada en días" — whether a daily pay frequency uses it
# is a G1 decision), and 03 Catorcenal, 06 Bimestral, 07 Unidad obra,
# 08 Comisión, 09 Precio alzado, 99 Otra Periodicidad (no Art. 96 table in S2).
MX_PAY_FREQUENCY_ISR_PERIOD_SOURCES: dict = {
    code: (("S28/S28_SAT_catNomina.xls", f"c_PeriodicidadPago v1.1, code {code} ({label})"),
           (_S2, f"Anexo 8 RMF 2026, B.{table}"), PENDING_G1)
    for code, label, table in (("02", "Semanal", "II"), ("04", "Quincenal", "IV"), ("05", "Mensual", "V"),
                               ("10", "Decenal", "III"))
}


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
                   effective_to, tax_table_number=None, jurisdiction_state=None) -> tuple:
    # jurisdiction_state: the zone a professional minimum wage applies in
    # (Phase 11d) — None for every other slab.
    return ("SLAB", rule_type, filing_status, _d(min_amount), _d(max_amount), _d(flat_amount), _d(rate_pct),
            effective_from, effective_to, tax_table_number or None, jurisdiction_state or None)


def expected_national_signatures(start: date, end: date) -> list:
    _check_date(start)
    _check_date(end)
    out = [rate_signature(r.key, r.employee_pct, r.employer_pct, r.flat_amount, r.text_value, r.effective_from,
                          r.effective_to)
           for r in MX_SCALAR_CONTENT if _overlaps(r.effective_from, r.effective_to, start, end)]
    out += [slab_signature(MX_ISR_TARIFF_RULE, b.period, b.lower, b.upper, b.fixed_quota, b.rate_pct,
                           b.effective_from, b.effective_to)
            for b in MX_ISR_TARIFFS if _overlaps(b.effective_from, b.effective_to, start, end)]
    out += [slab_signature(MX_MIN_WAGE_RULE, w.code, "0", None, w.daily_amount, "0", w.effective_from, w.effective_to,
                           jurisdiction_state=w.zone)
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
