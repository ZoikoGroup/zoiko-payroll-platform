import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Check, CheckCircle, Code, Copy, Eye, FileDown, Save, Sliders, X } from "lucide-react";
import {
  downloadPayslipTemplateSamplePdf,
  previewPayslipTemplate,
  publishPayslipTemplate,
  updatePayslipTemplate,
} from "../../../../service/payrollService";
import { useToast } from "../../ToastContext";

// Must match payslip_template_service.build_payslip_context / sample_context.
const PLACEHOLDERS = [
  { group: "Company", items: [
    ["{{ company.name }}", "Company name"], ["{{ company.address }}", "Address"],
    ["{{ company.tax_id }}", "Tax ID"], ["{{ company.registration_no }}", "Registration no."],
    ['<img src="{{ company.logo_data_uri }}" alt="">', "Logo (when shown)"],
  ] },
  { group: "Employee", items: [
    ["{{ employee.name }}", "Name"], ["{{ employee.id }}", "Employee ID"],
    ["{{ employee.department }}", "Department"], ["{{ employee.designation }}", "Designation"],
    ["{{ employee.date_of_joining }}", "Date of joining"], ["{{ employee.bank_name }}", "Bank"],
    ["{{ employee.bank_account }}", "Account (masked)"],
    ["{% for i in employee.identifiers %}{{ i.label }}: {{ i.value }}{% endfor %}", "Country identifiers (masked)"],
  ] },
  { group: "Period", items: [
    ["{{ payroll.period }}", "Pay period"], ["{{ payroll.pay_date }}", "Pay date"],
    ["{{ payroll.payslip_number }}", "Payslip number"], ["{{ payroll.payable_days }}", "Payable days"],
    ["{{ payroll.total_days }}", "Working days"], ["{{ currency.code }}", "Currency code"],
    ["{{ currency.symbol }}", "Currency symbol"], ["{{ generated_on }}", "Generated on"],
  ] },
  { group: "Amounts", items: [
    ["{% for line in earnings %}<div>{{ line.label }} {{ line.amount_formatted }}</div>{% endfor %}", "Earnings lines"],
    ["{% for line in deductions %}<div>{{ line.label }} {{ line.amount_formatted }}</div>{% endfor %}", "Deduction lines"],
    ["{{ totals.gross_pay_formatted }}", "Gross pay"], ["{{ totals.total_deductions_formatted }}", "Total deductions"],
    ["{{ totals.net_pay_formatted }}", "Net pay"], ["{{ totals.net_pay_in_words }}", "Net pay in words"],
    ["{{ disclaimer }}", "Footer text"],
  ] },
];

const TOGGLES = [
  ["showCompanyLogo", "Company logo", "Uses the logo uploaded on the organisation profile"],
  ["showEmployeeBank", "Bank details", "Bank name and masked account number"],
  ["showNetInWords", "Net pay in words", "Shown under the net pay figure"],
];

const tabCls = (on) =>
  `flex items-center gap-1.5 px-3 py-1.5 rounded-[8px] text-[12px] font-semibold transition-colors cursor-pointer ${
    on ? "bg-primary text-white" : "text-foreground-muted hover:text-foreground hover:bg-surface-muted"}`;

