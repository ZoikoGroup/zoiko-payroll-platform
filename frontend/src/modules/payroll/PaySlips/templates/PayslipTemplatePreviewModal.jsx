import { useEffect, useState } from "react";
import { AlertTriangle, FileDown, Globe, X, ZoomIn, ZoomOut } from "lucide-react";
import { downloadPayslipTemplateSamplePdf, previewPayslipTemplate } from "../../../../service/payrollService";

/** Preview a template (or starter) with sample data. `template.latestVersion`
 * holds htmlContent / cssContent / configurationJson. */
export default function PayslipTemplatePreviewModal({ template, countries = [], onClose }) {
  // Sample data only for the organisation's own countries (the API falls back to its default country).
  const [country, setCountry] = useState(countries[0]?.code || "IN");
  // Remounted per template (key in the dashboard); one result per country.
  const [result, setResult] = useState({ country: null, doc: "", error: "" });
  const [zoom, setZoom] = useState(100);
  const [pdfState, setPdfState] = useState({ busy: false, error: "" });
  const version = template?.latestVersion;

  const samplePdf = async () => {
    setPdfState({ busy: true, error: "" });
    try {
      await downloadPayslipTemplateSamplePdf({
        htmlContent: version?.htmlContent || "", cssContent: version?.cssContent || "",
        configurationJson: version?.configurationJson || {}, country,
      });
      setPdfState({ busy: false, error: "" });
    } catch (err) {
      setPdfState({ busy: false, error: err.message || "Could not create the sample PDF." });
    }
  };

  useEffect(() => {
    if (!version) return undefined;
    let cancelled = false;
    previewPayslipTemplate({
      htmlContent: version.htmlContent || "",
      cssContent: version.cssContent || "",
      configurationJson: version.configurationJson || {},
      country,
    })
      .then((res) => { if (!cancelled) setResult({ country, doc: res?.renderedHtml || "", error: "" }); })
      .catch((err) => { if (!cancelled) setResult({ country, doc: "", error: err.message || "Preview failed." }); });
    return () => { cancelled = true; };
  }, [version, country]);

  if (!template) return null;
  const loading = result.country !== country;
  const { doc, error } = loading ? { doc: "", error: "" } : result;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="bg-surface border border-border rounded-[18px] shadow-2xl flex flex-col w-full max-w-5xl h-[92vh] overflow-hidden">
        <div className="flex items-center justify-between gap-3 px-5 py-3 border-b border-border">
          <div>
            <h3 className="text-[15px] font-bold text-foreground">{template.name}</h3>
            <p className="text-[12px] text-foreground-muted">Preview with sample data — not a real employee.</p>
          </div>
          <div className="flex items-center gap-2">
            {countries.length > 1 && (
              <label className="flex items-center gap-1.5 rounded-[10px] border border-border px-2.5 py-1.5">
                <Globe size={13} className="text-foreground-muted" />
                <select value={country} onChange={(e) => setCountry(e.target.value)}
                  className="bg-transparent text-[12px] font-semibold text-foreground focus:outline-none cursor-pointer">
                  {countries.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
                </select>
              </label>
            )}
            <div className="flex items-center rounded-[10px] border border-border">
              <button type="button" className="p-1.5 text-foreground-muted hover:text-foreground cursor-pointer" aria-label="Zoom out"
                onClick={() => setZoom((z) => Math.max(50, z - 10))}><ZoomOut size={14} /></button>
              <span className="text-[11px] font-semibold w-10 text-center">{zoom}%</span>
              <button type="button" className="p-1.5 text-foreground-muted hover:text-foreground cursor-pointer" aria-label="Zoom in"
                onClick={() => setZoom((z) => Math.min(150, z + 10))}><ZoomIn size={14} /></button>
            </div>
            <button type="button" onClick={samplePdf} disabled={pdfState.busy}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-[10px] border border-border text-[12px] font-semibold text-foreground hover:bg-surface-muted disabled:opacity-50 cursor-pointer">
              <FileDown size={13} /> {pdfState.busy ? "Creating…" : "Sample PDF"}
            </button>
            <button type="button" onClick={onClose} aria-label="Close"
              className="p-1.5 rounded-[10px] text-foreground-muted hover:bg-surface-muted hover:text-foreground cursor-pointer">
              <X size={18} />
            </button>
          </div>
        </div>
        {(error || pdfState.error) && (
          <div className="flex items-center gap-2 px-5 py-2 text-[12px] bg-error/10 text-error border-b border-border">
            <AlertTriangle size={14} /> {error || pdfState.error}
          </div>
        )}
        <div className="flex-1 overflow-auto bg-surface-muted/40 p-6 flex justify-center items-start">
          {loading ? (
            <p className="text-[13px] text-foreground-muted py-20">Rendering…</p>
          ) : doc ? (
            <div style={{ transform: `scale(${zoom / 100})`, transformOrigin: "top center" }}
              className="w-[820px] bg-white shadow-lg rounded-md overflow-hidden">
              <iframe srcDoc={doc} title="Payslip template preview" sandbox="" referrerPolicy="no-referrer"
                className="w-full h-[1100px] border-0 bg-white" />
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
