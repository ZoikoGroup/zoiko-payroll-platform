import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, ArrowRight, Lock } from "lucide-react";
import { apiFetch, setSession, API_BASE } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { getDefaultTimezoneForCountry } from "../utils/registrationRegions";
import { getJurisdictionTaxFields, primaryTaxValue } from "../utils/jurisdictionTax";
import SignupLayout from "../components/auth/SignupLayout";
import StepIndicator from "../components/auth/StepIndicator";
import { dialCodeForCountry, phoneCountryOrDefault } from "../components/auth/PhoneInput";
import { AuthAlert, AuthPrimaryButton } from "../components/auth/authUi";
import MfaLoginStep from "../components/MfaLoginStep";
import SocialSignInButtons from "../components/auth/SocialSignInButtons";
import OrganizationStep from "../components/auth/register/OrganizationStep";
import AdministratorStep from "../components/auth/register/AdministratorStep";
import ReviewStep from "../components/auth/register/ReviewStep";
import PlanStep, { usePublishedPlans } from "../components/auth/register/PlanStep";
import { EMPTY_FORM, clearDraft, loadDraft, saveDraft } from "../components/auth/register/registerDraft";
import { STEP_FIELDS, firstIncompleteStep, validateStep } from "../components/auth/register/registerValidation";

// Create-account wizard: one step per screen.
//
//   1 Organization → 2 Administrator (+ setup preferences) → 3 Review → 4 Plan
//
// The step lives in the URL (?step=2) so the browser's back/forward buttons
// move between steps. A step can only be opened once every earlier step is
// valid; asking for a later one (a bookmarked URL, or a refresh that lost
// the password) lands on the first step that still needs input. What was
// typed is kept in sessionStorage (never the password — see registerDraft).
// "Continue" validates the current step only, and errors appear inline under
// each field instead of the browser's validation bubbles.

const STEPS = ["Organization", "Administrator", "Review", "Plan"];
const LAST_STEP = STEPS.length;

const PROVIDER_LABELS = { google: "Google" };

function parseStep(value) {
  const n = Number.parseInt(value, 10);
  return Number.isInteger(n) && n >= 1 && n <= LAST_STEP ? n : 1;
}

/** Presentation details for a social sign-up held in the draft. */
function describeSocial(social) {
  if (!social?.pendingToken) return null;
  return {
    ...social,
    label: PROVIDER_LABELS[social.provider] || social.provider,
    emailEditable: false,
  };
}

/** DOM id of the control for a validation error key (see STEP_FIELDS). */
function controlIdFor(key) {
  return key.startsWith("tax:") ? `reg-${key.slice(4)}` : key;
}

