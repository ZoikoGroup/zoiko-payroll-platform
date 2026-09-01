import { UI_TYPES } from "./usaComponentConfig";

// USA-only curated catalog of common STATE-level payroll components —
// additive alongside usaComponentConfig.js's PAYROLL_COMPONENT_CATALOG
// (federal-only, untouched by this file). Same {componentKey, displayName,
// category, description} shape, plus a `uiTypeHint` (one of the same
// UI_TYPES usaComponentConfig.js already defines) so the existing dynamic
// form (describeUiType) renders the right fields with zero new form logic.
//
// componentKey values are short — payroll_contribution_rates.component_key
// is VARCHAR(20) — and are just regular strings saved via the existing
// upsertCanonicalContributionRate API, exactly like every other component
// key in this app. No schema change, no new endpoint.
//
// These are sensible DEFAULTS for common state programs, not an exhaustive
// per-state list — real state law varies (not every state has SDI/PFL,
// naming differs by state). An admin can still add anything else via the
// existing "Other / Custom Component" escape hatch if a state needs a
// component not listed here.
export const STATE_COMPONENT_CATEGORIES = {
  incomeTax: "Income Tax",
  unemploymentInsurance: "Unemployment Insurance",
  familyDisability: "Family & Disability",
  longTermCare: "Long-Term Care",
  localTaxes: "Local Taxes",
};

export const STATE_COMPONENT_CATALOG = [
  {
    // Mirrors usaComponentConfig.js's "federal-income-tax" pointer exactly
    // (same navigatesTo mechanism, same "brackets live in the Income Tax
    // Brackets tab, not here" reasoning) — a distinct componentKey so it's
    // never confused with the federal entry's row. Needed so a State pack's
    // Add Component list has a way to reach its own Income Tax Brackets tab
    // now that the federal catalog is no longer merged in.
    componentKey: "state-income-tax", displayName: "State Income Tax",
    category: "incomeTax",
    description: "Progressive/flat brackets — configured in the Income Tax Brackets tab.",
    navigatesTo: "incomeTax",
  },
  {
    componentKey: "sui", displayName: "State Unemployment Insurance (SUI)",
    category: "unemploymentInsurance",
    description: "Employer-paid state unemployment tax, agency-assigned rate.",
    uiTypeHint: UI_TYPES.EMPLOYER_ASSIGNED_RATE,
  },
  {
    componentKey: "sui_wage_base", displayName: "SUI Taxable Wage Base",
    category: "unemploymentInsurance",
    description: "Annual per-employee wage cap SUI applies up to.",
    uiTypeHint: UI_TYPES.WAGE_BASE, parentKey: "sui",
  },
  {
    componentKey: "ett", displayName: "Employment Training Tax (ETT)",
    category: "unemploymentInsurance",
    description: "Employer-only workforce training assessment (e.g. California ETT).",
    uiTypeHint: UI_TYPES.EMPLOYER_ASSIGNED_RATE,
  },
  {
    componentKey: "sdi", displayName: "State Disability Insurance (SDI)",
    category: "familyDisability",
    description: "Employee-paid short-term disability contribution.",
    uiTypeHint: UI_TYPES.PERCENTAGE,
  },
  {
    componentKey: "pfl", displayName: "Paid Family Leave (PFL)",
    category: "familyDisability",
    description: "Employee and/or employer paid family & medical leave contribution.",
    uiTypeHint: UI_TYPES.EMPLOYEE_EMPLOYER_PERCENTAGE,
  },
  {
    componentKey: "local_transit", displayName: "Local Transit Tax",
    category: "localTaxes",
    description: "Employer-paid local/regional transit payroll tax (e.g. NY MCTMT, OR transit tax).",
    uiTypeHint: UI_TYPES.EMPLOYER_ASSIGNED_RATE,
  },
  {
    componentKey: "wa_cares", displayName: "WA Cares Fund",
    category: "longTermCare",
    description: "Long-term care payroll contribution (e.g. Washington WA Cares Fund).",
    uiTypeHint: UI_TYPES.PERCENTAGE,
  },
];
