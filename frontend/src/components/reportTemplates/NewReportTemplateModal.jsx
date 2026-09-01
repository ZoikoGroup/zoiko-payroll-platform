import { useState, useEffect } from "react";
import Modal from "../Modal";
import { useToast } from "../../context/ToastContext";
import { upsertReportTemplate, getSourceArtifacts } from "../../service/superAdminService";
import { inputClass, labelClass } from "../jurisdiction/constants";

// Jurisdiction is fixed by the page this modal is opened from (never a
// dropdown here) — matches JurisdictionLayout/NewPackModal's convention
// that country/state come from routing, not from this form.
export default function NewReportTemplateModal({ country, countryName, state, onClose, onCreated }) {
  const { addToast } = useToast() || {};
  const [form, setForm] = useState({
    templateKey: "", name: "", reportType: "", jurisdictionState: state || "",
    reportingYear: "", version: "1.0", effectiveFrom: "", effectiveTo: "",
    regulatoryAuthority: "", description: "", changeSummary: "", sourceReferences: "",
    reconciliationTolerance: "", documentScope: "AGGREGATE", sourceDocumentId: "",
  });
  const [saving, setSaving] = useState(false);
  const [sourceArtifacts, setSourceArtifacts] = useState([]);
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  // Real, backend-owned evidence list — reused as-is from Compliance's own
  // source-artifact store rather than a parallel evidence system.
  useEffect(() => { getSourceArtifacts().then(setSourceArtifacts).catch(() => {}); }, []);

  async function save() {
    if (!form.templateKey.trim() || !form.name.trim() || !form.reportType.trim() || !form.reportingYear.trim()) {
      addToast?.("Template Key, Report Name, Report Type and Reporting Year are required.", "error");
      return;
    }
    setSaving(true);
    try {
      const created = await upsertReportTemplate({
        templateKey: form.templateKey.trim(), name: form.name.trim(), reportType: form.reportType.trim().toUpperCase(),
        jurisdictionCountry: country, jurisdictionState: form.jurisdictionState || null,
        reportingYear: form.reportingYear.trim(), version: form.version,
        effectiveFrom: form.effectiveFrom || null, effectiveTo: form.effectiveTo || null,
        regulatoryAuthority: form.regulatoryAuthority || null, description: form.description || null,
        changeSummary: form.changeSummary || null, sourceReferences: form.sourceReferences || null,
        reconciliationTolerance: form.reconciliationTolerance ? Number(form.reconciliationTolerance) : null,
        documentScope: form.documentScope,
        sourceDocumentId: form.sourceDocumentId ? Number(form.sourceDocumentId) : null,
      });
      addToast?.("Report template created.", "success");
      onCreated(created);
    } catch (err) {
      addToast?.(err.message || "Failed to create report template.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={`New Report Template — ${countryName}`} onClose={onClose} maxWidth="max-w-2xl">
      <div className="grid grid-cols-3 gap-3">
        <div className="col-span-2">
          <label className={labelClass}>Template Key</label>
          <input className={inputClass} value={form.templateKey} onChange={set("templateKey")} placeholder="e.g. IN-TDS-SALARY" />
        </div>
        <div>
          <label className={labelClass}>State (optional)</label>
          <input className={inputClass} value={form.jurisdictionState} onChange={set("jurisdictionState")} placeholder="Country-level if blank" />
        </div>
        <div className="col-span-2">
          <label className={labelClass}>Report Name</label>
          <input className={inputClass} value={form.name} onChange={set("name")} placeholder="e.g. Salary TDS Report" />
        </div>
        <div>
          <label className={labelClass}>Report Type</label>
          <input className={inputClass} list="report-type-suggestions" value={form.reportType} onChange={set("reportType")} placeholder="TDS" />
          <datalist id="report-type-suggestions">
            <option value="TDS" />
            <option value="P60" />
            <option value="941" />
          </datalist>
        </div>
        <div>
          <label className={labelClass}>Reporting Year</label>
          <input className={inputClass} value={form.reportingYear} onChange={set("reportingYear")} placeholder="2026-27" />
        </div>
        <div>
          <label className={labelClass}>Version</label>
          <input className={inputClass} value={form.version} onChange={set("version")} />
        </div>
        <div>
          <label className={labelClass}>Document Scope</label>
          <select className={inputClass} value={form.documentScope} onChange={set("documentScope")}>
            <option value="AGGREGATE">Aggregate (one document for the run)</option>
            <option value="PER_EMPLOYEE">Per-Employee (one document each)</option>
          </select>
        </div>
        <div className="col-span-2">
          <label className={labelClass}>Source Document (optional)</label>
          <select className={inputClass} value={form.sourceDocumentId} onChange={set("sourceDocumentId")}>
            <option value="">No linked source document</option>
            {sourceArtifacts.map((a) => (
              <option key={a.id} value={a.id}>{a.agency} — {a.title}</option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelClass}>Effective From</label>
          <input type="date" className={inputClass} value={form.effectiveFrom} onChange={set("effectiveFrom")} />
        </div>
        <div>
          <label className={labelClass}>Effective To</label>
          <input type="date" className={inputClass} value={form.effectiveTo} onChange={set("effectiveTo")} />
        </div>
        <div className="col-span-3">
          <label className={labelClass}>Regulatory Authority</label>
          <input className={inputClass} value={form.regulatoryAuthority} onChange={set("regulatoryAuthority")} placeholder="e.g. Income Tax Department" />
        </div>
        <div className="col-span-2">
          <label className={labelClass}>Reconciliation Tolerance</label>
          <input type="number" step="0.01" className={inputClass} value={form.reconciliationTolerance} onChange={set("reconciliationTolerance")} placeholder="0.00 (exact match)" />
        </div>
        <div className="col-span-3">
          <label className={labelClass}>Description</label>
          <textarea className={inputClass} rows={2} value={form.description} onChange={set("description")} />
        </div>
        <div className="col-span-3">
          <label className={labelClass}>Source References</label>
          <input className={inputClass} value={form.sourceReferences} onChange={set("sourceReferences")} placeholder="e.g. ZP-TAX-IN-2026-27-001 v1.0" />
        </div>
        <div className="col-span-3">
          <label className={labelClass}>Change Summary</label>
          <textarea className={inputClass} rows={2} value={form.changeSummary} onChange={set("changeSummary")} />
        </div>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Creating…" : "Create"}</button>
      </div>
    </Modal>
  );
}
