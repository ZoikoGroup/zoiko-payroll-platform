// UK-only classification: maps a real ContributionRate row (or a chosen
// picker entry) to which fields are actually relevant, so the Tax
// Components tab never shows a wall of dashes for fields a component
// doesn't use. Follows the same structure as india/inComponentConfig.js
// and usa/usaComponentConfig.js — independent of both, nothing shared
// depends on it.
//
// Real UK componentKeys today (backend/app/modules/payroll/hardcoded_defaults.py
// _CONTRIBUTION_RATES_BY_COUNTRY["UK"]):
//   national-insurance (employee+employer rate), employer-pension (employer
//   rate + pension_basis text value), personal_allowance (flat), pa_taper
//   _threshold (flat), ni_primary_thresh (flat), ni_upper_threshold (flat),
//   ni_secondary_thresh (flat), ni_upper_rate (employee rate), k_code_cap
//   _pct (employee rate), pension_qe_lower/upper (flat), sl_plan1/2/4/5
//   _thresh + pg_loan_thresh (flat). Plus (2026-09-09 gap-closure Phase 2):
//   ssp_weekly_cap/ssp_awe_pct, fam_pay_awe_pct/fam_pay_flat_rate/
//   fam_pay_recov_thresh/_small/_std, appr_levy_rate/_allowance,
//   empl_allowance_cap, c1a_benefits_rate, c1a_term_rate/_thresh,
//   c1a_testim_rate/_thresh, c1b_psa_rate — read by uk.py's
//   calculate_ssp/calculate_statutory_family_pay/
//   calculate_family_pay_employer_recovery/
//   calculate_apprenticeship_levy_period_amount/
//   calculate_employment_allowance_net_liability/
//   calculate_class_1a_1b_charge, none of which have a hardcoded
//   fallback — they fail closed until a real row exists for these keys.
//
// NI Category Bands are TaxSlab rows (ruleType="NI_BAND"), not
// ContributionRate rows — managed by the NI Bands section of the
// unified Tax Components tab. PAYE Tax Bands are TaxSlab rows
// (ruleType="MARGINAL_RATE") — managed by the PAYE Income Tax tab.

export const UI_TYPES = {
  EMPLOYEE_EMPLOYER_PERCENTAGE: "EMPLOYEE_EMPLOYER_PERCENTAGE",
  EMPLOYER_ONLY_RATE: "EMPLOYER_ONLY_RATE",
  EMPLOYEE_ONLY_RATE: "EMPLOYEE_ONLY_RATE",
  THRESHOLD: "THRESHOLD",
  INCOME_TAX_POINTER: "INCOME_TAX_POINTER",
};

// Frontend-only "Add Component" type picker for the "Other / Custom
// Component" escape hatch — never sent to the API, only used to decide
// which fields the Add form shows for a component outside the catalog.
export const ADD_COMPONENT_TYPES = [
  { uiType: UI_TYPES.EMPLOYEE_EMPLOYER_PERCENTAGE, label: "Employee + Employer Contribution" },
  { uiType: UI_TYPES.EMPLOYER_ONLY_RATE, label: "Employer-Only Rate" },
  { uiType: UI_TYPES.EMPLOYEE_ONLY_RATE, label: "Employee-Only Rate" },
  { uiType: UI_TYPES.THRESHOLD, label: "Threshold / Flat Amount" },
];

