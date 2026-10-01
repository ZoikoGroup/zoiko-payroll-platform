// France statutory metadata + label/tone helpers (ZP-FR-ENG-001).
// Pure data, no JSX — mirrors uk/ukComponentConfig.js and
// canada/caComponentConfig.js. Single source of truth for the authority
// surfaces the France Compliance workspace presents: the FNAL/CFP class
// percentages (statutory constants — displayed as read-only reference,
// never editable data), PAS rate types and their derived source, the
// Urssaf filing due-date classes, the readiness evidence-gate statuses,
// and the DSN/outbox lifecycle tones.
//
// Tones reuse the shared StatusPill vocabulary (active | approved |
// pending | on_hold | suspended | rejected | deactivated | inactive).

// FNAL (employer logement contribution) class → administrative class plus
// the statutory percentage it maps to. The percentage is federal law, not
// per-employer data: the pack row stores only the class.
export const FNAL_CLASS_REFERENCE = {
  UNDER_50: {
    label: "FNAL — fewer than 50",
    pct: 0.10,
    note: "0.10% below the 50-employee establishment threshold",
  },
  OVER_50: {
    label: "FNAL — 50 or more",
    pct: 0.50,
    note: "0.50% at/above the 50-employee establishment threshold",
  },
};

// CFP (contribution formation professionnelle) class → statutory % it maps
// to. Same data-model: only the class is stored.
export const CFP_CLASS_REFERENCE = {
  UNDER_11: {
    label: "CFP — fewer than 11",
    pct: 0.55,
    note: "0.55% below the 11-employee establishment threshold",
  },
  OVER_11: {
    label: "CFP — 11 or more",
    pct: 1.0,
    note: "1.00% at/above the 11-employee establishment threshold",
  },
};

// The only real PAS decision is rate TYPE. The row's `source` (CRM for a
// personalized DGFiP-supplied rate, NEUTRAL_GRID for the statutory grid)
// is derived from it — the UI never lets the operator pick a contradictory
// type/source combination.
export const PAS_RATE_TYPES = {
  PERSONALIZED: {
    label: "Personalized (DGFiP CRM rate)",
    source: "CRM",
    hint: "The DGFiP authority percentage supplied through the CRM — carries ratePct and the DGFiP rate id.",
  },
  NEUTRAL: {
    label: "Neutral (statutory grid)",
    source: "NEUTRAL_GRID",
    hint: "No percentage — the engine resolves the statutory neutral grid from the payroll date.",
  },
};

export const PAS_RATE_STATUS_TONE = {
  ACTIVE: "active",
  PENDING: "pending",
  STALE: "inactive",
  CORRECTED: "rejected",
};

export const DUE_DATE_CLASSES = {
  M5: {
    label: "5th of M+1",
    eligibility: "≥ 50 employees",
    note: "filing due on the 5th of the following month",
  },
  M15: {
    label: "15th of M+1",
    eligibility: "< 50 employees",
    note: "filing due on the 15th of the following month",
  },
  DEFERRED_M15: {
    label: "Deferred M15",
    eligibility: "temporary deferral",
    note: "deferred filing due-date class (authority-granted)",
  },
};

export const READINESS_STATUSES = {
  NOT_CONFIGURED: { label: "Not configured" },
  NOT_READY: { label: "Not ready" },
  READY: { label: "Ready" },
  LIVE: { label: "Live" },
  LIVE_CHECKS_FAILING: { label: "Live — checks failing" },
};

export const IDCC_STATUSES = {
  APPLICABLE: "Applicable (IDCC code set)",
  NOT_APPLICABLE: "Not applicable",
  UNDER_REVIEW: "Unknown — under review (blocks launch)",
};

export const EFFECTIF_SOURCES = ["DSN", "PAYE", "AUTHORITY", "MANUAL"];

export const DSN_STATUS_TONE = {
  DRAFT: "inactive",
  VALIDATED: "approved",
  QUEUED: "pending",
  TRANSMITTED: "pending",
  ACKNOWLEDGED: "active",
  BUSINESS_REJECTED: "suspended",
  CRM_RESOLVED: "on_hold",
  UNKNOWN: "on_hold",
  SETTLED: "active",
};

export const OUTBOX_STATUS_TONE = {
  PENDING: "inactive",
  SENT: "approved",
  ACKNOWLEDGED: "active",
  UNKNOWN: "on_hold",
  FAILED: "suspended",
};

