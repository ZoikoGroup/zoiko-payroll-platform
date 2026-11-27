#!/usr/bin/env node
/**
 * United Arab Emirates (ZP-AE-ENG-001) frontend validation.
 *
 * The UAE is an ordinary country: registration opens once an Active AE pack
 * with rates exists, employee facts use the standard compliance-fields path,
 * and the two Super Admin workspaces (Compliance and Report Templates) have
 * real pages. This script never imports .jsx — it checks page/route wiring by
 * reading the source, and imports the plain-JS field specs directly.
 */
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { COUNTRIES, COUNTRY_FIELD_SPECS, normalizeComplianceFields, validateComplianceFields }
  from "../src/modules/payroll/Payroll_Employees/countryFieldSpecs.js";
import { getCurrencyForJurisdiction } from "../src/utils/currency.js";
import { getCountryNameFromJurisdictionCode, getJurisdictionCode, getJurisdictionTaxFields }
  from "../src/utils/jurisdictionTax.js";
import { hasBundledFlag } from "./country-flag-check.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(__dirname, "..", "src");
const BACKEND = resolve(__dirname, "..", "..", "backend", "app");
const read = (path) => readFileSync(resolve(SRC, path), "utf-8");
const readBackend = (path) => readFileSync(resolve(BACKEND, path), "utf-8");

let passed = 0;
const failures = [];
function check(name, fn) {
  try {
    if (fn() === false) throw new Error("assertion returned false");
    passed += 1;
  } catch (error) {
    failures.push(`${name}: ${error.message}`);
  }
}
function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const ALIASES = ["United Arab Emirates", "the united arab emirates", "UAE", "U.A.E.", "u.a.e", "The UAE", "Emirates"];
const AE_IBAN = "AE070331234567890123456";
const FIELDS = ["nationality_category", "gcc_country", "pension_scheme", "pension_contribution_salary",
  "government_support_eligible", "eos_regime", "savings_enrollment_date", "savings_enrollment_basic_wage",
  "work_pattern", "emirates_id", "iban"];

check("AE -> AED in the currency code map", () => {
  assert(getCurrencyForJurisdiction("AE")?.code === "AED", "AE should resolve to AED");
});

check("the UAE shows no payroll income-tax line", () => {
  assert(/NO_PAYROLL_INCOME_TAX = new Set\(\[[^\]]*"AE"[^\]]*\]\)/.test(read("utils/jurisdictionLabels.js")),
    "AE in NO_PAYROLL_INCOME_TAX");
});

check("AE tax schema mirrors the backend fields", () => {
  const fields = getJurisdictionTaxFields("AE");
  assert(Array.isArray(fields) && fields.length === 2, "two AE fields");
  const keys = fields.map((f) => f.key);
  assert(keys[0] === "mohre_establishment_id" && keys[1] === "gpssa_employer_number", `keys: ${keys}`);
  assert(fields.find((f) => f.primary)?.key === "mohre_establishment_id", "MOHRE establishment ID is primary");
  const backend = readBackend("core/jurisdiction.py");
  fields.forEach((f) => {
    assert(backend.includes(`"pattern": r"${f.pattern}"`), `backend pattern for ${f.key} must match ${f.pattern}`);
    assert(backend.includes(`"example": "${f.example}"`), `backend example for ${f.key} must match`);
  });
});

check("every UAE alias resolves to AE; the bare 'ae' is not an alias", () => {
  ALIASES.forEach((a) => assert(getJurisdictionCode(a) === "AE", `${a} should resolve to AE`));
  assert(getJurisdictionCode("AE") === "AE", "the code itself");
  assert(getCountryNameFromJurisdictionCode("AE") === "United Arab Emirates", "AE -> United Arab Emirates");
  const source = read("utils/jurisdictionTax.js");
  assert(!/^\s*ae: "AE"/m.test(source) && !/^\s*"ae": "AE"/m.test(source), "no bare ae alias");
  const backend = readBackend("core/jurisdiction.py");
  assert(!/^\s*"ae": "AE"/m.test(backend), "no bare ae alias in the backend either");
  assert(backend.includes('"AE": "United Arab Emirates"'), "backend display name");
});

check("UAE flag is registered", () => {
  assert(hasBundledFlag("AE"), "bundled flag-icons flag");
});

check("registration offers the UAE and the DIFC / ADGM regions", () => {
  const regions = read("utils/registrationRegions.js");
  assert(/"United Arab Emirates"/.test(regions.split("const STATES_BY_COUNTRY")[0]), "UAE in REGISTRATION_COUNTRIES");
  assert(/"Dubai – DIFC"/.test(regions) && /"Abu Dhabi – ADGM"/.test(regions), "free-zone regions present");
  const backend = readBackend("core/jurisdiction.py");
  assert(backend.includes('"United Arab Emirates",'), "backend registration list");
});

