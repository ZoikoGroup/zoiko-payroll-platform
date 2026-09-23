import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Loader2, Eye, EyeOff, AlertCircle, Check, X, Sparkles, Mail, ArrowLeft } from "lucide-react";
import { apiFetch, setSession } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { listPublishedPlans } from "../service/billingService";
import {
  REGISTRATION_COUNTRIES,
  getStatesForCountryName,
  getTimezonesForCountryName,
  getDefaultTimezoneForCountry,
} from "../utils/registrationRegions";
import {
  getJurisdictionTaxSchema,
  getJurisdictionTaxFields,
  validateJurisdictionTaxIds,
  primaryTaxValue,
} from "../utils/jurisdictionTax";
import LandingHeader from "../landing/LandingHeader";
import Footer from "../landing/Footer";

const fieldStyle = {
  width: "100%", padding: "11px 14px", borderRadius: "10px",
  border: "1.5px solid #E5E7EB", fontSize: "14px", color: "#111827",
  outline: "none", boxSizing: "border-box", transition: "border-color 0.2s",
  background: "#F9FAFB",
};

const selectStyle = {
  ...fieldStyle,
  appearance: "auto",
};

const labelStyle = {
  display: "block", fontSize: "13px", fontWeight: "600", color: "#374151", marginBottom: "6px",
};

// ── Plan catalog (Stage 1) ──────────────────────────────────────────────────
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
    tagline: "Deliberately simple — for single-entity, single-jurisdiction payroll.",
    recommended: false,
  },
  PROFESSIONAL: {
    tagline: "For businesses that have grown past one entity or jurisdiction.",
    recommended: true,
  },
  BUSINESS: {
    tagline: "Higher scale limits for growing multi-entity operations.",
    recommended: false,
  },
};

const CAPABILITY_LABELS = [
  ["payroll_runs", "Payroll runs"],
  ["multi_entity", "Multi-entity payroll"],
  ["multi_currency", "Multi-currency"],
  ["api_access", "API access"],
  ["assist", "Zoiko Payroll Assist"],
];

const SCALE_LABELS = [
  ["max_entities", (n) => `${n === 1 ? "1 legal entity" : `Up to ${n} legal entities`}`],
  ["max_jurisdictions", (n) => `${n === 1 ? "1 production jurisdiction" : `Up to ${n} production jurisdictions`}`],
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
    scale: SCALE_LABELS.filter(([key]) => flags[key] != null).map(([key, format]) => format(flags[key])),
  };
}

export const planCardStyle = (recommended) => ({
  background: "#FFFFFF",
  borderRadius: "16px",
  padding: "28px 24px",
  display: "flex",
  flexDirection: "column",
  gap: "14px",
  border: recommended ? "2px solid #087CC1" : "1.5px solid #E5E7EB",
  boxShadow: recommended ? "0 8px 32px rgba(8,124,193,0.18)" : "0 2px 12px rgba(0,0,0,0.05)",
  position: "relative",
});

export const badgeStyle = {
  position: "absolute", top: "-12px", left: "50%", transform: "translateX(-50%)",
  background: "linear-gradient(135deg, #087CC1, #1596D1)", color: "#FFFFFF",
  fontSize: "11px", fontWeight: "700", padding: "4px 14px", borderRadius: "20px",
  whiteSpace: "nowrap", letterSpacing: "0.03em",
};

export function PlanCapabilityRow({ label, on }) {
  return (
    <li style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "13px", color: on ? "#374151" : "#B0B7C3" }}>
      {on ? (
        <Check size={15} style={{ color: "#10B981", flexShrink: 0 }} />
      ) : (
        <X size={15} style={{ color: "#D1D5DB", flexShrink: 0 }} />
      )}
      <span style={on ? {} : { textDecoration: "line-through" }}>{label}</span>
    </li>
  );
}

