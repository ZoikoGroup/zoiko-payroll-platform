"""Italy (ZP-IT-ENG-001) — Draft canonical content.

SPLIT FROM italy.py ON PURPOSE. Every seedable Italian figure lives here as
explicit data so a reviewer can audit the NUMBERS (this file) without reading
the CALCULATION LOGIC (italy.py), and so the statutory review that must precede
launch (spec gate G1) has one small, complete file to sign off.

Status is Draft throughout and the registry row stays PLANNED. Each figure is
the one the specification states in §2-§7/§13 and cites it; the local surtax
rates and the INPS classification codes are NOT in the specification and are
marked "needs source" — they must be replaced from the MEF local-tax database
and the INPS technical catalogs (IT-012, IT-043) before activation.

D1 — INPS classification is NOT a table. The matrix is ContributionRate rows:
  jurisdiction_state = "CSC_<csc>" or "CSC_<csc>_CA_<ca>"
  tax_regime        = worker class (qualifica)
  component_key     = the contribution family (it_inps_ivs, it_inps_cigs, ...)
  filing_status     = UniEmens causale (reporting value only, not a rate key)

WIDTHS: TaxSlab.tax_table_number and tax_column are VARCHAR(10), rule_type is
VARCHAR(30); tax domicile is stored as codes (ISTAT region code, 2 chars;
cadastral comune code, 4 chars) so it fits it_tax_domicile_region String(10)
and never truncates a name such as "Emilia-Romagna".
"""
_STATUS = "Draft"

# ── TaxSlab.rule_type discriminators (all ≤ 30 chars) ──────────────────────
IT_IRPEF_BRACKET_RULE = "IT_IRPEF_BRACKET"     # §3 national brackets
IT_DETR_FIXED_RULE = "IT_DETR_FIXED"           # §4 detrazione lavoro, fixed part per band
IT_DETR_TAPER_RULE = "IT_DETR_TAPER"           # §4 detrazione lavoro, tapering part per band
IT_ADDL_FIXED_RULE = "IT_ADDL_DED_FIXED"       # §4 wedge additional deduction, fixed part
IT_ADDL_TAPER_RULE = "IT_ADDL_DED_TAPER"       # §4 wedge additional deduction, tapering part
IT_WEDGE_SUM_RULE = "IT_WEDGE_SUM"             # §4 wedge non-taxable sum percentage bands
IT_ADDREG_RULE = "IT_ADDREG"                   # §5 regional surtax brackets
IT_ADDREG_EXEMPT_RULE = "IT_ADDREG_EXEMPT"     # §5 regional exemption threshold
IT_ADDCOM_RULE = "IT_ADDCOM"                   # §5 municipal surtax brackets
IT_ADDCOM_EXEMPT_RULE = "IT_ADDCOM_EXEMPT"     # §5 municipal exemption threshold

# ── TaxSlab.tax_table_number values (all ≤ 10 chars) ───────────────────────
TBL_IRPEF26 = "IRPEF26"
TBL_DETR26 = "DETR26"
TBL_ADDL26 = "ADDL26"
TBL_WEDGE26 = "WEDGE26"
REGION_TABLE_PREFIX = "REG_"     # + ISTAT region code  → "REG_03"
COMUNE_TABLE_PREFIX = "COM_"     # + cadastral code     → "COM_F205"

