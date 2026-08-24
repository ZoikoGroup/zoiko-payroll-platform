import { useState } from "react";
import Modal from "../Modal";
import { inputClass, labelClass } from "./constants";
import {
  upsertCanonicalContributionRate, upsertCanonicalTaxSlab,
} from "../../service/superAdminService";

// A reusable, component-type-aware Add/Edit modal for Compliance Pack
// configuration — replaces the old one-size-fits-all "Edit Contribution
// Rate" form (Component Key/Label/State/Employee %/Employer %/Flat
// Amount/Sort Order for EVERY item, regardless of what it actually was).
// Genuinely reusable across jurisdictions: every sub-form here calls the
// SAME existing canonical rate/slab APIs every country's compliance page
// already uses (upsertCanonicalContributionRate/upsertCanonicalTaxSlab) —
// nothing UK-specific baked into this file, only the callers (today,
// UKCompliancePage.jsx) decide which configType/fields apply for a given
// tab. A future India/US/AU/DE/CA page can reuse this file directly.
//
// Deliberately does NOT invent fields the data model doesn't have:
// per-row Effective From/To and a "Frequency" dimension don't exist on
// ContributionRate/TaxSlab today (only the whole JurisdictionPack has an
// effective window) — every form below shows the pack's real effective
// period as READ-ONLY context instead of a fake editable field that
// would silently do nothing on save. That's a real, current limitation
// of the data model, not something a frontend-only refactor can honestly
// paper over.
export const CONFIG_TYPES = {
  THRESHOLD: "threshold",
  CONTRIBUTION_RATE: "contribution_rate",
  EMPLOYEE_DEDUCTION: "employee_deduction",
  TAX_SLAB: "tax_slab",
  NI_CATEGORY: "ni_category",
  GENERIC: "generic",
};

const NI_CATEGORIES = ["A", "B", "C", "D", "E", "F", "H", "I", "J", "K", "L", "M", "N", "S", "V", "Z"];
const PENSION_BASIS_OPTIONS = [
  { value: "QUALIFYING_EARNINGS", label: "Qualifying Earnings" },
  { value: "BASIC_PAY", label: "Basic Pay" },
  { value: "PENSIONABLE_EARNINGS", label: "Pensionable Earnings" },
];

function EffectivePeriodNote({ pack }) {
  return (
    <div className="col-span-2 rounded-lg bg-surface-muted px-3 py-2">
      <p className={labelClass + " mb-0.5"}>Effective Period</p>
      <p className="text-xs text-foreground-secondary">
        {pack?.effectiveFrom || "—"} → {pack?.effectiveTo || "open"}
        <span className="text-foreground-disabled"> (set at the Compliance Pack level, via Overview → Edit)</span>
      </p>
    </div>
  );
}

function ReasonField({ value, onChange }) {
  return (
    <div className="col-span-2">
      <label className={labelClass}>Reason for change (optional)</label>
      <input className={inputClass} value={value} onChange={onChange} placeholder="e.g. ZP-TAX-UK-2026-27-001 section 9.1" />
    </div>
  );
}

