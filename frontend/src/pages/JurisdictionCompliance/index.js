export { default as INCompliancePage } from "./INCompliancePage";
export { default as USACompliancePage } from "./USACompliancePage";
export { default as UKCompliancePage } from "./UKCompliancePage";
export { default as AUCompliancePage } from "./AUCompliancePage";
export { default as CACompliancePage } from "./CACompliancePage";
export { default as DECompliancePage } from "./DECompliancePage";
// Caribbean production jurisdictions (2026-09-21).
export { default as BBCompliancePage } from "./BBCompliancePage";
export { default as KYCompliancePage } from "./KYCompliancePage";
export { default as DOCompliancePage } from "./DOCompliancePage";
export { default as GYCompliancePage } from "./GYCompliancePage";
export { default as JMCompliancePage } from "./JMCompliancePage";
export { default as BSCompliancePage } from "./BSCompliancePage";
export { default as TTCompliancePage } from "./TTCompliancePage";
export { default as PRCompliancePage } from "./PRCompliancePage";
export { default as FRCompliancePage } from "./FRCompliancePage";
export { default as IECompliancePage } from "./IECompliancePage";

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
  BB: "barbados",
  KY: "cayman-islands",
  DO: "dominican-republic",
  GY: "guyana",
  JM: "jamaica",
  BS: "bahamas",
  TT: "trinidad-and-tobago",
  PR: "puerto-rico",
  FR: "france",
  IE: "ireland",
};
