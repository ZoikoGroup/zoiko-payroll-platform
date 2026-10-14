// Country-aware labels for statutory payroll components. Every jurisdiction's
// income-tax withholding, pension/social contribution, etc. are stored in
// the same fields (tds, pf, esi, employerPf, ...) regardless of country —
// only the DISPLAY LABEL should change. Mirrors the label choices already
// used server-side in generate_payslip_pdf_bytes (backend/app/modules/payroll/service.py)
// so a payslip's PDF and its on-screen views never disagree on wording.

// Each jurisdiction's own plain term — not a generic "Income Tax" gloss —
// so a payslip reads the way that country's own payslips actually do.
const INCOME_TAX_LABELS = {
  IN: "TDS",
  US: "Federal Withholding",
  UK: "PAYE",
  AU: "PAYG",
  DE: "Lohnsteuer",
  CA: "Federal Tax",
  // Caribbean production jurisdictions (ZP-MJR-2026-002, 2026-09-24) —
  // real terms verified from each country's own engine module docstring
  // (backend/app/modules/payroll/engine/countries/*.py), not guessed.
  // Bahamas/Cayman deliberately have no entry: `tds` is always 0 for both
  // (no personal income tax), so this map is never consulted with a
  // nonzero value for them.
  BB: "PAYE", DO: "ISR", GY: "PAYE", JM: "PAYE", TT: "PAYE",
  PR: "Hacienda Withholding",
  // Ireland's PAYE is the `tds` column, same shape as the other PAYE
  // jurisdictions. USC, PRSI and MyFutureFund ride on the payslip's
  // complianceFields snapshot rather than dedicated columns, so they are
  // labelled from the identity/compliance field path below.
  IE: "PAYE",
  // Sweden's preliminary tax (preliminär skatt) — table/column, 30%
  // supplementary, one-time or SINK, per the frozen se_calculation_snapshot.
  SE: "Preliminary Tax",
  // Switzerland — source tax (Quellensteuer), employee-only; the canton
  // tariffs are ingested as QST tariff files (ZP-CH-PAYROLL-001). Matches
  // the backend's own PDF wording "Source tax (Quellensteuer) withheld".
  CH: "Source Tax (QST)",
};

// Jurisdictions with NO payroll income-tax withholding at all — the payslip
// shows no income-tax line (not even a zero one). Hong Kong Salaries Tax is
// employee-assessed by the IRD (ZP-HK-ENG-001 architecture lock). Saudi Arabia
// has no monthly income-tax withholding: its statutory payroll liability is
// GOSI (pension/SANED/occupational hazard), never a `tds` line
// (ZP-SA-ENG-001 — the engine NEVER returns a `tds` key and tds stays 0.00).
const NO_PAYROLL_INCOME_TAX = new Set(["HK", "SA"]);

const PF_LABELS = { DE: "Pension Insurance" };
const ESI_LABELS = { DE: "Social Insurance (Health / Unemployment / Care)", CA: "Employment Insurance (EI)" };
const EMPLOYER_PF_LABELS = { DE: "Employer Pension Insurance" };
const EMPLOYER_ESI_LABELS = { DE: "Employer Social Insurance", CA: "Employer EI Contribution" };
const SOCIAL_SECURITY_LABELS = {
  CA: "Canada Pension Plan (CPP)",
  BB: "NIS", DO: "SFS (Seguro Familiar de Salud)", GY: "NIS", JM: "NIS", TT: "NIS",
  BS: "NIB", KY: "NIB Pension",
};
const EMPLOYER_SOCIAL_SECURITY_LABELS = { CA: "Employer CPP Contribution" };
const MEDICARE_LABELS = { AU: "Medicare Levy" };
const EMPLOYER_PENSION_LABELS = { AU: "Superannuation (Employer)", HK: "MPF Mandatory Contribution (Employer)" };
const CHURCH_TAX_LABELS = { DE: "Kirchensteuer" };
const SOLIDARITY_SURCHARGE_LABELS = { DE: "Solidaritätszuschlag" };
// Trinidad reuses the `professionalTax` field for its Health Surcharge (see
// trinidad_and_tobago.py's own comment on that field) — was previously
// shown under the literal, India-specific "Professional Tax" for every
// country.
const PROFESSIONAL_TAX_LABELS = { TT: "Health Surcharge" };
// `employeePension`/`niEmployee` are reused/repurposed fields in these
// Caribbean countries, NOT a literal pension or UK National Insurance —
// see barbados.py/dominican_republic.py/jamaica.py's own field comments.
const EMPLOYEE_PENSION_LABELS = {
  BB: "Reserve & Retraining (R&R) Levy",
  DO: "Pension (SVDS)",
  JM: "National Housing Trust (NHT)",
  HK: "MPF Mandatory Contribution (Employee)",
};
const NI_EMPLOYEE_LABELS = { JM: "Education Tax" };

// US-specific: federal/state/local income tax are stored as separate
// PayslipItem columns (federal_income_tax/state_income_tax/local_tax) —
// `tds` remains the combined total for backward compatibility. A payslip
// generated before this split existed has all three at their default 0
// even though `tds` is genuinely nonzero, so the split is only used when
// at least one of the three is actually nonzero — otherwise this falls
// back to the single combined line every other jurisdiction already uses,
// exactly matching pre-split behavior for old US payslips. Returns
// [label, amount] tuples so any list-based deduction table (PayslipStub,
// RunDetailPanel, ...) can spread them in place of a single generic line.
export function getIncomeTaxLines(payslip) {
  const c = (payslip?.country || "IN").toUpperCase();
  if (NO_PAYROLL_INCOME_TAX.has(c)) return [];
  if (c === "US") {
    const fed = Number(payslip?.federalIncomeTax) || 0;
    const state = Number(payslip?.stateIncomeTax) || 0;
    const local = Number(payslip?.localTax) || 0;
    if (fed + state + local > 0) {
      return [
        ["Federal Withholding", fed],
        ["State Tax", state],
        ["Local Tax", local],
      ];
    }
  }
  return [[getPayrollLabels(c).incomeTax, Number(payslip?.tds) || 0]];
}

