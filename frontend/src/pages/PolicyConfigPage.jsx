import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ArrowLeft, FileText, Plus, X } from "lucide-react";
import { useToast } from "../context/ToastContext";
import { upsertCompliancePolicy } from "../service/superAdminService";
import { CALCULATION_MODE_LABELS, EMPLOYEE_CATEGORY_LABELS } from "../service/payrollService";
import {
  STATUS_OPTIONS, inputClass, labelClass, emptyForm, slugify,
  CATEGORY_KEYS, CATEGORY_FIELDS, OVERTIME_FIELDS,
  getLockNode, setLockNode, LockableField,
} from "./policyFormShared";

// One row of the Allowance Components editor — label + %/flat amount +
// an "allow override" gate for the whole component (not per-field like
// LockableField; a partially-locked allowance isn't a real use case).
function AllowanceComponentRow({ componentKey, node, onChange, onRemove }) {
  const value = node.value || {};
  const allowOverride = node.allowOverride !== false;
  return (
    <div className="grid grid-cols-1 gap-2 rounded-lg border border-border p-2.5 sm:grid-cols-[1fr_110px_110px_auto_auto]">
      <input
        value={value.label ?? ""}
        onChange={(e) => onChange({ value: { ...value, label: e.target.value } })}
        placeholder="Transport Allowance"
        className="rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground"
      />
      <input
        type="number"
        value={value.pct ?? ""}
        onChange={(e) => onChange({ value: { ...value, pct: e.target.value === "" ? null : Number(e.target.value), flat_amount: null } })}
        placeholder="% of gross"
        className="rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground"
      />
      <input
        type="number"
        value={value.flat_amount ?? ""}
        onChange={(e) => onChange({ value: { ...value, flat_amount: e.target.value === "" ? null : Number(e.target.value), pct: null } })}
        placeholder="Flat amount"
        className="rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground"
      />
      <label className="flex items-center gap-1 whitespace-nowrap text-[10px] text-foreground-disabled">
        <input
          type="checkbox"
          checked={allowOverride}
          onChange={(e) => onChange({ allowOverride: e.target.checked })}
          className="h-3.5 w-3.5 rounded border-slate-300"
        />
        Allow override
      </label>
      <button type="button" onClick={onRemove} className="rounded-md p-1.5 text-foreground-disabled hover:bg-error/10 hover:text-error" title="Remove">
        <X size={14} />
      </button>
    </div>
  );
}

