#!/usr/bin/env node
/**
 * Super Admin Active Pack / Overview fixes (P3d): evaluated helpers from
 * components/jurisdiction/constants.js plus source checks on the pages.
 */
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(__dirname, "..", "src");
const read = (p) => readFileSync(resolve(SRC, p), "utf-8");
const c = await import(pathToFileURL(resolve(SRC, "components/jurisdiction/constants.js")).href);

let passed = 0;
const failures = [];
const check = (name, ok) => (ok ? (passed += 1) : failures.push(name));

const today = new Date().toISOString().slice(0, 10);
const past = "2020-01-01";
const future = "2999-01-01";
check("opens on the Active pack in force today", c.pickActivePack([
  { id: 1, status: "Draft" },
  { id: 2, status: "Active", effectiveFrom: past, effectiveTo: "2020-12-31" },
  { id: 3, status: "Active", effectiveFrom: past },
])?.id === 3);
check("falls back to any Active pack", c.pickActivePack([{ id: 4, status: "Active", effectiveFrom: future }])?.id === 4);
check("no Active pack: nothing selected", c.pickActivePack([{ id: 5, status: "Draft" }]) === null);
check("today is inside an open-ended window", c.pickActivePack([{ id: 6, status: "Active", effectiveFrom: today }])?.id === 6);
check("next version 1.0 -> 1.1", c.nextPackVersion("1.0") === "1.1");
check("next version skips used numbers", c.nextPackVersion("1.0", ["1.1", "1.2"]) === "1.3");
check("next version of a bare number", c.nextPackVersion("2") === "2.1");
check("non-numeric version left for the user", c.nextPackVersion("2026-H1") === "");
check("Superseded is a selectable status", c.STATUS_OPTIONS.includes("Superseded") && c.STATUS_PILL_MAP.Superseded);

// Contribution-rate units: fraction countries (PR, BS, BB, KY, DO, GY, JM) show x100, all others unchanged.
check("PR Social Security 0.0620 shows 6.2%", c.formatContributionRate("0.0620", "PR") === "6.2%");
check("PR Medicare 0.0145 shows 1.45%", c.formatContributionRate("0.0145", "PR") === "1.45%");
check("Barbados 0.1275 shows 12.75%", c.formatContributionRate("0.1275", "BB") === "12.75%");
check("percent countries unchanged (US 6.2, CA 4, FR 6.90, BE 13.07)",
  c.formatContributionRate("6.2", "US") === "6.2%" && c.formatContributionRate("4", "CA") === "4%"
  && c.formatContributionRate("6.90", "FR") === "6.90%" && c.formatContributionRate("13.07", "BE") === "13.07%");
// Rate edit form round trip: stored -> shown in the form -> saved.
const roundTrip = (stored, country) => c.percentToRate(c.rateToPercent(stored, country), country);
check("PR edit form shows 0.062 as 6.2", c.rateToPercent("0.062", "PR") === "6.2" && c.rateToPercent("0.0620", "PR") === "6.2");
check("PR edit form saves 6.2 as 0.062", c.percentToRate("6.2", "PR") === "0.062");
check("fraction round trip 0.062 -> 6.2 -> 0.062 (and 0.0145, 0.1275, 0.003, 1, 0)",
  [["0.062", "0.062"], ["0.0620", "0.062"], ["0.0145", "0.0145"], ["0.1275", "0.1275"], ["0.003", "0.003"], ["1", "1"], ["0", "0"]]
    .every(([stored, saved]) => roundTrip(stored, "PR") === saved && roundTrip(stored, "JM") === saved));
check("fraction input conversions (12.75 -> 0.1275, 0.25 -> 0.0025, 100 -> 1, .5 -> 0.005)",
  c.percentToRate("12.75", "BB") === "0.1275" && c.percentToRate("0.25", "BB") === "0.0025"
  && c.percentToRate("100", "KY") === "1" && c.percentToRate(".5", "DO") === "0.005");
