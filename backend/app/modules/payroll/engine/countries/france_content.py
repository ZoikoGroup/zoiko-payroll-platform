"""
modules/payroll/engine/countries/france_content.py
----------------------------------------------------
The France 2026 statutory content catalog (ZP-FR-ENG-001 FR-003) — the ONE
list of every rate and parameter row engine/countries/france.py reads from
`rate_map`. Pure data, no ORM import, so it is shared by:

  * scripts/seed_france_canonical_packs.py — writes these rows into the
    FR-2026-H1 / FR-2026-H2 canonical JurisdictionPacks (Draft);
  * tests/test_france_payroll.py — builds its golden-vector rate_map from
    the same rows, so the tests exercise exactly what gets seeded;
  * the Super Admin France component picker (via the fallback registry /
    frontend catalog, which mirror the keys and categories below).

Conventions (must match france.py):
  * kind "ee" / "er" — a PERCENT number (6.90 = 6.90%) stored in
    ContributionRate.employee_rate_pct / employer_rate_pct (Numeric(7,4)).
    RGDU coefficients and the CSG base factor are percent-type on purpose:
    flat_amount is Numeric(14,2) and would round 0.3781 to 0.38.
  * kind "amount" — ContributionRate.flat_amount (euros, hours or a plain
    multiple).
  * effective_from / effective_to — row-level dating INSIDE a pack
    (tax_resolver.resolve_tax_configuration filters on it), which is how
    the 1 June 2026 SMIC revaluation switches without a code branch.

Values marked PENDING_G1 are not numerically quoted by the spec (health,
family, CSA) and must be signed off by a French payroll specialist at gate
G1 before any pack carrying them is activated.
"""

from datetime import date
from decimal import Decimal

FR_2026_H1 = ("FR-2026-H1", date(2026, 1, 1), date(2026, 4, 30))
FR_2026_H2 = ("FR-2026-H2", date(2026, 5, 1), date(2026, 12, 31))

SOURCE_REFERENCES = (
    "ZP-FR-ENG-001 v1.0 §2/§5/§6/§7/§8/§9 and evidence register S1-S21: "
    "Urssaf 2026 private-sector rates (S1), PASS 2026 (S2), SMIC 1 Jan / 1 Jun 2026 (S3), "
    "Agirc-Arrco 2026 (S11/S12), RGDU 2026 (S13), FNAL (S14), CFP (S15), apprenticeship tax (S16), "
    "net-entreprises PAS 2026 updates (S8)."
)

_SMIC_JAN_MAY = (date(2026, 1, 1), date(2026, 5, 31))
_SMIC_FROM_JUN = (date(2026, 6, 1), None)