export function fnalReference(cls) {
  return FNAL_CLASS_REFERENCE[cls] || null;
}

export function cfpReference(cls) {
  return CFP_CLASS_REFERENCE[cls] || null;
}

export function pasRateType(type) {
  return PAS_RATE_TYPES[type] || null;
}

export function dueDateClass(cls) {
  return DUE_DATE_CLASSES[cls] || null;
}

export function dueDateClassLabel(cls) {
  const d = dueDateClass(cls);
  return d ? `${d.label} (${d.eligibility})` : cls || "—";
}

export function readinessMeta(status) {
  return READINESS_STATUSES[status] || { label: status || "Not configured" };
}

export function effectifHistory(effectifState) {
  if (!effectifState) return [];
  return Object.entries(effectifState)
    .map(([year, info]) => ({
      year: Number(year),
      value: typeof info === "object" ? info.value : info,
      source: typeof info === "object" ? info.source : "DSN",
      history: typeof info === "object" ? info.history || [] : [],
    }))
    .sort((a, b) => b.year - a.year);
}

export function latestEffectif(effectifState) {
  const history = effectifHistory(effectifState);
  return history.length ? history[0] : null;
}


// ── France statutory pack catalog (FR-003) ─────────────────────────────
// Mirrors backend engine/countries/france_content.py (keys, categories and
// value kind) — the rows engine/countries/france.py reads from the France
// JurisdictionPack. kind "ee"/"er" = PERCENT stored in the employee/employer
// rate column (6.90 = 6.90%; RGDU coefficients as % too: 37.81 = 0.3781);
// kind "amount" = flat amount (€, hours or a multiple). Keep in sync with
// the backend catalog (test_fr_content_catalog_covers_every_engine_parameter
// guards the backend side).
export const FR_PACK_CATEGORIES = [
  { key: "ceilings", label: "Ceilings & reference values" },
  { key: "smic", label: "SMIC" },
  { key: "rgdu", label: "RGDU (general reduction)" },
  { key: "social", label: "Social security" },
  { key: "csg", label: "CSG / CRDS" },
  { key: "employer_levies", label: "Employer levies" },
  { key: "agirc_arrco", label: "Agirc-Arrco retirement" },
  { key: "pas", label: "PAS (withholding tax)" },
];

