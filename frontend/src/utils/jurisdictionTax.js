// Jurisdiction-aware business tax/registration fields for the Register Page
// and the Company Compliance Details tab.
//
// Mirrors backend/app/core/jurisdiction.py — the backend is the canonical
// reference (exposed via GET /api/jurisdictions/tax-schemas); this local copy
// lets the Register Page render the dynamic fields instantly and validate on
// the client without a round-trip. Keep the two in sync when adding countries.

export const JURISDICTION_TAX_SCHEMAS = {
  IN: {
    label: "GSTIN / PAN / CIN",
    fields: [
      { key: "gstin", label: "GSTIN", pattern: "^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$", example: "36AAACI1234F1Z9", primary: true },
      { key: "pan", label: "PAN", pattern: "^[A-Z]{5}[0-9]{4}[A-Z]{1}$", example: "AAACI1234F", primary: false },
      { key: "cin", label: "CIN", pattern: "^[L|U][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$", example: "U72200TG2020PTC123456", primary: false },
    ],
  },
  US: {
    label: "EIN / State Tax ID",
    fields: [
      { key: "ein", label: "EIN", pattern: "^\\d{2}-\\d{7}$", example: "84-1234567", primary: true },
      { key: "state_tax_id", label: "State Tax ID", pattern: "^\\d{2,15}$", example: "123456789", primary: false },
    ],
  },
  UK: {
    label: "Company Registration Number (CRN) / VAT",
    fields: [
      { key: "crn", label: "Company Registration Number (CRN)", pattern: "^[0-9]{8}$|^[A-Z]{2}[0-9]{6}$", example: "12345678", primary: true },
      { key: "vat_number", label: "VAT Number", pattern: "^\\s*(GB\\s*)?[0-9]{3}\\s?[0-9]{4}\\s?[0-9]{2}\\s*$", example: "GB 123 4567 89", primary: false },
    ],
  },
  DE: {
    label: "USt-IdNr / Steuernummer / HRB",
    fields: [
      { key: "ust_idnr", label: "USt-IdNr.", pattern: "^DE[0-9]{9}$", example: "DE312345678", primary: true },
      { key: "steuernummer", label: "Steuernummer", pattern: "^[0-9]{2,4}/[0-9]{3,5}/[0-9]{4,5}$", example: "143/123/45678", primary: false },
      { key: "hrb", label: "HRB", pattern: "^HRB\\s?[0-9]{1,6}$", example: "HRB 123456", primary: false },
    ],
  },
  FR: {
    label: "SIREN / SIRET / TVA intracommunautaire",
    fields: [
      { key: "siren", label: "SIREN", pattern: "^\\d{9}$", example: "552100554", primary: true },
      { key: "siret", label: "SIRET", pattern: "^\\d{14}$", example: "55210055400021", primary: false },
      { key: "vat_intracom", label: "TVA intracommunautaire", pattern: "^FR[0-9]{11}$", example: "FR23392106162", primary: false },
    ],
  },
  IE: {
    label: "Revenue PAYE / PRSI Registration / ROS Sub-User",
    fields: [
      { key: "paye_registration_number", label: "Revenue PAYE Registration Number", pattern: "^[0-9A-Z]{6,12}$", example: "1234567", primary: true },
      { key: "prsi_registration_number", label: "PRSI Registration Number", pattern: "^[0-9A-Z]{6,12}$", example: "7654321", primary: false },
      { key: "ros_sub_user_reference", label: "ROS Sub-User Reference", pattern: "^[A-Za-z0-9._-]{3,64}$", example: "ZOIKO-IE-ROS-01", primary: false },
      { key: "eircode", label: "Eircode", pattern: "^[A-Z][0-9]{2}\\s?[A-Z0-9]{4}$", example: "D02 AF30", primary: false },
    ],
  },
  AU: {
    label: "ABN / ACN",
    fields: [
      { key: "abn", label: "ABN", pattern: "^\\d{2}\\s?\\d{3}\\s?\\d{3}\\s?\\d{3}$", example: "51 824 753 556", primary: true },
      { key: "acn", label: "ACN", pattern: "^\\d{3}\\s?\\d{3}\\s?\\d{3}$", example: "008 672 000", primary: false },
    ],
  },
  // Hong Kong — mirrors backend core/jurisdiction.py JURISDICTION_TAX_SCHEMAS.HK
  // (the backend re-validates every write and stays authoritative).
  HK: {
    label: "BR Number / IRD Employer's File Number",
    fields: [
      { key: "br_number", label: "Business Registration Number", pattern: "^\\d{8}$", example: "12345678", primary: true },
      { key: "ird_employer_file_number", label: "IRD Employer's File Number", pattern: "^\\d[A-Z0-9]{2}-?\\d{6,8}$", example: "6A1-12345678", primary: false },
      { key: "empf_employer_account", label: "eMPF employer account number", pattern: "^[A-Za-z0-9-]{4,30}$", example: "ER-12345678", primary: false },
      { key: "mpf_scheme_name", label: "MPF scheme (trustee) the employer participates in", pattern: "^[A-Za-z0-9 .,'&()/-]{2,100}$", example: "Example MPF Master Trust", primary: false },
      { key: "empf_submission_channel", label: "eMPF submission channel", pattern: "^(EMPF_PLATFORM_MANUAL|NOT_CONFIGURED)$", example: "EMPF_PLATFORM_MANUAL", primary: false, options: ["EMPF_PLATFORM_MANUAL", "NOT_CONFIGURED"] },
      { key: "ird_filing_channel", label: "IRD employer's return filing channel", pattern: "^(IRD_ETAX_MANUAL|PAPER|NOT_CONFIGURED)$", example: "IRD_ETAX_MANUAL", primary: false, options: ["IRD_ETAX_MANUAL", "PAPER", "NOT_CONFIGURED"] },
      { key: "ec_insurance_policy_number", label: "Employees' Compensation insurance policy number", pattern: "^[A-Za-z0-9/-]{3,40}$", example: "EC-2026-000123", primary: false },
      { key: "ec_insurance_expiry", label: "Employees' Compensation insurance expiry (YYYY-MM-DD)", pattern: "^\\d{4}-\\d{2}-\\d{2}$", example: "2027-06-30", primary: false },
      { key: "pics_published", label: "Employment Personal Information Collection Statement issued", pattern: "^(YES|NO)$", example: "NO", primary: false, options: ["YES", "NO"] },
      { key: "bank_workflow_validated", label: "Salary bank-payment workflow validated", pattern: "^(YES|NO)$", example: "NO", primary: false, options: ["YES", "NO"] },
    ],
  },
};

