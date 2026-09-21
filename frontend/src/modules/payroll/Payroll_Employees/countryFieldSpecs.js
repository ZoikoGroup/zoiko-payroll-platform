// Matches backend/app/modules/payroll/employee_validation.py exactly — these
// are the six jurisdictions get_employee_validation_strategy() dispatches
// on. Each spec's `required`/`pattern`/`error`/`strip`/`upper`/`choices`
// mirror the server's FIELD_SPECS so the bulk-import preview and the
// EmployeeForm can surface the SAME failure causes before anything hits the
// API (the server stays authoritative and re-validates on write). Kept in
// one file so labels/choices/validation never drift out of sync.
export const COUNTRIES = [
  { code: "IN", name: "India" },
  { code: "US", name: "United States" },
  { code: "UK", name: "United Kingdom" },
  { code: "AU", name: "Australia" },
  { code: "CA", name: "Canada" },
  { code: "DE", name: "Germany" },
  // Caribbean production jurisdictions (2026-09-21) — matching
  // backend/app/modules/payroll/employee_validation.py's _STRATEGIES
  // (BB/KY/DO/GY/JM/BS/TT entries, each with an empty FIELD_SPECS for
  // now — no jurisdiction-specific employee field validation is
  // enforced yet, so COUNTRY_FIELD_SPECS below has no entry for them
  // either; the `|| []` fallback everywhere COUNTRY_FIELD_SPECS is read
  // already handles an absent key).
  { code: "BB", name: "Barbados" },
  { code: "KY", name: "Cayman Islands" },
  { code: "DO", name: "Dominican Republic" },
  { code: "GY", name: "Guyana" },
  { code: "JM", name: "Jamaica" },
  { code: "BS", name: "Bahamas" },
  { code: "TT", name: "Trinidad and Tobago" },
];

