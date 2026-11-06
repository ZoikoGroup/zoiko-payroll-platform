// Poland (ZP-PL-ENG-001) organisation-side choice lists. They mirror the
// enumerations poland_service / the pl_* CHECK constraints accept — vocabulary
// only, never a statutory value.

export const ZUS_DEADLINE_CLASSES = ["DAY_5", "DAY_15", "DAY_20"];
export const ACCIDENT_RATE_SOURCES = ["ZUS_NOTICE", "SELF_DETERMINED", "SMALL_PAYER_DEFAULT"];
export const CONTRACT_TYPES = ["UMOWA_O_PRACE", "UMOWA_ZLECENIE", "UMOWA_O_DZIELO", "MANAGEMENT_CONTRACT",
  "BOARD_REMUNERATION"];
export const PAY_FREQUENCIES = ["MONTHLY", "WEEKLY", "FORTNIGHTLY", "OTHER"];
export const RESIDENCY = ["RESIDENT", "NON_RESIDENT"];
export const DECLARATION_TYPES = ["PIT2", "COSTS_COMMUTER", "COSTS_MULTIPLE", "PIT0_UNDER26", "PIT0_RETURN",
  "PIT0_FAMILY4", "PIT0_SENIOR", "PIT0_WAIVER", "HIGHER_RATE_REQUEST", "PPK_OPT_OUT", "PPK_REDUCED_RATE",
  "PPK_ADDITIONAL", "PRIOR_EMPLOYER_CAP"];
export const SOURCE_CHANNELS = ["PAPER", "ELECTRONIC", "EMPLOYEE_PORTAL", "IMPORT"];
export const PIT2_ALLOCATIONS = ["FULL", "HALF", "THIRD"];
export const PPK_STATES = ["NOT_ELIGIBLE", "ELIGIBLE_NOT_ENROLLED", "ENROLLED", "OPTED_OUT", "SUSPENDED_BY_LAW", "ENDED"];
export const PPK_NOTICE_STATES = ["NOT_SENT", "SENT", "ACKNOWLEDGED"];
export const INCAPACITY_CATEGORIES = ["ILLNESS", "ROUTE_ACCIDENT", "PREGNANCY", "DONOR", "WORK_ACCIDENT", "OTHER"];
export const IDENTIFIER_TYPES = ["PESEL", "NIP"];

// Statement value fields: which ones a declaration type carries (the backend
// validates them; blank ones are never sent).
export const STATEMENT_VALUE_FIELDS = {
  PIT2: ["allocation"],
  PPK_REDUCED_RATE: ["ratePct", "otherSourcesIncome"],
  PPK_ADDITIONAL: ["ratePct"],
  PRIOR_EMPLOYER_CAP: ["pensionBase", "disabilityBase"],
};

// The capture form sends the value fields flat; this folds them into `value`.
export function statementPayload(values) {
  const out = { ...values };
  const keys = STATEMENT_VALUE_FIELDS[out.declaration_type] || [];
  const value = {};
  for (const key of ["allocation", "ratePct", "otherSourcesIncome", "pensionBase", "disabilityBase"]) {
    if (keys.includes(key) && out[key] !== undefined) value[key] = out[key];
    delete out[key];
  }
  out.value = value;
  return out;
}
