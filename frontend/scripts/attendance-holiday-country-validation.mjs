#!/usr/bin/env node
/**
 * Attendance: holidays apply per employee country (2026-11-27 fix).
 *
 * The org's holiday list holds every country it pays in. The payroll run's
 * attendance check (service.check_attendance_readiness) treats a holiday as a
 * day off only for employees of that holiday's country (or every employee if
 * it has none). The attendance screen used to skip every holiday for every
 * employee, so AU's New Year's Day left 1 January unrecorded for India staff
 * and blocked the run. These checks prove the screen now uses the same rule
 * when it generates or imports attendance. Checked by source.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(__dirname, "..", "src");
const read = (p) => readFileSync(resolve(SRC, p), "utf-8");

let passed = 0;
const failures = [];
const check = (name, ok) => (ok ? (passed += 1) : failures.push(name));

const page = read("modules/payroll/Attendance/AttendancePage.jsx");
const service = read("service/payrollService.js");

check("roster keeps each employee's country", service.includes("countryCode: emp.country_code || null"));
check("holidays are grouped by country", page.includes("const holidayCountriesByDate = useMemo("));
check("same rule as the gate: blank-country holiday or employee's country",
  page.includes('return countries.has("") || !c || countries.has(c);'));
check("isWorkingDay takes the employee's country", page.includes("function isWorkingDay(dateStr, country)")
  && page.includes("isHolidayFor(dateStr, country)"));
check("bulk generate checks each employee", page.includes("if (!isWorkingDay(dateStr, emp.countryCode)) return;"));
check("bulk generate no longer skips a date for everyone", !page.includes("if (!isWorkingDay(dateStr)) continue;"));
check("bulk preview skips a date only when it is off for every target country",
  page.includes("countries.every((c) => !isWorkingDay(dateStr, c))"));
check("summary-sheet import builds working days per country", page.includes("const workingDatesFor = (country) =>")
  && page.includes("const workingDates = workingDatesFor(empCountry);"));
check("summary-sheet import no longer skips every org holiday",
  !page.includes("if (holidayDates.has(toLocalDateStr(d))) continue;"));

if (failures.length) {
  console.error(`attendance holiday-country validation: ${failures.length} failed, ${passed} passed`);
  for (const f of failures) console.error(`  ✗ ${f}`);
  process.exit(1);
}
console.log(`attendance holiday-country validation: ${passed} checks passed`);
