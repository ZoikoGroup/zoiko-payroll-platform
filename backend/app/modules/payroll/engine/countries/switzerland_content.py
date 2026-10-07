"""Switzerland — Draft canonical content.

NO ZP-CH ENGINEERING SPECIFICATION EXISTS IN THIS REPOSITORY YET. Unlike the
IT/SE/SG content files, `CH_FEDERAL_SEED_2026` is not transcribed from a signed
spec — it is built from the 2026 statutory values PUBLISHED by the Swiss
federal authorities and cited inline (S1-S10, see `CH_SOURCES` below). Every
entry is therefore flagged `needs_g1=True`, and the canonical packs are seeded
as Draft: the statutory review that must precede launch (gate G1) gets one
small, complete file to sign off, and nothing here may be activated until each
value has a named source.

Unit conventions (mirror France/Sweden/Italy):
  * percent-type values are PERCENT numbers (4.35 = 4.35%).
  * amount-type values are Swiss francs stored in flat_amount.
  * all values are calendar-year 2026 figures unless noted.

What is intentionally NOT here: canton Quellensteuer tariffs (heavy, per-canton
files — stored as inert scaffold rows that are NULL until a canton's published
tariff is entered), canton FAK top-ups (the federal minimums are here; canton
rates are scaffolds), and the KTG loss-of-earnings daily allowance (canton-
configured, scaffold). These live on the per-canton packs seeded by
scripts/seed_switzerland_canonical_packs.py, never computed.

The only QST figures at this level are the ARITHMETIC parameters the two named
engine strategies read (CH_QST_MONTHS_PER_YEAR / CH_QST_PCT_DIVISOR): the tax
figures themselves are canton tariff rows, never content.
"""
from decimal import Decimal  # noqa: E402

_STATUS = "Draft"

# ── Statutory references (cited on the seeded packs, S1-S10) ──────────────
# These are the authorities backing CH_FEDERAL_SEED_2026. The federal rates
# (S1-S3), the ALV (S4), BVG (S6) and FAK (S8) figures are 2026 values
# published by BSV / ahv-iv.ch / BVG-Kommission; the Quellensteuer note (S9)
# and Swiss rounding convention (S10) are the engine-level conventions the
# canton scaffolds will hang off after a canton's own published figures are
# entered.
CH_SOURCES = (
    ("S1", "AHV 2026 — gross contribution 8.7% (4.35% employee / 4.35% employer)",
     "https://www.ahv-iv.ch/de/Sozialversicherungen/Alters-und-Hinterlassenenversicherung-AHV-Dateien/Baeufige-Arbeitgeber"),
    ("S2", "IV 2026 — 1.4% (0.70% / 0.70%)", "https://www.ahv-iv.ch/de/Sozialversicherungen/IV-Dateien/IV-Zweigstelle"),
    ("S3", "EO 2026 — 0.5% (0.25% / 0.25%)", "https://www.ahv-iv.ch/de/Sozialversicherungen/EO-Dateien/SV-Beitraege-Arbeitgeber"),
    ("S4", "ALV 2026 — 2.2% (1.10% / 1.10%) up to a CHF 148,200 max insured annual salary",
     "https://www.adventa-treuhand.ch/wissen/aktuelles/news/alv-arbeitgeberabgabe-und-vermoegensverwaltung-grenzbetraege-2026/"),
    ("S5", "UVG 2026 — CHF 148,200 max insured annual salary; NBUV compulsory from 8 h/week",
     "https://www.adventa-treuhand.ch/wissen/aktuelles/news/bgln-grenzbetraege-2026/"),
    ("S6", "BVG 2026 — Eintrittsschwelle 22,680; Koordinationsabzug 26,460; max mandatory-BVG insurable salary 90,720; min coordinated salary 3,780",
     "https://www.koordination.ch/praxis/BVG-Masszahlen-2026"),
    ("S7", "EO parental allowance 2026 — 80% of average income, max CHF 220/day (AS 2024 463)",
     "https://www.ahv-iv.ch/de/Sozialversicherungen/EO-Dateien/Finanzierung-der-EO"),
    ("S8", "FAK 2026 — federal minimum child allowance CHF 215/mo and education allowance CHF 268/mo; entitlement/contribution earnings threshold CHF 630/mo (CHF 7,560/yr)",
     "https://www.bsv.admin.ch/bsv/de/home/sozialversicherungen/familienzulagen.html"),
    ("S9", "Quellensteuer 2026 — canton tariffs phased MONTHLY (Monatsmodell) or ANNUAL (Jahresmodell); annual-model cantons FR/GE/TI/VD/VS",
     "https://www.estv.admin.ch/estv/de/home/steuern/steuern-natuerliche-personen/quellensteuer.html"),
    ("S10", "Swiss rounding convention — statutory amounts rounded to the nearest 5 Rappen (CHF 0.05)",
     "https://www.bsv.admin.ch/bsv/de/home/sozialversicherungen/ahv/beitraege.html"),
    ("S11", "EO revision (EOG) — change-watch anchor: revised compensation in force 1 July 2027",
     "https://www.parlament.ch/de/ratsbetrieb/suche-curia-vista/geschaeft?AffairId=20220079"),
)