export default function RegisterPage() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();

  const [initialDraft] = useState(loadDraft);
  const [form, setForm] = useState(() => initialDraft?.form || { ...EMPTY_FORM });
  const [selectedPlanCode, setSelectedPlanCode] = useState(() => initialDraft?.planCode || null);
  const [socialDraft, setSocialDraft] = useState(() => initialDraft?.social || null);
  const [errors, setErrors] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [localError, setLocalError] = useState(null);
  // ZP-PRIV B08: a new organization admin sets up MFA before the first session.
  const [mfaStep, setMfaStep] = useState(null);
  const finishedRef = useRef(false);
  const headingRef = useRef(null);

  const { plans, loading: plansLoading, error: plansError } = usePublishedPlans();

  const social = describeSocial(socialDraft);
  const validationOptions = { passwordless: Boolean(social), emailEditable: !social || social.emailEditable };

  // ── Step from the URL, gated on the earlier steps being complete ─────────
  const requestedStep = parseStep(searchParams.get("step"));
  const incomplete = firstIncompleteStep(form, validationOptions);
  const maxAllowedStep = incomplete ?? LAST_STEP;
  const step = Math.min(requestedStep, maxAllowedStep);
  const pendingTokenInUrl = searchParams.get("pending") || "";
  // A refresh drops the password (it is never stored); say why the admin is
  // back on step 2 instead of leaving them guessing. Latched in state because
  // the URL is corrected to ?step=2 straight away.
  const [passwordLost, setPasswordLost] = useState(false);
  if (requestedStep > 2 && step === 2 && !social && !form.password && !passwordLost) {
    setPasswordLost(true);
  }
  if (passwordLost && form.password) setPasswordLost(false);

  useEffect(() => {
    if (pendingTokenInUrl) return; // handled below
    if (String(step) !== searchParams.get("step")) {
      setSearchParams({ step: String(step) }, { replace: true });
    }
  }, [step, searchParams, setSearchParams, pendingTokenInUrl]);

  // ── Social sign-up: the provider callback lands here with ?pending= ──────
  // Pre-fill name + email from the held profile, then drop the token from
  // the address bar (it stays in the per-tab draft) and continue at the first
  // step that still needs input — org details typed before choosing the
  // provider survive the round trip through the draft.
  const handledPendingRef = useRef("");
  useEffect(() => {
    if (!pendingTokenInUrl || handledPendingRef.current === pendingTokenInUrl) return undefined;
    handledPendingRef.current = pendingTokenInUrl;
    let cancelled = false;
    const provider = "google";
    const emailFromUrl = searchParams.get("email") || "";
    const nextSocial = { provider, pendingToken: pendingTokenInUrl, email: emailFromUrl };

    fetch(`${API_BASE}/api/auth/google/pending/${encodeURIComponent(pendingTokenInUrl)}`, { credentials: "include" })
      .then(async (res) => (res.ok ? res.json() : {}))
      .catch(() => ({}))
      .then((profile) => {
        if (cancelled) return;
        // Expired/used token: keep the email from the redirect; the server
        // explains on submit that the sign-up must be restarted.
        const email = profile.email || emailFromUrl;
        const merged = {
          ...form,
          firstName: profile.given_name || form.firstName,
          lastName: profile.family_name || form.lastName,
          adminEmail: email || form.adminEmail,
          password: "",
        };
        setForm(merged);
        setSocialDraft({ ...nextSocial, email });
        const firstOpen = firstIncompleteStep(merged, { passwordless: true, emailEditable: false }) ?? 3;
        setSearchParams({ step: String(firstOpen) }, { replace: true });
      });
    return () => { cancelled = true; };
    // `form` is read once, at the moment the provider returns.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingTokenInUrl]);

  // ── Draft persistence ────────────────────────────────────────────────────
  useEffect(() => {
    if (finishedRef.current) return;
    saveDraft({ form, planCode: selectedPlanCode, social: socialDraft });
  }, [form, selectedPlanCode, socialDraft]);

  // A new step starts at the top of the card (desktop) / page (mobile), with
  // focus on its heading for screen readers. Not on first load: the page
  // opens at its natural top.
  const shownStepRef = useRef(step);
  useEffect(() => {
    if (shownStepRef.current === step) return;
    shownStepRef.current = step;
    document.getElementById("register-scroll")?.scrollTo?.({ top: 0 });
    window.scrollTo?.({ top: 0 });
    headingRef.current?.focus?.({ preventScroll: true });
  }, [step]);

  // ── Field updates ────────────────────────────────────────────────────────
  const clearError = useCallback((key) => {
    setErrors((e) => {
      if (!(key in e)) return e;
      const next = { ...e };
      delete next[key];
      return next;
    });
  }, []);

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
    clearError(field === "phoneNumber" ? "phone" : field);
  }

  function updateTaxIdentifier(key, value) {
    setForm((f) => ({ ...f, taxIdentifiers: { ...f.taxIdentifiers, [key]: value } }));
    clearError(`tax:${key}`);
  }

  function handleCountryChange(value) {
    setForm((f) => ({
      ...f,
      country: value,
      state: "",
      timezone: getDefaultTimezoneForCountry(value),
      taxIdentifiers: {},
      // The calling code follows the organization's country until the admin
      // picks one by hand.
      phoneCountry: f.phoneCountryTouched ? f.phoneCountry : value,
    }));
    setErrors((e) => {
      const next = {};
      for (const [key, message] of Object.entries(e)) {
        if (key !== "country" && !key.startsWith("tax:")) next[key] = message;
      }
      return next;
    });
  }

  function handlePhoneCountryChange(value) {
    setForm((f) => ({ ...f, phoneCountry: value, phoneCountryTouched: true }));
  }

  function cancelSocial() {
    setSocialDraft(null);
    setForm((f) => ({ ...f, adminEmail: "" }));
    setErrors({});
  }

  // ── Navigation ───────────────────────────────────────────────────────────
  function goToStep(target) {
    setLocalError(null);
    setErrors({});
    setSearchParams({ step: String(target) });
  }

  function focusFirstError(stepErrors) {
    const order = STEP_FIELDS[step] || [];
    const keys = Object.keys(stepErrors);
    const first = order.find((k) => keys.includes(k)) || keys.find((k) => k.startsWith("tax:")) || keys[0];
    if (!first) return;
    window.requestAnimationFrame(() => {
      const el = document.getElementById(controlIdFor(first));
      el?.focus?.();
      el?.scrollIntoView?.({ block: "center", behavior: "smooth" });
    });
  }

  function handleContinue(e) {
    e?.preventDefault?.();
    setLocalError(null);
    if (step === LAST_STEP) {
      handleCreate();
      return;
    }
    const stepErrors = validateStep(step, form, validationOptions);
    if (Object.keys(stepErrors).length) {
      setErrors(stepErrors);
      focusFirstError(stepErrors);
      return;
    }
    // Entering step 2: make sure the calling code matches the country now,
    // including drafts saved before the code followed the country.
    if (step === 1 && !form.phoneCountryTouched && form.phoneCountry !== form.country) {
      setForm((f) => ({ ...f, phoneCountry: f.country }));
    }
    goToStep(step + 1);
  }

  // ── Create the account (step 4) ──────────────────────────────────────────
  const selectedPlan = selectedPlanCode ? plans[selectedPlanCode] : null;
  const fullName = `${form.firstName.trim()} ${form.lastName.trim()}`.trim();
  const phoneCountry = phoneCountryOrDefault(form.phoneCountry || form.country);
  const phone = form.phoneNumber.trim() ? `${dialCodeForCountry(phoneCountry)} ${form.phoneNumber.trim()}` : "";

  async function handleCreate() {
    setLocalError(null);
    if (!selectedPlanCode) {
      setLocalError("Please choose a plan before creating your account.");
      return;
    }
    setSubmitting(true);
    try {
      const hasTaxIdentifiers = getJurisdictionTaxFields(form.country).length > 0;
      const body = {
        organization: form.orgName,
        name: fullName,
        email: form.adminEmail,
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
      };
      // Google Sign-Up: no password (Google is the IdP). The server takes the
      // Google identity and verified email from the pending token — never
      // from this request — and consumes the token once the account exists.
      if (social) {
        body.auth_provider = social.provider;
        body.google_pending_token = social.pendingToken;
      } else {
        body.password = form.password;
      }
      const data = await apiFetch("/api/auth/register", { method: "POST", body });

      // The account exists from here on: the draft has done its job.
      finishedRef.current = true;
      clearDraft();

      // Log the browser in immediately so PlanReviewPage's checkout call
      // (which requires a real org-admin JWT) works with no separate login
      // step in between.
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

    // Checkout itself happens on PlanReviewPage, not here — it's the one
    // place that reviews the plan and computes the actual
    // service_commencement_at before ever calling /billing/checkout. Pass
    // the already-fetched plan card along so that page doesn't need a
    // second GET /billing/plans round-trip.
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

  const continueLabel = {
    1: "Continue",
    2: "Continue to review",
    3: "Continue to choose plan",
    4: selectedPlan ? `Create account with ${selectedPlan.name}` : "Select a plan to continue",
  }[step];

  const footer = (
    <div className="flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-end sm:gap-3">
      {step > 1 && (
        <button
          type="button"
          onClick={() => goToStep(step - 1)}
          className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-300 px-5 py-3 text-[15px] font-semibold text-slate-700 hover:bg-slate-50 sm:mr-auto"
        >
          <ArrowLeft size={17} aria-hidden="true" /> Back
        </button>
      )}
      <AuthPrimaryButton
        type="submit"
        form="register-form"
        className="px-6 sm:w-auto sm:min-w-56"
        disabled={step === LAST_STEP && !selectedPlan}
        busy={submitting}
        busyLabel="Creating account…"
      >
        {continueLabel} {step < LAST_STEP && <ArrowRight size={18} aria-hidden="true" />}
      </AuthPrimaryButton>
    </div>
  );

  return (
    <SignupLayout footer={footer}>
      <div className="mb-4">
        <h2 className="text-[22px] font-extrabold leading-tight tracking-[-0.02em] text-slate-900">
          Create your Zoiko Payroll account
        </h2>
        {step === 1 && (
          <p className="mt-0.5 text-[14px] text-slate-600">
            Set up your organization to start running global payroll in minutes.
          </p>
        )}
      </div>

      {/* Sign-up method: provider buttons first, then the email divider. */}
      {step === 1 && !social && (
        <>
          <SocialSignInButtons mode="register" />
          <div className="my-3 flex items-center gap-3 text-[13px] text-blue-700">
            <span className="h-px flex-1 bg-slate-200" />
            <span>or sign up with email</span>
            <span className="h-px flex-1 bg-slate-200" />
          </div>
        </>
      )}
      {social && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-blue-100 bg-blue-50 px-4 py-2.5 text-[13px] text-blue-800">
          <span>
            Signing up with {social.label}{social.email ? <> as <strong>{social.email}</strong></> : null}. No password
            needed — {social.label} handles sign-in for this account.
          </span>
          <button type="button" onClick={cancelSocial} className="font-semibold text-blue-700 underline-offset-2 hover:underline">
            Use email instead
          </button>
        </div>
      )}

      <div className="mb-4">
        <StepIndicator steps={STEPS} current={step} onStepClick={goToStep} />
      </div>

      {passwordLost && (
        <AuthAlert tone="warning">For your security the password isn&apos;t saved when the page reloads. Please enter it again.</AuthAlert>
      )}
      {localError && <AuthAlert>{localError}</AuthAlert>}

      <form id="register-form" noValidate onSubmit={handleContinue} aria-labelledby="register-step-title">
        <div ref={headingRef} tabIndex={-1} id="register-step-title" className="sr-only scroll-mt-4">
          Step {step} of {LAST_STEP}: {STEPS[step - 1]}
        </div>
        {step === 1 && (
          <OrganizationStep form={form} errors={errors} onChange={update}
            onCountryChange={handleCountryChange} onTaxChange={updateTaxIdentifier} />
        )}
        {step === 2 && (
          <AdministratorStep form={{ ...form, phoneCountry }} errors={errors} onChange={update}
            onPhoneCountryChange={handlePhoneCountryChange} social={social} />
        )}
        {step === 3 && (
          <ReviewStep form={form} phone={phone} social={social} selectedPlan={selectedPlan} onEditStep={goToStep} />
        )}
        {step === 4 && (
          <PlanStep plans={plans} plansLoading={plansLoading} plansError={plansError}
            selectedCode={selectedPlanCode} onSelectPlan={(code) => { setSelectedPlanCode(code); setLocalError(null); }} />
        )}
      </form>

      <p className="mt-6 flex flex-wrap items-center justify-center gap-1.5 text-center text-[12px] text-slate-500">
        <Lock size={13} aria-hidden="true" />
        Your information is sent over an encrypted connection and kept secure.
        {step < LAST_STEP && (
          <span>
            Prefer to try first?{" "}
            <Link to="/trial-register" className="font-medium text-blue-700 hover:underline">Start a 30-day evaluation</Link>.
          </span>
        )}
      </p>
    </SignupLayout>
  );
}