// ── THRESHOLD — a plain flat monetary limit (HMRC Statutory Thresholds,
// Workplace Pension → Qualifying Earnings). Never shows Employee/
// Employer % — a threshold isn't a contribution split.
function ThresholdForm({ pack, initialData, componentKey: fixedComponentKey, defaultLabel, lockComponentKey, onClose, onSaved, addToast }) {
  const [componentKey, setComponentKey] = useState(initialData?.componentKey || fixedComponentKey || "");
  const [label, setLabel] = useState(initialData?.label || defaultLabel || "");
  const [amount, setAmount] = useState(initialData?.flatAmount ?? "");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function save() {
    if (!componentKey.trim()) {
      setError("Component Key is required.");
      return;
    }
    if (amount === "" || Number.isNaN(Number(amount)) || Number(amount) < 0) {
      setError("Enter a threshold amount of £0 or more.");
      return;
    }
    if (!label.trim()) {
      setError("Label is required.");
      return;
    }
    setError("");
    setSaving(true);
    try {
      await upsertCanonicalContributionRate({
        id: initialData?.id, jurisdictionPackId: pack.id, jurisdictionCountry: pack.jurisdictionCountry,
        jurisdictionState: null, taxRegime: pack.taxRegime || null,
        componentKey, label, employeeSharePct: null, employerSharePct: null,
        flatAmount: amount, sortOrder: initialData?.sortOrder ?? 0, reason: reason || null,
      });
      addToast?.("Threshold saved.", "success");
      onSaved();
    } catch (err) {
      addToast?.(err.message || "Failed to save threshold.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={labelClass}>Component Key</label>
          <input className={inputClass} value={componentKey} disabled={lockComponentKey} onChange={(e) => setComponentKey(e.target.value)} />
        </div>
        <div><label className={labelClass}>Label</label><input className={inputClass} value={label} onChange={(e) => setLabel(e.target.value)} /></div>
        <div>
          <label className={labelClass}>Threshold Amount</label>
          <input className={inputClass} value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="e.g. 6240" />
        </div>
        <div>
          <label className={labelClass}>Frequency</label>
          <input className={inputClass} value="Annual" disabled title="Every UK statutory threshold today is an annual figure — not yet a configurable dimension." />
        </div>
        <EffectivePeriodNote pack={pack} />
        <ReasonField value={reason} onChange={(e) => setReason(e.target.value)} />
      </div>
      {error && <p className="mt-2 text-xs text-error">{error}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Saving…" : "Save"}</button>
      </div>
    </>
  );
}

// ── CONTRIBUTION_RATE — a genuine dual-sided contribution (Workplace
// Pension). Shows both Employee and Employer % with a live-computed
// Total. Saves the employer-pension rate row AND (if the Calculation
// Basis was changed) the separate pension_basis text-value row.
function ContributionRateForm({ pack, pensionRate, basisRow, onClose, onSaved, addToast }) {
  const [label, setLabel] = useState(pensionRate?.label || "Workplace Pension (Employer)");
  const [basis, setBasis] = useState(basisRow?.textValue || "QUALIFYING_EARNINGS");
  const [employeePct, setEmployeePct] = useState(pensionRate?.employeeRatePct ?? "");
  const [employerPct, setEmployerPct] = useState(pensionRate?.employerRatePct ?? "");
  const [flatAmount, setFlatAmount] = useState(pensionRate?.flatAmount ?? "");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const total = (employeePct !== "" || employerPct !== "")
    ? (Number(employeePct || 0) + Number(employerPct || 0))
    : null;

  async function save() {
    if (employeePct === "" && employerPct === "") {
      setError("Enter at least an Employee or Employer contribution.");
      return;
    }
    setError("");
    setSaving(true);
    try {
      await upsertCanonicalContributionRate({
        id: pensionRate?.id, jurisdictionPackId: pack.id, jurisdictionCountry: pack.jurisdictionCountry,
        jurisdictionState: null, taxRegime: pack.taxRegime || null,
        componentKey: "employer-pension", label,
        employeeSharePct: employeePct === "" ? null : employeePct,
        employerSharePct: employerPct === "" ? null : employerPct,
        flatAmount: flatAmount === "" ? null : flatAmount,
        sortOrder: pensionRate?.sortOrder ?? 0, reason: reason || null,
      });
      if (basis !== (basisRow?.textValue || "QUALIFYING_EARNINGS") || !basisRow) {
        await upsertCanonicalContributionRate({
          id: basisRow?.id, jurisdictionPackId: pack.id, jurisdictionCountry: pack.jurisdictionCountry,
          jurisdictionState: null, taxRegime: pack.taxRegime || null,
          componentKey: "pension_basis", label: "Pension Calculation Basis",
          employeeSharePct: null, employerSharePct: null, flatAmount: null,
          textValue: basis, sortOrder: basisRow?.sortOrder ?? 0, reason: reason || null,
        });
      }
      addToast?.("Workplace Pension contribution saved.", "success");
      onSaved();
    } catch (err) {
      addToast?.(err.message || "Failed to save.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className="grid grid-cols-2 gap-3">
        <div><label className={labelClass}>Component Key</label><input className={inputClass} value="employer-pension" disabled /></div>
        <div><label className={labelClass}>Label</label><input className={inputClass} value={label} onChange={(e) => setLabel(e.target.value)} /></div>
        <div className="col-span-2">
          <label className={labelClass}>Calculation Basis</label>
          <select className={inputClass} value={basis} onChange={(e) => setBasis(e.target.value)}>
            {PENSION_BASIS_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>

        <div className="col-span-2 border-t border-border-light pt-3">
          <p className="text-xs font-semibold text-foreground-secondary mb-2">Contribution Rates</p>
          <div className="grid grid-cols-2 gap-3">
            <div><label className={labelClass}>Employee Contribution %</label><input className={inputClass} value={employeePct} onChange={(e) => setEmployeePct(e.target.value)} placeholder="5.00" /></div>
            <div><label className={labelClass}>Employer Contribution %</label><input className={inputClass} value={employerPct} onChange={(e) => setEmployerPct(e.target.value)} placeholder="3.00" /></div>
          </div>
          <div className="mt-3 flex items-center justify-between rounded-lg bg-surface-muted px-3 py-2">
            <span className="text-xs font-semibold text-foreground-secondary">Total Contribution</span>
            <span className="text-sm font-bold text-foreground">{total != null ? `${total}%` : "—"}</span>
          </div>
          <div className="mt-3"><label className={labelClass}>Optional Flat Amount</label><input className={inputClass} value={flatAmount} onChange={(e) => setFlatAmount(e.target.value)} placeholder="£ amount, if used instead of/alongside a %" /></div>
        </div>

        <EffectivePeriodNote pack={pack} />
        <ReasonField value={reason} onChange={(e) => setReason(e.target.value)} />
      </div>
      {error && <p className="mt-2 text-xs text-error">{error}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Saving…" : "Save"}</button>
      </div>
    </>
  );
}

// ── EMPLOYEE_DEDUCTION — Student/Postgraduate Loan plans. The deduction
// RATE is a fixed HMRC figure per plan (engine/countries/uk.py hardcodes
// it — never read from this row), so it's shown as read-only reference,
// never as an editable input; only the threshold is genuinely
// configurable. Employer side never applies — shown as a badge, not a field.
function StudentLoanForm({ pack, plan: initialPlan, rate: initialRate, plans, rates, allowPlanChange, onClose, onSaved, addToast }) {
  const [planKey, setPlanKey] = useState(initialPlan.componentKey);
  const plan = plans.find((p) => p.componentKey === planKey) || initialPlan;
  const rate = allowPlanChange ? rates.find((r) => r.componentKey === planKey) : initialRate;
  const [amount, setAmount] = useState(initialRate?.flatAmount ?? "");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function onPlanChange(e) {
    const key = e.target.value;
    setPlanKey(key);
    setAmount(rates.find((r) => r.componentKey === key)?.flatAmount ?? "");
  }

  async function save() {
    if (amount === "" || Number.isNaN(Number(amount)) || Number(amount) < 0) {
      setError("Enter an annual threshold of £0 or more.");
      return;
    }
    setError("");
    setSaving(true);
    try {
      await upsertCanonicalContributionRate({
        id: rate?.id, jurisdictionPackId: pack.id, jurisdictionCountry: pack.jurisdictionCountry,
        jurisdictionState: null, taxRegime: pack.taxRegime || null,
        componentKey: plan.componentKey, label: rate?.label || `Student Loan ${plan.label} Threshold`,
        employeeSharePct: null, employerSharePct: null, flatAmount: amount,
        sortOrder: rate?.sortOrder ?? 0, reason: reason || null,
      });
      addToast?.("Student Loan plan saved.", "success");
      onSaved();
    } catch (err) {
      addToast?.(err.message || "Failed to save.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2">
          <label className={labelClass}>Loan Plan</label>
          {allowPlanChange ? (
            <select className={inputClass} value={planKey} onChange={onPlanChange}>
              {plans.map((p) => <option key={p.componentKey} value={p.componentKey}>{p.label}</option>)}
            </select>
          ) : (
            <input className={inputClass} value={plan.label} disabled />
          )}
        </div>
        <div><label className={labelClass}>Component Key</label><input className={inputClass} value={plan.componentKey} disabled /></div>
        <div><label className={labelClass}>Label</label><input className={inputClass} value={rate?.label || `Student Loan ${plan.label} Threshold`} disabled /></div>
        <div>
          <label className={labelClass}>Annual Threshold</label>
          <input className={inputClass} value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="e.g. 26900" />
        </div>
        <div>
          <label className={labelClass}>Employee Deduction Rate</label>
          <input className={inputClass} value={plan.rate} disabled title="Fixed by HMRC per plan — not configurable per Compliance Pack." />
        </div>
        <div className="col-span-2">
          <label className={labelClass}>Applies To</label>
          <div className="flex items-center gap-2">
            <span className="rounded-full bg-primary/10 px-3 py-1 text-xs font-semibold text-primary">Employee Deduction</span>
            <span className="text-xs text-foreground-disabled">— no employer contribution exists for Student/Postgraduate Loans.</span>
          </div>
        </div>
        <div className="col-span-2"><label className={labelClass}>Calculation Rule</label><input className={inputClass} value="Percentage of earnings above threshold" disabled /></div>
        <EffectivePeriodNote pack={pack} />
        <ReasonField value={reason} onChange={(e) => setReason(e.target.value)} />
      </div>
      {error && <p className="mt-2 text-xs text-error">{error}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Saving…" : "Save"}</button>
      </div>
    </>
  );
}

// ── TAX_SLAB — a PAYE income-tax bracket. Min/Max/Rate only — never
// Employee/Employer % or Flat Amount, which belong to a different shape
// entirely.
function TaxSlabForm({ pack, initialData, onClose, onSaved, addToast }) {
  const [label, setLabel] = useState(initialData?.rateLabel || "");
  const [minAmount, setMinAmount] = useState(initialData?.minAmount ?? "0");
  const [maxAmount, setMaxAmount] = useState(initialData?.maxAmount ?? "");
  const [ratePct, setRatePct] = useState(initialData?.ratePct ?? "");
  const [description, setDescription] = useState(initialData?.taxFormula || "");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function save() {
    if (minAmount === "" || Number.isNaN(Number(minAmount))) {
      setError("Minimum Income is required.");
      return;
    }
    if (maxAmount !== "" && Number(maxAmount) <= Number(minAmount)) {
      setError("Maximum Income must be greater than Minimum Income (leave blank for \"and above\").");
      return;
    }
    if (ratePct === "" || Number.isNaN(Number(ratePct))) {
      setError("Tax Rate is required.");
      return;
    }
    if (!label.trim()) {
      setError("Tax Band Name is required.");
      return;
    }
    setError("");
    setSaving(true);
    try {
      await upsertCanonicalTaxSlab({
        id: initialData?.id, jurisdictionPackId: pack.id, jurisdictionCountry: pack.jurisdictionCountry,
        jurisdictionState: pack.jurisdictionState || null, taxRegime: pack.taxRegime || null,
        minAmount, maxAmount: maxAmount === "" ? null : maxAmount, ratePct,
        rateLabel: label, taxFormula: description, ruleType: "MARGINAL_RATE",
        sortOrder: initialData?.sortOrder ?? 0, reason: reason || null,
      });
      addToast?.("PAYE tax band saved.", "success");
      onSaved();
    } catch (err) {
      addToast?.(err.message || "Failed to save tax band.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2"><label className={labelClass}>Tax Band Name</label><input className={inputClass} value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Basic Rate 20%" /></div>
        <div><label className={labelClass}>Minimum Income</label><input className={inputClass} value={minAmount} onChange={(e) => setMinAmount(e.target.value)} /></div>
        <div><label className={labelClass}>Maximum Income (blank = and above)</label><input className={inputClass} value={maxAmount} onChange={(e) => setMaxAmount(e.target.value)} /></div>
        <div><label className={labelClass}>Tax Rate %</label><input className={inputClass} value={ratePct} onChange={(e) => setRatePct(e.target.value)} /></div>
        <div><label className={labelClass}>Calculation Description (optional)</label><input className={inputClass} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="e.g. Higher Rate — England and NI" /></div>
        <EffectivePeriodNote pack={pack} />
        <ReasonField value={reason} onChange={(e) => setReason(e.target.value)} />
      </div>
      {error && <p className="mt-2 text-xs text-error">{error}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Saving…" : "Save"}</button>
      </div>
    </>
  );
}

// ── NI_CATEGORY — one National Insurance band for one HMRC category
// letter. Flat Amount is never shown — no NI_BAND row in this engine has
// ever used it (bands are always rate_pct/employer_rate_pct), matching
// the "only show Flat Amount if the configuration actually supports it" rule.
function NICategoryForm({ pack, initialData, onClose, onSaved, addToast }) {
  const [category, setCategory] = useState(initialData?.niCategory || "A");
  const [label, setLabel] = useState(initialData?.rateLabel || "");
  const [minAmount, setMinAmount] = useState(initialData?.minAmount ?? "0");
  const [maxAmount, setMaxAmount] = useState(initialData?.maxAmount ?? "");
  const [employeeRatePct, setEmployeeRatePct] = useState(initialData?.ratePct ?? "");
  const [employerRatePct, setEmployerRatePct] = useState(initialData?.employerRatePct ?? "");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function save() {
    if (minAmount === "" || Number.isNaN(Number(minAmount))) {
      setError("Earnings Range minimum is required.");
      return;
    }
    if (employeeRatePct === "" || Number.isNaN(Number(employeeRatePct))) {
      setError("Employee Rate % is required.");
      return;
    }
    setError("");
    setSaving(true);
    try {
      await upsertCanonicalTaxSlab({
        id: initialData?.id, jurisdictionPackId: pack.id, jurisdictionCountry: pack.jurisdictionCountry,
        jurisdictionState: null, taxRegime: pack.taxRegime || null,
        minAmount, maxAmount: maxAmount === "" ? null : maxAmount, ratePct: employeeRatePct,
        rateLabel: label || `NI Category ${category} band`, taxFormula: "", ruleType: "NI_BAND",
        niCategory: category, employerRatePct: employerRatePct === "" ? null : employerRatePct,
        sortOrder: initialData?.sortOrder ?? 0, reason: reason || null,
      });
      addToast?.("NI category band saved.", "success");
      onSaved();
    } catch (err) {
      addToast?.(err.message || "Failed to save NI band.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={labelClass}>NI Category</label>
          <select className={inputClass} value={category} onChange={(e) => setCategory(e.target.value)}>
            {NI_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div><label className={labelClass}>Label</label><input className={inputClass} value={label} onChange={(e) => setLabel(e.target.value)} placeholder={`NI Category ${category} band`} /></div>
        <div className="col-span-2">
          <p className={labelClass}>Earnings Range / Threshold Reference</p>
          <div className="grid grid-cols-2 gap-3">
            <input className={inputClass} value={minAmount} onChange={(e) => setMinAmount(e.target.value)} placeholder="Lower limit" />
            <input className={inputClass} value={maxAmount} onChange={(e) => setMaxAmount(e.target.value)} placeholder="Upper limit (blank = and above)" />
          </div>
        </div>
        <div><label className={labelClass}>Employee Rate %</label><input className={inputClass} value={employeeRatePct} onChange={(e) => setEmployeeRatePct(e.target.value)} /></div>
        <div><label className={labelClass}>Employer Rate %</label><input className={inputClass} value={employerRatePct} onChange={(e) => setEmployerRatePct(e.target.value)} /></div>
        <EffectivePeriodNote pack={pack} />
        <ReasonField value={reason} onChange={(e) => setReason(e.target.value)} />
      </div>
      {error && <p className="mt-2 text-xs text-error">{error}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Saving…" : "Save"}</button>
      </div>
    </>
  );
}

// ── GENERIC — the old one-size-fits-all shape, kept ONLY as a safety net
// for a componentType this modal doesn't know how to classify yet
// (matters for "reusability for future jurisdictions": an unmapped India/
// US/AU/DE/CA component still gets a working form instead of no form at all).
function GenericFallbackForm({ pack, initialData, onClose, onSaved, addToast }) {
  const [componentKey, setComponentKey] = useState(initialData?.componentKey || "");
  const [label, setLabel] = useState(initialData?.label || "");
  const [employeeSharePct, setEmployeeSharePct] = useState(initialData?.employeeRatePct ?? "");
  const [employerSharePct, setEmployerSharePct] = useState(initialData?.employerRatePct ?? "");
  const [flatAmount, setFlatAmount] = useState(initialData?.flatAmount ?? "");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      await upsertCanonicalContributionRate({
        id: initialData?.id, jurisdictionPackId: pack.id, jurisdictionCountry: pack.jurisdictionCountry,
        jurisdictionState: pack.jurisdictionState || null, taxRegime: pack.taxRegime || null,
        componentKey, label,
        employeeSharePct: employeeSharePct === "" ? null : employeeSharePct,
        employerSharePct: employerSharePct === "" ? null : employerSharePct,
        flatAmount: flatAmount === "" ? null : flatAmount,
        sortOrder: initialData?.sortOrder ?? 0, reason: reason || null,
      });
      addToast?.("Saved.", "success");
      onSaved();
    } catch (err) {
      addToast?.(err.message || "Failed to save.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className="grid grid-cols-2 gap-3">
        <div><label className={labelClass}>Component Key</label><input className={inputClass} value={componentKey} onChange={(e) => setComponentKey(e.target.value)} /></div>
        <div><label className={labelClass}>Label</label><input className={inputClass} value={label} onChange={(e) => setLabel(e.target.value)} /></div>
        <div><label className={labelClass}>Employee %</label><input className={inputClass} value={employeeSharePct} onChange={(e) => setEmployeeSharePct(e.target.value)} /></div>
        <div><label className={labelClass}>Employer %</label><input className={inputClass} value={employerSharePct} onChange={(e) => setEmployerSharePct(e.target.value)} /></div>
        <div><label className={labelClass}>Flat Amount</label><input className={inputClass} value={flatAmount} onChange={(e) => setFlatAmount(e.target.value)} /></div>
        <EffectivePeriodNote pack={pack} />
        <ReasonField value={reason} onChange={(e) => setReason(e.target.value)} />
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Saving…" : "Save"}</button>
      </div>
    </>
  );
}

const TITLES = {
  [CONFIG_TYPES.THRESHOLD]: { add: "Add Statutory Threshold", edit: "Edit Statutory Threshold" },
  [CONFIG_TYPES.CONTRIBUTION_RATE]: { add: "Add Workplace Pension Contribution", edit: "Edit Workplace Pension Contribution" },
  [CONFIG_TYPES.EMPLOYEE_DEDUCTION]: { add: "Add Student Loan Plan", edit: "Edit Student Loan Plan" },
  [CONFIG_TYPES.TAX_SLAB]: { add: "Add PAYE Tax Band", edit: "Edit PAYE Tax Band" },
  [CONFIG_TYPES.NI_CATEGORY]: { add: "Add NI Category Band", edit: "Edit NI Category Band" },
  [CONFIG_TYPES.GENERIC]: { add: "Add Contribution Rate", edit: "Edit Contribution Rate" },
};

// The single entry point every UK Compliance tab now opens instead of a
// hardcoded modal — `configType` (plus whatever extra props that type's
// form needs, spread via `formProps`) decides everything else: title,
// fields, and validation. `mode` only affects the title (add vs edit);
// each sub-form itself already knows how to behave for either based on
// whether it received existing data.
export default function ComplianceConfigModal({ configType, mode = "edit", title, description, ...formProps }) {
  const resolvedTitle = title || TITLES[configType]?.[mode] || TITLES[CONFIG_TYPES.GENERIC][mode];
  const Form = {
    [CONFIG_TYPES.THRESHOLD]: ThresholdForm,
    [CONFIG_TYPES.CONTRIBUTION_RATE]: ContributionRateForm,
    [CONFIG_TYPES.EMPLOYEE_DEDUCTION]: StudentLoanForm,
    [CONFIG_TYPES.TAX_SLAB]: TaxSlabForm,
    [CONFIG_TYPES.NI_CATEGORY]: NICategoryForm,
  }[configType] || GenericFallbackForm;

  return (
    <Modal title={resolvedTitle} onClose={formProps.onClose} maxWidth="max-w-lg">
      {description && <p className="mb-4 text-xs text-foreground-muted">{description}</p>}
      <Form {...formProps} />
    </Modal>
  );
}
