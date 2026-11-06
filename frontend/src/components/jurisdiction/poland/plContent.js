// Poland (ZP-PL-ENG-001) Super Admin content map. Keys match
// backend/app/modules/payroll/engine/countries/poland_content.py; the choices
// match what pl_super_admin.py accepts, so a value the engine cannot read is
// never offered. No statutory VALUE lives here — only keys and vocabularies.

export const EDITABLE_PACK_STATUSES = ["Draft", "In Review", "QA", "Approved"];
export const isEditablePack = (pack) => Boolean(pack && EDITABLE_PACK_STATUSES.includes(pack.status));

export const NOT_SUPPORTED = "NOT_SUPPORTED";
const ROUNDING = ["GROSZ_HALF_UP", "GROSZ_DOWN", "FULL_PLN_HALF_UP", "FULL_PLN_DOWN"];
const OVERTIME_KINDS = ["DAILY", "WEEKLY", "NIGHT", "SUNDAY_HOLIDAY", "COMP_TIME_FAILED"];
export const INCAPACITY_CATEGORIES = ["ILLNESS", "ROUTE_ACCIDENT", "PREGNANCY", "DONOR", "WORK_ACCIDENT", "OTHER"];

// Text rows: a fixed choice list, or a free-text hint (validated by the backend).
// NOT_SUPPORTED records a G1 decision that the feature stays blocked.
const choices = (...values) => ({ choices: [...values, NOT_SUPPORTED] });
export const TEXT_ROWS = {
  pl_rounding_pit: choices(...ROUNDING),
  pl_rounding_zus: choices(...ROUNDING),
  pl_rounding_health: choices(...ROUNDING),
  pl_rounding_ppk: choices(...ROUNDING),
  pl_supported_pay_frequencies: choices("MONTHLY"),
  pl_supported_contract_types: choices("UMOWA_O_PRACE"),
  pl_pit_social_deduction_rule: choices("EMPLOYEE_SOCIAL_ONLY"),
  pl_health_base_rule: choices("GROSS_LESS_EMPLOYEE_SOCIAL"),
  pl_health_limitation_rule: choices("NONE"),
  pl_fp_fs_min_base_rule: choices("NONE", "BASE_AT_LEAST_MIN_WAGE"),
  pl_fund_cap_rule: choices("CAPPED_WITH_PENSION_BASE", "UNCAPPED"),
  pl_ppk_employer_pit_treatment: choices("TAXABLE_EMPLOYEE_INCOME", "NOT_TAXABLE"),
  pl_leave_part_time_rounding: choices("ROUND_UP_FULL_DAY", "EXACT"),
  pl_sick_age_rule: choices("AGE_AT_EPISODE_START", "FROM_YEAR_AFTER_REACHING_AGE"),
  pl_zus_due_day_classes: choices("5,15,20"),
  pl_pit11_authority_due: choices("END_JANUARY"),
  pl_pit11_employee_due: choices("END_FEBRUARY"),
  pl_pit4r_due: choices("END_JANUARY"),
  pl_pit8ar_due: choices("END_JANUARY"),
  // No signed vocabulary exists yet: only NOT_SUPPORTED can be signed.
  pl_night_supplement_basis: { choices: [NOT_SUPPORTED] },
  pl_leave_pay_reference_rule: { choices: [NOT_SUPPORTED] },
  pl_fund_exemption_rules: { choices: [NOT_SUPPORTED] },
  pl_pit_remittance_due_rule: { choices: [NOT_SUPPORTED] },
  pl_zus_contribution_year_start: { hint: "MM-DD (the accident-rate contribution year starts on this day)" },
  pl_overtime_premium_map: { hint: `Every kind once as KIND=50|100: ${OVERTIME_KINDS.join(", ")}`, allowNotSupported: true },
  pl_sick_full_rate_cases: { hint: `Comma-separated: ${INCAPACITY_CATEGORIES.join(", ")}`, allowNotSupported: true },
};

// Value kind of every scalar row (poland_content.POLAND_PARAMETER_KEYS), used
// to offer exactly the slot(s) the backend accepts.
export const PCT_ROWS = {
  employee: ["pl_zus_chorobowe", "pl_health", "pl_ppk_employee_basic", "pl_ppk_employee_reduced_min",
    "pl_ppk_reduced_income_pct_min_wage", "pl_ppk_employee_additional_max", "pl_overtime_premium_standard",
    "pl_overtime_premium_high", "pl_sick_rate_standard", "pl_sick_rate_full"],
  employer: ["pl_zus_wypadkowe_min", "pl_zus_wypadkowe_max", "pl_zus_wypadkowe_small_payer", "pl_fp_fs", "pl_fgsp",
    "pl_fep", "pl_ppk_employer_basic", "pl_ppk_employer_additional_max"],
  pair: ["pl_zus_emerytalne", "pl_zus_rentowe"],
};
export function valueKind(key) {
  if (TEXT_ROWS[key]) return "text";
  if (PCT_ROWS.pair.includes(key)) return "pair";
  if (PCT_ROWS.employee.includes(key)) return "employee";
  if (PCT_ROWS.employer.includes(key)) return "employer";
  return "amount";
}

