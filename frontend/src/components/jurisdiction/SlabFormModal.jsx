import { useState } from "react";
import Modal from "../Modal";
import { useToast } from "../../context/ToastContext";
import { upsertCanonicalTaxSlab } from "../../service/superAdminService";
import { inputClass, labelClass } from "./constants";

// Rule Type stays a plain text-ish choice rather than a big schema
// change — NI_BAND is UK National Insurance's per-category-letter band
// shape (uk.py's _resolve_ni_bands reads it); every other country keeps
// using the default MARGINAL_RATE. Selecting it reveals NI Category/
// Employer Rate % — both real TaxSlab columns that had no form field at
// all until now, so a category beyond A could never be entered.
const RULE_TYPE_OPTIONS = ["MARGINAL_RATE", "NI_BAND", "PT_FLAT", "FORMULA"];
const NI_CATEGORIES = ["A", "B", "C", "D", "E", "F", "H", "I", "J", "K", "L", "M", "N", "S", "V", "Z"];

export default function SlabFormModal({ pack, slab, onClose, onSaved }) {
  const { addToast } = useToast() || {};
  const [form, setForm] = useState({
    minAmount: slab?.minAmount ?? "0", maxAmount: slab?.maxAmount ?? "",
    ratePct: slab?.ratePct ?? "", rateLabel: slab?.rateLabel || "",
    jurisdictionState: slab?.jurisdictionState || pack.jurisdictionState || "",
    ruleType: slab?.ruleType || "MARGINAL_RATE",
    niCategory: slab?.niCategory || "", employerRatePct: slab?.employerRatePct ?? "",
    sortOrder: slab?.sortOrder ?? 0, reason: "",
  });
  const [saving, setSaving] = useState(false);
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));
  const isNiBand = form.ruleType === "NI_BAND";

  async function save() {
    if (form.minAmount === "" || form.ratePct === "" || !form.rateLabel.trim()) {
      addToast?.("Min amount, rate %, and label are required.", "error");
      return;
    }
    if (isNiBand && !form.niCategory) {
      addToast?.("NI Category is required for an NI Band row.", "error");
      return;
    }
    setSaving(true);
    try {
      await upsertCanonicalTaxSlab({
        id: slab?.id, jurisdictionPackId: pack.id, jurisdictionCountry: pack.jurisdictionCountry,
        jurisdictionState: form.jurisdictionState || null, taxRegime: pack.taxRegime || null,
        minAmount: form.minAmount, maxAmount: form.maxAmount === "" ? null : form.maxAmount,
        ratePct: form.ratePct, rateLabel: form.rateLabel, taxFormula: "", ruleType: form.ruleType,
        niCategory: isNiBand ? form.niCategory : null,
        employerRatePct: isNiBand && form.employerRatePct !== "" ? form.employerRatePct : null,
        sortOrder: Number(form.sortOrder) || 0, reason: form.reason || null,
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
        <div><label className={labelClass}>Rate % {isNiBand ? "(Employee)" : ""}</label><input className={inputClass} value={form.ratePct} onChange={set("ratePct")} /></div>
        <div><label className={labelClass}>Label</label><input className={inputClass} value={form.rateLabel} onChange={set("rateLabel")} placeholder="e.g. 20% Bracket" /></div>
        <div><label className={labelClass}>Rule Type</label><select className={inputClass} value={form.ruleType} onChange={set("ruleType")}>{RULE_TYPE_OPTIONS.map((r) => <option key={r} value={r}>{r}</option>)}</select></div>
        <div><label className={labelClass}>State (optional)</label><input className={inputClass} value={form.jurisdictionState} onChange={set("jurisdictionState")} /></div>
        {isNiBand && (
          <>
            <div>
              <label className={labelClass}>NI Category</label>
              <select className={inputClass} value={form.niCategory} onChange={set("niCategory")}>
                <option value="">Select…</option>
                {NI_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <div><label className={labelClass}>Employer Rate %</label><input className={inputClass} value={form.employerRatePct} onChange={set("employerRatePct")} placeholder="e.g. 15" /></div>
          </>
        )}
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
