import { useState } from "react";
import { Mail } from "lucide-react";
import { apiFetch } from "../api/client";
import AuthLayout from "../components/auth/AuthLayout";
import {
  AUTH_LABEL, AuthAlert, AuthPrimaryButton, AuthResult, AuthTitle, BackToSignIn, authInputClass,
} from "../components/auth/authUi";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [sent, setSent] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await apiFetch("/api/auth/forgot-password", {
        method: "POST",
        body: { email },
      });
      setSent(true);
    } catch (err) {
      setError(err.message || "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthLayout>
      <div className="mx-auto w-full max-w-[420px]">
        {!sent ? (
          <>
            <AuthTitle
              title="Forgot your password?"
              subtitle="Enter the email address for your account and we'll send you a secure link to reset your password."
            />

            {error && <AuthAlert>{error}</AuthAlert>}

            <form onSubmit={handleSubmit}>
              <label htmlFor="email" className={AUTH_LABEL}>Work email address</label>
              <div className="relative mb-5">
                <Mail size={18} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-500" />
                <input
                  id="email" type="email" required autoComplete="email"
                  value={email} onChange={(e) => setEmail(e.target.value)}
                  placeholder="name@company.com" className={authInputClass({ withIcon: true })}
                />
              </div>
              <AuthPrimaryButton type="submit" busy={submitting} busyLabel="Sending…">
                Send reset link
              </AuthPrimaryButton>
            </form>
          </>
        ) : (
          <AuthResult
            title="Check your email"
            action={
              <button
                type="button"
                onClick={() => { setSent(false); setEmail(""); }}
                className="text-[14px] font-semibold text-blue-700 hover:text-blue-800"
              >
                Use a different email
              </button>
            }
          >
            <p>If an account exists for <strong className="text-slate-800">{email}</strong>, a password reset link has been sent.</p>
            <p className="mt-1 text-[13px] text-slate-500">The link expires in 24 hours.</p>
          </AuthResult>
        )}

        <BackToSignIn />
      </div>
    </AuthLayout>
  );
}