# ── Scheme / plan vocabulary read by onboarding and the readiness gates ────
CH_SCHEME_TYPES = ("COMPENSATION_OFFICE", "FAK", "BVG_PLAN", "UVG_POLICY", "KTG_POLICY")
CH_QST_MODELS = ("MONTHLY", "ANNUAL")

# QST ARITHMETIC parameters — the two named engine strategies read these from
# content instead of hardcoding figures in the calculator: the ANNUAL
# (Jahresmodell) strategy annualises the monthly determination income by
# CH_QST_MONTHS_PER_YEAR, applies the annual tariff, then back-apportions the
# annual tax into each month by the same divisor; CH_QST_PCT_DIVISOR turns a
# tariff PERCENT into its fraction. The TAX figures themselves are canton
# tariff rows (ChQstTariffRow), never content.
CH_QST_MONTHS_PER_YEAR = Decimal("12")
CH_QST_PCT_DIVISOR = Decimal("100")

# ── Component / obligation constants ───────────────────────────────────────
CH_AHV = "ch_ahv"                 # AHV/AVS — old-age and survivors insurance
CH_IV = "ch_iv"                   # IV/AI — invalidity insurance
CH_EO = "ch_eo"                   # EO/APG — loss-of-earnings allowance (maternity/paternity)
CH_ALV = "ch_alv"                 # ALV/AC — unemployment insurance
CH_UVG = "ch_uvg"                 # UVG — occupational and non-occupational accident insurance
CH_BVG = "ch_bvg"                 # BVG/LPP — occupational pension plan
CH_KTG = "ch_ktg"                 # KTG — canton-configured daily allowance in sickness
CH_QST = "ch_qst"                 # Quellensteuer — source tax (non-residents / cross-border)
CH_LA = "ch_la"                   # Lohnausweis — statutory declaration, NOT a contribution
CH_WAGE_FLOOR = "ch_wage_floor"   # No federal statutory minimum wage — floor only where a CBA/canton sets one

# Running totals the YTD accumulator keeps per Swiss component (the outreach
# convention of Italy's ledgers: what (ytd_taxable_wages, ytd_tax_withheld)
# holds is named on each PayrollYtdAccumulator row).
CH_YTD_COMPONENTS = (CH_AHV, CH_ALV, CH_UVG, CH_BVG, CH_KTG, CH_QST)

# The obligations a Swiss payroll must satisfy. CH_LA and CH_WAGE_FLOOR are
# declaration/classification vocabulary, NOT parameter rows (no rate lives on
# them) — they appear here so a readiness check can enumerate every obligation
# a Swiss employer has against the component keys that carry rates.
CH_OBLIGATIONS = (CH_AHV, CH_ALV, CH_BVG, CH_UVG, CH_KTG, CH_QST, CH_LA, CH_WAGE_FLOOR)

# ── Scalar engine parameter keys (mirrors italy_content.IT_PARAMETER_KEYS) ──
# Each is a ContributionRate.component_key. Kind: employer_pct | employee_pct |
# amount | text. Rates are PERCENT numbers (4.35 = 4.35%); the ceiling/threshold
# keys are Swiss francs via flat_amount.
CH_FEDERAL_PARAMETER_KEYS = {
    "ch_ahv": "employee_pct",
    "ch_iv": "employee_pct",
    "ch_eo": "employee_pct",
    "ch_alv": "employee_pct",
    "ch_alv_ceiling": "amount",
    "ch_uvg_ceiling": "amount",
    "ch_nbu_min_weekly_hours": "amount",
    "ch_bvg_entry_threshold": "amount",
    "ch_bvg_coordination_deduction": "amount",
    "ch_bvg_upper_salary": "amount",
    "ch_bvg_min_coordinated": "amount",
    "ch_fak_child_min": "amount",
    "ch_fak_education_min": "amount",
    "ch_fak_earnings_threshold_month": "amount",
    "ch_fak_earnings_threshold_year": "amount",
    "ch_eo_parental_pct": "employee_pct",
    "ch_eo_daily_cap": "amount",
    "ch_rounding_rule": "amount",
}

# Canton-scoped parameters — seeded as INERT scaffolds (every value NULL) on
# each canton pack until the canton's own published figure is entered from its
# tariff / FAK rates. The engine refuses to calculate from a NULL row.
CH_CANTON_PARAMETER_KEYS = {
    "ch_qst_model": "text",
    "ch_qst_tariff_file_id": "text",
    "ch_fak_child": "amount",
    "ch_fak_education": "amount",
    "ch_fak_employee_pct": "employee_pct",
}

