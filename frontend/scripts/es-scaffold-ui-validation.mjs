#!/usr/bin/env node
/**
 * Spain (ZP-ES-ENG-001, docs/spain) frontend validation.
 *
 * Spain is an ordinary country: registration opens once an Active ES pack with
 * rates exists, employee facts use the standard compliance-fields path, and
 * the two Super Admin workspaces (Compliance and Report Templates) have real
 * pages. This script never imports .jsx — it checks page/route wiring by
 * reading the source, and imports the plain-JS field specs directly.
 */
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { COUNTRIES, COUNTRY_FIELD_SPECS, DUPLICATE_ID_FIELDS, normalizeComplianceFields, validateComplianceFields }
  from "../src/modules/payroll/Payroll_Employees/countryFieldSpecs.js";
import { getCurrencyForJurisdiction } from "../src/utils/currency.js";
import { getCountryNameFromJurisdictionCode, getJurisdictionCode, getJurisdictionTaxFields }
  from "../src/utils/jurisdictionTax.js";

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

const ALIASES = ["Spain", "spain", "España", "Espana", "Kingdom of Spain", "Reino de España"];
const ES_IBAN = "ES9121000418450200051332";
const FIELDS = ["nif_nie", "naf_nuss", "contract_type", "contract_end_date", "short_contract_exception",
  "contribution_group", "work_pattern", "extra_pay_policy", "extra_pay_annual_amount", "extra_pay_months",
  "overtime_kind", "at_ep_rate", "family_situation", "children_count", "children_under_3", "ascendants_count",
  "disability_degree", "irpf_voluntary_rate", "iban"];
const BASE = { contract_type: "INDEFINITE", contribution_group: "5", extra_pay_policy: "PRORATED_12" };

check("ES -> EUR in the currency code map", () => {
  assert(getCurrencyForJurisdiction("ES")?.code === "EUR", "ES should resolve to EUR");
});

