#!/usr/bin/env node
/**
 * ZP-BE-ENG-001 (Belgium) Phase 3B — Super Admin console validation.
 *
 *  - the Belgium page, route, export and route-map entry exist;
 *  - the generic "rates" / "slabs" editors are hidden;
 *  - no hard-coded statutory number appears in any Belgium UI file;
 *  - no content key name (be_*) and no vocabulary value from the backend
 *    catalogue (engine/countries/belgium_content.py) appears in beShared.js or a
 *    BE component — groups, labels, vocabularies and specs come from the API;
 *  - every superAdminService function a Belgium file imports is exported, and
 *    every Belgium API path the service uses exists in the backend router.
 * Block A4 (organisation and employee screens):
 *  - the Compliance Centre tab and the employee "Manage" button are wired for BE only;
 *  - the same number / vocabulary / arithmetic rules hold for the org files
 *    (choice lists come from /belgium/options, committees from /joint-committees);
 *  - every payrollService function a Belgian org file imports is exported, and
 *    every /api/payroll/belgium path it uses exists in be_org_router.py;
 *  - an identifier is never put in storage, the URL or the console.
 * Does not import .jsx (the Vite graph is heavy on this machine).
 */
import { readFileSync, readdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(__dirname, "..", "src");
const BACKEND = resolve(__dirname, "..", "..", "backend", "app");
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

const BE_DIR = "components/jurisdiction/belgium";
const componentFiles = readdirSync(resolve(SRC, BE_DIR)).filter((f) => /\.(jsx?|mjs)$/.test(f)).map((f) => `${BE_DIR}/${f}`);
const uiFiles = [...componentFiles, "config/jurisdictions/belgiumComplianceConfig.jsx",
  "pages/JurisdictionCompliance/BECompliancePage.jsx"];

check("page, export, route map and routes exist", () => {
  assert(/export \{ default as BECompliancePage \} from "\.\/BECompliancePage"/.test(read("pages/JurisdictionCompliance/index.js")), "export");
  assert(/^\s*BE: "belgium",\r?$/m.test(read("pages/JurisdictionCompliance/index.js")), "COUNTRY_CODE_TO_ROUTE BE");
  const app = read("App.jsx");
  assert(app.includes('path="/super-admin/compliance/belgium"') && app.includes('path="/super-admin/compliance/belgium/:state"'), "routes");
  assert(/BECompliancePage,/.test(app), "App imports the page");
});

check("generic rates / slabs editors are hidden", () => {
  assert(/hiddenTabs: \["rates", "slabs"\]/.test(read("config/jurisdictions/belgiumComplianceConfig.jsx")), "hiddenTabs");
});

const beConfig = read("config/jurisdictions/belgiumComplianceConfig.jsx");
const PRIMARY_TABS = ["be-rates", "be-slabs", "be-policy", "be-release"];
const MORE_TABS = ["be-holiday-pay", "be-wages-time", "be-absence", "be-public-holidays", "be-earning",
  "be-joint-committees", "be-sources"];

check("primary tabs: Overview | Contributions | Tax Slabs | Policy | Readiness (+ shared tabs)", () => {
  const keys = [...beConfig.matchAll(/\btab\("(be-[a-z-]+)", "([^"]+)"[^,]*, [^,]*, "([a-z-]+)"/g)];
  assert(keys.map((m) => m[1]).join() === PRIMARY_TABS.join(), `primary tab keys: ${keys.map((m) => m[1]).join(", ")}`);
  assert(keys.map((m) => m[2]).join() === "Contributions,Tax Slabs,Policy,Readiness",
    `labels: ${keys.map((m) => m[2]).join(", ")}`);
  // each anchors after the previous one, starting after Overview
  assert(keys.map((m) => m[3]).join() === ["overview", ...PRIMARY_TABS.slice(0, -1)].join(), "anchors");
  // the shared Organizations / Versions / Audit tabs are not hidden
  const hidden = (beConfig.match(/hiddenTabs: \[([^\]]*)\]/) || [])[1] || "";
  for (const shared of ["organizations", "versions", "audit", "overview"]) assert(!hidden.includes(shared), `${shared} hidden`);
});

check("data tabs live in the More menu and the tab row never scrolls sideways", () => {
  const keys = [...beConfig.matchAll(/\bmore\("(be-[a-z-]+)"/g)].map((m) => m[1]);
  assert(keys.join() === MORE_TABS.join(), `More tabs: ${keys.join(", ")}`);
  assert(/overflow: true/.test(beConfig), "More tabs are flagged overflow");
  assert(/adaptiveTabs: true/.test(beConfig), "adaptive tab row");
  // Same layout as every country: the pack list in the LEFT column (240px, all compliance pages) at
  // every width; tabs that do not fit overflow from the end into More (measured in headless Chrome).
  assert(!/compactUntilWide/.test(beConfig), "no stacked pack chips (commit h reverted)");
  const layoutSrc = read("components/jurisdiction/JurisdictionLayout.jsx");
  assert(layoutSrc.includes('<div className="grid grid-cols-1 gap-4 lg:grid-cols-[240px_1fr]">')
    && !/compactUntilWide|iconsWhenWide/.test(layoutSrc), "left-column layout for every country");
  assert(!/iconsWhenWide|min-\[1760px\]/.test(read("components/jurisdiction/PackTabBar.jsx")), "tab icons always shown");
  const layout = read("components/jurisdiction/JurisdictionLayout.jsx");
  assert(/visibleExtraTabs\.filter\(\(t\) => t\.overflow\)/.test(layout) && /adaptive=\{adaptiveTabs\}/.test(layout), "layout wiring");
  const bar = read("components/jurisdiction/PackTabBar.jsx");
  assert(/const active = tabs\.find\(\(t\) => t\.key === activeKey\)/.test(bar) && /<MoreContent tab=\{active\}/.test(bar),
    "More shows the selected tab's name");
});

check("activation readiness, signing status and owner decisions are sections of Release Readiness", () => {
  const release = read("components/jurisdiction/belgium/BEReleaseReadinessTab.jsx");
  for (const name of ["BEActivationReadinessTab", "BESigningStatusTab", "BEOwnerDecisionsTab", "GoldenCertification", "GateEvidence"]) {
    assert(release.includes(`<${name}`), `${name} rendered`);
  }
  assert((release.match(/<Collapsible/g) || []).length >= 5, "gate cards and sections are collapsible");
  assert(/list-disc/.test(release) && /c\.detail/.test(release), "failing checks listed as bullets");
  for (const old of ["be-activation", "be-signing", "be-decisions"]) assert(!new RegExp(`tab\\("${old}"`).test(beConfig), `${old} still a tab`);
});

check("old tab keys redirect to the tab that now holds them", () => {
  const aliases = Object.fromEntries([...beConfig.matchAll(/"(be-[a-z-]+)": "(be-[a-z-]+)"/g)].map((m) => [m[1], m[2]]));
  const expected = { "be-withholding": "be-slabs", "be-onss-employee": "be-rates", "be-onss-employer": "be-rates",
    "be-activation": "be-release", "be-signing": "be-release", "be-decisions": "be-release" };
  for (const [from, to] of Object.entries(expected)) assert(aliases[from] === to, `${from} -> ${aliases[from]}`);
  for (const to of Object.values(aliases)) assert([...PRIMARY_TABS, ...MORE_TABS].includes(to), `alias target ${to}`);
  assert(/tabAliases: BELGIUM_TAB_ALIASES/.test(beConfig), "aliases passed to the layout");
});

check("Contribution Rates / Tax Slabs use the shared tables and the governed editor", () => {
  const tables = read("components/jurisdiction/belgium/BEPackTables.jsx");
  assert(/import \{ ContributionRatesTable, PackTableHeader, TaxSlabsTable \} from "\.\.\/PackRowTables"/.test(tables), "shared tables");
  assert(tables.includes("<BERowEditor") && !/upsertCanonical|deleteCanonical/.test(tables), "governed editor only");
  assert(/locked=\{isActive\(pack\)\}/.test(tables) && (tables.match(/actionsDisabled=\{isActive\(pack\)\}/g) || []).length === 2,
    "Active pack locked: icons shown disabled on both tables");
  assert(/const HIDDEN_COLUMNS = \["state", "filingStatus"\]/.test(tables)
    && (tables.match(/hideColumns=\{HIDDEN_COLUMNS\}/g) || []).length === 2, "State / Filing Status hidden on both tables");
  for (const col of ["statusColumn", "inForceColumn", '"dimension"', '"amount"', '"formula"']) assert(tables.includes(col), `${col} kept`);
});

check("Overview cards count Belgium's configuration rows (signed vs pending), other countries unchanged", () => {
  const shared = read("components/jurisdiction/belgium/beShared.js");
  assert(/export function beOverviewCounts\(config\)/.test(shared) && shared.includes("pending: rows.filter((r) => !r.signed).length"),
    "counts from config rows' signed flag");
  assert(shared.includes("TAB_GROUPS.onssEmployee") && shared.includes("TAB_GROUPS.onssEmployer"), "groups from TAB_GROUPS, no key names");
  const overview = read("components/jurisdiction/belgium/BEOverviewDashboard.jsx");
  assert(/stats=\{stats\}/.test(overview) && overview.includes("loadConfiguration(pack)"), "BE passes its own cards");
  const summary = read("components/jurisdiction/PackOverviewSummary.jsx");
  assert(summary.includes("stats = null") && summary.includes("{stats ? stats.map("), "generic cards unless a country passes stats");
});

check("Hotfix Activate is hidden for Belgium (self-approval refused), like Mexico", () => {
  assert(/hideHotfixActivate: true/.test(beConfig), "hideHotfixActivate");
  assert(/!hideHotfixActivate && selectedPack\.status !== "Active"/.test(read("components/jurisdiction/JurisdictionLayout.jsx")), "layout honours it");
});

check("Overview is the shared pack summary plus the engine chip; shared country-level label", () => {
  const overview = read("components/jurisdiction/belgium/BEOverviewDashboard.jsx");
  assert(/<PackOverviewSummary/.test(overview) && /extraFlags=\{<EngineChip/.test(overview), "summary + chip");
  assert(/onNavigateTab\?\.\("be-release"\)/.test(overview), "chip opens Release Readiness");
  assert(!/countryLevelLabel/.test(beConfig), "uses the shared Country-level (no state) label");
});

check("the activation readiness tab is read-only", () => {
  const tab = read("components/jurisdiction/belgium/BEActivationReadinessTab.jsx");
  const imports = (tab.match(/import \{([^}]*)\} from "\.\.\/\.\.\/\.\.\/service\/superAdminService"/) || [])[1] || "";
  assert(imports.trim() === "getBeActivationReadiness", `service imports: ${imports}`);
  assert(!/\b(apiFetch|fetch|axios)\s*\(/.test(tab), "the tab makes no direct request (only the read-only GET above)");
  const service = read("service/superAdminService.js");
  assert(/getBeActivationReadiness = \(packRowId\) =>\s*apiFetch\(`\$\{BE_SA\}\/packs\/\$\{packRowId\}\/activation-readiness`\)/.test(service), "GET only");
  const router = readFileSync(resolve(BACKEND, "modules/super_admin/router.py"), "utf-8");
  assert(router.includes('@router.get("/compliance/belgium/packs/{pack_row_id}/activation-readiness"'), "backend GET route");
});

check("with no Belgian pack the page offers the governed seed, not only the generic form", () => {
  const page = read("pages/JurisdictionCompliance/BECompliancePage.jsx");
  assert(/import \{ SeedDraftPanel \} from "\.\.\/\.\.\/components\/jurisdiction\/belgium\/BEOverviewDashboard"/.test(page),
    "BECompliancePage imports the governed SeedDraftPanel");
  assert(/listBePacks\(\)/.test(page) && /packs\.length === 0/.test(page), "shown only when the Belgium pack list is empty");
  assert(/export function SeedDraftPanel/.test(read("components/jurisdiction/belgium/BEOverviewDashboard.jsx")), "panel exported");
  const service = read("service/superAdminService.js");
  assert(/seedBeDraftPack = \(reason\) => apiFetch\(`\$\{BE_SA\}\/seed-draft`, \{ method: "POST"/.test(service), "seed-draft POST");
});

const STATUTORY_NUMBER = /\d+(?:[.,]\d+)?\s*%|EUR\s*\d|\b\d{1,3}(?:[.,]\d{3})*[.,]\d{2}\b|\b(?:13\.07|24\.92|108|5\.57|10\.27|2233|4000|92|38|40)\b/;
check("no hard-coded statutory number in Belgium UI files", () => {
  for (const file of uiFiles) {
    const code = read(file).replace(/\/\/.*$/gm, "").replace(/\/\*[\s\S]*?\*\//g, "");
    const strings = [...code.matchAll(/"([^"\n]*)"|'([^'\n]*)'|`([^`]*)`/g)].map((m) => m[1] ?? m[2] ?? m[3]);
    for (const s of strings) {
      // Tailwind classes and icon sizes are presentation, not statutory content.
      if (/^[a-z0-9 :/.[\]()-]+$/.test(s) && /\b(px|py|text|mt|mb|gap|grid|rounded|border|bg|max-w|col|p)-/.test(s)) continue;
      assert(!STATUTORY_NUMBER.test(s), `${file}: ${JSON.stringify(s)}`);
    }
  }
});

const content = readFileSync(resolve(BACKEND, "modules/payroll/engine/countries/belgium_content.py"), "utf-8");
const vocabTuples = ["WORKER_CATEGORIES", "PAY_FREQUENCIES", "PAY_BASES", "ROUNDING_RULES", "TREATMENTS",
  "DECLARATION_TYPES", "ACCUMULATORS", "COMPONENTS", "OBLIGATIONS"];
const vocabulary = new Set(["NOT_SUPPORTED", "SLAB_ROWS"]);
for (const name of vocabTuples) {
  const block = content.match(new RegExp(`^${name} = \\(([\\s\\S]*?)\\)\\s*(?:#.*)?$`, "m"));
  if (!block) failures.push(`belgium_content.py: ${name} not found`);
  else for (const m of block[1].matchAll(/"([A-Z0-9_]+)"/g)) vocabulary.add(m[1]);
}
check("vocabulary was extracted from the backend catalogue", () => assert(vocabulary.size > 60, `only ${vocabulary.size}`));

check("no content key name or vocabulary value in beShared.js / BE components", () => {
  for (const file of componentFiles) {
    const code = read(file);
    const key = code.match(/["'`]be_[a-z0-9_]+["'`]/);
    assert(!key, `${file}: content key ${key && key[0]}`);
    for (const m of code.matchAll(/["'`]([A-Z0-9_]{2,})["'`]/g)) {
      assert(!vocabulary.has(m[1]), `${file}: vocabulary value ${m[1]}`);
    }
  }
});

check("every superAdminService function a Belgium file imports exists", () => {
  const service = read("service/superAdminService.js");
  for (const file of uiFiles) {
    for (const m of read(file).matchAll(/import \{([^}]*)\} from "[./]*service\/superAdminService"/g)) {
      for (const name of m[1].split(",").map((s) => s.trim()).filter(Boolean)) {
        assert(new RegExp(`export (const|function|async function) ${name}\\b`).test(service), `${file}: ${name}`);
      }
    }
  }
});

check("every Belgium API path in superAdminService exists in the backend router", () => {
  const service = read("service/superAdminService.js");
  const router = readFileSync(resolve(BACKEND, "modules/super_admin/router.py"), "utf-8");
  const section = service.slice(service.indexOf('const BE_SA = "/api/super-admin/compliance/belgium";'));
  assert(section.length > 0, "BE section");
  const paths = [...section.matchAll(/\$\{BE_SA\}([^`"]*)/g)].map((m) => m[1].replace(/\$\{[^}]+\}/g, "{}"));
  assert(paths.length >= 10, `only ${paths.length} paths`);
  const routes = [...router.matchAll(/@router\.(?:get|post|put|delete)\("\/compliance\/belgium([^"]*)"/g)]
    .map((m) => m[1].replace(/\{[^}]+\}/g, "{}"));
  for (const path of paths) assert(routes.includes(path), `no backend route for ${path}`);
  assert(/BE\/statutory-summary/.test(section), "summary route");
});

check("no payroll arithmetic in Belgium UI files", () => {
  for (const file of uiFiles) {
    assert(!/\b(gross|net|withholding|contribution)\s*[*+-]/i.test(read(file)), `${file}: arithmetic on a payroll value`);
  }
});

// ── Block A4: organisation and employee screens ────────────────────────────
const ORG_FILES = ["modules/payroll/Compliances/BEComplianceCentreTab.jsx",
  "modules/payroll/Payroll_Employees/BelgiumStatutoryProfilePanel.jsx",
  "modules/payroll/Payroll_Employees/BEIdentifierField.jsx", "modules/payroll/Payroll_Employees/beOrgPayloads.js",
  // Block B3: run preflight, payslip breakdown, payment
  "modules/payroll/PayRollRuns/BERunPreflightPanel.jsx", "modules/payroll/PayRollRuns/BEPayslipBreakdown.jsx",
  "modules/payroll/PayRollRuns/BEPaymentPanel.jsx", "modules/payroll/PayRollRuns/bePayslipLines.js",
  // Block C1: filing centre, calendar, exception queue
  "modules/payroll/Compliances/BEFilingSettlementPanel.jsx",
  // Block C2: parallel cycles
  "modules/payroll/Compliances/BEParallelCyclesSection.jsx"];

check("A4: the Compliance Centre tab and the employee button are wired for BE", () => {
  const page = read("modules/payroll/Compliances/CompliancePage.jsx");
  assert(page.includes('import BEComplianceCentreTab from "./BEComplianceCentreTab";'), "tab import");
  assert(/isBelgium = normalizeCountryCode\(companyDetails\.jurisdictionCountry\) === "BE"/.test(page), "isBelgium");
  assert(page.includes("...(isBelgium ? [BE_TAB] : [])") && page.includes("currentTab === BE_TAB && <BEComplianceCentreTab />"),
    "tab listed and rendered");
  const panel = read("modules/payroll/Payroll_Employees/EmployeeDetailPanel.jsx");
  assert(panel.includes('employee.countryCode === "BE"') && panel.includes("setShowBeStatutory(true)"), "Manage button");
  assert(panel.includes("<BelgiumStatutoryProfilePanel employee={employee}"), "panel rendered");
});

check("B3: the run panels and the payslip are wired for BE only", () => {
  const panel = read("modules/payroll/PayRollRuns/RunDetailPanel.jsx");
  for (const name of ["BEPayslipBreakdown", "BERunPreflightPanel", "BEPaymentPanel"]) {
    assert(panel.includes(`import ${name} from "./${name}";`), `${name} import`);
  }
  assert(panel.includes('(item.country || item.countryCode) === "BE" && item.beCalculationSnapshot && <BEPayslipBreakdown'),
    "breakdown per BE payslip");
  assert(panel.includes('items.some((i) => (i.country || i.countryCode) === "BE") && <BERunPreflightPanel'), "preflight");
  assert(/=== "BE"\)\s*&& \["Approved", "Authorized", "Paid", "Closed"\]\.includes\(\(detail \|\| run\)\.status\)\s*&& <BEPaymentPanel/
    .test(panel), "payment panel only for a committed run");
  const stub = read("modules/payroll/PaySlips/PayslipStub.jsx");
  assert(stub.includes('=== "BE" ? payslip.beCalculationSnapshot : null') && stub.includes("beEmployeeLines(beSnapshot)"),
    "payslip stub BE branch");
  assert(stub.includes("beSnapshot.identifierMasked"), "masked national number on the payslip");
});

check("B3: net pay is never an input on a Belgian run screen", () => {
  for (const file of ["modules/payroll/PayRollRuns/BEPayslipBreakdown.jsx", "modules/payroll/PayRollRuns/BEPaymentPanel.jsx"]) {
    assert(!/<input/.test(read(file)), `${file}: an input field`);
  }
});

check("A4: no hard-coded statutory number in the org files", () => {
  for (const file of ORG_FILES) {
    const code = read(file).replace(/\/\/.*$/gm, "").replace(/\/\*[\s\S]*?\*\//g, "");
    const strings = [...code.matchAll(/"([^"\n]*)"|'([^'\n]*)'|`([^`]*)`/g)].map((m) => m[1] ?? m[2] ?? m[3]);
    for (const raw of strings) {
      const str = raw.replace(/\b[a-z-]+-\[[^\]]*\]/g, "");          // Tailwind arbitrary values (shadow-[...])
      if (/^[a-z0-9 :/.[\]()-]+$/.test(str) && /\b(px|py|text|mt|mb|gap|grid|rounded|border|bg|max-w|col|p)-/.test(str)) continue;
      assert(!STATUTORY_NUMBER.test(str), `${file}: ${JSON.stringify(str)}`);
    }
  }
});

// Org files name database columns such as be_component, so only the catalogue's
// own content keys (the KEYS dict of belgium_content.py) are refused there.
const contentKeys = new Set([...content.matchAll(/^\s+"(be_[a-z0-9_]+)": \(/gm)].map((m) => m[1]));
check("A4: the content key list was extracted from the backend catalogue", () =>
  assert(contentKeys.size > 60, `only ${contentKeys.size}`));
check("A4: no content key or catalogue vocabulary value in the org files", () => {
  for (const file of ORG_FILES) {
    const code = read(file);
    const key = [...code.matchAll(/["'`](be_[a-z0-9_]+)["'`]/g)].map((m) => m[1]).find((k) => contentKeys.has(k));
    assert(!key, `${file}: content key ${key}`);
    for (const m of code.matchAll(/["'`]([A-Z0-9_]{2,})["'`]/g)) {
      assert(!vocabulary.has(m[1]), `${file}: vocabulary value ${m[1]}`);
    }
  }
});

check("A4: no payroll arithmetic in the org files", () => {
  for (const file of ORG_FILES) {
    const code = read(file).replace(/\/\/.*$/gm, "").replace(/\/\*[\s\S]*?\*\//g, "");      // comments are prose
    assert(!/\b(gross|net|withholding|contribution|onss)\s*[*+\-/]/i.test(code), `${file}: arithmetic on a payroll value`);
  }
});

check("A4: an identifier never reaches storage, the URL or the console", () => {
  for (const file of ORG_FILES) {
    const code = read(file).replace(/\/\/.*$/gm, "").replace(/\/\*[\s\S]*?\*\//g, "");
    assert(!/localStorage|sessionStorage|console\.|window\.location|history\.push|searchParams/.test(code),
      `${file}: storage / URL / console use`);
  }
  const field = read("modules/payroll/Payroll_Employees/BEIdentifierField.jsx");
  assert(/type="password"/.test(field) && /autoComplete="off"/.test(field), "identifier input is masked");
  assert(/setValue\(""\)/.test(field) && /setTimeout\(\(\) => setRevealed\(null\)/.test(field), "typed value and reveal are wiped");
});

check("A4: every payrollService function a Belgian org file imports exists", () => {
  const service = read("service/payrollService.js");
  for (const file of ORG_FILES) {
    for (const m of read(file).matchAll(/import \{([^}]*)\} from "[./]*service\/payrollService"/g)) {
      for (const name of m[1].split(",").map((x) => x.trim()).filter(Boolean)) {
        assert(new RegExp(`export (const|function|async function) ${name}\\b`).test(service), `${file}: ${name}`);
      }
    }
  }
});

check("A4: every /api/payroll/belgium path in payrollService exists in be_org_router.py", () => {
  const service = read("service/payrollService.js");
  const start = service.indexOf('const BE = "/api/payroll/belgium";');
  assert(start >= 0, "BE section");
  const section = service.slice(start);
  const paths = [...section.matchAll(/\$\{BE\}([^`"]*)/g)].map((m) => m[1].replace(/\$\{[^}]+\}/g, "{}"));
  assert(paths.length >= 25, `only ${paths.length} paths`);
  const router = readFileSync(resolve(BACKEND, "modules/payroll/be_org_router.py"), "utf-8");
  const routes = [...router.matchAll(/@router\.(?:get|post|put|delete)\("([^"]*)"/g)].map((m) => m[1].replace(/\{[^}]+\}/g, "{}"));
  for (const path of paths) assert(routes.includes(path), `no backend route for ${path}`);
});

if (failures.length) {
  console.error(`Belgium console UI validation: ${failures.length} failure(s), ${passed} passed`);
  failures.forEach((f) => console.error(`  ✗ ${f}`));
  process.exit(1);
}
console.log(`Belgium console UI validation: ${passed} checks passed`);
