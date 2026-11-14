#!/usr/bin/env node
/**
 * ZP-MY-ENG-001 (Malaysia) frontend validation.
 *
 * Phase 0: the NRIC check in countryFieldSpecs.js must agree with the backend
 * (employee_validation.py my_nric_is_valid and the vectors in
 * backend/tests/test_malaysia_scaffold.py), and the Malaysia schema / currency
 * / bank wiring must mirror the backend. Later phases add their own checks
 * here. Does not import .jsx (the Vite graph OOMs on this machine).
 *
 * Phase 8a: the Super Admin console and statutory workbook are wired to
 * declared backend routes; generic editors hidden; workbook never signs.
 * Phase 8b: organisation screens call only my_org_router routes; vault field
 * never persists; declarations carry no reason; breakdown reads the snapshot.
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

// ── Phase 8a: Super Admin console (signing + statutory workbook) ───────────
const BACKEND_ROOT = resolve(__dirname, "..", "..", "backend", "app", "modules");
const saRouter = () => readFileSync(resolve(BACKEND_ROOT, "super_admin", "router.py"), "utf-8");
check("every Malaysia Super Admin client call has a declared backend route", () => {
  const service = read("service/superAdminService.js");
  assert(service.includes('const MY_SA = "/api/super-admin/compliance/malaysia"'), "MY_SA base");
  const calls = [...service.matchAll(/\$\{MY_SA\}(\/[^`"?]*)/g)].map((m) => m[1]
    .replace(/\$\{packRowId\}/g, "{pack_row_id}").replace(/\$\{kind\}/g, "{kind}").replace(/\$\{rowId\}/g, "{row_id}")
    .replace(/\$\{step\}/g, "{step}"));
  assert(calls.length >= 9, `only ${calls.length} Malaysia client calls`);
  const router = saRouter();
  calls.forEach((path) => {
    const paths = path.includes("{step}") ? ["preview", "apply"].map((s) => path.replace("{step}", s)) : [path];
    paths.forEach((one) => assert(router.includes(`"/compliance/malaysia${one}"`), `no backend route for ${one}`));
  });
});
check("the Malaysia page hides the generic editors and is routed", () => {
  const config = read("config/jurisdictions/malaysiaComplianceConfig.jsx");
  assert(/hiddenTabs: \["rates", "slabs"\]/.test(config), "generic editors must be hidden");
  ["my-territory", "my-tables", "my-earning", "my-workbook", "my-signing"].forEach((key) =>
    assert(config.includes(`tab("${key}"`), `tab ${key}`));
  const app = read("App.jsx");
  assert(app.includes('path="/super-admin/compliance/malaysia"') && app.includes("<MYCompliancePage />"), "route");
  assert(/MY: "malaysia"/.test(read("pages/JurisdictionCompliance/index.js")), "slug");
  assert(/MY: Malaysia/.test(read("components/jurisdiction/CountryFlag.jsx")), "flag");
  assert(/jurisdiction_country == "MY"/.test(readFileSync(resolve(BACKEND_ROOT, "payroll", "service.py"), "utf-8")),
    "backend refuses the generic editor for MY");
});
check("the workbook screen never signs or activates and applies only to a Draft pack", () => {
  const tab = read("components/jurisdiction/malaysia/MYWorkbookTab.jsx");
  assert(!/specialistVerified|signMyRows|activate/i.test(tab.replace(/never signs|Activated|activate a pack/gi, "")),
    "the workbook must not sign or activate");
  assert(tab.includes("isEditablePack(pack)") && tab.includes("!summary.INVALID"), "Draft-only, no INVALID rows");
  assert(/Change reason \*/.test(tab), "apply needs a reason");
});
check("territorial rows are read per territory, never defaulted", () => {
  const content = read("components/jurisdiction/malaysia/myContent.js");
  ["PENINSULAR_LABUAN", "SABAH", "SARAWAK"].forEach((t) => assert(content.includes(`code: "${t}"`), t));
  assert(!/\b(1700|5000|6000|20000|4000)\b/.test(content), "a statutory number in the console vocabulary");
  const tabs = read("components/jurisdiction/malaysia/MYPackTabs.jsx");
  assert(tabs.includes("territoryKey(base, t)") && tabs.includes('<span className="text-error">missing</span>'),
    "a missing territorial row is shown, never filled");
});

