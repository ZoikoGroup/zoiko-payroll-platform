export { default as INReportTemplatesPage } from "./INReportTemplatesPage";
export { default as UKReportTemplatesPage } from "./UKReportTemplatesPage";
export { default as USAReportTemplatesPage } from "./USAReportTemplatesPage";
export { default as CAReportTemplatesPage } from "./CAReportTemplatesPage";

// Phase 2: UK and USA added. Phase 8: CA added (service.py's
// _PAYSLIP_FIELDS_BY_COUNTRY now has a real "CA" entry rather than
// falling back to the generic default list). AU/DE get their own thin
// wrapper pages here in a later phase, following the exact same pattern
// (see JurisdictionCompliance/index.js's COUNTRY_CODE_TO_ROUTE for the
// precedent this mirrors once they exist).
export const COUNTRY_CODE_TO_ROUTE = {
  IN: "india",
  UK: "united-kingdom",
  US: "united-states",
  CA: "canada",
};
