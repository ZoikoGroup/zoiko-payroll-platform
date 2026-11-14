import { useState } from "react";
import Modal from "../Modal";
import { useToast } from "../../context/ToastContext";
import { upsertCompliancePolicy } from "../../service/superAdminService";
import { inputClass, labelClass, STATUS_OPTIONS, POLICY_STATUS_OPTIONS, nextPackVersion } from "./constants";

// "New Version" passes `basePack` (the pack being versioned): the form starts
// on the next free version number with that pack's metadata, instead of
// version "1.0" with blank fields - which, with the same Pack ID, used to
// overwrite the existing 1.0 row in place.
export default function NewPackModal({ country, state, packType, stateOptions = [], onClose, onCreated, defaultPackId, basePack = null, existingVersions = [] }) {
  const { addToast } = useToast() || {};
  const b = basePack || {};
  const [form, setForm] = useState({
    packId: defaultPackId || "", jurisdictionState: b.jurisdictionState || state || "",
    version: basePack ? nextPackVersion(b.version, existingVersions) : "1.0", status: "Draft",
    effectiveFrom: "", effectiveTo: "", taxYear: "", taxRegime: b.taxRegime || "", currency: b.currency || "",
    regulatoryAuthority: b.regulatoryAuthority || "", complianceCategory: b.complianceCategory || "",
    complianceOwner: b.complianceOwner || "", engineeringOwner: b.engineeringOwner || "", changeSummary: "",
    nextReviewDate: "", sourceReferences: b.sourceReferences || "",
  });
  const [saving, setSaving] = useState(false);
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  async function save() {
    if (!form.packId.trim() || !form.effectiveFrom || !form.version.trim()) {
      addToast?.("Pack ID, Version and Effective From are required.", "error");
      return;
    }
    if (existingVersions.includes(form.version.trim())) {
      addToast?.(`Version ${form.version.trim()} already exists - open it and use Edit, or choose another version.`, "error");
      return;
    }
    setSaving(true);
    try {
      const created = await upsertCompliancePolicy({
        packId: form.packId, jurisdictionCountry: country, jurisdictionState: form.jurisdictionState || null,
        packType, version: form.version, status: form.status,
        effectiveFrom: form.effectiveFrom, effectiveTo: form.effectiveTo || null,
        taxYear: form.taxYear || null, taxRegime: form.taxRegime || null, currency: form.currency || null,
        regulatoryAuthority: form.regulatoryAuthority || null, complianceCategory: form.complianceCategory || null,
        complianceOwner: form.complianceOwner || null, engineeringOwner: form.engineeringOwner || null,
        nextReviewDate: form.nextReviewDate || null, sourceReferences: form.sourceReferences || null,
        changeSummary: form.changeSummary || null,
      });
      addToast?.("Pack created.", "success");
      onCreated(created);
    } catch (err) {
      addToast?.(err.message || "Failed to create pack.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={`New ${packType === "tax" ? "Tax" : "Policy"} Pack`} onClose={onClose} maxWidth="max-w-2xl">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="col-span-2"><label className={labelClass}>Pack ID</label><input className={inputClass} value={form.packId} onChange={set("packId")} placeholder="e.g. IN-PAYROLL-2026-V1" /></div>
        <div>
          <label className={labelClass}>State (optional)</label>
          {stateOptions.length > 0 ? (
            // A fixed state list (e.g. Canada's 13 provinces/territories)
            // prevents a typo (e.g. "Ontario" instead of "ON") from
            // silently creating a pack the engine's exact-match state
            // resolver will never actually select for any employee.
            <select className={inputClass} value={form.jurisdictionState} onChange={set("jurisdictionState")}>
              <option value="">— Country-level (no state) —</option>
              {stateOptions.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          ) : (
            <input className={inputClass} value={form.jurisdictionState} onChange={set("jurisdictionState")} placeholder="e.g. Maharashtra" />
          )}
        </div>
        <div><label className={labelClass}>Version</label><input className={inputClass} value={form.version} onChange={set("version")} /></div>
        <div><label className={labelClass}>Status</label><select className={inputClass} value={form.status} onChange={set("status")}>{(packType === "policy" ? POLICY_STATUS_OPTIONS : STATUS_OPTIONS).map((s) => <option key={s} value={s}>{s}</option>)}</select></div>
        <div><label className={labelClass}>Tax Year</label><input className={inputClass} value={form.taxYear} onChange={set("taxYear")} placeholder="2026-27" /></div>
        <div><label className={labelClass}>Effective From</label><input type="date" className={inputClass} value={form.effectiveFrom} onChange={set("effectiveFrom")} /></div>
        <div><label className={labelClass}>Effective To</label><input type="date" className={inputClass} value={form.effectiveTo} onChange={set("effectiveTo")} /></div>
        <div><label className={labelClass}>Tax Regime</label><input className={inputClass} value={form.taxRegime} onChange={set("taxRegime")} placeholder="Old / New" /></div>
        <div><label className={labelClass}>Currency</label><input className={inputClass} value={form.currency} onChange={set("currency")} placeholder="INR" /></div>
        <div><label className={labelClass}>Compliance Category</label><input className={inputClass} value={form.complianceCategory} onChange={set("complianceCategory")} /></div>
        <div className="col-span-3"><label className={labelClass}>Regulatory Authority</label><input className={inputClass} value={form.regulatoryAuthority} onChange={set("regulatoryAuthority")} /></div>
        <div><label className={labelClass}>Compliance Owner</label><input className={inputClass} value={form.complianceOwner} onChange={set("complianceOwner")} /></div>
        <div><label className={labelClass}>Engineering Owner</label><input className={inputClass} value={form.engineeringOwner} onChange={set("engineeringOwner")} /></div>
        <div><label className={labelClass}>Next Review Date</label><input type="date" className={inputClass} value={form.nextReviewDate} onChange={set("nextReviewDate")} /></div>
        <div className="col-span-3"><label className={labelClass}>Source References</label><input className={inputClass} value={form.sourceReferences} onChange={set("sourceReferences")} placeholder="e.g. ZP-TAX-UK-2026-27-001 v1.0" /></div>
        <div className="col-span-3"><label className={labelClass}>Change Summary</label><textarea className={inputClass} rows={2} value={form.changeSummary} onChange={set("changeSummary")} /></div>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Creating…" : "Create"}</button>
      </div>
    </Modal>
  );
}