// Static map for every real UK componentKey. `associatedKey` marks a
// componentKey merged INTO its parent's card rather than as its own
// top-level card (pension_basis shown inline under employer-pension).
const STATIC_MAP = {
  "national-insurance": { uiType: UI_TYPES.EMPLOYEE_EMPLOYER_PERCENTAGE },
  "employer-pension": { uiType: UI_TYPES.EMPLOYER_ONLY_RATE, associatedKey: "pension_basis" },
  pension_basis: { uiType: UI_TYPES.THRESHOLD },
  personal_allowance: { uiType: UI_TYPES.THRESHOLD },
  pa_taper_threshold: { uiType: UI_TYPES.THRESHOLD },
  ni_primary_thresh: { uiType: UI_TYPES.THRESHOLD },
  ni_upper_threshold: { uiType: UI_TYPES.THRESHOLD },
  ni_secondary_thresh: { uiType: UI_TYPES.THRESHOLD },
  ni_upper_rate: { uiType: UI_TYPES.EMPLOYEE_ONLY_RATE },
  k_code_cap_pct: { uiType: UI_TYPES.EMPLOYEE_ONLY_RATE },
  pension_qe_lower: { uiType: UI_TYPES.THRESHOLD },
  pension_qe_upper: { uiType: UI_TYPES.THRESHOLD },
  sl_plan1_thresh: { uiType: UI_TYPES.THRESHOLD },
  sl_plan2_thresh: { uiType: UI_TYPES.THRESHOLD },
  sl_plan4_thresh: { uiType: UI_TYPES.THRESHOLD },
  sl_plan5_thresh: { uiType: UI_TYPES.THRESHOLD },
  pg_loan_thresh: { uiType: UI_TYPES.THRESHOLD },
  // 2026-09-09 gap-closure Phase 2 — Statutory Sick Pay / Statutory
  // Family Pay + recovery. Without an explicit entry here, a newly-added
  // row would still display (classifyUKContributionRate's populated-
  // field heuristic never hides an unmapped key) but as the generic
  // EMPLOYEE_EMPLOYER_PERCENTAGE shape whenever the employer-side fields
  // above are populated alone — wrong for these genuinely single-sided
  // figures.
  ssp_weekly_cap: { uiType: UI_TYPES.THRESHOLD },
  ssp_awe_pct: { uiType: UI_TYPES.EMPLOYEE_ONLY_RATE },
  fam_pay_awe_pct: { uiType: UI_TYPES.EMPLOYEE_ONLY_RATE },
  fam_pay_flat_rate: { uiType: UI_TYPES.THRESHOLD },
  fam_pay_recov_thresh: { uiType: UI_TYPES.THRESHOLD },
  fam_pay_recov_small: { uiType: UI_TYPES.EMPLOYER_ONLY_RATE },
  fam_pay_recov_std: { uiType: UI_TYPES.EMPLOYER_ONLY_RATE },
  // Apprenticeship Levy / Employment Allowance / Class 1A / Class 1B.
  appr_levy_rate: { uiType: UI_TYPES.EMPLOYER_ONLY_RATE },
  appr_levy_allowance: { uiType: UI_TYPES.THRESHOLD },
  empl_allowance_cap: { uiType: UI_TYPES.THRESHOLD },
  c1a_benefits_rate: { uiType: UI_TYPES.EMPLOYER_ONLY_RATE },
  c1a_term_rate: { uiType: UI_TYPES.EMPLOYER_ONLY_RATE },
  c1a_term_thresh: { uiType: UI_TYPES.THRESHOLD },
  c1a_testim_rate: { uiType: UI_TYPES.EMPLOYER_ONLY_RATE },
  c1a_testim_thresh: { uiType: UI_TYPES.THRESHOLD },
  c1b_psa_rate: { uiType: UI_TYPES.EMPLOYER_ONLY_RATE },
};

export const PAYROLL_COMPONENT_CATEGORIES = {
  nationalInsurance: "National Insurance",
  workplacePension: "Workplace Pension",
  studentLoans: "Student Loans",
  statutoryThresholds: "HMRC Statutory Thresholds",
  // 2026-09-09 gap-closure Phase 2 — the doc's §11/§12 (Statutory Sick
  // Pay, SMP/SPP/SAP/ShPP/SPBP/SNCP + employer recovery) and §14/§9.3
  // (Apprenticeship Levy, Employment Allowance, Class 1A/1B) have been
  // computable by the backend since the 2026-09-08 commit but had no
  // admin UI category to live under at all.
  statutoryPay: "Statutory Pay",
  employerCharges: "Employer Charges",
};

