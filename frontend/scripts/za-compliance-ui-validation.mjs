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
  readiness.includes("data.signedGates") &&
  // Phase 10: gate state now comes from the API (evidence reviewed by a second Super Admin).
  readiness.includes("<Badge state={gate.state} />") &&
  !/gate\s*[:=]\s*(true|"PASS"|'PASS'|"SIGNED"|'SIGNED')/i.test(readiness));

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

// ── Phase 9: approval checks, overrides, deductions, corrections, journal ──
const runChecks = read("modules/payroll/PayRollRuns/ZARunExceptionsPanel.jsx");
const runDetail = read("modules/payroll/PayRollRuns/RunDetailPanel.jsx");
const breakdown = read("modules/payroll/PayRollRuns/ZAPayslipBreakdown.jsx");
const deductionBlock = read("modules/payroll/Payroll_Employees/ZADeductionOrdersBlock.jsx");
const employeeDetail = read("modules/payroll/Payroll_Employees/EmployeeDetailPanel.jsx");
const phase9 = [runChecks, breakdown, deductionBlock].join("\n");

check("The ZA approval checks panel is mounted only for runs with ZA payslips", () =>
  runDetail.includes('import ZARunExceptionsPanel from "./ZARunExceptionsPanel"') &&
  runDetail.includes('items.some((i) => (i.country || i.countryCode) === "ZA") && (') &&
  employeeDetail.includes('employee.countryCode === "ZA" && <ZADeductionOrdersBlock'));

check("Every Phase 9 call goes to the South Africa tenant routes", () =>
  ["/runs/${runId}/exceptions", "/runs/${runId}/overrides", "/overrides/${overrideId}/approve",
   "/employees/${employeeId}/deduction-orders", "/payslips/${payslipId}/corrections", "/runs/${runId}/journal"]
    .every((p) => payrollService.includes("${ZA}" + p)));

check("Exceptions and overrides are approved only through the API (no client-side approval state)", () =>
  runChecks.includes("approveZaRunException(runId, r.key)") && runChecks.includes("approveZaOverride(r.id)") &&
  !/localStorage|sessionStorage/.test(runChecks) && !/approved\s*:\s*true/.test(runChecks));

check("No BCEA premium multiplier or damage-deduction percentage is hard-coded", () =>
  !/\b(1\.5|2\.0|1,5)\s*[x×]|multiplier\s*[:=]\s*\d|limit(Pct)?\s*[:=]\s*\d|\b25\s*%/i.test(phase9));

check("ETI is still never an employee line", () =>
  !/deduct[^\n]*\beti\b|\beti\b[^\n]*deduction/i.test(
    phase9.replace("never changes the employee&apos;s PAYE or net pay", "")));

check("Labour findings and overrides are disclosed on the payslip breakdown", () =>
  breakdown.includes('data-testid="za-labour-checks"') && breakdown.includes('data-testid="za-overrides-note"') &&
  breakdown.includes("Authorised deductions (ZA-013)"));

check("A blocked journal is surfaced, never hidden", () =>
  runChecks.includes('data-testid="za-journal-blocked"'));

// ── Phase 10: release gates G0-G7 and G6 parallel cycles ──
const readinessTab = read("components/jurisdiction/southAfrica/ZAReadinessTab.jsx");
const parallelSection = read("modules/payroll/Reports/ZAParallelCyclesSection.jsx");
const filingPanelP10 = read("modules/payroll/Reports/ZAFilingPanel.jsx");
const superAdminSvc = read("service/superAdminService.js");

check("South Africa readiness speaks of gates G0-G7, never G8", () =>
  /G0[–-]G7/.test(readinessTab) && !/G1[–-]G8|\bG8\b/.test(readinessTab) && !/G1[–-]G8/.test(parallelSection));

check("Gate and decision state is read from the API only - nothing on the tab signs or records", () =>
  readinessTab.includes("getZaSummary") && !/state\s*:\s*["']SIGNED["']|["']RECORDED["']\s*\}/.test(readinessTab) &&
  !/\b(post|put|patch)\b/i.test(readinessTab.replace(/import[^;]+;/g, "")));

check("The readiness tab shows gates, preconditions, code checks, decisions, NO-GO and open points", () =>
  ["data.gates", "data.gaPreconditions", "data.codeChecks", "data.decisions", "data.noGo", "data.openPoints"]
    .every((k) => readinessTab.includes(k)));

check("Readiness and parallel calls go to their South Africa routes", () =>
  superAdminSvc.includes("${ZA_SA}/readiness") &&
  ["/parallel-imports", "/parallel-imports/${importId}/accept", "/parallel-differences/${diffId}/explain",
   "/parallel-differences/${diffId}/accept"].every((p) => payrollService.includes("${ZA}" + p)));

check("The parallel-cycles section is mounted in the SARS filing panel", () =>
  filingPanelP10.includes('import ZAParallelCyclesSection from "./ZAParallelCyclesSection"') &&
  filingPanelP10.includes("<ZAParallelCyclesSection />"));

check("No materiality tolerance is hard-coded and ETI is not a compared concept", () =>
  !/materiality\s*[:=]\s*\d|tolerance\s*[:=]\s*\d/i.test(parallelSection) &&
  !/\[\s*["']eti["']/i.test(parallelSection));

check("A cycle is accepted only when the server says it is clean", () =>
  parallelSection.includes("disabled={state.busy || !data.clean}") &&
  parallelSection.includes('data-testid="za-parallel-clean"'));

console.log(`za-compliance-ui-validation: ${passed} passed, ${failures.length} failed`);
for (const failure of failures) console.log(`  FAIL ${failure}`);
process.exit(failures.length ? 1 : 0);
