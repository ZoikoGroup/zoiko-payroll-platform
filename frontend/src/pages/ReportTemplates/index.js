export { default as INReportTemplatesPage } from "./INReportTemplatesPage";
export { default as UKReportTemplatesPage } from "./UKReportTemplatesPage";
export { default as USAReportTemplatesPage } from "./USAReportTemplatesPage";
export { default as CAReportTemplatesPage } from "./CAReportTemplatesPage";
export { default as AUReportTemplatesPage } from "./AUReportTemplatesPage";
export { default as NLReportTemplatesPage } from "./NLReportTemplatesPage";
export { default as MXReportTemplatesPage } from "./MXReportTemplatesPage";
export { default as BRReportTemplatesPage } from "./BRReportTemplatesPage";
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
export { default as PRReportTemplatesPage } from "./PRReportTemplatesPage";
// Ireland (ZP-IE-ENG-001) — ROS (Revenue Online System) per-employee
// certificate plus the three ROS report types Revenue's ROS requires for a
// period. Same thin wrapper pattern as every other jurisdiction above.
export { default as IEReportTemplatesPage } from "./IEReportTemplatesPage";
// Singapore (final closure) — the 11 SG templates in the shared lifecycle module.
export { default as SGReportTemplatesPage } from "./SGReportTemplatesPage";
// Hong Kong (ZP-HK-ENG-001) — same thin wrapper; no authority file layout seeded (G2).
export { default as HKReportTemplatesPage } from "./HKReportTemplatesPage";
// Sweden (ZP-SE-ENG-001) — AGI individual-statement data extract.
export { default as SEReportTemplatesPage } from "./SEReportTemplatesPage";
// Switzerland (ZP-CH-PAYROLL-001) — per-employee Lohnausweis + ELM envelopes.
export { default as CHReportTemplatesPage } from "./CHReportTemplatesPage";
// BE / FR / IT / JP / MY / NZ / PL / SA / ZA — previously "Coming soon". Same
// thin wrapper; their templates are seeded Draft by
// scripts/seed_statutory_report_templates.py and activate only through each
// jurisdiction's template_activation_refusal gate.
export { default as BEReportTemplatesPage } from "./BEReportTemplatesPage";
export { default as FRReportTemplatesPage } from "./FRReportTemplatesPage";
export { default as ITReportTemplatesPage } from "./ITReportTemplatesPage";
export { default as JPReportTemplatesPage } from "./JPReportTemplatesPage";
export { default as MYReportTemplatesPage } from "./MYReportTemplatesPage";
export { default as NZReportTemplatesPage } from "./NZReportTemplatesPage";
export { default as PLReportTemplatesPage } from "./PLReportTemplatesPage";
export { default as SAReportTemplatesPage } from "./SAReportTemplatesPage";
export { default as ZAReportTemplatesPage } from "./ZAReportTemplatesPage";
export { default as AEReportTemplatesPage } from "./AEReportTemplatesPage";

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
  PR: "puerto-rico",
  IE: "ireland",
  SG: "singapore",
  HK: "hong-kong",
  SE: "sweden",
  CH: "switzerland",
  NL: "netherlands",
  MX: "mexico",
  BR: "brazil",
  BE: "belgium",
  FR: "france",
  IT: "italy",
  JP: "japan",
  MY: "malaysia",
  NZ: "new-zealand",
  PL: "poland",
  SA: "saudi-arabia",
  ZA: "south-africa",
  AE: "united-arab-emirates",
};