check("whole-percent round trip unchanged (US 6.2, CA 4, FR 6.90, BE 13.07, UK 8, AU 1.0)",
  [["6.2", "US"], ["4", "CA"], ["6.90", "FR"], ["13.07", "BE"], ["8", "UK"], ["1.0", "AU"]]
    .every(([stored, country]) => c.rateToPercent(stored, country) === stored && roundTrip(stored, country) === stored));
check("empty rate stays empty both ways", c.rateToPercent(null, "PR") === "" && c.percentToRate("", "PR") === ""
  && c.percentToRate("  ", "US") === "");
check("over-100 % warns, a normal rate does not",
  c.ratePercentWarnings("620", "PR").some((w) => w.startsWith("Over 100"))
  && c.ratePercentWarnings("150", "US").some((w) => w.startsWith("Over 100"))
  && c.ratePercentWarnings("6.2", "PR").length === 0 && c.ratePercentWarnings("100", "US").length === 0);
check("fraction precision warning past 2 decimals of a percentage",
  c.ratePercentWarnings("1.455", "PR").some((w) => w.includes("rounded")) && c.ratePercentWarnings("1.455", "US").length === 0);
const rowTables = read("components/jurisdiction/PackRowTables.jsx");
check("Active pack: shared edit/delete icons are disabled, aria-disabled, with the locked tooltip",
  rowTables.includes('export const LOCKED_ROW_TITLE = "Active pack is locked — create a New Version to edit"')
  && rowTables.includes("disabled={disabled}") && rowTables.includes("aria-disabled={disabled || undefined}")
  && rowTables.includes("<DisabledReason reason={LOCKED_ROW_TITLE}>") && rowTables.includes("<span title={reason} className=\"inline-flex cursor-not-allowed\">") && rowTables.includes("onClick={disabled ? undefined : onClick}")
  && read("components/jurisdiction/RatesTab.jsx").includes("actionsDisabled={isActive}")
  && read("components/jurisdiction/SlabsTab.jsx").includes("actionsDisabled={isActive}"));
const rateForm = read("components/jurisdiction/RateFormModal.jsx");
check("rate form converts on load and save with the same unit flag",
  rateForm.includes("rateToPercent(rate?.employeeRatePct, country)") && rateForm.includes("rateToPercent(rate?.employerRatePct, country)")
  && rateForm.includes("percentToRate(form.employeeSharePct, country)") && rateForm.includes("percentToRate(form.employerSharePct, country)")
  && rateForm.includes("window.confirm("));
check("fraction country list", ["PR", "BS", "BB", "KY", "DO", "GY", "JM"].join() === c.FRACTION_RATE_COUNTRIES.join());

// Tax year vs. dates: the form's rule against the SAME case table the backend
// test uses (backend/tests/data/tax_year_cases.json), so server and form agree.
const ty = await import(pathToFileURL(resolve(SRC, "components/jurisdiction/taxYear.js")).href);
const tyCases = JSON.parse(readFileSync(resolve(SRC, "..", "..", "backend", "tests", "data", "tax_year_cases.json"), "utf-8")).cases;
const tyWrong = tyCases.filter((k) => (ty.taxYearDateProblem(k.taxYear, k.from, k.to) === null) !== k.ok);
check(`tax year rule matches the shared backend case table (${tyCases.length} cases)`, tyCases.length >= 20 && tyWrong.length === 0);
check("tax year message names the fix", ty.taxYearDateProblem("2027-2028", "2027-01-01", "2027-12-31")
  === `Tax year "2027-2028" spans two years, but this pack's dates (2027-01-01 → 2027-12-31) fall within 2027. Use the single year 2027.`);
