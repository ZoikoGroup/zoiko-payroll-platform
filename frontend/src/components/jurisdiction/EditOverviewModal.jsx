import { useEffect, useState } from "react";
import Modal from "../Modal";
import { useToast } from "../../context/ToastContext";
import { upsertCompliancePolicy, getSourceArtifacts } from "../../service/superAdminService";
import { inputClass, labelClass } from "./constants";
import { taxYearDateProblem } from "./taxYear";

// Tax packs' Overview tab was read-only — no way to fix a typo in
// Regulatory Authority, correct the Tax Year, etc. after creation without
// this. packId/jurisdictionCountry/jurisdictionState/version/status are
// deliberately NOT editable here (those are the pack's structural
// identity/lifecycle, changed via other, more deliberate flows) — only
// the descriptive metadata already shown on the Overview tab.
export default function EditOverviewModal({ pack, onClose, onSaved }) {
  const { addToast } = useToast() || {};
  const [form, setForm] = useState({
    taxYear: pack.taxYear || "", effectiveFrom: pack.effectiveFrom || "", effectiveTo: pack.effectiveTo || "",
    taxRegime: pack.taxRegime || "", currency: pack.currency || "",
    regulatoryAuthority: pack.regulatoryAuthority || "", complianceCategory: pack.complianceCategory || "",
    complianceOwner: pack.complianceOwner || "", engineeringOwner: pack.engineeringOwner || "",
    nextReviewDate: pack.nextReviewDate || "", sourceReferences: pack.sourceReferences || "",
    changeSummary: pack.changeSummary || "", reason: "",
    sourceDocumentId: pack.sourceDocumentId ? String(pack.sourceDocumentId) : "",
  });
  const [saving, setSaving] = useState(false);
  // Source Evidence recorded under Super Admin > Compliance. No screen could
  // link one to a pack, so the source-locked countries (US ...) could never
  // pass their activation gate (2026-11-17).
  const [sources, setSources] = useState([]);
  useEffect(() => {
    let cancelled = false;
    getSourceArtifacts().then((rows) => { if (!cancelled) setSources(rows || []); }).catch(() => {});
    return () => { cancelled = true; };
  }, []);
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  // Same rule as the server: checked only when the tax year or a date is
  // changed here — an existing value is never flagged on an unrelated edit.
  const datesOrYearChanged = (form.taxYear || "") !== (pack.taxYear || "")
    || (form.effectiveFrom || "") !== (pack.effectiveFrom || "") || (form.effectiveTo || "") !== (pack.effectiveTo || "");
  const taxYearProblem = datesOrYearChanged ? taxYearDateProblem(form.taxYear, form.effectiveFrom, form.effectiveTo) : null;

  async function save() {
    if (taxYearProblem) {
      addToast?.(taxYearProblem, "error");
      return;
    }
    setSaving(true);
    try {
      const updated = await upsertCompliancePolicy({
        id: pack.id, packId: pack.packId, jurisdictionCountry: pack.jurisdictionCountry,
        jurisdictionState: pack.jurisdictionState || null, packType: pack.packType,
        version: pack.version, status: pack.status,
        effectiveFrom: form.effectiveFrom || null, effectiveTo: form.effectiveTo || null,
        taxYear: form.taxYear || null, taxRegime: form.taxRegime || null, currency: form.currency || null,
        regulatoryAuthority: form.regulatoryAuthority || null, complianceCategory: form.complianceCategory || null,
        complianceOwner: form.complianceOwner || null, engineeringOwner: form.engineeringOwner || null,
        nextReviewDate: form.nextReviewDate || null, sourceReferences: form.sourceReferences || null,
        changeSummary: form.changeSummary || null, reason: form.reason || null,
        sourceDocumentId: form.sourceDocumentId ? Number(form.sourceDocumentId) : null,
      });
      addToast?.("Overview details saved.", "success");
      onSaved(updated);
    } catch (err) {
      addToast?.(err.message || "Failed to save.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={`Edit ${pack.packId} — Overview`} onClose={onClose} maxWidth="max-w-2xl">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div>
          <label className={labelClass} htmlFor="pack-tax-year">Tax Year</label>
          <input id="pack-tax-year" className={inputClass} value={form.taxYear} onChange={set("taxYear")} placeholder="2026 or 2026-27"
            aria-invalid={taxYearProblem ? true : undefined} aria-describedby={taxYearProblem ? "pack-tax-year-problem" : undefined} />
          {taxYearProblem && <p id="pack-tax-year-problem" role="alert" data-testid="tax-year-problem" className="mt-1 text-[11px] text-error">{taxYearProblem}</p>}
        </div>
        <div><label className={labelClass}>Tax Regime</label><input className={inputClass} value={form.taxRegime} onChange={set("taxRegime")} placeholder="Old / New" /></div>
        <div><label className={labelClass}>Currency</label><input className={inputClass} value={form.currency} onChange={set("currency")} placeholder="INR" /></div>
        <div><label className={labelClass}>Effective From</label><input type="date" className={inputClass} value={form.effectiveFrom} onChange={set("effectiveFrom")} /></div>
        <div><label className={labelClass}>Effective To</label><input type="date" className={inputClass} value={form.effectiveTo} onChange={set("effectiveTo")} /></div>
        <div><label className={labelClass}>Next Review Date</label><input type="date" className={inputClass} value={form.nextReviewDate} onChange={set("nextReviewDate")} /></div>
        <div className="col-span-3"><label className={labelClass}>Regulatory Authority</label><input className={inputClass} value={form.regulatoryAuthority} onChange={set("regulatoryAuthority")} /></div>
        <div><label className={labelClass}>Compliance Category</label><input className={inputClass} value={form.complianceCategory} onChange={set("complianceCategory")} /></div>
        <div><label className={labelClass}>Compliance Owner</label><input className={inputClass} value={form.complianceOwner} onChange={set("complianceOwner")} /></div>
        <div><label className={labelClass}>Engineering Owner</label><input className={inputClass} value={form.engineeringOwner} onChange={set("engineeringOwner")} /></div>
        <div className="col-span-3">
          <label className={labelClass}>Source document (Source Evidence)</label>
          <select className={inputClass} value={form.sourceDocumentId} onChange={set("sourceDocumentId")}>
            <option value="">— None linked —</option>
            {sources.map((s) => (
              <option key={s.id} value={String(s.id)}>
                #{s.id} · {s.agency} · {s.formNumber ? `${s.formNumber} · ` : ""}{s.title}{s.hasFile ? "" : " (no file uploaded)"}
              </option>
            ))}
          </select>
        </div>
        <div className="col-span-3"><label className={labelClass}>Source References</label><input className={inputClass} value={form.sourceReferences} onChange={set("sourceReferences")} /></div>
        <div className="col-span-3"><label className={labelClass}>Change Summary</label><textarea className={inputClass} rows={2} value={form.changeSummary} onChange={set("changeSummary")} /></div>
        <div className="col-span-3"><label className={labelClass}>Reason for this edit (optional)</label><input className={inputClass} value={form.reason} onChange={set("reason")} placeholder="e.g. Corrected per ZP-TAX-UK-2026-27-001" /></div>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving || Boolean(taxYearProblem)} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Saving…" : "Save"}</button>
      </div>
    </Modal>
  );
}