check("Spain's income-tax line is labelled IRPF", () => {
  const labels = read("utils/jurisdictionLabels.js");
  assert(/^\s*ES: "IRPF \(retención\)",/m.test(labels), "ES IRPF label");
  assert(!/NO_PAYROLL_INCOME_TAX = new Set\(\[[^\]]*"ES"/.test(labels), "Spain has income tax");
});

check("ES tax schema mirrors the backend fields", () => {
  const fields = getJurisdictionTaxFields("ES");
  assert(Array.isArray(fields) && fields.length === 2, "two ES fields");
  assert(fields.map((f) => f.key).join(",") === "nif,ccc", `keys: ${fields.map((f) => f.key)}`);
  assert(fields.find((f) => f.primary)?.key === "nif", "NIF is primary");
  const backend = readBackend("core/jurisdiction.py");
  fields.forEach((f) => {
    assert(backend.includes(`"pattern": r"${f.pattern}"`), `backend pattern for ${f.key} must match ${f.pattern}`);
    assert(backend.includes(`"example": "${f.example}"`), `backend example for ${f.key} must match`);
  });
});

check("every Spain alias resolves to ES; the bare 'es' is not an alias", () => {
  ALIASES.forEach((a) => assert(getJurisdictionCode(a) === "ES", `${a} should resolve to ES`));
  assert(getJurisdictionCode("ES") === "ES", "the code itself");
  assert(getCountryNameFromJurisdictionCode("ES") === "Spain", "ES -> Spain");
  const source = read("utils/jurisdictionTax.js");
  assert(!/^\s*es: "ES"/m.test(source) && !/^\s*"es": "ES"/m.test(source), "no bare es alias");
  const backend = readBackend("core/jurisdiction.py");
  assert(!/^\s*"es": "ES"/m.test(backend), "no bare es alias in the backend either");
  assert(backend.includes('"ES": "Spain"'), "backend display name");
});

check("Spain flag is registered", () => {
  const flag = read("components/jurisdiction/CountryFlag.jsx");
  assert(/function Spain\(\)/.test(flag) && /ES: Spain/.test(flag), "flag component + FLAGS entry");
});

check("registration offers Spain with its regions", () => {
  const regions = read("utils/registrationRegions.js");
  assert(/"Spain"/.test(regions.split("const STATES_BY_COUNTRY")[0]), "Spain in REGISTRATION_COUNTRIES");
  assert(/"Community of Madrid"/.test(regions) && /"Catalonia"/.test(regions), "Spanish regions present");
  assert(readBackend("core/jurisdiction.py").includes('    "Spain",\n'), "backend registration list");
});

check("Spain employee fields mirror ESEmployeeValidation", () => {
  assert(COUNTRIES.some((c) => c.code === "ES" && c.name === "Spain"), "ES in COUNTRIES");
  const spec = COUNTRY_FIELD_SPECS.ES;
  assert(Array.isArray(spec), "ES spec exists");
  assert(spec.map((f) => f.key).join(",") === FIELDS.join(","), `keys: ${spec.map((f) => f.key)}`);
  const backend = readBackend("modules/payroll/employee_validation.py");
  FIELDS.forEach((key) => assert(backend.includes(`"${key}": {`), `backend field ${key}`));
  ["contract_type", "contribution_group", "extra_pay_policy"].forEach((key) =>
    assert(spec.find((f) => f.key === key).required === true, `${key} required`));
  assert(DUPLICATE_ID_FIELDS.ES === "nif_nie", "NIF/NIE is the duplicate-checked identifier");
  const iban = spec.find((f) => f.key === "iban");
  assert(iban.pattern.test(ES_IBAN) && iban.check(ES_IBAN) && !iban.check(`${ES_IBAN.slice(0, -1)}3`),
    "ES IBAN pattern and check digits");
  const nif = spec.find((f) => f.key === "nif_nie");
  assert(nif.check("12345678Z") && nif.check("X1234567L") && !nif.check("12345678A"), "NIF/NIE check letter");
});

check("front-end combination validation mirrors the backend rules", () => {
  assert(validateComplianceFields("ES", { ...BASE, nif_nie: "12345678Z", iban: ES_IBAN }).length === 0,
    "valid Spanish employee has no errors");
  const normalized = normalizeComplianceFields("ES", { ...BASE, contract_type: "indefinido" });
  assert(normalized.contract_type === "INDEFINITE", "contract alias");
  const errors = (fields) => validateComplianceFields("ES", { ...BASE, ...fields });
  assert(errors({ contract_type: "TEMPORARY" }).some((e) => e.includes("contract_end_date")), "temp needs end date");
  assert(errors({ short_contract_exception: "YES" }).some((e) => e.includes("short_contract_exception")),
    "exception only for temporary");
  assert(errors({ extra_pay_policy: "SEPARATE_14" }).some((e) => e.includes("extra_pay_annual_amount")),
    "14 pays need the amount");
  assert(errors({ extra_pay_months: "6,13" }).some((e) => e.includes("between 1 and 12")), "months 1-12");
  assert(errors({ children_count: "1", children_under_3: "2" }).some((e) => e.includes("children_under_3")),
    "children under 3");
  assert(errors({ nif_nie: "12345678A" }).length === 1, "wrong NIF letter refused");
  assert(errors({}).length === 0 && validateComplianceFields("ES", {}).length === 3, "three required facts");
});

check("Spain routes salary by IBAN, payment mode SEPA", () => {
  const bank = read("modules/payroll/Payroll_Employees/bankFieldsFor.js");
  assert(/BANK_ROUTING_COUNTRIES = \[[^\]]*"ES"[^\]]*\]/.test(bank), "ES in BANK_ROUTING_COUNTRIES");
  assert(/"ZA", "PL", "MY"\];/.test(bank), "the Poland/Malaysia tail pin is kept");
  assert(/^ {2}ES: "SEPA",\r?$/m.test(bank), "payment mode SEPA");
  assert(/^ {2}ES: "IBAN",\r?$/m.test(bank), "BTF label IBAN");
  assert(/^ {2}ES: \["iban"\],\r?$/m.test(bank), "banking compliance keys");
});

check("Super Admin compliance and report-template routes exist", () => {
  const complianceIndex = read("pages/JurisdictionCompliance/index.js");
  const reportIndex = read("pages/ReportTemplates/index.js");
  const statutoryIndex = read("pages/JurisdictionStatutory/index.js");
  const app = read("App.jsx");
  assert(/ES: "spain"/.test(complianceIndex), "ES compliance slug");
  assert(/ES: "spain"/.test(reportIndex), "ES report-template slug");
  assert(/"AE", "ES"\]\.includes\(code\)/.test(statutoryIndex), "no separate Statutory Rates card for Spain");
  assert(app.includes("/super-admin/compliance/spain"), "compliance route");
  assert(app.includes("/super-admin/report-templates/spain") && app.includes("/super-admin/report-templates/spain/:jurisdiction"),
    "report-template routes");
  assert(existsSync(resolve(SRC, "pages/JurisdictionCompliance/ESCompliancePage.jsx")), "ESCompliancePage.jsx");
  assert(existsSync(resolve(SRC, "pages/ReportTemplates/ESReportTemplatesPage.jsx")), "ESReportTemplatesPage.jsx");
  assert(/country="ES" countryName="Spain"/.test(read("pages/JurisdictionCompliance/ESCompliancePage.jsx")),
    "compliance page renders the ES layout");
});

if (failures.length) {
  console.error(`Spain UI validation: ${failures.length} failure(s), ${passed} passed`);
  failures.forEach((f) => console.error(`  ✗ ${f}`));
  process.exit(1);
}
console.log(`Spain UI validation: ${passed} checks passed`);
