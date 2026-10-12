import { useState } from "react";
import Modal from "../Modal";
import { useToast } from "../../context/ToastContext";
import { upsertCanonicalContributionRate } from "../../service/superAdminService";
import { inputClass, labelClass } from "./constants";

// See the matching note in SlabFormModal.jsx — same US-only, optional,
// blank-means-"applies to every filing status" convention.
const US_FILING_STATUSES = ["SINGLE", "MFJ", "MFS", "HOH"];

export default function RateFormModal({ pack, rate, onClose, onSaved }) {
  const { addToast } = useToast() || {};
  const [form, setForm] = useState({
    componentKey: rate?.componentKey || "", label: rate?.label || "",
    jurisdictionState: rate?.jurisdictionState || pack.jurisdictionState || "",
    employeeSharePct: rate?.employeeRatePct ?? "", employerSharePct: rate?.employerRatePct ?? "",
    flatAmount: rate?.flatAmount ?? "", filingStatus: rate?.filingStatus || "",
    sortOrder: rate?.sortOrder ?? 0, reason: "",
  });
  const [saving, setSaving] = useState(false);
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));
  const isUS = pack.jurisdictionCountry === "US";

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
        filingStatus: isUS && form.filingStatus ? form.filingStatus : null,
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
    <Modal title={rate ? "Edit Contribution Rate" : "Add Contribution Rate"} onClose={onClose} maxWidth="max-w-2xl">
      <div className="space-y-5">
        <FormSection title="General">
          <div className="grid grid-cols-3 gap-3">
            <div><label className={labelClass}>Component Key</label><input className={inputClass} value={form.componentKey} onChange={set("componentKey")} placeholder="e.g. pf" /></div>
            <div><label className={labelClass}>Label</label><input className={inputClass} value={form.label} onChange={set("label")} placeholder="e.g. Provident Fund" /></div>
            <div><label className={labelClass}>State (optional — overrides country-level)</label><input className={inputClass} value={form.jurisdictionState} onChange={set("jurisdictionState")} /></div>
          </div>
        </FormSection>

        <FormSection title="Rate Configuration">
          <div className="grid grid-cols-3 gap-3">
            <div><label className={labelClass}>Employee Rate %</label><input className={inputClass} value={form.employeeSharePct} onChange={set("employeeSharePct")} placeholder="12.00" /></div>
            <div><label className={labelClass}>Employer Rate %</label><input className={inputClass} value={form.employerSharePct} onChange={set("employerSharePct")} placeholder="12.00" /></div>
            <div><label className={labelClass}>Flat Amount</label><input className={inputClass} value={form.flatAmount} onChange={set("flatAmount")} placeholder="e.g. 200" /></div>
          </div>
        </FormSection>

        {isUS && (
          <FormSection title="Applicability">
            <div className="grid grid-cols-3 gap-3">
              <div><label className={labelClass}>Filing Status (optional — leave blank to apply to every filing status)</label>
                <select className={inputClass} value={form.filingStatus} onChange={set("filingStatus")}>
                  <option value="">Any filing status</option>
                  {US_FILING_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
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

// Pure presentational grouping — no field/state/payload changes. Used by
// every country's Add/Edit Contribution Rate modal (RateFormModal is
// shared, not US-only); groups the same fields into labeled fieldsets
// instead of one flat grid, per the USA compliance UI/UX refactor.
function FormSection({ title, children }) {
  return (
    <div>
      <p className="mb-2 text-[11px] font-bold uppercase tracking-wider text-foreground-muted">{title}</p>
      {children}
    </div>
  );
}
