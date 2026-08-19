// Shared between CompliancePage.jsx's Tax modal and PolicyConfigPage.jsx's
// full-page Policy configuration — extracted so both consume the exact same
// field taxonomy/lock-node helpers instead of two copies drifting apart.
import { Lock, Unlock } from "lucide-react";

export const STATUS_OPTIONS = ["Draft", "In Review", "QA", "Approved", "Active", "Deprecated", "Retired"];
export const STATUS_PILL_MAP = {
  Active: "active", Approved: "approved", Draft: "pending", "In Review": "pending",
  QA: "pending", Deprecated: "inactive", Retired: "suspended",
};

export const inputClass =
  "w-full rounded-lg border border-border-strong bg-background px-3 py-2.5 text-sm text-foreground shadow-sm " +
  "transition-colors placeholder:text-foreground-disabled hover:border-primary/50 focus:border-primary " +
  "focus:outline-none focus:ring-2 focus:ring-focus-ring/30 disabled:cursor-not-allowed disabled:border-border-light " +
  "disabled:bg-surface-muted disabled:text-foreground-disabled disabled:shadow-none";
export const labelClass = "mb-1.5 block text-xs font-medium text-foreground-muted";

// Same visual language as inputClass, sized down for compact card-level
// controls (LockableField's value input, AllowanceComponentRow's cells) —
// full-size inputClass reads oversized once several of these sit inside a
// small bordered row.
export const compactInputClass =
  "w-full rounded-md border border-border-strong bg-background px-2.5 py-1.5 text-xs text-foreground shadow-sm " +
  "transition-colors placeholder:text-foreground-disabled hover:border-primary/50 focus:border-primary " +
  "focus:outline-none focus:ring-2 focus:ring-focus-ring/30";

export function emptyForm(country, state, packType) {
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
// overtime_rule / allowance_components fields Organization Admin already edits.
export const CATEGORY_KEYS = ["full_time", "part_time", "intern", "contract", "consultant", "freelancer"];
export const CATEGORY_FIELDS = [
  { key: "working_days", label: "Working Days", type: "number" },
  { key: "expected_hours", label: "Expected Hours", type: "number" },
  { key: "minimum_hours", label: "Minimum Hours", type: "number" },
  { key: "paid_leave_eligible", label: "Paid Leave Eligible", type: "boolean" },
];
export const OVERTIME_FIELDS = [
  { key: "enabled", label: "Overtime Enabled", type: "boolean" },
  { key: "minimum_overtime_minutes", label: "Minimum OT Minutes", type: "number" },
  { key: "approval_required", label: "Approval Required", type: "boolean" },
];

// Admin types a display label ("Transport Allowance"); the machine-readable
// key it's stored/matched under is derived from that, same idea as
// employee_code auto-generation elsewhere in this app — one less field for
// the admin to fill in, and no risk of two components colliding on a
// hand-typed slug.
export function slugify(label) {
  return (
    (label || "")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "") || "component"
  );
}

export function getLockNode(policyDefaults, path) {
  let node = policyDefaults;
  for (const key of path) {
    if (!node || typeof node !== "object") return {};
    node = node[key];
  }
  return node && typeof node === "object" ? node : {};
}

export function setLockNode(setForm, path, patch) {
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

// A default value (this pack's own suggestion) plus an independent
// "Allow override" flag (whether an assigned organization may replace that
// value). The two are unrelated to each other's editability — Super Admin
// can always edit the value here regardless of the lock state, since the
// lock only governs what an ORGANIZATION can later do with it — so the
// value control is never disabled by allowOverride, only visually paired
// with a lock/unlock indicator for the flag next to it.
export function LockableField({ label, node, type, choices, onChangeValue, onChangeAllow }) {
  const value = node.value;
  const allowOverride = node.allowOverride !== false;
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2.5">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-foreground-secondary">{label}</span>
        <label
          className="flex cursor-pointer select-none items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium whitespace-nowrap"
          style={
            allowOverride
              ? { background: "var(--color-success-light)", color: "var(--color-success)" }
              : { background: "var(--color-surface-muted)", color: "var(--color-foreground-muted)" }
          }
          title={allowOverride ? "Organizations may override this value" : "Locked — organizations must keep this value"}
        >
          <input
            type="checkbox"
            checked={allowOverride}
            onChange={(e) => onChangeAllow(e.target.checked)}
            className="sr-only"
          />
          {allowOverride ? <Unlock size={10} /> : <Lock size={10} />}
          {allowOverride ? "Overridable" : "Locked"}
        </label>
      </div>
      {type === "select" ? (
        <select value={value ?? ""} onChange={(e) => onChangeValue(e.target.value || null)} className={compactInputClass}>
          <option value="">No default</option>
          {choices.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </select>
      ) : type === "boolean" ? (
        <select
          value={value === true ? "true" : value === false ? "false" : ""}
          onChange={(e) => onChangeValue(e.target.value === "" ? null : e.target.value === "true")}
          className={compactInputClass}
        >
          <option value="">No default</option>
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>
      ) : (
        <input
          type="number"
          min={0}
          value={value ?? ""}
          onChange={(e) => onChangeValue(e.target.value === "" ? null : Number(e.target.value))}
          placeholder="No default"
          className={compactInputClass}
        />
      )}
    </div>
  );
}
