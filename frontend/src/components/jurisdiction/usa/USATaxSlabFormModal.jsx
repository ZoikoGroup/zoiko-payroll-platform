import { useState } from "react";
import { ChevronDown } from "lucide-react";
import Modal from "../../Modal";
import { useToast } from "../../../context/ToastContext";
import { upsertCanonicalTaxSlab } from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";
import { US_FILING_STATUSES } from "./usaComponentConfig";

// USA-only Add/Edit Tax Bracket form — a simplified subset of the generic
// SlabFormModal (which every other country keeps using untouched). Drops
// Rule Type/NI Category/Employer Rate % entirely since those are UK
// National Insurance concepts never relevant to a US MARGINAL_RATE bracket
// — a US bracket is always General + Calculation Range + Filing Status.
// Sends the exact same payload shape upsertCanonicalTaxSlab already
// expects, with ruleType/niCategory/employerRatePct/taxFormula hardcoded to
// the same values SlabFormModal already sends for a non-NI-band US row.
export default function USATaxSlabFormModal({ pack, slab, onClose, onSaved }) {
  const { addToast } = useToast() || {};
  const [form, setForm] = useState({
    minAmount: slab?.minAmount ?? "0", maxAmount: slab?.maxAmount ?? "",
    ratePct: slab?.ratePct ?? "", rateLabel: slab?.rateLabel || "",
    jurisdictionState: slab?.jurisdictionState || pack.jurisdictionState || "",
    filingStatus: slab?.filingStatus || "",
    sortOrder: slab?.sortOrder ?? 0, reason: "",
  });
  const [advancedOpen, setAdvancedOpen] = useState(false);
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
        ratePct: form.ratePct, rateLabel: form.rateLabel, taxFormula: "", ruleType: "MARGINAL_RATE",
        niCategory: null, employerRatePct: null,
        filingStatus: form.filingStatus || null,
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
            <div className="col-span-2"><label className={labelClass}>Label</label><input className={inputClass} value={form.rateLabel} onChange={set("rateLabel")} placeholder="e.g. 22% Bracket" /></div>
            <div><label className={labelClass}>State (optional)</label><input className={inputClass} value={form.jurisdictionState} onChange={set("jurisdictionState")} /></div>
          </div>
        </FormSection>

        <FormSection title="Calculation Range">
          <div className="grid grid-cols-3 gap-3">
            <div><label className={labelClass}>From Amount</label><input className={inputClass} value={form.minAmount} onChange={set("minAmount")} /></div>
            <div><label className={labelClass}>To Amount (blank = and above)</label><input className={inputClass} value={form.maxAmount} onChange={set("maxAmount")} /></div>
            <div><label className={labelClass}>Tax Rate %</label><input className={inputClass} value={form.ratePct} onChange={set("ratePct")} /></div>
          </div>
        </FormSection>

        <FormSection title="Applicability">
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className={labelClass}>Filing Status (optional — leave blank to apply to every filing status)</label>
              <select className={inputClass} value={form.filingStatus} onChange={set("filingStatus")}>
                <option value="">Any filing status</option>
                {US_FILING_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
          </div>
        </FormSection>

        <div>
          <button onClick={() => setAdvancedOpen((o) => !o)} className="flex items-center gap-1 text-[11px] font-bold uppercase tracking-wider text-foreground-muted">
            <ChevronDown size={13} className={`transition-transform ${advancedOpen ? "" : "-rotate-90"}`} /> Advanced Settings
          </button>
          {advancedOpen && (
            <div className="mt-2 grid grid-cols-3 gap-3">
              <div><label className={labelClass}>Sort Order</label><input type="number" className={inputClass} value={form.sortOrder} onChange={set("sortOrder")} /></div>
              <div className="col-span-2"><label className={labelClass}>Reason for change (optional)</label><input className={inputClass} value={form.reason} onChange={set("reason")} placeholder="e.g. ZP-TAX-UK-2026-27-001 section 9.1" /></div>
            </div>
          )}
        </div>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Saving…" : "Save"}</button>
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
