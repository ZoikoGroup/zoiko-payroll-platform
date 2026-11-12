import { useRef, useState } from "react";
import { FileText, UploadCloud, X } from "lucide-react";
import { analyzePayslipPdf, createPayslipTemplateFromPdf } from "../../../../service/payrollService";
import { useToast } from "../../ToastContext";

const MAX_BYTES = 5_000_000;

// Friendly names for the detail placeholders the analysis can suggest.
const PLACEHOLDER_NAMES = {
  "employee.name": "Employee name",
  "employee.id": "Employee ID",
  "employee.department": "Department",
  "employee.designation": "Designation",
  "employee.date_of_joining": "Date of joining",
  "employee.bank_account": "Bank account (masked)",
  "employee.bank_name": "Bank name",
  "employee.identifiers": "Country identifiers (PAN / Tax ID … masked)",
  "payroll.pay_date": "Pay date",
  "payroll.period": "Pay period",
  "payroll.payable_days": "Payable days",
  "payroll.total_days": "Working days",
  "payroll.payslip_number": "Payslip number",
  "company.registration_no": "Company registration no.",
};

const field = "w-full rounded-[8px] border border-border bg-surface px-2.5 py-1.5 text-[12px] text-foreground focus:outline-none focus:border-primary";

/** Build a payslip template from a PDF payslip's design. The PDF is read once
 * (nothing is stored); the user confirms colours, wording and which fields
 * map to which placeholders; a flowing template is created as a draft. */
