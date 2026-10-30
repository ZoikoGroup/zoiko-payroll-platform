import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Eye, EyeOff, Lock, Mail } from "lucide-react";
import { apiFetch, setSession } from "../api/client";
import { ROLE_DEFAULT_REDIRECT, VALID_ROLES } from "../config/roles";
import { useAuth } from "../context/AuthContext";
import PublicAssistWidget from "../modules/assist/PublicAssistWidget";
import MfaLoginStep from "../components/MfaLoginStep";
import AuthLayout from "../components/auth/AuthLayout";
import SocialSignInButtons from "../components/auth/SocialSignInButtons";
import { AUTH_LABEL, AuthAlert, AuthPrimaryButton, authInputClass } from "../components/auth/authUi";

// "Remember this device" keeps only the work email on this browser — never a
// password or token, and it never skips the second factor (ZP-PRIV B08).
const REMEMBERED_EMAIL_KEY = "zoiko_payroll_remembered_email";

// A developer may prefill the email on the local dev server only. In a
// production build import.meta.env.DEV is false, so the value is dropped and
// never reaches the public bundle (vite.config.js also fails any build that
// would contain it). A password is never prefilled, in any mode.
const DEV_DEFAULT_EMAIL = import.meta.env.DEV ? (import.meta.env.VITE_DEFAULT_EMAIL || "") : "";

function readRememberedEmail() {
  try {
    return localStorage.getItem(REMEMBERED_EMAIL_KEY) || "";
  } catch {
    return "";
  }
}

function storeRememberedEmail(email, remember) {
  try {
    if (remember && email) localStorage.setItem(REMEMBERED_EMAIL_KEY, email);
    else localStorage.removeItem(REMEMBERED_EMAIL_KEY);
  } catch {
    // Storage unavailable (private mode): remembering is a convenience only.
  }
}

export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login } = useAuth();

  const [email, setEmail] = useState(DEV_DEFAULT_EMAIL || readRememberedEmail());
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [localError, setLocalError] = useState(null);
  // ZP-PRIV B08: {mode: "challenge" | "enroll", mfaToken} after a password step.
  const [mfaStep, setMfaStep] = useState(null);

  function defaultRedirectFor(role) {
    return VALID_ROLES.includes(role)
      ? ROLE_DEFAULT_REDIRECT[role]
      : "/payroll";
  }

  async function completeSignIn(data) {
    setSession(data);
    await login(data.user);
    const fallback = defaultRedirectFor(data.user?.role);
    const from = location.state?.from?.pathname || fallback;
    navigate(from, { replace: true });
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setLocalError(null);
    setSubmitting(true);
    try {
      const data = await apiFetch("/api/auth/login", {
        method: "POST",
        body: { email, password },
      });
      storeRememberedEmail(email, remember);
      if (data.mfa_required || data.mfa_enrollment_required) {
        setMfaStep({ mode: data.mfa_required ? "challenge" : "enroll", mfaToken: data.mfa_token });
        return;
      }
      await completeSignIn(data);
    } catch (err) {
      setLocalError(err.message || "Unable to sign in. Please check your credentials.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthLayout>
      <div className="mx-auto w-full max-w-[420px]">
        {mfaStep ? (
          <MfaLoginStep
            mode={mfaStep.mode}
            mfaToken={mfaStep.mfaToken}
            onComplete={(session) => completeSignIn(session)}
            onCancel={() => {
              setMfaStep(null);
              setPassword("");
            }}
          />
        ) : (
          <>
            <h2 className="text-[32px] font-extrabold leading-tight tracking-[-0.02em] text-slate-900">Welcome back!</h2>
            <p className="mt-2 text-[15px] text-slate-600">Sign in to your Zoiko Payroll account.</p>

            <div className="mt-5">
              <SocialSignInButtons />
            </div>

            <div className="my-4 flex items-center gap-3 text-[13px] text-blue-700">
              <span className="h-px flex-1 bg-slate-200" />
              or sign in with email
              <span className="h-px flex-1 bg-slate-200" />
            </div>

            {location.state?.sessionExpired && !localError && (
              <AuthAlert tone="warning">Your session has expired. Sign in again to continue where you left off.</AuthAlert>
            )}

            {localError && <AuthAlert>{localError}</AuthAlert>}

            <form onSubmit={handleSubmit}>
              <label htmlFor="email" className={AUTH_LABEL}>
                Work email address
              </label>
              <div className="relative mb-4">
                <Mail size={18} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-500" />
                <input
                  id="email" type="email" required autoComplete="email"
                  value={email} onChange={(e) => setEmail(e.target.value)}
                  placeholder="name@company.com" className={authInputClass({ withIcon: true })}
                />
              </div>

              <label htmlFor="password" className={AUTH_LABEL}>
                Password
              </label>
              <div className="relative mb-3">
                <Lock size={18} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-500" />
                <input
                  id="password" type={showPassword ? "text" : "password"} required autoComplete="current-password"
                  value={password} onChange={(e) => setPassword(e.target.value)}
                  placeholder="Enter your password" className={authInputClass({ withIcon: true, withTrailing: true })}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  className="absolute right-3 top-1/2 -translate-y-1/2 rounded p-1 text-slate-500 hover:text-slate-800 focus-visible:outline-2 focus-visible:outline-blue-600"
                >
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>

              <div className="mb-4 flex items-center justify-between gap-3 text-[14px]">
                <label className="flex cursor-pointer items-center gap-2 text-slate-700">
                  <input
                    type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)}
                    className="h-4 w-4 rounded border-slate-300 accent-blue-600"
                  />
                  Remember this device
                </label>
                <Link to="/forgot-password" className="font-medium text-blue-700 hover:text-blue-800">
                  Forgot password?
                </Link>
              </div>

              <AuthPrimaryButton type="submit" busy={submitting} busyLabel="Signing in…">
                Log In
              </AuthPrimaryButton>
            </form>

            <p className="mt-5 text-center text-[15px] text-slate-700">
              New to Zoiko Payroll?{" "}
              <Link to="/register" className="font-semibold text-blue-700 hover:text-blue-800">Register</Link>
            </p>
            <p className="mt-1.5 text-center text-[13px] text-slate-500">
              or{" "}
              <Link to="/trial-register" className="font-medium text-blue-700 hover:text-blue-800">
                start a free 30-day trial
              </Link>
            </p>
          </>
        )}
      </div>
      <PublicAssistWidget />
    </AuthLayout>
  );
}
