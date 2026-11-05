#!/usr/bin/env node
/**
 * ZP-PL-ENG-001 (Poland) frontend validation.
 *
 * Phase 0: the identifier checks in countryFieldSpecs.js must agree with the
 * backend (employee_validation.py pl_pesel_is_valid / pl_nip_is_valid and the
 * vectors in backend/tests/test_poland_scaffold.py), and the Poland schema /
 * currency / bank wiring must mirror the backend. Later phases add their own
 * checks here. Does not import .jsx (the Vite graph OOMs on this machine).
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { COUNTRIES, COUNTRY_FIELD_SPECS, DUPLICATE_ID_FIELDS, plNipIsValid, plPeselIsValid }
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

// Same vectors as backend/tests/test_poland_scaffold.py.
const VALID_PESEL = ["44051401359", "80010101230", "02270803624", "02322900013", "00222900016", "00810101232",
  "440514 01359", "4405-1401-359"];
const INVALID_PESEL = ["44051401358", "99022900010", "44133101359", "4405140135", "4405140135A", "", null];
const NIP = [["1234563218", true], ["5261040828", true], ["526-104-08-28", true], ["5261040827", false],
  ["1234567890", false], ["123456321", false]];

check("PESEL accepts the backend's valid vectors", () => {
  VALID_PESEL.forEach((v) => assert(plPeselIsValid(v), `${v} should be valid`));
});
check("PESEL rejects the backend's invalid vectors", () => {
  INVALID_PESEL.forEach((v) => assert(!plPeselIsValid(v), `${v} should be invalid`));
});
check("NIP check digit matches the backend", () => {
  NIP.forEach(([v, ok]) => assert(plNipIsValid(v) === ok, `${v} expected ${ok}`));
});
check("Poland employee field specs mirror PLEmployeeValidation", () => {
  const keys = COUNTRY_FIELD_SPECS.PL.map((s) => s.key);
  assert(JSON.stringify(keys) === JSON.stringify(["national_id", "passport_number", "tax_number", "iban"]), keys.join(","));
  const iban = COUNTRY_FIELD_SPECS.PL.find((s) => s.key === "iban");
  assert(iban.pattern.test("PL61109010140000071219812874") && iban.check("PL61109010140000071219812874"), "valid IBAN refused");
  assert(!iban.check("PL61109010140000071219812875"), "bad IBAN accepted");
  assert(!iban.pattern.test("DE89370400440532013000"), "non-Polish IBAN accepted");
  assert(COUNTRY_FIELD_SPECS.PL.every((s) => !/\$\{|got/.test(s.error)), "errors must not echo the value");
  assert(COUNTRIES.some((c) => c.code === "PL" && c.name === "Poland"), "PL missing from COUNTRIES");
  assert(DUPLICATE_ID_FIELDS.PL === "national_id", "duplicate field mismatch");
});
check("jurisdiction schema mirrors core/jurisdiction.py", () => {
  ["Poland", "polska", "Rzeczpospolita Polska", "Republic of Poland", "PL", "pol"].forEach((v) =>
    assert(getJurisdictionCode(v) === "PL", `${v} did not resolve to PL`));
  assert(getJurisdictionCode("Polandia") === "", "unknown name resolved");
  const fields = getJurisdictionTaxFields("PL");
  assert(JSON.stringify(fields.map((f) => f.key)) === JSON.stringify(["nip", "regon", "krs"]), "field keys");
  fields.forEach((f) => assert(new RegExp(f.pattern).test(f.example), `${f.key} example fails its pattern`));
  assert(plNipIsValid(fields[0].example), "NIP example fails its check digit");
  assert(getCountryNameFromJurisdictionCode("PL") === "Poland", "code -> name");
});
check("bare 'pl' is never a free-text alias (paid-leave code)", () => {
  const source = read("utils/jurisdictionTax.js");
  assert(!/^\s*pl:\s*"PL"/m.test(source), "bare pl alias found");
});
check("PLN currency and IBAN routing are wired", () => {
  const currency = read("utils/currency.js");
  assert(/PL: "PLN"/.test(currency) && /Poland: "PLN"/.test(currency), "PL -> PLN map");
  assert(/PLN: \{ code: 'PLN'.*locale: 'pl-PL'/.test(currency), "PLN master entry");
  assert(/\{ code: "PL", name: "Poland", currency: "PLN" \}/.test(currency), "PLN country list entry");
  const bank = read("modules/payroll/Payroll_Employees/bankFieldsFor.js");
  assert(/"ZA", "PL"\]/.test(bank) && /PL: \["iban"\]/.test(bank) && /PL: "IBAN"/.test(bank), "bank routing");
});

if (failures.length) {
  console.error(`pl-compliance-ui-validation: ${failures.length} failed, ${passed} passed`);
  failures.forEach((f) => console.error(`  - ${f}`));
  process.exit(1);
}
console.log(`pl-compliance-ui-validation: ${passed} checks passed`);
