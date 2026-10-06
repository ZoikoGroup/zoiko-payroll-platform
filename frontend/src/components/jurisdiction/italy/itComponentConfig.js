// Italy (ZP-IT-ENG-001) — which canonical ContributionRate keys and TaxSlab
// rule types each Super Admin tab shows. Mirrors backend
// engine/countries/italy_content.py; a key missing from a pack is listed by
// the tab (the engine blocks on it), never defaulted here.

// §6/§7 INPS: thresholds, the contributory minimum and FIS. The IVS/CIGS
// rates themselves are classification-scoped matrix rows (ITInpsMatrixTab).
export const IT_INPS_KEYS = [
  "it_ivs_additional_pct", "it_ivs_additional_threshold", "it_contributory_ceiling",
  "it_inps_daily_minimum", "it_inps_full_month_days", "it_inps_parttime_hourly_factor",
  "it_fis_small_employer", "it_fis_large_employer",
];

// §3/§4/§5 withholding parameters (the bands live in ITBandsTab).
export const IT_TAX_KEYS = [
  "it_mensilita_default", "it_detrazione_min_permanent", "it_detrazione_min_fixed_term",
  "it_wedge_recovery_threshold", "it_wedge_recovery_instalments",
  "it_addreg_saldo_first_month", "it_addreg_saldo_last_month",
  "it_addcom_saldo_first_month", "it_addcom_saldo_last_month",
  "it_addcom_acconto_pct", "it_addcom_acconto_first_month", "it_addcom_acconto_last_month",
];

// §13/§14 TFR and the Fondo Tesoreria threshold.
export const IT_TFR_KEYS = [
  "it_tfr_divisor", "it_tfr_inps_offset", "it_tesoreria_headcount_threshold",
  "it_tfr_revaluation_fixed_pct", "it_tfr_revaluation_istat_share", "it_tfr_revaluation_tax_pct",
];

// §11 fringe-benefit and meal-voucher thresholds.
export const IT_BENEFIT_KEYS = [
  "it_fringe_exempt_limit", "it_fringe_exempt_limit_children", "it_meal_electronic_exempt", "it_meal_paper_exempt",
];

export const IT_GROUPED_KEYS = new Set([...IT_INPS_KEYS, ...IT_TAX_KEYS, ...IT_TFR_KEYS, ...IT_BENEFIT_KEYS]);

// §7 matrix rows are scoped "CSC_<csc>" or "CSC_<csc>_CA_<ca>".
export const isMatrixRow = (r) => (r.jurisdictionState || "").startsWith("CSC_");
export const IT_MATRIX_FAMILIES = ["it_inps_ivs", "it_inps_cigs"];

// TaxSlab rule types. `value` says which column carries the figure:
// "rate" → ratePct (a percentage), "amount" → flatAmount (EUR).
// `table` says how tax_table_number is chosen: a fixed national code, or the
// tax-domicile REGION (ISTAT code) / COMUNE (cadastral code).
export const IT_BAND_RULES = [
  { rule: "IT_IRPEF_BRACKET", label: "IRPEF brackets (§3)", value: "rate", table: "national", group: "national" },
  { rule: "IT_DETR_FIXED", label: "Detrazione lavoro — fixed part (§4)", value: "amount", table: "national", group: "national" },
  { rule: "IT_DETR_TAPER", label: "Detrazione lavoro — tapering part (§4)", value: "amount", table: "national", group: "national" },
  { rule: "IT_ADDL_DED_FIXED", label: "Wedge additional deduction — fixed part (§4)", value: "amount", table: "national", group: "national" },
  { rule: "IT_ADDL_DED_TAPER", label: "Wedge additional deduction — tapering part (§4)", value: "amount", table: "national", group: "national" },
  { rule: "IT_WEDGE_SUM", label: "Wedge non-taxable sum (§4)", value: "rate", table: "national", group: "national" },
  { rule: "IT_ADDREG", label: "Regional surtax brackets (§5)", value: "rate", table: "region", group: "local" },
  { rule: "IT_ADDREG_EXEMPT", label: "Regional surtax exemption threshold (§5)", value: "amount", table: "region", group: "local" },
  { rule: "IT_ADDCOM", label: "Municipal surtax brackets (§5)", value: "rate", table: "comune", group: "local" },
  { rule: "IT_ADDCOM_EXEMPT", label: "Municipal surtax exemption threshold (§5)", value: "amount", table: "comune", group: "local" },
];
export const ruleMeta = (rule) => IT_BAND_RULES.find((r) => r.rule === rule);

export const REGION_TABLE_PREFIX = "REG_";
export const COMUNE_TABLE_PREFIX = "COM_";

// ISTAT region codes (mirrors italy_content.IT_REGIONS).
export const IT_REGIONS = [
  ["01", "Piemonte"], ["02", "Valle d'Aosta"], ["03", "Lombardia"], ["04", "Trentino-Alto Adige"],
  ["05", "Veneto"], ["06", "Friuli-Venezia Giulia"], ["07", "Liguria"], ["08", "Emilia-Romagna"],
  ["09", "Toscana"], ["10", "Umbria"], ["11", "Marche"], ["12", "Lazio"], ["13", "Abruzzo"],
  ["14", "Molise"], ["15", "Campania"], ["16", "Puglia"], ["17", "Basilicata"], ["18", "Calabria"],
  ["19", "Sicilia"], ["20", "Sardegna"],
];
export const regionName = (code) => (IT_REGIONS.find(([c]) => c === code) || [])[1];

// Launch communes (D4): cadastral code, name, ISTAT region.
export const IT_LAUNCH_COMMUNI = [
  ["F205", "Milano", "03"], ["H501", "Roma", "12"], ["F839", "Napoli", "15"], ["L219", "Torino", "01"],
  ["G273", "Palermo", "19"], ["D969", "Genova", "07"], ["A944", "Bologna", "08"], ["D612", "Firenze", "09"],
  ["L736", "Venezia", "05"],
];
export const comuneName = (code) => (IT_LAUNCH_COMMUNI.find(([c]) => c === code) || [])[1];

// Worker-fact vocabularies (mirror engine/countries/italy.py constants).
export const IT_CONTRACT_TYPES = ["INDETERMINATO", "DETERMINATO", "APPRENDISTATO"];
export const IT_TFR_DESTINATIONS = ["AZIENDA", "FONDO_PENSIONE", "FONDO_TESORERIA"];
export const IT_CAP_COHORTS = ["POST_1995", "OPZIONE_CONTRIBUTIVA"];
