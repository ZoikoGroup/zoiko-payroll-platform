export { default as INReportTemplatesPage } from "./INReportTemplatesPage";
export { default as UKReportTemplatesPage } from "./UKReportTemplatesPage";
export { default as USAReportTemplatesPage } from "./USAReportTemplatesPage";
export { default as CAReportTemplatesPage } from "./CAReportTemplatesPage";
export { default as AUReportTemplatesPage } from "./AUReportTemplatesPage";
// Caribbean 7 (2026-09-22, Group D gap-closure) — one seeded PER_EMPLOYEE
// statutory pay-component template each (service.py's
// _PAYSLIP_FIELDS_BY_COUNTRY + _REPORT_COMPONENTS_BY_TYPE), same pattern
// as every country above.
export { default as BBReportTemplatesPage } from "./BBReportTemplatesPage";
export { default as KYReportTemplatesPage } from "./KYReportTemplatesPage";
export { default as DOReportTemplatesPage } from "./DOReportTemplatesPage";
export { default as GYReportTemplatesPage } from "./GYReportTemplatesPage";
export { default as JMReportTemplatesPage } from "./JMReportTemplatesPage";
export { default as BSReportTemplatesPage } from "./BSReportTemplatesPage";
export { default as TTReportTemplatesPage } from "./TTReportTemplatesPage";
export { default as DEReportTemplatesPage } from "./DEReportTemplatesPage";

// Phase 2: UK and USA added. Phase 8: CA added (service.py's
// _PAYSLIP_FIELDS_BY_COUNTRY now has a real "CA" entry rather than
// falling back to the generic default list). AU added 2026-09-17 (10 real
// templates — STP/SuperStream/8 state payroll-tax-returns — seeded,
// Active, and live-verified against real payslip data). Caribbean 7 added
// 2026-09-22 (one seeded Draft template each — see seed_statutory_report_
// templates.py). DE added (Lohnsteuerbescheinigung per-employee + a
// Payroll Summary aggregate, scripts/seed_statutory_report_templates.py)
// — same thin wrapper pattern as every other jurisdiction above, no
// Germany-specific UI.
export const COUNTRY_CODE_TO_ROUTE = {
  IN: "india",
  UK: "united-kingdom",
  US: "united-states",
  CA: "canada",
  AU: "australia",
  BB: "barbados",
  KY: "cayman-islands",
  DO: "dominican-republic",
  GY: "guyana",
  JM: "jamaica",
  BS: "bahamas",
  TT: "trinidad-and-tobago",
  DE: "germany",
};
