import ComplianceConfigModal, { CONFIG_TYPES } from "../ComplianceConfigModal";

const STUDENT_LOAN_KEYS = new Set(["sl_plan1_thresh", "sl_plan2_thresh", "sl_plan4_thresh", "sl_plan5_thresh", "pg_loan_thresh"]);
const STUDENT_LOAN_PLANS = [
  { componentKey: "sl_plan1_thresh", label: "Plan 1", rate: "9%" },
  { componentKey: "sl_plan2_thresh", label: "Plan 2", rate: "9%" },
  { componentKey: "sl_plan4_thresh", label: "Plan 4", rate: "9%" },
  { componentKey: "sl_plan5_thresh", label: "Plan 5", rate: "9%" },
  { componentKey: "pg_loan_thresh", label: "Postgraduate Loan", rate: "6%" },
];

// Shape-aware component key options for the shared GenericFallbackForm —
// matches how Canada's CARateGroupTab wires componentKeyOptions. Only the
// keys reachable through the unified UK Tax Components tab's picker that
// are ContributionRate-backed (not slabs, not student loans, not pension).
const GENERIC_RATE_KEYS = [
  { key: "national-insurance", label: "National Insurance (NI)", shape: "rate_pair" },
  { key: "ni_upper_rate", label: "NI Upper Rate (Employee)", shape: "rate_single" },
  { key: "k_code_cap_pct", label: "K-Code Overriding Limit", shape: "rate_single" },
  { key: "personal_allowance", label: "Personal Allowance", shape: "flat" },
  { key: "pa_taper_threshold", label: "Personal Allowance Taper Threshold", shape: "flat" },
  { key: "ni_primary_thresh", label: "NI Primary Threshold", shape: "flat" },
  { key: "ni_upper_threshold", label: "NI Upper Earnings Limit", shape: "flat" },
  { key: "ni_secondary_thresh", label: "NI Secondary Threshold (Employer)", shape: "flat" },
  { key: "pension_qe_lower", label: "Pension QE Lower Limit", shape: "flat" },
  { key: "pension_qe_upper", label: "Pension QE Upper Limit", shape: "flat" },
  { key: "sl_plan1_thresh", label: "Student Loan Plan 1 Threshold", shape: "flat" },
  { key: "sl_plan2_thresh", label: "Student Loan Plan 2 Threshold", shape: "flat" },
  { key: "sl_plan4_thresh", label: "Student Loan Plan 4 Threshold", shape: "flat" },
  { key: "sl_plan5_thresh", label: "Student Loan Plan 5 Threshold", shape: "flat" },
  { key: "pg_loan_thresh", label: "Postgraduate Loan Threshold", shape: "flat" },
  // 2026-09-09 gap-closure Phase 2: Statutory Sick Pay / Statutory Family
  // Pay + recovery keys — these have been readable by uk.py's
  // calculate_ssp()/calculate_statutory_family_pay()/
  // calculate_family_pay_employer_recovery() since the 2026-09-08 commit,
  // but had no UI path to configure at all (no hardcoded fallback either
  // — they fail closed until a Super Admin enters a real row here).
  { key: "ssp_weekly_cap", label: "Statutory Sick Pay — Weekly Cap", shape: "flat" },
  { key: "ssp_awe_pct", label: "Statutory Sick Pay — AWE Percentage", shape: "rate_single" },
  { key: "fam_pay_awe_pct", label: "Statutory Family Pay — AWE Percentage", shape: "rate_single" },
  { key: "fam_pay_flat_rate", label: "Statutory Family Pay — Standard Weekly Rate", shape: "flat" },
  { key: "fam_pay_recov_thresh", label: "Family Pay Recovery — Small Employer Threshold", shape: "flat" },
  // Employer recovery %s — uk.py reads these via .employer_rate_pct, not
  // .employee_rate_pct (it's what the EMPLOYER reclaims, not an employee
  // deduction), so "rate_single_employer" (not "rate_single") is correct here.
  { key: "fam_pay_recov_small", label: "Family Pay Recovery Rate — Small Employer", shape: "rate_single_employer" },
  { key: "fam_pay_recov_std", label: "Family Pay Recovery Rate — Standard", shape: "rate_single_employer" },
  // Apprenticeship Levy / Employment Allowance / Class 1A / Class 1B —
  // all employer-only charges, same "readable but unconfigurable until
  // now" status as the statutory-pay keys above.
  { key: "appr_levy_rate", label: "Apprenticeship Levy Rate", shape: "rate_single_employer" },
  { key: "appr_levy_allowance", label: "Apprenticeship Levy Annual Allowance", shape: "flat" },
  { key: "empl_allowance_cap", label: "Employment Allowance Cap", shape: "flat" },
  { key: "c1a_benefits_rate", label: "Class 1A — Benefits & Expenses Rate", shape: "rate_single_employer" },
  { key: "c1a_term_rate", label: "Class 1A — Termination Awards Rate", shape: "rate_single_employer" },
  { key: "c1a_term_thresh", label: "Class 1A — Termination Awards Threshold", shape: "flat" },
  { key: "c1a_testim_rate", label: "Class 1A — Sporting Testimonial Rate", shape: "rate_single_employer" },
  { key: "c1a_testim_thresh", label: "Class 1A — Sporting Testimonial Threshold", shape: "flat" },
  { key: "c1b_psa_rate", label: "Class 1B — PAYE Settlement Agreement Rate", shape: "rate_single_employer" },
];