// Business-language catalog for the "+ Add Component" picker — the admin
// selects a payroll component by name, never a technical UI type.
// `navigatesTo` marks entries that point at another tab instead of
// opening a fillable form here.
export const PAYROLL_COMPONENT_CATALOG = [
  { componentKey: "national-insurance", displayName: "National Insurance (NI)", category: "nationalInsurance", description: "Employee & employer National Insurance contribution rates." },
  { componentKey: "employer-pension", displayName: "Workplace Pension", category: "workplacePension", description: "Employer (and optional employee) pension contribution rate." },
  { componentKey: "pension_basis", displayName: "Pension Calculation Basis", category: "workplacePension", description: "Determines which earnings are used for pension calculation (QE, Basic Pay, or Pensionable Earnings).", parentKey: "employer-pension" },
  { componentKey: "pension_qe_lower", displayName: "Pension — Qualifying Earnings Lower Limit", category: "workplacePension", description: "Lower bound of the qualifying earnings band for workplace pension." },
  { componentKey: "pension_qe_upper", displayName: "Pension — Qualifying Earnings Upper Limit", category: "workplacePension", description: "Upper bound of the qualifying earnings band for workplace pension." },
  { componentKey: "sl_plan1_thresh", displayName: "Student Loan — Plan 1 Threshold", category: "studentLoans", description: "Annual earnings threshold above which Plan 1 deductions begin (9% rate)." },
  { componentKey: "sl_plan2_thresh", displayName: "Student Loan — Plan 2 Threshold", category: "studentLoans", description: "Annual earnings threshold above which Plan 2 deductions begin (9% rate)." },
  { componentKey: "sl_plan4_thresh", displayName: "Student Loan — Plan 4 Threshold", category: "studentLoans", description: "Annual earnings threshold above which Plan 4 deductions begin (9% rate)." },
  { componentKey: "sl_plan5_thresh", displayName: "Student Loan — Plan 5 Threshold", category: "studentLoans", description: "Annual earnings threshold above which Plan 5 deductions begin (9% rate)." },
  { componentKey: "pg_loan_thresh", displayName: "Postgraduate Loan Threshold", category: "studentLoans", description: "Annual earnings threshold above which Postgraduate Loan deductions begin (6% rate)." },
  { componentKey: "personal_allowance", displayName: "Personal Allowance", category: "statutoryThresholds", description: "Tax-free income allowance before PAYE tax is applied." },
  { componentKey: "pa_taper_threshold", displayName: "Personal Allowance Taper Threshold", category: "statutoryThresholds", description: "Income level above which the Personal Allowance begins to taper away." },
  { componentKey: "ni_primary_thresh", displayName: "NI Primary Threshold", category: "statutoryThresholds", description: "Lower earnings limit below which no employee NI is due." },
  { componentKey: "ni_upper_threshold", displayName: "NI Upper Earnings Limit", category: "statutoryThresholds", description: "Earnings level above which the NI Upper Rate (2%) applies." },
  { componentKey: "ni_secondary_thresh", displayName: "NI Secondary Threshold", category: "statutoryThresholds", description: "Earnings level above which employer NI contributions begin." },
  { componentKey: "ni_upper_rate", displayName: "NI Upper Rate (Employee)", category: "statutoryThresholds", description: "Employee NI rate applied to earnings above the Upper Earnings Limit." },
  { componentKey: "k_code_cap_pct", displayName: "K-Code Overriding Limit", category: "statutoryThresholds", description: "Maximum PAYE deduction as a percentage of gross pay for K-coded employees." },
  { componentKey: "__paye_income_tax", displayName: "PAYE Income Tax Bands", category: "statutoryThresholds", description: "Progressive income tax brackets — configured in the PAYE Income Tax tab.", navigatesTo: "paye", synthetic: true },
  { componentKey: "__ni_bands", displayName: "NI Category Bands", category: "nationalInsurance", description: "Per-category NI band rates (Employee % / Employer %) — managed below.", navigatesTo: "ni-bands", synthetic: true },
  // 2026-09-09 gap-closure Phase 2 — Statutory Pay (§11/§12).
  { componentKey: "ssp_weekly_cap", displayName: "Statutory Sick Pay — Weekly Cap", category: "statutoryPay", description: "Maximum weekly SSP amount — SSP pays the lower of this cap or the AWE percentage below." },
  { componentKey: "ssp_awe_pct", displayName: "Statutory Sick Pay — AWE Percentage", category: "statutoryPay", description: "Percentage of Average Weekly Earnings used to calculate SSP (80%)." },
  { componentKey: "fam_pay_awe_pct", displayName: "Statutory Family Pay — AWE Percentage", category: "statutoryPay", description: "Percentage of AWE used for SMP/SPP/SAP/ShPP/SPBP/SNCP (90%), including SMP/SAP's uncapped first 6 weeks." },
  { componentKey: "fam_pay_flat_rate", displayName: "Statutory Family Pay — Standard Weekly Rate", category: "statutoryPay", description: "Flat weekly rate cap for statutory family pay after any uncapped first weeks (£194.32)." },
  { componentKey: "fam_pay_recov_thresh", displayName: "Family Pay Recovery — Small Employer Threshold", category: "statutoryPay", description: "Prior-year total Class 1 NIC threshold (£45,000) that decides which recovery rate an employer gets." },
  { componentKey: "fam_pay_recov_small", displayName: "Family Pay Recovery Rate — Small Employer", category: "statutoryPay", description: "Employer recovery rate when prior-year Class 1 NIC was at/below the threshold (109%)." },
  { componentKey: "fam_pay_recov_std", displayName: "Family Pay Recovery Rate — Standard", category: "statutoryPay", description: "Employer recovery rate when prior-year Class 1 NIC was above the threshold (92%). SSP is never eligible for recovery." },
  // 2026-09-09 gap-closure Phase 2 — Employer Charges (§9.3/§14).
  { componentKey: "appr_levy_rate", displayName: "Apprenticeship Levy Rate", category: "employerCharges", description: "Employer levy rate on cumulative annual pay bill (0.5%)." },
  { componentKey: "appr_levy_allowance", displayName: "Apprenticeship Levy Annual Allowance", category: "employerCharges", description: "Annual allowance offsetting the levy before any net charge applies (£15,000, shared across connected employers)." },
  { componentKey: "empl_allowance_cap", displayName: "Employment Allowance Cap", category: "employerCharges", description: "Maximum reduction to eligible employer secondary Class 1 NIC liability per tax year (£10,500) — only applies once claimed." },
  { componentKey: "c1a_benefits_rate", displayName: "Class 1A — Benefits & Expenses Rate", category: "employerCharges", description: "Employer NIC rate on payrolled/reported benefits and expenses (15%)." },
  { componentKey: "c1a_term_rate", displayName: "Class 1A — Termination Awards Rate", category: "employerCharges", description: "Employer NIC rate on the portion of a termination award above its threshold (15%)." },
  { componentKey: "c1a_term_thresh", displayName: "Class 1A — Termination Awards Threshold", category: "employerCharges", description: "Termination award amount (£30,000) below which no Class 1A charge applies." },
  { componentKey: "c1a_testim_rate", displayName: "Class 1A — Sporting Testimonial Rate", category: "employerCharges", description: "Employer NIC rate on the portion of a qualifying sporting testimonial payment above its threshold (15%)." },
  { componentKey: "c1a_testim_thresh", displayName: "Class 1A — Sporting Testimonial Threshold", category: "employerCharges", description: "Sporting testimonial payment amount (£100,000) below which no Class 1A charge applies." },
  { componentKey: "c1b_psa_rate", displayName: "Class 1B — PAYE Settlement Agreement Rate", category: "employerCharges", description: "Employer NIC rate on PAYE Settlement Agreement items (15%)." },
];

