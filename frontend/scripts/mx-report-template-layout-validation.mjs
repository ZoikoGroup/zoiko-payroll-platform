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
 *         (pre-selected, or "does not apply") render for MX-ANNUAL-ISR-ADJ, a
 *         dedicated generator and the CFDI receipt;
 *       * the Library view renders every template.
 *   - EVALUATED: the template_key lookup (mxTemplateLookup.js) never uses a
 *     row of another template; buildDetailTabs hides only what a page asks
 *     and never Overview (Mexico hides the built-in "Versions").
 * Fixtures mirror the backend for real seeded templates
 * (seed_statutory_report_templates.py; mexico_report_service._kind /
 * MX_REPORT_GATES): MX-ANNUAL-ISR-ADJ is MX_ANNUAL_ISR, NOT in MX_REPORT_SPECS,
 * so it is a snapshot-field (TEMPLATE_ENGINE) template with gate G1, as in
 * production (11 fields, Published). Hashes / ids / path counts are illustrative.
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
  /extraDetailTabs = NO_EXTRAS, renderOverviewExtra = null, pageTools = NO_EXTRAS, hiddenDetailTabs = NO_EXTRAS/.test(layout));
await check("layout renderComponentsExtra defaults to nothing", () => /\n\s*renderComponentsExtra = null,\n\}\) \{/.test(layout));
await check("built-in tabs unchanged, extras appended after them", () =>
  /const TABS = \[\s*\{ key: "overview"[\s\S]*?\{ key: "audit", label: "Audit", icon: ScrollText \},\s*\];/.test(layout)
  && layout.includes("buildDetailTabs(TABS, hiddenDetailTabs, extraDetailTabs)"));
await check("a hidden built-in tab's panel cannot render either", () =>
  ["components", "filing-calendar", "versions", "audit"].every((k) => layout.includes(`{tab === "${k}" && isShown("${k}") && (`)));
await check("page tools collapsed by default", () => layout.includes("const [openTool, setOpenTool] = useState(null);"));
await check("MX page is a thin wrapper (one ReportTemplateLayout, no stacked panels)", () =>
  (mxPage.match(/<ReportTemplateLayout/g) || []).length === 1 && !mxPage.includes("<>")
  && !/<MXTemplateLibraryPanel\s*\/>\s*\n?\s*(\{|<\/|<div)/.test(mxPage.split("export default")[1]));
await check("MX page passes the extension props", () =>
  ["extraDetailTabs={MX_DETAIL_TABS}", "renderOverviewExtra={renderMxOverview}", "pageTools={MX_PAGE_TOOLS}",
   "hiddenDetailTabs={MX_HIDDEN_DETAIL_TABS}", "renderComponentsExtra={renderMxComponents}"].every((s) => mxPage.includes(s)));
await check("MX status block / Components / Preview / Versions read the library by template_key (no client-side kind)", () =>
  (libSrc.match(/findCoverageRow\(rows, detail\)/g) || []).length === 3 && verSrc.includes("findVersionsGroup(data, detail)")
  && !/reportType|report_type|MX_REPORT_SPECS|MX_ANNUAL/.test(libSrc + verSrc));
await check("MX page keeps the state route (CDMX ISN under /mexico/CDMX)", () =>
  mxPage.includes("`/super-admin/report-templates/mexico/${encodeURIComponent(state)}`"));
for (const [fn, src] of [["getMxTemplateCoverage", libSrc], ["compareMxReportTemplates", libSrc], ["previewMxTemplateInSandbox", libSrc],
                         ["getMxTemplateVersions", verSrc], ["newMxTemplateVersion", verSrc]]) {
  await check(`MX panels still call ${fn}`, () => new RegExp(`${fn}\\(`).test(src));
}
const pages = readdirSync(resolve(SRC, "pages/ReportTemplates")).filter((f) => f.endsWith("ReportTemplatesPage.jsx"));
await check("no other country page passes the extension props", () => {
  const offenders = pages.filter((f) => f !== "MXReportTemplatesPage.jsx")
    .filter((f) => /extraDetailTabs|renderOverviewExtra|pageTools|hiddenDetailTabs|renderComponentsExtra/.test(read(`pages/ReportTemplates/${f}`)));
  if (offenders.length) throw new Error(offenders.join(", "));
});

// ── EVALUATED (plain JS helpers) ────────────────────────────────────────────
const L = await import(pathToFileURL(resolve(SRC, "components/jurisdiction/mexico/mxTemplateLookup.js")).href);
const { buildDetailTabs } = await import(pathToFileURL(resolve(SRC, "components/reportTemplates/detailTabs.js")).href);
const lookupRows = [{ id: 7, templateKey: "MX-IDSE-MOVEMENTS", version: "1.0", kind: "DEDICATED" },
                    { id: 9, templateKey: "MX-ANNUAL-ISR-ADJ", version: "1.0", kind: "TEMPLATE_ENGINE" }];
await check("lookup: id + template_key match", () =>
  L.findCoverageRow(lookupRows, { id: 9, templateKey: "MX-ANNUAL-ISR-ADJ", version: "1.0" })?.kind === "TEMPLATE_ENGINE");
await check("lookup: a row with the same id but another template_key is never used", () =>
  L.findCoverageRow(lookupRows, { id: 7, templateKey: "MX-ANNUAL-ISR-ADJ", version: "2.0" }) === null);
await check("lookup: falls back to template_key + version", () =>
  L.findCoverageRow(lookupRows, { id: 99, templateKey: "MX-ANNUAL-ISR-ADJ", version: "1.0" })?.id === 9);
await check("lookup: versions group / entry by template_key", () => {
  const g = [{ templateKey: "A", versions: [{ id: 1, version: "1" }] }, { templateKey: "B", versions: [{ id: 2, version: "1" }] }];
  return L.findVersionsGroup(g, { templateKey: "B" }) === g[1] && L.findVersionEntry(g, { id: 1, templateKey: "B", version: "1" })?.id === 2
    && L.findVersionEntry(g, { id: 1, templateKey: "C" }) === null;
});
const BUILT_IN = ["overview", "components", "filing-calendar", "versions", "audit"].map((key) => ({ key }));
const keys = (tabs) => tabs.map((t) => t.key).join(",");
await check("tabs: nothing hidden / added = the built-in five (other countries)", () =>
  keys(buildDetailTabs(BUILT_IN)) === "overview,components,filing-calendar,versions,audit");
await check("tabs: Mexico hides Versions and appends its tabs", () =>
  keys(buildDetailTabs(BUILT_IN, ["versions"], [{ key: "mx-versions-gates" }, { key: "mx-preview" }]))
    === "overview,components,filing-calendar,audit,mx-versions-gates,mx-preview");
await check("tabs: overview can never be hidden", () => keys(buildDetailTabs(BUILT_IN, ["overview"])).startsWith("overview,"));

const N = await import(pathToFileURL(resolve(SRC, "components/jurisdiction/mexico/mxTemplateNotices.js")).href);
const { describeAuditEntry } = await import(pathToFileURL(resolve(SRC, "components/reportTemplates/auditView.js")).href);
const engine0 = { templateKey: "MX-AGUINALDO", kind: "TEMPLATE_ENGINE", fields: 0, fieldProof: "no fields", status: "Approved" };
await check("components notice: a dedicated generator / the receipt take no components", () =>
  N.componentsNotice({ templateKey: "MX-IDSE-MOVEMENTS", kind: "DEDICATED" }, {}).title.startsWith("Built by a dedicated generator")
  && N.componentsNotice({ kind: "RECEIPT" }, {}).title === "CFDI receipt: no components"
  && N.componentsNotice(null, {}) === null);
await check("components notice: snapshot fields present → count and field check", () => {
  const n = N.componentsNotice({ kind: "TEMPLATE_ENGINE", fields: 11, fieldProof: "all 6 catalogued" }, { status: "Published" });
  return n.tone === "ok" && n.title === "Snapshot fields: 11 fields" && n.body.includes("all 6 catalogued");
});
await check("components notice: an Approved empty shell says the seed skipped it and how to refill it", () => {
  const n = N.componentsNotice(engine0, { status: "Approved" });
  return n.tone === "warning" && n.title.includes("the template has no fields")
    && n.body.includes("only refreshes a Draft template") && n.body.includes("Set the status back to Draft (allowed from Approved)");
});
await check("components notice: Draft → re-run the seed; released → new version", () =>
  N.componentsNotice(engine0, { status: "Draft" }).body.includes("Re-run the seed")
  && N.componentsNotice(engine0, { status: "Published" }).body.includes("make a new version"));
await check("approver: Approved with no approver recorded is called out (maker-checker)", () =>
  N.approverNote({ status: "Approved", approvedById: null }).text.startsWith("Status is Approved, but no approver is recorded")
  && N.approverNote({ status: "Draft", approvedById: 7 }).text === "Approved by user #7"
  && N.approverNote({ status: "Draft" }).text === "No approver recorded");
await check("gate lines: area and state from readiness; unknown when not loaded", () => {
  const g = N.gateLines(["G1", "G5"], [{ gate: "G1", label: "ISR / CFDI", state: "OPEN" }, { gate: "G5", label: "Labor", state: "SIGNED" }]);
  const none = N.gateLines(["G2"], null);
  return g[0].label === "ISR / CFDI" && !g[0].signed && g[1].signed && none[0].state === null;
});
// The exact entries Super Admin saw on MX-AGUINALDO (2026-10-28).
const refusedEntry = { action: "refused", oldValue: { status: "Draft" }, newValue: { attempted: "Active", result: "REFUSED" },
                       reason: "MX-AGUINALDO v1.0 cannot move from Draft to Active (allowed: Review, Approved)." };
const statusEntry = { action: "status_change", oldValue: { status: "Draft" },
                      newValue: { status: "Approved", templateKey: "MX-AGUINALDO", approvedById: null } };
await check("audit: a refusal reads as one line, not three phantom changes", () => {
  const d = describeAuditEntry(refusedEntry);
  return d.summary === "Refused: Draft → Active" && d.rows.length === 0;
});
await check("audit: a key empty on both sides is not listed (approvedById: — → —)", () => {
  const d = describeAuditEntry(statusEntry);
  return d.summary === null && d.rows.map((r) => r.key).join() === "status,templateKey" && d.rows[0].to === "Approved";
});
await check("audit: ordinary changes (any country) are still listed", () => {
  const d = describeAuditEntry({ action: "update", oldValue: { name: "A", n: 1 }, newValue: { name: "B", n: 1, x: { y: 1 } } });
  return d.rows.map((r) => `${r.key}:${r.from}>${r.to}`).join("|") === 'name:A>B|x:—>{"y":1}';
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
import { MX_DETAIL_TABS, MX_HIDDEN_DETAIL_TABS, MX_PAGE_TOOLS, renderMxComponents, renderMxOverview } from ${JSON.stringify(resolve(SRC, "components/jurisdiction/mexico/mxReportTemplateExtras.jsx"))};
import ComponentsTab from ${JSON.stringify(resolve(SRC, "components/reportTemplates/ComponentsTab.jsx"))};
const wrap = (C) => renderToStaticMarkup(h(MemoryRouter, null, h(C)));
export const render = (node) => renderToStaticMarkup(node);
export const pageFR = () => wrap(FR);
export const pageMX = () => wrap(MX);
export const componentsTab = (props) => renderToStaticMarkup(h(ComponentsTab, props));
export { MX_DETAIL_TABS, MX_HIDDEN_DETAIL_TABS, MX_PAGE_TOOLS, renderMxComponents, renderMxOverview };
`;
// Fixtures follow mexico_report_service's response shapes.
const stubService = `
${serviceNames.map((n) => `export const ${n} = () => new Promise(() => {});`).join("\n")
  .replace(/export const (getMxTemplateCoverage|getMxTemplateVersions|getMxReadiness) = [^\n]*\n?/g, "")}
export const getMxTemplateCoverage = () => globalThis.__MX_FIX.coverage;
export const getMxTemplateVersions = () => globalThis.__MX_FIX.versions;
export const getMxReadiness = () => globalThis.__MX_FIX.readiness;
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

const ISR = { id: 41, templateKey: "MX-ANNUAL-ISR-ADJ", name: "Annual ISR adjustment (applied in this run)", version: "1.0",
              status: "Published", reportType: "MX_ANNUAL_ISR" };
const IDSE = { id: 61, templateKey: "MX-IDSE-MOVEMENTS", name: "IDSE affiliation movements", version: "1.0", status: "Draft", reportType: "MX_IDSE" };
const RCPT = { id: 51, templateKey: "MX-CFDI-NOMINA-RECEIPT", name: "CFDI 4.0 + Nómina 1.2 payroll receipt", version: "1.0", status: "Draft",
               reportType: "MX_CFDI_RECEIPT" };
const REG = { id: 11, templateKey: "MX-PAYROLL-REGISTER", name: "Mexico payroll register", version: "1.0", status: "Draft", reportType: "MX_REGISTER" };
// The early empty shell moved to Approved with no approver (seen in Super Admin, 2026-10-28).
const AGU = { id: 71, templateKey: "MX-AGUINALDO", name: "Aguinaldo statement", version: "1.0", status: "Approved", reportType: "MX_AGUINALDO",
              approvedById: null };
const NA_DEDICATED = "not applicable — built from service views";
const GATE_G1 = "release gate(s) G1 not SIGNED (and the payslip field proof at activation)";
const GATE_AGU = "release gate(s) G1, G5 not SIGNED; pack MX-PAYROLL-2026 is not Active; the template has no fields "
  + "(and the payslip field proof at activation)";
globalThis.__MX_FIX = {
  readiness: { gates: [{ gate: "G1", label: "ISR / CFDI", state: "OPEN" }, { gate: "G2", label: "IMSS / SUA", state: "OPEN" },
                       { gate: "G5", label: "Labor", state: "OPEN" }] },
  coverage: [
    { id: 71, templateKey: AGU.templateKey, version: "1.0", status: "Approved", kind: "TEMPLATE_ENGINE", fields: 0, gates: ["G1", "G5"],
      fieldProof: "no fields" },
    { id: 11, templateKey: REG.templateKey, version: "1.0", status: "Draft", kind: "TEMPLATE_ENGINE", fields: 14, gates: ["G1", "G2", "G3"],
      fieldProof: "all 9 snapshot path(s) catalogued; proven on a committed payslip at activation" },
    { id: 41, templateKey: ISR.templateKey, version: "1.0", status: "Published", kind: "TEMPLATE_ENGINE", fields: 11, gates: ["G1"],
      fieldProof: "all 6 snapshot path(s) catalogued; proven on a committed payslip at activation" },
    { id: 42, templateKey: ISR.templateKey, version: "1.1", status: "Draft", kind: "TEMPLATE_ENGINE", fields: 11, gates: ["G1"],
      fieldProof: "all 6 snapshot path(s) catalogued; proven on a committed payslip at activation" },
    { id: 51, templateKey: RCPT.templateKey, version: "1.0", status: "Draft", kind: "RECEIPT", fields: 0, gates: ["G1"], fieldProof: NA_DEDICATED },
    { id: 61, templateKey: IDSE.templateKey, version: "1.0", status: "Draft", kind: "DEDICATED", fields: 0, gates: ["G2"], fieldProof: NA_DEDICATED },
  ],
  versions: [
    { templateKey: AGU.templateKey, name: AGU.name, kind: "TEMPLATE_ENGINE", versions: [
      { id: 71, version: "1.0", status: "Approved", fields: 0, contentHash: "ffffffffffffffff", activationRefusal: GATE_AGU, changeSummary: null }] },
    { templateKey: REG.templateKey, name: REG.name, kind: "TEMPLATE_ENGINE", versions: [
      { id: 11, version: "1.0", status: "Draft", fields: 14, contentHash: "aaaaaaaaaaaaaaaa", activationRefusal: GATE_G1, changeSummary: null }] },
    { templateKey: ISR.templateKey, name: ISR.name, kind: "TEMPLATE_ENGINE", versions: [
      { id: 41, version: "1.0", status: "Published", fields: 11, contentHash: "bbbbbbbbbbbbbbbb", activationRefusal: GATE_G1, changeSummary: null },
      { id: 42, version: "1.1", status: "Draft", fields: 11, contentHash: "cccccccccccccccc", activationRefusal: GATE_G1,
        changeSummary: "Copy of v1.0: rollback" }] },
    { templateKey: RCPT.templateKey, name: RCPT.name, kind: "RECEIPT", versions: [
      { id: 51, version: "1.0", status: "Draft", fields: 0, contentHash: "dddddddddddddddd", activationRefusal: GATE_G1, changeSummary: null }] },
    { templateKey: IDSE.templateKey, name: IDSE.name, kind: "DEDICATED", versions: [
      { id: 61, version: "1.0", status: "Draft", fields: 0, contentHash: "eeeeeeeeeeeeeeee",
        activationRefusal: "release gate(s) G2 not SIGNED (and the payslip field proof at activation)", changeSummary: null }] },
  ],
};
const ctx = { reloadDetail() {}, reloadTemplates() {}, selectTemplate() {} };
const tab = (key) => R.MX_DETAIL_TABS.find((t) => t.key === key);

const fr = R.pageFR();
const mx = R.pageMX();
// The same page apart from the country name and the MX "Library" toggle.
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
await check("detail tabs are Versions & gates and Preview; built-in Versions hidden", () =>
  R.MX_DETAIL_TABS.map((t) => t.label).join("|") === "Versions & gates|Preview" && R.MX_HIDDEN_DETAIL_TABS.join() === "versions");

const overview = R.render(R.renderMxOverview(ISR, ctx));
await check("Overview block: MX-ANNUAL-ISR-ADJ is a snapshot-field template, 11 fields, gate G1", () => {
  has(overview, "mx-template-status"); has(overview, "Snapshot fields"); lacks(overview, "Dedicated generator");
  has(overview, ">G1<"); has(overview, ">11<"); has(overview, "all 6 snapshot path(s) catalogued"); has(overview, GATE_G1);
});
const overviewIdse = R.render(R.renderMxOverview(IDSE, ctx));
await check("Overview block: a dedicated generator says so", () => {
  has(overviewIdse, "Dedicated generator"); has(overviewIdse, ">G2<"); has(overviewIdse, NA_DEDICATED);
});
const versions = R.render(tab("mx-versions-gates").render(ISR, ctx));
await check("Versions & gates shows only the selected template's versions", () => {
  has(versions, "mx-template-versions-MX-ANNUAL-ISR-ADJ"); has(versions, "v1.0 (open)"); has(versions, "v1.1");
  has(versions, "bbbbbbbbbbbb…"); has(versions, "cccccccccccc…"); has(versions, GATE_G1);
  for (const other of ["MX-PAYROLL-REGISTER", "MX-IDSE-MOVEMENTS", "aaaaaaaaaaaa", "eeeeeeeeeeee"]) lacks(versions, other);
});
await check("Versions & gates has New version buttons for each version", () =>
  (versions.match(/>New version<\/button>/g) || []).length === 2);
await check("Versions & gates opens another version (the hidden built-in Versions tab's job), not the open one", () => {
  has(versions, 'aria-label="Open v1.1"'); lacks(versions, 'aria-label="Open v1.0"');
});
await check("Compare is in Versions & gates, limited to this template", () => {
  has(versions, 'data-testid="mx-template-compare"');
  const options = [...versions.matchAll(/<option value="(\d+)"[^>]*>([^<]*)<\/option>/g)].map((m) => m[2]);
  if (options.length !== 4 || !options.every((o) => o.startsWith("MX-ANNUAL-ISR-ADJ v"))) throw new Error(options.join(" | "));
});
const preview = R.render(tab("mx-preview").render(ISR, ctx));
await check("Preview: MX-ANNUAL-ISR-ADJ is previewable and pre-selected", () => {
  has(preview, 'data-testid="mx-template-preview"'); has(preview, 'aria-label="Template to preview"'); lacks(preview, "mx-template-preview-na");
  if (!/<option value="41" selected="">MX-ANNUAL-ISR-ADJ v1\.0<\/option>/.test(preview)) throw new Error("not pre-selected");
  lacks(preview, "MX-IDSE-MOVEMENTS"); lacks(preview, "MX-CFDI-NOMINA-RECEIPT");
});
const previewIdse = R.render(tab("mx-preview").render(IDSE, ctx));
await check("Preview explains why it does not apply to a dedicated generator", () => {
  has(previewIdse, "mx-template-preview-na"); has(previewIdse, "MX-IDSE-MOVEMENTS is built by a dedicated generator");
  lacks(previewIdse, 'data-testid="mx-template-preview"');
});
const previewRcpt = R.render(tab("mx-preview").render(RCPT, ctx));
await check("Preview explains why it does not apply to the CFDI receipt", () => {
  has(previewRcpt, "mx-template-preview-na"); has(previewRcpt, "CFDI receipt is rendered from the stamped CFDI");
});
await check("Overview block: each gate with its area and state, and why activation is refused", () => {
  has(overview, 'data-testid="mx-template-gate-states"'); has(overview, "ISR / CFDI");
  has(overview, "A gate is signed only by its reviewed evidence"); has(overview, "Nothing on this page can override it");
});
const overviewAgu = R.render(R.renderMxOverview(AGU, ctx));
await check("Overview block: Approved with no approver recorded is called out", () => {
  has(overviewAgu, "mx-template-approver"); has(overviewAgu, "Status is Approved, but no approver is recorded");
  has(overviewAgu, "the template has no fields"); has(overviewAgu, "Labor");
});
const compIdse = R.render(R.renderMxComponents(IDSE, ctx));
await check("Components: a dedicated generator explains it has no components", () => {
  has(compIdse, "mx-template-components-notice"); has(compIdse, "Built by a dedicated generator: no components");
  has(compIdse, "MX-IDSE-MOVEMENTS is produced by Mexico");
});
const compAgu = R.render(R.renderMxComponents(AGU, ctx));
await check("Components: the Approved empty Aguinaldo shell says why and how to refill it", () => {
  has(compAgu, 'data-tone="warning"'); has(compAgu, "No fields yet"); has(compAgu, "Set the status back to Draft");
  has(compAgu, "seed_statutory_report_templates.py");
});
const compIsr = R.render(R.renderMxComponents(ISR, ctx));
await check("Components: MX-ANNUAL-ISR-ADJ shows its 11 snapshot fields", () => {
  has(compIsr, "Snapshot fields: 11 fields"); lacks(compIsr, "No fields yet");
});
const tabProps = { template: IDSE, components: [], availableDataFields: [], editable: true, onChanged() {} };
await check("ComponentsTab: an empty catalog offers no picker and says the type takes none", () => {
  const html = R.componentsTab({ ...tabProps, availableComponents: [] });
  lacks(html, "Add a component"); lacks(html, "Add Component"); has(html, "This report type takes no components.");
});
await check("ComponentsTab: a catalog still offers its own components (other countries unchanged)", () => {
  const html = R.componentsTab({ ...tabProps, availableComponents: [{ key: "aguinaldo", label: "Aguinaldo" }] });
  has(html, "Add a component"); has(html, ">Aguinaldo</option>"); has(html, "No components configured yet.");
});
const library = R.render(R.MX_PAGE_TOOLS[0].render(ctx));
await check("Library view lists every template with gates and field check", () => {
  for (const t of [REG, ISR, IDSE, RCPT]) has(library, t.templateKey);
  has(library, "Snapshot fields"); has(library, "Dedicated generator"); has(library, "CFDI receipt"); has(library, "Field check");
});
void h;

console.log(`mx report-template layout validation: ${passed} passed, ${failures.length} failed`);
if (failures.length) {
  for (const f of failures) console.error("  FAIL " + f);
  process.exit(1);
}