check("UAE employee fields mirror AEEmployeeValidation", () => {
  assert(COUNTRIES.some((c) => c.code === "AE" && c.name === "United Arab Emirates"), "AE in COUNTRIES");
  const spec = COUNTRY_FIELD_SPECS.AE;
  assert(Array.isArray(spec), "AE spec exists");
  assert(spec.map((f) => f.key).join(",") === FIELDS.join(","), `keys: ${spec.map((f) => f.key)}`);
  assert(!spec.some((f) => f.key === "eos_unpaid_absence_days"), "unpaid absence is derived, not a field");
  const iban = spec.find((f) => f.key === "iban");
  assert(iban.pattern.test(AE_IBAN) && iban.check(AE_IBAN) && !iban.check(`${AE_IBAN.slice(0, -1)}7`),
    "AE IBAN pattern and check digits");
  const emiratesId = spec.find((f) => f.key === "emirates_id");
  assert(emiratesId.pattern.test("784199012345671") && !emiratesId.pattern.test("78419901234567"),
    "Emirates ID pattern");
  const backend = readBackend("modules/payroll/employee_validation.py");
  assert(!backend.includes('"eos_unpaid_absence_days"'), "backend derives unpaid absence too");
});

check("front-end combination validation mirrors the backend rules", () => {
  const valid = { nationality_category: "uae national", pension_scheme: "law 57",
                  pension_contribution_salary: "15,000", government_support_eligible: "yes", iban: AE_IBAN };
  const normalized = normalizeComplianceFields("AE", valid);
  assert(normalized.nationality_category === "UAE_NATIONAL", "nationality alias");
  assert(normalized.pension_scheme === "GPSSA_LAW_57_2023", "scheme alias");
  assert(validateComplianceFields("AE", valid).length === 0, "valid UAE employee has no errors");
  const expatWithPension = validateComplianceFields("AE", { nationality_category: "EXPATRIATE",
    pension_scheme: "ADPF_NEW_MEMBER", pension_contribution_salary: "10000", eos_regime: "TRADITIONAL" });
  assert(expatWithPension.some((e) => e.includes("An expatriate has no pension_scheme")), "expatriate pension refused");
  const gccWithoutCountry = validateComplianceFields("AE", { nationality_category: "GCC_NATIONAL" });
  assert(gccWithoutCountry.some((e) => e.includes("gcc_country is required")), "GCC country required");
  const savingsWithoutFacts = validateComplianceFields("AE", { nationality_category: "EXPATRIATE", eos_regime: "SAVINGS_SCHEME" });
  assert(savingsWithoutFacts.some((e) => e.includes("savings_enrollment_date")), "savings facts required");
});

check("the UAE routes salary by IBAN, payment mode WPS", () => {
  const bank = read("modules/payroll/Payroll_Employees/bankFieldsFor.js");
  assert(/BANK_ROUTING_COUNTRIES = \[[^\]]*"AE"[^\]]*\]/.test(bank), "AE in BANK_ROUTING_COUNTRIES");
  assert(/^ {2}AE: "WPS",\r?$/m.test(bank), "payment mode WPS");
  assert(/^ {2}AE: "IBAN",\r?$/m.test(bank), "BTF label IBAN");
  assert(/^ {2}AE: \["iban"\],\r?$/m.test(bank), "banking compliance keys");
});

check("Super Admin compliance and report-template routes exist", () => {
  const complianceIndex = read("pages/JurisdictionCompliance/index.js");
  const reportIndex = read("pages/ReportTemplates/index.js");
  const app = read("App.jsx");
  assert(/AE: "united-arab-emirates"/.test(complianceIndex), "AE compliance slug");
  assert(/AE: "united-arab-emirates"/.test(reportIndex), "AE report-template slug");
  assert(app.includes("/super-admin/compliance/united-arab-emirates"), "compliance route");
  assert(app.includes("/super-admin/report-templates/united-arab-emirates"), "report-template route");
  assert(existsSync(resolve(SRC, "pages/JurisdictionCompliance/AECompliancePage.jsx")), "AECompliancePage.jsx");
  assert(existsSync(resolve(SRC, "pages/ReportTemplates/AEReportTemplatesPage.jsx")), "AEReportTemplatesPage.jsx");
});

if (failures.length) {
  console.error(`UAE UI validation: ${failures.length} failure(s), ${passed} passed`);
  failures.forEach((f) => console.error(`  ✗ ${f}`));
  process.exit(1);
}
console.log(`UAE UI validation: ${passed} checks passed`);
