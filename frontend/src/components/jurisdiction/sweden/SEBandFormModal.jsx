import { useState } from "react";
import Modal from "../../Modal";
import { useToast } from "../../../context/ToastContext";
import { upsertCanonicalTaxSlab } from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";
import { SE_ONE_TIME_PAYMENT_RULE, SE_TAX_TABLE_RULE, SE_TAX_TABLES } from "./seComponentConfig";

// Add/Edit one Skatteverket authority band. The generic SlabFormModal has no
// table / column / basis fields and would clear flatAmount, so Sweden has its
// own form writing through the SAME canonical upsertCanonicalTaxSlab endpoint
// (editable-pack guard, approval invalidation, audit trail server-side).
//
// Values are entered exactly as Skatteverket publishes them — never
// converted:
//   * tax table (monthly): monthly pay band + either the monthly withholding
//     AMOUNT or, for the top incomes, the published PERCENTAGE;
//   * one-time payment: expected ANNUAL income band + the published PERCENTAGE.
export default function SEBandFormModal({ pack, kind, slab, initial = {}, onClose, onSaved }) {
  const { addToast } = useToast() || {};
  const isOneTime = kind === SE_ONE_TIME_PAYMENT_RULE;
  const seed = { ...initial, ...(slab || {}) };
  const [form, setForm] = useState({
    table: seed.taxTableNumber || "",
    column: seed.taxColumn || "1",
    basis: isOneTime ? "PERCENT" : (seed.assessmentBasis || "AMOUNT"),
    minAmount: seed.minAmount ?? "",
    maxAmount: seed.maxAmount ?? "",
    flatAmount: seed.flatAmount ?? "",
    ratePct: seed.ratePct && Number(seed.ratePct) !== 0 ? seed.ratePct : (isOneTime ? seed.ratePct ?? "" : ""),
    reason: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const set = (field) => (e) => { setForm((f) => ({ ...f, [field]: e.target.value })); setError(null); };

  async function save() {
    const problems = [];
    if (!isOneTime && !form.table) problems.push("Choose the tax table (29–42).");
    if (!form.column.trim()) problems.push("Enter the tax column.");
    if (form.minAmount === "") problems.push("Enter the band's lower bound.");
    if (form.basis === "AMOUNT" && form.flatAmount === "") problems.push("Enter the published monthly withholding amount.");
    if (form.basis === "PERCENT" && form.ratePct === "") problems.push("Enter the published percentage.");
    if (!form.reason.trim()) problems.push("A reason citing the Skatteverket source is required.");
    if (problems.length) { setError(problems.join(" ")); addToast?.(problems[0], "error"); return; }
    const label = isOneTime
      ? `SE-${pack.taxYear || ""}-OTP-C${form.column}-${form.minAmount}`
      : `SE-${pack.taxYear || ""}-T${form.table}-C${form.column}-${form.minAmount}`;
    setSaving(true);
    try {
      await upsertCanonicalTaxSlab({
        id: slab?.id, jurisdictionPackId: pack.id, jurisdictionCountry: "SE", jurisdictionState: null,
        ruleType: kind, taxTableNumber: isOneTime ? null : form.table, taxColumn: form.column.trim(),
        assessmentBasis: form.basis,
        minAmount: form.minAmount, maxAmount: form.maxAmount === "" ? null : form.maxAmount,
        ratePct: form.basis === "PERCENT" ? form.ratePct : "0",
        flatAmount: form.basis === "AMOUNT" ? form.flatAmount : null,
        rateLabel: label.slice(0, 150),
        taxFormula: (isOneTime ? "One-time payment — annual income band, published %" :
          form.basis === "AMOUNT" ? "Monthly table — published withholding amount" : "Monthly table — published %"),
        sortOrder: slab?.sortOrder ?? 0, reason: form.reason,
      });
      addToast?.("Skatteverket band saved.", "success");
      onSaved();
    } catch (err) {
      addToast?.(err.message || "Failed to save band.", "error");
    } finally {
      setSaving(false);
    }
  }

  const unit = isOneTime ? "annual income, SEK" : "monthly pay, SEK";
  return (
    <Modal title={`${slab ? "Edit" : "Add"} ${isOneTime ? "one-time-payment band" : "tax-table band"}`} onClose={onClose} maxWidth="max-w-2xl">
      <div className="space-y-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {!isOneTime && (
            <div>
              <label className={labelClass} htmlFor="se-band-table">Tax table</label>
              <select id="se-band-table" className={inputClass} value={form.table} onChange={set("table")}>
                <option value="">Select…</option>
                {SE_TAX_TABLES.map((t) => <option key={t} value={t}>Table {t}</option>)}
              </select>
            </div>
          )}
          <div>
            <label className={labelClass} htmlFor="se-band-column">Column</label>
            <input id="se-band-column" className={inputClass} value={form.column} onChange={set("column")} />
          </div>
          {!isOneTime && (
            <div>
              <label className={labelClass} htmlFor="se-band-basis">Published as</label>
              <select id="se-band-basis" className={inputClass} value={form.basis} onChange={set("basis")}>
                <option value="AMOUNT">Withholding amount (SEK)</option>
                <option value="PERCENT">Percentage (top incomes)</option>
              </select>
            </div>
          )}
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label className={labelClass} htmlFor="se-band-min">From ({unit}, inclusive)</label>
            <input id="se-band-min" className={inputClass} inputMode="decimal" value={form.minAmount} onChange={set("minAmount")} />
          </div>
          <div>
            <label className={labelClass} htmlFor="se-band-max">Up to ({unit}, exclusive; blank = no upper limit)</label>
            <input id="se-band-max" className={inputClass} inputMode="decimal" value={form.maxAmount} onChange={set("maxAmount")} />
          </div>
        </div>
        {form.basis === "AMOUNT" ? (
          <div>
            <label className={labelClass} htmlFor="se-band-amount">Monthly withholding (SEK)</label>
            <input id="se-band-amount" className={inputClass} inputMode="decimal" value={form.flatAmount} onChange={set("flatAmount")} />
          </div>
        ) : (
          <div>
            <label className={labelClass} htmlFor="se-band-pct">Published percentage (%)</label>
            <input id="se-band-pct" className={inputClass} inputMode="decimal" value={form.ratePct} onChange={set("ratePct")} />
          </div>
        )}
        <div>
          <label className={labelClass} htmlFor="se-band-reason">Reason and Skatteverket source (recorded in the audit trail)</label>
          <textarea id="se-band-reason" rows={2} className={inputClass} value={form.reason} onChange={set("reason")}
            placeholder="e.g. Skatteverket skattetabell 2026, table 32 column 1, row 30 001–30 200" />
        </div>
        {error && <p role="alert" className="text-sm font-medium text-error">{error}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm font-semibold text-foreground-secondary hover:bg-surface-muted">Cancel</button>
          <button type="button" onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary-hover disabled:opacity-60">
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
