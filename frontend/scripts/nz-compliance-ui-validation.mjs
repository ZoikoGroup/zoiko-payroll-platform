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
