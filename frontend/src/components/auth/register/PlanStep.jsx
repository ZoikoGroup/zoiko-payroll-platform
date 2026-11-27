import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Loader2, Mail } from "lucide-react";

import { listPublishedPlans } from "../../../service/billingService";
import { COUNTRY_LIMIT_KEY, formatCountryLimit } from "../../../utils/planLimits";
import PlanCard, { planCardStyle } from "../../billing/PlanCard";
import { StepHeading } from "./fields";

// ── Plan catalog ────────────────────────────────────────────────────────────
//
// Sourced live from GET /billing/plans (now unauthenticated — see
// billing/router.py's list_published_plans docstring) rather than hardcoded
// copy, so this card can never drift from the database the way an earlier
// version of this page did (Professional's displayed "3 entities" not
// matching its actual seeded max_entities=1 before scripts/
// migrate_plan_versions_v2.py corrected it). Only cosmetic, non-numeric
// copy — the tagline and which plan gets the "Recommended" badge — stays
// as local presentation data, since GET /billing/plans has no such field.
const PLAN_PRESENTATION = {
  CORE: {
    tagline: "Deliberately simple — for single-entity payroll in one country.",
    recommended: false,
  },
  PROFESSIONAL: {
    tagline: "For businesses that have grown past one entity or country.",
    recommended: true,
  },
  BUSINESS: {
    tagline: "Higher scale limits for growing multi-entity operations.",
    recommended: false,
  },
};

const PLAN_ORDER = ["CORE", "PROFESSIONAL", "BUSINESS"];

const CAPABILITY_LABELS = [
  ["payroll_runs", "Payroll runs"],
  ["multi_entity", "Multi-entity payroll"],
  ["multi_currency", "Multi-currency"],
  ["assist", "Zoiko Payroll Assist"],
];

const SCALE_LABELS = [
  ["max_entities", (n) => `${n === 1 ? "1 legal entity" : `Up to ${n} legal entities`}`],
  [COUNTRY_LIMIT_KEY, formatCountryLimit],
  ["max_schedules", (n) => `Up to ${n} payroll schedules`],
  ["max_billable_worker_months", (n) => `Up to ${n} billable worker-months`],
];

/** Convert one GET /billing/plans entry into this page's card shape. Plan
 * entitlement_flags is a {feature_key: limit_value} dict — a capability is
 * "on" only if the key is present AND its limit_value isn't 0; an absent
 * key or an explicit limit_value=0 both mean off, matching
 * billing/entitlements.py's _resolve_entitlement exactly (a flag row with
 * limit_value=0 is "explicitly disabled", not "allowed with a zero cap"). */
function buildPlanCard(apiPlan) {
  const flags = apiPlan.entitlement_flags || {};
  const presentation = PLAN_PRESENTATION[apiPlan.code] || {};
  return {
    code: apiPlan.code,
    name: apiPlan.name,
    priceLabel: apiPlan.monthly_price_usd > 0 ? `$${apiPlan.monthly_price_usd}/mo` : "Free",
    tagline: presentation.tagline || "",
    recommended: Boolean(presentation.recommended),
    capabilities: CAPABILITY_LABELS.map(([key, label]) => [label, key in flags && flags[key] !== 0]),
    // A present-but-null country limit means unlimited (Enterprise), so it
    // is still listed; other null scale limits are skipped as before.
    scale: SCALE_LABELS
      .filter(([key]) => flags[key] != null || (key === COUNTRY_LIMIT_KEY && key in flags))
      .map(([key, format]) => format(flags[key])),
  };
}

/** Loads the published plans once: {plans: {CODE: card}, loading, error}. */
export function usePublishedPlans() {
  const [state, setState] = useState({ plans: {}, loading: true, error: null });
  useEffect(() => {
    let cancelled = false;
    listPublishedPlans()
      .then((apiPlans) => {
        if (cancelled) return;
        const byCode = {};
        for (const p of apiPlans || []) byCode[p.code] = buildPlanCard(p);
        setState({ plans: byCode, loading: false, error: null });
      })
      .catch(() => {
        if (!cancelled) {
          setState({ plans: {}, loading: false, error: "Couldn't load current plan details — showing may be incomplete." });
        }
      });
    return () => { cancelled = true; };
  }, []);
  return state;
}

function ContactSalesPlanCard() {
  return (
    <div style={planCardStyle(false)}>
      <div>
        <div style={{ fontSize: "18px", fontWeight: "700", color: "#111827" }}>Enterprise</div>
        <div style={{ fontSize: "22px", fontWeight: "800", color: "#111827", marginTop: 2 }}>Custom pricing</div>
        <p style={{ fontSize: "12px", color: "#6B7280", marginTop: 6, minHeight: "32px" }}>
          Order-form governed — tailored entitlements, contracts, and support for large deployments.
        </p>
      </div>
      <a
        href="mailto:sales@zoikogroup.com?subject=Zoiko%20Payroll%20Enterprise%20inquiry"
        style={{
          marginTop: "auto", width: "100%", padding: "11px", borderRadius: "10px", border: "1.5px solid #087CC1",
          fontSize: "14px", fontWeight: "700", color: "#087CC1", background: "white", cursor: "pointer",
          textAlign: "center", textDecoration: "none", display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
          boxSizing: "border-box",
        }}
      >
        <Mail size={14} /> Contact Sales
      </a>
    </div>
  );
}

export default function PlanStep({ plans, plansLoading, plansError, selectedCode, onSelectPlan }) {
  return (
    <div>
      <StepHeading
        title="Choose your plan"
        subtitle="Pick a plan to finish setting up your account. You can change plans later from your dashboard."
      />

      {plansError && <p className="mb-4 text-[13px] text-red-600">{plansError}</p>}

      {plansLoading ? (
        <div className="py-10 text-center">
          <Loader2 size={28} className="inline animate-spin text-[#087CC1]" aria-label="Loading plans" />
        </div>
      ) : (
        <div role="radiogroup" aria-label="Plan" className="grid grid-cols-[repeat(auto-fit,minmax(210px,1fr))] gap-4">
          {PLAN_ORDER.filter((code) => plans[code]).map((code) => (
            <PlanCard
              key={code}
              name={plans[code].name}
              priceLabel={plans[code].priceLabel}
              tagline={plans[code].tagline}
              recommended={plans[code].recommended}
              capabilities={plans[code].capabilities}
              scale={plans[code].scale}
              selected={selectedCode === code}
              onSelect={() => onSelectPlan(code)}
            />
          ))}
          <ContactSalesPlanCard />
        </div>
      )}

      <p className="mt-5 text-center text-[13px] text-slate-500">
        Not ready to commit?{" "}
        <Link to="/trial-register" className="font-semibold text-[#087CC1] hover:underline">
          Try Zoiko Payroll free for 30 days
        </Link>
      </p>
    </div>
  );
}