export const FR_PACK_CATALOG = [
  { key: "fr_pass_annual", label: "PASS — annual Social Security ceiling", category: "ceilings", kind: "amount" },
  { key: "fr_pmss", label: "PMSS — monthly Social Security ceiling", category: "ceilings", kind: "amount" },
  { key: "fr_fulltime_monthly_hours", label: "Full-time monthly hours (35h × 52 / 12)", category: "ceilings", kind: "amount" },
  { key: "fr_chomage_ceiling_pass_multiple", label: "Unemployment/AGS ceiling (× PASS)", category: "ceilings", kind: "amount" },
  { key: "fr_agirc_t2_ceiling_pss_multiple", label: "Agirc-Arrco T2 upper limit (× PSS)", category: "ceilings", kind: "amount" },
  { key: "fr_apec_ceiling_pss_multiple", label: "Apec ceiling (× PSS)", category: "ceilings", kind: "amount" },
  { key: "fr_csg_abatement_ceiling_pss_multiple", label: "CSG 1.75% abatement ceiling (× PSS, cumulative)", category: "ceilings", kind: "amount" },
  { key: "fr_smic_hourly", label: "SMIC — hourly", category: "smic", kind: "amount" },
  { key: "fr_smic_monthly", label: "SMIC — monthly 35h", category: "smic", kind: "amount" },
  { key: "fr_smic_rgdu_annual", label: "RGDU SMIC reference — annual (frozen 1 Jan 2026)", category: "rgdu", kind: "amount" },
  { key: "fr_smic_rgdu_hourly", label: "RGDU SMIC reference — hourly (frozen 1 Jan 2026)", category: "rgdu", kind: "amount" },
  { key: "fr_rgdu_tmin", label: "RGDU Tmin (0.0200)", category: "rgdu", kind: "er" },
  { key: "fr_rgdu_tdelta_lt50", label: "RGDU Tdelta — under 50 employees (0.3781)", category: "rgdu", kind: "er" },
  { key: "fr_rgdu_tdelta_ge50", label: "RGDU Tdelta — 50+ employees (0.3821)", category: "rgdu", kind: "er" },
  { key: "fr_rgdu_power", label: "RGDU exponent", category: "rgdu", kind: "amount" },
  { key: "fr_rgdu_smic_multiple", label: "RGDU eligibility envelope (× SMIC)", category: "rgdu", kind: "amount" },
  { key: "fr_vieillesse_capped_ee", label: "Old-age capped — employee", category: "social", kind: "ee" },
  { key: "fr_vieillesse_uncapped_ee", label: "Old-age uncapped — employee", category: "social", kind: "ee" },
  { key: "fr_csg_deductible", label: "CSG deductible", category: "csg", kind: "ee" },
  { key: "fr_csg_nondeductible", label: "CSG non-deductible", category: "csg", kind: "ee" },
  { key: "fr_crds", label: "CRDS", category: "csg", kind: "ee" },
  { key: "fr_csg_base_factor", label: "CSG/CRDS base factor (98.25%)", category: "csg", kind: "ee" },
  { key: "fr_vieillesse_capped_er", label: "Old-age capped — employer", category: "social", kind: "er" },
  { key: "fr_vieillesse_uncapped_er", label: "Old-age uncapped — employer", category: "social", kind: "er" },
  { key: "fr_sante_er", label: "Health/maternity — employer (standard)", category: "social", kind: "er", pendingG1: true },
  { key: "fr_sante_er_reduced", label: "Health/maternity — employer (reduced)", category: "social", kind: "er", pendingG1: true },
  { key: "fr_famille_er", label: "Family allowances — employer", category: "social", kind: "er", pendingG1: true },
  { key: "fr_csa_er", label: "CSA (solidarity-autonomy) — employer", category: "social", kind: "er", pendingG1: true },
  { key: "fr_chomage_er", label: "Unemployment — employer", category: "social", kind: "er" },
  { key: "fr_ags_er", label: "AGS — employer", category: "social", kind: "er" },
  { key: "fr_fnal_er_0p10", label: "FNAL — under 50 (capped)", category: "employer_levies", kind: "er" },
  { key: "fr_fnal_er_0p50", label: "FNAL — 50+ (total pay)", category: "employer_levies", kind: "er" },
  { key: "fr_cfp_er_0p55", label: "CFP — under 11 employees", category: "employer_levies", kind: "er" },
  { key: "fr_cfp_er_1p00", label: "CFP — 11+ employees", category: "employer_levies", kind: "er" },
  { key: "fr_apprentissage_er", label: "Apprenticeship tax — main share", category: "employer_levies", kind: "er" },
  { key: "fr_apprentissage_balance_er", label: "Apprenticeship tax — balance", category: "employer_levies", kind: "er" },
  { key: "fr_agirc_t1_ee", label: "Agirc-Arrco T1 — employee", category: "agirc_arrco", kind: "ee" },
  { key: "fr_agirc_t1_er", label: "Agirc-Arrco T1 — employer", category: "agirc_arrco", kind: "er" },
  { key: "fr_agirc_t2_ee", label: "Agirc-Arrco T2 — employee", category: "agirc_arrco", kind: "ee" },
  { key: "fr_agirc_t2_er", label: "Agirc-Arrco T2 — employer", category: "agirc_arrco", kind: "er" },
  { key: "fr_ceg_t1_ee", label: "CEG T1 — employee", category: "agirc_arrco", kind: "ee" },
  { key: "fr_ceg_t1_er", label: "CEG T1 — employer", category: "agirc_arrco", kind: "er" },
  { key: "fr_ceg_t2_ee", label: "CEG T2 — employee", category: "agirc_arrco", kind: "ee" },
  { key: "fr_ceg_t2_er", label: "CEG T2 — employer", category: "agirc_arrco", kind: "er" },
  { key: "fr_cet_ee", label: "CET — employee", category: "agirc_arrco", kind: "ee" },
  { key: "fr_cet_er", label: "CET — employer", category: "agirc_arrco", kind: "er" },
  { key: "fr_apec_ee", label: "Apec (cadres) — employee", category: "agirc_arrco", kind: "ee" },
  { key: "fr_apec_er", label: "Apec (cadres) — employer", category: "agirc_arrco", kind: "er" },
  { key: "fr_pas_short_contract_abatement", label: "PAS short-contract base abatement (€)", category: "pas", kind: "amount" },
  { key: "fr_pas_apprentice_threshold", label: "PAS apprentice/trainee exemption threshold (€/year)", category: "pas", kind: "amount" },
];

export function frCatalogEntry(key) {
  return FR_PACK_CATALOG.find((e) => e.key === key) || null;
}
