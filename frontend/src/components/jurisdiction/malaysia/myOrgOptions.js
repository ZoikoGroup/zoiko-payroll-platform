// Malaysia (ZP-MY-ENG-001) organisation-side choice lists. They mirror the
// enumerations malaysia_service / the payroll_my_* CHECK constraints accept —
// vocabulary only, never a statutory value.

export const HRD_CATEGORIES = ["COMPULSORY", "OPTIONAL_REGISTERED", "NOT_REGISTERED"];
export const CONTRACT_TYPES = ["CONTRACT_OF_SERVICE", "GIG_PLATFORM", "DOMESTIC", "PUBLIC_SECTOR", "OTHER"];
export const PAY_FREQUENCIES = ["MONTHLY", "SEMI_MONTHLY", "WEEKLY", "OTHER"];
export const CITIZENSHIP = ["CITIZEN", "PERMANENT_RESIDENT", "NON_CITIZEN"];
export const TAX_RESIDENCE = ["REVIEW_REQUIRED", "RESIDENT", "NON_RESIDENT"];
export const WORK_PASS_TYPES = ["NONE", "EMPLOYMENT_PASS", "VISIT_PASS_TEMP_EMPLOYMENT", "RESIDENCE_PASS_TALENT", "OTHER"];
export const EPF_MEMBER_CLASSES = ["MY_PR_BELOW_60", "MY_60_PLUS", "PR_OR_PRE1998_NONMY_60_PLUS", "NONMY_POST_1998",
  "NOT_COVERED"];
export const SOCSO_CATEGORIES = ["EI_AND_INVALIDITY", "EI_ONLY", "FOREIGN_WORKER", "NOT_COVERED", "UNSUPPORTED_DOMESTIC"];
export const EIS_STATES = ["COVERED", "EXEMPT_AGE", "EXEMPT_HISTORY", "FOREIGN_EXCLUDED"];
export const REST_DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"];
export const TERRITORIES = ["PENINSULAR_LABUAN", "SABAH", "SARAWAK"];
// 13 states + 3 federal territories (holiday calendars are per state, not per
// labour territory: Labuan follows Peninsular labour law, its own holidays).
export const HOLIDAY_STATES = ["JHR", "KDH", "KTN", "MLK", "NSN", "PHG", "PRK", "PLS", "PNG", "SBH", "SWK", "SGR", "TRG",
  "KUL", "LBN", "PJY"];
export const ASSIGNMENT_REASONS = ["HIRE", "TRANSFER", "ASSIGNMENT", "CORRECTION"];
export const DECLARATION_TYPES = ["TP1", "TP3", "CP38", "ZAKAT", "TAX_BORNE_BY_EMPLOYER", "EPF_VOLUNTARY_EXCESS"];
export const SOURCE_CHANNELS = ["PAPER", "ELECTRONIC", "EMPLOYEE_PORTAL", "AUTHORITY", "IMPORT"];
export const IDENTIFIER_TYPES = ["NRIC", "TIN", "EPF_NO", "SOCSO_NO", "WORK_PASS_NO"];
export const EVENT_TYPES = ["CP22", "CP22A", "CP21", "DEATH_NOTICE"];

// Declaration value fields per type (the backend validates them; blank ones are
// never sent). TP1 claims and TP3 accumulators are entered as JSON objects.
export const DECLARATION_VALUE_FIELDS = {
  TP1: ["claimsJson"],
  TP3: ["priorEmployer", "accumulatorsJson"],
  CP38: ["amount", "instructionRef"],
  ZAKAT: ["amount"],
  EPF_VOLUNTARY_EXCESS: ["ratePct"],
};
const VALUE_KEYS = ["amount", "instructionRef", "priorEmployer", "ratePct", "claimsJson", "accumulatorsJson"];

function parseObject(text, name) {
  if (text === undefined || text === null || String(text).trim() === "") return undefined;
  try {
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed;
  } catch { /* fall through */ }
  throw new Error(`${name} must be a JSON object, e.g. {"PCB_GROSS_NORMAL": 12000}`);
}

// The capture form sends the value fields flat; this folds them into `value`.
export function declarationPayload(values) {
  const out = { ...values };
  const keys = DECLARATION_VALUE_FIELDS[out.declaration_type] || [];
  const value = {};
  for (const key of VALUE_KEYS) {
    if (keys.includes(key) && out[key] !== undefined && out[key] !== "") {
      if (key === "claimsJson") value.claims = parseObject(out[key], "TP1 claims");
      else if (key === "accumulatorsJson") value.accumulators = parseObject(out[key], "TP3 accumulators");
      else value[key] = out[key];
    }
    delete out[key];
  }
  out.value = value;
  return out;
}

// Holiday states of the Sabah / Sarawak territories; the backend refuses any
// other combination (MY-003) — the UI only warns early.
export const territoryForState = (state) => ({ SBH: "SABAH", SWK: "SARAWAK" }[state] || (state ? "PENINSULAR_LABUAN" : ""));
