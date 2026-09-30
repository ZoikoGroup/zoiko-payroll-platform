// Sweden Compliance UI config (ZP-SE-ENG-001) — plain component-key lists
// grouping the statutory rows each tab displays. Same role as
// ieComponentConfig.js for Ireland: key lists only, no values, no logic.
//
// The keys are exactly the SE_PARAMETER_KEYS entries that
// backend/app/modules/payroll/engine/countries/sweden.py reads out of
// rate_map; tests/test_sweden_statutory_catalog.py asserts this file and the
// backend catalog cover the same key set, so a key can never be invisible
// here yet still block every Sweden run.
//
// Percent-type rows are PERCENT numbers (31.42 = 31.42%), amount-type rows
// use the flat amount column.

// Employer contributions (arbetsgivaravgifter) — the seven statutory
// components whose sum is the standard rate (spec §3: "store component rates
// and total; do not hard-code only the total").
export const SE_EMPLOYER_COMPONENT_KEYS = [
  "se_er_age_pension",
  "se_er_survivor_pension",
  "se_er_health_insurance",
  "se_er_parental_insurance",
  "se_er_work_injury",
  "se_er_labour_market",
  "se_er_general_payroll_tax",
];

// Birth-year cohorts and the temporary youth reduction (spec §3/§6, SE-005).
// The youth rows carry their own payment-date window (1 Apr 2026 – 30 Sep
// 2027); outside it they are legitimately absent.
export const SE_COHORT_COMPONENT_KEYS = [
  "se_zero_cohort_max_birth_year",
  "se_older_cohort_max_birth_year",
  "se_youth_reduced",
  "se_youth_monthly_threshold",
];

// Preliminary-tax withholding strategies that are rows rather than tables
// (spec §5): SINK for non-residents and the 30% supplementary-income path.
// Tax tables 29–42 and one-time-payment tables are TaxSlab bands, edited in
// the Tax Tables tab.
export const SE_WITHHOLDING_COMPONENT_KEYS = ["se_sink", "se_supplementary_rate"];

// Special payroll tax on pension costs (SE-007) — applied to the employer
// pension-cost ledger, never to gross pay.
export const SE_SLP_COMPONENT_KEYS = ["se_slp"];

// Annual leave and sick-pay parameters (spec §7/§8), read by the leave and
// sickness workspaces rather than the payroll engine.
export const SE_LEAVE_SICK_COMPONENT_KEYS = ["se_vacation_percentage", "se_sick_qualifying_deduction_pct"];

export const SE_ALL_COMPONENT_KEYS = [
  ...SE_EMPLOYER_COMPONENT_KEYS,
  ...SE_COHORT_COMPONENT_KEYS,
  ...SE_WITHHOLDING_COMPONENT_KEYS,
  ...SE_SLP_COMPONENT_KEYS,
  ...SE_LEAVE_SICK_COMPONENT_KEYS,
];

// TaxSlab rule types for the two authority table families.
export const SE_TAX_TABLE_RULE = "SE_TAX_TABLE";
export const SE_ONE_TIME_PAYMENT_RULE = "SE_ONE_TIME_PAYMENT";
export const SE_TAX_TABLES = Array.from({ length: 14 }, (_, i) => String(29 + i));

// Collective-agreement vocabularies — deliberately no NATIONAL type (spec §9).
export const SE_CBA_TYPES = ["EMPLOYER_SPECIFIC", "SECTOR", "LOCAL_SUPPLEMENT"];
export const SE_CBA_MODULES = [
  "wage_scales", "overtime", "unsocial_hours", "sickness_supplements", "parental_pay",
  "vacation_enhancement", "occupational_pension", "insurance", "termination",
];
