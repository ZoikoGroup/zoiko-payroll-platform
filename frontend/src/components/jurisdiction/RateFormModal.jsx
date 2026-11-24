import { useState } from "react";
import Modal from "../Modal";
import { useToast } from "../../context/ToastContext";
import { upsertCanonicalContributionRate } from "../../service/superAdminService";
import { inputClass, isFractionRateCountry, labelClass, percentToRate, ratePercentWarnings, rateToPercent } from "./constants";

// See the matching note in SlabFormModal.jsx — same US-only, optional,
// blank-means-"applies to every filing status" convention.
const US_FILING_STATUSES = ["SINGLE", "MFJ", "MFS", "HOH"];

// Rate fields always take a PERCENTAGE (6.2 = 6.2 %). For countries whose
// engine stores a fraction (constants.FRACTION_RATE_COUNTRIES) the stored
// value is shown x100 and saved /100, so what is stored never changes unit.
function RateField({ label, value, onChange, warnings }) {
  return (
    <div>
      <label className={labelClass}>{label}</label>
      <input className={inputClass} value={value} onChange={onChange} placeholder="12.00" inputMode="decimal"
        aria-invalid={warnings.length > 0 || undefined} />
      {warnings.map((w) => <p key={w} role="alert" className="mt-1 text-[11px] text-warning">{w}</p>)}
    </div>
  );
}

export default function RateFormModal({ pack, rate, onClose, onSaved }) {
  const { addToast } = useToast() || {};
  const country = pack.jurisdictionCountry;
  const [form, setForm] = useState({
    componentKey: rate?.componentKey || "", label: rate?.label || "",
    jurisdictionState: rate?.jurisdictionState || pack.jurisdictionState || "",
    employeeSharePct: rateToPercent(rate?.employeeRatePct, country),
    employerSharePct: rateToPercent(rate?.employerRatePct, country),
    flatAmount: rate?.flatAmount ?? "", filingStatus: rate?.filingStatus || "",
    sortOrder: rate?.sortOrder ?? 0, reason: "",
  });
  const [saving, setSaving] = useState(false);
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));
  const isUS = pack.jurisdictionCountry === "US";
  const employeeWarnings = ratePercentWarnings(form.employeeSharePct, country);
  const employerWarnings = ratePercentWarnings(form.employerSharePct, country);

  async function save() {
    if (!form.componentKey.trim() || !form.label.trim()) {
      addToast?.("Component key and label are required.", "error");
      return;
    }
    if ((employeeWarnings.length || employerWarnings.length)
      && !window.confirm(["Check the rates before saving:", ...employeeWarnings, ...employerWarnings, "", "Save anyway?"].join("\n"))) {
      return;
    }
    const employeeRate = percentToRate(form.employeeSharePct, country);
    const employerRate = percentToRate(form.employerSharePct, country);
    setSaving(true);
    try {
      await upsertCanonicalContributionRate({
        id: rate?.id, jurisdictionPackId: pack.id, jurisdictionCountry: pack.jurisdictionCountry,
        jurisdictionState: form.jurisdictionState || null, taxRegime: pack.taxRegime || null,
        componentKey: form.componentKey, label: form.label,
        employeeSharePct: employeeRate === "" ? null : employeeRate,
        employerSharePct: employerRate === "" ? null : employerRate,
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
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div><label className={labelClass}>Component Key</label><input className={inputClass} value={form.componentKey} onChange={set("componentKey")} placeholder="e.g. pf" /></div>
            <div><label className={labelClass}>Label</label><input className={inputClass} value={form.label} onChange={set("label")} placeholder="e.g. Provident Fund" /></div>
            <div><label className={labelClass}>State (optional — overrides country-level)</label><input className={inputClass} value={form.jurisdictionState} onChange={set("jurisdictionState")} /></div>
          </div>
        </FormSection>

        <FormSection title="Rate Configuration">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <RateField label="Employee Rate %" value={form.employeeSharePct} onChange={set("employeeSharePct")} warnings={employeeWarnings} />
            <RateField label="Employer Rate %" value={form.employerSharePct} onChange={set("employerSharePct")} warnings={employerWarnings} />
            <div><label className={labelClass}>Flat Amount</label><input className={inputClass} value={form.flatAmount} onChange={set("flatAmount")} placeholder="e.g. 200" /></div>
          </div>
          {isFractionRateCountry(country) && (
            <p className="mt-2 text-[11px] text-foreground-muted" data-testid="rate-unit-note">
              Enter rates as percentages (6.2 for 6.2 %). {country} stores them as fractions (0.062); the conversion is automatic.
            </p>
          )}
        </FormSection>

        {isUS && (
          <FormSection title="Applicability">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
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
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
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
