#!/usr/bin/env node
/**
 * ZP-MX-ENG-001 frontend validation — Mexico's counterpart of
 * za/jp/nz-compliance-ui-validation.mjs.
 *
 * Source-level checks only (no .jsx imports: the Vite graph OOMs on this
 * machine). They cover the Super Admin workspace wiring, the organisation
 * surfaces, and the shared per-country registries (labels, tax schemas, bank
 * routing) where Mexico must be listed exactly like every other country.
 */
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(__dirname, "..", "src");
const read = (path) => readFileSync(resolve(SRC, path), "utf-8");
const sourceExists = (path) => existsSync(resolve(SRC, path));

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

const config = read("config/jurisdictions/mexicoComplianceConfig.jsx");
const page = read("pages/JurisdictionCompliance/MXCompliancePage.jsx");
const app = read("App.jsx");
const index = read("pages/JurisdictionCompliance/index.js");
const flag = read("components/jurisdiction/CountryFlag.jsx");
const certification = read("pages/TestCertificationPage.jsx");
const superAdminSvc = read("service/superAdminService.js");
const payrollService = read("service/payrollService.js");
const compliancePage = read("modules/payroll/Compliances/CompliancePage.jsx");
const taxConfigTab = read("modules/payroll/Compliances/TaxConfigurationTab.jsx");
const payslipStub = read("modules/payroll/PaySlips/PayslipStub.jsx");
const runDetail = read("modules/payroll/PayRollRuns/RunDetailPanel.jsx");
const employeeDetail = read("modules/payroll/Payroll_Employees/EmployeeDetailPanel.jsx");
const fieldSpecs = read("modules/payroll/Payroll_Employees/countryFieldSpecs.js");
const bankFields = read("modules/payroll/Payroll_Employees/bankFieldsFor.js");
const labels = read("utils/jurisdictionLabels.js");
const taxSchemas = read("utils/jurisdictionTax.js");
const currency = read("utils/currency.js");

// ── Super Admin workspace ──
check("Mexico config exports the page config and tab factory", () =>
  config.includes("export function mexicoExtraTabs(") &&
  config.includes("export const mexicoComplianceConfig"));

check("Mexico page owns both country routes", () =>
  page.includes("mexicoExtraTabs(") &&
  app.includes('path="/super-admin/compliance/mexico"') &&
  app.includes('path="/super-admin/compliance/mexico/:jurisdiction"') &&
  app.includes("<MXCompliancePage />"));

check("Statutory-rate and report-template routes exist for Mexico", () =>
  app.includes('path="/super-admin/statutory-rates/mexico"') &&
  app.includes('path="/super-admin/report-templates/mexico"'));

check("Mexico page is exported and mapped from the compliance index", () =>
  index.includes('export { default as MXCompliancePage } from "./MXCompliancePage"') &&
  index.includes('MX: "mexico"'));

check("Mexico has a flag and a certification entry", () =>
  flag.includes("function Mexico()") && /\bMX:\s*Mexico\b/.test(flag) &&
  certification.includes('value: "MX"'));

check("Super Admin and organisation services target the Mexico routes", () =>
  superAdminSvc.includes('const MX_SA = "/api/super-admin/compliance/mexico"') &&
  payrollService.includes('const MX = "/api/payroll/mexico"'));

check("Readiness speaks of gates G1-G8", () => /G1[–-]G8/.test(config));

// ── Organisation surfaces ──
check("Compliance shows the Mexico centres and omits the generic tax tab", () =>
  compliancePage.includes("<MXComplianceCentreTab />") &&
  compliancePage.includes("<MXSocialSecurityCenter />") &&
  /isNetherlands \|\| isMexico/.test(compliancePage));

check("TaxConfigurationTab never renders the US-fallback tab for Mexico", () =>
  /\["MX", "MEXICO"/.test(taxConfigTab));

check("A calculated Mexican payslip renders the Recibo", () =>
  payslipStub.includes("<MexicoRecibo") && payslipStub.includes("mxCalculationSnapshot"));

check("Mexican run panels are mounted only for runs with MX payslips", () =>
  runDetail.includes('items.some((i) => (i.country || i.countryCode) === "MX") && (') &&
  ["MXRunPreflightPanel", "MXCfdiStagePanel", "MXCorrectionsPanel", "MXRunCalculationTrace"]
    .every((c) => runDetail.includes(`<${c}`)));

check("Employee detail mounts the Mexico statutory profile", () =>
  employeeDetail.includes('employee.countryCode === "MX"') &&
  employeeDetail.includes("<MexicoStatutoryProfilePanel"));

// ── Shared per-country registries ──
check("Employee compliance fields include RFC, CURP, NSS and CLABE", () =>
  ["rfc", "curp", "nss", "clabe"].every((k) => fieldSpecs.includes(`key: "${k}"`)) &&
  fieldSpecs.includes('MX: "curp"'));

check("CLABE renders in the bank section (bank_routing.ROUTING_FIELDS.MX)", () =>
  bankFields.includes('"MX"') && bankFields.includes('MX: "SPEI"') &&
  bankFields.includes('MX: "CLABE"') && bankFields.includes('MX: ["clabe"]'));

check("Payroll labels never fall back to India's TDS / PAN for Mexico", () =>
  /\bMX:\s*"ISR/.test(labels) &&
  /\bMX:\s*\{\s*label:\s*"RFC"/.test(labels) &&
  /\bMX:\s*"RFC \/ Registro Patronal IMSS"/.test(labels) &&
  /\bMX:\s*"ISR, IMSS and INFONAVIT/.test(labels));

check("Company tax schema mirrors backend JURISDICTION_TAX_SCHEMAS.MX", () =>
  taxSchemas.includes("MX: {") && taxSchemas.includes('key: "rfc"') &&
  taxSchemas.includes('key: "registro_patronal"') &&
  taxSchemas.includes('mexico: "MX"') && taxSchemas.includes('MX: "Mexico"'));

check("Mexico is priced in MXN", () => currency.includes('MX: "MXN"'));

check("Every Mexico organisation component exists", () =>
  [
    "modules/payroll/Compliances/MXComplianceCentreTab.jsx",
    "modules/payroll/Compliances/MXPaymentsPanel.jsx",
    "modules/payroll/Compliances/MXJournalPanel.jsx",
    "modules/payroll/Compliances/MXAnnualAdjustmentPanel.jsx",
    "modules/payroll/Compliances/MXPtuCyclePanel.jsx",
    "modules/payroll/PaySlips/MexicoRecibo.jsx",
    "modules/payroll/Payroll_Employees/MexicoStatutoryProfilePanel.jsx",
    "components/jurisdiction/mexico/authorities/MXSocialSecurityCenter.jsx",
  ].every(sourceExists));

console.log(`mx-compliance-ui-validation: ${passed} passed, ${failures.length} failed`);
for (const failure of failures) console.log(`  FAIL ${failure}`);
process.exit(failures.length ? 1 : 0);
