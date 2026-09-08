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
  // ZP-TAX-US-2026-001 §5 build-out — state-level statutory payroll
  // programs beyond the original SDI/PFL/WA Cares set above. "paid_leave"
  // is deliberately its OWN entry, distinct from "pfl": several states
  // (CT/DC/NY) run their own program under this generic name rather than
  // literally being called "PFL", and the underlying engine component_key
  // already seeded live is "paid_leave", not "pfl" — this entry matches
  // what's actually in the database, not a renamed alias.
  {
    componentKey: "paid_leave", displayName: "Paid Leave",
    category: "familyDisability",
    description: "State paid family/medical leave program (e.g. Connecticut Paid Leave, DC Universal Paid Leave, New York Paid Family Leave) — employee, employer, or both, depending on the state.",
    uiTypeHint: UI_TYPES.EMPLOYEE_EMPLOYER_PERCENTAGE,
  },
  {
    componentKey: "tdi", displayName: "Temporary Disability Insurance (TDI)",
    category: "familyDisability",
    description: "Employee-paid short-term disability contribution (e.g. Rhode Island TDI/TCI).",
    uiTypeHint: UI_TYPES.PERCENTAGE,
  },
  {
    componentKey: "worker_ui", displayName: "Worker Unemployment Insurance",
    category: "unemploymentInsurance",
    description: "Employee-side worker contribution to state UI (e.g. New Jersey Worker UI).",
    uiTypeHint: UI_TYPES.PERCENTAGE,
  },
  {
    componentKey: "worker_di", displayName: "Worker Disability Insurance",
    category: "familyDisability",
    description: "Employee-paid state disability insurance contribution, distinct from SDI's own component (e.g. New Jersey Worker Disability Insurance).",
    uiTypeHint: UI_TYPES.PERCENTAGE,
  },
  {
    componentKey: "workforce_dev", displayName: "Workforce Development / Supplemental Workforce Fund",
    category: "unemploymentInsurance",
    description: "Employee-paid workforce training/development assessment (e.g. New Jersey Workforce Development Fund).",
    uiTypeHint: UI_TYPES.PERCENTAGE,
  },
  {
    componentKey: "fli", displayName: "Family Leave Insurance (FLI)",
    category: "familyDisability",
    description: "Employee-paid family leave insurance contribution (e.g. New Jersey Family Leave Insurance).",
    uiTypeHint: UI_TYPES.PERCENTAGE,
  },
  {
    componentKey: "state_standard_deduction", displayName: "State Standard Deduction",
    category: "incomeTax",
    description: "Filing-status-based standard deduction/allowance subtracted before applying this state's own income-tax rate (e.g. Colorado, Kentucky).",
    uiTypeHint: UI_TYPES.DEDUCTION_AMOUNT,
  },
  // "<componentKey>_wage_cap" / "<componentKey>_annual_max" — the optional
  // companion rows any program above can carry (ZP-TAX-US-2026-001 §5: a
  // wage-base cap on the taxable amount, and/or a dollar cap on the
  // resulting contribution itself) are deliberately NOT their own
  // top-level catalog entries — they only ever make sense attached to a
  // program that already exists, so they're added via "Other / Custom
  // Component" typing the exact suffixed key (e.g. "tdi_wage_cap").
  // usaComponentConfig.js's classifyContributionRate recognizes both
  // suffixes generically once created, so they still display/edit
  // correctly (right label, right field) with no catalog entry needed.
];
