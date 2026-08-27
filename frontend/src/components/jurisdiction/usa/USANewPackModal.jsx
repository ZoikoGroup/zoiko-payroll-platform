import { useState } from "react";
import Modal from "../../Modal";
import { useToast } from "../../../context/ToastContext";
import { upsertCompliancePolicy } from "../../../service/superAdminService";
import { inputClass, labelClass, STATUS_OPTIONS } from "../constants";

// USA-only replacement for the generic NewPackModal (every other country
// keeps using that one untouched — see JurisdictionLayout's
// newPackFormComponent prop, which defaults to NewPackModal and is only
// overridden here). Two differences, both purely cosmetic/field-visibility,
// same upsertCompliancePolicy payload/contract:
//   1. Drops "Tax Regime" — an India/UK-oriented field (Old/New regime,
//      current-year vs previous) that's never populated on any real US
//      JurisdictionPack (confirmed: always null in current data) — always
//      sent as null here rather than shown as an empty, irrelevant input.
//   2. Wider, multi-column ("square" instead of a single tall column)
//      layout grouped into labeled sections, matching the visual language
//      already used by USAComponentFormModal/USATaxSlabFormModal.
export default function USANewPackModal({ country, state, packType, onClose, onCreated }) {
  const { addToast } = useToast() || {};
  const [form, setForm] = useState({
    packId: "", jurisdictionState: state || "", version: "1.0", status: "Draft",
    effectiveFrom: "", effectiveTo: "", taxYear: "", currency: "",
    regulatoryAuthority: "", complianceCategory: "", complianceOwner: "", engineeringOwner: "", changeSummary: "",
    nextReviewDate: "", sourceReferences: "",
  });
  const [saving, setSaving] = useState(false);
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  async function save() {
    if (!form.packId.trim() || !form.effectiveFrom) {
      addToast?.("Pack ID and Effective From are required.", "error");
      return;
    }
    setSaving(true);
    try {
      const created = await upsertCompliancePolicy({
        packId: form.packId, jurisdictionCountry: country, jurisdictionState: form.jurisdictionState || null,
        packType, version: form.version, status: form.status,
        effectiveFrom: form.effectiveFrom, effectiveTo: form.effectiveTo || null,
        taxYear: form.taxYear || null, taxRegime: null, currency: form.currency || null,
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
      <div className="space-y-5">
        <FormSection title="General">
          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2"><label className={labelClass}>Pack ID</label><input className={inputClass} value={form.packId} onChange={set("packId")} placeholder="e.g. US-PAYROLL-2026-V1" /></div>
            <div><label className={labelClass}>State (optional)</label><input className={inputClass} value={form.jurisdictionState} onChange={set("jurisdictionState")} placeholder="e.g. California" /></div>
            <div><label className={labelClass}>Version</label><input className={inputClass} value={form.version} onChange={set("version")} /></div>
            <div><label className={labelClass}>Status</label><select className={inputClass} value={form.status} onChange={set("status")}>{STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}</select></div>
            <div><label className={labelClass}>Tax Year</label><input className={inputClass} value={form.taxYear} onChange={set("taxYear")} placeholder="2026" /></div>
          </div>
        </FormSection>

        <FormSection title="Effective Dates">
          <div className="grid grid-cols-3 gap-3">
            <div><label className={labelClass}>Effective From</label><input type="date" className={inputClass} value={form.effectiveFrom} onChange={set("effectiveFrom")} /></div>
            <div><label className={labelClass}>Effective To</label><input type="date" className={inputClass} value={form.effectiveTo} onChange={set("effectiveTo")} /></div>
            <div><label className={labelClass}>Currency</label><input className={inputClass} value={form.currency} onChange={set("currency")} placeholder="USD" /></div>
          </div>
        </FormSection>

        <FormSection title="Compliance Metadata">
          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-3"><label className={labelClass}>Regulatory Authority</label><input className={inputClass} value={form.regulatoryAuthority} onChange={set("regulatoryAuthority")} placeholder="e.g. Internal Revenue Service (IRS)" /></div>
            <div><label className={labelClass}>Compliance Category</label><input className={inputClass} value={form.complianceCategory} onChange={set("complianceCategory")} /></div>
            <div><label className={labelClass}>Compliance Owner</label><input className={inputClass} value={form.complianceOwner} onChange={set("complianceOwner")} /></div>
            <div><label className={labelClass}>Engineering Owner</label><input className={inputClass} value={form.engineeringOwner} onChange={set("engineeringOwner")} /></div>
            <div><label className={labelClass}>Next Review Date</label><input type="date" className={inputClass} value={form.nextReviewDate} onChange={set("nextReviewDate")} /></div>
            <div className="col-span-2"><label className={labelClass}>Source References</label><input className={inputClass} value={form.sourceReferences} onChange={set("sourceReferences")} placeholder="e.g. ZP-TAX-US-2026-001 v1.0" /></div>
            <div className="col-span-3"><label className={labelClass}>Change Summary</label><textarea className={inputClass} rows={2} value={form.changeSummary} onChange={set("changeSummary")} /></div>
          </div>
        </FormSection>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Creating…" : "Create"}</button>
      </div>
    </Modal>
  );
}

function FormSection({ title, children }) {
  return (
    <div>
      <p className="mb-2 text-[11px] font-bold uppercase tracking-wider text-foreground-muted">{title}</p>
      {children}
    </div>
  );
}
