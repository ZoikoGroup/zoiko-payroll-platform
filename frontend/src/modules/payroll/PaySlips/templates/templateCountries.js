import { getCountryNameFromCode } from "../../../../utils/currency";

// Countries come from the backend (GET /payslip-templates -> countries): only
// the organisation's own payroll countries can be chosen for a template.
export function countryLabel(code, countries = []) {
  if (!code || code === "ALL") return "All countries";
  const hit = countries.find((c) => c.code === code);
  const name = hit?.name || getCountryNameFromCode(code) || code;
  return name === code ? code : `${name} (${code})`;
}
