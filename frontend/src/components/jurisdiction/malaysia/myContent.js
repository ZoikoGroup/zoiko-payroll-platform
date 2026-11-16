// Malaysia statutory content console vocabulary (ZP-MY-ENG-001 Phase 8a).
// Keys mirror engine/countries/malaysia_content.py; text choices mirror the
// signing vocabularies in my_super_admin._vocabulary (a key with no
// vocabulary can only be signed NOT_SUPPORTED, which keeps the feature
// blocked). No statutory value lives here — values come from the pack.

export const NOT_SUPPORTED = "NOT_SUPPORTED";
export const PENDING = "PENDING_G1";
export const TREATMENTS = ["INCLUDED", "EXCLUDED", "REVIEW"];
export const TERRITORIES = [
  { code: "PENINSULAR_LABUAN", suffix: "PEN", label: "Peninsular + Labuan" },
  { code: "SABAH", suffix: "SBH", label: "Sabah" },
  { code: "SARAWAK", suffix: "SWK", label: "Sarawak" },
];

const ROUNDING = ["SEN_HALF_UP", "SEN_DOWN", "SEN_UP", "FIVE_SEN_UP", "RINGGIT_HALF_UP", "RINGGIT_DOWN", "RINGGIT_UP"];
const choices = (...values) => ({ choices: [...values, NOT_SUPPORTED] });

// National text rows with a signing vocabulary.
export const TEXT_ROWS = {
  my_rounding_pcb: choices(...ROUNDING),
  my_rounding_epf_direct: choices(...ROUNDING),
  my_rounding_socso: choices(...ROUNDING),
  my_rounding_eis: choices(...ROUNDING),
  my_rounding_hrd: choices(...ROUNDING),
  my_supported_pay_frequencies: { hint: "Comma-separated: MONTHLY" },
  my_supported_contract_types: { hint: "Comma-separated: CONTRACT_OF_SERVICE" },
  my_pcb_spec_version: { hint: "The HASiL specification's version label", allowNotSupported: true },
  my_ea_due: choices("END_FEBRUARY"),
  my_form_e_due: choices("END_MARCH"),
  my_epf_age_transition_rule: choices("AGE_AT_WAGE_MONTH_START", "FROM_MONTH_AFTER_BIRTHDAY"),
  my_eis_age_rule: choices("AGE_AT_WAGE_MONTH_START", "AGE_AT_WAGE_MONTH_END"),
  my_hrd_non_malaysian_rule: choices("LEVY_ON_ALL_COVERED_WAGES", "MALAYSIAN_EMPLOYEES_ONLY"),
  my_epf_direct_calc_rule: choices("NON_MALAYSIAN_PART_F_ONLY"),
  my_transfer_split_rule: choices("TERRITORY_AT_PERIOD_END"),
};

// Territorial text rows (per territory key suffix).
export const TERRITORY_TEXT_ROWS = {
  my_ot_rate_divisor_rule: choices("MONTHLY_BASE_DIV_DAYS_DIV_DAILY_HOURS"),
  my_annual_leave_tiers: { hint: "YEARS:DAYS pairs, e.g. 0:8,2:12 (from the signed ordinance)", allowNotSupported: true },
  my_sick_leave_tiers: { hint: "YEARS:DAYS pairs (from the signed ordinance)", allowNotSupported: true },
};

export function textRow(componentKey) {
  if (TEXT_ROWS[componentKey]) return TEXT_ROWS[componentKey];
  const base = String(componentKey || "").split("__")[0];
  if (TERRITORY_TEXT_ROWS[base]) return TERRITORY_TEXT_ROWS[base];
  return null;
}

