#!/usr/bin/env node
/**
 * ZP-BE-ENG-001 (Belgium) frontend validation.
 *
 * Phase 1: the Belgium currency / label / tax-schema / flag / employee-field /
 * bank wiring must exist and mirror the backend (core/jurisdiction.py
 * JURISDICTION_TAX_SCHEMAS.BE and its aliases, bank_routing.py, and
 * employee_validation.py BEEmployeeValidation). No routes, pages or Super
 * Admin UI exist yet. Later phases add their own checks here. Does not import
 * .jsx (the Vite graph OOMs on this machine).
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { COUNTRIES, COUNTRY_FIELD_SPECS } from "../src/modules/payroll/Payroll_Employees/countryFieldSpecs.js";
import { getCurrencyForJurisdiction } from "../src/utils/currency.js";
import { getPayrollLabels } from "../src/utils/jurisdictionLabels.js";
import { getCountryNameFromJurisdictionCode, getJurisdictionCode, getJurisdictionTaxFields }
  from "../src/utils/jurisdictionTax.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(__dirname, "..", "src");
const BACKEND_CORE = resolve(__dirname, "..", "..", "backend", "app", "core", "jurisdiction.py");
const read = (path) => readFileSync(resolve(SRC, path), "utf-8");

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

const ALIASES = ["Belgium", "belgique", "België", "belgie", "Belgien", "Kingdom of Belgium", "Royaume de Belgique",
  "Koninkrijk België", "BEL"];

check("BE -> EUR in the currency code map", () => {
  assert(getCurrencyForJurisdiction("BE")?.code === "EUR", "BE should resolve to EUR");
  assert(/^ {2}BE: "EUR",\r?$/m.test(read("utils/currency.js")), "BE entry in the code map");
});

check("Belgian payroll labels are obligation-specific, never one all-in rate", () => {
  const labels = getPayrollLabels("BE");
  assert(labels.incomeTax === "Professional withholding (précompte professionnel / bedrijfsvoorheffing)",
    `income tax label: ${labels.incomeTax}`);
  assert(labels.employerEsi === "ONSS/RSZ (Employer)", `employer label: ${labels.employerEsi}`);
  assert(!/\d+(\.\d+)?\s*%/.test(JSON.stringify(labels)), "no rate inside a label");
});

check("BE tax schema mirrors the backend fields", () => {
  const fields = getJurisdictionTaxFields("BE");
  assert(Array.isArray(fields) && fields.length === 2, "two BE fields");
  const keys = fields.map((f) => f.key);
  assert(keys[0] === "enterprise_number" && keys[1] === "onss_employer_number", `keys: ${keys}`);
  assert(fields.find((f) => f.primary)?.key === "enterprise_number", "enterprise_number is primary");
  const backend = readFileSync(BACKEND_CORE, "utf-8");
  fields.forEach((f) => {
    assert(backend.includes(`"pattern": r"${f.pattern}"`), `backend pattern for ${f.key} must match ${f.pattern}`);
    assert(backend.includes(`"example": "${f.example}"`), `backend example for ${f.key} must match`);
  });
});

check("every Belgium alias resolves to BE; the bare 'be' is not an alias", () => {
  ALIASES.forEach((a) => assert(getJurisdictionCode(a) === "BE", `${a} should resolve to BE`));
  assert(getCountryNameFromJurisdictionCode("BE") === "Belgium", "BE -> Belgium");
  const source = read("utils/jurisdictionTax.js");
  assert(!/^\s*be: "BE"/m.test(source) && !/^\s*"be": "BE"/m.test(source), "no bare be alias");
  const backend = readFileSync(BACKEND_CORE, "utf-8");
  assert(!/^\s*"be": "BE"/m.test(backend), "no bare be alias in the backend either");
});

check("Belgium flag is registered", () => {
  const flag = read("components/jurisdiction/CountryFlag.jsx");
  assert(/function Belgium\(\)/.test(flag) && /BE: Belgium/.test(flag), "flag component + FLAGS entry");
});

check("Belgian employee fields are IBAN only (NISS is vault-only)", () => {
  assert(COUNTRIES.some((c) => c.code === "BE" && c.name === "Belgium"), "BE in COUNTRIES");
  const spec = COUNTRY_FIELD_SPECS.BE;
  assert(Array.isArray(spec) && spec.length === 1 && spec[0].key === "iban", "BE spec is exactly [iban]");
  assert(spec[0].pattern.test("BE68539007547034") && !spec[0].pattern.test("PL61109010140000071219812874"),
    "BE IBAN pattern");
  const nissLike = /niss|insz|national/i;
  assert(!spec.some((f) => nissLike.test(f.key)), "no NISS field");
});

check("Belgium routes salary by IBAN over SEPA", () => {
  const bank = read("modules/payroll/Payroll_Employees/bankFieldsFor.js");
  assert(/BANK_ROUTING_COUNTRIES = \[[^\]]*"BE"[^\]]*\]/.test(bank), "BE in BANK_ROUTING_COUNTRIES");
  assert(/^ {2}BE: "SEPA",\r?$/m.test(bank), "payment mode SEPA");
  assert(/^ {2}BE: "IBAN",\r?$/m.test(bank), "BTF label IBAN");
  assert(/^ {2}BE: \["iban"\],\r?$/m.test(bank), "banking compliance keys");
});

// Phase 3B added the Super Admin console: its routes and pages are validated by
// scripts/be-console-ui-validation.mjs.
check("the Belgium console page is wired (Phase 3B)", () => {
  assert(/compliance\/belgium/.test(read("App.jsx")), "BE route");
  assert(/BE: "belgium"/.test(read("pages/JurisdictionCompliance/index.js")), "BE compliance slug");
});

if (failures.length) {
  console.error(`Belgium UI validation: ${failures.length} failure(s), ${passed} passed`);
  failures.forEach((f) => console.error(`  ✗ ${f}`));
  process.exit(1);
}
console.log(`Belgium UI validation: ${passed} checks passed`);
