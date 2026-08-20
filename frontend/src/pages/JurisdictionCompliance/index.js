export { default as INCompliancePage } from "./INCompliancePage";
export { default as USACompliancePage } from "./USACompliancePage";
export { default as UKCompliancePage } from "./UKCompliancePage";
export { default as AUCompliancePage } from "./AUCompliancePage";
export { default as CACompliancePage } from "./CACompliancePage";
export { default as DECompliancePage } from "./DECompliancePage";

// Single source of truth for the route-slug naming — used by App.jsx (to
// define the routes) and the CompliancePage.jsx landing page (to link to
// them), so the two can never drift apart.
export const COUNTRY_CODE_TO_ROUTE = {
  IN: "india",
  US: "united-states",
  UK: "united-kingdom",
  AU: "australia",
  CA: "canada",
  DE: "germany",
};
