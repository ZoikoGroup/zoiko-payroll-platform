// India-only classification: maps a real ContributionRate row (or a chosen
// picker entry) to which fields are actually relevant, so the Contribution
// Components tab never asks the admin to pick a technical type. Mirrors
// usa/usaComponentConfig.js's structure exactly; independent of it — no
// shared file changed, no other country affected.
//
// Real India componentKeys today (backend/app/modules/payroll/service.py
// _CONTRIBUTION_RATES_BY_COUNTRY["IN"]): pf / esi (employee+employer rate),
// esi_wage_ceiling (flat, child of esi), pt (flat, country-level fallback —
// state PT brackets are a separate pack via the existing PT Slabs tab),
// tds (no numeric fields — real data lives in TaxSlab rows on the Tax Slabs
// tab). eps_rate/edli_rate/nps_employer_pct (employer-only rate,
// ZP-TAX-IN-2026-27-001 §9.1/§3.2 — no hardcoded fallback, resolve to 0
// until configured here); eps_rate/edli_rate have their own
// eps_wage_ceiling/edli_wage_ceiling child rows (same shape as esi's) —
// nps_employer_pct has no ceiling child, the document gives none.
// standard_deduction/rebate_87a_*/cess_pct/surcharge_*/gratuity/
// leave-encashment/80c are intentionally NOT in this catalog as fillable
// entries — they're already fully owned by INCompliancePage.jsx's Tax
// Parameters tab; the one "Income Tax Parameters" entry below just
// navigates there instead of duplicating those fields here.

// Every India numeric input (currency/percent amounts, bracket bounds) is a
// plain unmasked <input>, while the read-side tables display the same
// numbers with Indian comma grouping (toLocaleString("en-IN")) — that
// trains an admin to type "1,00,00,000" right back in. Number("1,00,00,000")
// is NaN, and sending the raw comma string to the API fails backend
// decimal validation ("Input should be a valid decimal"). Strips everything
// but digits/decimal point/leading minus before a value is validated with
// Number(...) or sent in a save payload — used by every India form in this
// folder and in INCompliancePage.jsx.
export function sanitizeNumeric(raw) {
  if (typeof raw !== "string") return raw;
  return raw.replace(/[^0-9.-]/g, "");
}

export const UI_TYPES = {
  EMPLOYEE_EMPLOYER_PERCENTAGE: "EMPLOYEE_EMPLOYER_PERCENTAGE",
  WAGE_CEILING: "WAGE_CEILING",
  FIXED_AMOUNT: "FIXED_AMOUNT",
  INCOME_TAX_POINTER: "INCOME_TAX_POINTER",
};

// Frontend-only "Add Component" type picker for the "Other / Custom
// Component" escape hatch — never sent to the API, only used to decide
// which fields the Add form shows for a component outside the catalog.
export const ADD_COMPONENT_TYPES = [
  { uiType: UI_TYPES.EMPLOYEE_EMPLOYER_PERCENTAGE, label: "Employee + Employer Contribution" },
  { uiType: UI_TYPES.WAGE_CEILING, label: "Wage Ceiling / Threshold" },
  { uiType: UI_TYPES.FIXED_AMOUNT, label: "Fixed Amount" },
];

// Static map for every real India componentKey. `associatedKey` marks a
// componentKey merged INTO its parent's card (ESI Wage Ceiling shown
// inline under ESI) rather than as its own top-level card — same
// convention as USA's ss_wage_base/medicare_addl_thresh.
const STATIC_MAP = {
  pf: { uiType: UI_TYPES.EMPLOYEE_EMPLOYER_PERCENTAGE },
  esi: { uiType: UI_TYPES.EMPLOYEE_EMPLOYER_PERCENTAGE, associatedKey: "esi_wage_ceiling" },
  esi_wage_ceiling: { uiType: UI_TYPES.WAGE_CEILING },
  pt: { uiType: UI_TYPES.FIXED_AMOUNT },
  tds: { uiType: UI_TYPES.INCOME_TAX_POINTER },
  // Employer-only (no employee share) — the shared EMPLOYEE_EMPLOYER_PERCENTAGE
  // form already tolerates a blank employee-rate side, same as US's DC
  // Paid Leave precedent.
  eps_rate: { uiType: UI_TYPES.EMPLOYEE_EMPLOYER_PERCENTAGE, associatedKey: "eps_wage_ceiling" },
  eps_wage_ceiling: { uiType: UI_TYPES.WAGE_CEILING },
  edli_rate: { uiType: UI_TYPES.EMPLOYEE_EMPLOYER_PERCENTAGE, associatedKey: "edli_wage_ceiling" },
  edli_wage_ceiling: { uiType: UI_TYPES.WAGE_CEILING },
  // Employer-only, no wage ceiling — ZP-TAX-IN-2026-27-001 §3.2 gives no
  // ceiling figure for this (unlike EPS/EDLI's INR 15,000), only a
  // percentage. Same blank-employee-share tolerance as eps_rate/edli_rate.
  nps_employer_pct: { uiType: UI_TYPES.EMPLOYEE_EMPLOYER_PERCENTAGE },
};

