// Shared between CompliancePage.jsx's Tax modal and PolicyConfigPage.jsx's
// full-page Policy configuration — extracted so both consume the exact same
// field taxonomy/lock-node helpers instead of two copies drifting apart.
export const STATUS_OPTIONS = ["Draft", "In Review", "QA", "Approved", "Active", "Deprecated", "Retired"];
export const STATUS_PILL_MAP = {
  Active: "active", Approved: "approved", Draft: "pending", "In Review": "pending",
  QA: "pending", Deprecated: "inactive", Retired: "suspended",
};

export const inputClass =
  "w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-focus-ring/40";
export const labelClass = "block text-xs font-medium text-foreground-muted mb-1";

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

export function LockableField({ label, node, type, choices, onChangeValue, onChangeAllow }) {
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