# ── Scalar engine parameter keys (mirrors italy.IT_PARAMETER_KEYS) ──────────
# Each is a ContributionRate.component_key. Kind: employer_pct | employee_pct |
# amount. Rates are PERCENT numbers (9.19 = 9.19%), France's convention.
IT_PARAMETER_KEYS = {
    "it_ivs_additional_pct": "employee_pct",
    "it_ivs_additional_threshold": "amount",
    "it_contributory_ceiling": "amount",
    "it_tfr_divisor": "amount",
    "it_tfr_inps_offset": "employer_pct",
    "it_tesoreria_headcount_threshold": "amount",
    "it_detrazione_min_permanent": "amount",
    "it_detrazione_min_fixed_term": "amount",
    "it_mensilita_default": "amount",
    "it_fis_small_employer": "employer_pct",
    "it_fis_large_employer": "employer_pct",
    # §5 local-surtax withholding schedule: pay MONTHS (1-12) bounding each
    # instalment window, and the municipal advance percentage.
    "it_addreg_saldo_first_month": "amount",
    "it_addreg_saldo_last_month": "amount",
    "it_addcom_saldo_first_month": "amount",
    "it_addcom_saldo_last_month": "amount",
    "it_addcom_acconto_pct": "employee_pct",
    "it_addcom_acconto_first_month": "amount",
    "it_addcom_acconto_last_month": "amount",
    # §2/§6 INPS contributory minimum — NOT a wage floor (IT-004).
    "it_inps_daily_minimum": "amount",
    "it_inps_full_month_days": "amount",
    "it_inps_parttime_hourly_factor": "amount",
    # §11 annual fringe exemption and per-voucher meal exemptions.
    "it_fringe_exempt_limit": "amount",
    "it_fringe_exempt_limit_children": "amount",
    "it_meal_electronic_exempt": "amount",
    "it_meal_paper_exempt": "amount",
    # §4 / IT-011 recovery of a wedge sum that turns out not to be due.
    "it_wedge_recovery_threshold": "amount",
    "it_wedge_recovery_instalments": "amount",
}

