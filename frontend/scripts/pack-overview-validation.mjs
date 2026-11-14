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

const layout = read("components/jurisdiction/JurisdictionLayout.jsx");
const modal = read("components/jurisdiction/NewPackModal.jsx");
const landing = read("pages/CompliancePage.jsx");
const summary = read("components/jurisdiction/PackOverviewSummary.jsx");
check("layout defaults to pickActivePack", layout.includes("autoSelectPack || pickActivePack"));
check("layout re-picks after a state / pack type change", layout.includes("setAutoPicked(false)"));
check("Overview shows the pack summary when no country dashboard replaces it",
  /!overviewOverrideActive && \(\s*<PackOverviewSummary/.test(layout));
check("New Version passes the base pack and used versions", layout.includes("basePack={") && layout.includes("existingVersions={"));
check("New Version refuses an existing version", modal.includes("existingVersions.includes(form.version.trim())"));
check("New Version pre-fills the next version", modal.includes("nextPackVersion(b.version, existingVersions)"));
check("landing page shows pack status badges", landing.includes("packStatus(j.code)"));
check("landing page loading fix (finally callback)", landing.includes(".finally(() => setLoading(false))"));
check("summary never invents values (counts only)", summary.includes("awaiting sign-off") && !/defaultValue|placeholder=/.test(summary));

if (failures.length) {
  console.error(`pack-overview-validation: ${failures.length} failed, ${passed} passed`);
  for (const f of failures) console.error(`  ✗ ${f}`);
  process.exit(1);
}
console.log(`pack-overview-validation: ${passed} checks passed`);
