// New Zealand organisation-side option lists (ZP-NZ-ENG-001). Each list is the
// backend's own enumeration (new_zealand_content.py / the migrations' CHECKs),
// so a form never offers a value the server refuses. No statutory number here.

export const TAX_CODES = ["M", "ME", "M SL", "ME SL", "SB", "S", "SH", "ST", "SA", "SB SL", "S SL", "SH SL", "ST SL",
  "SA SL", "ND", "STC"];
export const IRD_NUMBER_STATES = ["VALID", "PENDING", "MISSING", "INVALID"];
export const TAX_CODE_SOURCES = ["IR330_DECLARATION", "IRD_NOTICE", "NO_NOTIFICATION"];
export const RESIDENCY = ["RESIDENT", "NON_RESIDENT"];
export const SL_CERTIFICATES = ["SPECIAL_DEDUCTION_RATE", "NIL_DEDUCTION"];
export const MIN_WAGE_CATEGORIES = ["ADULT", "STARTING_OUT", "TRAINING", "EXEMPTION_PERMIT"];
export const KS_MEMBERSHIP = ["NOT_MEMBER", "CONTRIBUTING", "OPTED_OUT", "SAVINGS_SUSPENSION", "NOT_ELIGIBLE"];
export const KS_ROUTES = ["AUTO_ENROLLED", "OPT_IN", "EXISTING_MEMBER"];
export const ESCT_BASES = ["PRIOR_YEAR", "ESTIMATE", "NEW_EMPLOYEE_ESTIMATE"];
export const KS_DESTINATIONS = ["INLAND_REVENUE", "COMPLYING_FUND"];
export const PATTERN_TYPES = ["FIXED", "ROSTERED", "VARIABLE"];
export const HOURS_SOURCES = ["CONTRACT", "TIMESHEET", "ROSTER"];
export const NZ_WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"];
export const NOTICE_TYPES = ["CHILD_SUPPORT", "STUDENT_LOAN_EXTRA", "IRD_DEDUCTION_NOTICE", "COURT_ATTACHMENT"];
export const NOTICE_ISSUERS = ["INLAND_REVENUE", "COURT", "MSD", "OTHER_AUTHORITY"];
export const PROTECTED_POLICIES = ["IRD_PROTECTED_NET", "COURT_SPECIFIED", "NONE"];
export const OBLIGATIONS = ["ACC_LIABLE_EARNINGS", "PAYE_GROSS", "PAYE", "ACC_LEVY", "KS_GROSS", "KS_EMPLOYEE",
  "KS_EMPLOYER_GROSS", "ESCT", "STUDENT_LOAN", "CHILD_SUPPORT"];
export const FILING_METHODS = ["PAYDAY_GATEWAY", "MYIR_FILE_UPLOAD", "MYIR_ONSCREEN", "PAPER"];
export const REMITTANCE_CLASSES = ["MONTHLY", "TWICE_MONTHLY"];
export const PAYE_ESCT_BASES = ["PRIOR_YEAR", "ESTIMATE"];
export const TIMEZONES = ["Pacific/Auckland", "Pacific/Chatham"];
export const CONTINUITY = ["NEW_INSTANCE", "CONTINUOUS"];
export const PAYG_BASES = ["FIXED_TERM_UNDER_12_MONTHS", "IRREGULAR_INTERMITTENT"];
export const OWD_DECISIONS = ["YES", "NO"];

// A reason is required on every New Zealand statutory write (NZ-024).
export const REASON_FIELD = { key: "reason", label: "Reason for the change", required: true };

export const errorText = (e) => {
  const detail = e?.response?.data?.detail ?? e?.detail;
  if (typeof detail === "string") return detail;
  return e?.message || "The action failed.";
};

export const period = (row) => `${row.effective_from || row.effectiveFrom || "—"} → ${row.effective_to || row.effectiveTo || "open"}`;
