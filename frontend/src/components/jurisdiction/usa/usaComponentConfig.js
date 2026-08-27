// USA-only classification: maps a real ContributionRate row (or a chosen
// Add-flow "component type") to which fields are actually relevant, so the
// Tax Components tab never shows a wall of dashes for fields a component
// doesn't use. This file is independent of constants.js/RateFormModal/
// SlabFormModal — nothing shared depends on it, and it depends on nothing
// shared, per the USA-isolation requirement.
//
// Real US componentKeys today (backend/app/modules/payroll/service.py
// _CONTRIBUTION_RATES_BY_COUNTRY["US"] + backend/scripts/populate_canonical_
// tax_v1.py): social-security / medicare (employee+employer rate, no flat),
// medicare_additional (single rate — NOTE: its 0.9% surtax is actually
// stored in employer_rate_pct, not employee_rate_pct, even though it reads
// as an employee-only tax), medicare_addl_thresh / ss_wage_base /
// futa_wage_base / standard_deduction (flat amount only), futa (employer
// rate only), federal-income-tax (a placeholder row with NO numeric fields
// at all — the real data lives in TaxSlab, not here).

export const US_FILING_STATUSES = ["SINGLE", "MFJ", "MFS", "HOH"];

export const UI_TYPES = {
  PERCENTAGE: "PERCENTAGE",
  EMPLOYEE_EMPLOYER_PERCENTAGE: "EMPLOYEE_EMPLOYER_PERCENTAGE",
  EMPLOYER_ASSIGNED_RATE: "EMPLOYER_ASSIGNED_RATE",
  WAGE_BASE: "WAGE_BASE",
  THRESHOLD: "THRESHOLD",
  FIXED_AMOUNT: "FIXED_AMOUNT",
  DEDUCTION_AMOUNT: "DEDUCTION_AMOUNT",
  INCOME_TAX_POINTER: "INCOME_TAX_POINTER",
};

// Frontend-only "Add Component" type picker — never sent to the API, only
// used to decide which fields the Add form shows.
export const ADD_COMPONENT_TYPES = [
  { uiType: UI_TYPES.PERCENTAGE, label: "Percentage Rate" },
  { uiType: UI_TYPES.EMPLOYEE_EMPLOYER_PERCENTAGE, label: "Employee + Employer Contribution" },
  { uiType: UI_TYPES.WAGE_BASE, label: "Wage Base" },
  { uiType: UI_TYPES.THRESHOLD, label: "Threshold" },
  { uiType: UI_TYPES.FIXED_AMOUNT, label: "Fixed Amount" },
  { uiType: UI_TYPES.DEDUCTION_AMOUNT, label: "Deduction Amount" },
];

// Static map for every real US componentKey seen in production data today.
// Anything not listed here falls through to the populated-field heuristic
// in classifyContributionRate — never breaks for a future/unmapped key.
// `associatedKey` marks a componentKey whose row should be merged INTO its
// parent's card (shown as one inline line there) rather than rendered as
// its own separate top-level card — Social Security's wage base and
// Additional Medicare's threshold are conceptually part of that same
// component, not a distinct one, so showing them twice (once inline, once
// as their own card) was pure duplication. The associated row is still a
// fully separate API row/CRUD target — only its TOP-LEVEL card is hidden,
// and only when its parent's card actually exists (see
// USTaxComponentsTab.jsx's mergedAwayKeys) so an associated row is never
// silently hidden if its parent is missing.
const STATIC_MAP = {
  "social-security": { uiType: UI_TYPES.EMPLOYEE_EMPLOYER_PERCENTAGE, associatedKey: "ss_wage_base" },
  medicare: { uiType: UI_TYPES.EMPLOYEE_EMPLOYER_PERCENTAGE },
  medicare_additional: { uiType: UI_TYPES.PERCENTAGE, rateLabel: "Employee Rate %", associatedKey: "medicare_addl_thresh" },
  medicare_addl_thresh: { uiType: UI_TYPES.THRESHOLD },
  futa: { uiType: UI_TYPES.EMPLOYER_ASSIGNED_RATE, associatedKey: "futa_wage_base" },
  ss_wage_base: { uiType: UI_TYPES.WAGE_BASE },
  futa_wage_base: { uiType: UI_TYPES.WAGE_BASE },
  standard_deduction: { uiType: UI_TYPES.DEDUCTION_AMOUNT },
  "federal-income-tax": { uiType: UI_TYPES.INCOME_TAX_POINTER },
};

// Business-language catalog for the "+ Add Component" picker — the admin
// selects a payroll component by name (Social Security, FUTA, ...), never
// a technical UI type. `uiType` here is looked up once at picker-build
// time from STATIC_MAP so the two never drift apart. `parentKey` groups an
// associated row (wage base / threshold) under its parent for display —
// it's still independently selectable/editable, just shown indented.
// `navigatesTo` marks the one entry (Federal/State Income Tax) that isn't
// a fillable component at all — selecting it switches tabs instead.
export const PAYROLL_COMPONENT_CATEGORIES = {
  payrollTaxes: "Payroll Taxes",
  incomeTax: "Income Tax",
};