for (const modal of ["NewPackModal", "EditOverviewModal"]) {
  const src = read(`components/jurisdiction/${modal}.jsx`);
  check(`${modal}: shows the tax-year problem and blocks saving`, src.includes("taxYearDateProblem(form.taxYear, form.effectiveFrom, form.effectiveTo)")
    && src.includes('data-testid="tax-year-problem"') && src.includes("disabled={saving || Boolean(taxYearProblem)}"));
}
check("EditOverviewModal checks only when the tax year or a date changed",
  read("components/jurisdiction/EditOverviewModal.jsx").includes("datesOrYearChanged ? taxYearDateProblem("));
const layout = read("components/jurisdiction/JurisdictionLayout.jsx");
const modal = read("components/jurisdiction/NewPackModal.jsx");
const landing = read("pages/CompliancePage.jsx");
const summary = read("components/jurisdiction/PackOverviewSummary.jsx");
check("layout defaults to pickActivePack", layout.includes("autoSelectPack || pickActivePack"));
check("layout re-picks after a state / pack type change", layout.includes("setAutoPicked(false)"));
check("Overview shows the pack summary when no country dashboard replaces it",
  /!overviewOverrideActive && \(\s*<PackOverviewSummary/.test(layout));
check("Approve is hidden on an Active pack (tax and policy), the not-approved chip stays",
  (layout.match(/\{selectedPack\.status !== "Active" && \(\s*<button\s*onClick=\{handleApprove\}/g) || []).length === 2
  && summary.includes('"Not approved yet"'));
check("New Version passes the base pack and used versions", layout.includes("basePack={") && layout.includes("existingVersions={"));
check("New Version refuses an existing version", modal.includes("existingVersions.includes(version.trim())"));
check("New Version pre-fills the next version", modal.includes("nextPackVersion(b.version, existingVersions)"));
check("New Version re-picks the next free version when the version list arrives late",
  /basePack && !versionEdited\s*\?\s*\(nextPackVersion\(b\.version, existingVersions\)/.test(modal)
  && modal.includes("setVersionEdited(true)") && modal.includes("value={version}")
  && modal.includes("existingVersions.includes(version.trim())"));
check("next version skips every existing version (1.0 with 1.0 and 1.1 existing -> 1.2)",
  c.nextPackVersion("1.0", ["1.0", "1.1"]) === "1.2");
check("landing page shows pack status badges", landing.includes("packStatus(j.code)"));
check("landing page loading fix (finally callback)", landing.includes(".finally(() => setLoading(false))"));
check("summary reloads after an Edit Overview save (pack updatedAt)",
  summary.includes("pack?.updatedAt, refreshKey]"));
const editOverview = read("components/jurisdiction/EditOverviewModal.jsx");
check("Edit Overview links a Source Evidence document to the pack",
  editOverview.includes("getSourceArtifacts()") && editOverview.includes("value={form.sourceDocumentId}")
  && /sourceDocumentId: form\.sourceDocumentId \? Number\(form\.sourceDocumentId\) : null/.test(editOverview));
check("summary never invents values (counts only)", summary.includes("awaiting sign-off") && !/defaultValue|placeholder=/.test(summary));

const health = read("components/jurisdiction/PackHealthPanel.jsx");
const service = read("service/superAdminService.js");
check("landing page shows the pack health panel", landing.includes("<PackHealthPanel />"));
check("pack health calls the read-only endpoint", service.includes("/api/super-admin/compliance/pack-health")
  && health.includes("getCompliancePackHealth()"));
check("pack health lists all three problem kinds",
  ["overlappingActive", "duplicateRows", "noActivePack"].every((k) => health.includes(k)));
check("pack health is read-only (no write calls)", !/apiFetch\(|method:\s*"(POST|PUT|PATCH|DELETE)"/.test(health));

if (failures.length) {
  console.error(`pack-overview-validation: ${failures.length} failed, ${passed} passed`);
  for (const f of failures) console.error(`  ✗ ${f}`);
  process.exit(1);
}
console.log(`pack-overview-validation: ${passed} checks passed`);
