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

// Unit of ContributionRate.employee_rate_pct / employer_rate_pct per country.
// Most engines store a percentage NUMBER (6.2 = 6.2 %: US, UK, CA, AU, FR,
// BE, ...). These engines store a FRACTION (0.062 = 6.2 %) — their defaults
// in backend engine/countries/<country>.py are fractions and the value is
// multiplied in without /100. Display only: stored values are never changed.
export const FRACTION_RATE_COUNTRIES = ["PR", "BS", "BB", "KY", "DO", "GY", "JM"];

// "0.0620" -> "6.2" by moving the decimal point two places (string-based, so
// no floating-point noise such as 6.200000000000001).
function fractionToPercent(value) {
  const match = /^(-?)(\d*)(?:\.(\d*))?$/.exec(String(value).trim());
  if (!match) return String(Number((Number(value) * 100).toPrecision(12)));
  const [, sign, int = "", frac = ""] = match;
  const padded = frac.padEnd(2, "0");
  const whole = `${int}${padded.slice(0, 2)}`.replace(/^0+(?=\d)/, "") || "0";
  const rest = padded.slice(2).replace(/0+$/, "");
  return `${sign}${whole}${rest ? `.${rest}` : ""}`;
}

// A contribution rate as shown in the Contribution Rates table.
export function formatContributionRate(value, country) {
  if (value == null || value === "") return "—";
  return FRACTION_RATE_COUNTRIES.includes(String(country || "").toUpperCase()) ? `${fractionToPercent(value)}%` : `${value}%`;
}
