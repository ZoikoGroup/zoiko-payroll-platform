import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Plus, Pencil, Trash2, X, Percent } from "lucide-react";
import Modal from "../../components/Modal";
import { upsertCanonicalContributionRate, upsertCanonicalTaxSlab } from "../../service/superAdminService";
import { inputClass, labelClass } from "../../components/jurisdiction/constants";
import RateFormModal from "../../components/jurisdiction/RateFormModal";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";
import INTaxComponentsTab from "../../components/jurisdiction/india/INTaxComponentsTab";
import { sanitizeNumeric } from "../../components/jurisdiction/india/inComponentConfig";

// India — everything country-specific for this jurisdiction lives in this
// one file: the two real backend constructs built this session (Section
// 87A/cess/surcharge parameters, and state-level Professional Tax
// brackets) and the config that wires them into the shared
// JurisdictionLayout. Every other country (USACompliancePage.jsx etc.)
// stays a thin wrapper because nothing country-specific exists for them
// yet — this file is only this size because India genuinely has real,
// shipped functionality the others don't.

// ── Tax Parameters ───────────────────────────────────────────────────────
// Curated component_keys this tab manages, split from the generic
// Contribution Rates table (PF/ESI/PT stay there). `appliesToBoth` keys
// share ONE regime-agnostic row; everything else gets its own row per
// regime (tax_regime="New"/"Old"). `notApplied` keys are stored but not
// yet read by the calculation engine — see india.py's docstring for why
// (no employee-declared 80C investment, NPS component, or F&F flow exists
// yet) — flagged visibly in the UI rather than silently pretending they work.
const PARAM_SECTIONS = [
  {
    key: "general", title: "General Settings", subtitle: "Standard deduction and cess",
    fields: [
      { key: "standard_deduction", label: "Standard Deduction", type: "currency", perRegime: true },
      { key: "cess_pct", label: "Health & Education Cess", type: "percent", appliesToBoth: true },
    ],
  },
  {
    key: "rebate87a", title: "Section 87A Rebate", subtitle: "Income Tax Act, 1961 — s.87A",
    fields: [
      { key: "rebate_87a_limit", label: "Income Eligibility Limit", type: "currency", perRegime: true },
      { key: "rebate_87a_max", label: "Maximum Rebate Amount", type: "currency", perRegime: true },
      { key: "rebate_87a_marginal_relief", label: "Marginal Relief", type: "toggle", appliesToBoth: true },
    ],
  },
  {
    key: "surcharge", title: "Surcharge Slabs & Caps", subtitle: "Tiered — its own table below",
    fields: [
      { key: "surcharge_cap_pct", label: "Maximum Surcharge Cap", type: "percent", perRegime: true },
      { key: "surcharge_marginal_relief", label: "Marginal Relief on Surcharge", type: "toggle", appliesToBoth: true },
    ],
  },
  {
    key: "retirement", title: "Retirement & Exemption Limits", subtitle: "Section 80C shown only under Old Regime",
    fields: [
      { key: "nps_80ccd2_employer_cap_pct", label: "NPS Employer Contribution Cap — 80CCD(2)", type: "percent", appliesToBoth: true, notApplied: true },
      { key: "gratuity_exemption_limit", label: "Gratuity Exemption Limit", type: "currency", appliesToBoth: true, notApplied: true },
      { key: "leave_encashment_exemption_limit", label: "Leave Encashment Exemption Limit", type: "currency", appliesToBoth: true, notApplied: true },
      { key: "section_80c_limit", label: "Section 80C Limit", type: "currency", perRegime: true, oldOnly: true, notApplied: true },
    ],
  },
];
// Exported so INTaxComponentsTab (the business-language Contribution
// Components tab) can exclude these rows from its own card list — they're
// only ever edited here, avoiding the same field showing up twice in raw
// form on a second tab.
export const PARAM_KEYS = new Set(PARAM_SECTIONS.flatMap((s) => s.fields.map((f) => f.key)));

