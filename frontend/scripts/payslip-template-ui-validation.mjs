#!/usr/bin/env node
/**
 * Payslip templates — exact-layout import + field settings: UI validation.
 *
 * The rules live in the backend (payslip_template_service / _exact); these
 * checks prove the UI wires them: the import wizard offers Exact layout (the
 * default) and Same style, asks the server in that mode, sends the mapping
 * back with mode "exact" (without the page image), the Map fields step and
 * the editor's Fields panel lock required fields, and the dashboard hands the
 * field catalogue to both. Checked by source, like the other UI validations.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(__dirname, "..", "src");
const read = (p) => readFileSync(resolve(SRC, p), "utf-8");

let passed = 0;
const failures = [];
const check = (name, ok) => (ok ? (passed += 1) : failures.push(name));

const DIR = "modules/payroll/PaySlips/templates/";
const modal = read(`${DIR}PayslipTemplatePdfImportModal.jsx`);
const mapping = read(`${DIR}PayslipTemplateExactMapping.jsx`);
const fieldsPanel = read(`${DIR}PayslipTemplateFieldsPanel.jsx`);
const editor = read(`${DIR}PayslipTemplateEditorModal.jsx`);
const dashboard = read(`${DIR}PayslipTemplateDashboard.jsx`);
const service = read("service/payrollService.js");

// Import wizard: two modes, exact by default, mode sent to the server.
check("wizard offers Exact layout", modal.includes('"exact", Grid3x3, "Exact layout"'));
check("wizard offers Same style", modal.includes('"style", Palette, "Same style"'));
check("exact is the default mode", modal.includes('useState("exact")'));
check("analyse is called with the chosen mode", modal.includes("analyzePayslipPdf(formData, mode)"));
check("service puts the mode in the query (exact|style only)",
  service.includes('import-pdf/analyze?mode=${mode === "exact" ? "exact" : "style"}'));
check("create sends mode exact", /mode: "exact",\s*analysis:/.test(modal));
check("create drops the page image", modal.includes("const { pageImage: _pageImage, ...exactAnalysis } = analysis"));
check("exact analysis shows the Map fields step", modal.includes("<PayslipTemplateExactMapping"));
check("same-style form still there", modal.includes("Section wording"));

// Map fields step.
check("mapping lists every PDF label", mapping.includes("form.fields.map((row, i)"));
check("unmatched labels are flagged, not dropped", mapping.includes("Not matched") && mapping.includes("kept as plain text"));
check("fuzzy matches ask for a check", mapping.includes('row.match === "fuzzy"'));
check("required fields are locked on (mapping)", mapping.includes("f?.required") && mapping.includes("<Lock"));
check("column headings are choosable", ["col_particulars", "col_entitled", "col_earnings", "col_deductions"]
  .every((k) => mapping.includes(`"${k}"`)));
check("line rows get a code input", mapping.includes("f?.side") && mapping.includes("Line code for"));

// Editor Fields panel.
check("Fields panel only for field-aware templates", fieldsPanel.includes("if (!fields || catalogue.length === 0)"));
check("required fields are locked on (editor)", fieldsPanel.includes("f.required") && fieldsPanel.includes("<Lock"));
check("editor renders the Fields panel", editor.includes("<PayslipTemplateFieldsPanel"));
check("editor saves fields into configurationJson", editor.includes('setCfg("fields", fields)'));

// Diagnostics (P6): test with a real payslip; the reason is shown, never raw JSON.
const diag = read(`${DIR}PayslipTemplateDiagnostics.jsx`);
check("editor can test with a payslip number", editor.includes("Test with payslip #")
  && editor.includes("payslipId: Number(testPayslipId)"));
check("preview re-runs when the payslip number changes", editor.includes("[template, html, css, config, testPayslipId]"));
check("editor keeps the server's diagnostics", editor.includes("setDiagnostics(res?.diagnostics || null)"));
check("Sample PDF errors keep their diagnostic", editor.includes("if (err.diagnostics) setDiagnostics(err.diagnostics)")
  && service.includes("err.diagnostics = detail"));
check("Sample PDF shows the message, not JSON", service.includes("detail?.message || JSON.stringify(detail)"));
check("editor renders the diagnostics banner", editor.includes("<PayslipTemplateDiagnostics"));
check("every diagnostic code has a title", ["TIE_OUT_MISMATCH", "PAYSLIP_BLOCKED", "BELGIUM", "RENDER_ERROR",
  "ENGINE_FAILURE", "NOT_ASSIGNED"].every((c) => diag.includes(`${c}:`)));
check("tie-out shows both differences", diag.includes("d.earningsDifference") && diag.includes("d.deductionsDifference"));
check("banner says downloads are unaffected", diag.includes("Downloads and e-mails of this payslip are not affected"));

// Dashboard passes the catalogue to both.
check("dashboard keeps fieldCatalogue", dashboard.includes("fieldCatalogue: res?.fieldCatalogue || []"));
check("catalogue reaches the editor and the PDF import",
  (dashboard.match(/fieldCatalogue=\{data\.fieldCatalogue\}/g) || []).length === 2);

if (failures.length) {
  console.error(`payslip-template UI validation: ${failures.length} failed, ${passed} passed`);
  for (const f of failures) console.error(`  ✗ ${f}`);
  process.exit(1);
}
console.log(`payslip-template UI validation: ${passed} checks passed`);
