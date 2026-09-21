import { useState } from "react";
import Modal from "../../Modal";
import { useToast } from "../../../context/ToastContext";
import { upsertCanonicalTaxSlab } from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";

// Add/Edit modal for one Trinidad and Tobago NIS earnings class
// (rule_type="TT_NIS_CLASS") — the generic SlabFormModal has no field for
// a flat weekly EMPLOYER dollar amount at all, so a dedicated modal is
// the minimal way to enter a class's earnings band plus the two real
// weekly dollar figures — see engine/countries/shared.py's own docstring
// for exactly why flatAmount/adjustmentAmount are reused this way for
// this rule_type. Deliberately NOT employerRatePct: that column is
// Numeric(6,4) (a real percentage field, max ~99.9999) and overflows on
// a $339.00 Class-XVI employer figure — found live against production
// Postgres 2026-09-21 (SQLite-backed tests never enforce column
// precision, so this was invisible until a real-DB run). Mirrors
// australia/AUCoefficientRowFormModal.jsx's exact shape, simplified (TT
// has no family/scale grouping — one flat class list).
export default function TTNisClassFormModal({ pack, slab, onClose, onSaved }) {
  const { addToast } = useToast() || {};
  const [form, setForm] = useState({
    classLabel: slab?.rateLabel || "",
    bandVariant: slab?.filingStatus || "MONTHLY",
    minAmount: slab?.minAmount ?? "0", maxAmount: slab?.maxAmount ?? "",
    employeeWeekly: slab?.flatAmount ?? "", employerWeekly: slab?.adjustmentAmount ?? "",
    sortOrder: slab?.sortOrder ?? 100, reason: "",
  });
  const [saving, setSaving] = useState(false);
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  async function save() {
    if (!form.classLabel || form.minAmount === "" || form.employeeWeekly === "") {
      addToast?.("Class label, monthly earnings from, and the weekly employee amount are required.", "error");
      return;
    }
    setSaving(true);
    try {
      await upsertCanonicalTaxSlab({
        id: slab?.id, jurisdictionPackId: pack.id, jurisdictionCountry: pack.jurisdictionCountry,
        jurisdictionState: pack.jurisdictionState || null, taxRegime: pack.taxRegime || null,
        ruleType: "TT_NIS_CLASS", filingStatus: form.bandVariant,
        minAmount: form.minAmount, maxAmount: form.maxAmount === "" ? null : form.maxAmount,
        ratePct: 0, // unread for TT_NIS_CLASS rows — the real amounts are flatAmount/adjustmentAmount below
        flatAmount: form.employeeWeekly, adjustmentAmount: form.employerWeekly === "" ? null : form.employerWeekly,
        rateLabel: form.classLabel, taxFormula: "Fixed weekly NIS contribution",
        sortOrder: Number(form.sortOrder) || 0, reason: form.reason || null,
      });
      addToast?.("NIS class saved.", "success");
      onSaved();
    } catch (err) {
      addToast?.(err.message || "Failed to save NIS class.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={slab ? "Edit NIS Earnings Class" : "Add NIS Earnings Class"} onClose={onClose} maxWidth="max-w-xl">
      <div className="space-y-5">
        <div className="grid grid-cols-2 gap-3">
          <div><label className={labelClass}>Class label</label><input className={inputClass} value={form.classLabel} onChange={set("classLabel")} placeholder="e.g. Class XII" /></div>
          <div>
            <label className={labelClass}>Applies to</label>
            <select className={inputClass} value={form.bandVariant} onChange={set("bandVariant")}>
              <option value="MONTHLY">Monthly-paid employees</option>
              <option value="WEEKLY">Weekly-paid employees</option>
            </select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div><label className={labelClass}>{form.bandVariant === "WEEKLY" ? "Weekly" : "Monthly"} earnings — from</label><input className={inputClass} value={form.minAmount} onChange={set("minAmount")} /></div>
          <div><label className={labelClass}>{form.bandVariant === "WEEKLY" ? "Weekly" : "Monthly"} earnings — to (blank = and above)</label><input className={inputClass} value={form.maxAmount} onChange={set("maxAmount")} /></div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div><label className={labelClass}>Weekly employee contribution</label><input className={inputClass} value={form.employeeWeekly} onChange={set("employeeWeekly")} placeholder="e.g. 122.00" /></div>
          <div><label className={labelClass}>Weekly employer contribution</label><input className={inputClass} value={form.employerWeekly} onChange={set("employerWeekly")} placeholder="e.g. 244.00" /></div>
        </div>
        <p className="text-xs text-foreground-muted">
          Fixed dollar amounts per contribution week — not a percentage (NIBTT's 16-class table, ZP-TT-ENG-001 §5).
        </p>

        <div className="grid grid-cols-3 gap-3">
          <div><label className={labelClass}>Sort Order</label><input type="number" className={inputClass} value={form.sortOrder} onChange={set("sortOrder")} /></div>
          <div className="col-span-2"><label className={labelClass}>Reason for change (optional)</label><input className={inputClass} value={form.reason} onChange={set("reason")} placeholder="e.g. NIBTT 2026 rate table" /></div>
        </div>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Saving…" : "Save"}</button>
      </div>
    </Modal>
  );
}