# (component_key, label, employee_pct, employer_pct, flat_amount, source)
IT_SCALAR_CONTENT = (
    ("it_ivs_additional_pct", "Additional 1% IVS (employee)", "1.0000", None, None,
     "§6 / IT-016"),
    ("it_ivs_additional_threshold", "Additional 1% IVS annual threshold", None, None,
     "56224.00", "§2 / §6"),
    ("it_contributory_ceiling", "Annual contributory maximum (cohort only)", None, None,
     "122295.00", "§2 / §6 / IT-017"),
    ("it_tfr_divisor", "TFR accrual divisor (remuneration / 13.5)", None, None,
     "13.50", "§13 / Codice civile art. 2120"),
    ("it_tfr_inps_offset", "TFR offset for the 0.50% INPS contribution", None, "0.5000",
     None, "§13 — needs source (L. 297/1982 art. 3)"),
    ("it_tesoreria_headcount_threshold", "Fondo Tesoreria prior-year average headcount",
     None, None, "60.00", "§2 / §14 (2026-2027)"),
    ("it_detrazione_min_permanent", "Detrazione lavoro floor (permanent contract)",
     None, None, "690.00", "§4 'statutory minimum rules' — needs source (TUIR art. 13)"),
    ("it_detrazione_min_fixed_term", "Detrazione lavoro floor (fixed-term contract)",
     None, None, "1380.00", "§4 'statutory minimum rules' — needs source (TUIR art. 13)"),
    ("it_mensilita_default", "Default mensilità per year (CCNL overrides, D5)",
     None, None, "13.00", "Decision 2 (2026-10-01): default 13 until CCNL content lands"),
    # IT-020: FIS 0.50% (≤5 employees) / 0.80% (>5), split ⅔ employer / ⅓
    # employee. Shares are the rounded split INPS publishes.
    ("it_fis_small_employer", "FIS (≤5 employees)", "0.1700", "0.3300", None,
     "§7 / IT-020"),
    ("it_fis_large_employer", "FIS (>5 employees)", "0.2700", "0.5300", None,
     "§7 / IT-020"),
    # §5 withholding schedule. The specification requires the regional balance,
    # the municipal balance and the municipal advance as distinct deductions
    # withheld "using the current legal schedule" but does not state it; these
    # are the statutory figures, cited, pending the G1 review.
    ("it_addreg_saldo_first_month", "Regional balance — first instalment month", None, None,
     "1.00", "§5 — needs source review (D.Lgs. 446/1997 art. 50 c.4: up to 11 instalments)"),
    ("it_addreg_saldo_last_month", "Regional balance — last instalment month (November)", None, None,
     "11.00", "§5 — needs source review (D.Lgs. 446/1997 art. 50 c.4)"),
    ("it_addcom_saldo_first_month", "Municipal balance — first instalment month", None, None,
     "1.00", "§5 — needs source review (D.Lgs. 360/1998 art. 1 c.5: same schedule as regional)"),
    ("it_addcom_saldo_last_month", "Municipal balance — last instalment month (November)", None, None,
     "11.00", "§5 — needs source review (D.Lgs. 360/1998 art. 1 c.5)"),
    ("it_addcom_acconto_pct", "Municipal advance — % of prior-year municipal amount", "30.0000", None,
     None, "§5 — needs source review (D.Lgs. 360/1998 art. 1 c.4: 30% advance)"),
    ("it_addcom_acconto_first_month", "Municipal advance — first instalment month (March)", None, None,
     "3.00", "§5 — needs source review (D.Lgs. 360/1998 art. 1 c.5: up to 9 instalments from March)"),
    ("it_addcom_acconto_last_month", "Municipal advance — last instalment month (November)", None, None,
     "11.00", "§5 — needs source review (D.Lgs. 360/1998 art. 1 c.5)"),
    # §2/§6 / IT-004 / IT-018 — the contributory minimum. It raises the base
    # INPS is paid on; it is never a salary floor shown to anyone (IT-004).
    ("it_inps_daily_minimum", "INPS contributory daily minimum (2026)", None, None,
     "58.13", "§2 / §6 / IT-004 (INPS Circular 6/2026)"),
    ("it_inps_full_month_days", "Contributory days in a full month (monthly-paid)", None, None,
     "26.00", "§6 — needs source review (INPS monthly-paid convention: 26 days)"),
    ("it_inps_parttime_hourly_factor", "Part-time hourly minimum = daily minimum × factor ÷ CCNL weekly hours",
     None, None, "6.00", "IT-018 — needs source review (INPS part-time hourly minimum)"),
    # §11 / IT-031 — aggregate annual fringe exemption under the temporary
    # 2025-2027 rule; crossing it makes the WHOLE amount taxable.
    ("it_fringe_exempt_limit", "Fringe benefits — annual exemption", None, None,
     "1000.00", "§2 / §11 / IT-031 (L. 207/2024, 2025-2027)"),
    ("it_fringe_exempt_limit_children", "Fringe benefits — annual exemption with child declaration",
     None, None, "2000.00", "§2 / §11 / IT-032 — requires the employee's own declaration"),
    # §11 — per-voucher exemption; only the excess over it is taxable.
    ("it_meal_electronic_exempt", "Electronic meal voucher — exempt per voucher (2026)", None, None,
     "10.00", "§2 / §11"),
    ("it_meal_paper_exempt", "Paper meal voucher — exempt per voucher", None, None,
     "4.00", "§11 'separate statutory limit' — needs source review (TUIR art. 51 c.2 lett. c)"),
    # §4 / IT-011 — a wedge sum found not due at conguaglio is recovered in
    # equal instalments when it exceeds the threshold.
    ("it_wedge_recovery_threshold", "Wedge sum recovery — instalments above this amount", None, None,
     "60.00", "§4 / IT-011"),
    ("it_wedge_recovery_instalments", "Wedge sum recovery — number of instalments", None, None,
     "10.00", "§4 / IT-011"),
)

