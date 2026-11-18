#!/usr/bin/env node
/**
 * Super Admin > Report Templates > Mexico uses the shared list + detail layout.
 *
 *   - SOURCE: ReportTemplateLayout's extension props are generic (no Mexico
 *     code inside it) and default to nothing; the Mexico page is a thin
 *     wrapper that passes them and stacks nothing under the layout; no other
 *     country page passes them; the MX panels keep their API calls.
 *   - RENDERED: the real components are bundled with rolldown (Vite's bundler)
 *     and rendered with react-dom/server against fixtures — the service module
 *     is stubbed and useLoad answers synchronously, so nothing touches the
 *     network:
 *       * France and Mexico render the same shell; Mexico adds only a
 *         "Library" toggle, collapsed by default (no library table on the page);
 *       * the Overview status block, "Versions & gates" (selected template's
 *         versions only, New version, Compare limited to them) and "Preview"
 *         (pre-selected, or "does not apply") render for MX-ANNUAL-ISR-ADJ and
 *         a snapshot-field template;
 *       * the Library view renders every template.
 */
import { readFileSync, readdirSync, mkdirSync, writeFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "..");
const SRC = resolve(ROOT, "src");
const read = (p) => readFileSync(resolve(SRC, p), "utf-8");

let passed = 0;
const failures = [];
async function check(name, fn) {
  try {
    if ((await fn()) === false) throw new Error("assertion returned false");
    passed += 1;
  } catch (err) {
    failures.push(`${name}: ${err.message}`);
  }
}
const has = (html, text) => { if (!html.includes(text)) throw new Error(`missing ${JSON.stringify(text)}`); };
const lacks = (html, text) => { if (html.includes(text)) throw new Error(`unexpected ${JSON.stringify(text)}`); };

// ── SOURCE ──────────────────────────────────────────────────────────────────
const layout = read("components/reportTemplates/ReportTemplateLayout.jsx");
const mxPage = read("pages/ReportTemplates/MXReportTemplatesPage.jsx");
const libSrc = read("components/jurisdiction/mexico/MXTemplateLibraryPanel.jsx");
const verSrc = read("components/jurisdiction/mexico/MXTemplateVersionsPanel.jsx");