export const PAYROLL_COMPONENT_CATEGORIES = {
  contributions: "Employee & Employer Contributions",
  incomeTax: "Income Tax & Deductions",
};

// Business-language catalog for the "+ Add Component" picker — the admin
// selects a payroll component by name, never a technical UI type.
// `navigatesTo` marks entries that aren't a fillable component at all:
// TDS points at the Tax Slabs tab (the real bracket data); the synthetic
// "parameters" entry points at the existing Tax Parameters tab instead of
// duplicating Standard Deduction/87A/Surcharge/Retirement fields here.
export const PAYROLL_COMPONENT_CATALOG = [
  { componentKey: "pf", displayName: "Employee Provident Fund (EPF)", category: "contributions", description: "Employee & employer contribution, as a % of Basic." },
  { componentKey: "esi", displayName: "Employee State Insurance (ESI)", category: "contributions", description: "Employee & employer contribution, as a % of Gross (subject to the wage ceiling)." },
  { componentKey: "esi_wage_ceiling", displayName: "ESI Wage Ceiling", category: "contributions", description: "Monthly gross salary limit above which ESI no longer applies.", parentKey: "esi" },
  { componentKey: "eps_rate", displayName: "Employee Pension Scheme (EPS) Diversion", category: "contributions", description: "Employer-only — % of PF wages diverted from the employer's 12% PF share into EPS (subject to its own wage ceiling)." },
  { componentKey: "eps_wage_ceiling", displayName: "EPS Wage Ceiling", category: "contributions", description: "Monthly pensionable-wage limit for EPS diversion.", parentKey: "eps_rate" },
  { componentKey: "edli_rate", displayName: "Employee Deposit-Linked Insurance (EDLI)", category: "contributions", description: "Employer-only — a separate statutory liability additional to PF, as a % of wages (subject to its own wage ceiling)." },
  { componentKey: "edli_wage_ceiling", displayName: "EDLI Wage Ceiling", category: "contributions", description: "Monthly wage limit for EDLI.", parentKey: "edli_rate" },
  { componentKey: "nps_employer_pct", displayName: "Employer NPS Contribution", category: "contributions", description: "Employer-only — % of Basic. Also reduces taxable salary under the New Regime only (not Old)." },
  { componentKey: "pt", displayName: "Professional Tax (PT)", category: "incomeTax", description: "Country-level flat fallback amount. State-specific brackets are configured separately, per state." },
  { componentKey: "tds", displayName: "TDS / Income Tax", category: "incomeTax", description: "Progressive brackets — configured in the Tax Slabs tab.", navigatesTo: "slabs" },
  { componentKey: "__parameters", displayName: "Income Tax Parameters", category: "incomeTax", description: "Standard Deduction, Section 87A Rebate, Surcharge, and Retirement & Exemption Limits — configured in the Tax Parameters tab.", navigatesTo: "parameters", synthetic: true },
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
    case UI_TYPES.WAGE_CEILING:
      return { flatAmount: true, flatAmountLabel: "Applicable Wage Ceiling (Monthly)" };
    case UI_TYPES.FIXED_AMOUNT:
      return { flatAmount: true, flatAmountLabel: "Professional Tax Amount (Monthly)" };
    case UI_TYPES.INCOME_TAX_POINTER:
    default:
      return { pointer: true };
  }
}

// Given a real fetched ContributionRate row, determine its UI type and the
// resolved field labels/flags to render. Falls back to a populated-field
// heuristic for any future/unmapped componentKey — never hides a component
// just because it isn't in the static map above.
export function classifyIndiaContributionRate(rate) {
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
    uiType = UI_TYPES.FIXED_AMOUNT;
  } else {
    uiType = UI_TYPES.INCOME_TAX_POINTER;
  }

  return { uiType, associatedKey: staticEntry?.associatedKey, ...describeUiType(uiType) };
}
