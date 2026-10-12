// Australia Compliance UI config (ZP-TAX-AU-2026-27-001, Phase 6) — key
// lists driving the PAYG/STSL coefficient editors and the Medicare/Super/
// Special Payments component pickers. Mirrors caComponentConfig.js's own
// role (plain key lists, no component logic) for Canada.

// §6's own Schedule 1 Scale registry — the TaxSlab.filing_status value
// each AU_PAYG_COEFFICIENT band is tagged with (see engine/countries/
// australia.py's _resolve_au_payg_scale).
export const AU_PAYG_SCALES = [
  { value: "SCALE_1", label: "Scale 1 — Threshold not claimed" },
  { value: "SCALE_2", label: "Scale 2 — Threshold claimed" },
  { value: "SCALE_3", label: "Scale 3 — Foreign resident" },
  { value: "SCALE_4", label: "Scale 4 — No TFN (flat rate, no coefficient bands)" },
  { value: "SCALE_5", label: "Scale 5 — Full Medicare exemption" },
  { value: "SCALE_6", label: "Scale 6 — Half Medicare exemption" },
];

// §8's own Schedule 8 declaration-state families — the TaxSlab.
// filing_status value each AU_STSL_COEFFICIENT band is tagged with (see
// engine/countries/australia.py's _resolve_au_stsl_family).
export const AU_STSL_FAMILIES = [
  { value: "STSL_CLAIMED_OR_FOREIGN", label: "Tax-free threshold claimed OR foreign resident" },
  { value: "STSL_NOT_CLAIMED", label: "Tax-free threshold not claimed" },
];

// ContributionRate component_key values Medicare/Super/Special Payments
// each display — see hardcoded_defaults.py's AU seed list for the exact
// same keys/labels these fall back to before a canonical row exists.
export const AU_MEDICARE_COMPONENT_KEYS = ["mls_threshold", "mls_rate"];
export const AU_SUPER_COMPONENT_KEYS = ["super", "super_max_contrib"];
export const AU_SPECIAL_PAYMENT_COMPONENT_KEYS = [
  "etp_life_cap", "etp_death_cap", "redundancy_base", "redundancy_per_yr",
  "untaxed_plan_cap", "transfer_balance_cap", "db_income_cap",
];

export function labelForAuFamily(options, value) {
  return options.find((o) => o.value === value)?.label || value || "—";
}