function ChoosablePlanCard({ plan, onChoose }) {
  return (
    <div style={planCardStyle(plan.recommended)}>
      {plan.recommended && <div style={badgeStyle}><Sparkles size={11} style={{ display: "inline", marginRight: 4, marginBottom: -1 }} />Recommended plan</div>}
      <div>
        <div style={{ fontSize: "18px", fontWeight: "700", color: "#111827" }}>{plan.name}</div>
        <div style={{ fontSize: "22px", fontWeight: "800", color: "#087CC1", marginTop: 2 }}>{plan.priceLabel}</div>
        <p style={{ fontSize: "12px", color: "#6B7280", marginTop: 6, minHeight: "32px" }}>{plan.tagline}</p>
      </div>
      <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: "6px" }}>
        {plan.capabilities.map(([label, on]) => (
          <PlanCapabilityRow key={label} label={label} on={on} />
        ))}
      </ul>
      <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: "4px", borderTop: "1px solid #F3F4F6", paddingTop: "10px" }}>
        {plan.scale.map((s) => (
          <li key={s} style={{ fontSize: "12px", color: "#4B5563", fontWeight: 500 }}>{s}</li>
        ))}
      </ul>
      <button
        type="button"
        onClick={() => onChoose(plan.code)}
        style={{
          marginTop: "auto", width: "100%", padding: "11px", borderRadius: "10px", border: "none",
          fontSize: "14px", fontWeight: "700", color: "white", cursor: "pointer",
          background: plan.recommended ? "linear-gradient(135deg, #087CC1, #1596D1)" : "#111827",
        }}
      >
        Choose {plan.name}
      </button>
    </div>
  );
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

function PlanPickerStage({ plans, plansLoading, plansError, onChoosePlan }) {
  return (
    <div style={{ width: "100%", maxWidth: "980px" }}>
      <div style={{ textAlign: "center", marginBottom: "32px" }}>
        <h1 style={{ fontSize: "26px", fontWeight: "800", color: "#111827", margin: "0 0 8px 0", letterSpacing: "-0.5px" }}>
          Choose your plan
        </h1>
        <p style={{ fontSize: "14px", color: "#6B7280", margin: 0 }}>
          Pick a plan to get started. You can change plans later from your dashboard.
        </p>
      </div>

      {plansError && (
        <p style={{ textAlign: "center", fontSize: "13px", color: "#DC2626", marginBottom: "16px" }}>{plansError}</p>
      )}

      {plansLoading ? (
        <div style={{ textAlign: "center", padding: "40px 0" }}>
          <Loader2 size={28} style={{ animation: "spin 1s linear infinite", color: "#087CC1" }} />
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "20px" }}>
          {plans.CORE && <ChoosablePlanCard plan={plans.CORE} onChoose={onChoosePlan} />}
          {plans.PROFESSIONAL && <ChoosablePlanCard plan={plans.PROFESSIONAL} onChoose={onChoosePlan} />}
          {plans.BUSINESS && <ChoosablePlanCard plan={plans.BUSINESS} onChoose={onChoosePlan} />}
          <ContactSalesPlanCard />
        </div>
      )}

      <p style={{ textAlign: "center", fontSize: "13px", color: "#6B7280", marginTop: "28px" }}>
        Not ready to commit?{" "}
        <Link to="/trial-register" style={{ color: "#087CC1", fontWeight: "600", textDecoration: "none" }}>
          Try Zoiko Payroll free for 30 days
        </Link>
      </p>
    </div>
  );
}