// Full-page Policy configuration — was previously a small modal
// (PolicyFormModal's `!isTax` branch in CompliancePage.jsx). Policy configs
// have more to review/scroll through (calculation mode, salary structure,
// six employee categories, overtime rule) than a modal comfortably fits,
// so this got its own route instead. Tax packs keep their 2-step modal
// wizard in CompliancePage.jsx — unaffected by this change.
export default function PolicyConfigPage() {
  const { addToast } = useToast() || {};
  const navigate = useNavigate();
  const location = useLocation();
  const { mode, initial, returnTo } = location.state || {};

  const [form, setForm] = useState(initial || emptyForm());
  const [saving, setSaving] = useState(false);

  if (!initial) {
    // Direct navigation/refresh with no state (e.g. a bookmarked URL) —
    // there's nothing to configure, so send them back to pick a jurisdiction
    // and start again rather than rendering a blank/broken form.
    navigate("/super-admin/compliance", { replace: true });
    return null;
  }

  const locked = mode === "newVersion";
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  function goBack() {
    navigate("/super-admin/compliance", {
      state: { tab: "policies", restoreJurisdiction: returnTo?.jurisdiction, restoreState: returnTo?.state },
    });
  }

  async function handleSave() {
    if (!form.packId.trim() || !form.jurisdictionCountry.trim() || !form.version.trim()) {
      addToast?.("Policy ID, country, and version are required.", "error");
      return;
    }
    setSaving(true);
    try {
      const payload = { ...form };
      Object.keys(payload).forEach((k) => {
        if (payload[k] === "") payload[k] = null;
      });
      await upsertCompliancePolicy(payload);
      addToast?.(mode === "newVersion" ? "New version created." : "Policy created.", "success");
      goBack();
    } catch (err) {
      addToast?.(err.message || "Failed to save.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-6 sm:px-6 lg:px-8">
      <button
        type="button"
        onClick={goBack}
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-foreground-secondary hover:text-foreground"
      >
        <ArrowLeft size={15} /> Back to Compliance
      </button>

      <div className="mb-6 flex items-center gap-2">
        <span className="inline-flex items-center gap-1 rounded-full bg-category-teal/10 px-2.5 py-1 text-xs font-bold text-category-teal">
          <FileText size={12} /> Policy
        </span>
        <h1 className="text-xl font-semibold text-foreground">
          {mode === "newVersion" ? `New Version — ${form.packId}` : "New Policy"}
        </h1>
      </div>

      <div className="space-y-6 rounded-xl border border-border bg-surface p-6 shadow-sm">
        {/* Identity + lifecycle */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className={labelClass}>Policy ID</label>
            <input value={form.packId} onChange={set("packId")} className={inputClass} placeholder="IN-POLICY-2026-V1" />
          </div>
          <div>
            <label className={labelClass}>Version</label>
            <input value={form.version} onChange={set("version")} disabled={locked} className={`${inputClass} ${locked ? "opacity-60" : ""}`} placeholder="1.0 / 1.1 / 2.0" />
          </div>
          <div>
            <label className={labelClass}>Country</label>
            <input value={form.jurisdictionCountry} onChange={set("jurisdictionCountry")} disabled={locked} className={`${inputClass} ${locked ? "opacity-60" : ""}`} placeholder="IN" />
          </div>
          <div>
            <label className={labelClass}>State / Province (optional)</label>
            <input value={form.jurisdictionState || ""} onChange={set("jurisdictionState")} disabled={locked} className={`${inputClass} ${locked ? "opacity-60" : ""}`} placeholder="Telangana" />
          </div>
          <div>
            <label className={labelClass}>Status</label>
            <select value={form.status} onChange={set("status")} className={inputClass}>
              {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div />
          <div>
            <label className={labelClass}>Effective From</label>
            <input type="date" value={form.effectiveFrom || ""} onChange={set("effectiveFrom")} className={inputClass} />
          </div>
          <div>
            <label className={labelClass}>Effective To</label>
            <input type="date" value={form.effectiveTo || ""} onChange={set("effectiveTo")} className={inputClass} />
          </div>
        </div>

        {/* Policy Defaults — the actual substance of a Policy pack */}
        <div className="rounded-lg border border-border px-4 py-4 space-y-5">
          <div>
            <p className="text-sm font-medium text-foreground">Policy Defaults</p>
            <p className="text-xs text-foreground-muted">
              Set a default value per field and uncheck "Allow override" to lock it — organizations assigned this
              policy pack must keep that field at the value shown. Leave a field as "No default" to keep it fully
              editable by the organization, exactly as today.
            </p>
          </div>

          <div>
            <p className={labelClass}>Calculation Mode</p>
            <LockableField
              label="Calculation Mode"
              node={getLockNode(form.policyDefaults, ["calculation_mode"])}
              type="select"
              choices={Object.entries(CALCULATION_MODE_LABELS).map(([value, label]) => ({ value, label }))}
              onChangeValue={(value) => setLockNode(setForm, ["calculation_mode"], { value })}
              onChangeAllow={(allowOverride) => setLockNode(setForm, ["calculation_mode"], { allowOverride })}
            />
          </div>

          <div>
            <p className={labelClass}>Salary Structure</p>
            <p className="mb-1.5 text-[11px] text-foreground-disabled">
              Percentage of monthly gross allocated as Basic and HRA for employees without their own explicit
              amounts set — Special Allowance is always whatever's left of gross.
            </p>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <LockableField
                label="Basic % of Gross"
                node={getLockNode(form.policyDefaults, ["basic_pct"])}
                type="number"
                onChangeValue={(value) => setLockNode(setForm, ["basic_pct"], { value })}
                onChangeAllow={(allowOverride) => setLockNode(setForm, ["basic_pct"], { allowOverride })}
              />
              <LockableField
                label="HRA % of Gross"
                node={getLockNode(form.policyDefaults, ["hra_pct"])}
                type="number"
                onChangeValue={(value) => setLockNode(setForm, ["hra_pct"], { value })}
                onChangeAllow={(allowOverride) => setLockNode(setForm, ["hra_pct"], { allowOverride })}
              />
            </div>
          </div>

          <div>
            <p className={labelClass}>Special Allowance</p>
            <p className="mb-1.5 text-[11px] text-foreground-disabled">
              Special Allowance is always whatever's left of gross after Basic, HRA, and the named components below.
              Add a component for anything organizations should break out as its own line item — Transport, Medical,
              or any custom name.
            </p>
            <div className="space-y-2">
              {Object.entries(form.policyDefaults?.allowance_components || {}).map(([key, node]) => (
                <AllowanceComponentRow
                  key={key}
                  componentKey={key}
                  node={node || {}}
                  onChange={(patch) => setLockNode(setForm, ["allowance_components", key], patch)}
                  onRemove={() => setForm((f) => {
                    const next = { ...(f.policyDefaults || {}) };
                    const components = { ...(next.allowance_components || {}) };
                    delete components[key];
                    next.allowance_components = components;
                    return { ...f, policyDefaults: next };
                  })}
                />
              ))}
              <button
                type="button"
                onClick={() => {
                  const label = window.prompt("Allowance name (e.g. Transport Allowance)");
                  if (!label || !label.trim()) return;
                  const key = slugify(label);
                  setLockNode(setForm, ["allowance_components", key], {
                    value: { label: label.trim(), pct: null, flat_amount: null },
                    allowOverride: true,
                  });
                }}
                className="inline-flex items-center gap-1.5 rounded-lg border border-dashed border-border px-3 py-1.5 text-xs font-medium text-foreground-secondary hover:bg-surface-muted"
              >
                <Plus size={13} /> Add Allowance Component
              </button>
            </div>
          </div>

          <div>
            <p className={labelClass}>Employee Categories</p>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {CATEGORY_KEYS.map((category) => (
                <div key={category} className="space-y-1.5 rounded-lg border border-border p-2.5">
                  <p className="text-xs font-semibold text-foreground">{EMPLOYEE_CATEGORY_LABELS[category]}</p>
                  {CATEGORY_FIELDS.map((field) => (
                    <LockableField
                      key={field.key}
                      label={field.label}
                      node={getLockNode(form.policyDefaults, ["employee_categories", category, field.key])}
                      type={field.type}
                      onChangeValue={(value) => setLockNode(setForm, ["employee_categories", category, field.key], { value })}
                      onChangeAllow={(allowOverride) => setLockNode(setForm, ["employee_categories", category, field.key], { allowOverride })}
                    />
                  ))}
                </div>
              ))}
            </div>
          </div>

          <div>
            <p className={labelClass}>Overtime Rule</p>
            <div className="space-y-1.5">
              {OVERTIME_FIELDS.map((field) => (
                <LockableField
                  key={field.key}
                  label={field.label}
                  node={getLockNode(form.policyDefaults, ["overtime_rule", field.key])}
                  type={field.type}
                  onChangeValue={(value) => setLockNode(setForm, ["overtime_rule", field.key], { value })}
                  onChangeAllow={(allowOverride) => setLockNode(setForm, ["overtime_rule", field.key], { allowOverride })}
                />
              ))}
            </div>
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t border-border pt-5">
          <button type="button" onClick={goBack} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">
            Cancel
          </button>
          <button type="button" onClick={handleSave} disabled={saving} className="rounded-lg bg-primary px-5 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">
            {saving ? "Saving…" : "Save Policy"}
          </button>
        </div>
      </div>
    </div>
  );
}
