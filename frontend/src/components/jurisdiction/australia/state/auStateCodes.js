// Australia's 8 states/territories that levy their own payroll tax
// (§14-18) — a fixed constitutional fact, not a statutory VALUE (no
// rate/threshold lives here). Same short codes used platform-wide:
// PayrollEmployee.work_state choices (countryFieldSpecs.js), service.py's
// _AU_PAYROLL_TAX_COMPONENT_BY_WORK_STATE, and engine/countries/
// australia.py's calculate_au_state_payroll_tax dispatch — all keyed by
// these exact strings, so a JurisdictionPack's own jurisdictionState must
// match one of them exactly for get_state_scoped_config to find it.
export const AU_STATE_CODES = ["NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"];

export const AU_STATE_NAMES = {
  NSW: "New South Wales", VIC: "Victoria", QLD: "Queensland", WA: "Western Australia",
  SA: "South Australia", TAS: "Tasmania", ACT: "Australian Capital Territory", NT: "Northern Territory",
};