function ParametersTab({ pack, rates, slabs, addToast, onReload, onPublish }) {
  const [regime, setRegime] = useState("New");
  const [values, setValues] = useState({});   // `${key}::${regime|"_"}` -> { id, value }
  const [tiers, setTiers] = useState([]);     // surcharge TaxSlab rows for the current regime
  const [saving, setSaving] = useState(false);
  const [reviewed, setReviewed] = useState(false);
  const [showAddCustom, setShowAddCustom] = useState(false);

  useEffect(() => {
    const next = {};
    for (const r of rates) {
      if (!PARAM_KEYS.has(r.componentKey)) continue;
      const scope = r.taxRegime || "_";
      next[`${r.componentKey}::${scope}`] = { id: r.id, value: r.flatAmount != null ? String(r.flatAmount) : "" };
    }
    setValues(next);
  }, [rates]);

  useEffect(() => {
    setTiers(
      slabs
        .filter((s) => s.ruleType === "SURCHARGE" && (s.taxRegime || "New") === regime)
        .map((s) => ({ id: s.id, minAmount: String(s.minAmount), ratePct: String(s.ratePct) }))
        .sort((a, b) => Number(a.minAmount) - Number(b.minAmount))
    );
  }, [slabs, regime]);

  function fieldScope(field) {
    return field.appliesToBoth ? "_" : regime;
  }
  function getValue(field) {
    return values[`${field.key}::${fieldScope(field)}`]?.value ?? "";
  }
  function setValue(field, raw) {
    const scope = fieldScope(field);
    setValues((prev) => ({ ...prev, [`${field.key}::${scope}`]: { ...(prev[`${field.key}::${scope}`] || {}), value: raw } }));
  }
  function isOn(field) {
    return getValue(field) === "1";
  }
  function toggle(field) {
    setValue(field, isOn(field) ? "0" : "1");
  }

  function addTier() {
    const last = tiers[tiers.length - 1];
    setTiers([...tiers, { id: null, minAmount: last ? String(Number(sanitizeNumeric(last.minAmount)) + 1000000) : "5000000", ratePct: "10" }]);
  }
  function removeTier(idx) {
    setTiers(tiers.filter((_, i) => i !== idx));
  }
  function updateTier(idx, field, raw) {
    setTiers(tiers.map((t, i) => (i === idx ? { ...t, [field]: raw } : t)));
  }

  async function saveDraft() {
    setSaving(true);
    try {
      const scalarSaves = [];
      for (const section of PARAM_SECTIONS) {
        for (const field of section.fields) {
          if (field.oldOnly && regime !== "Old") continue;
          const scope = fieldScope(field);
          const entry = values[`${field.key}::${scope}`];
          const raw = entry?.value ?? "";
          scalarSaves.push(
            upsertCanonicalContributionRate({
              id: entry?.id, jurisdictionPackId: pack.id, jurisdictionCountry: pack.jurisdictionCountry,
              jurisdictionState: pack.jurisdictionState || null, taxRegime: scope === "_" ? null : scope,
              componentKey: field.key, label: field.label,
              flatAmount: raw === "" ? null : sanitizeNumeric(raw), sortOrder: 0,
            })
          );
        }
      }
      const tierSaves = tiers
        .filter((t) => t.minAmount !== "" && t.ratePct !== "")
        .map((t) =>
          upsertCanonicalTaxSlab({
            id: t.id, jurisdictionPackId: pack.id, jurisdictionCountry: pack.jurisdictionCountry,
            jurisdictionState: pack.jurisdictionState || null, taxRegime: regime,
            minAmount: sanitizeNumeric(t.minAmount), maxAmount: null, ratePct: sanitizeNumeric(t.ratePct),
            rateLabel: `Surcharge above ${t.minAmount}`, ruleType: "SURCHARGE", sortOrder: 0,
          })
        );
      await Promise.all([...scalarSaves, ...tierSaves]);
      addToast?.("Tax parameters saved.", "success");
      onReload();
    } catch (err) {
      addToast?.(err.message || "Failed to save parameters.", "error");
    } finally {
      setSaving(false);
    }
  }

  const allFilled = PARAM_SECTIONS.every((section) =>
    section.fields.every((field) => {
      if (field.oldOnly && regime !== "Old") return true;
      if (field.type === "toggle") return true;
      return getValue(field) !== "";
    })
  );

  async function publish() {
    if (!reviewed) {
      addToast?.("Confirm you've reviewed this against the latest notification first.", "error");
      return;
    }
    if (!allFilled) {
      addToast?.("Some parameters are still empty — fill them in before publishing.", "error");
      return;
    }
    await saveDraft();
    onPublish();
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="inline-flex rounded-lg border border-border bg-surface-muted p-1">
          {["New", "Old"].map((r) => (
            <button
              key={r} onClick={() => setRegime(r)}
              className={`rounded-md px-4 py-1.5 text-xs font-bold ${regime === r ? "bg-surface text-primary shadow-sm" : "text-foreground-muted hover:text-foreground"}`}
            >
              {r} Regime
            </button>
          ))}
        </div>
        <button onClick={() => setShowAddCustom(true)} className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted">
          <Plus size={13} /> Add Custom Parameter
        </button>
      </div>

      {PARAM_SECTIONS.map((section) => (
        <div key={section.key} className="rounded-xl border border-border">
          <div className="border-b border-border-light px-4 py-3">
            <p className="text-sm font-bold text-foreground">{section.title}</p>
            <p className="text-[11px] text-foreground-muted">{section.subtitle}</p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 p-4">
            {section.fields
              .filter((field) => !field.oldOnly || regime === "Old")
              .map((field) => (
                <div key={field.key}>
                  <label className={labelClass}>
                    {field.label}
                    {field.notApplied && (
                      <span className="ml-1.5 rounded-full bg-warning/10 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-warning">Not yet applied</span>
                    )}
                  </label>
                  {field.type === "toggle" ? (
                    <button
                      onClick={() => toggle(field)}
                      className={`h-6 w-11 rounded-full transition-colors ${isOn(field) ? "bg-primary" : "bg-border-strong"}`}
                    >
                      <span className={`block h-5 w-5 rounded-full bg-white shadow transition-transform ${isOn(field) ? "translate-x-5" : "translate-x-0.5"}`} />
                    </button>
                  ) : (
                    <div className="relative">
                      {field.type === "currency" && <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs text-foreground-muted">₹</span>}
                      <input
                        className={inputClass + (field.type === "currency" ? " pl-6" : " pr-7")}
                        value={getValue(field)} onChange={(e) => setValue(field, e.target.value)}
                        placeholder={field.type === "percent" ? "e.g. 4" : "e.g. 75000"}
                      />
                      {field.type === "percent" && <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-foreground-muted">%</span>}
                    </div>
                  )}
                </div>
              ))}
          </div>
          {section.key === "surcharge" && (
            <div className="border-t border-border-light p-4">
              <div className="overflow-x-auto rounded-lg border border-border">
                <table className="w-full text-xs">
                  <thead className="bg-background text-left text-foreground-muted">
                    <tr><th className="px-3 py-2">Taxable income above</th><th className="px-3 py-2">Surcharge %</th><th className="px-3 py-2 w-10"></th></tr>
                  </thead>
                  <tbody>
                    {tiers.length === 0 ? (
                      <tr><td colSpan={3} className="px-3 py-4 text-center text-foreground-disabled">No surcharge tiers configured — surcharge stays 0 until at least one is added.</td></tr>
                    ) : tiers.map((t, i) => (
                      <tr key={t.id ?? `new-${i}`} className="border-t border-border-light">
                        <td className="px-3 py-2"><input className={inputClass} value={t.minAmount} onChange={(e) => updateTier(i, "minAmount", e.target.value)} /></td>
                        <td className="px-3 py-2"><input className={inputClass} value={t.ratePct} onChange={(e) => updateTier(i, "ratePct", e.target.value)} /></td>
                        <td className="px-3 py-2">
                          <button onClick={() => removeTier(i)} className="rounded p-1 text-foreground-disabled hover:text-error hover:bg-error-light"><X size={13} /></button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <button onClick={addTier} className="mt-2 flex items-center gap-1.5 text-xs font-semibold text-primary">
                <Plus size={13} /> Add tier
              </button>
            </div>
          )}
        </div>
      ))}

      <div className="flex items-center justify-between flex-wrap gap-3 border-t border-border pt-4">
        <label className="flex items-center gap-2 text-xs text-foreground-muted">
          <input type="checkbox" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} className="rounded border-border-strong" />
          Reviewed against the latest CBDT notification
        </label>
        <div className="flex items-center gap-2">
          <button onClick={saveDraft} disabled={saving} className="rounded-lg border border-border px-4 py-2 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted disabled:opacity-50">
            {saving ? "Saving…" : "Save Draft"}
          </button>
          <button
            onClick={publish} disabled={saving}
            className="rounded-lg bg-primary px-4 py-2 text-xs font-semibold text-white hover:bg-primary-hover disabled:opacity-50"
          >
            Publish Pack
          </button>
        </div>
      </div>

      {showAddCustom && (
        <RateFormModal
          pack={pack} onClose={() => setShowAddCustom(false)}
          onSaved={() => { setShowAddCustom(false); onReload(); }}
        />
      )}
    </div>
  );
}

// ── PT Slabs ──────────────────────────────────────────────────────────────
// State-level Professional Tax — a fixed monthly deduction per
// gross-income bracket, not a percentage. Reads only rule_type="PT_FLAT"
// TaxSlab rows (the caller below already filters `slabs` to that before
// passing them in) so it never shows a state's OTHER tax slabs (were
// there ever any) in this PT-shaped table.
function PTSlabsTab({ slabs, onAdd, onEdit, onDelete }) {
  const sorted = [...slabs].sort((a, b) => Number(a.minAmount) - Number(b.minAmount));
  const hasOpenEnded = sorted.some((s) => s.maxAmount == null);
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-foreground-muted">Professional Tax brackets — a fixed monthly deduction per gross-income range.</p>
        <button onClick={onAdd} className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover">
          <Plus size={13} /> Add PT Slab
        </button>
      </div>
      {sorted.length > 0 && !hasOpenEnded && (
        <div className="rounded-lg border border-warning/30 bg-warning/5 px-3 py-2 text-[11px] text-warning">
          No bracket covers "and above" yet — an employee earning more than the highest configured amount won't match any slab.
        </div>
      )}
      {sorted.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border-light px-3 py-8 text-center text-xs text-foreground-disabled">No PT slabs yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-xs">
            <thead className="bg-background text-left text-foreground-muted">
              <tr>
                <th className="px-3 py-2">Gross Income From (₹)</th>
                <th className="px-3 py-2">Gross Income To (₹)</th>
                <th className="px-3 py-2">Monthly PT Amount (₹)</th>
                <th className="px-3 py-2">Adjustment Month Amount (₹)</th>
                <th className="px-3 py-2 w-16"></th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((s) => (
                <tr key={s.id} className="border-t border-border-light">
                  <td className="px-3 py-2 text-foreground-secondary">{s.minAmount}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{s.maxAmount ?? "Above"}</td>
                  <td className="px-3 py-2 font-medium text-foreground">₹{s.flatAmount ?? "0"}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{s.adjustmentAmount != null ? `₹${s.adjustmentAmount}` : "—"}</td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-1">
                      <button onClick={() => onEdit(s)} className="rounded p-1 text-foreground-disabled hover:text-primary hover:bg-surface-muted"><Pencil size={12} /></button>
                      <button onClick={() => onDelete(s)} className="rounded p-1 text-foreground-disabled hover:text-error hover:bg-error-light"><Trash2 size={12} /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function PTSlabFormModal({ pack, slab, existingSlabs, onClose, onSaved, addToast }) {
  const [minAmount, setMinAmount] = useState(slab?.minAmount != null ? String(slab.minAmount) : "");
  const [isAbove, setIsAbove] = useState(slab ? slab.maxAmount == null : false);
  const [maxAmount, setMaxAmount] = useState(slab?.maxAmount != null ? String(slab.maxAmount) : "");
  const [flatAmount, setFlatAmount] = useState(slab?.flatAmount != null ? String(slab.flatAmount) : "");
  const [adjustmentAmount, setAdjustmentAmount] = useState(slab?.adjustmentAmount != null ? String(slab.adjustmentAmount) : "");
  const [saving, setSaving] = useState(false);

  const flatNum = Number(sanitizeNumeric(flatAmount)) || 0;
  const adjNum = adjustmentAmount === "" ? null : Number(sanitizeNumeric(adjustmentAmount));
  const annualTotal = adjNum != null ? flatNum * 11 + adjNum : flatNum * 12;

  async function save() {
    // Sanitized once here — used for both validation and the save payload,
    // so a value typed with Indian comma grouping (e.g. "1,00,00,000",
    // matching how this same data is DISPLAYED elsewhere) is accepted
    // instead of failing Number() parsing / the backend's decimal validator.
    const cleanMin = sanitizeNumeric(minAmount);
    const cleanMax = sanitizeNumeric(maxAmount);
    const cleanFlat = sanitizeNumeric(flatAmount);
    const cleanAdj = adjustmentAmount === "" ? "" : sanitizeNumeric(adjustmentAmount);

    const min = Number(cleanMin);
    const max = isAbove ? null : Number(cleanMax);
    const flat = Number(cleanFlat);
    const adj = cleanAdj === "" ? null : Number(cleanAdj);

    if (minAmount === "" || Number.isNaN(min) || min < 0) {
      addToast?.("Gross Income From must be a non-negative number.", "error");
      return;
    }
    if (!isAbove && (maxAmount === "" || Number.isNaN(max) || max <= min)) {
      addToast?.("Gross Income To must be greater than Gross Income From (or check 'And above').", "error");
      return;
    }
    if (flatAmount === "" || Number.isNaN(flat) || flat < 0) {
      addToast?.("Monthly PT Amount must be a non-negative number.", "error");
      return;
    }
    if (adjustmentAmount !== "" && (Number.isNaN(adj) || adj < 0)) {
      addToast?.("Adjustment Month Amount must be a non-negative number.", "error");
      return;
    }

    const others = (existingSlabs || []).filter((s) => s.id !== slab?.id);
    for (const other of others) {
      const otherMin = Number(other.minAmount);
      const otherMax = other.maxAmount == null ? Infinity : Number(other.maxAmount);
      const overlaps = min <= otherMax && (max ?? Infinity) >= otherMin;
      if (overlaps) {
        addToast?.(`This overlaps the existing ₹${other.minAmount}–${other.maxAmount ?? "Above"} bracket.`, "error");
        return;
      }
    }
    if (isAbove && others.some((s) => s.maxAmount == null)) {
      addToast?.("Another bracket is already open-ended ('And above') — only one is allowed.", "error");
      return;
    }

    setSaving(true);
    try {
      await upsertCanonicalTaxSlab({
        id: slab?.id, jurisdictionPackId: pack.id, jurisdictionCountry: pack.jurisdictionCountry,
        jurisdictionState: pack.jurisdictionState || null, taxRegime: null,
        minAmount: cleanMin, maxAmount: isAbove ? null : cleanMax,
        ratePct: 0, rateLabel: `₹${cleanFlat}`, taxFormula: "", ruleType: "PT_FLAT",
        flatAmount: cleanFlat, adjustmentAmount: cleanAdj === "" ? null : cleanAdj,
        sortOrder: 0,
      });
      addToast?.("PT slab saved.", "success");
      onSaved();
    } catch (err) {
      addToast?.(err.message || "Failed to save PT slab.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={slab ? "Edit PT Slab" : "Add PT Slab"} onClose={onClose} maxWidth="max-w-md">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={labelClass}>Gross Income From (₹)</label>
          <input className={inputClass} value={minAmount} onChange={(e) => setMinAmount(e.target.value)} placeholder="0" />
        </div>
        <div>
          <label className={labelClass}>Gross Income To (₹)</label>
          <input className={inputClass} value={isAbove ? "" : maxAmount} disabled={isAbove} onChange={(e) => setMaxAmount(e.target.value)} placeholder={isAbove ? "Above" : "20000"} />
          <label className="mt-1.5 flex items-center gap-1.5 text-[11px] text-foreground-muted">
            <input type="checkbox" checked={isAbove} onChange={(e) => setIsAbove(e.target.checked)} className="rounded border-border-strong" />
            And above (no upper limit)
          </label>
        </div>
        <div>
          <label className={labelClass}>Monthly PT Amount (₹)</label>
          <input className={inputClass} value={flatAmount} onChange={(e) => setFlatAmount(e.target.value)} placeholder="200" />
        </div>
        <div>
          <label className={labelClass}>Adjustment Month Amount (₹) <span className="font-normal normal-case tracking-normal text-foreground-disabled">(optional)</span></label>
          <input className={inputClass} value={adjustmentAmount} onChange={(e) => setAdjustmentAmount(e.target.value)} placeholder="e.g. 300 for Feb" />
        </div>
      </div>
      {flatAmount !== "" && (
        <p className="mt-2 text-[11px] text-foreground-muted">Annual total for this bracket: ₹{annualTotal.toFixed(2)}</p>
      )}
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Saving…" : "Save"}</button>
      </div>
    </Modal>
  );
}

// ── TDS Brackets ────────────────────────────────────────────────────────
// Country-level income-tax brackets — India's real "MARGINAL_RATE" TaxSlab
// rows. Replaces the generic Tax Slabs tab (Rule Type / State / Sort Order)
// with a table shaped for what these rows actually are, and — unlike the
// generic SlabFormModal, which stamps every row with the pack's single
// static taxRegime field — an explicit per-row New/Old regime, matching
// how get_tax_slabs() actually resolves brackets for an employee (each
// row's own tax_regime, not the pack's).
function inr(n) {
  return `₹${Number(n).toLocaleString("en-IN")}`;
}

function TDSBracketsTab({ slabs, onAdd, onEdit, onDelete }) {
  const [regime, setRegime] = useState("New");
  const filtered = slabs.filter((s) => (s.taxRegime || "New") === regime);
  const sorted = [...filtered].sort((a, b) => Number(a.minAmount) - Number(b.minAmount));
  const hasOpenEnded = sorted.some((s) => s.maxAmount == null);
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="inline-flex rounded-lg border border-border bg-surface-muted p-1">
          {["New", "Old"].map((r) => (
            <button
              key={r} onClick={() => setRegime(r)}
              className={`rounded-md px-4 py-1.5 text-xs font-bold ${regime === r ? "bg-surface text-primary shadow-sm" : "text-foreground-muted hover:text-foreground"}`}
            >
              {r} Regime
            </button>
          ))}
        </div>
        <button onClick={onAdd} className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover">
          <Plus size={13} /> Add Bracket
        </button>
      </div>
      {sorted.length > 0 && !hasOpenEnded && (
        <div className="rounded-lg border border-warning/30 bg-warning/5 px-3 py-2 text-[11px] text-warning">
          No bracket covers "and above" yet — an employee earning more than the highest configured amount under {regime} Regime won't match any slab.
        </div>
      )}
      {sorted.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border-light px-3 py-8 text-center text-xs text-foreground-disabled">No {regime} Regime tax brackets yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-xs">
            <thead className="bg-background text-left text-foreground-muted">
              <tr>
                <th className="px-3 py-2">Order</th>
                <th className="px-3 py-2">Income From</th>
                <th className="px-3 py-2">Income To</th>
                <th className="px-3 py-2">Tax Rate</th>
                <th className="px-3 py-2">Notes</th>
                <th className="px-3 py-2 w-16"></th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((s, i) => (
                <tr key={s.id} className="border-t border-border-light">
                  <td className="px-3 py-2 text-foreground-secondary">{i + 1}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{inr(s.minAmount)}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{s.maxAmount == null ? "And above" : inr(s.maxAmount)}</td>
                  <td className="px-3 py-2 font-medium text-foreground">{s.ratePct}%</td>
                  <td className="px-3 py-2 text-foreground-secondary">{s.rateLabel || "—"}</td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-1">
                      <button onClick={() => onEdit(s)} className="rounded p-1 text-foreground-disabled hover:text-primary hover:bg-surface-muted"><Pencil size={12} /></button>
                      <button onClick={() => onDelete(s)} className="rounded p-1 text-foreground-disabled hover:text-error hover:bg-error-light"><Trash2 size={12} /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function TDSBracketFormModal({ pack, slab, existingSlabs, onClose, onSaved, addToast }) {
  const [regime, setRegime] = useState(slab?.taxRegime || "New");
  const [minAmount, setMinAmount] = useState(slab?.minAmount != null ? String(slab.minAmount) : "");
  const [isAbove, setIsAbove] = useState(slab ? slab.maxAmount == null : false);
  const [maxAmount, setMaxAmount] = useState(slab?.maxAmount != null ? String(slab.maxAmount) : "");
  const [ratePct, setRatePct] = useState(slab?.ratePct != null ? String(slab.ratePct) : "");
  const [notes, setNotes] = useState(slab?.rateLabel || "");
  const [saving, setSaving] = useState(false);

  const cleanRatePctPreview = sanitizeNumeric(ratePct);
  const autoLabel = cleanRatePctPreview !== "" && !Number.isNaN(Number(cleanRatePctPreview)) ? `${cleanRatePctPreview}% Bracket`.slice(0, 20) : "";

  async function save() {
    // Sanitized once here — used for both validation and the save payload,
    // so a value typed with Indian comma grouping (e.g. "8,00,001",
    // matching how this same data is DISPLAYED elsewhere via inr()) is
    // accepted instead of failing Number() parsing / the backend's
    // decimal validator.
    const cleanMin = sanitizeNumeric(minAmount);
    const cleanMax = sanitizeNumeric(maxAmount);
    const cleanRate = sanitizeNumeric(ratePct);

    const min = Number(cleanMin);
    const max = isAbove ? null : Number(cleanMax);
    const rate = Number(cleanRate);

    if (minAmount === "" || Number.isNaN(min) || min < 0) {
      addToast?.("Income From must be a non-negative number.", "error");
      return;
    }
    if (!isAbove && (maxAmount === "" || Number.isNaN(max) || max <= min)) {
      addToast?.("Income To must be greater than Income From (or check 'And above').", "error");
      return;
    }
    if (ratePct === "" || Number.isNaN(rate) || rate < 0 || rate > 100) {
      addToast?.("Tax Rate must be a number between 0 and 100.", "error");
      return;
    }

    const others = (existingSlabs || []).filter((s) => s.id !== slab?.id && (s.taxRegime || "New") === regime);
    for (const other of others) {
      const otherMin = Number(other.minAmount);
      const otherMax = other.maxAmount == null ? Infinity : Number(other.maxAmount);
      // Strict inequalities — unlike PT_FLAT's inclusive-both-ends single-
      // bracket lookup, these are marginal-rate brackets summed
      // cumulatively (engine/countries/shared.py:_calculate_annual_tax):
      // one bracket's max touching the next one's min (e.g. 0–400000 then
      // 400000–and above) is the CORRECT, intended shape — income exactly
      // at the boundary is counted once, in the lower bracket, not double-
      // counted. Only a genuine overlap (ranges sharing more than a single
      // touching point) should be rejected.
      const overlaps = min < otherMax && (max ?? Infinity) > otherMin;
      if (overlaps) {
        addToast?.(`This overlaps the existing ${inr(other.minAmount)}–${other.maxAmount == null ? "and above" : inr(other.maxAmount)} bracket under ${regime} Regime.`, "error");
        return;
      }
    }
    if (isAbove && others.some((s) => s.maxAmount == null)) {
      addToast?.(`Another bracket under ${regime} Regime is already open-ended ('And above') — only one is allowed.`, "error");
      return;
    }

    setSaving(true);
    try {
      await upsertCanonicalTaxSlab({
        id: slab?.id, jurisdictionPackId: pack.id, jurisdictionCountry: pack.jurisdictionCountry,
        jurisdictionState: null, taxRegime: regime,
        minAmount: cleanMin, maxAmount: isAbove ? null : cleanMax,
        ratePct: cleanRate, rateLabel: (notes.trim() || autoLabel || `${cleanRate}%`).slice(0, 20),
        taxFormula: "", ruleType: "MARGINAL_RATE", sortOrder: 0,
      });
      addToast?.("Tax bracket saved.", "success");
      onSaved();
    } catch (err) {
      addToast?.(err.message || "Failed to save tax bracket.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={slab ? "Edit Tax Bracket" : "Add Tax Bracket"} onClose={onClose} maxWidth="max-w-md">
      <div className="mb-3 inline-flex rounded-lg border border-border bg-surface-muted p-1">
        {["New", "Old"].map((r) => (
          <button
            key={r} type="button" onClick={() => setRegime(r)}
            className={`rounded-md px-4 py-1.5 text-xs font-bold ${regime === r ? "bg-surface text-primary shadow-sm" : "text-foreground-muted hover:text-foreground"}`}
          >
            {r} Regime
          </button>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={labelClass}>Income From (₹)</label>
          <input className={inputClass} value={minAmount} onChange={(e) => setMinAmount(e.target.value)} placeholder="0" />
        </div>
        <div>
          <label className={labelClass}>Income To (₹)</label>
          <input className={inputClass} value={isAbove ? "" : maxAmount} disabled={isAbove} onChange={(e) => setMaxAmount(e.target.value)} placeholder={isAbove ? "And above" : "400000"} />
          <label className="mt-1.5 flex items-center gap-1.5 text-[11px] text-foreground-muted">
            <input type="checkbox" checked={isAbove} onChange={(e) => setIsAbove(e.target.checked)} className="rounded border-border-strong" />
            And above (no upper limit)
          </label>
        </div>
        <div>
          <label className={labelClass}>Tax Rate (%)</label>
          <input className={inputClass} value={ratePct} onChange={(e) => setRatePct(e.target.value)} placeholder="10" />
        </div>
        <div>
          <label className={labelClass}>Notes <span className="font-normal normal-case tracking-normal text-foreground-disabled">(optional)</span></label>
          <input className={inputClass} value={notes} onChange={(e) => setNotes(e.target.value.slice(0, 20))} placeholder={autoLabel || "e.g. 10% Bracket"} maxLength={20} />
        </div>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Saving…" : "Save"}</button>
      </div>
    </Modal>
  );
}

// ── India's JurisdictionLayout config ──────────────────────────────────
// Extra tab shown alongside the standard six, only for country-level (no
// state) India Tax packs — matches the pre-existing gate exactly.
// slabsTabOverride replaces the generic percentage-shaped Tax Slabs tab
// with the PT bracket table whenever the selected pack is a state-scoped
// India Tax pack — every other India pack (country-level, or Policy)
// keeps the generic Tax Slabs tab untouched. A state-scoped PT pack is
// also single-purpose enough that Contribution Rates and Versions don't
// apply the way they do to a full country-level pack — restrictTabsTo
// narrows the whole tab set down for it.
const indiaComplianceConfig = {
  extraTabs: [
    // Business-language replacement for the generic "Contribution Rates"
    // tab (hidden below via hiddenTabs) — PF/ESI/PT/TDS, presented as a
    // named-component picker instead of raw Component Key/Rate fields.
    // Same gate as "parameters" below: doesn't apply to a state-scoped PT
    // pack, which has no Contribution Rates concept of its own.
    {
      key: "components",
      label: "Contribution Components",
      icon: Percent,
      after: "overview",
      isVisible: (pack) => !pack.jurisdictionState,
      render: ({ pack, rates, addToast, onReload, onDeleteRate, onNavigateTab }) => (
        <INTaxComponentsTab
          pack={pack} rates={rates} addToast={addToast} onReload={onReload}
          onDeleteRate={onDeleteRate} onNavigateTab={onNavigateTab} paramKeys={PARAM_KEYS}
        />
      ),
    },
    {
      key: "parameters",
      label: "Tax Parameters",
      icon: Percent,
      isVisible: (pack) => !pack.jurisdictionState,
      render: ({ pack, rates, slabs, addToast, onReload, onPublish }) => (
        <ParametersTab pack={pack} rates={rates} slabs={slabs} addToast={addToast} onReload={onReload} onPublish={onPublish} />
      ),
    },
  ],
  hiddenTabs: ["rates"],
  // Active for every India Tax pack now (was: state-scoped PT packs only)
  // — branches internally on jurisdictionState so a state-scoped pack still
  // gets exactly today's PT Slabs behavior, while a country-level pack gets
  // the new TDS Brackets UI instead of the generic Tax Slabs tab. label/
  // restrictTabsTo/deleteTitle are now functions of the pack (JurisdictionLayout's
  // resolveOverride helper) so the two cases can differ — a country-level
  // pack keeps its full tab set; only the state-scoped PT case narrows it,
  // exactly as before.
  slabsTabOverride: {
    isActive: (pack) => pack.packType === "tax",
    label: (pack) => (pack.jurisdictionState ? "PT Slabs" : "Tax Slabs"),
    restrictTabsTo: (pack) => (pack.jurisdictionState ? ["overview", "slabs", "organizations", "audit"] : null),
    renderTab: ({ pack, slabs, onAdd, onEdit, onDelete }) =>
      pack.jurisdictionState ? (
        <PTSlabsTab slabs={slabs.filter((s) => s.ruleType === "PT_FLAT")} onAdd={onAdd} onEdit={onEdit} onDelete={onDelete} />
      ) : (
        <TDSBracketsTab slabs={slabs.filter((s) => (s.ruleType || "MARGINAL_RATE") === "MARGINAL_RATE")} onAdd={onAdd} onEdit={onEdit} onDelete={onDelete} />
      ),
    renderAddModal: ({ pack, slabs, onClose, onSaved, addToast }) =>
      pack.jurisdictionState ? (
        <PTSlabFormModal
          pack={pack} existingSlabs={slabs.filter((s) => s.ruleType === "PT_FLAT")}
          onClose={onClose} onSaved={onSaved} addToast={addToast}
        />
      ) : (
        <TDSBracketFormModal
          pack={pack} existingSlabs={slabs.filter((s) => (s.ruleType || "MARGINAL_RATE") === "MARGINAL_RATE")}
          onClose={onClose} onSaved={onSaved} addToast={addToast}
        />
      ),
    renderEditModal: ({ pack, slab, slabs, onClose, onSaved, addToast }) =>
      pack.jurisdictionState ? (
        <PTSlabFormModal
          pack={pack} slab={slab} existingSlabs={slabs.filter((s) => s.ruleType === "PT_FLAT")}
          onClose={onClose} onSaved={onSaved} addToast={addToast}
        />
      ) : (
        <TDSBracketFormModal
          pack={pack} slab={slab} existingSlabs={slabs.filter((s) => (s.ruleType || "MARGINAL_RATE") === "MARGINAL_RATE")}
          onClose={onClose} onSaved={onSaved} addToast={addToast}
        />
      ),
    deleteTitle: (pack) => (pack.jurisdictionState ? "Delete PT Slab" : "Delete Tax Bracket"),
    deleteMessage: (slab) =>
      slab.ruleType === "PT_FLAT"
        ? "Delete this PT slab? This cannot be undone."
        : `Delete this ${slab.ratePct}% tax bracket (${slab.taxRegime || "New"} Regime)? This cannot be undone.`,
  },
};

// ── The page itself ──────────────────────────────────────────────────────
export default function INCompliancePage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <JurisdictionLayout
      country="IN" countryName="India"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        // Push (not replace) — each state selection is its own history
        // entry so Back walks through them one at a time instead of
        // collapsing every state click into a single overwritten entry.
        navigate(state ? `/super-admin/compliance/india/${encodeURIComponent(state)}` : "/super-admin/compliance/india")
      }
      {...indiaComplianceConfig}
    />
  );
}