CH_CANTON_PARAMETER_LABELS = {
    "ch_qst_model": "Quellensteuer model (MONTHLY | ANNUAL)",
    "ch_qst_tariff_file_id": "Quellensteuer tariff file",
    "ch_fak_child": "Family allowance — child (per month)",
    "ch_fak_education": "Family allowance — education (per month)",
    "ch_fak_employee_pct": "Family allowance — employer share (%)",
}

CH_PARAMETER_KEYS = {**CH_FEDERAL_PARAMETER_KEYS, **CH_CANTON_PARAMETER_KEYS}

# ── Federal 2026 content (S1-S10; every row needs_g1) ─────────────────────
# (component_key, label, employee_pct, employer_pct, flat_amount, source, needs_g1)
CH_FEDERAL_SEED_2026 = (
    ("ch_ahv", "AHV/AVS federal insurance (8.7% total)", "4.35", "4.35", None, "S1", True),
    ("ch_iv", "IV/AI invalidity insurance (1.4% total)", "0.70", "0.70", None, "S2", True),
    ("ch_eo", "EO/APG loss-of-earnings allowance (0.5% total)", "0.25", "0.25", None, "S3", True),
    ("ch_alv", "ALV/AC unemployment insurance (2.2% total, up to ceiling)", "1.10", "1.10", None,
     "S4", True),
    ("ch_alv_ceiling", "ALV — max insured annual salary", None, None, "148200.00", "S4", True),
    ("ch_uvg_ceiling", "UVG — max insured annual salary (occupational / NBUV)", None, None,
     "148200.00", "S5", True),
    ("ch_nbu_min_weekly_hours", "NBUV compulsory from this weekly working time", None, None,
     "8.00", "S5", True),
    ("ch_bvg_entry_threshold", "BVG — Eintrittsschwelle (annual threshold to join)", None, None,
     "22680.00", "S6", True),
    ("ch_bvg_coordination_deduction", "BVG — Koordinationsabzug (annual)", None, None,
     "26460.00", "S6", True),
    ("ch_bvg_upper_salary", "BVG — max annual salary insured in the mandatory plan", None, None,
     "90720.00", "S6", True),
    ("ch_bvg_min_coordinated", "BVG — minimum coordinated annual salary", None, None,
     "3780.00", "S6", True),
    ("ch_fak_child_min", "FAK — federal minimum child allowance (per month)", None, None,
     "215.00", "S8", True),
    ("ch_fak_education_min", "FAK — federal minimum education allowance (per month)", None, None,
     "268.00", "S8", True),
    ("ch_fak_earnings_threshold_month", "FAK — earnings threshold for entitlement (per month)",
     None, None, "630.00", "S8", True),
    ("ch_fak_earnings_threshold_year", "FAK — earnings threshold for entitlement (per year)",
     None, None, "7560.00", "S8", True),
    ("ch_eo_parental_pct", "EO — parental allowance (% of average income)", "80.00", None, None,
     "S7", True),
    ("ch_eo_daily_cap", "EO — parental allowance daily maximum", None, None, "220.00", "S7", True),
    ("ch_rounding_rule", "Rounding — amounts rounded to the nearest CHF 0.05 (5 Rappen)", None, None,
     "0.05", "S10", True),
)

# ── Cantons (ISO 3166-2:CH codes; the same codes used as jurisdiction_state) ─
# Alphabetical by code for a deterministic catalog. German-language official
# names, with the widely-used English names in common use where they differ.
CH_CANTONS = (
    ("CH-AG", "Aargau"), ("CH-AI", "Appenzell Innerrhoden"), ("CH-AR", "Appenzell Ausserrhoden"),
    ("CH-BE", "Bern"), ("CH-BL", "Basel-Landschaft"), ("CH-BS", "Basel-Stadt"),
    ("CH-FR", "Fribourg"), ("CH-GE", "Geneva"), ("CH-GL", "Glarus"),
    ("CH-GR", "Graubünden"), ("CH-JU", "Jura"), ("CH-LU", "Lucerne"),
    ("CH-NE", "Neuchâtel"), ("CH-NW", "Nidwalden"), ("CH-OW", "Obwalden"),
    ("CH-SG", "St. Gallen"), ("CH-SH", "Schaffhausen"), ("CH-SO", "Solothurn"),
    ("CH-SZ", "Schwyz"), ("CH-TG", "Thurgau"), ("CH-TI", "Ticino"),
    ("CH-UR", "Uri"), ("CH-VD", "Vaud"), ("CH-VS", "Valais"),
    ("CH-ZG", "Zug"), ("CH-ZH", "Zurich"),
)

CH_CANTON_CODES = tuple(code for code, _name in CH_CANTONS)

# Jahresmodell (annual model) cantons per S9 — the remaining cantons use the
# Monatsmodell (monthly model). Only these five carry an ANNUAL note on their
# pack's source_references; the actual tariff values are scaffold rows.
CH_QST_ANNUAL_MODEL_CANTONS = frozenset(("CH-FR", "CH-GE", "CH-TI", "CH-VD", "CH-VS"))