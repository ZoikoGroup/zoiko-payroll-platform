import { COUNTRY_OPTIONS } from "../../../../utils/currency";

// Payslips store the UK as "UK" (not ISO "GB"); the backend accepts both.
export const TEMPLATE_COUNTRIES = COUNTRY_OPTIONS
  .map((c) => ({ code: c.code === "GB" ? "UK" : c.code, name: c.name }))
  .sort((a, b) => a.name.localeCompare(b.name));

export function countryLabel(code) {
  if (!code || code === "ALL") return "All countries";
  const hit = TEMPLATE_COUNTRIES.find((c) => c.code === code);
  return hit ? `${hit.name} (${code})` : code;
}
