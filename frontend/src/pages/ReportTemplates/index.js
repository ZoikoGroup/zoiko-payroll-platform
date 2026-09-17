export { default as INReportTemplatesPage } from "./INReportTemplatesPage";
export { default as UKReportTemplatesPage } from "./UKReportTemplatesPage";
export { default as USAReportTemplatesPage } from "./USAReportTemplatesPage";
export { default as CAReportTemplatesPage } from "./CAReportTemplatesPage";
export { default as AUReportTemplatesPage } from "./AUReportTemplatesPage";

// Phase 2: UK and USA added. Phase 8: CA added (service.py's
// _PAYSLIP_FIELDS_BY_COUNTRY now has a real "CA" entry rather than
// falling back to the generic default list). AU added 2026-09-17 (10 real
// templates — STP/SuperStream/8 state payroll-tax-returns — seeded,
// Active, and live-verified against real payslip data). DE still gets its
// own thin wrapper page in a later phase, once its backend exists,
// following the exact same pattern (see JurisdictionCompliance/index.js's
// COUNTRY_CODE_TO_ROUTE for the precedent this mirrors).
export const COUNTRY_CODE_TO_ROUTE = {
  IN: "india",
  UK: "united-kingdom",
  US: "united-states",
  CA: "canada",
  AU: "australia",
};
