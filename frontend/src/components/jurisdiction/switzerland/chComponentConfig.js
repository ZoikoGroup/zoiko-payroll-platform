// Switzerland (ZP-CH-PAYROLL-001) — component keys, cantons and catalog
// constants shared by every CH jurisdiction component. Mirrors the backend
// content module (engine/countries/switzerland_content.py at line 187:
// CH_PARAMETER_KEYS merges CH_FEDERAL_PARAMETER_KEYS + CH_CANTON_PARAMETER_KEYS)
// and the CH_TAXABILITY_COMPONENTS tuple in switzerland_service.py.

// Cantons (ISO 3166-2:CH; the same codes the backend uses for
// jurisdiction_state). Alphabetical by code, exactly like CH_CANTONS.
export const CH_CANTONS = [
  ["CH-AG", "Aargau"], ["CH-AI", "Appenzell Innerrhoden"], ["CH-AR", "Appenzell Ausserrhoden"],
  ["CH-BE", "Bern"], ["CH-BL", "Basel-Landschaft"], ["CH-BS", "Basel-Stadt"],
  ["CH-FR", "Fribourg"], ["CH-GE", "Geneva"], ["CH-GL", "Glarus"],
  ["CH-GR", "Graubünden"], ["CH-JU", "Jura"], ["CH-LU", "Lucerne"],
  ["CH-NE", "Neuchâtel"], ["CH-NW", "Nidwalden"], ["CH-OW", "Obwalden"],
  ["CH-SG", "St. Gallen"], ["CH-SH", "Schaffhausen"], ["CH-SO", "Solothurn"],
  ["CH-SZ", "Schwyz"], ["CH-TG", "Thurgau"], ["CH-TI", "Ticino"],
  ["CH-UR", "Uri"], ["CH-VD", "Vaud"], ["CH-VS", "Valais"],
  ["CH-ZG", "Zug"], ["CH-ZH", "Zurich"],
];

export const CH_CANTON_CODES = CH_CANTONS.map(([code]) => code);

// Cantons on the Jahresmodell (annual tariff model) per S9 of the CH content
// notes; every other canton uses the Monatsmodell (monthly).
export const CH_QST_MODELS = ["MONTHLY", "ANNUAL"];
export const CH_ANNUAL_MODEL_CANTONS = new Set(["CH-FR", "CH-GE", "CH-TI", "CH-VD", "CH-VS"]);

export const CH_QST_FORMAT_VERSIONS = ["ESTV_FIXED_WIDTH_V1"];
export const CH_QST_STATUSES = ["IMPORTED", "VALIDATED", "APPROVED", "ACTIVE", "REJECTED", "SUPERSEDED"];

// The 18 federal scalar parameters of a CH federal pack (content.py
// CH_FEDERAL_PARAMETER_KEYS; the engine reads them from the Active federal
// pack). Canton scaffold keys live in CH_CANTON_KEYS.
export const CH_FEDERAL_KEYS = [
  "ch_ahv", "ch_iv", "ch_eo", "ch_alv", "ch_alv_ceiling", "ch_uvg_ceiling",
  "ch_nbu_min_weekly_hours", "ch_bvg_entry_threshold", "ch_bvg_coordination_deduction",
  "ch_bvg_upper_salary", "ch_bvg_min_coordinated", "ch_fak_child_min", "ch_fak_education_min",
  "ch_fak_earnings_threshold_month", "ch_fak_earnings_threshold_year", "ch_eo_parental_pct",
  "ch_eo_daily_cap", "ch_rounding_rule",
];

// Canton-pack scaffold keys (content.py CH_CANTON_PARAMETER_KEYS). The
// federal JSON calculator does not read these directly — they are the canton
// facts (QST model + tariff file, FAK amounts) the readiness/canton status
// and the org QST resolution consume.
export const CH_CANTON_KEYS = [
  "ch_qst_model", "ch_qst_tariff_file_id", "ch_fak_child", "ch_fak_education", "ch_fak_employee_pct",
];

// Earned-income types the CH engine recognizes (service.ch_earnings; named
// allowance items flow in as their own keys at runtime).
export const CH_EARNING_TYPES = [
  ["base_salary", "Basic salary"],
  ["hra", "HRA (housing allowance)"],
  ["special_allowance", "Special allowance"],
  ["overtime", "Overtime"],
  ["additional_compensation", "Additional compensation"],
  ["named_allowances", "Named allowances"],
];

// The ten obligations CH earning classification covers (switzerland_service
// CH_TAXABILITY_COMPONENTS). ch_la = Lohnausweis box classification (the
// treatment carries the box code); ch_wage_floor classifies the wages that
// count toward a wage-floor check.
export const CH_TAXABILITY_COMPONENTS = [
  ["ch_ahv", "AHV/AVS — old-age and survivors"],
  ["ch_iv", "IV — invalidity"],
  ["ch_eo", "EO — loss-of-earnings compensation"],
  ["ch_alv", "ALV — unemployment"],
  ["ch_uvg", "UVG/NBU — occupational accident"],
  ["ch_bvg", "BVG — occupational pension"],
  ["ch_ktg", "KTG — daily allowance (illness)"],
  ["ch_qst", "QST — source tax (Quellensteuer)"],
  ["ch_wage_floor", "Wage floor"],
  ["ch_la", "Lohnausweis box classification"],
];

export const CH_SCHEME_TYPES = ["COMPENSATION_OFFICE", "FAK", "BVG_PLAN", "UVG_POLICY", "KTG_POLICY"];
export const CH_WAGE_FLOOR_TYPES = ["CH_CANTON_MINIMUM", "CH_GAV", "CH_NAV"];
export const CH_ELM_DOMAINS = ["AHV", "QST", "FAK", "UVG", "KTG", "BFS"];

// Everything a CH contribution-rate row can mean, so the generic Parameters
// tab only ever lists the rows no dedicated group claims.
export const CH_GROUPED_KEYS = new Set([...CH_FEDERAL_KEYS, ...CH_CANTON_KEYS, "ch_wage_floor"]);