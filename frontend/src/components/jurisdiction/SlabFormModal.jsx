import { useState } from "react";
import Modal from "../Modal";
import { useToast } from "../../context/ToastContext";
import { upsertCanonicalTaxSlab } from "../../service/superAdminService";
import { inputClass, labelClass } from "./constants";

// Rule Type stays a plain text-ish choice rather than a big schema
// change — NI_BAND is UK National Insurance's per-category-letter band
// shape (uk.py's _resolve_ni_bands reads it); PT_FLAT is India's
// Professional Tax bracket shape. Neither means anything for a country
// that doesn't read them, so the dropdown is scoped per jurisdiction
// (below) instead of always offering all four to everyone. Selecting
// NI_BAND reveals NI Category/Employer Rate % — both real TaxSlab
// columns that had no form field at all until now, so a category beyond
// A could never be entered.
const RULE_TYPE_OPTIONS_BY_COUNTRY = {
  UK: ["MARGINAL_RATE", "NI_BAND", "FORMULA"],
  IN: ["MARGINAL_RATE", "PT_FLAT", "FORMULA"],
};
const DEFAULT_RULE_TYPE_OPTIONS = ["MARGINAL_RATE", "FORMULA"];
const NI_CATEGORIES = ["A", "B", "C", "D", "E", "F", "H", "I", "J", "K", "L", "M", "N", "S", "V", "Z"];
// US Form W-4 filing status — a bracket row tagged with one of these wins
// over an untagged (filing_status IS NULL) row for a matching employee;
// leaving it blank keeps today's exact behavior (one table for everyone).
// See engine/countries/shared.py:_calculate_annual_tax and
// TaxSlab.filing_status. Only surfaced for US packs — every other
// jurisdiction has no filing-status concept.
const US_FILING_STATUSES = ["SINGLE", "MFJ", "MFS", "HOH"];

export default function SlabFormModal({ pack, slab, onClose, onSaved }) {
  const { addToast } = useToast() || {};
  const [form, setForm] = useState({
    minAmount: slab?.minAmount ?? "0", maxAmount: slab?.maxAmount ?? "",
    ratePct: slab?.ratePct ?? "", rateLabel: slab?.rateLabel || "",
    jurisdictionState: slab?.jurisdictionState || pack.jurisdictionState || "",
    ruleType: slab?.ruleType || "MARGINAL_RATE",
    niCategory: slab?.niCategory || "", employerRatePct: slab?.employerRatePct ?? "",
    filingStatus: slab?.filingStatus || "",
    sortOrder: slab?.sortOrder ?? 0, reason: "",
  });
  const [saving, setSaving] = useState(false);
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));
  const isNiBand = form.ruleType === "NI_BAND";
  const isUS = pack.jurisdictionCountry === "US";
  // Always includes whatever this row is already set to, even if it's
  // outside the country's normal set — editing an existing row must
  // never silently change its rule type just because the dropdown
  // narrowed under it.
  const ruleTypeOptions = Array.from(new Set([
    ...(RULE_TYPE_OPTIONS_BY_COUNTRY[pack.jurisdictionCountry] || DEFAULT_RULE_TYPE_OPTIONS),
    form.ruleType,
  ]));

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
        filingStatus: isUS && form.filingStatus ? form.filingStatus : null,
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
    <Modal title={slab ? "Edit Tax Bracket" : "Add Tax Bracket"} onClose={onClose} maxWidth="max-w-2xl">
      <div className="space-y-5">
        <FormSection title="General">
          <div className="grid grid-cols-3 gap-3">
            <div><label className={labelClass}>Label</label><input className={inputClass} value={form.rateLabel} onChange={set("rateLabel")} placeholder="e.g. 20% Bracket" /></div>
            <div><label className={labelClass}>Rule Type</label><select className={inputClass} value={form.ruleType} onChange={set("ruleType")}>{ruleTypeOptions.map((r) => <option key={r} value={r}>{r}</option>)}</select></div>
            <div><label className={labelClass}>State (optional)</label><input className={inputClass} value={form.jurisdictionState} onChange={set("jurisdictionState")} /></div>
          </div>
        </FormSection>

        <FormSection title="Bracket">
          <div className="grid grid-cols-3 gap-3">
            <div><label className={labelClass}>Min Amount</label><input className={inputClass} value={form.minAmount} onChange={set("minAmount")} /></div>
            <div><label className={labelClass}>Max Amount (blank = and above)</label><input className={inputClass} value={form.maxAmount} onChange={set("maxAmount")} /></div>
            <div><label className={labelClass}>Rate % {isNiBand ? "(Employee)" : ""}</label><input className={inputClass} value={form.ratePct} onChange={set("ratePct")} /></div>
          </div>
        </FormSection>

        {(isUS || isNiBand) && (
          <FormSection title="Applicability">
            <div className="grid grid-cols-3 gap-3">
              {isUS && (
                <div>
                  <label className={labelClass}>Filing Status (optional — leave blank to apply to every filing status)</label>
                  <select className={inputClass} value={form.filingStatus} onChange={set("filingStatus")}>
                    <option value="">Any filing status</option>
                    {US_FILING_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
              )}
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
            </div>
          </FormSection>
        )}

        <FormSection title="Administration">
          <div className="grid grid-cols-3 gap-3">
            <div><label className={labelClass}>Sort Order</label><input type="number" className={inputClass} value={form.sortOrder} onChange={set("sortOrder")} /></div>
            <div className="col-span-2"><label className={labelClass}>Reason for change (optional)</label><input className={inputClass} value={form.reason} onChange={set("reason")} placeholder="e.g. ZP-TAX-UK-2026-27-001 section 9.1" /></div>
          </div>
        </FormSection>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Saving…" : "Save"}</button>
      </div>
    </Modal>
  );
}

// Pure presentational grouping — no field/state/payload changes. Shared by
// every country's Add/Edit Tax Slab modal (SlabFormModal is not US-only);
// groups the same fields into labeled fieldsets instead of one flat grid,
// per the USA compliance UI/UX refactor.
function FormSection({ title, children }) {
  return (
    <div>
      <p className="mb-2 text-[11px] font-bold uppercase tracking-wider text-foreground-muted">{title}</p>
      {children}
    </div>
  );
}
