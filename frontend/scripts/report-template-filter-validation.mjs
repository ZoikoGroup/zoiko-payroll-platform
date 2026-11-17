#!/usr/bin/env node
/**
 * Super Admin > Report Templates filter (every country page + the SG / HK
 * compliance tabs share ReportTemplateLayout). Plain Node, like the other
 * scripts here.
 *
 *   - EVALUATED: filterTemplates is case-insensitive, partial, and matches the
 *     name, report type, template key and state; blank text keeps everything.
 *   - SOURCE: the layout fetches once per country with includeStates (no
 *     reportType param, so typing never refetches), has no "State (optional)"
 *     input, shows a clearable state chip and the no-match message; every
 *     country page in COUNTRY_CODE_TO_ROUTE renders ReportTemplateLayout.
 */
import { readFileSync, readdirSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(__dirname, "..", "src");
const read = (p) => readFileSync(resolve(SRC, p), "utf-8");

let passed = 0;
const failures = [];
async function check(name, fn) {
  try {
    const ok = await fn();
    if (ok === false) failures.push(`${name}: assertion returned false`);
    else passed += 1;
  } catch (err) {
    failures.push(`${name}: ${err.message}`);
  }
}
const eq = (a, b) => {
  if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`${JSON.stringify(a)} !== ${JSON.stringify(b)}`);
};

const { filterTemplates } = await import(pathToFileURL(resolve(SRC, "components/reportTemplates/filterTemplates.js")).href);

const T = [
  { id: 1, name: "Payroll register", reportType: "SA_PAYROLL_REGISTER", templateKey: "SA-PAYROLL-REGISTER", jurisdictionState: null },
  { id: 2, name: "GOSI contribution statement", reportType: "SA_GOSI_STATEMENT", templateKey: "SA-GOSI-STATEMENT", jurisdictionState: null },
  { id: 3, name: "Payroll tax return", reportType: "AU_PAYROLL_TAX_RETURN", templateKey: "AU-PTR-NSW", jurisdictionState: "NSW" },
  { id: 4, name: "Year-end certificate", reportType: "P60", templateKey: "UK-P60", jurisdictionState: undefined },
];
const ids = (text) => filterTemplates(T, text).map((t) => t.id);

await check("blank / whitespace text keeps every template", () => { eq(ids(""), [1, 2, 3, 4]); eq(ids("   "), [1, 2, 3, 4]); });
await check("case-insensitive partial match on name", () => { eq(ids("payroll"), [1, 3]); eq(ids("CERTIF"), [4]); });
await check("matches report type", () => { eq(ids("gosi"), [2]); eq(ids("p60"), [4]); eq(ids("tax_return"), [3]); });
await check("matches template key", () => eq(ids("au-ptr"), [3]));
await check("matches state", () => eq(ids("nsw"), [3]));
await check("no match returns empty", () => eq(ids("zzz"), []));
await check("null / undefined input is safe", () => { eq(filterTemplates(null, "x"), []); eq(filterTemplates(undefined, ""), []); });

const layout = read("components/reportTemplates/ReportTemplateLayout.jsx");
await check("no State (optional) input", () => !layout.includes("State (optional)"));
await check("no per-keystroke reportType fetch", () => !/reportType:\s*reportType/.test(layout) && !layout.includes("Filter by Report Type"));
await check("fetches with includeStates: true", () => /getReportTemplates\(\{\s*country,\s*state:[^}]*includeStates:\s*true\s*\}\)/.test(layout));
await check("filter is a useMemo over the fetched list", () => /useMemo\(\(\) => filterTemplates\(templates, filterText\), \[templates, filterText\]\)/.test(layout));
await check("single name-or-type filter input", () => layout.includes('placeholder="Filter by name or report type"'));
await check("clearable state chip", () => layout.includes("State: {state}") && layout.includes('onClick={() => setState("")}'));
await check("no-match message distinct from empty-country message", () =>
  layout.includes('{`No templates match "${filterText.trim()}"`}') &&layout.includes("No report templates for this jurisdiction yet."));
await check("state shown on list rows", () => layout.includes("{t.jurisdictionState ? ` · ${t.jurisdictionState}` : \"\"}"));
await check("NewReportTemplateModal still receives country / state", () =>
  /<NewReportTemplateModal[\s\S]*?country=\{country\}[\s\S]*?state=\{state\}/.test(layout));

const index = read("pages/ReportTemplates/index.js");
const codes = [...index.matchAll(/^\s{2}([A-Z]{2}):\s*"([a-z-]+)"/gm)].map((m) => [m[1], m[2]]);
const pages = readdirSync(resolve(SRC, "pages/ReportTemplates")).filter((f) => f.endsWith("ReportTemplatesPage.jsx"));
await check("COUNTRY_CODE_TO_ROUTE parsed", () => codes.length >= 31);
for (const [code, slug] of codes) {
  await check(`${code} page renders ReportTemplateLayout for its own route`, () => {
    const file = pages.find((f) => f === `${code === "US" ? "USA" : code}ReportTemplatesPage.jsx`);
    if (!file) throw new Error("no page file");
    const src = read(`pages/ReportTemplates/${file}`);
    return src.includes("<ReportTemplateLayout") && src.includes(`country="${code}"`)
      && src.includes(`/super-admin/report-templates/${slug}`);
  });
}
for (const [path, code] of [["components/jurisdiction/singapore/SGReportTemplatesTab.jsx", "SG"],
                            ["pages/JurisdictionCompliance/HKCompliancePage.jsx", "HK"]]) {
  await check(`${code} compliance tab embeds ReportTemplateLayout`, () =>
    new RegExp(`<ReportTemplateLayout country="${code}"[^>]*embedded`).test(read(path)));
}

console.log(`report-template filter validation: ${passed} passed, ${failures.length} failed`);
if (failures.length) {
  for (const f of failures) console.error("  FAIL " + f);
  process.exit(1);
}
