#!/usr/bin/env node
/**
 * ZP-ZA-ENG-001 Phase 6 frontend validation.
 *
 * Source-level checks for the dormant South Africa Super Admin compliance
 * surface. This intentionally does not import .jsx modules: the Vite graph
 * OOMs on this machine, and these assertions are about wiring and safety
 * constraints, not rendered markup.
 */
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

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

const config = read("config/jurisdictions/southAfricaComplianceConfig.jsx");
const page = read("pages/JurisdictionCompliance/ZACompliancePage.jsx");
const app = read("App.jsx");
const index = read("pages/JurisdictionCompliance/index.js");
const flag = read("components/jurisdiction/CountryFlag.jsx");
const certification = read("pages/TestCertificationPage.jsx");
const service = read("service/superAdminService.js");
const readiness = read("components/jurisdiction/southAfrica/ZAReadinessTab.jsx");
const overview = read("components/jurisdiction/southAfrica/ZAOverviewDashboard.jsx");
const matrix = read("components/jurisdiction/EarningClassMatrix.jsx");
const display = read("components/jurisdiction/southAfrica/zaComponentConfig.js");

function sourceExists(path) {
  return existsSync(resolve(SRC, path));
}

function tabKeys(text) {
  return [...text.matchAll(/tab\("([^"]+)",/g)].map((match) => match[1]);
}

check("South Africa config exports the page config and tab factory", () =>
  config.includes("export function southAfricaExtraTabs()") &&
  config.includes("export const southAfricaComplianceConfig"));

check("ZA tab factory takes no organization id (no ZA org picker endpoint exists)", () =>
  /export function southAfricaExtraTabs\(\)/.test(config) &&
  !/\b(orgId|organizationId|organization_id)\b/.test(config));

check("ZA tabs are ordered and include all Phase 6 surfaces", () => {
  const expected = [
    "za-paye",
    "za-contributions",
    "za-eti",
    "za-earning",
    "za-labour",
    "za-readiness",
    "sources",
    "tests",
  ];
  assert(JSON.stringify(tabKeys(config)) === JSON.stringify(expected), tabKeys(config).join(", "));
});

check("ZA page loads one stable tab list and owns the two country routes", () =>
  page.includes("const EXTRA_TABS = southAfricaExtraTabs();") &&
  page.includes("extraTabs={EXTRA_TABS}") &&
  page.includes("/super-admin/compliance/south-africa") &&
  app.includes('path="/super-admin/compliance/south-africa"') &&
  app.includes('path="/super-admin/compliance/south-africa/:state"') &&
  app.includes("<ZACompliancePage />"));

check("ZA page is exported and mapped from the compliance index", () =>
  index.includes('export { default as ZACompliancePage } from "./ZACompliancePage"') &&
  index.includes('ZA: "south-africa"'));

check("South Africa has a flag and a certification entry", () =>
  flag.includes("function SouthAfrica()") &&
  /\bZA:\s*SouthAfrica\b/.test(flag) &&
  certification.includes("South Africa (SARS)"));

check("ZA summary service calls the single supported summary endpoint", () =>
  service.includes("getZaSummary") &&
  service.includes('const ZA_SA = "/api/super-admin/compliance/south-africa"') &&
  service.includes("${ZA_SA}/summary"));

check("PAYE, UIF/SDL and ETI tabs consume canonical pack rows", () => {
  const paye = read("components/jurisdiction/southAfrica/ZAPayeTab.jsx");
  const contributions = read("components/jurisdiction/southAfrica/ZAContributionsTab.jsx");
  const eti = read("components/jurisdiction/southAfrica/ZAEtiTab.jsx");
  return paye.includes("slabs") && paye.includes("rates") &&
    contributions.includes("rates") &&
    eti.includes("slabs") && eti.includes("rates");
});

check("Earning classification uses the governed ZA_EARNING_CLASS slab shape", () => {
  assert(config.includes('ruleType="ZA_EARNING_CLASS"'), "missing ZA_EARNING_CLASS rule type");
  assert(/obligations=\{\["PAYE"[^\]]*"COIDA"\]\}/.test(config), "missing obligation list");
  assert(matrix.includes("row.taxRegime"), "matrix ignores taxRegime");
  assert(matrix.includes("row.filingStatus"), "matrix ignores filingStatus");
  assert(matrix.includes(".assessmentBasis"), "matrix ignores assessmentBasis");
});

