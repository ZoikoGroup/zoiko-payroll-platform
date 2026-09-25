// Frontend mirror of backend/app/modules/payroll/bank_routing.py
// (ZP-MJR-2026-001) — the single client-side source of truth for per-country
// salary-payment routing fields, labels, and payment rails:
//
//   IN -> IFSC      UK -> Sort Code      US -> ABA routing number
//   CA -> Transit + Institution Number   DE -> IBAN + BIC   AU -> BSB
//
// Storage stays exactly as on the backend:
//   * India keeps its dedicated `ifscCode` employee column (a real
//     PayrollEmployee field), written via the EmployeeForm/bulk-import.
//   * Every other country keeps its codes in `complianceFields` (the
//     same JSON the backend validates via employee_validation.py and
//     snapshots onto each payslip).
//
// The per-country field *definitions* (label/pattern/error/required) for
// the non-India routing codes already live in countryFieldSpecs.js (which
// mirrors employee_validation.py); this module tags precisely which of
// those are banking/routing fields and composes them with India's
// dedicated IFSC so the Form/import/export all use one shape.

import { COUNTRY_FIELD_SPECS } from "./countryFieldSpecs";

export const BANK_ROUTING_COUNTRIES = ["IN", "UK", "US", "CA", "DE", "AU", "BB", "KY", "DO", "GY", "JM", "BS", "TT", "PR", "FR", "IE"];

// Mirrors backend bank_routing.py's PAYMENT_MODE_LABEL.
const PAYMENT_MODE_LABEL = {
  IN: "NEFT",
  UK: "BACS",
  US: "ACH",
  CA: "EFT",
  DE: "SEPA",
  AU: "Direct Entry",
  FR: "SEPA",
  IE: "SEPA",
  BB: "EFT",
  KY: "EFT",
  DO: "EFT",
  GY: "EFT",
  JM: "EFT",
  TT: "EFT",
  BS: "ACH",
  PR: "ACH",
};

// Mirrors backend bank_routing.py's BTF_ROUTING_LABEL — the canonical name
// used as the Bank Transfer File's routing column header per country. India
// stays literally "IFSC" so India bank-transfer output remains unchanged.
const BTF_ROUTING_LABEL = {
  IN: "IFSC",
  UK: "Sort Code",
  US: "ABA Routing #",
  CA: "Transit No.",
  DE: "IBAN",
  AU: "BSB",
  FR: "IBAN",
  IE: "IBAN",
  BB: "Bank/Branch Code",
  KY: "Bank/Branch Code",
  DO: "Bank/Branch Code",
  GY: "Bank/Branch Code",
  JM: "Bank/Branch Code",
  TT: "Bank/Branch Code",
  BS: "ACH Routing #",
  PR: "ACH Routing #",
};

// Mirrors backend bank_routing.py's _IN_IFSC_PATTERN + ifsc_warning().
const IN_IFSC_PATTERN = /^[A-Z]{4}0[A-Z0-9]{6}$/;

// Mirrors backend bank_routing.py's ROUTING_FIELDS — which compliance-field
// keys are the banking/routing codes for each jurisdiction.
const BANKING_COMPLIANCE_KEYS = {
  UK: ["sort_code"],
  US: ["aba_routing_number"],
  CA: ["transit_number", "financial_institution_number"],
  DE: ["iban", "bic"],
  AU: ["bsb_code"],
  FR: ["iban", "bic"],
  IE: ["iban", "bic"],
  BB: ["bank_branch_code"],
  KY: ["bank_branch_code"],
  DO: ["bank_branch_code"],
  GY: ["bank_branch_code"],
  JM: ["bank_branch_code"],
  TT: ["bank_branch_code"],
  BS: ["ach_routing_number"],
  PR: ["ach_routing_number"],
};

function normalizeCountry(country) {
  if (!country) return "";
  const code = String(country).trim().toUpperCase();
  return BANK_ROUTING_COUNTRIES.includes(code) ? code : "";
}

export function bankPaymentModeLabel(country) {
  return PAYMENT_MODE_LABEL[normalizeCountry(country)] || "Bank Transfer";
}

export function bankBtfLabel(country) {
  return BTF_ROUTING_LABEL[normalizeCountry(country)] || "Routing Code";
}

// Non-blocking advisory only — never blocks a save, mirroring the backend's
// soft (non-enforced) IFSC guidance.
export function ifscWarning(value) {
  if (!value) return null;
  if (IN_IFSC_PATTERN.test(String(value).toUpperCase())) return null;
  return "IFSC format looks incorrect (e.g. HDFC0001234) — please verify before payment.";
}

export function bankFieldsFor(country) {
  const code = normalizeCountry(country);
  if (!code) return [];
  if (code === "IN") {
    return [
      {
        key: "ifsc",
        formKey: "ifscCode",
        storage: "dedicated",
        label: "IFSC code",
        type: "text",
        upper: true,
        placeholder: "e.g. HDFC0001234",
        error: "IFSC format looks incorrect (e.g. HDFC0001234)",
      },
    ];
  }
  const keys = BANKING_COMPLIANCE_KEYS[code] || [];
  return (COUNTRY_FIELD_SPECS[code] || [])
    .filter((spec) => keys.includes(spec.key))
    .map((spec) => ({ ...spec, formKey: spec.key, storage: "compliance" }));
}

export function bankComplianceKeys(country) {
  return bankFieldsFor(country)
    .filter((field) => field.storage === "compliance")
    .map((field) => field.key);
}

// Read one routing field from either the employee object's dedicated column
// (India: `ifscCode`) or its complianceFields (every other country).
export function readRoutingField(employee, field) {
  if (field.storage === "dedicated") {
    const v = employee?.[field.formKey];
    return v === undefined || v === null ? "" : String(v);
  }
  const cf = employee?.complianceFields || {};
  const v = cf[field.formKey];
  return v === undefined || v === null ? "" : String(v);
}

// The single combined Bank Transfer File value for a country — mirrors
// backend btf_routing_value():
//   CA -> "{transit_number}-{institution}" (e.g. 12345-001)
//   DE -> "{iban} {bic}" (IBAN alone when no BIC)
//   everything else -> its single routing code.
export function combineRoutingValue(country, get) {
  const code = normalizeCountry(country);
  const fields = bankFieldsFor(code);
  if (!fields.length) return "";
  const read = (formKey) => {
    const v = get(formKey);
    return v === undefined || v === null ? "" : String(v);
  };
  if (code === "CA") {
    const transit = read("transit_number");
    const institution = read("financial_institution_number");
    if (transit && institution) return `${transit}-${institution}`;
    return transit || institution;
  }
  if (code === "DE") {
    const iban = read("iban");
    const bic = read("bic");
    if (iban && bic) return `${iban} ${bic}`;
    return iban || bic;
  }
  return read(fields[0].formKey);
}