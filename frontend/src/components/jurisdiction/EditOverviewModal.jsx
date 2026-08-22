import { useState } from "react";
import Modal from "../Modal";
import { useToast } from "../../context/ToastContext";
import { upsertCompliancePolicy } from "../../service/superAdminService";
import { inputClass, labelClass } from "./constants";

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
  });
  const [saving, setSaving] = useState(false);
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  async function save() {
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
    <Modal title={`Edit ${pack.packId} — Overview`} onClose={onClose} maxWidth="max-w-md">
      <div className="grid grid-cols-2 gap-3">
        <div><label className={labelClass}>Tax Year</label><input className={inputClass} value={form.taxYear} onChange={set("taxYear")} placeholder="2026-27" /></div>
        <div><label className={labelClass}>Tax Regime</label><input className={inputClass} value={form.taxRegime} onChange={set("taxRegime")} placeholder="Old / New" /></div>
        <div><label className={labelClass}>Effective From</label><input type="date" className={inputClass} value={form.effectiveFrom} onChange={set("effectiveFrom")} /></div>
        <div><label className={labelClass}>Effective To</label><input type="date" className={inputClass} value={form.effectiveTo} onChange={set("effectiveTo")} /></div>
        <div><label className={labelClass}>Currency</label><input className={inputClass} value={form.currency} onChange={set("currency")} placeholder="INR" /></div>
        <div><label className={labelClass}>Next Review Date</label><input type="date" className={inputClass} value={form.nextReviewDate} onChange={set("nextReviewDate")} /></div>
        <div className="col-span-2"><label className={labelClass}>Regulatory Authority</label><input className={inputClass} value={form.regulatoryAuthority} onChange={set("regulatoryAuthority")} /></div>
        <div><label className={labelClass}>Compliance Category</label><input className={inputClass} value={form.complianceCategory} onChange={set("complianceCategory")} /></div>
        <div><label className={labelClass}>Compliance Owner</label><input className={inputClass} value={form.complianceOwner} onChange={set("complianceOwner")} /></div>
        <div className="col-span-2"><label className={labelClass}>Engineering Owner</label><input className={inputClass} value={form.engineeringOwner} onChange={set("engineeringOwner")} /></div>
        <div className="col-span-2"><label className={labelClass}>Source References</label><input className={inputClass} value={form.sourceReferences} onChange={set("sourceReferences")} /></div>
        <div className="col-span-2"><label className={labelClass}>Change Summary</label><textarea className={inputClass} rows={2} value={form.changeSummary} onChange={set("changeSummary")} /></div>
        <div className="col-span-2"><label className={labelClass}>Reason for this edit (optional)</label><input className={inputClass} value={form.reason} onChange={set("reason")} placeholder="e.g. Corrected per ZP-TAX-UK-2026-27-001" /></div>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Saving…" : "Save"}</button>
      </div>
    </Modal>
  );
}
