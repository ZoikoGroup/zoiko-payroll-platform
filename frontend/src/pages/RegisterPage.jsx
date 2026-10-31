import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowLeft, ArrowRight, Building, Building2, Check, ChevronDown, ClipboardCheck, Clock, Eye, EyeOff, Factory,
  FileText, Globe2, Info, Landmark, Loader2, Lock, Mail, MapPin, Settings, Sparkles, UserRound, X,
} from "lucide-react";
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
import AuthLayout, { AUTH_FOOTER_LINKS } from "../components/auth/AuthLayout";
import SignupLayout from "../components/auth/SignupLayout";
import StepIndicator from "../components/auth/StepIndicator";
import PhoneInput, { dialCodeForCountry } from "../components/auth/PhoneInput";
import { AuthAlert, AuthPrimaryButton, authInputClass } from "../components/auth/authUi";
import MfaLoginStep from "../components/MfaLoginStep";
import { COUNTRY_LIMIT_KEY, formatCountryLimit } from "../utils/planLimits";

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

const CAPABILITY_LABELS = [
  ["payroll_runs", "Payroll runs"],
  ["multi_entity", "Multi-entity payroll"],
  ["multi_currency", "Multi-currency"],
  ["api_access", "API access"],
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

const COMPANY_TYPES = [
  "Private Limited", "Public Limited", "Limited Liability Company (LLC)", "Sole Proprietorship",
  "Partnership", "Corporation", "Non-profit", "Government / Public sector", "Other",
];
const INDUSTRIES = [
  "Technology", "Telecommunications", "Financial Services", "Healthcare", "Manufacturing",
  "Retail & E-commerce", "Professional Services", "Education", "Construction", "Hospitality",
  "Transport & Logistics", "Energy & Utilities", "Media & Entertainment", "Non-profit", "Other",
];
const STEPS = ["Organization", "Administrator", "Review & confirm"];

// Mirrors the API's registration rule (backend auth/schemas.py).
const PASSWORD_CHECKS = [
  ["At least 12 characters", (p) => p.length >= 12],
  ["A letter", (p) => /[A-Za-z]/.test(p)],
  ["A number", (p) => /[0-9]/.test(p)],
  ["A symbol", (p) => /[^A-Za-z0-9]/.test(p)],
];
const passwordOk = (p) => PASSWORD_CHECKS.every(([, test]) => test(p));

const INPUT = authInputClass({ withIcon: true });
const SELECT = `${authInputClass({ withIcon: true, withTrailing: true })} appearance-none disabled:cursor-not-allowed disabled:bg-slate-50`;

function Section({ icon: Icon, title, subtitle, children }) {
  return (
    <section className="rounded-xl border border-slate-200 p-4 sm:p-5">
      <div className="mb-4 flex items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
          <Icon size={20} aria-hidden="true" />
        </span>
        <div>
          <h3 className="text-[17px] font-bold text-slate-900">{title}</h3>
          <p className="text-[13px] text-slate-500">{subtitle}</p>
        </div>
      </div>
      {children}
    </section>
  );
}

function Field({ id, label, required, info, hint, className = "", children }) {
  return (
    <div className={className}>
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <label htmlFor={id} className="text-[13px] font-semibold text-slate-800">
          {label}{required && <span className="text-red-600"> *</span>}
        </label>
        {info && <Info size={15} className="shrink-0 text-slate-500" aria-label={info} title={info} />}
      </div>
      {children}
      {hint && <div className="mt-1.5 text-[12px] text-slate-500">{hint}</div>}
    </div>
  );
}

function IconInput({ icon: Icon, ...props }) {
  return (
    <div className="relative">
      <Icon size={17} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-500" />
      <input {...props} className={INPUT} />
    </div>
  );
}

function IconSelect({ icon: Icon, children, ...props }) {
  return (
    <div className="relative">
      <Icon size={17} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-500" />
      <select {...props} className={SELECT}>{children}</select>
      <ChevronDown size={16} className="pointer-events-none absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-500" />
    </div>
  );
}

function ReviewRow({ label, value }) {
  return (
    <div className="grid grid-cols-[150px_1fr] gap-3 py-1.5 text-[14px]">
      <dt className="text-slate-500">{label}</dt>
      <dd className="break-words text-slate-900">{value || <span className="text-slate-400">—</span>}</dd>
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
    companyType: "",
    industry: "",
    country: "",
    state: "",
    city: "",
    address: "",
    taxNo: "",
    taxIdentifiers: {},
    firstName: "",
    lastName: "",
    adminEmail: "",
    phoneCountry: "United States",
    phoneNumber: "",
    password: "",
    timezone: "",
    termsAccepted: false,
  });
  const [showPassword, setShowPassword] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [localError, setLocalError] = useState(null);
  // ZP-PRIV B08: a new organization admin sets up MFA before the first session.
  const [mfaStep, setMfaStep] = useState(null);

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
      // Follow the organisation's country until the admin types a number.
      phoneCountry: f.phoneNumber ? f.phoneCountry : (value || f.phoneCountry),
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
  const fullName = `${form.firstName.trim()} ${form.lastName.trim()}`.trim();
  const phone = form.phoneNumber.trim() ? `${dialCodeForCountry(form.phoneCountry)} ${form.phoneNumber.trim()}` : "";
  const orgComplete = Boolean(form.orgName.trim() && form.companyType && form.industry && form.country
    && form.address.trim());
  const currentStep = reviewing ? 3 : orgComplete ? 2 : 1;

  function handleContinue(e) {
    e.preventDefault();
    setLocalError(null);
    const taxValidationErrors = validateJurisdictionTaxIds(form.country, form.taxIdentifiers);
    if (taxValidationErrors.length) {
      setLocalError(taxValidationErrors[0].message);
      return;
    }
    if (!passwordOk(form.password)) {
      setLocalError("Password must be at least 12 characters and include a letter, a number and a symbol.");
      return;
    }
    setReviewing(true);
    window.scrollTo?.({ top: 0, behavior: "smooth" });
  }

  async function handleCreate() {
    setLocalError(null);
    setSubmitting(true);
    try {
      const hasTaxIdentifiers = jurisdictionTaxFields.length > 0;
      const data = await apiFetch("/api/auth/register", {
        method: "POST",
        body: {
          organization: form.orgName,
          name: fullName,
          email: form.adminEmail,
          password: form.password,
          phone,
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
          plan_code: selectedPlanCode,
        },
      });

      // Account exists from here on — log the browser in immediately so
      // PlanReviewPage's checkout call (which requires a real org-admin
      // JWT) works with no separate login step in between.
      if (data.mfa_enrollment_required) {
        setMfaStep({ mfaToken: data.mfa_token });
        return;
      }
      await finishRegistration(data);
    } catch (err) {
      setLocalError(err.message || "Unable to create your account.");
    } finally {
      setSubmitting(false);
    }
  }

  async function finishRegistration(data) {
      setSession(data);
      await login(data.user);

      // Checkout itself now happens on PlanReviewPage, not here — it's the
      // one place that reviews the plan and computes the actual
      // service_commencement_at before ever calling /billing/checkout.
      // Pass the already-fetched plan card along so that page doesn't need
      // a second GET /billing/plans round-trip.
      navigate("/register/plan-review", { state: { planCode: selectedPlanCode, plan: selectedPlan } });
  }

  if (mfaStep) {
    return (
      <SignupLayout>
        <div className="mx-auto w-full max-w-md py-4">
          <MfaLoginStep
            mode="enroll"
            mfaToken={mfaStep.mfaToken}
            onComplete={(session) => finishRegistration(session)}
            onCancel={() => navigate("/login")}
          />
        </div>
      </SignupLayout>
    );
  }

  if (stage === "plan") {
    return (
      <AuthLayout wide>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
          <PlanPickerStage
            plans={plans}
            plansLoading={plansLoading}
            plansError={plansError}
            onChoosePlan={handleChoosePlan}
          />
        </div>
        <style>{`
          @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        `}</style>
      </AuthLayout>
    );
  }

  const termsLink = AUTH_FOOTER_LINKS.find((l) => l.label === "Terms")?.href;
  const privacyLink = AUTH_FOOTER_LINKS.find((l) => l.label === "Privacy")?.href;

  return (
    <SignupLayout>
      <div className="mb-4 flex items-start gap-4">
        <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-700">
          <Building2 size={26} aria-hidden="true" />
        </span>
        <div className="min-w-0">
          <h2 className="text-[26px] font-extrabold leading-tight tracking-[-0.02em] text-slate-900">
            Create your Zoiko Payroll account
          </h2>
          <p className="mt-1 text-[15px] text-slate-600">
            Set up your organization to start running global payroll in minutes.
          </p>
        </div>
      </div>

      {selectedPlan && (
        <button
          type="button"
          onClick={() => { setReviewing(false); setStage("plan"); }}
          className="mb-4 inline-flex items-center gap-2 rounded-full border border-slate-200 px-3.5 py-1.5 text-[13px] text-slate-700 hover:bg-slate-50"
        >
          <ArrowLeft size={13} aria-hidden="true" />
          Plan: <strong className="text-blue-700">{selectedPlan.name}</strong> ({selectedPlan.priceLabel}) · change
        </button>
      )}

      <div className="mb-5 sm:pl-[4.5rem]">
        <StepIndicator steps={STEPS} current={currentStep} />
      </div>

      {localError && <AuthAlert>{localError}</AuthAlert>}

      {reviewing ? (
        <div className="space-y-4">
          <Section icon={ClipboardCheck} title="Review & confirm" subtitle="Check your details before we create the account.">
            <dl className="divide-y divide-slate-100">
              <ReviewRow label="Organization" value={form.orgName} />
              <ReviewRow label="Company type" value={form.companyType} />
              <ReviewRow label="Industry" value={form.industry} />
              <ReviewRow label="Location" value={[form.address, form.city, form.state, form.country].filter(Boolean).join(", ")} />
              {jurisdictionTaxFields.length > 0
                ? jurisdictionTaxFields.map((f) => (
                  <ReviewRow key={f.key} label={f.label} value={form.taxIdentifiers[f.key]} />))
                : <ReviewRow label="Tax registration" value={form.taxNo} />}
              <ReviewRow label="Administrator" value={fullName} />
              <ReviewRow label="Work email" value={form.adminEmail} />
              <ReviewRow label="Phone" value={phone} />
              <ReviewRow label="Password" value="••••••••••••" />
              <ReviewRow label="Timezone" value={form.timezone} />
              <ReviewRow label="Product" value="Zoiko Payroll" />
              <ReviewRow label="Plan" value={selectedPlan ? `${selectedPlan.name} (${selectedPlan.priceLabel})` : ""} />
            </dl>
          </Section>
          <div className="flex flex-col-reverse gap-3 sm:flex-row">
            <button
              type="button"
              onClick={() => setReviewing(false)}
              className="rounded-lg border border-slate-300 px-5 py-3 text-[15px] font-semibold text-slate-700 hover:bg-slate-50 sm:w-40"
            >
              Edit details
            </button>
            <AuthPrimaryButton type="button" busy={submitting} busyLabel="Creating account…" onClick={handleCreate}>
              Create account &amp; continue <ArrowRight size={18} aria-hidden="true" />
            </AuthPrimaryButton>
          </div>
        </div>
      ) : (
        <form onSubmit={handleContinue} className="space-y-4">
          <Section icon={Building2} title="Organization details" subtitle="Tell us about your company.">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field id="orgName" label="Organization name" required>
                <IconInput icon={Building} id="orgName" required autoComplete="organization"
                  value={form.orgName} onChange={(e) => update("orgName", e.target.value)} placeholder="e.g. Zoiko Telecom" />
              </Field>
              <Field id="companyType" label="Company type" required>
                <IconSelect icon={FileText} id="companyType" required value={form.companyType}
                  onChange={(e) => update("companyType", e.target.value)}>
                  <option value="">Select company type</option>
                  {COMPANY_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </IconSelect>
              </Field>
              <Field id="industry" label="Industry" required>
                <IconSelect icon={Factory} id="industry" required value={form.industry}
                  onChange={(e) => update("industry", e.target.value)}>
                  <option value="">Select industry</option>
                  {INDUSTRIES.map((t) => <option key={t} value={t}>{t}</option>)}
                </IconSelect>
              </Field>
            </div>
            <div className="mt-4 grid gap-4 sm:grid-cols-3">
              <Field id="country" label="Country" required>
                <IconSelect icon={Globe2} id="country" required value={form.country}
                  onChange={(e) => handleCountryChange(e.target.value)}>
                  <option value="">Select a country</option>
                  {REGISTRATION_COUNTRIES.map((c) => <option key={c} value={c}>{c}</option>)}
                </IconSelect>
              </Field>
              <Field id="state" label="State / Province">
                <IconSelect icon={MapPin} id="state" value={form.state} disabled={countryStates.length === 0}
                  onChange={(e) => update("state", e.target.value)}>
                  <option value="">{countryStates.length === 0 ? (form.country ? "Not applicable" : "Select a country first") : "Select a state"}</option>
                  {countryStates.map((s) => <option key={s} value={s}>{s}</option>)}
                </IconSelect>
              </Field>
              <Field id="city" label="City">
                <IconInput icon={Landmark} id="city" value={form.city} autoComplete="address-level2"
                  onChange={(e) => update("city", e.target.value)} placeholder="e.g. New York" />
              </Field>
            </div>
            <Field id="address" label="Address" required className="mt-4">
              <IconInput icon={MapPin} id="address" required autoComplete="street-address" value={form.address}
                onChange={(e) => update("address", e.target.value)} placeholder="e.g. 123 Main St, Suite 100" />
            </Field>
            {jurisdictionTaxFields.length > 0 ? (
              <div className="mt-4">
                <div className="mb-1.5 flex items-center justify-between gap-2">
                  <span className="text-[13px] font-semibold text-slate-800">Tax registration</span>
                  <Info size={15} className="text-slate-500"
                    aria-label={`${jurisdictionSchema.label} for payroll in ${form.country}. Format is checked as you type.`}
                    title={`${jurisdictionSchema.label} for payroll in ${form.country}. Format is checked as you type.`} />
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  {jurisdictionTaxFields.map((f) => (
                    <Field key={f.key} id={`reg-${f.key}`} label={f.label} required={f.primary}>
                      <IconInput icon={FileText} id={`reg-${f.key}`} value={form.taxIdentifiers[f.key] || ""}
                        onChange={(e) => updateTaxIdentifier(f.key, e.target.value)} placeholder={`e.g. ${f.example}`} />
                    </Field>
                  ))}
                </div>
              </div>
            ) : (
              <Field id="taxNo" label="Tax registration number" className="mt-4"
                info="Your company's tax or business registration number for payroll filings.">
                <IconInput icon={FileText} id="taxNo" value={form.taxNo} onChange={(e) => update("taxNo", e.target.value)}
                  placeholder="e.g. GSTIN, EIN, VAT No." />
              </Field>
            )}
          </Section>

          <Section icon={UserRound} title="Administrator details" subtitle="This will be your primary administrator account.">
            <div className="grid gap-4 sm:grid-cols-3">
              <Field id="firstName" label="First name" required>
                <IconInput icon={UserRound} id="firstName" required autoComplete="given-name" value={form.firstName}
                  onChange={(e) => update("firstName", e.target.value)} placeholder="e.g. Lennox" />
              </Field>
              <Field id="lastName" label="Last name" required>
                <IconInput icon={UserRound} id="lastName" required autoComplete="family-name" value={form.lastName}
                  onChange={(e) => update("lastName", e.target.value)} placeholder="e.g. Green" />
              </Field>
              <Field id="adminEmail" label="Work email" required>
                <IconInput icon={Mail} id="adminEmail" type="email" required autoComplete="email" value={form.adminEmail}
                  onChange={(e) => update("adminEmail", e.target.value)} placeholder="e.g. lennox@company.com" />
              </Field>
            </div>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <Field id="phone" label="Phone number" required>
                <PhoneInput id="phone" country={form.phoneCountry} onCountryChange={(v) => update("phoneCountry", v)}
                  number={form.phoneNumber} onNumberChange={(v) => update("phoneNumber", v)} />
              </Field>
              <Field id="password" label="Password" required
                hint={
                  <ul className="flex flex-wrap gap-x-3 gap-y-1">
                    {PASSWORD_CHECKS.map(([label, test]) => {
                      const ok = test(form.password);
                      return (
                        <li key={label} className={`inline-flex items-center gap-1 ${ok ? "text-emerald-700" : ""}`}>
                          {ok ? <Check size={13} aria-hidden="true" /> : <span aria-hidden="true">•</span>} {label}
                        </li>
                      );
                    })}
                  </ul>
                }>
                <div className="relative">
                  <Lock size={17} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-500" />
                  <input id="password" type={showPassword ? "text" : "password"} required minLength={12}
                    autoComplete="new-password" value={form.password} onChange={(e) => update("password", e.target.value)}
                    placeholder="Create a strong password" className={authInputClass({ withIcon: true, withTrailing: true })} />
                  <button type="button" onClick={() => setShowPassword((v) => !v)}
                    aria-label={showPassword ? "Hide password" : "Show password"}
                    className="absolute right-3 top-1/2 -translate-y-1/2 rounded p-1 text-slate-500 hover:text-slate-800">
                    {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </Field>
            </div>
          </Section>

          <Section icon={Settings} title="Setup preferences" subtitle="Tailor your account to your needs.">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field id="timezone" label="Timezone" required={countryTimezones.length > 0}>
                <IconSelect icon={Clock} id="timezone" value={form.timezone} required={countryTimezones.length > 0}
                  disabled={countryTimezones.length === 0} onChange={(e) => update("timezone", e.target.value)}>
                  {countryTimezones.length === 0
                    ? <option value="">Select a country first</option>
                    : countryTimezones.map((tz) => <option key={tz} value={tz}>{tz}</option>)}
                </IconSelect>
              </Field>
              <Field id="product" label="Product" required>
                <div id="product" role="radio" aria-checked="true" tabIndex={0}
                  className="flex items-center gap-3 rounded-lg border-2 border-blue-600 bg-blue-50 px-4 py-2.5">
                  <span className="flex h-4 w-4 items-center justify-center rounded-full border-2 border-blue-600">
                    <span className="h-2 w-2 rounded-full bg-blue-600" />
                  </span>
                  <span>
                    <span className="block text-[14px] font-semibold text-blue-800">Zoiko Payroll</span>
                    <span className="block text-[12px] text-slate-600">Pay runs, statutory rates &amp; payslips</span>
                  </span>
                </div>
              </Field>
            </div>
            <label className="mt-4 flex cursor-pointer items-start gap-2.5 text-[14px] text-slate-700">
              <input type="checkbox" required checked={form.termsAccepted}
                onChange={(e) => update("termsAccepted", e.target.checked)}
                className="mt-0.5 h-4 w-4 shrink-0 rounded border-slate-300 accent-blue-600" />
              <span>
                I agree to the{" "}
                <a href={termsLink} target="_blank" rel="noopener noreferrer" className="font-medium text-blue-700 hover:underline">Terms of Service</a>
                {" "}and{" "}
                <a href={privacyLink} target="_blank" rel="noopener noreferrer" className="font-medium text-blue-700 hover:underline">Privacy Policy</a>.
                <span className="text-red-600"> *</span>
              </span>
            </label>
          </Section>

          <AuthPrimaryButton type="submit">
            Continue to review <ArrowRight size={18} aria-hidden="true" />
          </AuthPrimaryButton>
        </form>
      )}

      <p className="mt-4 flex flex-wrap items-center justify-center gap-1.5 text-center text-[12px] text-slate-500">
        <Lock size={13} aria-hidden="true" />
        Your information is sent over an encrypted connection and kept secure.
        <span>
          Prefer to try first?{" "}
          <Link to="/trial-register" className="font-medium text-blue-700 hover:underline">Start a 30-day evaluation</Link>.
        </span>
      </p>
    </SignupLayout>
  );
}