export function getPayrollLabels(country) {
  const c = (country || "IN").toUpperCase();
  return {
    incomeTax: NO_PAYROLL_INCOME_TAX.has(c) ? "Salaries Tax (not withheld)" : (INCOME_TAX_LABELS[c] || "TDS"),
    noPayrollIncomeTax: NO_PAYROLL_INCOME_TAX.has(c),
    pf: PF_LABELS[c] || "Provident Fund (PF)",
    esi: ESI_LABELS[c] || "Employee State Insurance (ESI)",
    employerPf: EMPLOYER_PF_LABELS[c] || "Employer PF",
    employerEsi: EMPLOYER_ESI_LABELS[c] || "Employer ESI",
    socialSecurity: SOCIAL_SECURITY_LABELS[c] || "Social Security",
    employerSocialSecurity: EMPLOYER_SOCIAL_SECURITY_LABELS[c] || "Employer Social Security",
    medicare: MEDICARE_LABELS[c] || "Medicare",
    employerPension: EMPLOYER_PENSION_LABELS[c] || "Employer Pension",
    churchTax: CHURCH_TAX_LABELS[c] || null,
    solidaritySurcharge: SOLIDARITY_SURCHARGE_LABELS[c] || null,
    professionalTax: PROFESSIONAL_TAX_LABELS[c] || "Professional Tax",
    employeePension: EMPLOYEE_PENSION_LABELS[c] || "Workplace Pension",
    niEmployee: NI_EMPLOYEE_LABELS[c] || "National Insurance",
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
  HK: "Business Registration No. / IRD Employer's File No.",
  CH: "UID (Business Identification No.)",
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
  HK: "One territory-wide regime: MPF is deducted through payroll; Salaries Tax is assessed by the IRD on the employee and is never withheld from pay.",
};

// The one statutory ID that best identifies an employee to their tax
// authority, per jurisdiction — India's lives on the payslip's own `pan`
// column; every other country's lives in the payslip's `complianceFields`
// snapshot (see employee_validation.py for the full per-country field
// list). Mirrors _payslip_identity_rows in service.py so the on-screen
// payslip and the generated PDF never disagree on which field they show.
const IDENTITY_FIELD = {
  IN: { label: "PAN", get: (p) => p.pan },
  US: { label: "SSN", get: (p) => p.complianceFields?.ssn },
  UK: { label: "NINO", get: (p) => p.complianceFields?.nino },
  AU: { label: "TFN", get: (p) => p.complianceFields?.tfn },
  CA: { label: "SIN", get: (p) => p.complianceFields?.sin },
  DE: { label: "Steuer-ID", get: (p) => p.complianceFields?.steuer_id },
  // Masked server-side (SENSITIVE_FIELDS) before it ever reaches the browser.
  HK: { label: "HKID", get: (p) => p.complianceFields?.hkid || p.complianceFields?.passport_number },
  // Caribbean production jurisdictions (ZP-MJR-2026-002, 2026-09-24) — the
  // data was already captured end-to-end (complianceFields), only this
  // display mapping was missing, so a Caribbean/PR payslip previously fell
  // back to IDENTITY_FIELD.IN below ("PAN", always blank for these
  // employees).
  BB: { label: "TAMIS TIN", get: (p) => p.complianceFields?.tamis_tin },
  KY: { label: "NIB Member No.", get: (p) => p.complianceFields?.nib_member_number },
  DO: { label: "Cédula", get: (p) => p.complianceFields?.cedula },
  GY: { label: "GRA TIN", get: (p) => p.complianceFields?.gra_tin },
  JM: { label: "TRN", get: (p) => p.complianceFields?.trn },
  BS: { label: "NIB No.", get: (p) => p.complianceFields?.nib_number },
  TT: { label: "BIR File No.", get: (p) => p.complianceFields?.bir_file_number },
  PR: { label: "SSN", get: (p) => p.complianceFields?.ssn },
  IE: { label: "PPSN", get: (p) => p.complianceFields?.ppsn },
  SE: { label: "Personnummer", get: (p) => p.complianceFields?.swedish_id_number },
  IT: { label: "Codice fiscale", get: (p) => p.complianceFields?.codice_fiscale },
  // Masked server-side (SENSITIVE_FIELDS), same as HKID above.
  CH: { label: "AHV No.", get: (p) => p.complianceFields?.ahv_number },
};

export function getIdentityField(payslip) {
  const c = (payslip?.country || "IN").toUpperCase();
  const spec = IDENTITY_FIELD[c] || IDENTITY_FIELD.IN;
  return { label: spec.label, value: spec.get(payslip || {}) || null };
}

export function getComplianceLabels(country) {
  const c = (country || "IN").toUpperCase();
  return {
    taxIdLabel: TAX_ID_LABELS[c] || "Tax Registration Number",
    stateRuleNote: STATE_RULE_NOTES[c] || "Statutory deductions can vary by state/province.",
  };
}