export default function PayslipTemplatePdfImportModal({ isOpen, onClose, onCreated }) {
  const { addToast } = useToast();
  const inputRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const [fileName, setFileName] = useState("");
  const [analysis, setAnalysis] = useState(null);
  const [form, setForm] = useState(null);

  if (!isOpen) return null;

  const set = (key, value) => setForm((f) => ({ ...f, [key]: value }));
  const setSection = (key, value) => setForm((f) => ({ ...f, sections: { ...f.sections, [key]: value } }));
  const setField = (i, key, value) =>
    setForm((f) => ({ ...f, fields: f.fields.map((fl, j) => (j === i ? { ...fl, [key]: value } : fl)) }));

  const upload = async (file) => {
    if (!file) return;
    if (!/\.pdf$/i.test(file.name)) { addToast?.("Choose a .pdf file.", "error"); return; }
    if (file.size > MAX_BYTES) { addToast?.("The PDF is larger than 5 MB.", "error"); return; }
    setBusy(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const a = await analyzePayslipPdf(formData);
      setFileName(file.name);
      setAnalysis(a);
      setForm({
        name: file.name.replace(/\.[^.]+$/, "").replace(/[-_]+/g, " "),
        title: a.title,
        primaryColor: a.primaryColor,
        accentColor: "#FFFFFF",
        includeLogo: !!a.logoDataUri,
        layout: a.layout,
        sections: { ...a.sections },
        fields: a.fields.map((f) => ({ ...f })),
        disclaimer: a.disclaimer,
      });
    } catch (err) {
      addToast?.(err.message || "This PDF could not be read.", "error");
    } finally {
      setBusy(false);
    }
  };

  const create = async () => {
    setBusy(true);
    try {
      const created = await createPayslipTemplateFromPdf({
        name: form.name,
        description: `Built from ${fileName}`,
        analysis: {
          title: form.title,
          primaryColor: form.primaryColor,
          accentColor: form.accentColor,
          logoDataUri: analysis.logoDataUri,
          includeLogo: form.includeLogo,
          layout: form.layout,
          sections: form.sections,
          fields: form.fields,
          disclaimer: form.disclaimer,
        },
      });
      addToast?.(`"${created.name}" created as a draft. Check it in the editor, then publish.`, "success");
      onClose();
      onCreated?.(created);
    } catch (err) {
      addToast?.(err.message || "Could not create the template.", "error");
    } finally {
      setBusy(false);
    }
  };

  const placeholderOptions = analysis?.detailPlaceholders || Object.keys(PLACEHOLDER_NAMES);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="bg-surface border border-border rounded-[18px] shadow-2xl flex flex-col w-full max-w-6xl max-h-[94vh] overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3 border-b border-border">
          <div>
            <h3 className="text-[15px] font-bold text-foreground">Import a PDF payslip design</h3>
            <p className="text-[12px] text-foreground-muted">
              Builds a template from your PDF&apos;s colours, logo and wording. It will look similar, not identical,
              and works for every employee.
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close"
            className="p-1.5 rounded-[10px] text-foreground-muted hover:bg-surface-muted hover:text-foreground cursor-pointer">
            <X size={18} />
          </button>
        </div>

        {!analysis ? (
          <div className="p-6 space-y-4">
            <button type="button" disabled={busy} onClick={() => inputRef.current?.click()}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => { e.preventDefault(); upload(e.dataTransfer.files?.[0]); }}
              className="w-full rounded-[14px] border-2 border-dashed border-border p-10 text-center hover:border-primary/50 cursor-pointer disabled:opacity-60">
              <input ref={inputRef} type="file" accept=".pdf" className="hidden" onChange={(e) => upload(e.target.files?.[0])} />
              <span className="flex flex-col items-center gap-1 text-[13px] text-foreground-muted">
                <UploadCloud size={28} />
                {busy ? "Reading the PDF…" : "Click or drop a PDF payslip (max 5 MB, up to 5 pages)"}
              </span>
            </button>
            <ul className="text-[11px] text-foreground-muted list-disc pl-5 space-y-1">
              <li>Use a <strong>sample or blank</strong> payslip if you can. Nothing from the file is stored; only the
                labels you keep become part of the template.</li>
              <li>The PDF must contain text (exported from payroll software or Word). Scanned images can&apos;t be read.</li>
              <li>Have the original Word file? Use <strong>Import</strong> instead — it keeps the layout more closely.</li>
            </ul>
          </div>
        ) : (
          <div className="flex-1 flex overflow-hidden">
            <div className="w-[42%] border-r border-border overflow-auto bg-surface-muted/40 p-4">
              <p className="flex items-center gap-1.5 text-[11px] font-semibold text-foreground-muted mb-2">
                <FileText size={12} /> {fileName} — page 1{analysis.pageCount > 1 ? ` of ${analysis.pageCount}` : ""}
              </p>
              <img src={analysis.pageImage} alt="Uploaded payslip, page 1" className="w-full rounded border border-border bg-white" />
              <ul className="mt-3 text-[11px] text-foreground-muted list-disc pl-4 space-y-1">
                {analysis.notes.map((n) => <li key={n}>{n}</li>)}
              </ul>
            </div>
            <div className="flex-1 overflow-auto p-5 space-y-5">
              <div className="grid grid-cols-2 gap-3">
                <label className="block col-span-2">
                  <span className="block text-[11px] font-semibold text-foreground-muted mb-1">Template name</span>
                  <input value={form.name} onChange={(e) => set("name", e.target.value)} className={field} />
                </label>
                <label className="block">
                  <span className="block text-[11px] font-semibold text-foreground-muted mb-1">Title on the payslip</span>
                  <input value={form.title} maxLength={40} onChange={(e) => set("title", e.target.value)} className={field} />
                </label>
                <label className="block">
                  <span className="block text-[11px] font-semibold text-foreground-muted mb-1">Layout</span>
                  <select value={form.layout} onChange={(e) => set("layout", e.target.value)} className={field}>
                    <option value="side">Earnings and deductions side by side</option>
                    <option value="stacked">Earnings above deductions</option>
                  </select>
                </label>
                {[["primaryColor", "Main colour"], ["accentColor", "Net pay figure colour"]].map(([key, label]) => (
                  <label key={key} className="block">
                    <span className="block text-[11px] font-semibold text-foreground-muted mb-1">{label}</span>
                    <div className="flex items-center gap-2">
                      <input type="color" value={form[key]} onChange={(e) => set(key, e.target.value)}
                        className="w-8 h-8 rounded border border-border p-0.5 bg-transparent cursor-pointer" />
                      <input value={form[key]} onChange={(e) => set(key, e.target.value)} className={`${field} font-mono`} />
                    </div>
                    {key === "primaryColor" && analysis.colors.length > 1 && (
                      <div className="flex gap-1 mt-1">
                        {analysis.colors.map((c) => (
                          <button key={c} type="button" title={c} onClick={() => set("primaryColor", c)}
                            className="w-5 h-5 rounded border border-border cursor-pointer" style={{ backgroundColor: c }} />
                        ))}
                      </div>
                    )}
                  </label>
                ))}
                <div className="col-span-2 flex items-center gap-3">
                  {analysis.logoDataUri ? (
                    <>
                      <img src={analysis.logoDataUri} alt="Logo found in the PDF" className="h-10 rounded border border-border bg-white" />
                      <label className="flex items-center gap-1.5 text-[12px] text-foreground cursor-pointer">
                        <input type="checkbox" checked={form.includeLogo} onChange={(e) => set("includeLogo", e.target.checked)} />
                        Use this logo
                      </label>
                    </>
                  ) : (
                    <span className="text-[12px] text-foreground-muted">No logo found at the top of the PDF.</span>
                  )}
                </div>
              </div>

              <div>
                <p className="text-[12px] font-bold text-foreground mb-2">Section wording</p>
                <div className="grid grid-cols-2 gap-3">
                  {[["earningsTitle", "Earnings heading"], ["deductionsTitle", "Deductions heading"],
                    ["grossLabel", "Gross total label"], ["totalDeductionsLabel", "Deductions total label"],
                    ["netLabel", "Net pay label"]].map(([key, label]) => (
                    <label key={key} className="block">
                      <span className="block text-[11px] font-semibold text-foreground-muted mb-1">{label}</span>
                      <input value={form.sections[key]} maxLength={60} onChange={(e) => setSection(key, e.target.value)} className={field} />
                    </label>
                  ))}
                  <label className="flex items-center gap-1.5 text-[12px] text-foreground self-end pb-2 cursor-pointer">
                    <input type="checkbox" checked={!!form.sections.showNetInWords}
                      onChange={(e) => setSection("showNetInWords", e.target.checked)} />
                    Show net pay in words
                  </label>
                </div>
                <p className="text-[11px] text-foreground-muted mt-2">
                  The earnings and deduction lines themselves always come from each employee&apos;s payslip.
                </p>
              </div>

              <div>
                <p className="text-[12px] font-bold text-foreground mb-2">Employee and pay details found</p>
                {form.fields.length === 0 ? (
                  <p className="text-[12px] text-foreground-muted">No labelled fields were recognised; employee name will be shown.</p>
                ) : (
                  <table className="w-full text-[12px]">
                    <thead>
                      <tr className="text-left text-[10px] uppercase tracking-wider text-foreground-muted">
                        <th className="py-1 w-8">Use</th><th className="py-1">Label on payslip</th>
                        <th className="py-1">Value in your PDF</th><th className="py-1">Shows</th>
                      </tr>
                    </thead>
                    <tbody>
                      {form.fields.map((f, i) => (
                        <tr key={`${f.placeholder}-${i}`} className="border-t border-border">
                          <td className="py-1.5">
                            <input type="checkbox" checked={f.include} onChange={(e) => setField(i, "include", e.target.checked)} />
                          </td>
                          <td className="py-1.5 pr-2">
                            <input value={f.label} maxLength={60} onChange={(e) => setField(i, "label", e.target.value)} className={field} />
                          </td>
                          <td className="py-1.5 pr-2 text-foreground-muted truncate max-w-[140px]" title={f.value}>{f.value || "—"}</td>
                          <td className="py-1.5">
                            <select value={f.placeholder} onChange={(e) => setField(i, "placeholder", e.target.value)} className={field}>
                              {placeholderOptions.map((p) => <option key={p} value={p}>{PLACEHOLDER_NAMES[p] || p}</option>)}
                            </select>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>

              <label className="block">
                <span className="block text-[11px] font-semibold text-foreground-muted mb-1">Footer text</span>
                <textarea rows={2} maxLength={500} value={form.disclaimer} onChange={(e) => set("disclaimer", e.target.value)}
                  className={field} placeholder="This is a computer-generated payslip and does not require a signature." />
              </label>

              <div className="flex justify-end gap-2 pt-3 border-t border-border">
                <button type="button" onClick={() => { setAnalysis(null); setForm(null); }} disabled={busy}
                  className="px-4 py-2 rounded-[10px] text-[13px] font-semibold text-foreground-muted hover:bg-surface-muted cursor-pointer">
                  Choose another PDF
                </button>
                <button type="button" onClick={create} disabled={busy || !form.name.trim()}
                  className="px-4 py-2 rounded-[10px] bg-primary text-white text-[13px] font-semibold hover:bg-primary/90 disabled:opacity-50 cursor-pointer">
                  {busy ? "Creating…" : "Create draft template"}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
