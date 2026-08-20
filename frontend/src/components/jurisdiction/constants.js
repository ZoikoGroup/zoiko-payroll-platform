// Shared across every Jurisdiction Compliance page (all six countries) —
// extracted verbatim from the old monolithic CompliancePage.jsx, zero
// behavior change.
export const STATUS_PILL_MAP = { Active: "active", Draft: "pending", "In Review": "pending", QA: "pending", Approved: "pending", Deprecated: "inactive", Retired: "suspended" };
export const STATUS_OPTIONS = ["Draft", "In Review", "QA", "Approved", "Active", "Deprecated", "Retired"];
export const inputClass = "w-full rounded-lg border border-border-strong bg-background px-3 py-2 text-sm text-foreground shadow-sm focus:outline-none focus:ring-2 focus:ring-focus-ring/30";
export const labelClass = "mb-1.5 block text-xs font-medium text-foreground-muted";
export const PACK_TABS = [
  { key: "tax", label: "Tax" },
  { key: "policy", label: "Policy" },
];