// National parameter groups (one tab each).
export const GROUPS = {
  pcb: {
    title: "PCB / MTD (HASiL)",
    description: "PCB is blocked until the HASiL 2026 computerised specification is archived (Phase 4); annual brackets are never used instead.",
    keys: ["my_pcb_spec_version", "my_pcb_non_resident_rate", "my_pcb_remittance_day", "my_tp1_retention_years",
      "my_rounding_pcb"],
  },
  epf: {
    title: "EPF (KWSP)",
    description: "Contributions come from the Third Schedule rows (Tables tab); these rates are reference values and drive only the signed direct-calculation branch.",
    keys: ["my_epf_wage_band_threshold", "my_epf_schedule_upper_wage", "my_epf_rate_my_pr_low", "my_epf_rate_my_pr_high",
      "my_epf_rate_60_plus", "my_epf_rate_pr_hist_60_plus_low", "my_epf_rate_pr_hist_60_plus_high",
      "my_epf_rate_non_malaysian", "my_epf_direct_calc_rule", "my_epf_age_threshold", "my_epf_age_transition_rule",
      "my_rounding_epf_direct", "my_epf_due_rule"],
  },
  perkeso: {
    title: "PERKESO & EIS",
    description: "SOCSO (Act 4), EIS (Act 800) and the foreign-worker scheme are separate obligations with their own schedules; the wage ceiling applies only to their bases.",
    keys: ["my_socso_wage_ceiling", "my_socso_employee_rate_ref", "my_eis_rate_ref", "my_eis_min_age", "my_eis_max_age",
      "my_eis_age_rule", "my_fw_lindung_employee_rate", "my_fw_lindung_phase_rule", "my_rounding_socso",
      "my_rounding_eis", "my_socso_due_rule"],
  },
  hrd: {
    title: "HRD levy",
    description: "Employer cost from the registered category (never a live headcount); never deducted from pay.",
    keys: ["my_hrd_rate_compulsory", "my_hrd_rate_optional", "my_hrd_compulsory_min_employees",
      "my_hrd_optional_min_employees", "my_hrd_base_rule", "my_hrd_non_malaysian_rule", "my_rounding_hrd",
      "my_hrd_due_rule"],
  },
  wages: {
    title: "Minimum wage",
    description: "Tested on the basic wage before a run is approved; overtime and bonuses never make up a deficient basic wage.",
    keys: ["my_min_wage_monthly", "my_min_wage_daily_rule", "my_min_wage_hourly_rule"],
  },
  events: {
    title: "Employer events & annual forms",
    description: "Due dates of CP22 / CP22A / CP21 and the tax-clearance hold maximum come only from these signed rows.",
    keys: ["my_cp22_days_after_start", "my_cp22a_days_before_cessation", "my_cp22a_days_after_death",
      "my_cp21_days_before_departure", "my_clearance_hold_max_days", "my_ea_due", "my_form_e_due"],
  },
  policy: {
    title: "Scope & operations",
    description: "Release 1 scope (decisions D-6), transfers between territories and operational thresholds.",
    keys: ["my_supported_pay_frequencies", "my_supported_contract_types", "my_transfer_split_rule",
      "my_record_retention_years", "my_reconciliation_tolerance", "my_parallel_materiality_amount"],
  },
};

// Territorial labour rows (one matrix: base key x territory).
export const TERRITORY_KEYS = [
  ["my_weekly_hours_max", "Statutory weekly hours"],
  ["my_ot_exclusion_wage", "Overtime exclusion wage (non-manual)"],
  ["my_ot_multiplier_workday", "Overtime multiplier — working day"],
  ["my_ot_multiplier_rest_day", "Overtime multiplier — rest day"],
  ["my_ot_multiplier_public_holiday", "Overtime multiplier — public holiday"],
  ["my_ot_rate_divisor_rule", "Ordinary-rate rule"],
  ["my_ot_rate_days_divisor", "Ordinary-rate days divisor"],
  ["my_annual_leave_tiers", "Annual leave tiers"],
  ["my_sick_leave_tiers", "Sick leave tiers"],
  ["my_hospitalisation_days", "Hospitalisation days"],
  ["my_maternity_days", "Maternity days"],
  ["my_paternity_days", "Paternity days"],
  ["my_leave_pay_rule", "Leave pay rule"],
];

export const SCHEDULES = [
  ["MY_EPF_SCHEDULE", "EPF Third Schedule"],
  ["MY_SOCSO_SCHEDULE", "PERKESO (Act 4)"],
  ["MY_EIS_SCHEDULE", "EIS (Act 800)"],
  ["MY_FW_SOCSO_SCHEDULE", "Foreign workers (LINDUNG 24 JAM)"],
];

export const isEditablePack = (pack) => Boolean(pack) && !["Active", "Superseded", "Retired"].includes(pack.status);
export const territoryKey = (base, territory) => `${base}__${territory.suffix}`;
export const cleanLabel = (row) => String(row?.label || "").replace("[PENDING G1]", "").trim();

export function valueOf(row) {
  if (!row) return null;
  if (row.textValue) return row.textValue;
  const ee = row.employeeRatePct, er = row.employerRatePct;
  if (ee != null && er != null) return `${ee}% / ${er}%`;
  if (ee != null) return `${ee}%`;
  if (er != null) return `${er}% (employer)`;
  if (row.flatAmount != null) return String(row.flatAmount);
  return null;
}

export const band = (row) => `${row.minAmount ?? 0} – ${row.maxAmount ?? "and above"}`;
