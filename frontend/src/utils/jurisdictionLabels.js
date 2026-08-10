// Country-aware labels for statutory payroll components. Every jurisdiction's
// income-tax withholding, pension/social contribution, etc. are stored in
// the same fields (tds, pf, esi, employerPf, ...) regardless of country —
// only the DISPLAY LABEL should change. Mirrors the label choices already
// used server-side in generate_payslip_pdf_bytes (backend/app/modules/payroll/service.py)
// so a payslip's PDF and its on-screen views never disagree on wording.

const INCOME_TAX_LABELS = {
  US: "Federal Income Tax",
  UK: "Income Tax (PAYE)",
  AU: "Income Tax (PAYG)",
  DE: "Income Tax (Lohnsteuer)",
  CA: "Federal Income Tax",
};

const PF_LABELS = { DE: "Pension Insurance" };
const ESI_LABELS = { DE: "Social Insurance (Health / Unemployment / Care)", CA: "Employment Insurance (EI)" };
const EMPLOYER_PF_LABELS = { DE: "Employer Pension Insurance" };
const EMPLOYER_ESI_LABELS = { DE: "Employer Social Insurance", CA: "Employer EI Contribution" };
const SOCIAL_SECURITY_LABELS = { CA: "Canada Pension Plan (CPP)" };
const EMPLOYER_SOCIAL_SECURITY_LABELS = { CA: "Employer CPP Contribution" };
const MEDICARE_LABELS = { AU: "Medicare Levy" };
const EMPLOYER_PENSION_LABELS = { AU: "Superannuation (Employer)" };

export function getPayrollLabels(country) {
  const c = (country || "IN").toUpperCase();
  return {
    incomeTax: INCOME_TAX_LABELS[c] || "TDS / Income Tax",
    pf: PF_LABELS[c] || "Provident Fund (PF)",
    esi: ESI_LABELS[c] || "Employee State Insurance (ESI)",
    employerPf: EMPLOYER_PF_LABELS[c] || "Employer PF",
    employerEsi: EMPLOYER_ESI_LABELS[c] || "Employer ESI",
    socialSecurity: SOCIAL_SECURITY_LABELS[c] || "Social Security",
    employerSocialSecurity: EMPLOYER_SOCIAL_SECURITY_LABELS[c] || "Employer Social Security",
    medicare: MEDICARE_LABELS[c] || "Medicare",
    employerPension: EMPLOYER_PENSION_LABELS[c] || "Employer Pension",
  };
}

// Compliance-form copy that otherwise hardcoded India-only terms (PAN/GST,
// "Professional Tax") regardless of the company's selected jurisdiction.
const TAX_ID_LABELS = {
  IN: "Tax Registration No. (PAN/GST)",
  US: "Tax ID (EIN)",
  UK: "Tax Reference (UTR / VAT No.)",
  AU: "Tax File Number (TFN/ABN)",
  DE: "Tax Registration No. (Steuernummer / USt-IdNr.)",
  CA: "Business Number (BN)",
};

// "Professional Tax" is an India-specific, state-levied deduction — only
// mention it for IN; every other jurisdiction gets a neutral note about
// state/province-specific statutory rules instead.
const STATE_RULE_NOTES = {
  IN: "Statutory deductions such as Professional Tax vary by state.",
  US: "Statutory deductions such as state income tax and unemployment insurance vary by state.",
  AU: "Payroll tax thresholds and rates vary by state/territory.",
  CA: "Statutory deductions such as provincial income tax vary by province.",
  DE: "Statutory contribution rates can vary by state (Bundesland).",
  UK: "Statutory rates are generally uniform nationwide, but some allowances vary by region.",
};

export function getComplianceLabels(country) {
  const c = (country || "IN").toUpperCase();
  return {
    taxIdLabel: TAX_ID_LABELS[c] || "Tax Registration Number",
    stateRuleNote: STATE_RULE_NOTES[c] || "Statutory deductions can vary by state/province.",
  };
}
