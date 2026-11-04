// New Zealand (ZP-NZ-ENG-001) Super Admin content map. Keys match
// backend/app/modules/payroll/engine/countries/new_zealand_content.py; the
// choices match what nz_super_admin.py accepts, so a value the engine cannot
// read is never offered.

export const EDITABLE_PACK_STATUSES = ["Draft", "In Review", "QA", "Approved"];
export const isEditablePack = (pack) => Boolean(pack && EDITABLE_PACK_STATUSES.includes(pack.status));

const ROUNDING = ["NEAREST_CENT_HALF_UP", "HALF_EVEN_CENT", "DOWN_CENT", "UP_CENT", "NEAREST_DOLLAR_HALF_UP", "DOWN_DOLLAR"];

// Text rows: a fixed choice list, or a free-text hint (validated by the backend).
export const TEXT_ROWS = {
  nz_paye_rounding: { choices: ROUNDING },
  nz_acc_rounding: { choices: ROUNDING },
  nz_sl_rounding: { choices: ROUNDING },
  nz_ks_rounding: { choices: ROUNDING },
  nz_esct_rounding: { choices: ROUNDING },
  nz_cs_rounding: { choices: ROUNDING },
  nz_hol_pay_rounding: { choices: ROUNDING },
  nz_correction_policy: { choices: ["COMPENSATING_DELTA"] },
  nz_ks_rate_selection_basis: { choices: ["PAYDAY"] },
  nz_sl_secondary_basis: { choices: ["WHOLE_PAYMENT"] },
  nz_hol_owp_method: { choices: ["AGREEMENT_THEN_FALLBACK"] },
  nz_hol_rdp_method: { choices: ["AGREEMENT_DAILY"] },
  nz_hol_adp_use_rule: { choices: ["RDP_UNDETERMINABLE_OR_VARIES"] },
  nz_hol_final_pay_unvested_method: { choices: ["PCT_OF_GROSS_SINCE_ANNIVERSARY"] },
  nz_out_of_cycle_paye_method: { choices: ["EXTRA_PAY", "PERIOD_MAIN"] },
  nz_lump_sum_paye_method: { choices: ["EXTRA_PAY_FOUR_WEEK_ANNUALISE"] },
  nz_supported_pay_frequencies: { hint: "Comma-separated: WEEKLY, FORTNIGHTLY, FOUR_WEEKLY, MONTHLY" },
  nz_deduction_precedence: { hint: "Each of PAYE, ACC_LEVY, STUDENT_LOAN, KS_EMPLOYEE, CHILD_SUPPORT once; child support after PAYE and ACC_LEVY" },
  nz_ks_employee_rates: { hint: "Comma-separated percentages, e.g. 3.5,4,6,8,10" },
  nz_remit_december_second_half_due: { hint: "MM-DD" },
};
export const isTextRow = (row) => Boolean(row && TEXT_ROWS[row.componentKey]);

export const TREATMENTS = ["INCLUDED", "EXCLUDED", "LUMP_SUM_PATH", "REVIEW"];
export const REGIONS = ["NTL", "AUK", "WKO", "BOP", "GIS", "HKB", "TKI", "MWT", "WGN", "TAS", "NSN", "MBH", "WTC",
  "CAN", "OTA", "STL", "CIT"];

export const GROUPS = {
  paye: {
    title: "PAYE and ACC earner levy",
    description: "Tax-code routing and the ACC earner levy with its annual cap (one cap per employee, legal employer and tax year).",
    keys: ["nz_supported_pay_frequencies", "nz_paye_rounding", "nz_acc_earner_levy_rate", "nz_acc_max_liable_earnings",
      "nz_acc_rounding"],
    tables: [
      { ruleType: "NZ_PAYE_BAND", label: "PAYE bands 2026-27", gate: "G1" },
      { ruleType: "NZ_TAX_CODE", label: "Tax-code catalogue (supported / refused)", gate: "G1" },
    ],
  },
  kiwisaver: {
    title: "KiwiSaver and ESCT",
    description: "Rates are selected by the payday. Employer gross, ESCT and net contribution are kept separate.",
    keys: ["nz_ks_employee_rates", "nz_ks_temporary_reduction_rate", "nz_ks_default_rate", "nz_ks_employer_min_rate",
      "nz_ks_employer_min_age", "nz_ks_employer_max_age", "nz_ks_rate_selection_basis", "nz_ks_rounding",
      "nz_esct_rounding"],
    tables: [{ ruleType: "NZ_ESCT_BAND", label: "ESCT bands", gate: "G1" }],
  },
  deductions: {
    title: "Student loan, child support and deduction order",
    description: "Child support is taken from net pay after the tax deductions and never beyond the protected-net share.",
    keys: ["nz_sl_rate", "nz_sl_annual_threshold", "nz_sl_threshold_weekly", "nz_sl_threshold_fortnightly",
      "nz_sl_threshold_four_weekly", "nz_sl_threshold_monthly", "nz_sl_secondary_basis", "nz_sl_rounding",
      "nz_cs_protected_net_pct", "nz_cs_max_deduction_pct", "nz_cs_rounding", "nz_deduction_precedence"],
    tables: [],
  },
  minimumWage: {
    title: "Minimum wage",
    description: "The category comes from the employee's evidenced record, never from age. A shortfall stops approval; pay is never topped up silently.",
    keys: ["nz_min_wage_adult", "nz_min_wage_starting_out", "nz_min_wage_training"],
    tables: [],
  },
  holidays: {
    title: "Holidays Act 2003",
    description: "Entitlements in weeks / days (never an hours accrual) and leave pay (greater of OWP and AWE; RDP or ADP). Windows and methods are not stated by the specification and stay empty until G2.",
    keys: ["nz_hol_annual_weeks", "nz_hol_annual_qualifying_months", "nz_hol_sick_days", "nz_hol_sick_qualifying_months",
      "nz_hol_sick_carry_max", "nz_hol_bereavement_close_days", "nz_hol_bereavement_other_days",
      "nz_hol_family_violence_days", "nz_hol_payg_pct", "nz_hol_cashup_max_weeks", "nz_hol_ph_worked_multiplier",
      "nz_hol_pay_rounding", "nz_hol_awe_lookback_months", "nz_hol_awe_divisor_weeks", "nz_hol_owp_fallback_weeks",
      "nz_hol_adp_lookback_weeks", "nz_hol_owp_method", "nz_hol_rdp_method", "nz_hol_adp_use_rule",
      "nz_hol_final_pay_unvested_method"],
    tables: [],
  },
  filing: {
    title: "Payday filing, remittance and records",
    description: "Read by the filing phase (P8). File exports stay refused until gate G3 certifies a schema.",
    keys: ["nz_payday_filing_working_days", "nz_paper_filing_working_days", "nz_efiling_threshold",
      "nz_efiling_threshold_after_months", "nz_large_employer_threshold", "nz_remit_monthly_due_day",
      "nz_remit_first_half_due_day", "nz_remit_second_half_due_day", "nz_remit_december_second_half_due",
      "nz_record_retention_years"],
    tables: [],
  },
  policy: {
    title: "Corrections and non-standard payments",
    description: "Corrections are compensating results, never overwrites (NZ-006). Lump sums and out-of-cycle payments use the signed IRD method.",
    keys: ["nz_correction_policy", "nz_out_of_cycle_paye_method", "nz_lump_sum_paye_method"],
    tables: [],
  },
};

