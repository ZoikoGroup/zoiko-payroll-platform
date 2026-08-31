import { useState } from "react";
import { ChevronDown } from "lucide-react";
import Modal from "../../Modal";
import { useToast } from "../../../context/ToastContext";
import { upsertCanonicalContributionRate } from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";
import { ADD_COMPONENT_TYPES, classifyIndiaContributionRate, describeUiType, sanitizeNumeric } from "./inComponentConfig";

// India-only Add/Edit Contribution Rate form — replaces the generic
// RateFormModal (which every other country keeps using untouched) with a
// component-driven form that shows only the field(s) relevant to that
// component. Sends the EXACT SAME payload shape/keys to the EXACT SAME
// upsertCanonicalContributionRate API RateFormModal already uses — only the
// surrounding form UI differs, never the wire contract. Direct structural
// port of usa/USAComponentFormModal.jsx.
//
// Add flow: a known catalog component (`initial`) already knows its shape,
// so this skips straight to the relevant fields. Edit flow: the type is
// auto-detected from the existing row via classifyIndiaContributionRate —
// no picker shown. The technical-type screen below only appears via the
// picker's "Other / Custom Component" escape hatch.
export default function INComponentFormModal({ pack, rate, initial, onClose, onSaved }) {
  const { addToast } = useToast() || {};
  const editingDesc = rate ? classifyIndiaContributionRate(rate) : null;
  const [chosenType, setChosenType] = useState(editingDesc?.uiType || initial?.uiType || null);
  const desc = chosenType ? describeUiType(chosenType) : null;

  const [form, setForm] = useState({
    componentKey: rate?.componentKey || initial?.componentKey || "",
    label: rate?.label || initial?.displayName || "",
    jurisdictionState: rate?.jurisdictionState || pack.jurisdictionState || "",
    employeeSharePct: rate?.employeeRatePct ?? "",
    employerSharePct: rate?.employerRatePct ?? "",
    flatAmount: rate?.flatAmount ?? "",
    sortOrder: rate?.sortOrder ?? 0,
    reason: "",
  });
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

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
        // sanitizeNumeric strips commas — these inputs are plain and unmasked
        // while the display side (INComponentCard) shows the same values
        // with comma grouping, so an admin re-typing what they see (e.g.
        // "21,000" for the ESI Wage Ceiling) must still parse and save.
        employeeSharePct: desc.employeeRate ? (form.employeeSharePct === "" ? null : sanitizeNumeric(form.employeeSharePct)) : null,
        employerSharePct: desc.employeeRate ? (form.employerSharePct === "" ? null : sanitizeNumeric(form.employerSharePct)) : null,
        flatAmount: desc.flatAmount ? (form.flatAmount === "" ? null : sanitizeNumeric(form.flatAmount)) : null,
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
                <div><label className={labelClass}>Employee Contribution Rate %</label><input className={inputClass} value={form.employeeSharePct} onChange={set("employeeSharePct")} placeholder="12.00" /></div>
                <div><label className={labelClass}>Employer Contribution Rate %</label><input className={inputClass} value={form.employerSharePct} onChange={set("employerSharePct")} placeholder="12.00" /></div>
              </>
            )}
            {desc.flatAmount && (
              <div><label className={labelClass}>{desc.flatAmountLabel}</label><input className={inputClass} value={form.flatAmount} onChange={set("flatAmount")} placeholder="0.00" /></div>
            )}
          </div>
        </FormSection>

        <div>
          <button onClick={() => setAdvancedOpen((o) => !o)} className="flex items-center gap-1 text-[11px] font-bold uppercase tracking-wider text-foreground-muted">
            <ChevronDown size={13} className={`transition-transform ${advancedOpen ? "" : "-rotate-90"}`} /> Advanced Settings
          </button>
          {advancedOpen && (
            <div className="mt-2 grid grid-cols-3 gap-3">
              <div><label className={labelClass}>Sort Order</label><input type="number" className={inputClass} value={form.sortOrder} onChange={set("sortOrder")} /></div>
              <div className="col-span-2"><label className={labelClass}>Reason for change (optional)</label><input className={inputClass} value={form.reason} onChange={set("reason")} placeholder="e.g. EPFO notification" /></div>
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