export default function RegisterPage() {
  const navigate = useNavigate();
  const { login } = useAuth();

  const [stage, setStage] = useState("plan"); // "plan" | "details"
  const [selectedPlanCode, setSelectedPlanCode] = useState(null);

  const [plans, setPlans] = useState({});
  const [plansLoading, setPlansLoading] = useState(true);
  const [plansError, setPlansError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    listPublishedPlans()
      .then((apiPlans) => {
        if (cancelled) return;
        const byCode = {};
        for (const p of apiPlans || []) byCode[p.code] = buildPlanCard(p);
        setPlans(byCode);
      })
      .catch(() => {
        if (!cancelled) setPlansError("Couldn't load current plan details — showing may be incomplete.");
      })
      .finally(() => {
        if (!cancelled) setPlansLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  const [form, setForm] = useState({
    orgName: "",
    adminName: "",
    adminEmail: "",
    password: "",
    phone: "",
    address: "",
    city: "",
    state: "",
    country: "",
    timezone: "",
    industry: "",
    companyType: "",
    taxNo: "",
    taxIdentifiers: {},
    termsAccepted: false,
  });
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [localError, setLocalError] = useState(null);

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  function updateTaxIdentifier(key, value) {
    setForm((f) => ({
      ...f,
      taxIdentifiers: { ...f.taxIdentifiers, [key]: value },
    }));
  }

  function handleCountryChange(value) {
    setForm((f) => ({
      ...f,
      country: value,
      state: "",
      timezone: getDefaultTimezoneForCountry(value),
      taxIdentifiers: {},
    }));
  }

  function handleChoosePlan(code) {
    setSelectedPlanCode(code);
    setStage("details");
  }

  const countryStates = getStatesForCountryName(form.country);
  const countryTimezones = getTimezonesForCountryName(form.country);
  const jurisdictionSchema = getJurisdictionTaxSchema(form.country);
  const jurisdictionTaxFields = getJurisdictionTaxFields(form.country);
  const selectedPlan = selectedPlanCode ? plans[selectedPlanCode] : null;

  async function handleSubmit(e) {
    e.preventDefault();
    setLocalError(null);

    const taxValidationErrors = validateJurisdictionTaxIds(form.country, form.taxIdentifiers);
    if (taxValidationErrors.length) {
      setLocalError(taxValidationErrors[0].message);
      return;
    }

    setSubmitting(true);
    try {
      const hasTaxIdentifiers = jurisdictionTaxFields.length > 0;
      const data = await apiFetch("/api/auth/register", {
        method: "POST",
        body: {
          organization: form.orgName,
          name: form.adminName,
          email: form.adminEmail,
          password: form.password,
          phone: form.phone,
          address: form.address,
          city: form.city,
          state: form.state,
          country: form.country,
          timezone: form.timezone,
          industry: form.industry,
          company_type: form.companyType,
          terms_accepted: form.termsAccepted,
          tax_no: hasTaxIdentifiers
            ? primaryTaxValue(form.country, form.taxIdentifiers)
            : form.taxNo,
          tax_identifiers: hasTaxIdentifiers ? form.taxIdentifiers : undefined,
        },
      });

      // Account exists from here on — log the browser in immediately so
      // PlanReviewPage's checkout call (which requires a real org-admin
      // JWT) works with no separate login step in between.
      setSession(data);
      await login(data.user);

      // Checkout itself now happens on PlanReviewPage, not here — it's the
      // one place that reviews the plan and computes the actual
      // service_commencement_at before ever calling /billing/checkout.
      // Pass the already-fetched plan card along so that page doesn't need
      // a second GET /billing/plans round-trip.
      navigate("/register/plan-review", { state: { planCode: selectedPlanCode, plan: selectedPlan } });
    } catch (err) {
      setLocalError(err.message || "Unable to create your account.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={{
      minHeight: "100vh", display: "flex", flexDirection: "column",
      background: "linear-gradient(135deg, #eef6fb 0%, #ffffff 50%, #eef6fb 100%)",
      fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif"
    }}>
      <LandingHeader />
      <div style={{
        flex: 1, display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
        padding: "40px 24px"
      }}>
        {stage === "plan" && (
          <PlanPickerStage
            plans={plans}
            plansLoading={plansLoading}
            plansError={plansError}
            onChoosePlan={handleChoosePlan}
          />
        )}

        {stage === "details" && (
        <div style={{ width: "100%", maxWidth: "680px" }}>
          <div style={{ textAlign: "center", marginBottom: "24px" }}>
            <h1 style={{ fontSize: "26px", fontWeight: "800", color: "#111827", margin: "0 0 8px 0", letterSpacing: "-0.5px" }}>
              Create your account
            </h1>
            <p style={{ fontSize: "14px", color: "#6B7280", margin: 0 }}>
              Register your organization for Zoiko Payroll. Connect people and money. Scale with Zoiko One.
            </p>
          </div>

          <button
            type="button"
            onClick={() => setStage("plan")}
            style={{
              display: "flex", alignItems: "center", gap: "8px", margin: "0 auto 18px", padding: "8px 14px",
              borderRadius: "999px", border: "1.5px solid #E5E7EB", background: "white", cursor: "pointer",
              fontSize: "13px", color: "#374151", fontWeight: 600,
            }}
          >
            <ArrowLeft size={13} />
            Signing up for <strong style={{ color: "#087CC1" }}>{selectedPlan?.name}</strong> ({selectedPlan?.priceLabel}) — change plan
          </button>

          <div style={{
            background: "white", borderRadius: "20px",
            boxShadow: "0 8px 40px rgba(0,0,0,0.10)",
            border: "1px solid #F3F4F6", padding: "36px"
          }}>
            {localError && (
              <div style={{
                display: "flex", alignItems: "flex-start", gap: "8px",
                background: "#FEF2F2", border: "1px solid #FECACA",
                borderRadius: "10px", padding: "12px 14px", marginBottom: "20px"
              }}>
                <AlertCircle size={16} color="#DC2626" style={{ marginTop: "1px", flexShrink: 0 }} />
                <span style={{ fontSize: "13px", color: "#DC2626" }}>{localError}</span>
              </div>
            )}

            <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "18px" }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "18px" }}>
                <div>
                  <label htmlFor="orgName" style={labelStyle}>
                    Organization Name
                  </label>
                  <input
                    id="orgName"
                    type="text"
                    required
                    autoComplete="organization"
                    value={form.orgName}
                    onChange={(e) => update("orgName", e.target.value)}
                    placeholder="Acme Inc."
                    style={fieldStyle}
                    onFocus={e => e.target.style.borderColor = "#087CC1"}
                    onBlur={e => e.target.style.borderColor = "#E5E7EB"}
                  />
                </div>

                <div>
                  <label htmlFor="adminName" style={labelStyle}>
                    Admin Name
                  </label>
                  <input
                    id="adminName"
                    type="text"
                    required
                    autoComplete="name"
                    value={form.adminName}
                    onChange={(e) => update("adminName", e.target.value)}
                    placeholder="Jane Doe"
                    style={fieldStyle}
                    onFocus={e => e.target.style.borderColor = "#087CC1"}
                    onBlur={e => e.target.style.borderColor = "#E5E7EB"}
                  />
                </div>

                <div>
                  <label htmlFor="adminEmail" style={labelStyle}>
                    Admin Email
                  </label>
                  <input
                    id="adminEmail"
                    type="email"
                    required
                    autoComplete="email"
                    value={form.adminEmail}
                    onChange={(e) => update("adminEmail", e.target.value)}
                    placeholder="admin@company.com"
                    style={fieldStyle}
                    onFocus={e => e.target.style.borderColor = "#087CC1"}
                    onBlur={e => e.target.style.borderColor = "#E5E7EB"}
                  />
                </div>

                <div>
                  <label htmlFor="password" style={labelStyle}>
                    Password
                  </label>
                  <div style={{ position: "relative" }}>
                    <input
                      id="password"
                      type={showPassword ? "text" : "password"}
                      required
                      minLength={8}
                      autoComplete="new-password"
                      value={form.password}
                      onChange={(e) => update("password", e.target.value)}
                      placeholder="At least 8 characters"
                      style={{ ...fieldStyle, padding: "11px 44px 11px 14px" }}
                      onFocus={e => e.target.style.borderColor = "#087CC1"}
                      onBlur={e => e.target.style.borderColor = "#E5E7EB"}
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(v => !v)}
                      style={{
                        position: "absolute", right: "12px", top: "50%", transform: "translateY(-50%)",
                        background: "none", border: "none", cursor: "pointer", color: "#9CA3AF", padding: 0
                      }}
                      aria-label={showPassword ? "Hide password" : "Show password"}
                    >
                      {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                    </button>
                  </div>
                </div>

                <div>
                  <label htmlFor="phone" style={labelStyle}>
                    Phone Number
                  </label>
                  <input
                    id="phone"
                    type="tel"
                    required
                    autoComplete="tel"
                    value={form.phone}
                    onChange={(e) => update("phone", e.target.value)}
                    placeholder="+1 (555) 123-4567"
                    style={fieldStyle}
                    onFocus={e => e.target.style.borderColor = "#087CC1"}
                    onBlur={e => e.target.style.borderColor = "#E5E7EB"}
                  />
                </div>

                <div>
                  <label htmlFor="industry" style={labelStyle}>
                    Industry
                  </label>
                  <input
                    id="industry"
                    type="text"
                    value={form.industry}
                    onChange={(e) => update("industry", e.target.value)}
                    placeholder="Technology"
                    style={fieldStyle}
                    onFocus={e => e.target.style.borderColor = "#087CC1"}
                    onBlur={e => e.target.style.borderColor = "#E5E7EB"}
                  />
                </div>

                <div>
                  <label htmlFor="companyType" style={labelStyle}>
                    Company Type
                  </label>
                  <input
                    id="companyType"
                    type="text"
                    value={form.companyType}
                    onChange={(e) => update("companyType", e.target.value)}
                    placeholder="Private Limited"
                    style={fieldStyle}
                    onFocus={e => e.target.style.borderColor = "#087CC1"}
                    onBlur={e => e.target.style.borderColor = "#E5E7EB"}
                  />
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "18px" }}>
                <div>
                  <label htmlFor="country" style={labelStyle}>
                    Country
                  </label>
                  <select
                    id="country"
                    required
                    value={form.country}
                    onChange={(e) => handleCountryChange(e.target.value)}
                    style={selectStyle}
                    onFocus={e => e.target.style.borderColor = "#087CC1"}
                    onBlur={e => e.target.style.borderColor = "#E5E7EB"}
                  >
                    <option value="">Select country</option>
                    {REGISTRATION_COUNTRIES.map((c) => (
                      <option key={c} value={c}>{c}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label htmlFor="state" style={labelStyle}>
                    State / Province
                  </label>
                  <select
                    id="state"
                    value={form.state}
                    onChange={(e) => update("state", e.target.value)}
                    disabled={countryStates.length === 0}
                    style={{ ...selectStyle, cursor: countryStates.length === 0 ? "not-allowed" : "default" }}
                    onFocus={e => e.target.style.borderColor = "#087CC1"}
                    onBlur={e => e.target.style.borderColor = "#E5E7EB"}
                  >
                    <option value="">
                      {countryStates.length === 0 ? "Select country first" : "Select state"}
                    </option>
                    {countryStates.map((s) => (
                      <option key={s} value={s}>{s}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label htmlFor="city" style={labelStyle}>
                    City
                  </label>
                  <input
                    id="city"
                    type="text"
                    value={form.city}
                    onChange={(e) => update("city", e.target.value)}
                    placeholder="New York"
                    style={fieldStyle}
                    onFocus={e => e.target.style.borderColor = "#087CC1"}
                    onBlur={e => e.target.style.borderColor = "#E5E7EB"}
                  />
                </div>
              </div>

              {jurisdictionTaxFields.length > 0 ? (
                <div>
                  <div style={{ marginBottom: "12px" }}>
                    <p style={{ margin: "0 0 2px 0", fontSize: "14px", fontWeight: "600", color: "#111827" }}>
                      Business Registration & Tax Identification
                    </p>
                    <p style={{ margin: 0, fontSize: "12px", color: "#6B7280" }}>
                      {jurisdictionSchema.label} for payroll in {form.country}. Format is validated as you enter.
                    </p>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "18px" }}>
                    {jurisdictionTaxFields.map((f) => (
                      <div key={f.key}>
                        <label htmlFor={`reg-${f.key}`} style={labelStyle}>
                          {f.label} {f.primary && <span style={{ color: "#DC2626" }}>*</span>}
                        </label>
                        <input
                          id={`reg-${f.key}`}
                          type="text"
                          value={form.taxIdentifiers[f.key] || ""}
                          onChange={(e) => updateTaxIdentifier(f.key, e.target.value)}
                          placeholder={`e.g. ${f.example}`}
                          style={fieldStyle}
                          onFocus={e => e.target.style.borderColor = "#087CC1"}
                          onBlur={e => e.target.style.borderColor = "#E5E7EB"}
                        />
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div>
                  <label htmlFor="taxNo" style={labelStyle}>
                    Tax Registration Number
                  </label>
                  <input
                    id="taxNo"
                    type="text"
                    value={form.taxNo}
                    onChange={(e) => update("taxNo", e.target.value)}
                    placeholder="e.g. GSTIN, EIN, VAT No."
                    style={fieldStyle}
                    onFocus={e => e.target.style.borderColor = "#087CC1"}
                    onBlur={e => e.target.style.borderColor = "#E5E7EB"}
                  />
                </div>
              )}

              <div>
                <label htmlFor="address" style={labelStyle}>
                  Address
                </label>
                <textarea
                  id="address"
                  required
                  value={form.address}
                  onChange={(e) => update("address", e.target.value)}
                  placeholder="123 Main St, Suite 100"
                  rows={2}
                  style={{ ...fieldStyle, resize: "vertical", fontFamily: "inherit" }}
                  onFocus={e => e.target.style.borderColor = "#087CC1"}
                  onBlur={e => e.target.style.borderColor = "#E5E7EB"}
                />
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "18px" }}>
                <div>
                  <label htmlFor="timezone" style={labelStyle}>
                    Timezone
                  </label>
                  <select
                    id="timezone"
                    value={form.timezone}
                    onChange={(e) => update("timezone", e.target.value)}
                    disabled={countryTimezones.length === 0}
                    style={{ ...selectStyle, cursor: countryTimezones.length === 0 ? "not-allowed" : "default" }}
                    onFocus={e => e.target.style.borderColor = "#087CC1"}
                    onBlur={e => e.target.style.borderColor = "#E5E7EB"}
                  >
                    {countryTimezones.length === 0 ? (
                      <option value="">Select a country first</option>
                    ) : (
                      countryTimezones.map((tz) => (
                        <option key={tz} value={tz}>{tz}</option>
                      ))
                    )}
                  </select>
                </div>

                <div>
                  <label style={labelStyle}>
                    Product <span style={{ color: "#DC2626" }}>*</span>
                  </label>
                  <div
                    style={{
                      padding: "12px", borderRadius: "12px", textAlign: "center",
                      border: "2px solid #087CC1", background: "#EEF6FB",
                      boxShadow: "0 4px 12px rgba(8,124,193,0.15)",
                      boxSizing: "border-box", height: "calc(100% - 26px)", marginTop: "26px",
                    }}
                  >
                    <p style={{ margin: "0 0 4px 0", fontSize: "15px", fontWeight: "700", color: "#087CC1" }}>
                      Zoiko Payroll
                    </p>
                    <p style={{ margin: 0, fontSize: "11px", color: "#6B7280", lineHeight: "1.3" }}>
                      Pay runs, statutory rates & payslips
                    </p>
                  </div>
                </div>
              </div>

              <div style={{ display: "flex", alignItems: "flex-start", gap: "10px" }}>
                <input
                  id="termsAccepted"
                  type="checkbox"
                  required
                  checked={form.termsAccepted}
                  onChange={(e) => update("termsAccepted", e.target.checked)}
                  style={{
                    marginTop: "2px", width: "16px", height: "16px", flexShrink: 0,
                    accentColor: "#087CC1", cursor: "pointer"
                  }}
                />
                <label htmlFor="termsAccepted" style={{ fontSize: "13px", color: "#374151", cursor: "pointer", lineHeight: "1.4" }}>
                  I accept the{" "}
                  <a href="https://zoikoone.com" target="_blank" rel="noopener noreferrer" style={{ color: "#087CC1", fontWeight: "600", textDecoration: "none" }}>
                    Terms & Conditions
                  </a>
                </label>
              </div>

              <button
                type="submit"
                disabled={submitting}
                style={{
                  width: "100%", padding: "13px", borderRadius: "10px", border: "none",
                  fontSize: "15px", fontWeight: "700", color: "white", cursor: submitting ? "not-allowed" : "pointer",
                  background: submitting ? "#7EC1E0" : "linear-gradient(135deg, #087CC1, #1596D1)",
                  boxShadow: "0 6px 20px rgba(8,124,193,0.35)",
                  display: "flex", alignItems: "center", justifyContent: "center", gap: "8px",
                  transition: "all 0.2s", marginTop: "8px"
                }}
              >
                {submitting && <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} />}
                {submitting ? "Creating account…" : `Create account & continue to payment`}
              </button>
            </form>

            <p style={{ textAlign: "center", fontSize: "13px", color: "#6B7280", marginTop: "20px", marginBottom: 0 }}>
              Not ready to commit?{" "}
              <Link to="/trial-register" style={{ color: "#087CC1", fontWeight: "600", textDecoration: "none" }}>
                Try Zoiko Payroll free for 30 days
              </Link>
            </p>
          </div>

          <p style={{ textAlign: "center", marginTop: "20px" }}>
            <Link to="/login" style={{ fontSize: "13px", color: "#9CA3AF", textDecoration: "none" }}>
              ← Back to sign in
            </Link>
          </p>
        </div>
        )}
      </div>

      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
      `}</style>
      <Footer />
    </div>
  );
}
