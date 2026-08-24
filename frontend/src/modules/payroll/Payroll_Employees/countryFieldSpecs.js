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
    { key: "aba_routing_number", label: "ABA routing number", type: "text", placeholder: "9 digits", pattern: /^\d{9}$/, error: "ABA routing number must be exactly 9 digits." },
    { key: "state_tax_jurisdiction", label: "State tax jurisdiction", type: "text", placeholder: "e.g. CA", required: true, upper: true, pattern: /^[A-Z]{2}$/, error: "State tax jurisdiction must be a 2-letter state code (e.g. CA, NY)." },
    // Reciprocity (backend: service.py's _resolve_us_reciprocity) — only
    // meaningfully different from state_tax_jurisdiction (work state) for a
    // genuine multi-state commuter, e.g. lives in PA, works in NJ. All
    // optional: leaving these blank is the same as today's behavior for
    // every employee whose residence and work state match.
    { key: "residence_state", label: "Residence state (if different from work state)", type: "text", placeholder: "e.g. PA", upper: true, pattern: /^[A-Z]{2}$/, error: "Residence state must be a 2-letter state code (e.g. PA)." },
    { key: "reciprocity_certificate_on_file", label: "Reciprocity certificate on file", type: "select", choices: ["true", "false", "True", "False"] },
    { key: "reciprocity_certificate_expiry", label: "Reciprocity certificate expiry", type: "date", pattern: /^\d{4}-\d{2}-\d{2}$/, error: "Certificate expiry must be in YYYY-MM-DD format." },
    // Locality (backend: service.py's get_locality_rate) — only meaningful
    // once Tax Ops has entered a matching rate in Super Admin > Compliance >
    // United States > Locality Rates. Optional free text: no format is
    // enforced since real-world locality codes vary (county FIPS, municipal
    // short codes, PSD codes).
    { key: "work_locality", label: "Work locality code (county/municipal/school-district)", type: "text", placeholder: "e.g. PHILADELPHIA" },
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
    { key: "help_stsl_debt", label: "HELP/STSL debt", type: "select", choices: ["true", "false"] },
    { key: "super_fund_usi", label: "Super fund USI", type: "text", upper: true, pattern: /^[A-Z0-9]{8,14}$/, error: "Super fund USI looks incorrect." },
    { key: "super_member_number", label: "Super member number", type: "text", pattern: /^[A-Za-z0-9]{1,20}$/, error: "Member number looks incorrect." },
    { key: "bsb_code", label: "BSB code", type: "text", placeholder: "6 digits", required: true, strip: "- ", pattern: /^\d{6}$/, error: "BSB code must be 6 digits (e.g. 123456 or 123-456)." },
  ],
  CA: [
    { key: "sin", label: "SIN", type: "text", placeholder: "9 digits", required: true, strip: "- ", pattern: /^\d{9}$/, error: "SIN must be 9 digits (e.g. 123-456-789)." },
    { key: "td1_claim_amount", label: "TD1 claim amount", type: "text", pattern: /^\d+(\.\d{1,2})?$/, error: "TD1 claim amount must be a number." },
    { key: "province", label: "Province of employment", type: "select", required: true, upper: true, choices: ["ON", "QC", "BC", "AB", "MB", "SK", "NS", "NB", "NL", "PE", "YT", "NT", "NU"] },
    { key: "transit_number", label: "Bank transit number", type: "text", placeholder: "5 digits", pattern: /^\d{5}$/, error: "Transit number must be 5 digits." },
    { key: "financial_institution_number", label: "Financial institution number", type: "text", placeholder: "3 digits", pattern: /^\d{3}$/, error: "Financial institution number must be 3 digits." },
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
