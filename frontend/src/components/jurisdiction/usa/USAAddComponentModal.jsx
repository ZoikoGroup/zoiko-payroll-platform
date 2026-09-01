import { useMemo, useState } from "react";
import { Search, ChevronRight, CornerDownRight, ChevronLeft, Check } from "lucide-react";
import Drawer from "../../Drawer";
import { useToast } from "../../../context/ToastContext";
import { upsertCanonicalContributionRate } from "../../../service/superAdminService";
import { getStatesForCountryCode } from "../../../utils/registrationRegions";
import { inputClass, labelClass } from "../constants";
import {
  PAYROLL_COMPONENT_CATALOG, PAYROLL_COMPONENT_CATEGORIES,
  UI_TYPES, US_FILING_STATUSES, classifyContributionRate, describeUiType,
} from "./usaComponentConfig";
import { STATE_COMPONENT_CATALOG, STATE_COMPONENT_CATEGORIES } from "./stateComponentCatalog";

const US_STATE_OPTIONS = getStatesForCountryCode("US");

// USA-only step-based "+ Add Component" drawer (Select → Configure →
// Review & Save). Reuses the existing business-component catalog and the
// same field-classification (describeUiType/classifyContributionRate) and
// the exact same upsertCanonicalContributionRate payload as the existing
// form — the admin picks a PAYROLL component by name, never a technical
// type, and only the fields that component actually needs are shown. No new
// API call, no payload shape change.
//
// Step 1 (Select): the same catalog/categories/Configured badge logic as
// USAComponentPickerModal. Any unserializable pre-existing rows simply route
// Add, and already-configured rows route to Edit via onEditExisting.
export default function USAAddComponentModal({ pack, rates, onClose, onEditExisting, onSaved, onNavigateIncomeTax }) {
  const { addToast } = useToast() || {};
  const [step, setStep] = useState(1);
  const [search, setSearch] = useState("");
  const [entry, setEntry] = useState(null); // chosen catalog entry (componentKey via classify)
  const [form, setForm] = useState({});
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  // Level-exclusive, not merged: a State/District pack (jurisdictionState
  // set) only ever offers the state catalog; a Federal pack (no state) only
  // ever offers the federal one. Previously this spread the federal catalog
  // INTO every state pack's picker too, which is why Social Security/
  // Medicare/FUTA incorrectly appeared under e.g. California's "Add
  // Component" — usaComponentConfig.js (Federal-only) and
  // stateComponentCatalog.js (State-only) were already correctly scoped;
  // only this selection was wrong.
  const catalog = pack.jurisdictionState ? STATE_COMPONENT_CATALOG : PAYROLL_COMPONENT_CATALOG;
  const categories = pack.jurisdictionState ? STATE_COMPONENT_CATEGORIES : PAYROLL_COMPONENT_CATEGORIES;

  const q = search.trim().toLowerCase();
  const entries = useMemo(() => {
    return catalog
      .map((e) => ({ entry: e, rows: (rates || []).filter((r) => r.componentKey === e.componentKey) }))
      .filter(({ entry }) => !q || entry.displayName.toLowerCase().includes(q) || entry.description.toLowerCase().includes(q));
  }, [catalog, rates, q]);

  const grouped = useMemo(() => {
    const map = new Map();
    for (const item of entries) {
      const cat = item.entry.category;
      if (!map.has(cat)) map.set(cat, []);
      map.get(cat).push(item);
    }
    return map;
  }, [entries]);

  function choose(entryItem) {
    if (entryItem.navigatesTo) { onNavigateIncomeTax?.(); return; }
    const rows = (rates || []).filter((r) => r.componentKey === entryItem.componentKey);
    if (rows.length > 0) { onEditExisting(rows[0]); return; }
    setEntry(entryItem);
    setForm({
      componentKey: entryItem.componentKey,
      label: entryItem.displayName,
      jurisdictionState: pack.jurisdictionState || "",
      employeeSharePct: "", employerSharePct: "", flatAmount: "", filingStatus: "",
      sortOrder: 0, reason: "",
    });
    setStep(2);
  }

  // State-catalog entries carry their own uiTypeHint (no STATIC_MAP entry
  // exists for them in usaComponentConfig.js, so classifyContributionRate's
  // heuristic fallback would otherwise have to guess) — prefer that hint,
  // falling back to the existing federal classification when absent.
  const resolvedUiType = entry ? (entry.uiTypeHint || classifyContributionRate({ componentKey: entry.componentKey }).uiType) : null;
  const desc = resolvedUiType ? describeUiType(resolvedUiType) : null;
  const rateField = resolvedUiType === UI_TYPES.EMPLOYER_ASSIGNED_RATE ? "employerRatePct" : "employeeRatePct";
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  async function save() {
    if (!form.componentKey?.trim() || !form.label?.trim()) {
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
        const val = rateField === "employerRatePct" ? form.employerSharePct : form.employeeSharePct;
        const clean = val === "" ? null : val;
        if (rateField === "employerRatePct") employerSharePct = clean; else employeeSharePct = clean;
      }
      await upsertCanonicalContributionRate({
        jurisdictionPackId: pack.id, jurisdictionCountry: pack.jurisdictionCountry,
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

  const stepTitle = { 1: "Select Component", 2: "Configure", 3: "Review & Save" }[step];

  return (
    <Drawer
      title="Add Component"
      subtitle={`Step ${step} of 3 — ${stepTitle}`}
      onClose={onClose}
      width="max-w-2xl"
      footer={
        <>
          {step > 1 && (
            <button
              onClick={() => setStep((s) => s - 1)}
              className="flex items-center gap-1 rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted"
            >
              <ChevronLeft size={14} /> Back
            </button>
          )}
          {step < 3 ? (
            <button
              onClick={() => step === 1 ? null : setStep(3)}
              disabled={step === 1}
              className="flex items-center gap-1 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-40"
            >
              Continue <ChevronRight size={14} />
            </button>
          ) : (
            <button
              onClick={save}
              disabled={saving}
              className="flex items-center gap-1 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50"
            >
              <Check size={14} /> {saving ? "Saving…" : "Save Component"}
            </button>
          )}
        </>
      }
    >
      {step === 1 && (
        <div>
          <div className="relative mb-4">
            <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-foreground-disabled" />
            <input
              autoFocus className={inputClass + " pl-9"} value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder="Search components…"
            />
          </div>
          <div className="max-h-[60vh] space-y-5 overflow-y-auto pr-1">
            {Object.keys(categories).map((catKey) => {
              const items = grouped.get(catKey);
              if (!items || items.length === 0) return null;
              // `categories` is now always ONE level's set (never merged —
              // see the catalog/categories selection above), so every
              // category shown here genuinely belongs to the open pack's
              // level: state name prefix for a state pack, "Federal" for
              // the country-level pack.
              const categoryLabel = pack.jurisdictionState
                ? `${pack.jurisdictionState} ${categories[catKey]}`
                : `Federal ${categories[catKey]}`;
              return (
                <div key={catKey}>
                  <p className="mb-1.5 text-[11px] font-bold uppercase tracking-wider text-foreground-muted">
                    {categoryLabel}
                  </p>
                  <div className="space-y-1">
                    {items.map(({ entry, rows }) => (
                      <button
                        key={entry.componentKey}
                        onClick={() => choose(entry)}
                        className={`flex w-full items-center justify-between rounded-lg border border-border px-3 py-2.5 text-left hover:border-primary hover:bg-primary/5 ${entry.parentKey ? "ml-5" : ""}`}
                      >
                        <div className="flex items-start gap-2">
                          {entry.parentKey && <CornerDownRight size={13} className="mt-0.5 text-foreground-disabled" />}
                          <div>
                            <p className="text-sm font-medium text-foreground">{entry.displayName}</p>
                            <p className="text-xs text-foreground-muted">{entry.description}</p>
                          </div>
                        </div>
                        <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${rows.length > 0 ? "bg-success-light text-success" : "bg-surface-muted text-foreground-disabled"}`}>
                          {rows.length > 0 ? "✓ Configured" : "Not configured"}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
            {entries.length === 0 && (
              <p className="py-6 text-center text-xs text-foreground-disabled">No components match "{search}".</p>
            )}
          </div>
        </div>
      )}

      {step === 2 && entry && (
        <div className="space-y-5">
          <FieldRow label="Component" value={entry.displayName} mono={entry.componentKey} />
          <FormSection title="General">
            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2"><label className={labelClass}>Label</label><input className={inputClass} value={form.label} onChange={set("label")} /></div>
              <div><label className={labelClass}>State / District</label>
                <select className={inputClass} value={form.jurisdictionState} onChange={set("jurisdictionState")}>
                  <option value="">Federal / Country-level</option>
                  {US_STATE_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
            </div>
          </FormSection>
          <FormSection title="Calculation">
            <div className="grid grid-cols-3 gap-3">
              {desc.employeeRate && desc.employerRate && (
                <>
                  <NumericField label="Employee Rate %" value={form.employeeSharePct} onChange={set("employeeSharePct")} suffix="%" placeholder="6.20" />
                  <NumericField label="Employer Rate %" value={form.employerSharePct} onChange={set("employerSharePct")} suffix="%" placeholder="6.20" />
                </>
              )}
              {desc.singleRate && (
                <NumericField label={desc.rateLabel} value={rateField === "employerRatePct" ? form.employerSharePct : form.employeeSharePct} onChange={rateField === "employerRatePct" ? set("employerSharePct") : set("employeeSharePct")} suffix="%" placeholder="0.90" />
              )}
              {desc.flatAmount && (
                <NumericField label={desc.flatAmountLabel} value={form.flatAmount} onChange={set("flatAmount")} prefix="$" placeholder="0.00" />
              )}
            </div>
          </FormSection>
          {desc.filingStatus && (
            <FormSection title="Applicability">
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className={labelClass}>Filing Status (optional)</label>
                  <select className={inputClass} value={form.filingStatus} onChange={set("filingStatus")}>
                    <option value="">Any filing status</option>
                    {US_FILING_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
              </div>
            </FormSection>
          )}
          <AdvancedSettings form={form} set={set} advancedOpen={advancedOpen} onToggle={() => setAdvancedOpen((o) => !o)} />
        </div>
      )}

      {step === 3 && entry && (
        <ReviewSummary form={form} entry={entry} desc={desc} rateField={rateField} />
      )}
    </Drawer>
  );
}

function FieldRow({ label, value, mono }) {
  return (
    <div className="flex items-center justify-between rounded-lg bg-surface-muted px-3 py-2 text-sm">
      <span className="text-foreground-muted">{label}</span>
      <span className="font-medium text-foreground">{value} {mono ? <span className="ml-1 font-mono text-[11px] text-foreground-disabled">{mono}</span> : null}</span>
    </div>
  );
}

function NumericField({ label, value, onChange, prefix, suffix, placeholder }) {
  return (
    <div>
      <label className={labelClass}>{label}</label>
      <div className="relative">
        {prefix && <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-foreground-muted">{prefix}</span>}
        <input
          type="number" inputMode="decimal"
          className={inputClass + (prefix ? " pl-7" : "") + (suffix ? " pr-7" : "")}
          value={value} onChange={onChange} placeholder={placeholder}
        />
        {suffix && <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-foreground-muted">{suffix}</span>}
      </div>
    </div>
  );
}

function AdvancedSettings({ form, set, advancedOpen, onToggle }) {
  return (
    <div>
      <button onClick={onToggle} className="flex items-center gap-1 text-[11px] font-bold uppercase tracking-wider text-foreground-muted">
        Advanced Settings
      </button>
      {advancedOpen && (
        <div className="mt-2 grid grid-cols-3 gap-3">
          <div><label className={labelClass}>Sort Order</label><input type="number" className={inputClass} value={form.sortOrder} onChange={set("sortOrder")} /></div>
          <div className="col-span-2"><label className={labelClass}>Reason for change (optional)</label><input className={inputClass} value={form.reason} onChange={set("reason")} placeholder="e.g. ZP-TAX-US reference" /></div>
        </div>
      )}
    </div>
  );
}

function ReviewSummary({ form, entry, desc, rateField }) {
  const rows = [];
  rows.push(["Component", entry.displayName]);
  if (desc.employeeRate && desc.employerRate) {
    rows.push(["Employee Rate %", form.employeeSharePct ? `${form.employeeSharePct}%` : "—"]);
    rows.push(["Employer Rate %", form.employerSharePct ? `${form.employerSharePct}%` : "—"]);
  } else if (desc.singleRate) {
    const val = rateField === "employerRatePct" ? form.employerSharePct : form.employeeSharePct;
    rows.push([desc.rateLabel, val ? `${val}%` : "—"]);
  }
  if (desc.flatAmount) rows.push([desc.flatAmountLabel, form.flatAmount ? `$${form.flatAmount}` : "—"]);
  if (desc.filingStatus) rows.push(["Filing Status", form.filingStatus || "Any"]);
  rows.push(["Sort Order", form.sortOrder]);
  if (form.reason) rows.push(["Reason", form.reason]);

  return (
    <div>
      <p className="mb-3 text-sm text-foreground-muted">Review the component before saving. Values below are what will be written for this pack.</p>
      <div className="overflow-hidden rounded-xl border border-border">
        {rows.map(([k, v], i) => (
          <div key={k} className={`flex items-center justify-between px-3 py-2.5 text-sm ${i % 2 === 0 ? "bg-surface" : "bg-surface-muted/50"}`}>
            <span className="text-foreground-muted">{k}</span>
            <span className="font-medium text-foreground">{v}</span>
          </div>
        ))}
      </div>
    </div>
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
