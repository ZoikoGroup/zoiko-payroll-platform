import { useState } from "react";
import Modal from "../../Modal";
import { useToast } from "../../../context/ToastContext";
import { upsertCanonicalTaxSlab } from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";

// Shared Add/Edit modal for BOTH ATO Schedule 1 (AU_PAYG_COEFFICIENT) and
// Schedule 8 (AU_STSL_COEFFICIENT) coefficient bands — the generic
// SlabFormModal has no field for `flat_amount`/a non-US `filing_status`
// at all (see its own file: those fields only ever surface for NI_BAND/
// US rows), so a dedicated modal is the minimal way to enter Scale/
// declaration-family + the weekly-x band + the two real coefficients
// (`a` in rate_pct, `b` in flat_amount) — see models.TaxSlab's own
// rule_type docstring for exactly why these columns are reused this way.
export default function AUCoefficientRowFormModal({ pack, ruleType, familyOptions, familyLabel, slab, onClose, onSaved }) {
  const { addToast } = useToast() || {};
  const [form, setForm] = useState({
    family: slab?.filingStatus || familyOptions[0]?.value || "",
    minAmount: slab?.minAmount ?? "0", maxAmount: slab?.maxAmount ?? "",
    a: slab?.ratePct ?? "", b: slab?.flatAmount ?? "",
    sortOrder: slab?.sortOrder ?? 0, reason: "",
  });
  const [saving, setSaving] = useState(false);
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  async function save() {
    if (!form.family || form.minAmount === "" || form.a === "") {
      addToast?.("Family, weekly-x from, and coefficient a are required.", "error");
      return;
    }
    setSaving(true);
    try {
      await upsertCanonicalTaxSlab({
        id: slab?.id, jurisdictionPackId: pack.id, jurisdictionCountry: pack.jurisdictionCountry,
        jurisdictionState: pack.jurisdictionState || null, taxRegime: pack.taxRegime || null,
        ruleType, filingStatus: form.family,
        minAmount: form.minAmount, maxAmount: form.maxAmount === "" ? null : form.maxAmount,
        ratePct: form.a, flatAmount: form.b === "" ? null : form.b,
        rateLabel: `${form.family} coefficient band`, taxFormula: "y = a·x − b",
        sortOrder: Number(form.sortOrder) || 0, reason: form.reason || null,
      });
      addToast?.("Coefficient band saved.", "success");
      onSaved();
    } catch (err) {
      addToast?.(err.message || "Failed to save coefficient band.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={slab ? "Edit Coefficient Band" : "Add Coefficient Band"} onClose={onClose} maxWidth="max-w-xl">
      <div className="space-y-5">
        <div>
          <label className={labelClass}>{familyLabel}</label>
          <select className={inputClass} value={form.family} onChange={set("family")}>
            {familyOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div><label className={labelClass}>Weekly-equivalent x — from</label><input className={inputClass} value={form.minAmount} onChange={set("minAmount")} /></div>
          <div><label className={labelClass}>Weekly-equivalent x — to (blank = and above)</label><input className={inputClass} value={form.maxAmount} onChange={set("maxAmount")} /></div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div><label className={labelClass}>Coefficient a</label><input className={inputClass} value={form.a} onChange={set("a")} placeholder="e.g. 0.3227" /></div>
          <div><label className={labelClass}>Coefficient b</label><input className={inputClass} value={form.b} onChange={set("b")} placeholder="e.g. 74.1674" /></div>
        </div>
        <p className="text-xs text-foreground-muted">Withholding for this band: y = a·x − b, rounded to the nearest dollar.</p>

        <div className="grid grid-cols-3 gap-3">
          <div><label className={labelClass}>Sort Order</label><input type="number" className={inputClass} value={form.sortOrder} onChange={set("sortOrder")} /></div>
          <div className="col-span-2"><label className={labelClass}>Reason for change (optional)</label><input className={inputClass} value={form.reason} onChange={set("reason")} placeholder="e.g. ZP-TAX-AU-2026-27-001 §6" /></div>
        </div>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Saving…" : "Save"}</button>
      </div>
    </Modal>
  );
}