const COUNTRY_NAME_TO_CODE = {
  india: "IN",
  "united states": "US",
  usa: "US",
  "united kingdom": "UK",
  uk: "UK",
  germany: "DE",
  australia: "AU",
  "hong kong": "HK",
  france: "FR",
  ireland: "IE",
};

const CODE_TO_COUNTRY_NAME = {
  IN: "India",
  US: "United States",
  UK: "United Kingdom",
  DE: "Germany",
  AU: "Australia",
  HK: "Hong Kong",
  FR: "France",
  IE: "Ireland",
};

export function getJurisdictionCode(country) {
  if (!country) return "";
  const value = String(country).trim();
  const upper = value.toUpperCase();
  if (JURISDICTION_TAX_SCHEMAS[upper]) return upper;
  return COUNTRY_NAME_TO_CODE[value.toLowerCase()] || "";
}

export function getJurisdictionTaxSchema(country) {
  const code = getJurisdictionCode(country);
  return code ? JURISDICTION_TAX_SCHEMAS[code] : null;
}

export function getJurisdictionTaxFields(country) {
  const schema = getJurisdictionTaxSchema(country);
  return schema ? schema.fields : [];
}

export function getCountryNameFromJurisdictionCode(code) {
  if (!code) return "";
  return CODE_TO_COUNTRY_NAME[String(code).toUpperCase()] || "";
}

export function isJurisdictionTaxValueValid(field, value) {
  if (!value) return true; // optional — blank always passes
  try {
    return new RegExp(field.pattern).test(String(value).trim());
  } catch {
    return true; // never block submission on a malformed pattern
  }
}

// Returns [{ key, field, message }] for every value that fails its pattern.
export function validateJurisdictionTaxIds(country, values) {
  const fields = getJurisdictionTaxFields(country);
  const errors = [];
  if (!fields.length || !values) return errors;
  for (const field of fields) {
    const value = values[field.key];
    if (!value) continue;
    if (!isJurisdictionTaxValueValid(field, value)) {
      errors.push({
        key: field.key,
        field,
        message: `${field.label} is not in a valid format (e.g. ${field.example}).`,
      });
    }
  }
  return errors;
}

// Best-effort extraction of the primary identifier (mirrors the backend's
// primary_tax_value) so the legacy single tax_no payload field stays filled.
export function primaryTaxValue(country, values) {
  const fields = getJurisdictionTaxFields(country);
  if (!fields.length || !values) return "";
  const primary = fields.find((f) => f.primary) || fields[0];
  if (values[primary.key]) return String(values[primary.key]).trim();
  for (const f of fields) {
    if (values[f.key]) return String(values[f.key]).trim();
  }
  return "";
}
