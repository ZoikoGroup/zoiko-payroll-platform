"""
engine/countries/mexico_content.py
----------------------------------
Mexico statutory content (ZP-MX-ENG-001 v1.0) — pure data, no ORM, no
framework. scripts/seed_mexico_canonical_packs.py (Phase 1) writes it into
Draft canonical packs; countries/mexico.py only ever reads the rows those
packs resolve to by pay date / contribution period (MX-003, MX-004), never
these constants directly.

Phase 0 (scaffolding): identifiers and the evidence register only. No rate,
tariff, threshold or catalog value is declared here yet — Phase 1 adds them,
each transcribed from an official source saved under docs/mexico/sources/,
flagged [PENDING G1] and linked to a SourceArtifact (URL + SHA-256).
"""

from __future__ import annotations

from datetime import date

SPEC = "ZP-MX-ENG-001 v1.0"
PACK_STATUS = "Draft"  # seeds never create anything else

# (pack id, legal interval start, legal interval end)
MX_2026 = ("MX-PAYROLL-2026", date(2026, 1, 1), date(2026, 12, 31))
# State Impuesto Sobre Nóminas overlays: one pack per state (MX-047),
# parent_pack_id -> the national pack. CDMX only until further states are
# confirmed (Phase 0 decision 7).
MX_ISN_PACK_ID_FORMAT = "MX-ISN-{state}-2026"
MX_ISN_STATES_IN_SCOPE = ("CDMX",)

# TaxSlab discriminators (rule_type) — Phase 1 rows. countries/mexico.py
# reads only rows whose rule_type starts with "MX_" (§4 of the Phase 0 gap
# assessment: MX is NOT a _NO_TAX_SLAB_COUNTRIES country).
MX_ISR_TARIFF_RULE = "MX_ISR_TARIFF"
MX_CEAV_BAND_RULE = "MX_CEAV_BAND"
MX_MIN_WAGE_RULE = "MX_MIN_WAGE"
MX_VACATION_DAYS_RULE = "MX_VACATION_DAYS"
MX_WORKWEEK_RULE = "MX_WORKWEEK"

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

# component_key -> kind, for every ContributionRate row a Mexico pack may
# carry. Empty until Phase 1; the seed refuses any key not listed here.
MX_PARAMETER_KEYS: dict = {}
