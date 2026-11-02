import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Eye, EyeOff, Lock } from "lucide-react";
import { apiFetch } from "../api/client";
import AuthLayout from "../components/auth/AuthLayout";
import {
  AUTH_LABEL, AuthAlert, AuthPrimaryButton, AuthResult, AuthTitle, BackToSignIn, authInputClass,
} from "../components/auth/authUi";

export default function ResetPasswordPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") || "";

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);

    if (!token) {
      setError("This reset link is missing its security token. Please request a new link.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }

    setSubmitting(true);
    try {
      await apiFetch("/api/auth/reset-password", {
        method: "POST",
        body: { token, password },
      });
      setDone(true);
    } catch (err) {
      setError(err.message || "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  const invalidLink = !token;

  return (
    <AuthLayout>
      <div className="mx-auto w-full max-w-[420px]">
        {done ? (
          <AuthResult
            title="Password updated"
            action={<AuthPrimaryButton type="button" onClick={() => navigate("/login")}>Sign in</AuthPrimaryButton>}
          >
            Your password has been changed. Sign in with your new password.
          </AuthResult>
        ) : invalidLink ? (
          <AuthResult
            tone="error"
            title="Link not valid"
            action={
              <AuthPrimaryButton type="button" onClick={() => navigate("/forgot-password")}>
                Request a new link
              </AuthPrimaryButton>
            }
          >
            This password reset link is invalid, expired or has already been used.
          </AuthResult>
        ) : (
          <>
            <AuthTitle
              title="Choose a new password"
              subtitle="Pick a strong password you haven't used for this account before."
            />

            {error && <AuthAlert>{error}</AuthAlert>}

            <form onSubmit={handleSubmit}>
              <label htmlFor="password" className={AUTH_LABEL}>New password</label>
              <div className="relative mb-4">
                <Lock size={18} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-500" />
                <input
                  id="password" type={showPassword ? "text" : "password"} required minLength={8}
                  autoComplete="new-password"
                  value={password} onChange={(e) => setPassword(e.target.value)}
                  placeholder="At least 8 characters"
                  className={authInputClass({ withIcon: true, withTrailing: true })}
                />
                <button
                  type="button" onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  className="absolute right-3 top-1/2 -translate-y-1/2 rounded p-1 text-slate-500 hover:text-slate-800 focus-visible:outline-2 focus-visible:outline-blue-600"
                >
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>

              <label htmlFor="confirm" className={AUTH_LABEL}>Confirm new password</label>
              <div className="relative mb-5">
                <Lock size={18} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-500" />
                <input
                  id="confirm" type={showPassword ? "text" : "password"} required
                  autoComplete="new-password"
                  value={confirm} onChange={(e) => setConfirm(e.target.value)}
                  placeholder="Re-enter your new password"
                  className={authInputClass({ withIcon: true })}
                />
              </div>

              <AuthPrimaryButton type="submit" busy={submitting} busyLabel="Updating…">
                Reset password
              </AuthPrimaryButton>
            </form>
          </>
        )}

        <BackToSignIn />
      </div>
    </AuthLayout>
  );
}