const text = (name, label, extra = {}) => ({ name, label, type: "text", ...extra });
const num = (name, label) => ({ name, label, type: "number" });

// Authority tables the specification does not reproduce: filled here from an
// archived authority source, then signed. Fields match nz_super_admin.add_table_row.
export const AUTHORITY_TABLES = [
  { ruleType: "NZ_PAYE_METHOD", label: "PAYE method for main codes", gate: "G1",
    fields: [text("filingStatus", "Pay frequency", { options: ["WEEKLY", "FORTNIGHTLY", "FOUR_WEEKLY", "MONTHLY"] }),
      num("flatAmount", "Annualisation factor"), text("taxFormula", "Method", { options: ["ANNUALISE_BANDS"] })] },
  { ruleType: "NZ_SECONDARY_RATE", label: "Secondary-code rates", gate: "G1",
    fields: [text("filingStatus", "Code", { options: ["SB", "S", "SH", "ST", "SA"] }), num("ratePct", "Rate %")] },
  { ruleType: "NZ_ND_RATE", label: "No-notification (ND) rate", gate: "G1", fields: [num("ratePct", "Rate %")] },
  { ruleType: "NZ_IETC", label: "Independent earner tax credit", gate: "G1",
    fields: [num("minAmount", "From (annual)"), num("maxAmount", "To (annual, empty = open)"),
      num("flatAmount", "Credit"), num("ratePct", "Abatement %")] },
  { ruleType: "NZ_CS_VARIATION", label: "Child-support variation codes", gate: "G1",
    fields: [text("filingStatus", "Code"), text("taxFormula", "Reason code"), text("name", "Description")] },
  { ruleType: "NZ_LUMP_SUM", label: "Lump-sum / extra-pay method", gate: "G1",
    fields: [text("filingStatus", "Parameter", { options: ["ANNUALISATION_FACTOR", "SL_ON_EXTRA_PAY", "IETC_ON_EXTRA_PAY"] }),
      num("flatAmount", "Factor (ANNUALISATION_FACTOR)"), text("taxFormula", "Treatment (WHOLE / NONE)")] },
  { ruleType: "NZ_HOLIDAY_ADVANCE", label: "Holiday pay in advance — methods", gate: "G1",
    fields: [text("filingStatus", "Method", { options: ["STANDARD", "ALTERNATIVE"] })] },
  { ruleType: "NZ_IRD_EXAMPLE", label: "IRD official examples (golden fixtures)", gate: "G1",
    fields: [text("filingStatus", "Example id"), text("name", "Title"), text("taxFormula", "Expected values (JSON)")] },
  { ruleType: "NZ_PUBLIC_HOLIDAY", label: "Public holidays (national and regional)", gate: "G2",
    fields: [{ name: "date", label: "Date", type: "date" }, text("name", "Holiday"),
      text("region", "Region (empty = national)", { options: ["", ...REGIONS] })] },
  { ruleType: "NZ_ACC_CLASSIFICATION", label: "ACC employer classification units", gate: "G1", employerContent: true,
    fields: [text("filingStatus", "Classification unit"), num("ratePct", "Levy rate %"), text("name", "Description")] },
];

export const OBLIGATIONS = ["PAYE", "ACC", "KIWISAVER", "STUDENT_LOAN", "HOLIDAY_GROSS", "MIN_WAGE"];
export const COMPONENTS = ["SALARY", "OVERTIME", "ALLOWANCE", "BONUS", "LUMP_SUM", "HOLIDAY_PAY", "ACC_COMPENSATION",
  "REIMBURSEMENT", "OTHER_EARNINGS"];