check("Readiness renders server counts and never fabricates signed gates", () =>
  readiness.includes("getZaSummary") &&
  readiness.includes("data.activeEmployerRegistrations") &&
  readiness.includes("data.approvedDirectives") &&
  readiness.includes("data.liveEtiEntries") &&
  readiness.includes("does not expose gate evidence") &&
  !/gate\s*[:=]\s*(true|"PASS"|'PASS')/i.test(readiness));

check("Overview does not hardcode statutory amounts", () => {
  const statutoryLiterals = ["12.50", "27.50", "155.00", "7500", "2500", "2700"];
  return statutoryLiterals.every((literal) =>
    !overview.includes(literal) && !display.includes(literal));
});

check("Every Phase 6 South Africa component exists", () =>
  [
    "components/jurisdiction/southAfrica/ZAOverviewDashboard.jsx",
    "components/jurisdiction/southAfrica/ZAPayeTab.jsx",
    "components/jurisdiction/southAfrica/ZAContributionsTab.jsx",
    "components/jurisdiction/southAfrica/ZAEtiTab.jsx",
    "components/jurisdiction/southAfrica/ZALabourTab.jsx",
    "components/jurisdiction/southAfrica/ZAReadinessTab.jsx",
    "components/jurisdiction/southAfrica/zaFormat.js",
    "components/jurisdiction/southAfrica/zaShared.jsx",
    "components/jurisdiction/EarningClassMatrix.jsx",
  ].every(sourceExists));

check("The broken band-form modal is gone and not imported", () =>
  !sourceExists("components/jurisdiction/southAfrica/ZABandFormModal.jsx") &&
  !config.includes("ZABandFormModal") &&
  !overview.includes("ZABandFormModal"));

// ── Phase 8: SARS filing panel (export-and-evidence, ZA-002 / ZA-010 / ZA-018) ──
const filingPanel = read("modules/payroll/Reports/ZAFilingPanel.jsx");
const reportsPage = read("modules/payroll/Reports/ReportsPage.jsx");
const payrollService = read("service/payrollService.js");

check("The SARS filing tab is shown for ZA organisations only", () =>
  reportsPage.includes('import ZAFilingPanel from "./ZAFilingPanel"') &&
  reportsPage.includes("isSouthAfrica ? [ZA_FILING_TAB]") &&
  reportsPage.includes('isSouthAfrica && activeTab === "za-filing"') &&
  reportsPage.includes('normalizeCountryCode(jurisdictionCountry) === "ZA"'));

check("Every filing call goes to the South Africa tenant routes", () =>
  ["/emp201/", "/reconciliation/", "/certificates/", "/artifacts", "/sars-payments", "/coida-evidence/"]
    .every((p) => payrollService.includes("${ZA}" + p)));

check("No SARS source code or BRS field is hard-coded in the filing panel", () =>
  !/\b(3601|3605|3701|3810|4001|4005|4102|4141|4142)\b/.test(filingPanel));

check("ETI is presented as the employer's incentive, never an employee deduction", () =>
  filingPanel.includes("ETI available (employer)") && !/employee[^\n]*ETI|ETI[^\n]*employee deduction/i.test(
    filingPanel.replace("never an employee deduction", "")));

check("There is no portal automation — submission is recorded by the operator", () =>
  !/fetch\(["'`]https?:\/\/[^"'`]*sars/i.test(filingPanel) && filingPanel.includes("Submitted via"));

check("The BRS-blocked state is surfaced, not hidden", () =>
  filingPanel.includes('data-testid="za-brs-blocked"') && filingPanel.includes("never guessed"));

console.log(`za-compliance-ui-validation: ${passed} passed, ${failures.length} failed`);
for (const failure of failures) console.log(`  FAIL ${failure}`);
process.exit(failures.length ? 1 : 0);