// Comments may name countries (the includeStates note predates this change); code may not.
const layoutCode = layout.split("\n").filter((l) => !/^\s*(\/\/|\*|\/\*|\{\/\*)/.test(l)).join("\n");
await check("layout has no Mexico-specific code", () => !/\bMX\b|Mexico|mexico|getMx/.test(layoutCode));
await check("layout extension props default to nothing", () =>
  /extraDetailTabs = NO_EXTRAS, renderOverviewExtra = null, pageTools = NO_EXTRAS/.test(layout));
await check("built-in tabs unchanged, extras appended after them", () =>
  /const TABS = \[\s*\{ key: "overview"[\s\S]*?\{ key: "audit", label: "Audit", icon: ScrollText \},\s*\];/.test(layout)
  && layout.includes("[...TABS, ...extraDetailTabs]"));
await check("page tools collapsed by default", () => layout.includes("const [openTool, setOpenTool] = useState(null);"));
await check("MX page is a thin wrapper (one ReportTemplateLayout, no stacked panels)", () =>
  (mxPage.match(/<ReportTemplateLayout/g) || []).length === 1 && !mxPage.includes("<>")
  && !/<MXTemplateLibraryPanel\s*\/>\s*\n?\s*(\{|<\/|<div)/.test(mxPage.split("export default")[1]));
await check("MX page passes the three extension props", () =>
  ["extraDetailTabs={MX_DETAIL_TABS}", "renderOverviewExtra={renderMxOverview}", "pageTools={MX_PAGE_TOOLS}"].every((s) => mxPage.includes(s)));
await check("MX page keeps the state route (CDMX ISN under /mexico/CDMX)", () =>
  mxPage.includes("`/super-admin/report-templates/mexico/${encodeURIComponent(state)}`"));
for (const [fn, src] of [["getMxTemplateCoverage", libSrc], ["compareMxReportTemplates", libSrc], ["previewMxTemplateInSandbox", libSrc],
                         ["getMxTemplateVersions", verSrc], ["newMxTemplateVersion", verSrc]]) {
  await check(`MX panels still call ${fn}`, () => new RegExp(`${fn}\\(`).test(src));
}
const pages = readdirSync(resolve(SRC, "pages/ReportTemplates")).filter((f) => f.endsWith("ReportTemplatesPage.jsx"));
await check("no other country page passes the extension props", () => {
  const offenders = pages.filter((f) => f !== "MXReportTemplatesPage.jsx")
    .filter((f) => /extraDetailTabs|renderOverviewExtra|pageTools/.test(read(`pages/ReportTemplates/${f}`)));
  if (offenders.length) throw new Error(offenders.join(", "));
});

// ── RENDERED ────────────────────────────────────────────────────────────────
const SERVICE = resolve(SRC, "service/superAdminService.js");
const NL_SHARED = resolve(SRC, "components/jurisdiction/netherlands/nlShared.jsx");
const serviceNames = [...readFileSync(SERVICE, "utf-8").matchAll(/^export (?:const|async function|function) (\w+)/gm)].map((m) => m[1]);

const ENTRY = "\0mx-validation-entry";
const STUB_SERVICE = "\0stub-service";
const STUB_NL = "\0stub-nl-shared";
const entryCode = `
import { createElement as h } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import FR from ${JSON.stringify(resolve(SRC, "pages/ReportTemplates/FRReportTemplatesPage.jsx"))};
import MX from ${JSON.stringify(resolve(SRC, "pages/ReportTemplates/MXReportTemplatesPage.jsx"))};
import { MX_DETAIL_TABS, MX_PAGE_TOOLS, renderMxOverview } from ${JSON.stringify(resolve(SRC, "components/jurisdiction/mexico/mxReportTemplateExtras.jsx"))};
const wrap = (C) => renderToStaticMarkup(h(MemoryRouter, null, h(C)));
export const render = (node) => renderToStaticMarkup(node);
export const pageFR = () => wrap(FR);
export const pageMX = () => wrap(MX);
export { MX_DETAIL_TABS, MX_PAGE_TOOLS, renderMxOverview };
`;
// Fixtures follow mexico_report_service's response shapes.
const stubService = `
${serviceNames.map((n) => `export const ${n} = () => new Promise(() => {});`).join("\n")
  .replace(/export const (getMxTemplateCoverage|getMxTemplateVersions) = [^\n]*\n?/g, "")}
export const getMxTemplateCoverage = () => globalThis.__MX_FIX.coverage;
export const getMxTemplateVersions = () => globalThis.__MX_FIX.versions;
`;
const stubNl = `
export * from ${JSON.stringify(NL_SHARED)};
export function useLoad(fn) { return [fn(), null, false, () => {}]; }
`;

const { rolldown } = await import("rolldown");
const bundle = await rolldown({
  input: ENTRY,
  platform: "node",
  external: (id) => /^(react|react-dom|react-router-dom|react-router|lucide-react)(\/|$)/.test(id),
  plugins: [{
    name: "mx-validation-stubs",
    resolveId(id, importer) {
      if (id === ENTRY) return ENTRY;
      if (importer && /superAdminService(\.js)?$/.test(id)) return STUB_SERVICE;
      if (importer && /netherlands\/nlShared(\.jsx)?$/.test(id) && importer !== STUB_NL) return STUB_NL;
      return null;
    },
    load(id) {
      if (id === ENTRY) return { code: entryCode, moduleType: "js" };
      if (id === STUB_SERVICE) return { code: stubService, moduleType: "js" };
      if (id === STUB_NL) return { code: stubNl, moduleType: "js" };
      return null;
    },
  }],
  logLevel: "silent",
});
const { output } = await bundle.generate({ format: "esm" });
await bundle.close();
const outDir = resolve(ROOT, "node_modules", ".cache", "mx-layout-validation");
mkdirSync(outDir, { recursive: true });
const outFile = resolve(outDir, "bundle.mjs");
writeFileSync(outFile, output[0].code);
const R = await import(pathToFileURL(outFile).href + `?t=${Date.now()}`);
const { createElement: h } = await import("react");

const ISR = { id: 41, templateKey: "MX-ANNUAL-ISR-ADJ", name: "Annual ISR adjustment", version: "1.0", status: "Draft", reportType: "MX_ANNUAL_ISR_ADJ" };
const REG = { id: 11, templateKey: "MX-PAYROLL-REGISTER", name: "Payroll register", version: "1.0", status: "Draft", reportType: "MX_PAYROLL_REGISTER" };
globalThis.__MX_FIX = {
  coverage: [
    { id: 11, templateKey: REG.templateKey, version: "1.0", status: "Draft", kind: "TEMPLATE_ENGINE", fields: 6, gates: ["G1"],
      fieldProof: "all 6 snapshot path(s) catalogued; proven on a committed payslip at activation" },
    { id: 41, templateKey: ISR.templateKey, version: "1.0", status: "Draft", kind: "DEDICATED", fields: 0, gates: ["G1", "G3"],
      fieldProof: "not applicable — built from service views" },
    { id: 42, templateKey: ISR.templateKey, version: "1.1", status: "Draft", kind: "DEDICATED", fields: 0, gates: ["G1", "G3"],
      fieldProof: "not applicable — built from service views" },
  ],
  versions: [
    { templateKey: REG.templateKey, name: REG.name, kind: "TEMPLATE_ENGINE", versions: [
      { id: 11, version: "1.0", status: "Draft", fields: 6, contentHash: "aaaaaaaaaaaaaaaa", activationRefusal: null, changeSummary: null }] },
    { templateKey: ISR.templateKey, name: ISR.name, kind: "DEDICATED", versions: [
      { id: 41, version: "1.0", status: "Draft", fields: 0, contentHash: "bbbbbbbbbbbbbbbb",
        activationRefusal: "gate G3 not SIGNED (and the payslip field proof at activation)", changeSummary: null },
      { id: 42, version: "1.1", status: "Draft", fields: 0, contentHash: "cccccccccccccccc",
        activationRefusal: "gate G3 not SIGNED (and the payslip field proof at activation)", changeSummary: "Copy of v1.0: rollback" }] },
  ],
};
const ctx = { reloadDetail() {}, reloadTemplates() {}, selectTemplate() {} };
const tab = (key) => R.MX_DETAIL_TABS.find((t) => t.key === key);

const fr = R.pageFR();
const mx = R.pageMX();
// The same page apart from the country name, the MX "Library" toggle and the
// shared wrapper div that holds the toolbar buttons.
const normalise = (html) => html.replace(/France|Mexico/g, "X")
  .replace(/<button type="button" aria-expanded="false" data-testid="page-tool-mx-library"[\s\S]*?<\/button>/, "");
await check("France and Mexico render the same list + detail shell", () => normalise(fr) === normalise(mx));
await check("France shows no page tools", () => lacks(fr, "page-tool-"));
await check("Mexico has a Library toggle, collapsed by default", () => {
  has(mx, 'data-testid="page-tool-mx-library"'); has(mx, 'aria-expanded="false"');
  lacks(mx, "mx-template-library"); lacks(mx, "page-tool-panel-");
});
await check("Mexico stacks no panel under the page", () => {
  for (const id of ["mx-template-versions", "mx-template-compare", "mx-template-preview", "mx-template-status"]) lacks(mx, id);
});
await check("detail tabs are Versions & gates and Preview", () =>
  R.MX_DETAIL_TABS.map((t) => t.label).join("|") === "Versions & gates|Preview");

const overview = R.render(R.renderMxOverview(ISR, ctx));
await check("Overview block: MX-ANNUAL-ISR-ADJ built by, gates, field check, gate answer", () => {
  has(overview, "mx-template-status"); has(overview, "Dedicated generator"); has(overview, "G1, G3");
  has(overview, "not applicable — built from service views"); has(overview, "gate G3 not SIGNED");
});
const versions = R.render(tab("mx-versions-gates").render(ISR, ctx));
await check("Versions & gates shows only the selected template's versions", () => {
  has(versions, "mx-template-versions-MX-ANNUAL-ISR-ADJ"); has(versions, "v1.0 (open)"); has(versions, "v1.1");
  has(versions, "bbbbbbbbbbbb…"); has(versions, "cccccccccccc…"); has(versions, "gate G3 not SIGNED");
  lacks(versions, "MX-PAYROLL-REGISTER"); lacks(versions, "aaaaaaaaaaaa");
});
await check("Versions & gates has New version buttons for each version", () =>
  (versions.match(/>New version<\/button>/g) || []).length === 2);
await check("Compare is in Versions & gates, limited to this template", () => {
  has(versions, 'data-testid="mx-template-compare"');
  const options = [...versions.matchAll(/<option value="(\d+)"[^>]*>([^<]*)<\/option>/g)].map((m) => m[2]);
  if (options.length !== 4 || !options.every((o) => o.startsWith("MX-ANNUAL-ISR-ADJ v"))) throw new Error(options.join(" | "));
});
const previewNa = R.render(tab("mx-preview").render(ISR, ctx));
await check("Preview explains why it does not apply to a dedicated generator", () => {
  has(previewNa, "mx-template-preview-na"); has(previewNa, "dedicated generator"); lacks(previewNa, 'data-testid="mx-template-preview"');
});
const preview = R.render(tab("mx-preview").render(REG, ctx));
await check("Preview pre-selects the current snapshot-field template", () => {
  has(preview, 'data-testid="mx-template-preview"'); has(preview, 'aria-label="Template to preview"');
  if (!/<option value="11" selected="">MX-PAYROLL-REGISTER v1\.0<\/option>/.test(preview)) throw new Error("not pre-selected");
});
const library = R.render(R.MX_PAGE_TOOLS[0].render(ctx));
await check("Library view lists every template with gates and field check", () => {
  has(library, "mx-template-library"); has(library, "MX-PAYROLL-REGISTER"); has(library, "MX-ANNUAL-ISR-ADJ");
  has(library, "Snapshot fields"); has(library, "Dedicated generator"); has(library, "Field check");
});
void h;

console.log(`mx report-template layout validation: ${passed} passed, ${failures.length} failed`);
if (failures.length) {
  for (const f of failures) console.error("  FAIL " + f);
  process.exit(1);
}