# ── §6/§7 INPS matrix (D1: ContributionRate, no dedicated table) ───────────
# (csc, ca, worker_class, component_key, causale, employee_pct, employer_pct)
#
# IT-002: EXHAUSTIVE by design — a CSC/CA/class/family that is not here BLOCKS.
# The IVS figures are §6's ordinary FPLD reference (33% = 9.19 + 23.81); CIGS is
# the §6 employee variation (9.19 → 9.49) with its employer share. The CSC code
# and the class names are placeholders pending the INPS catalogs (IT-043).
_DRAFT_CSC = "70501"   # needs source — INPS CSC catalog
_DRAFT_CLASSES = ("OPERAIO", "IMPIEGATO", "QUADRO")   # needs source — UniEmens Qualifica
IT_INPS_MATRIX = tuple(
    row
    for worker_class in _DRAFT_CLASSES
    for row in (
        (_DRAFT_CSC, None, worker_class, "it_inps_ivs", None, "9.1900", "23.8100"),
        (_DRAFT_CSC, None, worker_class, "it_inps_cigs", None, "0.3000", "0.9000"),
    )
)

# ── §3/§4 TaxSlab content ──────────────────────────────────────────────────
# (rule_type, tax_table_number, min_amount, max_amount, rate_pct, flat_amount, label)
# Bands are (min, max]: "up to €28,000" includes €28,000 (§3 table).
IT_TAX_SLABS = (
    # §3 IRPEF 2026
    (IT_IRPEF_BRACKET_RULE, TBL_IRPEF26, "0", "28000", "23.0000", None,
     "IRPEF 2026 — up to EUR 28,000"),
    (IT_IRPEF_BRACKET_RULE, TBL_IRPEF26, "28000", "50000", "33.0000", None,
     "IRPEF 2026 — EUR 28,000.01 to 50,000"),
    (IT_IRPEF_BRACKET_RULE, TBL_IRPEF26, "50000", None, "43.0000", None,
     "IRPEF 2026 — above EUR 50,000"),

    # §4 detrazione lavoro: amount = fixed + taper × (max − R) / (max − min),
    # pro-rated to days worked. One FIXED and one TAPER row per band.
    (IT_DETR_FIXED_RULE, TBL_DETR26, "0", "15000", "0", "1955.00",
     "Detrazione lavoro ≤ EUR 15,000 — EUR 1,955"),
    (IT_DETR_TAPER_RULE, TBL_DETR26, "0", "15000", "0", "0.00",
     "Detrazione lavoro ≤ EUR 15,000 — no taper"),
    (IT_DETR_FIXED_RULE, TBL_DETR26, "15000", "28000", "0", "1910.00",
     "Detrazione lavoro EUR 15,000-28,000 — EUR 1,910"),
    (IT_DETR_TAPER_RULE, TBL_DETR26, "15000", "28000", "0", "1190.00",
     "Detrazione lavoro EUR 15,000-28,000 — + 1,190 × (28,000 − R) / 13,000"),
    (IT_DETR_FIXED_RULE, TBL_DETR26, "28000", "50000", "0", "0.00",
     "Detrazione lavoro EUR 28,000-50,000 — no fixed part"),
    (IT_DETR_TAPER_RULE, TBL_DETR26, "28000", "50000", "0", "1910.00",
     "Detrazione lavoro EUR 28,000-50,000 — 1,910 × (50,000 − R) / 22,000"),

    # §4 structural wedge — additional deduction (separate from detrazione lavoro).
    (IT_ADDL_FIXED_RULE, TBL_ADDL26, "20000", "32000", "0", "1000.00",
     "Wedge additional deduction EUR 20,000-32,000 — EUR 1,000"),
    (IT_ADDL_TAPER_RULE, TBL_ADDL26, "20000", "32000", "0", "0.00",
     "Wedge additional deduction EUR 20,000-32,000 — no taper"),
    (IT_ADDL_FIXED_RULE, TBL_ADDL26, "32000", "40000", "0", "0.00",
     "Wedge additional deduction EUR 32,000-40,000 — no fixed part"),
    (IT_ADDL_TAPER_RULE, TBL_ADDL26, "32000", "40000", "0", "1000.00",
     "Wedge additional deduction EUR 32,000-40,000 — 1,000 × (40,000 − R) / 8,000"),

    # §4 structural wedge — non-taxable sum (a benefit, never negative IRPEF).
    (IT_WEDGE_SUM_RULE, TBL_WEDGE26, "0", "8500", "7.1000", None,
     "Wedge non-taxable sum — income ≤ EUR 8,500: 7.1%"),
    (IT_WEDGE_SUM_RULE, TBL_WEDGE26, "8500", "15000", "5.3000", None,
     "Wedge non-taxable sum — EUR 8,500-15,000: 5.3%"),
    (IT_WEDGE_SUM_RULE, TBL_WEDGE26, "15000", "20000", "4.8000", None,
     "Wedge non-taxable sum — EUR 15,000-20,000: 4.8%"),
)

