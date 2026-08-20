import { useState } from "react";
import Modal from "../Modal";
import { useToast } from "../../context/ToastContext";
import { upsertCanonicalTaxSlab } from "../../service/superAdminService";
import { inputClass, labelClass } from "./constants";

export default function SlabFormModal({ pack, slab, onClose, onSaved }) {
  const { addToast } = useToast() || {};
  const [form, setForm] = useState({
    minAmount: slab?.minAmount ?? "0", maxAmount: slab?.maxAmount ?? "",
    ratePct: slab?.ratePct ?? "", rateLabel: slab?.rateLabel || "",
    jurisdictionState: slab?.jurisdictionState || pack.jurisdictionState || "",
    sortOrder: slab?.sortOrder ?? 0,
  });
  const [saving, setSaving] = useState(false);
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  async function save() {
    if (form.minAmount === "" || form.ratePct === "" || !form.rateLabel.trim()) {
      addToast?.("Min amount, rate %, and label are required.", "error");
      return;
    }
    setSaving(true);
    try {
      await upsertCanonicalTaxSlab({
        id: slab?.id, jurisdictionPackId: pack.id, jurisdictionCountry: pack.jurisdictionCountry,
        jurisdictionState: form.jurisdictionState || null, taxRegime: pack.taxRegime || null,
        minAmount: form.minAmount, maxAmount: form.maxAmount === "" ? null : form.maxAmount,
        ratePct: form.ratePct, rateLabel: form.rateLabel, taxFormula: "", sortOrder: Number(form.sortOrder) || 0,
      });
      addToast?.("Bracket saved.", "success");
      onSaved();
    } catch (err) {
      addToast?.(err.message || "Failed to save bracket.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={slab ? "Edit Tax Bracket" : "Add Tax Bracket"} onClose={onClose} maxWidth="max-w-md">
      <div className="grid grid-cols-2 gap-3">
        <div><label className={labelClass}>Min Amount</label><input className={inputClass} value={form.minAmount} onChange={set("minAmount")} /></div>
        <div><label className={labelClass}>Max Amount (blank = and above)</label><input className={inputClass} value={form.maxAmount} onChange={set("maxAmount")} /></div>
        <div><label className={labelClass}>Rate %</label><input className={inputClass} value={form.ratePct} onChange={set("ratePct")} /></div>
        <div><label className={labelClass}>Label</label><input className={inputClass} value={form.rateLabel} onChange={set("rateLabel")} placeholder="e.g. 20% Bracket" /></div>
        <div className="col-span-2"><label className={labelClass}>State (optional)</label><input className={inputClass} value={form.jurisdictionState} onChange={set("jurisdictionState")} /></div>
        <div><label className={labelClass}>Sort Order</label><input type="number" className={inputClass} value={form.sortOrder} onChange={set("sortOrder")} /></div>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Saving…" : "Save"}</button>
      </div>
    </Modal>
  );
}