// The single entry point for every UK Tax Components tab Add/Edit modal.
// Determines the correct ComplianceConfigModal configType from the
// component being added/edited and passes the right props:
//   - NI Category bands (TaxSlab, ruleType=NI_BAND)  → NI_CATEGORY form
//   - Student/Postgraduate loan thresholds           → EMPLOYEE_DEDUCTION form
//   - Workplace Pension employer rate                → CONTRIBUTION_RATE form
//   - All other ContributionRate rows                → GENERIC (shape-aware)
//   - Any unmapped/custom component                  → GENERIC (shape-aware)
//
// Props:
//   mode:     "add" | "edit"
//   initial:  { componentKey, displayName } — from the picker (add only)
//   rate:     ContributionRate row (edit only)
//   slab:     TaxSlab row (edit only, for NI bands)
//   pack:     current JurisdictionPack
//   rates:    full rates array (for student loan plan + pension resolution)
//   onSaved:  callback after successful save
//   onClose:  callback to close the modal
//   addToast: toast function
export default function UKComponentFormModal({ mode = "edit", initial, rate, slab, pack, rates = [], onSaved, onClose, addToast }) {
  const componentKey = rate?.componentKey || initial?.componentKey || slab?.componentKey || "";

  // NI category bands → dedicated NI_CATEGORY form
  if (slab?.ruleType === "NI_BAND") {
    return (
      <ComplianceConfigModal
        configType={CONFIG_TYPES.NI_CATEGORY}
        mode={mode}
        pack={pack}
        initialData={slab}
        addToast={addToast}
        onClose={onClose}
        onSaved={onSaved}
      />
    );
  }

  // Any other tax slab → TAX_SLAB form
  if (slab) {
    return (
      <ComplianceConfigModal
        configType={CONFIG_TYPES.TAX_SLAB}
        mode={mode}
        pack={pack}
        initialData={slab}
        addToast={addToast}
        onClose={onClose}
        onSaved={onSaved}
      />
    );
  }

  // Student / Postgraduate loan thresholds → EMPLOYEE_DEDUCTION form
  if (componentKey && STUDENT_LOAN_KEYS.has(componentKey)) {
    const plan = STUDENT_LOAN_PLANS.find((p) => p.componentKey === componentKey) || STUDENT_LOAN_PLANS[0];
    const rateRow = rate || rates.find((r) => r.componentKey === componentKey);
    return (
      <ComplianceConfigModal
        configType={CONFIG_TYPES.EMPLOYEE_DEDUCTION}
        mode={rateRow ? "edit" : "add"}
        pack={pack}
        plan={plan}
        rate={rateRow || null}
        plans={STUDENT_LOAN_PLANS}
        rates={rates}
        allowPlanChange={Boolean(initial)}
        addToast={addToast}
        onClose={onClose}
        onSaved={onSaved}
      />
    );
  }

  // Workplace Pension employer rate (and its pension_basis text value,
  // which the pension form writes together) → CONTRIBUTION_RATE form
  if (componentKey === "employer-pension" || componentKey === "pension_basis") {
    const pensionRate = rates.find((r) => r.componentKey === "employer-pension");
    const basisRow = rates.find((r) => r.componentKey === "pension_basis");
    const isBasisOnly = componentKey === "pension_basis";
    return (
      <ComplianceConfigModal
        configType={CONFIG_TYPES.CONTRIBUTION_RATE}
        mode={isBasisOnly ? "edit" : pensionRate ? "edit" : "add"}
        pack={pack}
        pensionRate={pensionRate || null}
        basisRow={basisRow || null}
        addToast={addToast}
        onClose={onClose}
        onSaved={onSaved}
      />
    );
  }

  // Everything else (national-insurance, thresholds, custom) → GENERIC
  // shape-aware form using the shared GenericFallbackForm.
  return (
    <ComplianceConfigModal
      configType={CONFIG_TYPES.GENERIC}
      mode={mode}
      pack={pack}
      initialData={rate || null}
      componentKeyOptions={GENERIC_RATE_KEYS}
      addToast={addToast}
      onClose={onClose}
      onSaved={onSaved}
    />
  );
}