# ── §5 local surtax content (Draft — needs MEF source, IT-012) ─────────────
# Regional and municipal tables are bracketed (IT-014) and keyed on the TAX
# DOMICILE code (IT-013). Only Lombardia/Milano are staged; every other launch
# locality deliberately has NO rows, so payroll for it BLOCKS until real MEF
# content is entered, rather than running on a guessed rate.
# (rule_type, tax_table_number, min_amount, max_amount, rate_pct, flat_amount, label)
IT_LOCAL_TAX_SLABS = (
    (IT_ADDREG_RULE, "REG_03", "0", "15000", "1.2300", None,
     "Lombardia addizionale regionale — up to EUR 15,000 (Draft, needs MEF source)"),
    (IT_ADDREG_RULE, "REG_03", "15000", "28000", "1.5800", None,
     "Lombardia addizionale regionale — EUR 15,000-28,000 (Draft, needs MEF source)"),
    (IT_ADDREG_RULE, "REG_03", "28000", "50000", "1.7200", None,
     "Lombardia addizionale regionale — EUR 28,000-50,000 (Draft, needs MEF source)"),
    (IT_ADDREG_RULE, "REG_03", "50000", None, "1.7300", None,
     "Lombardia addizionale regionale — above EUR 50,000 (Draft, needs MEF source)"),
    (IT_ADDCOM_RULE, "COM_F205", "0", None, "0.8000", None,
     "Milano addizionale comunale — 0.8% (Draft, needs MEF source)"),
    (IT_ADDCOM_EXEMPT_RULE, "COM_F205", "0", None, "0", "23000.00",
     "Milano addizionale comunale — exempt up to EUR 23,000 (Draft, needs MEF source)"),
)

# ── Localities (ISTAT region codes; cadastral comune codes) ────────────────
IT_REGIONS = (
    ("01", "Piemonte"), ("02", "Valle d'Aosta"), ("03", "Lombardia"),
    ("04", "Trentino-Alto Adige"), ("05", "Veneto"), ("06", "Friuli-Venezia Giulia"),
    ("07", "Liguria"), ("08", "Emilia-Romagna"), ("09", "Toscana"), ("10", "Umbria"),
    ("11", "Marche"), ("12", "Lazio"), ("13", "Abruzzo"), ("14", "Molise"),
    ("15", "Campania"), ("16", "Puglia"), ("17", "Basilicata"), ("18", "Calabria"),
    ("19", "Sicilia"), ("20", "Sardegna"),
)

# Launch communes (D4 — superset staged; Super Admin extends before activation).
# (cadastral code, comune name, ISTAT region code)
IT_LAUNCH_COMMUNI = (
    ("F205", "Milano", "03"),
    ("H501", "Roma", "12"),
    ("F839", "Napoli", "15"),
    ("L219", "Torino", "01"),
    ("G273", "Palermo", "19"),
    ("D969", "Genova", "07"),
    ("A944", "Bologna", "08"),
    ("D612", "Firenze", "09"),
    ("L736", "Venezia", "05"),
)