export const COUNTRY_FIELD_SPECS = {
  IN: [
    { key: "esi_number", label: "ESI number", type: "text", pattern: /^\d{10}(\d{7})?$/, error: "ESI number must be 10 or 17 digits." },
    { key: "tax_regime", label: "Tax regime", type: "select", choices: ["Old", "New"] },
  ],
  US: [
    { key: "ssn", label: "SSN", type: "text", placeholder: "123-45-6789", required: true, strip: " ", pattern: /^\d{3}-\d{2}-\d{4}$/, error: "SSN must be in the format 123-45-6789." },
    { key: "flsa_status", label: "FLSA status", type: "select", required: true, choices: ["Exempt", "Non-Exempt"] },
    { key: "w4_filing_status", label: "W-4 filing status", type: "select", choices: ["Single", "Married Filing Jointly", "Married Filing Separately", "Head of Household"] },
    // Form W-4 Step 2 "Multiple Jobs or Spouse Works" checkbox — a real,
    // higher-withholding bracket table (backend: hardcoded_defaults.py's
    // "_STEP2"-tagged federal TaxSlab rows), not cosmetic. Optional:
    // leaving unset/false uses the standard table exactly as before.
    { key: "w4_step2_checkbox", label: "W-4 Step 2 checked (multiple jobs / spouse works)", type: "select", choices: ["true", "false", "True", "False"] },
    // Which Form W-4 vintage this employee actually filed (backend:
    // models.py's w4_form_vintage) — selects the pre-2020-allowance path
    // and North Dakota's two different bracket tables in us.py. Existed
    // in the engine/DB since gap-closure Phase 2d, but had no Org Admin
    // UI path at all until this fix (2026-09-15 onboarding-guidance
    // audit). Unset defaults to the current post-2020 form, same as
    // before this field had a UI.
    { key: "w4_form_vintage", label: "W-4 form vintage", type: "select", choices: ["2020 or later (current form)", "Pre-2020 (legacy form)"] },
    // Federal W-4 §3.4 controls — all optional, each a no-op until set.
    // w4_allowances_claimed only matters on the legacy (pre-2020) form path.
    { key: "w4_allowances_claimed", label: "W-4 allowances claimed (pre-2020 form only)", type: "number", min: 0 },
    { key: "is_nonresident_alien", label: "Nonresident alien (Form W-4 NRA adjustment)", type: "select", choices: ["true", "false", "True", "False"] },
    { key: "w4_dependents_credit_annual", label: "W-4 Step 3: dependents credit (annual $)", type: "number", min: 0 },
    { key: "w4_other_income_annual", label: "W-4 Step 4(a): other income (annual $)", type: "number", min: 0 },
    { key: "w4_extra_withholding_per_period", label: "W-4 Step 4(c): extra withholding (per pay period $)", type: "number", min: 0 },
    // Connecticut CT-W4 Withholding Code — only meaningful for CT employees.
    // showWhen: previously shown unconditionally for every US employee
    // regardless of work state (found 2026-09-15 onboarding-guidance
    // audit) — now hidden unless the employee's own work state actually
    // matches, same as EmployeeForm's existing country-conditional
    // sections (UK RTI / CA TD1X).
    { key: "ct_withholding_code", label: "CT Withholding Code (CT employees only)", type: "select", choices: ["A", "B", "C", "D", "F"], showWhen: (cf) => (cf?.state_tax_jurisdiction || "").toUpperCase() === "CT" },
    { key: "nj_rate_table", label: "NJ-W4 Rate Table (NJ employees only)", type: "select", choices: ["A", "B", "C", "D", "E"], showWhen: (cf) => (cf?.state_tax_jurisdiction || "").toUpperCase() === "NJ" },
    // Kansas Form K-4 certified dependent count — only meaningful for KS
    // employees; drives the personal-exemption/HOH/dependent-allowance
    // layer in engine/countries/us.py's _ks_personal_exemption_for_status.
    { key: "ks_k4_dependents", label: "K-4 dependent count (KS employees only)", type: "number", min: 0, showWhen: (cf) => (cf?.state_tax_jurisdiction || "").toUpperCase() === "KS" },
    { key: "aba_routing_number", label: "ABA routing number", type: "text", placeholder: "9 digits", pattern: /^\d{9}$/, error: "ABA routing number must be exactly 9 digits." },
    { key: "state_tax_jurisdiction", label: "State tax jurisdiction", type: "text", placeholder: "e.g. CA", required: true, upper: true, pattern: /^[A-Z]{2}$/, error: "State tax jurisdiction must be a 2-letter state code (e.g. CA, NY)." },
    // Reciprocity (backend: service.py's _resolve_us_reciprocity) — only
    // meaningfully different from state_tax_jurisdiction (work state) for a
    // genuine multi-state commuter, e.g. lives in PA, works in NJ. All
    // optional: leaving these blank is the same as today's behavior for
    // every employee whose residence and work state match.
    { key: "residence_state", label: "Residence state (if different from work state)", type: "text", placeholder: "e.g. PA", upper: true, pattern: /^[A-Z]{2}$/, error: "Residence state must be a 2-letter state code (e.g. PA)." },
    // City/local-level residence (backend: models.py's residence_locality) —
    // New York's Yonkers resident surcharge, and (once real PA PSD-code
    // data exists) Pennsylvania's own resident-locality side of the Act
    // 32 "higher of" comparison. Optional free text, same convention as
    // work_locality below.
    { key: "residence_locality", label: "Residence locality (e.g. YONKERS, or a PA PSD code)", type: "text", placeholder: "e.g. YONKERS" },
    { key: "reciprocity_certificate_on_file", label: "Reciprocity certificate on file", type: "select", choices: ["true", "false", "True", "False"] },
    { key: "reciprocity_certificate_expiry", label: "Reciprocity certificate expiry", type: "date", pattern: /^\d{4}-\d{2}-\d{2}$/, error: "Certificate expiry must be in YYYY-MM-DD format." },
    // Pennsylvania Act 32 Residency Certification Form (DCED-CLGS-32-6) —
    // pure recordkeeping, optional; never read by any calculation.
    { key: "residency_certification_on_file", label: "PA Residency Certification on file", type: "select", choices: ["true", "false", "True", "False"] },
    { key: "residency_certification_date", label: "PA Residency Certification date", type: "date", pattern: /^\d{4}-\d{2}-\d{2}$/, error: "Residency certification date must be in YYYY-MM-DD format." },
    // Locality (backend: service.py's get_locality_rate) — only meaningful
    // once Tax Ops has entered a matching rate in Super Admin > Compliance >
    // United States > Locality Rates. Optional free text: no format is
    // enforced since real-world locality codes vary (county FIPS, municipal
    // short codes, PSD codes).
    { key: "work_locality", label: "Work locality code (county/municipal/school-district)", type: "text", placeholder: "e.g. PHILADELPHIA" },
    // Arizona Form A-4 employee election (ZP-TAX-US-2026-001 §4 Matrix) —
    // statutory range 0.5%-3.5%. Only meaningful for AZ employees; leaving
    // it blank falls back to the document's own 2.0% no-form default,
    // exactly as before this field existed. The server is authoritative on
    // the 0.5-3.5 bound (employee_validation.py) — no client-side pattern
    // here, same as every other numeric-range field in this list.
    { key: "state_income_tax_election_pct", label: "Arizona A-4 withholding election % (0.5–3.5, AZ only)", type: "text", placeholder: "e.g. 2.0", showWhen: (cf) => (cf?.state_tax_jurisdiction || "").toUpperCase() === "AZ" },
  ],
  UK: [
    // NOTE: the first/second letter exclusions (D,F,I,Q,U,V) are real — a
    // sample like "QQ123456C" is itself invalid and gets rejected.
    { key: "nino", label: "NINO", type: "text", placeholder: "AB123456C", required: true, upper: true, strip: " ", pattern: /^[A-CEGHJ-PR-TW-Z][A-CEGHJ-NPR-TW-Z]\d{6}[A-D]$/, error: "NINO must look like AB123456C." },
    { key: "paye_tax_code", label: "PAYE tax code", type: "text", placeholder: "1257L", required: true, upper: true, pattern: /^(K\d{1,6}|\d{1,4}[LMNPTY]|BR|NT|D0|D1)$/, error: "PAYE tax code format looks incorrect (e.g. 1257L)." },
    { key: "student_loan_plan", label: "Student loan plan", type: "select", choices: ["None", "Plan 1", "Plan 2", "Plan 4", "Postgraduate"] },
    { key: "auto_enrolment_pension", label: "Auto-enrolment pension", type: "select", choices: ["true", "false", "True", "False"] },
    { key: "sort_code", label: "Bank sort code", type: "text", placeholder: "123456 or 12-34-56", required: true, strip: "- ", pattern: /^\d{6}$/, error: "Sort code must be 6 digits (e.g. 123456 or 12-34-56)." },
  ],
  AU: [
    { key: "tfn", label: "TFN", type: "text", placeholder: "8-9 digits", required: true, strip: " ", pattern: /^\d{8,9}$/, error: "TFN must be 8 or 9 digits." },
    { key: "tfn_status", label: "TFN status", type: "select", choices: ["PROVIDED", "NOT_PROVIDED", "EXEMPTION"] },
    { key: "residency_status", label: "Residency status", type: "select", choices: ["RESIDENT", "FOREIGN_RESIDENT", "WORKING_HOLIDAY_MAKER"] },
    { key: "tax_free_threshold_claimed", label: "Tax-free threshold claimed", type: "select", choices: ["true", "false"] },
    { key: "medicare_levy_exemption", label: "Medicare levy exemption", type: "select", choices: ["FULL", "HALF"] },
    { key: "withholding_variation_pct", label: "Withholding variation (%)", type: "text", pattern: /^\d+(\.\d{1,2})?$/, error: "Withholding variation must be a number." },
    { key: "extra_pay_calendar", label: "Extra-pay calendar (53/27-pay year)", type: "select", choices: ["53_WEEK", "27_FORTNIGHT"] },
    { key: "work_state", label: "State/territory of work", type: "select", upper: true, choices: ["NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"] },
    { key: "help_stsl_debt", label: "HELP/STSL debt", type: "select", choices: ["true", "false"] },
    { key: "super_fund_usi", label: "Super fund USI", type: "text", upper: true, pattern: /^[A-Z0-9]{8,14}$/, error: "Super fund USI looks incorrect." },
    { key: "super_member_number", label: "Super member number", type: "text", pattern: /^[A-Za-z0-9]{1,20}$/, error: "Member number looks incorrect." },
    { key: "bsb_code", label: "BSB code", type: "text", placeholder: "6 digits", required: true, strip: "- ", pattern: /^\d{6}$/, error: "BSB code must be 6 digits (e.g. 123456 or 123-456)." },
  ],
  CA: [
    { key: "sin", label: "SIN", type: "text", placeholder: "9 digits", required: true, strip: "- ", pattern: /^\d{9}$/, error: "SIN must be 9 digits (e.g. 123-456-789)." },
    { key: "td1_claim_amount", label: "TD1 claim amount", type: "text", pattern: /^\d+(\.\d{1,2})?$/, error: "TD1 claim amount must be a number." },
    { key: "provincial_td1_claim_amount", label: "Provincial/territorial TD1 claim amount", type: "text", pattern: /^\d+(\.\d{1,2})?$/, error: "Provincial TD1 claim amount must be a number." },
    { key: "qc_tp1015_claim_amount", label: "TP-1015.3-V claim amount (Quebec)", type: "text", pattern: /^\d+(\.\d{1,2})?$/, error: "TP-1015.3-V claim amount must be a number." },
    { key: "td1_additional_tax", label: "TD1X additional tax per pay period", type: "text", pattern: /^\d+(\.\d{1,2})?$/, error: "TD1X additional tax must be a number." },
    { key: "province", label: "Province of employment", type: "select", required: true, upper: true, choices: ["ON", "QC", "BC", "AB", "MB", "SK", "NS", "NB", "NL", "PE", "YT", "NT", "NU"] },
    { key: "transit_number", label: "Bank transit number", type: "text", placeholder: "5 digits", pattern: /^\d{5}$/, error: "Transit number must be 5 digits." },
    { key: "financial_institution_number", label: "Financial institution number", type: "text", placeholder: "3 digits", pattern: /^\d{3}$/, error: "Financial institution number must be 3 digits." },
    { key: "cpp_qpp_election_status", label: "CPT30 CPP/QPP election", type: "select", upper: true, choices: ["ACTIVE", "STOPPED"] },
    { key: "cpp_election_effective_date", label: "CPP/QPP election effective date", type: "date", pattern: /^\d{4}-\d{2}-\d{2}$/, error: "Election effective date must be in YYYY-MM-DD format." },
    { key: "remote_work_agreement", label: "Full-time remote work agreement", type: "select", choices: ["true", "false", "True", "False"] },
    { key: "remote_attachment_province", label: "Remote attachment province", type: "select", upper: true, choices: ["ON", "QC", "BC", "AB", "MB", "SK", "NS", "NB", "NL", "PE", "YT", "NT", "NU"] },
    { key: "remote_agreement_effective_from", label: "Remote agreement effective from", type: "date", pattern: /^\d{4}-\d{2}-\d{2}$/, error: "Remote agreement effective date must be in YYYY-MM-DD format." },
  ],
  DE: [
    { key: "steuer_id", label: "Steuer-ID", type: "text", placeholder: "11 digits", required: true, strip: " ", pattern: /^\d{11}$/, error: "Steuer-ID must be exactly 11 digits." },
    { key: "rv_nummer", label: "RV-Nummer", type: "text", placeholder: "12 characters", upper: true, strip: " ", pattern: /^\d{8}[A-Z]\d{3}$/, error: "RV-Nummer must be 12 characters (8 digits, 1 letter, 3 digits)." },
    { key: "steuerklasse", label: "Steuerklasse", type: "select", required: true, upper: true, choices: ["I", "II", "III", "IV", "V", "VI"] },
    { key: "krankenkasse", label: "Krankenkasse", type: "text", required: true },
    { key: "iban", label: "IBAN", type: "text", placeholder: "DE + 20 digits", required: true, upper: true, strip: " ", pattern: /^DE\d{20}$/, error: "German IBAN must be DE followed by 20 digits." },
    { key: "bic", label: "BIC", type: "text", upper: true, strip: " ", pattern: /^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$/, error: "BIC must be 8 or 11 characters." },
  ],
};