function isSet(v) {
  return v !== null && v !== undefined && v !== "";
}

// Default field labels/behavior per UI type — used both by the display
// card and the form, so they never drift apart.
export function describeUiType(uiType) {
  switch (uiType) {
    case UI_TYPES.EMPLOYEE_EMPLOYER_PERCENTAGE:
      return { employeeRate: true, employerRate: true };
    case UI_TYPES.EMPLOYER_ONLY_RATE:
      return { employerRate: true, employeeRate: false };
    case UI_TYPES.EMPLOYEE_ONLY_RATE:
      return { employeeRate: true, employerRate: false };
    case UI_TYPES.THRESHOLD:
      return { flatAmount: true, flatAmountLabel: "Threshold Amount" };
    case UI_TYPES.INCOME_TAX_POINTER:
    default:
      return { pointer: true };
  }
}

// Given a real fetched ContributionRate row, determine its UI type and the
// resolved field labels/flags to render. Falls back to a populated-field
// heuristic for any future/unmapped componentKey — never hides a component
// just because it isn't in the static map above.
export function classifyUKContributionRate(rate) {
  const staticEntry = STATIC_MAP[rate?.componentKey];
  const hasEmployee = isSet(rate?.employeeRatePct);
  const hasEmployer = isSet(rate?.employerRatePct);
  const hasFlat = isSet(rate?.flatAmount);

  let uiType;
  if (staticEntry) {
    uiType = staticEntry.uiType;
  } else if (hasEmployee || hasEmployer) {
    uiType = UI_TYPES.EMPLOYEE_EMPLOYER_PERCENTAGE;
  } else if (hasFlat) {
    uiType = UI_TYPES.THRESHOLD;
  } else {
    uiType = UI_TYPES.INCOME_TAX_POINTER;
  }

  return { uiType, associatedKey: staticEntry?.associatedKey, ...describeUiType(uiType) };
}
