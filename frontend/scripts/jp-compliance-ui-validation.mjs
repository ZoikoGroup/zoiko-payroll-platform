#!/usr/bin/env node
/**
 * ZP-JP-ENG-001 Phase 7 frontend validation.
 *
 * Source-level checks (no .jsx import, like za-compliance-ui-validation): the
 * Japan API client only calls routes the backend router really declares, the
 * My Number handling never persists or logs the digits, and every Japan
 * surface is mounted where an operator can reach it.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(__dirname, "..", "src");
const BACKEND = resolve(__dirname, "..", "..", "backend");
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

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

const JAPAN_FILES = [
  "components/jurisdiction/japan/JPRecordSection.jsx",
  "components/jurisdiction/japan/JPPackRowsTab.jsx",
  "components/jurisdiction/japan/JPOverviewDashboard.jsx",
  "components/jurisdiction/japan/jpFormat.js",
  "components/jurisdiction/japan/jpShared.jsx",
  "components/jurisdiction/japan/jpComponentConfig.js",
  "config/jurisdictions/japanComplianceConfig.jsx",
  "pages/JurisdictionCompliance/JPCompliancePage.jsx",
  "modules/payroll/Compliances/JPComplianceCentreTab.jsx",
  "modules/payroll/Payroll_Employees/JapanStatutoryProfilePanel.jsx",
  "modules/payroll/Payroll_Employees/JPMyNumberField.jsx",
  "modules/payroll/PayRollRuns/JPPayslipBreakdown.jsx",
  "modules/payroll/PayRollRuns/JPRunPreflightPanel.jsx",
];
const files = Object.fromEntries(JAPAN_FILES.map((f) => [f, read(f)]));
const service = read("service/payrollService.js");
const jpBlock = service.slice(service.indexOf('const JP = "/api/payroll/japan";'));
const myNumber = files["modules/payroll/Payroll_Employees/JPMyNumberField.jsx"];
const employeePanel = files["modules/payroll/Payroll_Employees/JapanStatutoryProfilePanel.jsx"];

// ── API client ↔ backend router ──────────────────────────────────────────
const router = readFileSync(resolve(BACKEND, "app/modules/payroll/japan_org_router.py"), "utf-8");
const prefix = /APIRouter\(prefix="([^"]+)"/.exec(router)?.[1];
const backendRoutes = new Set(
  [...router.matchAll(/@router\.(get|post|put|patch|delete)\(\s*"([^"]+)"/g)]
    .map(([, method, path]) => `${method.toUpperCase()} /payroll${prefix}${path}`.replace(/\{[^}]+\}/g, "{}")),
);
const clientCalls = [...jpBlock.matchAll(/api\.(get|post|put|patch|delete)\(`\$\{JP\}([^`]*)`/g)]
  .map(([, method, path]) => `${method.toUpperCase()} /payroll/japan${path}`.replace(/\$\{[^}]+\}/g, "{}"));

check("The Japan client block exists with the real /api/payroll/japan prefix", () =>
  jpBlock.length > 0 && !/["`]\/api\/japan/.test(service));
check("The backend router was parsed", () => assert(prefix === "/japan" && backendRoutes.size >= 30, `prefix ${prefix}, ${backendRoutes.size} routes`));
check("Every Japan client call matches a route the backend declares", () => {
  const unknown = clientCalls.filter((call) => !backendRoutes.has(call));
  assert(clientCalls.length >= 30, `only ${clientCalls.length} client calls found`);
  assert(unknown.length === 0, `no backend route for: ${unknown.join(", ")}`);
});
check("Approve / apply calls send only the id, never a form", () => {
  const bad = [...jpBlock.matchAll(/export const (approveJp\w+|applyJp\w+) = \(([^)]*)\)/g)]
    .filter(([, , args]) => args.split(",").length !== 1);
  assert(bad.length === 0, bad.map(([, name]) => name).join(", "));
});

// ── My Number ─────────────────────────────────────────────────────────────
check("No 12-digit literal appears in any Japan file", () => {
  const hits = JAPAN_FILES.filter((f) => /(?<![\d.])\d{12}(?![\d.])/.test(files[f]));
  assert(hits.length === 0, hits.join(", "));
});
check("My Number is never written to storage, the URL or the console", () =>
  !/localStorage|sessionStorage|console\.|history\.push|navigate\(|location\./.test(myNumber));
check("A revealed My Number is wiped after 60 seconds and on unmount", () =>
  /export const REVEAL_SECONDS = 60;/.test(myNumber)
  && myNumber.includes("setTimeout(() => setRevealed(null), REVEAL_SECONDS * 1000)")
  && /useEffect\(\(\) => \(\) => \{\s*clearTimeout\(timer\.current\);\s*setRevealed\(null\);/.test(myNumber));
check("The My Number input is masked, not autofilled, and cleared before the request", () =>
  myNumber.includes('type="password"') && myNumber.includes('autoComplete="off"')
  && myNumber.indexOf('setNumber("")') < myNumber.indexOf("await createJpMyNumber"));
check("Lists show the masked form only", () => myNumber.includes("{revealed || row.masked}"));
check("A reveal needs a reason before it can be requested", () =>
  myNumber.includes("disabled={busy || !reason.trim()}"));
check("No other Japan file reads a My Number value", () => {
  const hits = JAPAN_FILES.filter((f) => f !== "modules/payroll/Payroll_Employees/JPMyNumberField.jsx"
    && /myNumber|my_number(?!_vault_id)/.test(files[f]));
  assert(hits.length === 0, hits.join(", "));
});
check("Payslip labels never map an identity field to a My Number", () =>
  !/JP:\s*\{\s*label:[^}]*my_number/.test(read("utils/jurisdictionLabels.js")));

// ── behaviour the backend relies on ───────────────────────────────────────
check("Attendance approval captures only a period — hours come from attendance records", () => {
  const section = employeePanel.slice(employeePanel.indexOf('title="Attendance approvals"'));
  const fields = section.slice(0, section.indexOf("]}")) ;
  assert(!/hours|status/.test(fields.slice(fields.indexOf("fields={["))), "the request form offers hours or a status");
});
check("Work conditions offer only the certified STANDARD system", () =>
  /options: \["STANDARD"\]/.test(files["modules/payroll/Compliances/JPComplianceCentreTab.jsx"])
  && !/FLEXIBLE|SHIFT|ON_CALL/.test(files["modules/payroll/Compliances/JPComplianceCentreTab.jsx"]));
check("No South Africa field leaked into a Japan form", () => {
  const hits = JAPAN_FILES.filter((f) => /\b(paye|uif|sdl|eti|directive)/i.test(files[f]));
  assert(hits.length === 0, hits.join(", "));
});
check("The payslip breakdown only displays the frozen result", () => {
  const breakdown = files["modules/payroll/PayRollRuns/JPPayslipBreakdown.jsx"];
  return !/api\.|payrollService|reduce\(/.test(breakdown);
});

// ── mounting ──────────────────────────────────────────────────────────────
check("Super Admin route, export, slug and flag exist", () => {
  const app = read("App.jsx");
  const index = read("pages/JurisdictionCompliance/index.js");
  return app.includes('path="/super-admin/compliance/japan"') && app.includes("<JPCompliancePage />")
    && index.includes('export { default as JPCompliancePage }') && /JP: "japan"/.test(index)
    && /JP: Japan/.test(read("components/jurisdiction/CountryFlag.jsx"));
});
check("The Compliance Centre tab is mounted for Japan organisations", () =>
  /currentTab === JP_TAB && <JPComplianceCentreTab \/>/.test(read("modules/payroll/Compliances/CompliancePage.jsx")));
check("The run detail mounts the JP breakdown and preflight", () => {
  const run = read("modules/payroll/PayRollRuns/RunDetailPanel.jsx");
  return run.includes("<JPPayslipBreakdown snapshot={item.jpCalculationSnapshot}")
    && run.includes("<JPRunPreflightPanel runId={run.id} />");
});
check("The employee detail opens the Japan statutory records for JP employees", () => {
  const employee = read("modules/payroll/Payroll_Employees/EmployeeDetailPanel.jsx");
  return employee.includes('employee.countryCode === "JP"') && employee.includes("<JapanStatutoryProfilePanel");
});
check("Every Japan source file is reachable from an import", () => {
  const all = walk(SRC).filter((p) => /\.(jsx?|mjs)$/.test(p)).map((p) => readFileSync(p, "utf-8")).join("\n");
  const orphans = JAPAN_FILES.filter((f) => {
    const base = f.split("/").pop().replace(/\.(jsx|js)$/, "");
    return !new RegExp(`from ["'][^"']*/${base}["']`).test(all);
  });
  assert(orphans.length === 0, orphans.join(", "));
});

console.log(`jp-compliance-ui-validation: ${passed} passed, ${failures.length} failed`);
for (const failure of failures) console.log(`  FAIL ${failure}`);
process.exit(failures.length ? 1 : 0);
