// Canada component key metadata — mirrors india/inComponentConfig.js's
// role: pure data/helpers the tab components consume, no JSX here.
//
// shape: "rate_pair" = Employee % + Employer %, "rate_single" = Employee
// % only (every single-sided rate this engine reads is employee-side —
// cpp2_rate, lowest_fed_rate, qc_fed_abatement, territorial payroll tax),
// "flat" = Flat Amount only. Matches exactly what engine/countries/
// canada.py reads via resolve_jurisdiction_parameter()/rate_map.get() —
// every key below is a real, engine-read key; nothing here invents one.

export const CPP_EI_KEYS = [
  { key: "cpp", label: "Canada Pension Plan (CPP)", shape: "rate_pair" },
  { key: "ei", label: "Employment Insurance (EI)", shape: "rate_pair" },
  { key: "cpp_ympe", label: "CPP Year's Maximum Pensionable Earnings (YMPE)", shape: "flat" },
  { key: "cpp_basic_exemption", label: "CPP Basic Exemption Amount", shape: "flat" },
  { key: "ei_mie", label: "EI Maximum Insurable Earnings", shape: "flat" },
  { key: "cpp2_yampe", label: "CPP2 Year's Additional Maximum Pensionable Earnings (YAMPE)", shape: "flat" },
  { key: "cpp2_rate", label: "CPP2 Second-Tier Rate", shape: "rate_single" },
];

export const FEDERAL_PARAM_KEYS = [
  { key: "basic_personal_amt", label: "Federal Basic Personal Amount — Maximum", shape: "flat" },
  { key: "bpaf_min", label: "Federal Basic Personal Amount — Minimum (tapered)", shape: "flat" },
  { key: "bpaf_ni_thresh_lo", label: "BPAF Taper — Net Income Threshold (Low)", shape: "flat" },
  { key: "bpaf_ni_thresh_hi", label: "BPAF Taper — Net Income Threshold (High)", shape: "flat" },
  { key: "cea", label: "Canada Employment Amount (credit)", shape: "flat" },
  { key: "lowest_fed_rate", label: "Lowest Federal Rate (credit conversion)", shape: "rate_single" },
];

export const QUEBEC_KEYS = [
  { key: "qpp", label: "Quebec Pension Plan (QPP)", shape: "rate_pair" },
  { key: "qpip", label: "Quebec Parental Insurance Plan (QPIP)", shape: "rate_pair" },
  { key: "qpip_mie", label: "QPIP Maximum Insurable Earnings", shape: "flat" },
  { key: "quebec_bpa", label: "Quebec Basic Personal Amount", shape: "flat" },
  { key: "qc_fed_abatement", label: "Quebec Federal Abatement", shape: "rate_single" },
];

// NWT vs Nunavut share one tab (see CACompliancePage.jsx's territorial-tax
// extraTab) — the component key and label depend on which territory's
// pack is selected, so this builds the one-item key list rather than a
// static export like the three above.
export function buildTerritorialKeys(jurisdictionState) {
  const territoryName = jurisdictionState === "NT" ? "Northwest Territories" : "Nunavut";
  const key = jurisdictionState === "NT" ? "nwt_payroll_tax" : "nu_payroll_tax";
  return [{ key, label: `${territoryName} Payroll Tax`, shape: "rate_single" }];
}
