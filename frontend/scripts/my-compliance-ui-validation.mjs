#!/usr/bin/env node
/**
 * ZP-MY-ENG-001 (Malaysia) frontend validation.
 *
 * Phase 0: the NRIC check in countryFieldSpecs.js must agree with the backend
 * (employee_validation.py my_nric_is_valid and the vectors in
 * backend/tests/test_malaysia_scaffold.py), and the Malaysia schema / currency
 * / bank wiring must mirror the backend. Later phases add their own checks
 * here. Does not import .jsx (the Vite graph OOMs on this machine).
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { COUNTRIES, COUNTRY_FIELD_SPECS, DUPLICATE_ID_FIELDS, myNricIsValid }
  from "../src/modules/payroll/Payroll_Employees/countryFieldSpecs.js";
import { getCountryNameFromJurisdictionCode, getJurisdictionCode, getJurisdictionTaxFields }
  from "../src/utils/jurisdictionTax.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(__dirname, "..", "src");
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

// Same vectors as backend/tests/test_malaysia_scaffold.py (synthetic numbers).
const VALID_NRIC = ["900101145678", "000229105555", "880531-08-1234", "990101 01 0001"];
const INVALID_NRIC = ["900101005678", "901301145678", "900230145678", "010229145678", "90010114567",
  "9001011456789", "90010114567A", "", null];

check("NRIC accepts the backend's valid vectors", () => {
  VALID_NRIC.forEach((v) => assert(myNricIsValid(v), `${v} should be valid`));
});
check("NRIC rejects the backend's invalid vectors", () => {
  INVALID_NRIC.forEach((v) => assert(!myNricIsValid(v), `${v} should be invalid`));
});
check("Malaysia employee field specs mirror MYEmployeeValidation", () => {
  const keys = COUNTRY_FIELD_SPECS.MY.map((s) => s.key);
  assert(JSON.stringify(keys) === JSON.stringify(["passport_number", "swift_bic", "bank_account"]), keys.join(","));
  ["national_id", "nric", "tin", "tax_number", "epf_no", "socso_no"].forEach((k) =>
    assert(!keys.includes(k), `${k} is vault-only`));
  const bic = COUNTRY_FIELD_SPECS.MY.find((s) => s.key === "swift_bic");
  assert(bic.pattern.test("MBBEMYKL") && bic.pattern.test("MBBEMYKLXXX") && !bic.pattern.test("MBBEMY"), "BIC");
  assert(COUNTRY_FIELD_SPECS.MY.every((s) => !/\$\{|got/.test(s.error)), "errors must not echo the value");
  assert(COUNTRIES.some((c) => c.code === "MY" && c.name === "Malaysia"), "MY missing from COUNTRIES");
  assert(DUPLICATE_ID_FIELDS.MY === "passport_number", "duplicate field mismatch");
});
check("jurisdiction schema mirrors core/jurisdiction.py (employer references only)", () => {
  ["Malaysia", "malaysia", "MYS", "Persekutuan Malaysia", "Federation of Malaysia", "MY"].forEach((v) =>
    assert(getJurisdictionCode(v) === "MY", `${v} did not resolve to MY`));
  assert(getJurisdictionCode("Malaysian") === "", "unknown name resolved");
  const fields = getJurisdictionTaxFields("MY");
  assert(JSON.stringify(fields.map((f) => f.key)) ===
    JSON.stringify(["hasil_employer_no", "epf_employer_no", "perkeso_employer_code", "hrd_registration_no"]), "keys");
  fields.forEach((f) => assert(new RegExp(f.pattern).test(f.example), `${f.key} example fails its pattern`));
  assert(!fields.some((f) => /nric|passport|member/i.test(f.key)), "employee identifiers must not be org fields");
  assert(getCountryNameFromJurisdictionCode("MY") === "Malaysia", "code -> name");
});
check("bare 'my' is never a free-text alias (ordinary English word)", () => {
  const source = read("utils/jurisdictionTax.js");
  assert(!/^\s*my:\s*"MY"/m.test(source), "bare my alias found");
});
check("MYR currency and SWIFT/account routing are wired", () => {
  const currency = read("utils/currency.js");
  assert(/MY: "MYR"/.test(currency) && /Malaysia: "MYR"/.test(currency), "MY -> MYR map");
  assert(/MYR: \{ code: 'MYR'.*locale: 'ms-MY'/.test(currency), "MYR master entry");
  const bank = read("modules/payroll/Payroll_Employees/bankFieldsFor.js");
  assert(/"PL", "MY"\]/.test(bank) && /MY: \["swift_bic", "bank_account"\]/.test(bank) && /MY: "SWIFT \/ Account"/.test(bank),
    "bank routing");
});

if (failures.length) {
  console.error(`my-compliance-ui-validation: ${failures.length} failed, ${passed} passed`);
  failures.forEach((f) => console.error(`  - ${f}`));
  process.exit(1);
}
console.log(`my-compliance-ui-validation: ${passed} checks passed`);
