import { useRef, useState } from "react";
import { FileCode, UploadCloud, X } from "lucide-react";
import { importPayslipTemplate } from "../../../../service/payrollService";
import { useToast } from "../../ToastContext";

const MAX_HTML_BYTES = 200_000;
const MAX_DOCX_BYTES = 5_000_000;

export default function PayslipTemplateImportModal({ isOpen, onClose, onImported }) {
  const { addToast } = useToast();
  const [file, setFile] = useState(null);
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [description, setDescription] = useState("");
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef(null);

  if (!isOpen) return null;

  const reset = () => { setFile(null); setName(""); setCode(""); setDescription(""); };
  const close = () => { reset(); onClose(); };

  const pick = (f) => {
    if (!f) return;
    const isWord = /\.docx$/i.test(f.name);
    if (/\.pdf$/i.test(f.name)) {
      addToast?.("PDF files are imported with \"Import PDF\", which builds a template from the design.", "error");
      return;
    }
    if (!isWord && !/\.html?$/i.test(f.name)) {
      addToast?.("Only Word (.docx) or HTML (.html/.htm) files can be imported here.", "error");
      return;
    }
    if (f.size > (isWord ? MAX_DOCX_BYTES : MAX_HTML_BYTES)) {
      addToast?.(isWord ? "The Word file is larger than 5 MB." : "The HTML file is larger than 200 KB.", "error");
      return;
    }
    setFile(f);
    if (!name) setName(f.name.replace(/\.[^.]+$/, "").replace(/[-_]+/g, " "));
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!file || !name.trim()) return;
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("name", name.trim());
      if (code.trim()) form.append("code", code.trim());
      if (description.trim()) form.append("description", description.trim());
      const created = await importPayslipTemplate(form);
      addToast?.(`"${created.name}" imported as a draft.`, "success");
      if (created.warnings?.length) addToast?.(created.warnings.join(" "), "warning");
      reset();
      onClose();
      onImported?.(created);
    } catch (err) {
      addToast?.(err.message || "Import failed.", "error");
    } finally {
      setUploading(false);
    }
  };

  const field = "w-full rounded-[10px] border border-border bg-surface px-3 py-2 text-[13px] text-foreground focus:outline-none focus:border-primary";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="bg-surface border border-border rounded-[18px] shadow-2xl w-full max-w-lg overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3 border-b border-border">
          <div>
            <h3 className="text-[15px] font-bold text-foreground">Import payslip template</h3>
            <p className="text-[12px] text-foreground-muted">A Word (.docx) or HTML file that uses the payslip placeholders.</p>
          </div>
          <button type="button" onClick={close} aria-label="Close"
            className="p-1.5 rounded-[10px] text-foreground-muted hover:bg-surface-muted hover:text-foreground cursor-pointer">
            <X size={18} />
          </button>
        </div>
        <form onSubmit={submit} className="p-5 space-y-4">
          <button type="button" onClick={() => inputRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); pick(e.dataTransfer.files?.[0]); }}
            className="w-full rounded-[14px] border-2 border-dashed border-border p-6 text-center hover:border-primary/50 cursor-pointer">
            <input ref={inputRef} type="file" accept=".docx,.html,.htm" className="hidden" onChange={(e) => pick(e.target.files?.[0])} />
            {file ? (
              <span className="flex items-center justify-center gap-2 text-[13px] font-semibold text-foreground">
                <FileCode size={20} className="text-primary" /> {file.name} ({(file.size / 1024).toFixed(1)} KB)
              </span>
            ) : (
              <span className="flex flex-col items-center gap-1 text-[13px] text-foreground-muted">
                <UploadCloud size={26} /> Click or drop a .docx (max 5 MB) or .html file (max 200 KB)
              </span>
            )}
          </button>
          <label className="block">
            <span className="block text-[11px] font-semibold text-foreground-muted mb-1">Name *</span>
            <input required value={name} onChange={(e) => setName(e.target.value)} className={field} />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="block text-[11px] font-semibold text-foreground-muted mb-1">Code (optional)</span>
              <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="Generated if empty" className={`${field} font-mono`} />
            </label>
            <label className="block">
              <span className="block text-[11px] font-semibold text-foreground-muted mb-1">Description</span>
              <input value={description} onChange={(e) => setDescription(e.target.value)} className={field} />
            </label>
          </div>
          <div className="rounded-[10px] border border-border bg-surface-muted/40 p-3 text-[11px] text-foreground-muted space-y-1">
            <p className="font-semibold text-foreground">Preparing a Word file</p>
            <p>Type placeholders where the data goes, e.g. <code>{"{{ employee.name }}"}</code>,{" "}
              <code>{"{{ payroll.period }}"}</code>, <code>{"{{ totals.net_pay_formatted }}"}</code>.</p>
            <p>For the earnings table, make one row with <code>{"{{ earning.label }}"}</code> and{" "}
              <code>{"{{ earning.amount_formatted }}"}</code> — it repeats for every earnings line. Same for{" "}
              <code>{"{{ deduction.label }}"}</code> / <code>{"{{ deduction.amount_formatted }}"}</code>.</p>
            <p>Links become plain text. Scripts, external images/links and <code>|safe</code> are rejected. The import is
              saved as a draft; preview and publish it from the editor.</p>
          </div>
          <div className="flex justify-end gap-2 pt-2 border-t border-border">
            <button type="button" onClick={close} disabled={uploading}
              className="px-4 py-2 rounded-[10px] text-[13px] font-semibold text-foreground-muted hover:bg-surface-muted cursor-pointer">Cancel</button>
            <button type="submit" disabled={uploading || !file || !name.trim()}
              className="px-4 py-2 rounded-[10px] bg-primary text-white text-[13px] font-semibold hover:bg-primary/90 disabled:opacity-50 cursor-pointer">
              {uploading ? "Importing…" : "Import"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
