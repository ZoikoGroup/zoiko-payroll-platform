import { useState } from "react";
import { ChevronDown } from "lucide-react";
import Modal from "../../Modal";
import { useToast } from "../../../context/ToastContext";
import { upsertCanonicalContributionRate } from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";
import { ADD_COMPONENT_TYPES, UI_TYPES, US_FILING_STATUSES, classifyContributionRate, describeUiType } from "./usaComponentConfig";

// USA-only Add/Edit Contribution Rate form — replaces the generic
// RateFormModal (which every other country keeps using untouched) with a
// component-type-driven form that shows only the field(s) relevant to that
// component. Sends the EXACT SAME payload shape/keys to the EXACT SAME
// upsertCanonicalContributionRate API RateFormModal already uses — only the
// surrounding form UI differs, never the wire contract.
//
// Add flow: a frontend-only "Component Type" picker (never sent to the
// API) determines which fields to show. Edit flow: the type is
// auto-detected from the existing row via classifyContributionRate — no
// picker shown, matching "the user should not have to select a component
// type while editing."
const DEFAULT_RATE_FIELD = {
  [UI_TYPES.PERCENTAGE]: "employeeRatePct",
  [UI_TYPES.EMPLOYER_ASSIGNED_RATE]: "employerRatePct",
};

export default function USAComponentFormModal({ pack, rate, initial, onClose, onSaved }) {
  const { addToast } = useToast() || {};
  const editingDesc = rate ? { ...classifyContributionRate(rate) } : null;
  // `initial` (componentKey/label/uiType) comes from the business-language
  // picker (USAComponentPickerModal) selecting a known, not-yet-configured
  // catalog component — its uiType is already known, so this skips
  // straight to the relevant fields, same as Edit does. The technical-type
  // screen below only shows when neither `rate` nor `initial` supply a
  // type (the picker's "Other / Custom Component" escape hatch).
  const [chosenType, setChosenType] = useState(editingDesc?.uiType || initial?.uiType || null);
  const desc = chosenType ? describeUiType(chosenType, {}) : null;
  const rateField = editingDesc?.rateField || DEFAULT_RATE_FIELD[chosenType] || "employeeRatePct";

  const [form, setForm] = useState({
    componentKey: rate?.componentKey || initial?.componentKey || "",
    label: rate?.label || initial?.displayName || "",
    jurisdictionState: rate?.jurisdictionState || pack.jurisdictionState || "",
    employeeSharePct: rate?.employeeRatePct ?? "",
    employerSharePct: rate?.employerRatePct ?? "",
    flatAmount: rate?.flatAmount ?? "",
    filingStatus: rate?.filingStatus || "",
    sortOrder: rate?.sortOrder ?? 0,
    reason: "",
  });
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));
  const setRateValue = (e) => {
    const field = rateField === "employerRatePct" ? "employerSharePct" : "employeeSharePct";
    setForm((f) => ({ ...f, [field]: e.target.value }));
  };
  const rateValue = rateField === "employerRatePct" ? form.employerSharePct : form.employeeSharePct;

  async function save() {
    if (!form.componentKey.trim() || !form.label.trim()) {
      addToast?.("Component key and label are required.", "error");
      return;
    }
    setSaving(true);
    try {
      let employeeSharePct = null, employerSharePct = null;
      if (desc.employeeRate && desc.employerRate) {
        employeeSharePct = form.employeeSharePct === "" ? null : form.employeeSharePct;
        employerSharePct = form.employerSharePct === "" ? null : form.employerSharePct;
      } else if (desc.singleRate) {
        const val = rateValue === "" ? null : rateValue;
        if (rateField === "employerRatePct") employerSharePct = val;
        else employeeSharePct = val;
      }
      await upsertCanonicalContributionRate({
        id: rate?.id, jurisdictionPackId: pack.id, jurisdictionCountry: pack.jurisdictionCountry,
        jurisdictionState: form.jurisdictionState || null, taxRegime: pack.taxRegime || null,
        componentKey: form.componentKey, label: form.label,
        employeeSharePct, employerSharePct,
        flatAmount: desc.flatAmount ? (form.flatAmount === "" ? null : form.flatAmount) : null,
        filingStatus: desc.filingStatus && form.filingStatus ? form.filingStatus : null,
        sortOrder: Number(form.sortOrder) || 0, reason: form.reason || null,
      });
      addToast?.("Component saved.", "success");
      onSaved();
    } catch (err) {
      addToast?.(err.message || "Failed to save component.", "error");
    } finally {
      setSaving(false);
    }
  }

  if (!chosenType) {
    return (
      <Modal title="Custom Component" onClose={onClose} maxWidth="max-w-lg">
        <p className={labelClass}>What kind of value does this component need?</p>
        <div className="grid grid-cols-2 gap-2">
          {ADD_COMPONENT_TYPES.map((t) => (
            <button
              key={t.uiType}
              onClick={() => setChosenType(t.uiType)}
              className="w-full rounded-lg border border-border px-3 py-2.5 text-left text-sm font-medium text-foreground-secondary hover:border-primary hover:bg-primary/5 hover:text-primary"
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="mt-5 flex justify-end">
          <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        </div>
      </Modal>
    );
  }

  return (
    <Modal title={rate ? `Edit ${rate.label}` : initial ? `Add ${initial.displayName}` : "Add Contribution Rate"} onClose={onClose} maxWidth="max-w-2xl">
      <div className="space-y-5">
        <FormSection title="General">
          <div className="grid grid-cols-3 gap-3">
            <div><label className={labelClass}>Component Key</label><input className={inputClass} value={form.componentKey} onChange={set("componentKey")} placeholder="e.g. pf" /></div>
            <div><label className={labelClass}>Label</label><input className={inputClass} value={form.label} onChange={set("label")} placeholder="e.g. Provident Fund" /></div>
            <div><label className={labelClass}>State (optional — overrides country-level)</label><input className={inputClass} value={form.jurisdictionState} onChange={set("jurisdictionState")} /></div>
          </div>
        </FormSection>

        <FormSection title="Calculation">
          <div className="grid grid-cols-3 gap-3">
            {desc.employeeRate && desc.employerRate && (
              <>
                <div><label className={labelClass}>Employee Rate %</label><input className={inputClass} value={form.employeeSharePct} onChange={set("employeeSharePct")} placeholder="6.20" /></div>
                <div><label className={labelClass}>Employer Rate %</label><input className={inputClass} value={form.employerSharePct} onChange={set("employerSharePct")} placeholder="6.20" /></div>
              </>
            )}
            {desc.singleRate && (
              <div><label className={labelClass}>{desc.rateLabel}</label><input className={inputClass} value={rateValue} onChange={setRateValue} placeholder="0.90" /></div>
            )}
            {desc.flatAmount && (
              <div><label className={labelClass}>{desc.flatAmountLabel}</label><input className={inputClass} value={form.flatAmount} onChange={set("flatAmount")} placeholder="0.00" /></div>
            )}
          </div>
        </FormSection>

        {desc.filingStatus && (
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
        )}

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