export default function PayslipTemplateEditorModal({ template, onClose, onSaved }) {
  const { addToast } = useToast();
  // Remounted per template (key in the dashboard), so props seed the state.
  const initial = template?.latestVersion || {};
  const [tab, setTab] = useState("visual");
  const [name, setName] = useState(template?.name || "");
  const [description, setDescription] = useState(template?.description || "");
  const [html, setHtml] = useState(initial.htmlContent || "");
  const [css, setCss] = useState(initial.cssContent || "");
  const [config, setConfig] = useState(initial.configurationJson || {});
  const [dirty, setDirty] = useState(false);
  const [hasDraft, setHasDraft] = useState(initial.status === "Draft");
  const [saving, setSaving] = useState(false);
  const [pdfBusy, setPdfBusy] = useState(false);
  const [doc, setDoc] = useState("");
  const [problem, setProblem] = useState("");
  const [warnings, setWarnings] = useState([]);
  const [copied, setCopied] = useState(null);
  const timer = useRef(null);

  useEffect(() => {
    if (!template) return undefined;
    clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      try {
        const res = await previewPayslipTemplate({ htmlContent: html, cssContent: css, configurationJson: config, country: template.country || "IN" });
        setDoc(res?.renderedHtml || "");
        setWarnings(res?.warnings || []);
        setProblem("");
      } catch (err) {
        setProblem(err.message || "This template cannot be rendered.");
      }
    }, 450);
    return () => clearTimeout(timer.current);
  }, [template, html, css, config]);

  if (!template) return null;

  const edit = (setter) => (value) => { setter(value); setDirty(true); };
  const setCfg = (key, value) => { setConfig((c) => ({ ...c, [key]: value })); setDirty(true); };

  const save = async () => {
    await updatePayslipTemplate(template.id, { name, description, htmlContent: html, cssContent: css, configurationJson: config });
    setDirty(false);
    setHasDraft(true);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await save();
      addToast?.("Draft saved.", "success");
      onSaved?.();
    } catch (err) {
      addToast?.(err.message || "Could not save the draft.", "error");
    } finally {
      setSaving(false);
    }
  };

  const handlePublish = async () => {
    const usedFor = template.assignedCountries?.length
      ? ` Payslips for ${template.assignedCountries.join(", ")} that are not yet approved will use the new version.`
      : " Assign it to a country to start using it.";
    if (!window.confirm(`Publish "${name}"?${usedFor} Payslips already approved keep the version they were issued with.`)) return;
    setSaving(true);
    try {
      await save();
      await publishPayslipTemplate(template.id);
      addToast?.(`"${name}" published.`, "success");
      onSaved?.();
      onClose();
    } catch (err) {
      addToast?.(err.message || "Could not publish the template.", "error");
    } finally {
      setSaving(false);
    }
  };

  const handleClose = () => {
    if (dirty && !window.confirm("Discard unsaved changes?")) return;
    onClose();
  };

  const handleSamplePdf = async () => {
    setPdfBusy(true);
    try {
      await downloadPayslipTemplateSamplePdf({ htmlContent: html, cssContent: css, configurationJson: config,
        country: template.country || "IN" });
    } catch (err) {
      addToast?.(err.message || "Could not create the sample PDF.", "error");
    } finally {
      setPdfBusy(false);
    }
  };

  const copy = (code) => {
    navigator.clipboard?.writeText(code);
    setCopied(code);
    setTimeout(() => setCopied(null), 1200);
  };

  const v = template.latestVersion || {};
  const canPublish = !problem && (dirty || hasDraft);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="bg-surface border border-border rounded-[18px] shadow-2xl flex flex-col w-full max-w-7xl h-[94vh] overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 border-b border-border">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <input value={name} onChange={(e) => edit(setName)(e.target.value)} aria-label="Template name"
                className="text-[15px] font-bold text-foreground bg-transparent border-b border-transparent hover:border-border focus:border-primary focus:outline-none px-1 min-w-0" />
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-surface-muted text-foreground-muted border border-border">{template.code}</span>
              <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-surface-muted text-foreground-muted">
                {v.status === "Draft" ? `Draft v${v.versionNumber}` : hasDraft ? `Draft v${(v.versionNumber || 0) + 1}` : `Editing creates v${(v.versionNumber || 0) + 1}`}
              </span>
            </div>
            <input value={description} onChange={(e) => edit(setDescription)(e.target.value)} placeholder="Description"
              className="mt-0.5 w-full text-[12px] text-foreground-muted bg-transparent focus:outline-none px-1" />
          </div>
          <div className="flex items-center gap-2">
            <div className="flex rounded-[10px] border border-border p-0.5">
              <button type="button" className={tabCls(tab === "visual")} onClick={() => setTab("visual")}><Sliders size={13} /> Style</button>
              <button type="button" className={tabCls(tab === "html")} onClick={() => setTab("html")}><Code size={13} /> HTML</button>
              <button type="button" className={tabCls(tab === "css")} onClick={() => setTab("css")}># CSS</button>
            </div>
            <button type="button" onClick={handleSamplePdf} disabled={pdfBusy || !!problem}
              title="Download this template as a PDF with sample data — what a downloaded payslip will look like"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-[10px] border border-border text-[12px] font-semibold text-foreground hover:bg-surface-muted disabled:opacity-50 cursor-pointer">
              <FileDown size={13} /> {pdfBusy ? "Creating…" : "Sample PDF"}
            </button>
            <button type="button" onClick={handleSave} disabled={saving || !dirty || !!problem}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-[10px] border border-border text-[12px] font-semibold text-foreground hover:bg-surface-muted disabled:opacity-50 cursor-pointer">
              <Save size={13} /> Save draft
            </button>
            <button type="button" onClick={handlePublish} disabled={saving || !canPublish}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-[10px] bg-primary text-white text-[12px] font-semibold hover:bg-primary/90 disabled:opacity-50 cursor-pointer">
              <CheckCircle size={13} /> Publish
            </button>
            <button type="button" onClick={handleClose} aria-label="Close"
              className="p-1.5 rounded-[10px] text-foreground-muted hover:bg-surface-muted hover:text-foreground cursor-pointer">
              <X size={18} />
            </button>
          </div>
        </div>

        {(problem || warnings.length > 0) && (
          <div className={`flex items-start gap-2 px-5 py-2 text-[12px] border-b border-border ${problem ? "bg-error/10 text-error" : "bg-warning/10 text-warning"}`}>
            <AlertTriangle size={14} className="shrink-0 mt-0.5" />
            <span>{problem || warnings.join(" ")}</span>
          </div>
        )}

        <div className="flex-1 flex overflow-hidden">
          <div className="w-1/2 border-r border-border flex flex-col">
            {tab === "visual" && (
              <div className="flex-1 overflow-y-auto p-5 space-y-5">
                <div className="grid grid-cols-2 gap-4">
                  {[["primaryColor", "Primary colour", "#1E3A8A"], ["accentColor", "Accent colour", "#FFFFFF"]].map(([key, label, fallback]) => (
                    <label key={key} className="block">
                      <span className="block text-[11px] font-semibold text-foreground-muted mb-1">{label}</span>
                      <div className="flex items-center gap-2">
                        <input type="color" value={config[key] || fallback} onChange={(e) => setCfg(key, e.target.value)}
                          className="w-9 h-9 rounded border border-border cursor-pointer p-0.5 bg-transparent" />
                        <input type="text" value={config[key] || ""} onChange={(e) => setCfg(key, e.target.value)}
                          className="flex-1 rounded-[8px] border border-border bg-surface px-2.5 py-1.5 text-[12px] font-mono text-foreground" />
                      </div>
                    </label>
                  ))}
                </div>
                <div className="space-y-2 rounded-[12px] border border-border p-4">
                  {TOGGLES.map(([key, label, hint]) => (
                    <label key={key} className="flex items-center justify-between gap-3 cursor-pointer">
                      <span>
                        <span className="block text-[12px] font-semibold text-foreground">{label}</span>
                        <span className="block text-[11px] text-foreground-muted">{hint}</span>
                      </span>
                      <input type="checkbox" checked={!!config[key]} onChange={(e) => setCfg(key, e.target.checked)} />
                    </label>
                  ))}
                </div>
                <label className="block">
                  <span className="block text-[11px] font-semibold text-foreground-muted mb-1">Footer text</span>
                  <textarea rows={3} maxLength={500} value={config.disclaimerText || ""} onChange={(e) => setCfg("disclaimerText", e.target.value)}
                    className="w-full rounded-[10px] border border-border bg-surface p-3 text-[12px] text-foreground focus:outline-none focus:border-primary" />
                </label>
                <p className="text-[11px] text-foreground-muted">
                  These settings apply to layouts that use them (both built-in layouts do). Amounts and line items always
                  come from the payslip.
                </p>
              </div>
            )}
            {tab === "html" && (
              <div className="flex-1 flex flex-col min-h-0">
                <textarea value={html} onChange={(e) => edit(setHtml)(e.target.value)} spellCheck={false} aria-label="Template HTML"
                  className="flex-1 w-full p-4 font-mono text-[12px] leading-relaxed bg-[#1e1e1e] text-[#d4d4d4] resize-none focus:outline-none" />
                <div className="h-48 overflow-y-auto border-t border-border p-3 space-y-2">
                  <p className="text-[11px] text-foreground-muted">
                    Jinja2 placeholders (click to copy). Scripts, external images/links, &lt;style&gt; and <code>|safe</code> are not allowed.
                  </p>
                  {PLACEHOLDERS.map((g) => (
                    <div key={g.group}>
                      <p className="text-[10px] font-bold uppercase tracking-wider text-foreground-muted mb-1">{g.group}</p>
                      <div className="flex flex-wrap gap-1.5">
                        {g.items.map(([code, label]) => (
                          <button key={code} type="button" title={code} onClick={() => copy(code)}
                            className="flex items-center gap-1 rounded border border-border px-2 py-0.5 text-[11px] text-foreground hover:border-primary cursor-pointer">
                            {copied === code ? <Check size={11} className="text-success" /> : <Copy size={11} />} {label}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {tab === "css" && (
              <textarea value={css} onChange={(e) => edit(setCss)(e.target.value)} spellCheck={false} aria-label="Template CSS"
                placeholder="/* --ps-primary and --ps-accent hold the colours chosen under Style */"
                className="flex-1 w-full p-4 font-mono text-[12px] leading-relaxed bg-[#1e1e1e] text-[#9cdcfe] resize-none focus:outline-none" />
            )}
          </div>
          <div className="w-1/2 flex flex-col bg-surface-muted/30">
            <div className="flex items-center gap-1.5 px-4 py-2 border-b border-border text-[11px] text-foreground-muted">
              <Eye size={12} /> Live preview with sample data
            </div>
            <div className="flex-1 overflow-auto p-4">
              {doc && (
                <iframe srcDoc={doc} title="Live preview" sandbox="" referrerPolicy="no-referrer"
                  className="w-full h-[1000px] border-0 bg-white rounded-md shadow" />
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
