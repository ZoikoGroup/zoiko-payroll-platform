import { useState, useEffect, useCallback } from "react";
import {
  ShieldCheck, Plus, RefreshCcw, History, Users as UsersIcon, GitBranch, Building2, ClipboardList, ArrowRight,
  Receipt, FileText, Trash2, Pencil, ScrollText, LayoutGrid,
} from "lucide-react";
import Modal from "../components/Modal";
import SearchInput from "../components/SearchInput";
import StatusPill from "../components/StatusPill";
import ConfirmDialog from "../components/ConfirmDialog";
import { useToast } from "../context/ToastContext";
import {
  getCompliancePolicies, upsertCompliancePolicy,
  getCompliancePolicyVersions, setCompliancePolicyStatus, getCompliancePolicyOrganizations,
  assignCompliancePolicy, listAllOrganizationsBrief, getComplianceConfigurations,
  getCanonicalTaxSlabs, upsertCanonicalTaxSlab, getCanonicalContributionRates,
  upsertCanonicalContributionRate, getTaxConfigurationAudit,
} from "../service/superAdminService";
// Reused, not redefined — these are the exact labels Organization Admin's
// own Payroll Policy screen already uses (payrollService.js centralizes
// them for both), so Policy Defaults below stays in sync with what an org
// admin actually sees for calculation mode / employee categories.
import { CALCULATION_MODE_LABELS, EMPLOYEE_CATEGORY_LABELS } from "../service/payrollService";
import { getStatesForCountryCode } from "../utils/registrationRegions";
import JurisdictionCardGrid, { AddJurisdictionModal } from "./JurisdictionCardGrid";

const STATUS_OPTIONS = ["Draft", "In Review", "QA", "Approved", "Active", "Deprecated", "Retired"];
const STATUS_PILL_MAP = {
  Active: "active", Approved: "approved", Draft: "pending", "In Review": "pending",
  QA: "pending", Deprecated: "inactive", Retired: "suspended",
};

const inputClass =
  "w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-focus-ring/40";
const labelClass = "block text-xs font-medium text-foreground-muted mb-1";

function emptyForm(country, state, packType) {
  return {
    packId: "", jurisdictionCountry: country || "IN", jurisdictionState: state || "", packType: packType || "policy",
    version: "1.0", status: "Draft",
    effectiveFrom: "", effectiveTo: "", regulatoryAuthority: "", complianceCategory: "",
    changeSummary: "", complianceOwner: "", engineeringOwner: "", sourceReferences: "", nextReviewDate: "",
    policyDefaults: {},
  };
}


// ── Policy Defaults (org-admin policy field defaults + override locks) ──
// Same field taxonomy as payroll/policy/models.py's PayrollPolicy — no new
// vocabulary invented here, just default values + an allowOverride flag
// layered on top of the same calculation_mode / employee_categories /
// overtime_rule fields Organization Admin already edits.
const CATEGORY_KEYS = ["full_time", "part_time", "intern", "contract", "consultant", "freelancer"];
const CATEGORY_FIELDS = [
  { key: "working_days", label: "Working Days", type: "number" },
  { key: "expected_hours", label: "Expected Hours", type: "number" },
  { key: "minimum_hours", label: "Minimum Hours", type: "number" },
  { key: "paid_leave_eligible", label: "Paid Leave Eligible", type: "boolean" },
];
const OVERTIME_FIELDS = [
  { key: "enabled", label: "Overtime Enabled", type: "boolean" },
  { key: "minimum_overtime_minutes", label: "Minimum OT Minutes", type: "number" },
  { key: "approval_required", label: "Approval Required", type: "boolean" },
];

function getLockNode(policyDefaults, path) {
  let node = policyDefaults;
  for (const key of path) {
    if (!node || typeof node !== "object") return {};
    node = node[key];
  }
  return node && typeof node === "object" ? node : {};
}

function setLockNode(setForm, path, patch) {
  setForm((f) => {
    const next = JSON.parse(JSON.stringify(f.policyDefaults || {}));
    let node = next;
    for (let i = 0; i < path.length - 1; i++) {
      const key = path[i];
      if (!node[key] || typeof node[key] !== "object") node[key] = {};
      node = node[key];
    }
    const leafKey = path[path.length - 1];
    const existing = node[leafKey] && typeof node[leafKey] === "object" ? node[leafKey] : {};
    node[leafKey] = { ...existing, ...patch };
    return { ...f, policyDefaults: next };
  });
}

