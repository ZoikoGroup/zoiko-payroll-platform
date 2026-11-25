#!/usr/bin/env node
/**
 * Germany Super Admin compliance page on the shared pack layout.
 *
 *  - DECompliancePage renders JurisdictionLayout with the Germany config;
 *  - the generic rates / slabs editors are replaced by Germany's own tabs:
 *    Overview | Contributions | Tax Slabs | Policy | Readiness (+ the shared
 *    Organizations / Versions / Audit), with the rest in the "More" menu;
 *  - every earlier Germany section (old ?section= keys, overview cards) maps to
 *    a tab that exists, and /germany/registries keeps working;
 *  - no statutory number is typed in any new Germany UI file (values come from
 *    the API, which reads the registries and the engine constants);
 *  - the wage-tax warning is the backend's text, and every service function a
 *    Germany file imports is exported, with its API path present in the router.
 * Does not import .jsx (the Vite graph is heavy on this machine).
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(__dirname, "..", "src");
const BACKEND = resolve(__dirname, "..", "..", "backend", "app");
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

const DIR = "pages/JurisdictionCompliance/components/germany";
const NEW_FILES = ["DEContributionsTab.jsx", "DETaxSlabsTab.jsx", "DEPolicyTab.jsx", "DEReadinessTab.jsx", "DEOverviewTab.jsx",
  "deShared.js"].map((f) => `${DIR}/${f}`);
const CONFIG = "config/jurisdictions/germanyComplianceConfig.jsx";
const PAGE = "pages/JurisdictionCompliance/DECompliancePage.jsx";
const config = read(CONFIG);
const page = read(PAGE);
const shared = read(`${DIR}/deShared.js`);

check("the page renders the shared layout with the Germany config", () => {
  assert(page.includes("<JurisdictionLayout") && page.includes('country="DE"'), "JurisdictionLayout country DE");
  assert(page.includes("extraTabs={germanyExtraTabs}") && page.includes("{...germanyComplianceConfig}"), "config spread");
  assert(/hiddenTabs: \["rates", "slabs"\]/.test(config), "generic rates / slabs hidden");
  assert(/adaptiveTabs: true/.test(config), "adaptive tab row (More menu)");
});

const PRIMARY = ["de-rates", "de-slabs", "de-policy", "de-readiness"];
check("primary tabs: Overview | Contributions | Tax Slabs | Policy | Readiness", () => {
  const tabs = [...config.matchAll(/\btab\("(de-[a-z-]+)", "([^"]+)", \w+, "([a-z-]+)"/g)];
  assert(tabs.map((m) => m[1]).join() === PRIMARY.join(), `keys ${tabs.map((m) => m[1]).join()}`);
  assert(tabs.map((m) => m[2]).join() === "Contributions,Tax Slabs,Policy,Readiness", "labels");
  assert(tabs.map((m) => m[3]).join() === ["overview", ...PRIMARY.slice(0, -1)].join(), "anchors");
  const hidden = (config.match(/hiddenTabs: \[([^\]]*)\]/) || [])[1] || "";
  for (const key of ["overview", "organizations", "versions", "audit"]) assert(!hidden.includes(key), `${key} hidden`);
});

const MORE = ["de-deuv", "de-elstam", "de-elster", "de-payroll-summary", "de-sources", "de-levies", "de-registry-audit"];
check("More menu: DEÜV, ELStAM, ELSTER, Payroll Summary, Source Evidence (+ levies, registry audit)", () => {
  const keys = [...config.matchAll(/\bmore\("(de-[a-z-]+)"/g)].map((m) => m[1]);
  assert(keys.join() === MORE.join(), `more keys ${keys.join()}`);
});

check("every earlier Germany section maps to a tab that exists", () => {
  const known = new Set(["overview", "organizations", "versions", "audit", ...PRIMARY, ...MORE]);
  const aliases = [...shared.matchAll(/^\s+"?([a-z-]+)"?: "([a-z-]+)",$/gm)].map((m) => [m[1], m[2]]);
  assert(aliases.length >= 15, "aliases parsed");
  for (const [from, to] of aliases) assert(known.has(to), `${from} -> ${to} is not a tab`);
  const aliasKeys = new Set(aliases.map(([from]) => from));
  const overview = read(`${DIR}/DEOverviewDashboard.jsx`);
  const areaKeys = [...overview.matchAll(/key: "([a-z-]+)", label:/g)].map((m) => m[1]);
  assert(areaKeys.length >= 10, "overview cards parsed");
  for (const key of [...areaKeys, "audit"]) assert(aliasKeys.has(key), `overview card ${key} has no tab`);
  const registries = read("pages/JurisdictionCompliance/GermanyStatutoryRegistriesPage.jsx");
  const regTabs = [...(registries.match(/export const TABS = \[([\s\S]*?)\];/) || [])[1].matchAll(/key: "([a-z-]+)"/g)].map((m) => m[1]);
  for (const key of regTabs) assert(aliasKeys.has(key), `registries tab ${key} has no tab`);
  assert(/tabAliases: GERMANY_TAB_ALIASES/.test(config), "aliases wired into the layout");
  assert(page.includes('searchParams.get("section")') && page.includes("<Navigate replace"), "?section= links rewritten");
});

check("/germany/registries redirects to the tab holding its default (PAP) section", () => {
  const app = read("App.jsx");
  const route = app.split(/\r?\n/).find((line) => line.includes('path="/super-admin/compliance/germany/registries"')) || "";
  assert(route.includes('<Navigate replace to="/super-admin/compliance/germany?tab=de-slabs"'), `route: ${route}`);
  assert(/pap: "de-slabs"/.test(shared), "pap lives in Tax Slabs");
});

check("Tax Slabs shows the tariff that applies to the pack; any other is collapsed and labelled not used", () => {
  const tab = read(`${DIR}/DETaxSlabsTab.jsx`);
  assert(tab.includes("getGermanyWageTaxTariff(pack.id)"), "tariff loaded for the selected pack");
  assert(tab.includes("v.appliesToPack") && tab.includes("<TariffZones version={applies} />"), "applying tariff shown open");
  assert(tab.includes('"Historical" : "Other tariff"}: not used for this pack') && /<Collapsible key=\{v\.taxYear\}/.test(tab),
    "other tariffs collapsed and labelled");
  assert(!/inForceToday|tariff.provenance/.test(tab), "not chosen by today's date or the module provenance constant");
  assert(read(`${DIR}/DEOverviewTab.jsx`).includes("v.appliesToPack"), "overview counts the pack's tariff");
});

check("every registry editor stays reachable from a tab", () => {
  const all = [config, ...NEW_FILES.map(read)].join("\n");
  for (const name of ["PapTab", "HealthFundsTab", "ContributionCeilingsTab", "PvConfigTab", "MinijobMidijobParametersTab",
    "EarningTaxabilityTab", "OvertimePremiumCategoriesTab", "OvertimeGrundlohnCapsTab", "ChurchTaxTab", "EmployerLeviesTab",
    "ElstamBatchesTab", "ElsterTab", "SourceEvidenceTab", "AuditTab", "GermanyDeuvTab", "CompletenessPanel", "DEOverviewDashboard"]) {
    assert(new RegExp(`<${name}\\b`).test(all), `${name} not rendered`);
  }
});

check("no statutory number typed in the new Germany UI files", () => {
  for (const file of [...NEW_FILES, CONFIG, PAGE]) {
    const code = read(file)
      .replace(/^\s*\/\/.*$/gm, "")                         // comments
      .replace(/className=\{?[`"][^`"]*[`"]\}?/g, "")      // Tailwind classes
      .replace(/"(?:[^"\\]|\\.)*(?:px-|py-|text-\[|rounded|border|bg-)(?:[^"\\]|\\.)*"/g, "");
    const hits = code.match(/(?<![\w-])\d+(?:\.\d+)?\s*%|(?<![\w.#-])\d{2,}(?:\.\d+)?(?![\w-])/g) || [];
    assert(hits.length === 0, `${file}: ${hits.slice(0, 5).join(", ")}`);
  }
});

check("the wage-tax warning is the backend's text", () => {
  const backend = readBackend("modules/payroll/germany_overview.py");
  const text = (backend.match(/UNCERTIFIED_TARIFF_WARNING = \(\s*"([^"]+)"\s*"([^"]+)"\s*\)/) || []).slice(1).join("");
  const tariff = (shared.match(/DE_TARIFF_WARNING = "([^"]+)"/) || [])[1];
  const none = (shared.match(/DE_NO_PAP_RELEASE = "([^"]+)"/) || [])[1];
  assert(text && text === `${tariff} ${none}`, `backend "${text}" vs UI "${tariff} ${none}"`);
  for (const file of ["DETaxSlabsTab.jsx", "DEReadinessTab.jsx", "DEOverviewTab.jsx"]) {
    const src = read(`${DIR}/${file}`);
    assert(/DEWageTaxWarning|loadPapWarning/.test(src), `${file} shows the warning`);
  }
});

check("service functions exist and their API paths are in the router", () => {
  const service = read("service/superAdminService.js");
  const router = readBackend("modules/super_admin/router.py");
  for (const file of [...NEW_FILES, CONFIG]) {
    const imports = [...read(file).matchAll(/import \{([^}]+)\} from "[./]+\/service\/superAdminService"/g)]
      .flatMap((m) => m[1].split(",").map((s) => s.trim()).filter(Boolean));
    for (const name of imports) assert(new RegExp(`export const ${name}\\b`).test(service), `${file}: ${name} not exported`);
  }
  for (const path of ["/compliance/germany/compliance-pack/{pack_id}/contributions", "/compliance/germany/wage-tax-tariff"]) {
    assert(router.includes(`"${path}"`), `router path ${path}`);
  }
});

check("shared summary: the attention lines are optional (other countries unchanged)", () => {
  const summary = read("components/jurisdiction/PackOverviewSummary.jsx");
  assert(/stats = null, attention = null \}\)/.test(summary), "attention defaults to null");
  assert(/extraAttention\.length > 0/.test(summary), "box shown only with lines");
});

console.log(`de-compliance-ui-validation: ${passed} passed, ${failures.length} failed`);
if (failures.length) {
  for (const f of failures) console.log(`  ✗ ${f}`);
  process.exit(1);
}
