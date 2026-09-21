export { default as INReportTemplatesPage } from "./INReportTemplatesPage";
export { default as UKReportTemplatesPage } from "./UKReportTemplatesPage";
export { default as USAReportTemplatesPage } from "./USAReportTemplatesPage";
export { default as CAReportTemplatesPage } from "./CAReportTemplatesPage";
export { default as AUReportTemplatesPage } from "./AUReportTemplatesPage";
export { default as DEReportTemplatesPage } from "./DEReportTemplatesPage";

// Phase 2: UK and USA added. Phase 8: CA added (service.py's
// _PAYSLIP_FIELDS_BY_COUNTRY now has a real "CA" entry rather than
// falling back to the generic default list). AU added 2026-09-17 (10 real
// templates — STP/SuperStream/8 state payroll-tax-returns — seeded,
// Active, and live-verified against real payslip data). DE added
// (Lohnsteuerbescheinigung per-employee + a Payroll Summary aggregate,
// scripts/seed_statutory_report_templates.py) — same thin wrapper
// pattern as every other jurisdiction above, no Germany-specific UI.
export const COUNTRY_CODE_TO_ROUTE = {
  IN: "india",
  UK: "united-kingdom",
  US: "united-states",
  CA: "canada",
  AU: "australia",
  DE: "germany",
};