// ── Phase 8b: organisation screens ─────────────────────────────────────────
const orgRouter = readFileSync(resolve(BACKEND_ROOT, "payroll", "my_org_router.py"), "utf-8");
const myOrgRoutes = new Set([...orgRouter.matchAll(/@router\.(get|post|put|patch|delete)\(\s*"([^"]+)"/g)]
  .map(([, method, path]) => `${method.toUpperCase()} /api/payroll/malaysia${path.replace(/\{[^}]+\}/g, "{}")}`));
const payrollServiceSource = read("service/payrollService.js");
const myStart = payrollServiceSource.indexOf('const MYP = "/api/payroll/malaysia";');
const myNext = payrollServiceSource.slice(myStart + 1).search(/\nconst [A-Z_]+ = "\/api\/payroll\//);
const myBlock = payrollServiceSource.slice(myStart, myNext < 0 ? undefined : myStart + 1 + myNext);
const myCalls = [...myBlock.matchAll(/api\.(get|post|put|delete)\(`([^`]+)`/g)]
  .map(([, method, path]) => `${method.toUpperCase()} ${path.replace("${MYP}", "/api/payroll/malaysia").split("?")[0]
    .replace(/\$\{[^}]+\}/g, "{}")}`);
check("every Malaysia organisation client call matches a declared my_org_router route", () => {
  assert(myStart >= 0, "MYP base");
  assert(myCalls.length >= 30, `found ${myCalls.length} calls`);
  const unknown = myCalls.filter((c) => !myOrgRoutes.has(c));
  assert(unknown.length === 0, `no backend route for: ${unknown.join(" | ")}`);
});
check("the identifier vault field never persists or logs a value", () => {
  const field = read("modules/payroll/Payroll_Employees/MYIdentifierField.jsx");
  assert(!/localStorage|sessionStorage|console\.[a-z]+\(|searchParams/.test(field), "storage / console use in the vault field");
  assert(/type="password"/.test(field) && /setValue\(""\)/.test(field), "typed value must be masked and cleared");
  assert(/REVEAL_SECONDS \* 1000/.test(field), "revealed value must expire");
});
check("declarations are recorded without a change reason (the backend refuses one)", () => {
  const panel = read("modules/payroll/Payroll_Employees/MalaysiaStatutoryProfilePanel.jsx");
  const declarations = panel.split('testId="my-declarations"')[1].split("<JPRecordSection")[0];
  assert(!declarations.includes("REASON_FIELD") && declarations.includes("transform={declarationPayload}"), "declaration form");
  assert(!/nric|passport/i.test(panel.split("<MYIdentifierField")[0].replace(/nric_vault_id|NRIC vault id|NRIC \/ TIN/g, "")),
    "no raw identifier field in the records panel");
});
check("the Malaysia centre, employee panel and run screens are wired in", () => {
  const compliance = read("modules/payroll/Compliances/CompliancePage.jsx");
  assert(compliance.includes("<MYComplianceCentreTab />") && /isMalaysia \? \[MY_TAB\]/.test(compliance), "compliance tab");
  const detail = read("modules/payroll/Payroll_Employees/EmployeeDetailPanel.jsx");
  assert(detail.includes('employee.countryCode === "MY"') && detail.includes("<MalaysiaStatutoryProfilePanel"), "employee panel");
  const run = read("modules/payroll/PayRollRuns/RunDetailPanel.jsx");
  assert(/=== "MY" && item\.myCalculationSnapshot && <MYPayslipBreakdown/.test(run), "breakdown");
  assert(/=== "MY"\) && <MYRunPreflightPanel runId=\{run\.id\} \/>/.test(run), "preflight");
  const schemas = readFileSync(resolve(BACKEND_ROOT, "payroll", "schemas.py"), "utf-8");
  assert(/myCalculationSnapshot: Optional\[dict\] = None/.test(schemas), "snapshot declared in the response schema");
});
check("the payslip breakdown only reads the frozen my_result", () => {
  const breakdown = read("modules/payroll/PayRollRuns/MYPayslipBreakdown.jsx");
  assert(!/\b(api|fetch|calculate)\b\(/.test(breakdown) && !/import .*payrollService/.test(breakdown), "no recalculation / call");
  assert(/s\.my_net/.test(breakdown) && /coverage\[name\]/.test(breakdown), "reads the snapshot fields");
  const labels = read("utils/jurisdictionLabels.js");
  assert(/MY: "PCB \/ MTD"/.test(labels) && /MY: "HRD Levy \(Employer\)"/.test(labels), "Malaysia payslip labels");
});

// ── Phase 9: filings, settlements, reconciliation, journal ─────────────────
check("the filing / settlement panel and the journal are wired and never send anything", () => {
  const centre = read("modules/payroll/Compliances/MYComplianceCentreTab.jsx");
  assert(centre.includes("<MYFilingSettlementPanel />"), "filing panel in the centre");
  const panel = read("modules/payroll/Compliances/MYFilingSettlementPanel.jsx");
  assert(/disabled=\{state\.busy \|\| !r\.schemaArchived\}/.test(panel), "approval disabled without an archived layout");
  assert(!/fetch\(|XMLHttpRequest|sendTo|transmit/i.test(panel), "no live transport from the UI (D-5)");
  assert(!/nric|tin\b|passport/i.test(panel.replace(/masked identifiers/g, "")), "identifier wording in the filing screen");
  const run = read("modules/payroll/PayRollRuns/RunDetailPanel.jsx");
  assert(/=== "MY"\)\s*&& \["Paid", "Closed"\]\.includes\(\(detail \|\| run\)\.status\) && <MYRunJournalPanel/.test(run),
    "journal only for a paid run");
  const events = read("modules/payroll/Payroll_Employees/MalaysiaStatutoryProfilePanel.jsx");
  assert(events.includes("buildMyEventFiling(r.id)"), "event form action");
});

// ── Phase 10: release gates, golden check, parallel cycles ─────────────────
check("the release-gates tab is on the Super Admin page and never decides a gate", () => {
  const config = read("config/jurisdictions/malaysiaComplianceConfig.jsx");
  assert(/tab\("my-readiness", "Release gates"/.test(config) && config.includes("<MYReadinessTab pack={pack} />"),
    "release-gates tab");
  const service = read("service/superAdminService.js");
  assert(service.includes("${MY_SA}/packs/${packRowId}/golden-check")
    && service.includes("${MY_SA}/packs/${packRowId}/authority-examples"), "golden-check / example client calls");
  const router = saRouter();
  ["/compliance/malaysia/packs/{pack_row_id}/golden-check", "/compliance/malaysia/packs/{pack_row_id}/authority-examples"]
    .forEach((path) => assert(router.includes(`"${path}"`), `no backend route ${path}`));
  const tab = read("components/jurisdiction/malaysia/MYReadinessTab.jsx");
  assert(!/passed\s*=\s*true|allPassed\s*=/.test(tab), "the UI must never decide a gate");
  assert(/pack\.status === "Draft" && <AddExample/.test(tab), "examples are added to a Draft pack only");
});
check("the parallel-cycle screen is wired and names the Malaysian identifiers it refuses", () => {
  const centre = read("modules/payroll/Compliances/MYComplianceCentreTab.jsx");
  assert(centre.includes("<MYParallelCyclesSection />"), "parallel section in the centre");
  const section = read("modules/payroll/Compliances/MYParallelCyclesSection.jsx");
  assert(/WITHOUT NRIC/.test(section) && /release gate G5/.test(section), "identifier warning and gate");
  assert(/"hrd_levy"/.test(section) && /"pcb"/.test(section), "Malaysian concepts");
});

if (failures.length) {
  console.error(`my-compliance-ui-validation: ${failures.length} failed, ${passed} passed`);
  failures.forEach((f) => console.error(`  - ${f}`));
  process.exit(1);
}
console.log(`my-compliance-ui-validation: ${passed} checks passed`);
