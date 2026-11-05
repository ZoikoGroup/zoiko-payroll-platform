#!/usr/bin/env node
/**
 * ZP-NZ-ENG-001 Phase 7 frontend validation (P7b: Super Admin signing console;
 * P7c/P7d extend it with the organisation screens).
 *
 * Source-level checks (no .jsx import, like jp-compliance-ui-validation): the
 * New Zealand Super Admin client only calls routes the backend declares; every
 * content key the page shows exists in new_zealand_content.py and every text
 * choice is one the backend accepts; the generic row editors stay hidden (NZ
 * rows change only through the governed console); and every NZ surface is
 * mounted where a Super Admin can reach it.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(__dirname, "..", "src");
const BACKEND = resolve(__dirname, "..", "..", "backend");
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
function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

const NZ_FILES = [
  "components/jurisdiction/new_zealand/nzContent.js",
  "components/jurisdiction/new_zealand/nzForm.js",
  "components/jurisdiction/new_zealand/nzShared.jsx",
  "components/jurisdiction/new_zealand/NZRowEditor.jsx",
  "components/jurisdiction/new_zealand/NZPackRowsTab.jsx",
  "components/jurisdiction/new_zealand/NZAuthorityTablesTab.jsx",
  "components/jurisdiction/new_zealand/NZEarningClassTab.jsx",
  "components/jurisdiction/new_zealand/NZOverviewDashboard.jsx",
  "components/jurisdiction/new_zealand/NZSigningStatusTab.jsx",
  "config/jurisdictions/newZealandComplianceConfig.jsx",
  "pages/JurisdictionCompliance/NZCompliancePage.jsx",
  "components/jurisdiction/new_zealand/NZSeedDraftPanel.jsx",
  // P7c — organisation screens
  "components/jurisdiction/new_zealand/nzOrgOptions.js",
  "modules/payroll/Compliances/NZComplianceCentreTab.jsx",
  "modules/payroll/Payroll_Employees/NewZealandStatutoryProfilePanel.jsx",
  "modules/payroll/Payroll_Employees/NZLeaveSections.jsx",
  "modules/payroll/Payroll_Employees/NZNoticeSection.jsx",
  "modules/payroll/Payroll_Employees/NZIrdNumberField.jsx",
  // P7d — runs, special payments, corrections
  "modules/payroll/PayRollRuns/NZPayslipBreakdown.jsx",
  "modules/payroll/PayRollRuns/NZRunPreflightPanel.jsx",
  "modules/payroll/Compliances/NZPaymentsSection.jsx",
  // P8 — payday filing, remittance, run exceptions, journal
  "modules/payroll/Compliances/NZFilingRemittanceSection.jsx",
  "modules/payroll/PayRollRuns/NZRunFilingPanel.jsx",
  // P9 — release gates and parallel cycles
  "components/jurisdiction/new_zealand/NZReadinessTab.jsx",
  "modules/payroll/Compliances/NZParallelCyclesSection.jsx",
];
const files = Object.fromEntries(NZ_FILES.map((f) => [f, read(f)]));
const contentJs = files["components/jurisdiction/new_zealand/nzContent.js"];
const config = files["config/jurisdictions/newZealandComplianceConfig.jsx"];

// ── Super Admin client ↔ backend routes ─────────────────────────────────────
const superAdminService = read("service/superAdminService.js");
const nzBlock = superAdminService.slice(superAdminService.indexOf('const NZ_SA = "/api/super-admin/compliance/new-zealand";'));
const nzClient = nzBlock.slice(0, nzBlock.indexOf("export const getZaReadiness"));
const saRouter = readBackend("app/modules/super_admin/router.py");
const saRoutes = new Set(
  [...saRouter.matchAll(/@router\.(get|post|put|patch|delete)\(\s*"([^"]+)"/g)]
    .map(([, method, path]) => `${method.toUpperCase()} /api/super-admin${path.replace(/\{[^}]+\}/g, "{}")}`),
);
const clientCalls = [...nzClient.matchAll(/apiFetch\(\s*[`"]([^`"]+)[`"](?:,\s*\{\s*method:\s*"([A-Z]+)")?/g)]
  .map(([, path, method]) => `${method || "GET"} ${path.replace("${NZ_SA}", "/api/super-admin/compliance/new-zealand")
    .replace(/\$\{[^}]+\}/g, "{}")}`);

check("The NZ Super Admin client block exists", () => assert(nzClient.length > 0 && clientCalls.length >= 6,
  `found ${clientCalls.length} calls`));
check("Every NZ Super Admin client call matches a declared route", () => {
  const generic = "GET /api/super-admin/compliance/jurisdictions/{}/statutory-summary";
  const missing = clientCalls.filter((call) => !saRoutes.has(call) && call !== generic.replace("{}", "NZ")
    && !(call.endsWith("/statutory-summary") && saRoutes.has(generic)));
  assert(missing.length === 0, missing.join(" | "));
});

check("The draft-pack seed is offered only while no NZ pack exists, with a reason", () => {
  const seed = files["components/jurisdiction/new_zealand/NZSeedDraftPanel.jsx"];
  const overview = files["components/jurisdiction/new_zealand/NZOverviewDashboard.jsx"];
  assert(/if \(!pack\) return <NZSeedDraftPanel \/>;/.test(overview), "mounted only without a selected pack");
  assert(/packs\.length > 0 && !state\.done/.test(seed), "hidden once any NZ pack exists");
  assert(/seedNzDraftPack\(reason\.trim\(\)\)/.test(seed) && /disabled=\{state\.busy \|\| !reason\.trim\(\)\}/.test(seed),
    "a reason is required");
  assert(!/Active/.test(seed.replace(/\/\/.*$/gm, "").replace(/is active|not active/gi, "")), "the seed never activates");
});
check("The signing status shows the activation checklist in order", () => {
  const signing = files["components/jurisdiction/new_zealand/NZSigningStatusTab.jsx"];
  const order = ["Draft pack seeded", "Parameters signed", "Table rows signed", "Authority tables filled",
    "Approved by a Super Admin who made none of the edits", "Activated"].map((label) => signing.indexOf(label));
  assert(signing.includes('data-testid="nz-activation-checklist"') && order.every((i, n) => i > 0 && (n === 0 || i > order[n - 1])),
    `order ${order}`);
});

// ── P9: release gates and parallel cycles ───────────────────────────────────
check("The release-gate tab and the parallel-cycle section are mounted", () => {
  assert(/tab\("nz-readiness", "Release gates", BadgeCheck, "nz-signing", \(\{ pack \}\) => <NZReadinessTab pack=\{pack\} \/>\)/
    .test(config), "Super Admin tab");
  const centreText = read("modules/payroll/Compliances/NZComplianceCentreTab.jsx");
  assert(centreText.includes("<NZParallelCyclesSection />") && centreText.includes('data-testid="nz-gates-passed"'),
    "compliance centre");
});
check("The readiness tab only reads the server's gates (nothing ticked in the browser)", () => {
  const tab = files["components/jurisdiction/new_zealand/NZReadinessTab.jsx"];
  assert(/getNzStatutorySummary\(\)/.test(tab) && /summary\?\.readiness/.test(tab), "reads the summary readiness");
  assert(!/useState\(\s*\{[^}]*passed/.test(tab) && !/passed:\s*true/.test(tab), "no client-side pass");
  assert(/runNzGoldenCheck\(pack\.id\)/.test(tab), "golden check runs against the selected pack");
});
check("Parallel concepts are exactly the backend's and no identifier column is offered", () => {
  const section = files["modules/payroll/Compliances/NZParallelCyclesSection.jsx"];
  const backend = readBackend("app/modules/payroll/nz_parallel.py");
  const server = [...backend.slice(backend.indexOf("CONCEPTS = ("), backend.indexOf(")", backend.indexOf("CONCEPTS = (")))
    .matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
  const client = [...section.slice(section.indexOf("const CONCEPTS"), section.indexOf("];", section.indexOf("const CONCEPTS")))
    .matchAll(/\["([a-z_]+)", "/g)].map((m) => m[1]);
  assert(JSON.stringify(server) === JSON.stringify(client), `${server} vs ${client}`);
  assert(!/ird|bank/i.test(section.slice(section.indexOf("const CONCEPTS"), section.indexOf("];", section.indexOf("const CONCEPTS")))),
    "no identifier concept");
  assert(/columnMap, reason: form\.reason/.test(section), "the import carries a reason");
  assert(/Accept \(another user\)/.test(section) && /Accept cycle \(not the importer\)/.test(section), "four-eyes labels");
});

// ── content keys ↔ backend content ──────────────────────────────────────────
const backendContent = readBackend("app/modules/payroll/engine/countries/new_zealand_content.py");
const parameterBlock = backendContent.slice(backendContent.indexOf("NZ_PARAMETER_KEYS = {"),
  backendContent.indexOf("}", backendContent.indexOf("NZ_PARAMETER_KEYS = {")));
const backendKeys = new Map([...parameterBlock.matchAll(/"(nz_[a-z0-9_]+)":\s*"([a-z_]+)"/g)].map((m) => [m[1], m[2]]));

check("Every NZ key the page shows exists in new_zealand_content.py", () => {
  const unknown = [...new Set([...contentJs.matchAll(/"(nz_[a-z0-9_]+)"/g)].map((m) => m[1]))]
    .filter((key) => !backendKeys.has(key));
  assert(unknown.length === 0, unknown.join(", "));
});
check("Every NZ parameter appears in one of the page's groups", () => {
  const groups = contentJs.slice(contentJs.indexOf("export const GROUPS"), contentJs.indexOf("const text ="));
  const missing = [...backendKeys.keys()].filter((key) => !groups.includes(`"${key}"`));
  assert(missing.length === 0, missing.join(", "));
});
check("Every text parameter has a choice list or a hint", () => {
  const textRows = contentJs.slice(contentJs.indexOf("export const TEXT_ROWS"), contentJs.indexOf("export const isTextRow"));
  const missing = [...backendKeys].filter(([, kind]) => kind === "text").map(([key]) => key)
    .filter((key) => !new RegExp(`^\\s*${key}:`, "m").test(textRows));
  assert(missing.length === 0, missing.join(", "));
});
check("Rounding choices are exactly the engine's rounding vocabulary", () => {
  const pack = readBackend("app/modules/payroll/engine/jurisdictions/new_zealand/pack.py");
  const engine = [...pack.slice(pack.indexOf("ROUNDING_RULES = {")).split("}")[0].matchAll(/"([A-Z_]+)":/g)].map((m) => m[1]);
  const ui = [...contentJs.slice(contentJs.indexOf("const ROUNDING"), contentJs.indexOf("];", contentJs.indexOf("const ROUNDING")))
    .matchAll(/"([A-Z_]+)"/g)].map((m) => m[1]);
  assert(engine.length > 0 && JSON.stringify([...engine].sort()) === JSON.stringify([...ui].sort()),
    `engine ${engine} vs ui ${ui}`);
});
check("Authority tables offered are the ones the backend accepts", () => {
  const console_ = readBackend("app/modules/payroll/nz_super_admin.py");
  const ui = [...contentJs.matchAll(/ruleType: "(NZ_[A-Z_]+)"/g)].map((m) => m[1])
    .filter((rt) => !["NZ_PAYE_BAND", "NZ_TAX_CODE", "NZ_ESCT_BAND"].includes(rt));
  const rules = ["NZ_PAYE_METHOD", "NZ_SECONDARY_RATE", "NZ_ND_RATE", "NZ_IETC", "NZ_CS_VARIATION", "NZ_LUMP_SUM",
    "NZ_HOLIDAY_ADVANCE", "NZ_IRD_EXAMPLE", "NZ_PUBLIC_HOLIDAY", "NZ_ACC_CLASSIFICATION"];
  assert(console_.includes("def add_table_row"), "add_table_row missing");
  const missing = rules.filter((rt) => !ui.includes(rt));
  assert(missing.length === 0, `not offered: ${missing.join(", ")}`);
});

// ── governance in the UI ────────────────────────────────────────────────────
check("The generic Contribution Rates / Tax Slabs editors are hidden for NZ", () =>
  /hiddenTabs:\s*\[\s*"rates",\s*"slabs"\s*\]/.test(config));
check("Every change sends a reason and a source; signing is an explicit opt-in", () => {
  const form = files["components/jurisdiction/new_zealand/nzForm.js"];
  const shared = files["components/jurisdiction/new_zealand/nzShared.jsx"];
  assert(/reason: value\.reason\.trim\(\)/.test(form) && /sourceDocumentId: Number/.test(form), "payload");
  assert(/specialistVerified: Boolean\(value\.specialistVerified\)/.test(form), "verify flag");
  assert(/disabled=\{!reviewed\(chosen\)\}/.test(shared), "sign checkbox must need a reviewed source");
});
check("Editing is offered only on an editable pack version", () => {
  for (const f of ["NZPackRowsTab.jsx", "NZAuthorityTablesTab.jsx", "NZEarningClassTab.jsx"]) {
    assert(files[`components/jurisdiction/new_zealand/${f}`].includes("isEditablePack(pack)"), f);
  }
});
check("Editable statuses match the backend's editable pack statuses", () => {
  const service = readBackend("app/modules/payroll/service.py");
  const backend = /_EDITABLE_PACK_STATUSES = \(([^)]+)\)/.exec(service)[1];
  const ui = /EDITABLE_PACK_STATUSES = \[([^\]]+)\]/.exec(contentJs)[1];
  const norm = (s) => s.replace(/["'\s]/g, "").split(",").filter(Boolean).sort().join(",");
  assert(norm(backend) === norm(ui), `${backend} vs ${ui}`);
});
check("No value is shown as configured while it is pending", () =>
  files["components/jurisdiction/new_zealand/NZPackRowsTab.jsx"].includes('value === "PENDING_G1"'));

// ── P7c: organisation client ↔ nz_org_router ──────────────────────────────────
const payrollService = read("service/payrollService.js");
const nzOrgBlock = payrollService.slice(payrollService.indexOf('const NZ = "/api/payroll/new-zealand";'));
const orgRouter = readBackend("app/modules/payroll/nz_org_router.py");
const orgPrefix = /APIRouter\(prefix="([^"]+)"/.exec(orgRouter)?.[1];
const orgRoutes = new Set([...orgRouter.matchAll(/@router\.(get|post|put|patch|delete)\(\s*"([^"]+)"/g)]
  .map(([, method, path]) => `${method.toUpperCase()} ${orgPrefix}${path.replace(/\{[^}]+\}/g, "{}")}`));
const orgCalls = [...nzOrgBlock.matchAll(/api\.(get|post|put|patch|delete)\(\s*`\$\{NZ\}([^`]+)`/g)]
  .map(([, method, path]) => `${method.toUpperCase()} /new-zealand${path.replace(/\$\{[^}]+\}/g, "{}")}`);

check("The NZ organisation client covers every organisation route", () => {
  const missing = [...orgRoutes].filter((route) => !orgCalls.includes(route));
  assert(orgPrefix === "/new-zealand" && missing.length === 0, `no client for: ${missing.join(" | ")}`);
});
check("Every NZ organisation client call matches a declared route", () => {
  const unknown = orgCalls.filter((call) => !orgRoutes.has(call));
  assert(orgCalls.length > 0 && unknown.length === 0, unknown.join(" | "));
});

// ── P7c: privacy of the IRD number and family-violence leave (NZ-023) ────────
const irdField = files["modules/payroll/Payroll_Employees/NZIrdNumberField.jsx"];
const centre = files["modules/payroll/Compliances/NZComplianceCentreTab.jsx"];
check("IRD numbers are typed into password fields and cleared before the request", () => {
  for (const [name, text] of [["NZIrdNumberField", irdField], ["NZComplianceCentreTab", centre]]) {
    assert(/type="password"/.test(text) && /autoComplete="off"/.test(text), `${name}: password input`);
    assert(/setNumber\(""\);\s*\/\/ never keep the typed digits around/.test(text), `${name}: cleared before request`);
  }
});
check("Revealed IRD digits live only in component state and expire", () => {
  assert(/setTimeout\(\(\) => setRevealed\(null\), REVEAL_SECONDS \* 1000\)/.test(irdField), "timer");
  assert(/useEffect\(\(\) => \(\) => \{\s*clearTimeout\(timer\.current\);\s*setRevealed\(null\);/.test(irdField), "wipe on unmount");
  const all = NZ_FILES.map((f) => files[f]).join("\n");
  assert(!/localStorage|sessionStorage|console\.(log|info|debug)/.test(all), "no storage / console");
});
check("Family-violence leave is never asked for a reason and shows only as restricted", () => {
  const all = NZ_FILES.map((f) => files[f]).join("\n");
  const lines = all.replace(/never records a reason/g, "").split("\n");
  const offending = lines.filter((line) => /family[_ ]violence/i.test(line) && /reason/i.test(line)
    && !/Grant reason|revoked|Permission granted/.test(line));
  assert(offending.length === 0, `a family-violence reason prompt: ${offending.join(" | ")}`);
  assert(files["modules/payroll/Payroll_Employees/NZLeaveSections.jsx"].includes('"Restricted leave"'), "restricted label");
});
check("Legal entitlements are shown apart from the planning view", () =>
  files["modules/payroll/Payroll_Employees/NZLeaveSections.jsx"].includes('data-testid="nz-planning-view"'));
check("Leave pay shows both candidates and the chosen one", () => {
  const leave = files["modules/payroll/Payroll_Employees/NZLeaveSections.jsx"];
  return leave.includes("r.candidateA, r.candidateB") && leave.includes("r.statutoryReason");
});
check("Every NZ write form carries a reason (NZ-024)", () => {
  const panel = files["modules/payroll/Payroll_Employees/NewZealandStatutoryProfilePanel.jsx"];
  // one REASON_FIELD per write form: tax profile, KiwiSaver, work pattern, opening balance |
  // employer profile | employment, rehire, cash-up, final pay
  const count = (text) => (text.match(/^\s*REASON_FIELD,$/gm) || []).length;
  const leave = files["modules/payroll/Payroll_Employees/NZLeaveSections.jsx"];
  assert(count(panel) === 4 && count(centre) === 1 && count(leave) === 4,
    `reason fields: panel ${count(panel)}, centre ${count(centre)}, leave ${count(leave)}`);
});
check("The NZ Compliance Centre tab and the employee panel are mounted", () => {
  const compliance = read("modules/payroll/Compliances/CompliancePage.jsx");
  const employee = read("modules/payroll/Payroll_Employees/EmployeeDetailPanel.jsx");
  assert(compliance.includes("<NZComplianceCentreTab />") && /isNewZealand \? \[NZ_TAB\]/.test(compliance), "compliance tab");
  assert(employee.includes('employee.countryCode === "NZ"') && employee.includes("<NewZealandStatutoryProfilePanel"), "employee panel");
});

// ── P7d: runs and the shared leave screens ───────────────────────────────────
check("The NZ payslip breakdown and preflight are mounted on run details", () => {
  const runs = read("modules/payroll/PayRollRuns/RunDetailPanel.jsx");
  assert(/=== "NZ" && item\.nzCalculationSnapshot && <NZPayslipBreakdown/.test(runs), "breakdown");
  assert(/=== "NZ"\) && <NZRunPreflightPanel runId=\{run\.id\} \/>/.test(runs), "preflight");
});
check("The payslip breakdown only reads the frozen result (no frozen inputs, no recalculation)", () => {
  const breakdown = files["modules/payroll/PayRollRuns/NZPayslipBreakdown.jsx"];
  assert(!/frozenContext|calculate|api\./.test(breakdown), "breakdown must only render the snapshot");
  assert(breakdown.includes('"RESTRICTED_LEAVE" ? "Restricted leave"'), "restricted leave lines stay masked");
});
check("Special runs and corrections are reachable from the NZ Compliance Centre", () =>
  centre.includes("<NZPaymentsSection />"));

// ── P8: payday filing, remittance, run exceptions, journal ──────────────────
const filingSection = files["modules/payroll/Compliances/NZFilingRemittanceSection.jsx"];
const runFiling = files["modules/payroll/PayRollRuns/NZRunFilingPanel.jsx"];
check("Filing / remittance and the run exceptions panel are mounted", () => {
  const runs = read("modules/payroll/PayRollRuns/RunDetailPanel.jsx");
  assert(centre.includes("<NZFilingRemittanceSection />"), "compliance centre");
  assert(/<NZRunFilingPanel runId=\{run\.id\}/.test(runs), "run details");
});
check("Only the exceptions the backend can approve are offered (never a minimum-wage failure)", () => {
  const backend = readBackend("app/modules/payroll/nz_lifecycle.py");
  const server = /APPROVABLE_EXCEPTIONS = \(([^)]*)\)/.exec(backend)?.[1].match(/"([A-Z_]+)"/g).map((s) => s.slice(1, -1));
  const client = /const APPROVABLE = \[([^\]]*)\]/.exec(runFiling)?.[1].match(/"([A-Z_]+)"/g).map((s) => s.slice(1, -1));
  assert(JSON.stringify(server) === JSON.stringify(client), `server ${server} vs client ${client}`);
  assert(!/NZ_MIN_WAGE_FAIL/.test(runFiling.replace(/\/\/.*$/gm, "")), "min-wage code in the panel");
});
check("The journal account map edits exactly the backend's account keys", () => {
  const backend = readBackend("app/modules/payroll/nz_journal.py");
  const block = backend.slice(backend.indexOf("ACCOUNT_KEYS = ("), backend.indexOf(")", backend.indexOf("ACCOUNT_KEYS = (")));
  const server = [...block.matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
  const client = [...filingSection.slice(filingSection.indexOf("const ACCOUNT_FIELDS"))
    .matchAll(/\["([a-z_]+)", "/g)].map((m) => m[1]);
  assert(server.length === 9 && JSON.stringify(server) === JSON.stringify(client), `${server} vs ${client}`);
});
check("P8 writes carry a reason and no screen edits a filed or owed amount", () => {
  assert(/payment_reference: v\.reference, reason: v\.reason/.test(filingSection), "settlement reason");
  assert(/setNzJournalAccounts\(Number\(selected\), accounts, reason\)/.test(filingSection), "account map reason");
  assert(/requestNzRunException\(runId, \{ code, payslip_item_id: item\.id, reason \}\)/.test(runFiling), "exception reason");
  assert(!/api\.|updateNzFiling|updateNzRemittance/.test(filingSection + runFiling), "no direct or amount-editing calls");
});
check("NZ leave types are exactly the ones the backend accepts", () => {
  const leaveService = readBackend("app/modules/payroll/nz_leave_service.py");
  const requestBlock = leaveService.slice(leaveService.indexOf("NZ_REQUEST_TYPES = {"), leaveService.indexOf("}", leaveService.indexOf("NZ_REQUEST_TYPES = {")));
  const backend = [...requestBlock.matchAll(/"([a-z_]+)":/g)].map((m) => m[1]);
  backend.push("nz_family_violence");                       // keyed by the FAMILY_VIOLENCE_REQUEST constant
  const passthrough = /NZ_PASSTHROUGH_TYPES = \(([^)]+)\)/.exec(leaveService)[1].match(/"([a-z_]+)"/g).map((x) => x.replace(/"/g, ""));
  const options = files["components/jurisdiction/new_zealand/nzOrgOptions.js"];
  const ui = [...options.slice(options.indexOf("NZ_LEAVE_REQUEST_TYPES = ["), options.indexOf("];", options.indexOf("NZ_LEAVE_REQUEST_TYPES = [")))
    .matchAll(/key: "([a-z_]+)"/g)].map((m) => m[1]).concat(options.includes("key: NZ_FAMILY_VIOLENCE") ? ["nz_family_violence"] : []);
  const want = [...new Set([...backend, ...passthrough])].sort();
  assert(JSON.stringify([...new Set(ui)].sort()) === JSON.stringify(want), `ui ${[...new Set(ui)].sort()} vs backend ${want}`);
});
check("The leave form gives NZ employees the NZ types and never sends a family-violence reason", () => {
  const leaves = read("modules/payroll/Attendance/Payroll_Leaves.jsx");
  assert(/applyIsNz \? NZ_LEAVE_REQUEST_TYPES : LEAVE_TYPES/.test(leaves), "NZ types for NZ employees only");
  assert(/reason: applyForm\.leaveType === NZ_FAMILY_VIOLENCE \? undefined : applyForm\.reason/.test(leaves), "reason not sent");
  assert(/applyForm\.leaveType === NZ_FAMILY_VIOLENCE \? \(/.test(leaves) && leaves.includes('data-testid="nz-fv-no-reason"'),
    "reason box hidden");
  assert(/reason: lt\.key === NZ_FAMILY_VIOLENCE \? "" : f\.reason/.test(leaves), "reason cleared on switching to it");
});
check("Shared leave screens label NZ types and mark balances as a planning view", () => {
  assert(/\.\.\.NZ_LEAVE_LABELS/.test(read("modules/payroll/Attendance/LeaveRequestsTab.jsx")), "labels");
  assert(read("modules/payroll/Attendance/LeaveBalancesTab.jsx").includes('data-testid="nz-planning-view-note"'), "planning note");
  assert(/restricted: "Restricted leave"/.test(files["components/jurisdiction/new_zealand/nzOrgOptions.js"]), "restricted label");
});

// ── mounting ────────────────────────────────────────────────────────────────
check("The NZ Super Admin page is routed", () => {
  const app = read("App.jsx");
  return app.includes('path="/super-admin/compliance/new-zealand"') && app.includes("<NZCompliancePage />");
});
check("The NZ page is exported and slugged new-zealand", () => {
  const index = read("pages/JurisdictionCompliance/index.js");
  return index.includes('NZCompliancePage } from "./NZCompliancePage"') && /NZ: "new-zealand"/.test(index);
});
check("NZ has a flag and labels", () =>
  /NZ: NewZealand/.test(read("components/jurisdiction/CountryFlag.jsx"))
  && (read("utils/jurisdictionLabels.js").match(/\bNZ: "/g) || []).length >= 2);
check("Every NZ source file is reachable from an import", () => {
  const all = walk(SRC).filter((p) => /\.(jsx?|mjs)$/.test(p)).map((p) => readFileSync(p, "utf-8")).join("\n");
  const orphans = NZ_FILES.filter((f) => {
    const base = f.split("/").pop().replace(/\.(jsx|js)$/, "");
    return !new RegExp(`from ["'][^"']*/${base}["']`).test(all);
  });
  assert(orphans.length === 0, orphans.join(", "));
});

console.log(`nz-compliance-ui-validation: ${passed} passed, ${failures.length} failed`);
for (const failure of failures) console.log(`  FAIL ${failure}`);
process.exit(failures.length ? 1 : 0);