export const PAYROLL_COMPONENT_CATALOG = [
  { componentKey: "social-security", displayName: "Social Security", category: "payrollTaxes", description: "Employee & employer OASDI contribution." },
  { componentKey: "ss_wage_base", displayName: "Social Security Wage Base", category: "payrollTaxes", description: "Annual wage cap Social Security applies up to.", parentKey: "social-security" },
  { componentKey: "medicare", displayName: "Medicare", category: "payrollTaxes", description: "Employee & employer Medicare contribution." },
  { componentKey: "medicare_additional", displayName: "Additional Medicare", category: "payrollTaxes", description: "Employee-only surtax above the threshold." },
  { componentKey: "medicare_addl_thresh", displayName: "Additional Medicare Threshold", category: "payrollTaxes", description: "Wage level the Additional Medicare surtax applies above.", parentKey: "medicare_additional" },
  { componentKey: "futa", displayName: "FUTA", category: "payrollTaxes", description: "Federal unemployment tax — employer only." },
  { componentKey: "futa_wage_base", displayName: "FUTA Wage Base", category: "payrollTaxes", description: "Annual wage cap FUTA applies up to.", parentKey: "futa" },
  { componentKey: "federal-income-tax", displayName: "Income Tax", category: "incomeTax", description: "Progressive brackets — configured in the Income Tax Brackets tab.", navigatesTo: "incomeTax" },
  { componentKey: "standard_deduction", displayName: "Standard Deduction", category: "incomeTax", description: "Filing-status-based standard deduction amount." },
];

function isSet(v) {
  return v !== null && v !== undefined && v !== "";
}

// Default field labels/behavior per UI type — used both by the display
// card and the form, so they never drift apart.
export function describeUiType(uiType, overrides = {}) {
  switch (uiType) {
    case UI_TYPES.EMPLOYEE_EMPLOYER_PERCENTAGE:
      return { employeeRate: true, employerRate: true };
    case UI_TYPES.PERCENTAGE:
      return { singleRate: true, rateLabel: overrides.rateLabel || "Employee Rate %" };
    case UI_TYPES.EMPLOYER_ASSIGNED_RATE:
      return { singleRate: true, rateLabel: overrides.rateLabel || "Employer Rate %" };
    case UI_TYPES.WAGE_BASE:
      return { flatAmount: true, flatAmountLabel: "Annual Wage Base" };
    case UI_TYPES.THRESHOLD:
      return { flatAmount: true, flatAmountLabel: "Threshold Amount" };
    case UI_TYPES.DEDUCTION_AMOUNT:
      return { flatAmount: true, flatAmountLabel: "Deduction Amount", filingStatus: true };
    case UI_TYPES.FIXED_AMOUNT:
      return { flatAmount: true, flatAmountLabel: "Fixed Amount" };
    case UI_TYPES.INCOME_TAX_POINTER:
    default:
      return { pointer: true };
  }
}

// Given a real fetched ContributionRate row, determine its UI type, which
// field the single-rate types actually read/write (resolved per-row, since
// medicare_additional's real data lives in employerRatePct despite reading
// as "Employee Rate %"), and the resolved field labels/flags to render.
export function classifyContributionRate(rate) {
  const staticEntry = STATIC_MAP[rate?.componentKey];
  const hasEmployee = isSet(rate?.employeeRatePct);
  const hasEmployer = isSet(rate?.employerRatePct);
  const hasFlat = isSet(rate?.flatAmount);

  let uiType, rateField, overrides = {};
  if (staticEntry) {
    uiType = staticEntry.uiType;
    overrides = staticEntry;
  } else {
    // Fallback heuristic for any future/unmapped componentKey — never
    // hides a component just because it isn't in the static map above.
    const haystack = `${rate?.componentKey || ""} ${rate?.label || ""}`.toLowerCase();
    if (hasEmployee && hasEmployer) uiType = UI_TYPES.EMPLOYEE_EMPLOYER_PERCENTAGE;
    else if (hasEmployee || hasEmployer) uiType = UI_TYPES.PERCENTAGE;
    else if (hasFlat && /wage.?base/.test(haystack)) uiType = UI_TYPES.WAGE_BASE;
    else if (hasFlat && /thresh/.test(haystack)) uiType = UI_TYPES.THRESHOLD;
    else if (hasFlat && /deduct/.test(haystack)) uiType = UI_TYPES.DEDUCTION_AMOUNT;
    else if (hasFlat) uiType = UI_TYPES.FIXED_AMOUNT;
    else uiType = UI_TYPES.INCOME_TAX_POINTER;
  }

  if (uiType === UI_TYPES.PERCENTAGE || uiType === UI_TYPES.EMPLOYER_ASSIGNED_RATE) {
    rateField = hasEmployee ? "employeeRatePct" : hasEmployer ? "employerRatePct" : "employeeRatePct";
  }

  return { uiType, rateField, associatedKey: staticEntry?.associatedKey, ...describeUiType(uiType, overrides) };
}