// Every jurisdiction's compliance field, flattened into one list — used to
// build the wide bulk-import template/export sheet (one column per field,
// across every country) so the two never drift out of sync.
export const COMPLIANCE_SPECS = Object.entries(COUNTRY_FIELD_SPECS).flatMap(([country, specs]) =>
  specs.map((spec) => ({ ...spec, country }))
);

// Column headers carry a "(CC)" suffix purely so a human scanning 30+
// columns can tell them apart at a glance — the bulk-import parser's
// normalizeHeader() strips parenthetical content before matching, so the
// suffix never affects round-tripping an exported/re-uploaded sheet.
export function complianceColumnHeader(spec) {
  return `${spec.label} (${spec.country})`;
}

// Mirrors the server's Strategy.validate() (employee_validation.py) so the
// bulk-import preview and EmployeeForm show the same failure causes the
// API would return. Order of checks matches the server exactly: clean →
// strip_chars → uppercase → choices → pattern. Returns a list of messages;
// empty means valid. The server remains authoritative and re-validates.
export function validateComplianceFields(countryCode, complianceFields) {
  const countryName = COUNTRIES.find((c) => c.code === countryCode)?.name || countryCode;
  const errors = [];
  for (const spec of COUNTRY_FIELD_SPECS[countryCode] || []) {
    let raw = complianceFields?.[spec.key];
    if (raw === undefined || raw === null) raw = "";
    raw = String(raw).trim();
    if (!raw) {
      if (spec.required) errors.push(`${spec.label} is required for ${countryName} employees.`);
      continue;
    }
    if (spec.strip) {
      for (const ch of spec.strip) raw = raw.split(ch).join("");
    }
    if (spec.upper) raw = raw.toUpperCase();
    if (spec.choices && !spec.choices.includes(raw)) {
      errors.push(`${spec.label} must be one of: ${spec.choices.join(", ")} (got "${raw}").`);
      continue;
    }
    if (spec.pattern && !spec.pattern.test(raw)) {
      errors.push(`${spec.error} (got "${raw}")`);
    }
  }
  return errors;
}