function LockableField({ label, node, type, choices, onChangeValue, onChangeAllow }) {
  const value = node.value;
  const allowOverride = node.allowOverride !== false;
  return (
    <div className="flex items-center gap-2 rounded-lg border border-border px-3 py-2">
      <span className="flex-1 text-xs text-foreground-secondary">{label}</span>
      {type === "select" ? (
        <select
          value={value ?? ""}
          onChange={(e) => onChangeValue(e.target.value || null)}
          className="rounded-md border border-border bg-background text-xs px-2 py-1 text-foreground"
        >
          <option value="">No default</option>
          {choices.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </select>
      ) : type === "boolean" ? (
        <select
          value={value === true ? "true" : value === false ? "false" : ""}
          onChange={(e) => onChangeValue(e.target.value === "" ? null : e.target.value === "true")}
          className="rounded-md border border-border bg-background text-xs px-2 py-1 text-foreground"
        >
          <option value="">No default</option>
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>
      ) : (
        <input
          type="number"
          value={value ?? ""}
          onChange={(e) => onChangeValue(e.target.value === "" ? null : Number(e.target.value))}
          className="w-20 rounded-md border border-border bg-background text-xs px-2 py-1 text-foreground"
        />
      )}
      <label className="flex items-center gap-1 text-[10px] text-foreground-disabled whitespace-nowrap">
        <input
          type="checkbox"
          checked={allowOverride}
          onChange={(e) => onChangeAllow(e.target.checked)}
          className="h-3.5 w-3.5 rounded border-slate-300"
        />
        Allow override
      </label>
    </div>
  );
}

function PolicyFormModal({ mode, initial, onClose, onSaved }) {
  const { addToast } = useToast() || {};
  const [form, setForm] = useState(initial);
  const [saving, setSaving] = useState(false);
  // Tax packs are a 2-step flow: step 1 saves identity/metadata, step 2
  // (only for Tax) adds the actual rate/slab values on that same pack —
  // no more separate "create the pack, then go hunt down a Rates icon."
  const [step, setStep] = useState(1);
  const [savedPack, setSavedPack] = useState(null);
  // Version/country/state can't change across versions or in-place edits —
  // only a genuinely new pack can pick new ones. The ID itself (packId)
  // CAN be renamed in "edit" mode: the backend looks the row up by its
  // real database id (form.id) when editing, not by (packId, version), so
  // renaming never orphans the row's history or its linked canonical
  // rate/slab/audit rows. A new version still keeps the same ID as its
  // predecessor by definition, so it stays locked there.
  const locked = mode === "newVersion" || mode === "edit";
  const idLocked = mode === "newVersion";

  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  async function handleSaveStep1() {
    if (!form.packId.trim() || !form.jurisdictionCountry.trim() || !form.version.trim()) {
      addToast?.(`${isTax ? "Tax ID" : "Policy ID"}, country, and version are required.`, "error");
      return;
    }
    setSaving(true);
    try {
      const payload = { ...form };
      Object.keys(payload).forEach((k) => {
        if (payload[k] === "") payload[k] = null;
      });
      const saved = await upsertCompliancePolicy(payload);
      addToast?.(mode === "edit" ? "Tax details updated." : mode === "newVersion" ? "New version created." : isTax ? "Tax created — now add its rates." : "Policy created.", "success");
      if (isTax) {
        setSavedPack(saved);
        setStep(2);
      } else {
        onSaved();
      }
    } catch (err) {
      addToast?.(err.message || "Failed to save.", "error");
    } finally {
      setSaving(false);
    }
  }

  const isTax = form.packType === "tax";

  return (
    <Modal
      title={
        step === 2
          ? `Rates — ${form.packId} v${form.version}`
          : mode === "edit"
          ? `Edit — ${form.packId}`
          : mode === "newVersion"
          ? `New Version — ${form.packId}`
          : isTax ? "New Tax" : "New Policy"
      }
      onClose={onClose}
      maxWidth={step === 2 ? "max-w-3xl" : "max-w-2xl"}
    >
      {step === 1 ? (
      <>
      <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold mb-3 ${
        isTax ? "bg-blue-500/10 text-blue-500" : "bg-category-teal/10 text-category-teal"
      }`}>
        {isTax ? <Receipt size={11} /> : <FileText size={11} />}
        {isTax ? "Tax" : "Policy"}
      </span>
      {/* Identity + lifecycle — the same handful of fields matter for both
          Tax and Policy packs (what/where/when this version applies), so
          these stay first and un-collapsed for both. */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className={labelClass}>{isTax ? "Tax ID" : "Policy ID"}</label>
          <input value={form.packId} onChange={set("packId")} disabled={idLocked} className={`${inputClass} ${idLocked ? "opacity-60" : ""}`} placeholder={isTax ? "IN-PAYROLL-2026-V1" : "IN-POLICY-2026-V1"} />
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
        <div>
          <label className={labelClass}>Effective From</label>
          <input type="date" value={form.effectiveFrom || ""} onChange={set("effectiveFrom")} className={inputClass} />
        </div>
        <div>
          <label className={labelClass}>Effective To</label>
          <input type="date" value={form.effectiveTo || ""} onChange={set("effectiveTo")} className={inputClass} />
        </div>
      </div>

      {isTax ? (
        // Tax's paper trail — legal basis, authority, review cadence — is
        // the substance of a tax pack, so it stays directly visible.
        <div className="mt-5 grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className={labelClass}>Tax Category</label>
            <input value={form.complianceCategory || ""} onChange={set("complianceCategory")} className={inputClass} placeholder="Income Tax / Statutory Contribution…" />
          </div>
          <div>
            <label className={labelClass}>Regulatory Authority</label>
            <input value={form.regulatoryAuthority || ""} onChange={set("regulatoryAuthority")} className={inputClass} placeholder="HMRC / IRS / CBDT…" />
          </div>
          <div>
            <label className={labelClass}>Next Review Date</label>
            <input type="date" value={form.nextReviewDate || ""} onChange={set("nextReviewDate")} className={inputClass} />
          </div>
          <div>
            <label className={labelClass}>Compliance Owner</label>
            <input value={form.complianceOwner || ""} onChange={set("complianceOwner")} className={inputClass} />
          </div>
          <div>
            <label className={labelClass}>Engineering Owner</label>
            <input value={form.engineeringOwner || ""} onChange={set("engineeringOwner")} className={inputClass} />
          </div>
          <div className="sm:col-span-2">
            <label className={labelClass}>Change Summary</label>
            <textarea value={form.changeSummary || ""} onChange={set("changeSummary")} rows={2} className={inputClass} placeholder="What changed in this version…" />
          </div>
          <div className="sm:col-span-2">
            <label className={labelClass}>Source References</label>
            <textarea value={form.sourceReferences || ""} onChange={set("sourceReferences")} rows={2} className={inputClass} placeholder="Notification / circular / gazette reference…" />
          </div>
        </div>
      ) : (
      // Policy's actual substance — default values & override locks —
      // is the whole point of a Policy pack, so nothing else (tax-flavored
      // paper trail like Regulatory Authority/Source References) is shown
      // here at all — not even collapsed.
      <div className="mt-5 rounded-lg border border-border px-3.5 py-3.5 space-y-4">
        <p className="text-sm font-medium text-foreground">Policy Defaults</p>
        <p className="text-xs text-foreground-muted">
          Set a default value per field and uncheck "Allow override" to lock it — organizations assigned this
          policy pack must keep that field at the value shown. Leave a field as "No default" to keep it fully
          editable by the organization, exactly as today.
        </p>

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
          <p className="text-[11px] text-foreground-disabled mb-1.5">
            Percentage of monthly gross allocated as Basic and HRA for employees without their own explicit
            amounts set — Special Allowance is always whatever's left of gross.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
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
          <p className={labelClass}>Employee Categories</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {CATEGORY_KEYS.map((category) => (
              <div key={category} className="rounded-lg border border-border p-2.5 space-y-1.5">
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
      )}

      <div className="mt-6 flex justify-end gap-2">
        <button type="button" onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">
          Cancel
        </button>
        <button type="button" onClick={handleSaveStep1} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">
          {saving ? "Saving…" : isTax ? "Save & Next →" : "Save"}
        </button>
      </div>
      </>
      ) : (
      <>
        <RatesEditor pack={savedPack} />
        <div className="mt-6 flex justify-end">
          <button type="button" onClick={onSaved} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover">
            Done
          </button>
        </div>
      </>
      )}
    </Modal>
  );
}

function VersionHistoryModal({ packId, versions, onClose }) {
  return (
    <Modal title={`Version History — ${packId}`} onClose={onClose} maxWidth="max-w-2xl">
      {versions.length === 0 ? (
        <p className="py-8 text-center text-sm text-foreground-disabled">No versions found.</p>
      ) : (
        <div className="space-y-3">
          {versions.map((v) => (
            <div key={v.id} className="rounded-lg border border-border p-3.5">
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-2 text-sm font-semibold text-foreground">
                  <GitBranch size={14} className="text-slate-400" /> v{v.version}
                </span>
                <StatusPill status={STATUS_PILL_MAP[v.status] || "pending"} label={v.status} />
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-foreground-muted">
                <span>Created: {v.createdAt ? new Date(v.createdAt).toLocaleDateString() : "—"}</span>
                <span>Effective: {v.effectiveFrom || "—"} → {v.effectiveTo || "—"}</span>
              </div>
              {v.changeSummary && (
                <p className="mt-2 text-sm text-foreground-secondary">{v.changeSummary}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}

// Government-mandated rate/slab values for one Tax pack version — the
// canonical (Super Admin-owned) rows engine/tax_resolver.py resolves and
// sync_org_rates_from_canonical() pushes down into every org's own
// ContributionRate/TaxSlab rows (what payroll calculation actually reads).
// Editing here changes the source of truth; it does not directly touch any
// organization's live payroll until that org is next synced.
//
// Rendered as step 2 of PolicyFormModal's Tax flow (New Tax → Next → add
// rates here → Done) — not its own modal, so creating a tax and entering
// its numbers is one continuous flow instead of two disconnected actions.
//
// Named, per-country government-mandated scalar parameters — the exact
// component_keys engine/standard.py's _param_amount/_param_pct read via
// rate_map (with the value shown in `fallback` as the built-in default
// when nothing is configured here). Proper labeled fields instead of the
// generic "Add Rate" free-text component-key entry, since typing the key
// wrong here silently breaks the calculation for that value (this is
// exactly the "EPF" vs "pf" bug this session already hit once).
const TAX_PARAMETER_FIELDS = {
  IN: [
    { key: "standard_deduction", label: "Standard Deduction", type: "amount", fallback: "75,000" },
    { key: "rebate_87a_limit", label: "Section 87A Rebate — Income Limit", type: "amount", fallback: "12,00,000" },
    { key: "rebate_87a_max", label: "Section 87A Rebate — Max Rebate", type: "amount", fallback: "60,000" },
    { key: "esi_wage_ceiling", label: "ESI Wage Ceiling (monthly)", type: "amount", fallback: "21,000" },
  ],
  US: [
    { key: "standard_deduction", label: "Federal Standard Deduction", type: "amount", fallback: "15,000" },
    { key: "ss_wage_base", label: "Social Security Wage Base", type: "amount", fallback: "176,100" },
    { key: "medicare_additional", label: "Additional Medicare Rate", type: "pct", fallback: "0.9%" },
    { key: "medicare_addl_thresh", label: "Additional Medicare Threshold", type: "amount", fallback: "200,000" },
  ],
  UK: [
    { key: "personal_allowance", label: "Personal Allowance", type: "amount", fallback: "12,570" },
    { key: "pa_taper_threshold", label: "Personal Allowance Taper Threshold", type: "amount", fallback: "100,000" },
    { key: "ni_primary_thresh", label: "NI Primary Threshold", type: "amount", fallback: "12,570" },
    { key: "ni_upper_threshold", label: "NI Upper Earnings Limit", type: "amount", fallback: "50,270" },
    { key: "ni_upper_rate", label: "NI Upper Rate", type: "pct", fallback: "2%" },
  ],
};

function RatesEditor({ pack }) {
  const { addToast } = useToast() || {};
  const [rates, setRates] = useState([]);
  const [slabs, setSlabs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [savingKey, setSavingKey] = useState("");
  const [newRate, setNewRate] = useState({ componentKey: "", label: "", employeeSharePct: "", employerSharePct: "", flatAmount: "" });
  const [newSlab, setNewSlab] = useState({ minAmount: "", maxAmount: "", ratePct: "", rateLabel: "", taxFormula: "" });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [r, s] = await Promise.all([
        getCanonicalContributionRates({ jurisdictionPackId: pack.id }),
        getCanonicalTaxSlabs({ jurisdictionPackId: pack.id }),
      ]);
      setRates(r);
      setSlabs(s.sort((a, b) => Number(a.minAmount) - Number(b.minAmount)));
    } catch (err) {
      addToast?.(err.message || "Failed to load rates.", "error");
    } finally {
      setLoading(false);
    }
  }, [pack.id]);

  useEffect(() => { load(); }, [load]);

  async function saveParamField(field, existing, value) {
    setSavingKey(`param-${field.key}`);
    try {
      await upsertCanonicalContributionRate({
        id: existing?.id, jurisdictionPackId: pack.id, jurisdictionCountry: pack.jurisdictionCountry,
        jurisdictionState: pack.jurisdictionState, componentKey: field.key, label: field.label,
        employeeSharePct: field.type === "pct" ? value : null,
        employerSharePct: null,
        flatAmount: field.type === "amount" ? value : null,
      });
      addToast?.(`${field.label} saved.`, "success");
      load();
    } catch (err) {
      addToast?.(err.message || `Failed to save ${field.label}.`, "error");
    } finally {
      setSavingKey("");
    }
  }

  async function saveRate(rate, patch) {
    setSavingKey(`rate-${rate.id}`);
    try {
      await upsertCanonicalContributionRate({
        id: rate.id, jurisdictionPackId: pack.id, jurisdictionCountry: pack.jurisdictionCountry,
        jurisdictionState: pack.jurisdictionState, componentKey: rate.componentKey, label: rate.label,
        employeeSharePct: rate.employeeRatePct, employerSharePct: rate.employerRatePct, flatAmount: rate.flatAmount,
        sortOrder: rate.sortOrder, ...patch,
      });
      addToast?.("Contribution rate saved.", "success");
      load();
    } catch (err) {
      addToast?.(err.message || "Failed to save rate.", "error");
    } finally {
      setSavingKey("");
    }
  }

  async function addRate() {
    if (!newRate.componentKey.trim() || !newRate.label.trim()) {
      addToast?.("Component key and label are required.", "error");
      return;
    }
    setSavingKey("new-rate");
    try {
      await upsertCanonicalContributionRate({
        jurisdictionPackId: pack.id, jurisdictionCountry: pack.jurisdictionCountry, jurisdictionState: pack.jurisdictionState,
        componentKey: newRate.componentKey.trim(), label: newRate.label.trim(),
        employeeSharePct: newRate.employeeSharePct || null, employerSharePct: newRate.employerSharePct || null,
        flatAmount: newRate.flatAmount || null,
      });
      setNewRate({ componentKey: "", label: "", employeeSharePct: "", employerSharePct: "", flatAmount: "" });
      addToast?.("Contribution rate added.", "success");
      load();
    } catch (err) {
      addToast?.(err.message || "Failed to add rate.", "error");
    } finally {
      setSavingKey("");
    }
  }

  async function saveSlab(slab, patch) {
    setSavingKey(`slab-${slab.id}`);
    try {
      await upsertCanonicalTaxSlab({
        id: slab.id, jurisdictionPackId: pack.id, jurisdictionCountry: pack.jurisdictionCountry,
        jurisdictionState: pack.jurisdictionState, minAmount: slab.minAmount, maxAmount: slab.maxAmount,
        ratePct: slab.ratePct, rateLabel: slab.rateLabel, taxFormula: slab.taxFormula,
        ruleType: slab.ruleType, formulaExpression: slab.formulaExpression, sortOrder: slab.sortOrder,
        ...patch,
      });
      addToast?.("Tax slab saved.", "success");
      load();
    } catch (err) {
      addToast?.(err.message || "Failed to save slab.", "error");
    } finally {
      setSavingKey("");
    }
  }

  async function addSlab() {
    if (newSlab.minAmount === "" || newSlab.ratePct === "") {
      addToast?.("Minimum amount and rate are required.", "error");
      return;
    }
    setSavingKey("new-slab");
    try {
      await upsertCanonicalTaxSlab({
        jurisdictionPackId: pack.id, jurisdictionCountry: pack.jurisdictionCountry, jurisdictionState: pack.jurisdictionState,
        minAmount: newSlab.minAmount, maxAmount: newSlab.maxAmount || null, ratePct: newSlab.ratePct,
        rateLabel: newSlab.rateLabel || `${newSlab.ratePct}%`, taxFormula: newSlab.taxFormula || "",
        sortOrder: slabs.length + 1,
      });
      setNewSlab({ minAmount: "", maxAmount: "", ratePct: "", rateLabel: "", taxFormula: "" });
      addToast?.("Tax slab added.", "success");
      load();
    } catch (err) {
      addToast?.(err.message || "Failed to add slab.", "error");
    } finally {
      setSavingKey("");
    }
  }

  const cellInput = "w-full rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-focus-ring";

  return (
      loading ? (
        <p className="py-8 text-center text-sm text-foreground-disabled">Loading…</p>
      ) : (
        <div className="space-y-6">
          <div>
            <p className="text-xs font-semibold text-foreground-muted mb-2">
              Contribution Rates — component key, employee %, employer %, or a flat amount
            </p>
            <div className="rounded-lg border border-border overflow-x-auto">
              <table className="w-full text-xs min-w-[560px]">
                <thead className="bg-background text-left text-foreground-muted">
                  <tr>
                    <th className="px-3 py-2">Component</th><th className="px-3 py-2">Label</th>
                    <th className="px-3 py-2">Employee %</th><th className="px-3 py-2">Employer %</th>
                    <th className="px-3 py-2">Flat Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {rates.map((r) => (
                    <tr key={r.id} className="border-t border-border-light">
                      <td className="px-3 py-1.5 font-mono text-foreground-secondary">{r.componentKey}</td>
                      <td className="px-3 py-1.5 text-foreground-secondary">{r.label}</td>
                      <td className="px-3 py-1.5">
                        <input className={cellInput} type="number" step="0.01" defaultValue={r.employeeRatePct ?? ""}
                          onBlur={(e) => e.target.value !== String(r.employeeRatePct ?? "") && saveRate(r, { employeeSharePct: e.target.value || null })}
                          disabled={savingKey === `rate-${r.id}`} />
                      </td>
                      <td className="px-3 py-1.5">
                        <input className={cellInput} type="number" step="0.01" defaultValue={r.employerRatePct ?? ""}
                          onBlur={(e) => e.target.value !== String(r.employerRatePct ?? "") && saveRate(r, { employerSharePct: e.target.value || null })}
                          disabled={savingKey === `rate-${r.id}`} />
                      </td>
                      <td className="px-3 py-1.5">
                        <input className={cellInput} type="number" step="0.01" defaultValue={r.flatAmount ?? ""}
                          onBlur={(e) => e.target.value !== String(r.flatAmount ?? "") && saveRate(r, { flatAmount: e.target.value || null })}
                          disabled={savingKey === `rate-${r.id}`} />
                      </td>
                    </tr>
                  ))}
                  <tr className="border-t border-border-light bg-slate-50/50 dark:bg-white/5">
                    <td className="px-3 py-1.5"><input className={cellInput} placeholder="component_key" value={newRate.componentKey} onChange={(e) => setNewRate((f) => ({ ...f, componentKey: e.target.value }))} /></td>
                    <td className="px-3 py-1.5"><input className={cellInput} placeholder="Label" value={newRate.label} onChange={(e) => setNewRate((f) => ({ ...f, label: e.target.value }))} /></td>
                    <td className="px-3 py-1.5"><input className={cellInput} type="number" step="0.01" value={newRate.employeeSharePct} onChange={(e) => setNewRate((f) => ({ ...f, employeeSharePct: e.target.value }))} /></td>
                    <td className="px-3 py-1.5"><input className={cellInput} type="number" step="0.01" value={newRate.employerSharePct} onChange={(e) => setNewRate((f) => ({ ...f, employerSharePct: e.target.value }))} /></td>
                    <td className="px-3 py-1.5 flex items-center gap-1">
                      <input className={cellInput} type="number" step="0.01" value={newRate.flatAmount} onChange={(e) => setNewRate((f) => ({ ...f, flatAmount: e.target.value }))} />
                      <button onClick={addRate} disabled={savingKey === "new-rate"} className="shrink-0 rounded-md bg-primary p-1.5 text-white hover:bg-primary-hover disabled:opacity-50"><Plus size={12} /></button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          {(TAX_PARAMETER_FIELDS[pack.jurisdictionCountry] || []).length > 0 && (
            <div>
              <p className="text-xs font-semibold text-foreground-muted mb-1">Tax Parameters</p>
              <p className="text-[11px] text-foreground-disabled mb-2">
                Government-mandated thresholds this jurisdiction's calculator reads directly. Leave blank to use
                the built-in default shown as a placeholder.
              </p>
              <div className="rounded-lg border border-border p-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
                {TAX_PARAMETER_FIELDS[pack.jurisdictionCountry].map((field) => {
                  const existing = rates.find((r) => r.componentKey === field.key);
                  const currentValue = field.type === "pct" ? existing?.employeeRatePct : existing?.flatAmount;
                  return (
                    <div key={field.key}>
                      <label className="block text-[11px] font-medium text-foreground-muted mb-1">
                        {field.label} {field.type === "pct" ? "(%)" : ""}
                      </label>
                      <input
                        className={cellInput}
                        type="number" step="0.01"
                        defaultValue={currentValue ?? ""}
                        placeholder={`Default: ${field.fallback}`}
                        disabled={savingKey === `param-${field.key}`}
                        onBlur={(e) => {
                          const v = e.target.value;
                          if (v !== "" && Number(v) !== Number(currentValue ?? NaN)) {
                            saveParamField(field, existing, v);
                          }
                        }}
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          <div>
            <p className="text-xs font-semibold text-foreground-muted mb-2">Tax Slabs — progressive brackets</p>
            <div className="rounded-lg border border-border overflow-x-auto">
              <table className="w-full text-xs min-w-[560px]">
                <thead className="bg-background text-left text-foreground-muted">
                  <tr>
                    <th className="px-3 py-2">Min</th><th className="px-3 py-2">Max</th>
                    <th className="px-3 py-2">Rate %</th><th className="px-3 py-2">Label</th><th className="px-3 py-2">Formula / Note</th>
                  </tr>
                </thead>
                <tbody>
                  {slabs.map((s) => (
                    <tr key={s.id} className="border-t border-border-light">
                      <td className="px-3 py-1.5">
                        <input className={cellInput} type="number" defaultValue={s.minAmount} onBlur={(e) => e.target.value !== String(s.minAmount) && saveSlab(s, { minAmount: e.target.value })} disabled={savingKey === `slab-${s.id}`} />
                      </td>
                      <td className="px-3 py-1.5">
                        <input className={cellInput} type="number" placeholder="and above" defaultValue={s.maxAmount ?? ""} onBlur={(e) => e.target.value !== String(s.maxAmount ?? "") && saveSlab(s, { maxAmount: e.target.value || null })} disabled={savingKey === `slab-${s.id}`} />
                      </td>
                      <td className="px-3 py-1.5">
                        <input className={cellInput} type="number" step="0.01" defaultValue={s.ratePct} onBlur={(e) => e.target.value !== String(s.ratePct) && saveSlab(s, { ratePct: e.target.value })} disabled={savingKey === `slab-${s.id}`} />
                      </td>
                      <td className="px-3 py-1.5 text-foreground-secondary">{s.rateLabel}</td>
                      <td className="px-3 py-1.5 text-foreground-muted">
                        {s.ruleType === "FORMULA" ? <span className="font-mono">{s.formulaExpression}</span> : s.taxFormula}
                      </td>
                    </tr>
                  ))}
                  <tr className="border-t border-border-light bg-slate-50/50 dark:bg-white/5">
                    <td className="px-3 py-1.5"><input className={cellInput} type="number" value={newSlab.minAmount} onChange={(e) => setNewSlab((f) => ({ ...f, minAmount: e.target.value }))} /></td>
                    <td className="px-3 py-1.5"><input className={cellInput} type="number" placeholder="and above" value={newSlab.maxAmount} onChange={(e) => setNewSlab((f) => ({ ...f, maxAmount: e.target.value }))} /></td>
                    <td className="px-3 py-1.5"><input className={cellInput} type="number" step="0.01" value={newSlab.ratePct} onChange={(e) => setNewSlab((f) => ({ ...f, ratePct: e.target.value }))} /></td>
                    <td className="px-3 py-1.5"><input className={cellInput} placeholder="e.g. 20%" value={newSlab.rateLabel} onChange={(e) => setNewSlab((f) => ({ ...f, rateLabel: e.target.value }))} /></td>
                    <td className="px-3 py-1.5 flex items-center gap-1">
                      <input className={cellInput} placeholder="Display note" value={newSlab.taxFormula} onChange={(e) => setNewSlab((f) => ({ ...f, taxFormula: e.target.value }))} />
                      <button onClick={addSlab} disabled={savingKey === "new-slab"} className="shrink-0 rounded-md bg-primary p-1.5 text-white hover:bg-primary-hover disabled:opacity-50"><Plus size={12} /></button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <p className="text-xs text-foreground-disabled">
            These are the canonical, government-mandated values. Organizations read a synced copy — changes here
            take effect the next time an organization's rates are synced from this jurisdiction.
          </p>
        </div>
      )
  );
}

// Read-only trail of who changed a canonical tax/rate value, when, and
// what changed — payroll_tax_configuration_audit, written automatically by
// every canonical mutation in service.py (record_tax_audit).
function AuditHistoryModal({ pack, onClose }) {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getTaxConfigurationAudit({ jurisdictionPackId: pack.id })
      .then(setEntries)
      .finally(() => setLoading(false));
  }, [pack.id]);

  return (
    <Modal title={`Audit History — ${pack.packId} v${pack.version}`} onClose={onClose} maxWidth="max-w-2xl">
      {loading ? (
        <p className="py-8 text-center text-sm text-foreground-disabled">Loading…</p>
      ) : entries.length === 0 ? (
        <p className="py-8 text-center text-sm text-foreground-disabled">No changes recorded yet.</p>
      ) : (
        <div className="max-h-96 overflow-y-auto space-y-2.5">
          {entries.map((e) => (
            <div key={e.id} className="rounded-lg border border-border p-3 text-xs">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-foreground capitalize">
                  {e.action.replace("_", " ")} · {e.entityType.replace("_", " ")}
                </span>
                <span className="text-foreground-disabled">
                  {e.createdAt ? new Date(e.createdAt).toLocaleString() : "—"}
                </span>
              </div>
              {(e.oldValue || e.newValue) && (
                <div className="mt-1.5 grid grid-cols-2 gap-2 font-mono text-[10px] text-foreground-muted">
                  <span>old: {JSON.stringify(e.oldValue)}</span>
                  <span>new: {JSON.stringify(e.newValue)}</span>
                </div>
              )}
              {e.reason && <p className="mt-1.5 text-foreground-muted">{e.reason}</p>}
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}

function AssignOrgsModal({ policy, orgs, assignedOrgIds, setAssignedOrgIds, onClose, onSave, saving }) {
  const [search, setSearch] = useState("");
  const isTax = policy.packType === "tax";
  const filtered = orgs.filter((o) =>
    (o.organization_name || o.organizationName || "").toLowerCase().includes(search.toLowerCase())
  );

  function toggle(id) {
    setAssignedOrgIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  return (
    <Modal title={`${isTax ? "Apply Tax & Sync Rates" : "Assign Policy"} — ${policy.packId} v${policy.version}`} onClose={onClose} maxWidth="max-w-lg">
      {isTax && (
        <p className="mb-3 text-xs text-foreground-muted rounded-lg bg-slate-50 dark:bg-white/5 border border-border px-3 py-2.5">
          This pushes this tax version's contribution rates and slabs into each selected organization's own payroll
          configuration — overwriting whatever they currently have for {policy.jurisdictionCountry}
          {policy.jurisdictionState ? ` / ${policy.jurisdictionState}` : ""}. Their next payslip uses the new numbers.
        </p>
      )}
      <SearchInput value={search} onChange={setSearch} placeholder="Search organizations…" className="mb-3" />
      <div className="max-h-72 overflow-y-auto rounded-lg border border-border">
        {filtered.length === 0 ? (
          <p className="p-4 text-center text-sm text-foreground-disabled">No organizations found.</p>
        ) : (
          filtered.map((o) => (
            <label key={o.id} className="flex items-center gap-3 border-b border-border-light px-3.5 py-2.5 last:border-b-0 hover:bg-surface-muted cursor-pointer">
              <input type="checkbox" checked={assignedOrgIds.includes(o.id)} onChange={() => toggle(o.id)} className="h-4 w-4 rounded border-slate-300" />
              <span className="flex-1 text-sm text-foreground">{o.organization_name || o.organizationName}</span>
              <span className="text-xs font-mono text-foreground-disabled">{o.organization_code || o.organizationCode}</span>
            </label>
          ))
        )}
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button type="button" onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">
          Cancel
        </button>
        <button type="button" onClick={onSave} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">
          {saving ? "Applying…" : `${isTax ? "Sync" : "Apply to"} ${assignedOrgIds.length} organization(s)`}
        </button>
      </div>
    </Modal>
  );
}

// One clean horizontal nav bar — Overview is a first-class tab alongside
// Taxes/Policies/Organizations (not a separate gated view), so the page
// has one consistent shell regardless of whether a jurisdiction is picked
// yet. States lives in this same bar as a persistent selector, not a tab.
const NAV_TABS = [
  { key: "overview", label: "Overview", icon: LayoutGrid },
  { key: "taxes", label: "Taxes", icon: Receipt },
  { key: "policies", label: "Policies", icon: FileText },
  { key: "orgConfigs", label: "Organizations", icon: ClipboardList },
];

export default function CompliancePage() {
  const { addToast } = useToast() || {};

  // null = no jurisdiction picked yet; set = every fetch below scopes to
  // this jurisdiction (+ optional state) — switching either changes the
  // entire configuration context, and nothing from one jurisdiction/state
  // is ever visible under another.
  const [selectedJurisdiction, setSelectedJurisdiction] = useState(null);
  const [selectedState, setSelectedState] = useState(""); // "" = country-level
  const [showAddJurisdiction, setShowAddJurisdiction] = useState(false);

  const [tab, setTab] = useState("overview"); // "overview" | "taxes" | "policies" | "orgConfigs"
  const [policies, setPolicies] = useState([]);
  const [configurations, setConfigurations] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  const [formState, setFormState] = useState(null); // { mode, initial }
  const [historyState, setHistoryState] = useState(null); // { packId, versions }
  const [auditPack, setAuditPack] = useState(null); // tax pack row whose Audit History modal is open
  const [assignState, setAssignState] = useState(null); // { policy, orgs, assignedOrgIds, saving }
  const [archiving, setArchiving] = useState(null); // the policy/tax pack pending archive confirmation
  const [archiveBusy, setArchiveBusy] = useState(false);

  const countryCode = selectedJurisdiction?.code || "";
  const availableStates = selectedJurisdiction ? getStatesForCountryCode(countryCode) : [];

  const load = useCallback(async () => {
    if (!selectedJurisdiction || tab === "overview") return;
    setLoading(true);
    setError("");
    try {
      if (tab === "orgConfigs") {
        const c = await getComplianceConfigurations({ country: countryCode, search: search || undefined });
        setConfigurations(c);
      } else {
        const p = await getCompliancePolicies({
          country: countryCode,
          state: selectedState || undefined,
          packType: tab === "taxes" ? "tax" : "policy",
          status: statusFilter || undefined,
          search: search || undefined,
        });
        setPolicies(p);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [selectedJurisdiction, countryCode, selectedState, tab, statusFilter, search]);

  useEffect(() => { load(); }, [load]);

  function handleSelectJurisdiction(jurisdiction) {
    setSelectedJurisdiction(jurisdiction);
    setSelectedState("");
    setTab("taxes");
    setSearch("");
    setStatusFilter("");
  }

  async function openHistory(policy) {
    setHistoryState({ packId: policy.packId, versions: [] });
    try {
      const versions = await getCompliancePolicyVersions(policy.packId);
      setHistoryState({ packId: policy.packId, versions });
    } catch (err) {
      addToast?.(err.message || "Failed to load version history.", "error");
      setHistoryState(null);
    }
  }

  async function openAssign(policy) {
    setAssignState({ policy, orgs: [], assignedOrgIds: [], saving: false });
    try {
      const [orgList, applied] = await Promise.all([
        listAllOrganizationsBrief(),
        getCompliancePolicyOrganizations(policy.id),
      ]);
      setAssignState({
        policy,
        orgs: orgList.organizations || [],
        assignedOrgIds: applied.map((o) => o.id),
        saving: false,
      });
    } catch (err) {
      addToast?.(err.message || "Failed to load organizations.", "error");
      setAssignState(null);
    }
  }

  async function handleAssignSave() {
    if (!assignState) return;
    setAssignState((s) => ({ ...s, saving: true }));
    try {
      const res = await assignCompliancePolicy(assignState.policy.id, assignState.assignedOrgIds);
      addToast?.(res.message || "Assignment updated.", "success");
      setAssignState(null);
      load();
    } catch (err) {
      addToast?.(err.message || "Failed to assign.", "error");
      setAssignState((s) => ({ ...s, saving: false }));
    }
  }

  async function handleStatusChange(policy, status) {
    try {
      await setCompliancePolicyStatus(policy.id, status);
      addToast?.(`Policy set to ${status}.`, "success");
      load();
    } catch (err) {
      addToast?.(err.message || "Failed to update status.", "error");
    }
  }

  // "Delete" here archives (status -> Retired), never a real row deletion —
  // JurisdictionPack has no delete endpoint at all, by design, since its
  // version chain and organization assignments are audit history. Retired
  // packs keep their full history and can be un-retired via the status
  // dropdown, same as any other status change.
  async function handleArchiveConfirm() {
    if (!archiving) return;
    setArchiveBusy(true);
    try {
      await setCompliancePolicyStatus(archiving.id, "Retired");
      addToast?.(`${archiving.packId} archived.`, "success");
      setArchiving(null);
      load();
    } catch (err) {
      addToast?.(err.message || "Failed to archive.", "error");
    } finally {
      setArchiveBusy(false);
    }
  }

  return (
    <div>
      {/* Page header — same structure regardless of navigation state */}
      <div className="mb-5">
        <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
          <ShieldCheck size={22} className="text-primary" /> Compliance
          {selectedJurisdiction && (
            <span className="ml-1 inline-flex items-center gap-1.5 rounded-full bg-slate-100 dark:bg-white/10 pl-1 pr-3 py-1 text-xs font-semibold text-foreground-secondary">
              <span className="flex h-5 w-5 items-center justify-center rounded-full bg-slate-900 dark:bg-black text-[9px] font-bold text-white">
                {countryCode}
              </span>
              {selectedJurisdiction.name}{selectedState ? ` / ${selectedState}` : ""}
            </span>
          )}
        </h1>
        <p className="text-sm text-foreground-muted mt-1">
          {selectedJurisdiction
            ? `${selectedJurisdiction.currency || "N/A"} · Taxes, policies, and organization assignments configured here apply only to ${selectedState || selectedJurisdiction.name}.`
            : "Pick a jurisdiction from Overview to manage its Taxes, Policies, and organization assignments — every jurisdiction (and state/province within it) is configured independently."}
        </p>
      </div>

      {/* One horizontal nav bar — tabs on the left, jurisdiction-wide
          controls (States, Refresh) on the right. Always rendered, so
          switching tabs never reloads or restructures the page. */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-5 pb-4 border-b border-border">
        <div className="flex flex-wrap gap-2">
          {NAV_TABS.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              aria-current={tab === key ? "page" : undefined}
              className={`flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition ${
                tab === key
                  ? "bg-primary text-white shadow-sm"
                  : "bg-surface border border-border text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5"
              }`}
            >
              <Icon size={15} /> {label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <select
            value={selectedState}
            disabled={!selectedJurisdiction || availableStates.length === 0}
            onChange={(e) => setSelectedState(e.target.value)}
            title="States"
            className="rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground disabled:opacity-50"
          >
            {!selectedJurisdiction ? (
              <option value="">Select a jurisdiction first</option>
            ) : (
              <>
                <option value="">Country-level (no state)</option>
                {availableStates.map((s) => <option key={s} value={s}>{s}</option>)}
              </>
            )}
          </select>
          {tab !== "overview" && (
            <button
              onClick={load}
              disabled={loading || !selectedJurisdiction}
              className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5 disabled:opacity-50"
            >
              <RefreshCcw size={15} className={loading ? "animate-spin" : ""} /> Refresh
            </button>
          )}
        </div>
      </div>

      {tab === "overview" && (
        <div>
          <JurisdictionCardGrid onSelect={handleSelectJurisdiction} onAddJurisdiction={() => setShowAddJurisdiction(true)} />
          {showAddJurisdiction && (
            <AddJurisdictionModal
              onClose={() => setShowAddJurisdiction(false)}
              onAdd={(j) => { setShowAddJurisdiction(false); handleSelectJurisdiction(j); }}
            />
          )}
        </div>
      )}

      {tab !== "overview" && !selectedJurisdiction && (
        <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border px-4 py-16 text-center">
          <LayoutGrid size={28} className="text-border-strong" />
          <p className="text-sm text-foreground-disabled">
            Pick a jurisdiction from <button onClick={() => setTab("overview")} className="font-semibold text-primary hover:underline">Overview</button> to get started.
          </p>
        </div>
      )}

      {tab !== "overview" && selectedJurisdiction && (
      <>
      <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
        <div className="flex flex-wrap items-center gap-2">
          <SearchInput
            value={search}
            onChange={setSearch}
            placeholder={tab === "orgConfigs" ? "Search organization, pack…" : "Search policy, authority, category…"}
            className="w-64"
          />
          {tab !== "orgConfigs" && (
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground"
            >
              <option value="">All Statuses</option>
              {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          )}
        </div>
        {tab !== "orgConfigs" && (
          <button
            onClick={() => setFormState({
              mode: "create",
              initial: emptyForm(countryCode, selectedState, tab === "taxes" ? "tax" : "policy"),
            })}
            className="flex items-center gap-2 rounded-lg bg-primary px-3.5 py-2 text-sm font-medium text-white hover:bg-primary-hover"
          >
            <Plus size={15} /> {tab === "taxes" ? "New Tax" : "New Policy"}
          </button>
        )}
      </div>

      {error && (
        <p className="mb-4 rounded-lg border border-red-200 bg-red-50 dark:bg-red-950/30 dark:border-red-900 px-4 py-3 text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      )}

      {tab === "orgConfigs" ? (
        <div className="bg-surface rounded-xl shadow-sm border border-border overflow-hidden overflow-x-auto">
          <table className="w-full text-sm min-w-[900px]">
            <thead className="bg-background text-left text-xs text-foreground-muted">
              <tr>
                <th className="px-4 py-3">Organization</th>
                <th className="px-4 py-3">Jurisdiction</th>
                <th className="px-4 py-3">Current Pack (as configured)</th>
                <th className="px-4 py-3">Active Versioned Policy</th>
                <th className="px-4 py-3">Configured</th>
                <th className="px-4 py-3">Last Updated</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {configurations.map((c) => (
                <tr key={c.organizationId} className="border-t border-border-light">
                  <td className="px-4 py-3 font-medium text-foreground">
                    {c.organizationName} <span className="ml-1 font-mono text-xs text-foreground-disabled">{c.organizationCode}</span>
                  </td>
                  <td className="px-4 py-3 text-foreground-secondary">
                    {c.jurisdictionCountry || "—"}{c.jurisdictionState ? ` / ${c.jurisdictionState}` : ""}
                  </td>
                  <td className="px-4 py-3 text-foreground-muted">{c.compliancePack || "—"}</td>
                  <td className="px-4 py-3 text-foreground-secondary">
                    {c.activePolicyId ? `${c.activePolicyId} (v${c.activePolicyVersion})` : "— Not linked to a policy —"}
                  </td>
                  <td className="px-4 py-3">
                    <StatusPill status={c.isConfigured ? "active" : "pending"} label={c.isConfigured ? "Configured" : "Not configured"} />
                  </td>
                  <td className="px-4 py-3 text-xs text-foreground-muted">
                    {c.updatedAt ? new Date(c.updatedAt).toLocaleDateString() : "—"}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      title="Create a versioned policy from this organization's current setup"
                      onClick={() => setFormState({
                        mode: "create",
                        initial: {
                          ...emptyForm(c.jurisdictionCountry),
                          jurisdictionCountry: c.jurisdictionCountry || "IN",
                          jurisdictionState: c.jurisdictionState || "",
                          complianceCategory: c.compliancePack || "",
                        },
                      })}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs font-medium text-foreground-secondary hover:bg-surface-muted"
                    >
                      Create Policy <ArrowRight size={12} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!loading && configurations.length === 0 && (
            <div className="flex flex-col items-center justify-center gap-2 px-4 py-14 text-center">
              <Building2 size={28} className="text-border-strong" />
              <p className="text-sm text-foreground-disabled">No organization compliance configurations match these filters.</p>
            </div>
          )}
        </div>
      ) : (
      <div className="bg-surface rounded-xl shadow-sm border border-border overflow-hidden overflow-x-auto">
        <table className="w-full text-sm min-w-[900px]">
          <thead className="bg-background text-left text-xs text-foreground-muted">
            <tr>
              <th className="px-4 py-3">{tab === "taxes" ? "Tax" : "Policy"}</th>
              <th className="px-4 py-3">Jurisdiction</th>
              <th className="px-4 py-3">Category</th>
              <th className="px-4 py-3">Version</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Effective</th>
              <th className="px-4 py-3">Last Updated</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {policies.map((p) => (
              <tr key={p.id} className="border-t border-border-light">
                <td className="px-4 py-3 font-medium text-foreground">{p.packId}</td>
                <td className="px-4 py-3 text-foreground-secondary">
                  {p.jurisdictionCountry}{p.jurisdictionState ? ` / ${p.jurisdictionState}` : ""}
                </td>
                <td className="px-4 py-3 text-foreground-muted">{p.complianceCategory || "—"}</td>
                <td className="px-4 py-3 font-mono text-xs text-foreground-muted">v{p.version}</td>
                <td className="px-4 py-3">
                  <select
                    value={p.status}
                    onChange={(e) => handleStatusChange(p, e.target.value)}
                    className="rounded-md border-0 bg-transparent text-xs font-medium focus:outline-none focus:ring-1 focus:ring-focus-ring"
                  >
                    {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </td>
                <td className="px-4 py-3 text-xs text-foreground-muted">
                  {p.effectiveFrom || "—"} → {p.effectiveTo || "—"}
                </td>
                <td className="px-4 py-3 text-xs text-foreground-muted">
                  {p.updatedAt ? new Date(p.updatedAt).toLocaleDateString() : new Date(p.createdAt).toLocaleDateString()}
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-end gap-1">
                    {tab === "taxes" && (
                      <button
                        title="Edit — metadata and rates"
                        onClick={() => setFormState({
                          mode: "edit",
                          initial: {
                            ...emptyForm(p.jurisdictionCountry, p.jurisdictionState, p.packType),
                            id: p.id, packId: p.packId, version: p.version,
                            jurisdictionCountry: p.jurisdictionCountry, jurisdictionState: p.jurisdictionState || "",
                            status: p.status, effectiveFrom: p.effectiveFrom || "", effectiveTo: p.effectiveTo || "",
                            complianceCategory: p.complianceCategory || "", regulatoryAuthority: p.regulatoryAuthority || "",
                            complianceOwner: p.complianceOwner || "", engineeringOwner: p.engineeringOwner || "",
                            changeSummary: p.changeSummary || "", sourceReferences: p.sourceReferences || "",
                            nextReviewDate: p.nextReviewDate || "", policyDefaults: p.policyDefaults || {},
                          },
                        })}
                        className="rounded-lg p-1.5 text-slate-400 hover:bg-surface-muted hover:text-slate-600 dark:hover:text-foreground"
                      >
                        <Pencil size={15} />
                      </button>
                    )}
                    {tab === "taxes" && (
                      <button title="Audit history" onClick={() => setAuditPack(p)} className="rounded-lg p-1.5 text-slate-400 hover:bg-surface-muted hover:text-slate-600 dark:hover:text-foreground">
                        <ScrollText size={15} />
                      </button>
                    )}
                    <button title="Version history" onClick={() => openHistory(p)} className="rounded-lg p-1.5 text-slate-400 hover:bg-surface-muted hover:text-slate-600 dark:hover:text-foreground">
                      <History size={15} />
                    </button>
                    <button
                      title={tab === "taxes" ? "Apply to organizations — syncs rates" : "Assign to organizations"}
                      onClick={() => openAssign(p)}
                      className="rounded-lg p-1.5 text-slate-400 hover:bg-surface-muted hover:text-slate-600 dark:hover:text-foreground"
                    >
                      <UsersIcon size={15} />
                    </button>
                    <button
                      title="Create new version"
                      onClick={() => setFormState({
                        mode: "newVersion",
                        initial: {
                          ...emptyForm(p.jurisdictionCountry, p.jurisdictionState, p.packType),
                          packId: p.packId, jurisdictionCountry: p.jurisdictionCountry, jurisdictionState: p.jurisdictionState || "",
                          complianceCategory: p.complianceCategory || "", regulatoryAuthority: p.regulatoryAuthority || "",
                          complianceOwner: p.complianceOwner || "", engineeringOwner: p.engineeringOwner || "",
                          policyDefaults: p.policyDefaults || {},
                          version: "", status: "Draft",
                        },
                      })}
                      className="rounded-lg p-1.5 text-slate-400 hover:bg-surface-muted hover:text-slate-600 dark:hover:text-foreground"
                    >
                      <GitBranch size={15} />
                    </button>
                    {p.status !== "Retired" && (
                      <button
                        title="Delete (archives — sets status to Retired, keeps full history)"
                        onClick={() => setArchiving(p)}
                        className="rounded-lg p-1.5 text-slate-400 hover:bg-red-50 dark:hover:bg-red-950/40 hover:text-red-500"
                      >
                        <Trash2 size={15} />
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && policies.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 px-4 py-14 text-center">
            <Building2 size={28} className="text-border-strong" />
            <p className="text-sm text-foreground-disabled">
              No {tab === "taxes" ? "taxes" : "policies"} found for {selectedJurisdiction.name}
              {selectedState ? ` / ${selectedState}` : ""} yet.
            </p>
          </div>
        )}
      </div>
      )}
      </>
      )}

      {formState && (
        <PolicyFormModal
          mode={formState.mode}
          initial={formState.initial}
          onClose={() => setFormState(null)}
          onSaved={() => { setFormState(null); load(); }}
        />
      )}
      {historyState && (
        <VersionHistoryModal packId={historyState.packId} versions={historyState.versions} onClose={() => setHistoryState(null)} />
      )}
      {auditPack && (
        <AuditHistoryModal pack={auditPack} onClose={() => setAuditPack(null)} />
      )}
      {assignState && (
        <AssignOrgsModal
          policy={assignState.policy}
          orgs={assignState.orgs}
          assignedOrgIds={assignState.assignedOrgIds}
          setAssignedOrgIds={(updater) => setAssignState((s) => ({ ...s, assignedOrgIds: typeof updater === "function" ? updater(s.assignedOrgIds) : updater }))}
          saving={assignState.saving}
          onClose={() => setAssignState(null)}
          onSave={handleAssignSave}
        />
      )}
      {archiving && (
        <ConfirmDialog
          title={`Delete ${archiving.packType === "tax" ? "Tax" : "Policy"} — ${archiving.packId}`}
          message={
            `This sets "${archiving.packId}" (v${archiving.version}) to Retired. It stops appearing as an active ` +
            `${archiving.packType === "tax" ? "tax" : "policy"}, but its full record and version history are kept ` +
            `— nothing is erased, and any organization still assigned to it keeps their current configuration until ` +
            `reassigned. You can un-retire it later from the status dropdown.`
          }
          confirmLabel="Delete"
          busy={archiveBusy}
          onConfirm={handleArchiveConfirm}
          onClose={() => setArchiving(null)}
        />
      )}
    </div>
  );
}
