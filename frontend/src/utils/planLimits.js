// Plain-language plan limit labels, shared by every page that renders a plan
// (register picker, plan selection, subscription page) so the country limit
// reads the same everywhere. The feature key stays `max_jurisdictions` on the
// backend; customers only ever see "countries".

export const COUNTRY_LIMIT_KEY = "max_jurisdictions";

// Compliance > Countries — CompliancePage opens the Countries tab when it is
// navigated to with this state (see its location.state?.tab handling).
export const COMPLIANCE_COUNTRIES_ROUTE = "/payroll/compliances";
export const COMPLIANCE_COUNTRIES_STATE = { tab: "Countries" };

/** "1 country" / "Up to N countries" / "Unlimited countries" (null = unlimited). */
export function formatCountryLimit(limit) {
  if (limit === null || limit === undefined || Number(limit) < 0) return "Unlimited countries";
  const n = Number(limit);
  return n === 1 ? "1 country" : `Up to ${n} countries`;
}

// ── Plan-change country impact ────────────────────────────────────────────
// GET /billing/plan-change-impact and the 409 POST /billing/checkout returns
// for an unacknowledged change share one shape:
// {planCode, newLimit, currentLimit, countries, keep, pause, restore}.

export const PLAN_CHANGE_PAUSES_COUNTRIES = "plan_change_pauses_countries";

/** The impact payload carried by a checkout 409, or null for any other error. */
export function getCountryPauseImpact(error) {
  const trace = error?.trace;
  return error?.status === 409 && trace?.reason === PLAN_CHANGE_PAUSES_COUNTRIES ? trace : null;
}

/** True when the impact needs the user to see it before checkout. */
export function impactNeedsReview(impact) {
  return Boolean(impact && ((impact.pause?.length || 0) > 0 || (impact.restore?.length || 0) > 0));
}

/** True when checkout must send acknowledge_country_pause: true. */
export function impactPausesCountries(impact) {
  return Boolean(impact?.pause?.length);
}

// Numeric limits: [singular noun, plural noun]. A null limit is unlimited.
const COUNT_LIMIT_NOUNS = {
  max_entities: ["legal entity", "legal entities"],
  max_schedules: ["payroll schedule", "payroll schedules"],
  max_billable_worker_months: ["employee paid per month", "employees paid per month"],
  payroll_runs: ["payroll run", "payroll runs"],
};

// On/off features (any non-zero value means included).
const FEATURE_NAMES = {
  multi_entity: "Multiple legal entities",
  multi_currency: "Multi-currency payroll",
  api_access: "API access",
  assist: "Zoiko Assist",
};

function formatCount(n) {
  return Number(n).toLocaleString("en-US");
}

/** Customer-facing label for one entitlement_flags entry: every limit
 * carries its number ("Up to 3 legal entities", "Unlimited payroll runs")
 * and on/off features read as plain features. Callers drop value === 0
 * (feature not included) before calling this. */
export function formatPlanFeature(key, value) {
  if (key === COUNTRY_LIMIT_KEY) return formatCountryLimit(value);
  const nouns = COUNT_LIMIT_NOUNS[key];
  if (nouns) {
    if (value === null || value === undefined || Number(value) < 0) return `Unlimited ${nouns[1]}`;
    const n = Number(value);
    return n === 1 ? `1 ${nouns[0]}` : `Up to ${formatCount(n)} ${nouns[1]}`;
  }
  if (FEATURE_NAMES[key]) return FEATURE_NAMES[key];
  const label = key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return typeof value === "number" && value > 0 ? `${label}: ${formatCount(value)}` : label;
}