# (component_key, label, category, kind, value, effective_from, effective_to, note)
FR_2026_CONTENT = [
    # ── Ceilings & reference values ─────────────────────────────────────
    ("fr_pass_annual", "PASS — annual Social Security ceiling", "ceilings", "amount", "48060", None, None, "S2"),
    ("fr_pmss", "PMSS — monthly Social Security ceiling", "ceilings", "amount", "4005", None, None, "S2"),
    ("fr_fulltime_monthly_hours", "Full-time monthly hours (35h × 52 / 12)", "ceilings", "amount", "151.67", None, None, "§14"),
    ("fr_chomage_ceiling_pass_multiple", "Unemployment/AGS ceiling (× PASS)", "ceilings", "amount", "4", None, None, "§2"),
    ("fr_agirc_t2_ceiling_pss_multiple", "Agirc-Arrco T2 upper limit (× PSS)", "ceilings", "amount", "8", None, None, "§7"),
    ("fr_apec_ceiling_pss_multiple", "Apec ceiling (× PSS)", "ceilings", "amount", "4", None, None, "§7"),
    ("fr_csg_abatement_ceiling_pss_multiple", "CSG 1.75% abatement ceiling (× PSS, cumulative)", "ceilings", "amount", "4", None, None, "§6"),
    # SMIC — dated rows inside the pack (FR-004 intrayear boundary)
    ("fr_smic_hourly", "SMIC — hourly (Jan–May 2026)", "smic", "amount", "12.02", *_SMIC_JAN_MAY, "S3"),
    ("fr_smic_hourly", "SMIC — hourly (from 1 Jun 2026)", "smic", "amount", "12.31", *_SMIC_FROM_JUN, "S3"),
    ("fr_smic_monthly", "SMIC — monthly 35h (Jan–May 2026)", "smic", "amount", "1823.03", *_SMIC_JAN_MAY, "S3"),
    ("fr_smic_monthly", "SMIC — monthly 35h (from 1 Jun 2026)", "smic", "amount", "1867.02", *_SMIC_FROM_JUN, "S3"),
    # RGDU SMIC reference: frozen at the 1 January value for all of 2026
    # (décret n° 2026-509, per the engine's existing FR-024 treatment).
    ("fr_smic_rgdu_annual", "RGDU SMIC reference — annual (frozen 1 Jan 2026)", "rgdu", "amount", "21876.64", None, None, "S13"),
    ("fr_smic_rgdu_hourly", "RGDU SMIC reference — hourly (frozen 1 Jan 2026)", "rgdu", "amount", "12.02", None, None, "S13"),
    # ── RGDU parameters ─────────────────────────────────────────────────
    ("fr_rgdu_tmin", "RGDU Tmin (0.0200)", "rgdu", "er", "2.00", None, None, "S13"),
    ("fr_rgdu_tdelta_lt50", "RGDU Tdelta — under 50 employees (0.3781)", "rgdu", "er", "37.81", None, None, "S13"),
    ("fr_rgdu_tdelta_ge50", "RGDU Tdelta — 50+ employees (0.3821)", "rgdu", "er", "38.21", None, None, "S13"),
    ("fr_rgdu_power", "RGDU exponent", "rgdu", "amount", "1.75", None, None, "S13"),
    ("fr_rgdu_smic_multiple", "RGDU eligibility envelope (× SMIC)", "rgdu", "amount", "3", None, None, "S13"),
    # ── Employee social contributions ───────────────────────────────────
    ("fr_vieillesse_capped_ee", "Old-age capped — employee", "social", "ee", "6.90", None, None, "S1"),
    ("fr_vieillesse_uncapped_ee", "Old-age uncapped — employee", "social", "ee", "0.40", None, None, "S1"),
    ("fr_csg_deductible", "CSG deductible", "csg", "ee", "6.80", None, None, "§6"),
    ("fr_csg_nondeductible", "CSG non-deductible", "csg", "ee", "2.40", None, None, "§6"),
    ("fr_crds", "CRDS", "csg", "ee", "0.50", None, None, "§6"),
    ("fr_csg_base_factor", "CSG/CRDS base factor (98.25%)", "csg", "ee", "98.25", None, None, "§6"),
    # ── Employer social contributions ───────────────────────────────────
    ("fr_vieillesse_capped_er", "Old-age capped — employer", "social", "er", "8.55", None, None, "S1"),
    ("fr_vieillesse_uncapped_er", "Old-age uncapped — employer", "social", "er", "2.11", None, None, "S1"),
    ("fr_sante_er", "Health/maternity — employer (standard)", "social", "er", "13.00", None, None, "PENDING_G1"),
    ("fr_sante_er_reduced", "Health/maternity — employer (reduced)", "social", "er", "7.00", None, None, "PENDING_G1"),
    ("fr_famille_er", "Family allowances — employer", "social", "er", "5.25", None, None, "PENDING_G1"),
    ("fr_csa_er", "CSA (solidarity-autonomy) — employer", "social", "er", "0.50", None, None, "PENDING_G1"),
    ("fr_chomage_er", "Unemployment — employer", "social", "er", "4.00", None, None, "§2"),
    ("fr_ags_er", "AGS — employer", "social", "er", "0.25", None, None, "§2"),
    ("fr_fnal_er_0p10", "FNAL — under 50 (capped)", "employer_levies", "er", "0.10", None, None, "S14"),
    ("fr_fnal_er_0p50", "FNAL — 50+ (total pay)", "employer_levies", "er", "0.50", None, None, "S14"),
    ("fr_cfp_er_0p55", "CFP — under 11 employees", "employer_levies", "er", "0.55", None, None, "S15"),
    ("fr_cfp_er_1p00", "CFP — 11+ employees", "employer_levies", "er", "1.00", None, None, "S15"),
    ("fr_apprentissage_er", "Apprenticeship tax — main share", "employer_levies", "er", "0.59", None, None, "S16"),
    ("fr_apprentissage_balance_er", "Apprenticeship tax — balance", "employer_levies", "er", "0.09", None, None, "S16"),
    # ── Agirc-Arrco ─────────────────────────────────────────────────────
    ("fr_agirc_t1_ee", "Agirc-Arrco T1 — employee", "agirc_arrco", "ee", "3.15", None, None, "S11"),
    ("fr_agirc_t1_er", "Agirc-Arrco T1 — employer", "agirc_arrco", "er", "4.72", None, None, "S11"),
    ("fr_agirc_t2_ee", "Agirc-Arrco T2 — employee", "agirc_arrco", "ee", "8.64", None, None, "S11"),
    ("fr_agirc_t2_er", "Agirc-Arrco T2 — employer", "agirc_arrco", "er", "12.95", None, None, "S11"),
    ("fr_ceg_t1_ee", "CEG T1 — employee", "agirc_arrco", "ee", "0.86", None, None, "S11"),
    ("fr_ceg_t1_er", "CEG T1 — employer", "agirc_arrco", "er", "1.29", None, None, "S11"),
    ("fr_ceg_t2_ee", "CEG T2 — employee", "agirc_arrco", "ee", "1.08", None, None, "S11"),
    ("fr_ceg_t2_er", "CEG T2 — employer", "agirc_arrco", "er", "1.62", None, None, "S11"),
    ("fr_cet_ee", "CET — employee", "agirc_arrco", "ee", "0.14", None, None, "S11"),
    ("fr_cet_er", "CET — employer", "agirc_arrco", "er", "0.21", None, None, "S11"),
    ("fr_apec_ee", "Apec (cadres) — employee", "agirc_arrco", "ee", "0.024", None, None, "S11"),
    ("fr_apec_er", "Apec (cadres) — employer", "agirc_arrco", "er", "0.036", None, None, "S11"),
    # ── PAS parameters ──────────────────────────────────────────────────
    ("fr_pas_short_contract_abatement", "PAS short-contract base abatement (€)", "pas", "amount", "748", None, None, "S8"),
    ("fr_pas_apprentice_threshold", "PAS apprentice/trainee exemption threshold (€/year)", "pas", "amount", "21876", None, None, "S8"),
]

FR_CATEGORIES = {
    "ceilings": "Ceilings & reference values",
    "smic": "SMIC",
    "rgdu": "RGDU (general reduction)",
    "social": "Social security",
    "csg": "CSG / CRDS",
    "employer_levies": "Employer levies",
    "agirc_arrco": "Agirc-Arrco retirement",
    "pas": "PAS (withholding tax)",
}


def content_rows_in_force(as_of: date):
    """The content rows in force on `as_of` (row-level dating), one per key —
    the same selection tax_resolver makes inside an Active pack."""
    selected = {}
    for key, label, category, kind, value, eff_from, eff_to, note in FR_2026_CONTENT:
        if eff_from is not None and as_of < eff_from:
            continue
        if eff_to is not None and as_of > eff_to:
            continue
        selected[key] = (key, label, category, kind, Decimal(value), eff_from, eff_to, note)
    return selected