export const GROUPS = {
  policy: {
    title: "Scope, policy & rounding",
    description: "Certified scope (D2: umowa o pracę, monthly) and the per-obligation rounding rules (PL-004). Every rule the specification does not give ships PENDING_G1 and blocks calculation until signed.",
    keys: ["pl_supported_pay_frequencies", "pl_supported_contract_types", "pl_rounding_pit", "pl_rounding_zus",
      "pl_rounding_health", "pl_rounding_ppk"],
  },
  pit: {
    title: "PIT scale, PIT-2 & deductible costs",
    description: "Cumulative withholding (spec §4). The published top-band base 10,800 already nets the 3,600 reducing amount; the engine applies the reduction monthly through PIT-2.",
    keys: ["pl_pit_tax_free_amount", "pl_pit_tax_reducing_annual", "pl_pit2_reduction_full", "pl_pit2_reduction_half",
      "pl_pit2_reduction_third", "pl_costs_standard_monthly", "pl_costs_standard_annual_cap",
      "pl_costs_standard_multi_annual_cap", "pl_costs_commuter_monthly", "pl_costs_commuter_annual_cap",
      "pl_costs_commuter_multi_annual_cap", "pl_pit0_annual_limit", "pl_pit_social_deduction_rule"],
    pitBands: true,
  },
  zus: {
    title: "ZUS social & health",
    description: "Separate employee / employer components; the 30x cap stops pension and disability only (PL-009). Health is employee-funded on its own base.",
    keys: ["pl_zus_emerytalne", "pl_zus_rentowe", "pl_zus_chorobowe", "pl_zus_wypadkowe_min", "pl_zus_wypadkowe_max",
      "pl_zus_wypadkowe_small_payer", "pl_zus_contribution_year_start", "pl_zus_annual_cap", "pl_health",
      "pl_health_base_rule", "pl_health_limitation_rule"],
  },
  funds: {
    title: "Employer funds",
    description: "FP/FS, FGŚP and FEP are independent liabilities (PL-011); FEP needs evidenced qualifying work (PL-012).",
    keys: ["pl_fp_fs", "pl_fp_fs_min_base_rule", "pl_fund_cap_rule", "pl_fgsp", "pl_fep", "pl_fund_exemption_rules"],
  },
  ppk: {
    title: "PPK",
    description: "Uncapped pension base (PL-014); the reduced employee rate needs a statement AND the monthly income test (PL-013).",
    keys: ["pl_ppk_employee_basic", "pl_ppk_employee_reduced_min", "pl_ppk_reduced_income_pct_min_wage",
      "pl_ppk_employee_additional_max", "pl_ppk_employer_basic", "pl_ppk_employer_additional_max",
      "pl_ppk_transfer_day", "pl_ppk_reenrolment_cycle_years", "pl_ppk_employer_pit_treatment"],
  },
  labour: {
    title: "Wages, overtime & leave",
    description: "Minimum wage on the minimum-wage base x FTE (PL-015); overtime only with its events (PL-016); 20 / 26 days annual leave.",
    keys: ["pl_min_wage_monthly", "pl_min_hourly_civil", "pl_pay_deadline_day", "pl_working_hours_daily",
      "pl_working_hours_weekly_avg", "pl_overtime_premium_standard", "pl_overtime_premium_high",
      "pl_overtime_premium_map", "pl_night_supplement_basis", "pl_leave_days_base", "pl_leave_days_senior",
      "pl_leave_service_years_senior", "pl_leave_part_time_rounding", "pl_leave_pay_reference_rule"],
  },
  sickness: {
    title: "Sickness",
    description: "Employer sick pay up to the yearly limit, then ZUS benefit (spec §9). Medical detail never reaches payroll (PL-017).",
    keys: ["pl_sick_employer_days", "pl_sick_employer_days_older", "pl_sick_older_age_threshold", "pl_sick_age_rule",
      "pl_sick_rate_standard", "pl_sick_rate_full", "pl_sick_full_rate_cases", "pl_benefit_reference_months"],
  },
  filing: {
    title: "Filing, settlement & operations",
    description: "Deadlines and evidence for ZUS / PIT reporting (spec §10). Form schemas are archived at gate G4.",
    keys: ["pl_zus_due_day_classes", "pl_pit_remittance_due_rule", "pl_pit11_authority_due", "pl_pit11_employee_due",
      "pl_pit4r_due", "pl_pit8ar_due", "pl_record_retention_years", "pl_reconciliation_tolerance",
      "pl_parallel_materiality_amount"],
  },
};

export const OBLIGATIONS = ["PIT", "EMERYTALNE", "RENTOWE", "CHOROBOWE", "WYPADKOWE", "ZDROWOTNE", "FP_FS", "FGSP",
  "FEP", "PPK", "MIN_WAGE"];
export const COMPONENTS = ["SALARY", "HOURLY_PAY", "OVERTIME_50", "OVERTIME_100", "NIGHT_SUPPLEMENT",
  "SENIORITY_ALLOWANCE", "BONUS", "ALLOWANCE", "BENEFIT_IN_KIND", "LEAVE_PAY", "SICK_PAY_EMPLOYER", "SICKNESS_BENEFIT"];
export const TREATMENTS = ["INCLUDED", "EXCLUDED", "REVIEW"];

const pln = (value) => `${Number(value).toLocaleString("pl-PL", { maximumFractionDigits: 2 })} zł`;
export function band(row) {
  if (!row || (row.minAmount == null && row.maxAmount == null)) return "—";
  return `${pln(row.minAmount ?? 0)} – ${row.maxAmount != null ? pln(row.maxAmount) : "and above"}`;
}
