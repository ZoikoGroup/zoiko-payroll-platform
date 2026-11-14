#!/usr/bin/env node
/**
 * Employee email / phone rules in the UI (src/utils/contactValidation.js),
 * evaluated against the same examples as the server tests
 * (backend/tests/test_employee_contact_validation.py), plus source checks
 * that every employee entry point uses them.
 */
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(__dirname, "..", "src");
const read = (p) => readFileSync(resolve(SRC, p), "utf-8");
const cv = await import(pathToFileURL(resolve(SRC, "utils/contactValidation.js")).href);

let passed = 0;
const failures = [];
function check(name, ok) {
  if (ok) passed += 1;
  else failures.push(name);
}

for (const v of ["98765 43210", "07700 900123", "(415) 555-0123", "0044 7700 900123", "+44 7700 900123", "+592 222 1234", ""]) {
  check(`phone accepted: "${v}"`, cv.phoneError(v) === null);
}
for (const v of ["98765abc10", "+44 7700 9OO123", "call me", "#123", "98765/43210"]) {
  check(`phone letters/symbols rejected: "${v}"`, cv.phoneError(v) === cv.PHONE_BAD_CHARACTERS);
}
for (const v of ["+1 555", "+1234567890123456", "12"]) {
  check(`phone bad length rejected: "${v}"`, cv.phoneError(v) === cv.PHONE_INVALID);
}
check("email normalised", cv.normalizeEmail("  John.Doe@Example.COM ") === "john.doe@example.com");
for (const v of ["john.doe@example.com", "n@test.example", "priya@acme.example.com", ""]) {
  check(`email accepted: "${v}"`, cv.emailError(v) === null);
}
for (const v of ["a@b", "a@@b.com", "a b@c.com", "a@b..com", "x@y.c0m", "@b.com", "a@.com", `${"a".repeat(65)}@b.com`]) {
  check(`email rejected: "${v}"`, cv.emailError(v) === cv.EMAIL_INVALID);
}
check("unchanged legacy value detected", cv.isUnchangedContact("Old Value", " old value ") && !cv.isUnchangedContact("a", "b"));

const form = read("modules/payroll/Payroll_Employees/EmployeeForm.jsx");
const bulk = read("modules/payroll/Payroll_Employees/EmployeeBulkImportModal.jsx");
const pub = read("pages/PublicFormPage.jsx");
check("EmployeeForm validates email and phone with the shared rules", form.includes("emailError(form.email)") && form.includes("phoneError(form.phone)"));
check("EmployeeForm phone input is type=tel", /type="tel"/.test(form));
check("EmployeeForm leaves unchanged legacy values alone", form.includes("isUnchangedContact(original?.phone, form.phone)"));
check("bulk import validates email and phone per row", bulk.includes("emailError(row.email)") && bulk.includes("phoneError(row.phone)"));
check("bulk import reads phone cells as text", bulk.includes('row.phone = String(row.phone ?? "").trim()'));
check("bulk template samples carry the country code", !/phone: "\d/.test(bulk));
check("public form checks email / phone answers", pub.includes("isContactField") && pub.includes("phoneError(v)"));

if (failures.length) {
  console.error(`contact-validation: ${failures.length} failed, ${passed} passed`);
  for (const f of failures) console.error(`  ✗ ${f}`);
  process.exit(1);
}
console.log(`contact-validation: ${passed} checks passed`);
