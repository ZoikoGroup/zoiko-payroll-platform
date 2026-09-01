export { default as INReportTemplatesPage } from "./INReportTemplatesPage";
export { default as UKReportTemplatesPage } from "./UKReportTemplatesPage";
export { default as USAReportTemplatesPage } from "./USAReportTemplatesPage";

// Phase 2: UK and USA added. AU/CA/DE get their own thin wrapper pages
// here in a later phase, following the exact same pattern (see
// JurisdictionCompliance/index.js's COUNTRY_CODE_TO_ROUTE for the
// precedent this mirrors once they exist) — the backend's field/component
// catalogs are already jurisdiction-agnostic (see service.py's
// _PAYSLIP_FIELDS_BY_COUNTRY/_REPORT_COMPONENTS_BY_TYPE), so adding a new
// country here never requires a backend change, only this page + route.
export const COUNTRY_CODE_TO_ROUTE = {
  IN: "india",
  UK: "united-kingdom",
  US: "united-states",
};
