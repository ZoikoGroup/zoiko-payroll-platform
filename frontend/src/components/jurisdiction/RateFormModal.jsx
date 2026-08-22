import { useState } from "react";
import Modal from "../Modal";
import { useToast } from "../../context/ToastContext";
import { upsertCanonicalContributionRate } from "../../service/superAdminService";
import { inputClass, labelClass } from "./constants";

export default function RateFormModal({ pack, rate, onClose, onSaved }) {
  const { addToast } = useToast() || {};
  const [form, setForm] = useState({
    componentKey: rate?.componentKey || "", label: rate?.label || "",
    jurisdictionState: rate?.jurisdictionState || pack.jurisdictionState || "",
    employeeSharePct: rate?.employeeRatePct ?? "", employerSharePct: rate?.employerRatePct ?? "",
    flatAmount: rate?.flatAmount ?? "", sortOrder: rate?.sortOrder ?? 0, reason: "",
  });
  const [saving, setSaving] = useState(false);
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  async function save() {
    if (!form.componentKey.trim() || !form.label.trim()) {
      addToast?.("Component key and label are required.", "error");
      return;
    }
    setSaving(true);
    try {
      await upsertCanonicalContributionRate({
        id: rate?.id, jurisdictionPackId: pack.id, jurisdictionCountry: pack.jurisdictionCountry,
        jurisdictionState: form.jurisdictionState || null, taxRegime: pack.taxRegime || null,
        componentKey: form.componentKey, label: form.label,
        employeeSharePct: form.employeeSharePct === "" ? null : form.employeeSharePct,
        employerSharePct: form.employerSharePct === "" ? null : form.employerSharePct,
        flatAmount: form.flatAmount === "" ? null : form.flatAmount,
        sortOrder: Number(form.sortOrder) || 0, reason: form.reason || null,
      });
      addToast?.("Rate saved.", "success");
      onSaved();
    } catch (err) {
      addToast?.(err.message || "Failed to save rate.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={rate ? "Edit Contribution Rate" : "Add Contribution Rate"} onClose={onClose} maxWidth="max-w-md">
      <div className="grid grid-cols-2 gap-3">
        <div><label className={labelClass}>Component Key</label><input className={inputClass} value={form.componentKey} onChange={set("componentKey")} placeholder="e.g. pf" /></div>
        <div><label className={labelClass}>Label</label><input className={inputClass} value={form.label} onChange={set("label")} placeholder="e.g. Provident Fund" /></div>
        <div className="col-span-2"><label className={labelClass}>State (optional — overrides country-level for this state)</label><input className={inputClass} value={form.jurisdictionState} onChange={set("jurisdictionState")} /></div>
        <div><label className={labelClass}>Employee Rate %</label><input className={inputClass} value={form.employeeSharePct} onChange={set("employeeSharePct")} placeholder="12.00" /></div>
        <div><label className={labelClass}>Employer Rate %</label><input className={inputClass} value={form.employerSharePct} onChange={set("employerSharePct")} placeholder="12.00" /></div>
        <div><label className={labelClass}>Flat Amount</label><input className={inputClass} value={form.flatAmount} onChange={set("flatAmount")} placeholder="e.g. 200 for a flat fee" /></div>
        <div><label className={labelClass}>Sort Order</label><input type="number" className={inputClass} value={form.sortOrder} onChange={set("sortOrder")} /></div>
        <div className="col-span-2"><label className={labelClass}>Reason for change (optional)</label><input className={inputClass} value={form.reason} onChange={set("reason")} placeholder="e.g. ZP-TAX-UK-2026-27-001 section 9.1" /></div>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Saving…" : "Save"}</button>
      </div>
    </Modal>
  );
}
