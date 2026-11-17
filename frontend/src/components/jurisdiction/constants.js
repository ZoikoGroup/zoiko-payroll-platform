// Shared across every Jurisdiction Compliance page (all six countries) —
// extracted verbatim from the old monolithic CompliancePage.jsx, zero
// behavior change.
// "Superseded" is a real tax-pack status in the backend (TAX_PACK_TRANSITIONS);
// without it here a Superseded pack showed as "Draft" in the status dropdown.
export const STATUS_PILL_MAP = { Active: "active", Draft: "pending", "In Review": "pending", QA: "pending", Approved: "pending", Deprecated: "inactive", Superseded: "inactive", Retired: "suspended" };
export const STATUS_OPTIONS = ["Draft", "In Review", "QA", "Approved", "Active", "Deprecated", "Superseded", "Retired"];

// The pack a jurisdiction page opens on when the country does not choose
// its own: the Active pack in force today, else any Active pack. Pages used
// to open on "No tax pack selected" even when an Active pack existed.
export function pickActivePack(packs) {
  const today = new Date().toISOString().slice(0, 10);
  const active = (packs || []).filter((p) => p.status === "Active");
  return active.find((p) => (!p.effectiveFrom || p.effectiveFrom <= today) && (!p.effectiveTo || p.effectiveTo >= today))
    || active[0] || null;
}

// Next version not already used: "1.0" -> "1.1", "2.3" -> "2.4"; "" when the
// version is not a number (the user types it).
export function nextPackVersion(version, existing = []) {
  const match = /^(\d+)(?:\.(\d+))?$/.exec(String(version || "").trim());
  if (!match) return "";
  const major = Number(match[1]);
  let minor = Number(match[2] || 0) + 1;
  while (existing.includes(`${major}.${minor}`)) minor += 1;
  return `${major}.${minor}`;
}
// Policy packs use only Draft | Active (no review/approval stage) — the Tax
// statuses above stay in STATUS_OPTIONS for Tax packs only. Both values are
// enforced server-side; these lists just drive the dropdown rendering.
export const POLICY_STATUS_OPTIONS = ["Draft", "Active"];
export const inputClass = "w-full rounded-lg border border-border-strong bg-background px-3 py-2 text-sm text-foreground shadow-sm focus:outline-none focus:ring-2 focus:ring-focus-ring/30";
export const labelClass = "mb-1.5 block text-xs font-medium text-foreground-muted";
export const PACK_TABS = [
  { key: "tax", label: "Tax" },
  { key: "policy", label: "Policy" },
];
