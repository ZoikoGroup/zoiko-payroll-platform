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
  assert(JSON.stringify(keys) === JSON.stringify(["passport_number", "iban"]), keys.join(","));
  assert(!keys.includes("national_id") && !keys.includes("tax_number"), "PESEL / NIP are vault-only (spec §13)");
  const iban = COUNTRY_FIELD_SPECS.PL.find((s) => s.key === "iban");
  assert(iban.pattern.test("PL61109010140000071219812874") && iban.check("PL61109010140000071219812874"), "valid IBAN refused");
  assert(!iban.check("PL61109010140000071219812875"), "bad IBAN accepted");
  assert(!iban.pattern.test("DE89370400440532013000"), "non-Polish IBAN accepted");
  assert(COUNTRY_FIELD_SPECS.PL.every((s) => !/\$\{|got/.test(s.error)), "errors must not echo the value");
  assert(COUNTRIES.some((c) => c.code === "PL" && c.name === "Poland"), "PL missing from COUNTRIES");
  assert(DUPLICATE_ID_FIELDS.PL === "passport_number", "duplicate field mismatch");
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

// ── Phase 7b: Super Admin Poland page (governed signing console) ──────────
const BACKEND = resolve(__dirname, "..", "..", "backend", "app", "modules", "payroll");
const content = readFileSync(resolve(BACKEND, "engine", "countries", "poland_content.py"), "utf-8");
const paramBlock = content.split("POLAND_PARAMETER_KEYS = {")[1].split("\n}")[0];
const BACKEND_KINDS = Object.fromEntries([...paramBlock.matchAll(/"(pl_[a-z0-9_]+)": "([a-z_]+)"/g)].map((m) => [m[1], m[2]]));
const plContent = await import("../src/components/jurisdiction/poland/plContent.js");

check("every backend parameter sits in exactly one tab", () => {
  const keys = Object.keys(BACKEND_KINDS);
  assert(keys.length > 60, `parsed only ${keys.length} backend keys`);
  const seen = Object.values(plContent.GROUPS).flatMap((g) => g.keys);
  const duplicates = seen.filter((k, i) => seen.indexOf(k) !== i);
  assert(duplicates.length === 0, `in two tabs: ${duplicates.join(", ")}`);
  const missing = keys.filter((k) => !seen.includes(k));
  const unknown = seen.filter((k) => !keys.includes(k));
  assert(!missing.length && !unknown.length, `missing ${missing.join(", ")} unknown ${unknown.join(", ")}`);
});
check("the editor offers exactly the slot each backend kind holds", () => {
  const expected = { text: "text", pct_pair: "pair", employee_pct: "employee", employer_pct: "employer", amount: "amount" };
  Object.entries(BACKEND_KINDS).forEach(([key, kind]) =>
    assert(plContent.valueKind(key) === expected[kind], `${key}: ${plContent.valueKind(key)} vs ${kind}`));
});
check("text choices are the backend vocabulary (+ NOT_SUPPORTED)", () => {
  const rounding = content.split("ROUNDING_MODES = (")[1].split(")")[0].match(/"([A-Z_]+)"/g).map((s) => s.slice(1, -1))
    .filter((v) => v !== "PENDING_G1");
  assert(JSON.stringify(plContent.TEXT_ROWS.pl_rounding_pit.choices) === JSON.stringify([...rounding, "NOT_SUPPORTED"]),
    "rounding choices differ from poland_content.ROUNDING_MODES");
  ["pl_night_supplement_basis", "pl_leave_pay_reference_rule", "pl_fund_exemption_rules", "pl_pit_remittance_due_rule"]
    .forEach((key) => assert(JSON.stringify(plContent.TEXT_ROWS[key].choices) === '["NOT_SUPPORTED"]', `${key}`));
});
check("Poland UI files carry no statutory value", () => {
  const files = ["components/jurisdiction/poland/plContent.js", "components/jurisdiction/poland/PLPackRowsTab.jsx",
    "components/jurisdiction/poland/PLRowEditor.jsx", "components/jurisdiction/poland/PLOverviewDashboard.jsx",
    "components/jurisdiction/poland/PLSigningStatusTab.jsx", "components/jurisdiction/poland/PLEarningClassTab.jsx",
    "config/jurisdictions/polandComplianceConfig.jsx"];
  files.forEach((f) => {
    const text = read(f);
    ["4806", "282600", "282,600", "9.76", "120000", "10800", "3600", "31.40", "2.45"].forEach((lit) =>
      assert(!text.includes(lit), `${f} hard-codes ${lit}`));
  });
});
check("the page hides the generic editors and is routed", () => {
  const config = read("config/jurisdictions/polandComplianceConfig.jsx");
  assert(/hiddenTabs: \["rates", "slabs"\]/.test(config), "generic editors visible");
  const app = read("App.jsx");
  assert(app.includes('path="/super-admin/compliance/poland"') && app.includes("<PLCompliancePage />"), "route");
  assert(/PL: "poland"/.test(read("pages/JurisdictionCompliance/index.js")), "slug");
  assert(/PL: Poland/.test(read("components/jurisdiction/CountryFlag.jsx")), "flag");
  const service = read("service/superAdminService.js");
  assert(service.includes('"/api/super-admin/compliance/poland"') && /export const updatePlRow/.test(service), "service");
  assert(read("components/jurisdiction/poland/PLRowEditor.jsx").includes("updatePlRow("), "editor uses the governed API");
});

// ── Phase 7c: organisation screens ↔ pl_org_router ─────────────────────────
const orgRouter = readFileSync(resolve(BACKEND, "pl_org_router.py"), "utf-8");
const orgRoutes = new Set([...orgRouter.matchAll(/@router\.(get|post|put|patch|delete)\(\s*"([^"]+)"/g)]
  .map(([, method, path]) => `${method.toUpperCase()} /api/payroll/poland${path.replace(/\{[^}]+\}/g, "{}")}`));
const payrollService = read("service/payrollService.js");
// The Poland section runs from its `const PL` to the next top-level declaration
// that is not Poland's own (PL / plList / plOne) — e.g. the payslip-template
// block (`const PST`) that follows it. Slicing to end-of-file counted those
// non-Poland calls as Poland routes.
const plStart = payrollService.indexOf('const PL = "/api/payroll/poland";');
const plAfter = payrollService.slice(plStart + 1).search(/\nconst (?!pl|PL\b)\w+ = /);
const plBlock = payrollService.slice(plStart, plAfter === -1 ? undefined : plStart + 1 + plAfter);
const plCalls = [...plBlock.matchAll(/api\.(get|post|put|delete)\(`([^`]+)`/g)]
  .map(([, method, path]) => `${method.toUpperCase()} ${path.replace("${PL}", "/api/payroll/poland").split("?")[0]
    .replace(/\$\{[^}]+\}/g, "{}")}`);

check("every Poland organisation client call matches a declared route", () => {
  assert(plCalls.length >= 25, `found ${plCalls.length} calls`);
  const unknown = plCalls.filter((c) => !orgRoutes.has(c));
  assert(unknown.length === 0, `no backend route for: ${unknown.join(" | ")}`);
});
check("the identifier vault field never persists or logs a value", () => {
  const field = read("modules/payroll/Payroll_Employees/PLIdentifierField.jsx");
  assert(!/localStorage|sessionStorage|console\.[a-z]+\(|searchParams/.test(field), "storage / console use in the vault field");
  assert(/type="password"/.test(field) && /setValue\(""\)/.test(field), "typed value must be masked and cleared");
  assert(/REVEAL_SECONDS \* 1000/.test(field), "revealed value must expire");
  const centre = read("modules/payroll/Compliances/PLComplianceCentreTab.jsx");
  assert(/type="password"/.test(centre) && /setNrs\(""\)/.test(centre), "NRS must be masked and cleared");
});
check("statements are recorded without a change reason (the backend refuses one)", () => {
  const panel = read("modules/payroll/Payroll_Employees/PolandStatutoryProfilePanel.jsx");
  const statements = panel.split('testId="pl-statements"')[1].split("<JPRecordSection")[0];
  assert(!statements.includes("REASON_FIELD") && statements.includes("transform={statementPayload}"), "statement form");
  assert(!/diagnos/i.test(panel), "no medical field may be captured (PL-017)");
});
check("the Poland centre and employee panel are wired in", () => {
  const compliance = read("modules/payroll/Compliances/CompliancePage.jsx");
  assert(compliance.includes("<PLComplianceCentreTab />") && /isPoland \? \[PL_TAB\]/.test(compliance), "compliance tab");
  const detail = read("modules/payroll/Payroll_Employees/EmployeeDetailPanel.jsx");
  assert(detail.includes('employee.countryCode === "PL"') && detail.includes("<PolandStatutoryProfilePanel"), "employee panel");
});

// ── Phase 7d: run screens ──────────────────────────────────────────────────
check("the payslip breakdown and preflight are wired into the run panel", () => {
  const run = read("modules/payroll/PayRollRuns/RunDetailPanel.jsx");
  assert(/=== "PL" && item\.plCalculationSnapshot && <PLPayslipBreakdown/.test(run), "breakdown");
  assert(/=== "PL"\) && <PLRunPreflightPanel runId=\{run\.id\} \/>/.test(run), "preflight");
  const schemas = readFileSync(resolve(BACKEND, "schemas.py"), "utf-8");
  assert(/plCalculationSnapshot: Optional\[dict\]/.test(schemas), "response schema would strip the snapshot");
});
check("the breakdown reads the frozen result and never recalculates", () => {
  const breakdown = read("modules/payroll/PayRollRuns/PLPayslipBreakdown.jsx");
  assert(!/\b(Number\([^)]*\)\s*[*+/-]\s*Number|\*\s*0\.\d|\/\s*100)\b/.test(breakdown), "arithmetic on statutory figures");
  assert(!/pesel|nip|iban|diagnos/i.test(breakdown.replace(/NIP \/ REGON/g, "")), "identifier / medical wording in breakdown");
  ["pl_pit_advance", "pl_zus_employee", "pl_health", "pl_ppk_employee", "pl_funds", "pl_net"].forEach((key) =>
    assert(breakdown.includes(key), `breakdown does not show ${key}`));
});
check("Poland payslip labels map the platform fields", () => {
  const labels = read("utils/jurisdictionLabels.js");
  ["PL: \"PIT Advance (zaliczka)\"", "PL: \"ZUS (Employer", "PL: \"FP/FS, FGŚP, FEP (Employer)\"", "PL: \"PPK (Employer)\""]
    .forEach((needle) => assert(labels.includes(needle), `missing label ${needle}`));
});

// ── Phase 8: filings, settlements, journal (PL-019 / PL-020 / PL-021) ──────
check("filings, settlements and the run journal are wired in", () => {
  const centre = read("modules/payroll/Compliances/PLComplianceCentreTab.jsx");
  assert(centre.includes("<PLFilingSettlementPanel />"), "filing panel not in the centre");
  const run = read("modules/payroll/PayRollRuns/RunDetailPanel.jsx");
  assert(/=== "PL"\)\s*&& \["Paid", "Closed"\]\.includes\(\(detail \|\| run\)\.status\) && <PLRunJournalPanel/.test(run),
    "journal must show for a PAID Poland run only");
  ["listPlFilings", "approvePlFiling", "recordPlFilingSubmission", "recordPlFilingResponse", "listPlSettlements",
    "recordPlSettlementPayment", "reconcilePlSettlement", "resolvePlVariance", "getPlRunJournal"]
    .forEach((fn) => assert(new RegExp(`export const ${fn} =`).test(payrollService), `missing ${fn}`));
});
check("the filing screen never transmits and never computes", () => {
  const panel = read("modules/payroll/Compliances/PLFilingSettlementPanel.jsx");
  assert(!/fetch\(|XMLHttpRequest|zus\.pl|e-deklaracje\.gov|puesc|https?:\/\//i.test(panel), "external transport in UI");
  assert(/disabled=\{state\.busy \|\| !r\.schemaArchived\}/.test(panel), "approval must wait for an archived schema");
  assert(!/(Number\([^)]*\)\s*[*+/-]|\*\s*0\.\d|\/\s*100)/.test(panel), "arithmetic on amounts in the UI");
  assert(!/pesel|iban/i.test(panel.replace(/masked identifiers/g, "")), "identifier wording in the filing screen");
});

// ── Phase 9: release gates, golden check, parallel cycles ──────────────────
check("the release-gates tab is on the Super Admin page and calls the governed routes", () => {
  const config = read("config/jurisdictions/polandComplianceConfig.jsx");
  assert(/tab\("pl-readiness", "Release gates"/.test(config) && config.includes("<PLReadinessTab pack={pack} />"),
    "release-gates tab");
  const service = read("service/superAdminService.js");
  assert(service.includes("${PL_SA}/packs/${packRowId}/golden-check")
    && service.includes("${PL_SA}/packs/${packRowId}/authority-examples"), "golden-check / example client calls");
  const saRouter = readFileSync(resolve(BACKEND, "../super_admin/router.py"), "utf-8");
  ["/compliance/poland/packs/{pack_row_id}/golden-check", "/compliance/poland/packs/{pack_row_id}/authority-examples"]
    .forEach((path) => assert(saRouter.includes(`"${path}"`), `no backend route ${path}`));
  const tab = read("components/jurisdiction/poland/PLReadinessTab.jsx");
  assert(!/passed\s*=\s*true|allPassed\s*=/.test(tab), "the UI must never decide a gate");
  assert(/pack\.status === "Draft" && <AddExample/.test(tab), "examples are added to a Draft pack only");
});
check("the parallel-cycle screen is wired and names the Polish identifiers it refuses", () => {
  const centre = read("modules/payroll/Compliances/PLComplianceCentreTab.jsx");
  assert(centre.includes("<PLParallelCyclesSection />") && centre.includes('data-testid="pl-gates-passed"'),
    "parallel section / gate count");
  const section = read("modules/payroll/Compliances/PLParallelCyclesSection.jsx");
  assert(/PESEL/.test(section) && !/IRD|KiwiSaver|PAYE/.test(section), "wording copied from New Zealand");
  const backend = readFileSync(resolve(BACKEND, "poland_parallel.py"), "utf-8");
  const concepts = backend.match(/CONCEPTS = \(([^)]*)\)/)[1].match(/"([a-z_]+)"/g).map((c) => c.slice(1, -1));
  const ui = [...section.matchAll(/\["([a-z_]+)", "/g)].map((m) => m[1]);
  assert(JSON.stringify(ui) === JSON.stringify(concepts), `UI concepts ${ui} != backend ${concepts}`);
});

if (failures.length) {
  console.error(`pl-compliance-ui-validation: ${failures.length} failed, ${passed} passed`);
  failures.forEach((f) => console.error(`  - ${f}`));
  process.exit(1);
}
console.log(`pl-compliance-ui-validation: ${passed} checks passed`);
