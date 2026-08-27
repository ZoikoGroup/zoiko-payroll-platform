// Field taxonomy/lock-node helpers for the Super Admin Policy module
// (frontend/src/pages/PolicyModule/). Moved from the old, single-page
// policyFormShared.jsx as part of splitting Policy authoring into
// per-jurisdiction pages (INPolicyPage.jsx, USPolicyPage.jsx, ...), mirroring
// how frontend/src/config/jurisdictions/*.jsx already does this for the Tax
// side. Every export here is unchanged in behavior from policyFormShared.jsx
// — this file is a relocation, not a rewrite.
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
//
// These are the DEFAULT (shared) field lists every jurisdiction page uses
// unless it explicitly overrides one via its own config — see
// PolicyLayout.jsx's `categoryFields`/`overtimeFields`/`payTypeChoices`
// props. No jurisdiction overrides any of these today (no real per-country
// policy divergence exists in the backend yet), so every page currently
// renders identically — the override slot exists so a future
// jurisdiction-specific field can be added to ONE country's file without
// touching this shared default or any other country's file.
export const CATEGORY_KEYS = ["full_time", "part_time", "intern", "contract", "consultant", "freelancer"];
export const DEFAULT_CATEGORY_FIELDS = [
  { key: "working_days", label: "Working Days", type: "number" },
  // Label only — the stored key stays "expected_hours" on purpose. The
  // Org Admin side (PayrollPolicyPage.jsx) reads this exact key for its
  // own lock/inheritance display and isn't part of this relabel.
  { key: "expected_hours", label: "Minimum Weekly Working Hours", type: "number" },
  { key: "minimum_hours", label: "Minimum Hours", type: "number" },
  { key: "paid_leave_eligible", label: "Paid Leave Eligible", type: "boolean" },
];
export const DEFAULT_OVERTIME_FIELDS = [
  { key: "enabled", label: "Overtime Enabled", type: "boolean" },
  { key: "minimum_overtime_minutes", label: "Minimum OT Minutes", type: "number" },
  { key: "approval_required", label: "Approval Required", type: "boolean" },
];

// "Pay Type" — additive policyDefaults key alongside Calculation Mode, same
// LockableField/Overridable pattern. Not wired into any calculation yet
// (out of scope) — the existing PayrollEmployee.pay_frequency field used by
// the UK engine calculator is a separate, already-consumed concept,
// deliberately not reused here to avoid conflating the two.
export const DEFAULT_PAY_TYPE_CHOICES = [
  { value: "Monthly", label: "Monthly" },
  { value: "Weekly", label: "Weekly" },
  { value: "Biweekly", label: "Biweekly" },
  { value: "Hourly", label: "Hourly" },
  { value: "Daily", label: "Daily" },
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
