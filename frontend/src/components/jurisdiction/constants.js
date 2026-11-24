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
// multiplied in without /100. The UI always shows and accepts a percentage;
// for these countries it converts on display and on save, so stored values
// stay fractions.
export const FRACTION_RATE_COUNTRIES = ["PR", "BS", "BB", "KY", "DO", "GY", "JM"];
export const isFractionRateCountry = (country) => FRACTION_RATE_COUNTRIES.includes(String(country || "").toUpperCase());

const DECIMAL = /^(-?)(\d*)(?:\.(\d*))?$/;
const tidy = (sign, whole, rest) => {
  const w = whole.replace(/^0+(?=\d)/, "") || "0";
  const r = rest.replace(/0+$/, "");
  return `${sign}${w}${r ? `.${r}` : ""}`;
};

// "0.0620" -> "6.2": the decimal point moves two places right (string-based,
// so no floating-point noise such as 6.200000000000001).
function fractionToPercent(value) {
  const match = DECIMAL.exec(String(value).trim());
  if (!match) return String(Number((Number(value) * 100).toPrecision(12)));
  const [, sign, int = "", frac = ""] = match;
  const padded = frac.padEnd(2, "0");
  return tidy(sign, `${int}${padded.slice(0, 2)}`, padded.slice(2));
}

// "6.2" -> "0.062": the decimal point moves two places left. Text that is not
// a plain decimal is returned as typed, for the backend to refuse.
function percentToFraction(value) {
  const text = String(value).trim();
  const match = DECIMAL.exec(text);
  if (!match || text === "" || text === "-" || text === ".") return text;
  const [, sign, int = "", frac = ""] = match;
  const padded = int.padStart(2, "0");
  return tidy(sign, padded.slice(0, -2), `${padded.slice(-2)}${frac}`);
}

// Stored rate -> the percentage number shown in the table and the edit form.
export function rateToPercent(value, country) {
  if (value == null || value === "") return "";
  return isFractionRateCountry(country) ? fractionToPercent(value) : String(value);
}

// Percentage typed in the edit form -> the value to store ("" stays "").
export function percentToRate(value, country) {
  if (value == null || String(value).trim() === "") return "";
  return isFractionRateCountry(country) ? percentToFraction(value) : value;
}

// Warnings for a percentage typed in the edit form (empty list = fine). Never
// blocks a save on its own; the form asks for confirmation.
export function ratePercentWarnings(value, country) {
  const text = String(value ?? "").trim();
  if (text === "") return [];
  if (!DECIMAL.test(text)) return ["Enter a number, e.g. 6.2 for 6.2 %."];
  const warnings = [];
  if (Number(text) > 100) warnings.push("Over 100 % — check this is a percentage, not an amount.");
  if (Number(text) < 0) warnings.push("Negative rate.");
  // Rates are stored with 4 decimals; as a fraction that is 2 decimals of a percentage.
  const decimals = (text.split(".")[1] || "").length;
  if (decimals > (isFractionRateCountry(country) ? 2 : 4)) {
    warnings.push(`Rates are stored to ${isFractionRateCountry(country) ? 2 : 4} decimal places of a percentage — this will be rounded.`);
  }
  return warnings;
}

// A contribution rate as shown in the Contribution Rates table.
export function formatContributionRate(value, country) {
  if (value == null || value === "") return "—";
  return `${rateToPercent(value, country)}%`;
}
