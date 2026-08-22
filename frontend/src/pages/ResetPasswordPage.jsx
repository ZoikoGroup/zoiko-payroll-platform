import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Loader2, AlertCircle, CheckCircle2, Eye, EyeOff, ArrowLeft } from "lucide-react";
import { apiFetch } from "../api/client";
import LandingHeader from "../landing/LandingHeader";
import Footer from "../landing/Footer";

export default function ResetPasswordPage() {
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

  const inputStyle = {
    width: "100%",
    padding: "11px 14px",
    borderRadius: "8px",
    border: "1.5px solid #E5E7EB",
    fontSize: "14px",
    color: "#111827",
    outline: "none",
    boxSizing: "border-box",
    background: "white",
    fontFamily: "inherit",
  };

  const invalidLink = !token;

  return (
    <div style={{
      minHeight: "100vh",
      display: "flex",
      flexDirection: "column",
      fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
      background: "#ffffff",
    }}>
      <LandingHeader />
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: "48px 24px" }}>
        <div style={{ width: "100%", maxWidth: "420px" }}>

          {done ? (
            <div style={{ textAlign: "center", padding: "8px 0" }}>
              <CheckCircle2 size={40} color="#059669" style={{ margin: "0 auto 16px" }} />
              <h1 style={{ fontSize: "22px", fontWeight: "800", color: "#0F172A", margin: "0 0 8px 0", letterSpacing: "-0.5px" }}>
                Password updated
              </h1>
              <p style={{ fontSize: "14px", color: "#6B7280", lineHeight: "1.7", margin: "0 0 24px 0" }}>
                Your password has been changed. Sign in with your new password.
              </p>
              <Link to="/login">
                <button type="button"
                  style={{
                    width: "100%", padding: "13px", borderRadius: "50px", border: "none",
                    fontSize: "15px", fontWeight: "600", color: "white", cursor: "pointer",
                    background: "linear-gradient(135deg, #087CC1, #1596D1)",
                    boxShadow: "0 4px 16px rgba(8,124,193,0.4)", letterSpacing: "0.01em",
                  }}>
                  Sign in
                </button>
              </Link>
            </div>
          ) : invalidLink ? (
            <div style={{ textAlign: "center", padding: "8px 0" }}>
              <AlertCircle size={40} color="#DC2626" style={{ margin: "0 auto 16px" }} />
              <h1 style={{ fontSize: "22px", fontWeight: "800", color: "#0F172A", margin: "0 0 8px 0", letterSpacing: "-0.5px" }}>
                Link not valid
              </h1>
              <p style={{ fontSize: "14px", color: "#6B7280", lineHeight: "1.7", margin: "0 0 24px 0" }}>
                This password reset link is invalid, expired or has already been used.
              </p>
              <Link to="/forgot-password">
                <button type="button"
                  style={{
                    width: "100%", padding: "13px", borderRadius: "50px", border: "none",
                    fontSize: "15px", fontWeight: "600", color: "white", cursor: "pointer",
                    background: "linear-gradient(135deg, #087CC1, #1596D1)",
                    boxShadow: "0 4px 16px rgba(8,124,193,0.4)", letterSpacing: "0.01em",
                  }}>
                  Request a new link
                </button>
              </Link>
            </div>
          ) : (
            <>
              <h1 style={{ fontSize: "24px", fontWeight: "800", color: "#0F172A", margin: "0 0 8px 0", letterSpacing: "-0.5px" }}>
                Choose a new password
              </h1>
              <p style={{ fontSize: "14px", color: "#6B7280", lineHeight: "1.6", margin: "0 0 28px 0" }}>
                Pick a strong password you haven't used for this account before.
              </p>

              {error && (
                <div style={{
                  display: "flex", alignItems: "flex-start", gap: "8px",
                  background: "#FEF2F2", border: "1px solid #FECACA",
                  borderRadius: "8px", padding: "12px 14px", marginBottom: "20px"
                }}>
                  <AlertCircle size={15} color="#DC2626" style={{ marginTop: "1px", flexShrink: 0 }} />
                  <span style={{ fontSize: "13px", color: "#DC2626" }}>{error}</span>
                </div>
              )}

              <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                <div>
                  <label htmlFor="password" style={{ display: "block", fontSize: "13px", fontWeight: "500", color: "#374151", marginBottom: "6px" }}>
                    New password
                  </label>
                  <div style={{ position: "relative" }}>
                    <input
                      id="password" type={showPassword ? "text" : "password"} required minLength={8}
                      autoComplete="new-password"
                      value={password} onChange={e => setPassword(e.target.value)}
                      placeholder="At least 8 characters"
                      style={{ ...inputStyle, paddingRight: "42px" }}
                      onFocus={e => e.target.style.borderColor = "#087CC1"}
                      onBlur={e => e.target.style.borderColor = "#E5E7EB"}
                    />
                    <button type="button" onClick={() => setShowPassword(v => !v)} aria-label="Toggle password visibility"
                      style={{
                        position: "absolute", right: "12px", top: "50%", transform: "translateY(-50%)",
                        background: "none", border: "none", cursor: "pointer", padding: 0,
                        color: "#9CA3AF", display: "flex",
                      }}>
                      {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </div>

                <div>
                  <label htmlFor="confirm" style={{ display: "block", fontSize: "13px", fontWeight: "500", color: "#374151", marginBottom: "6px" }}>
                    Confirm new password
                  </label>
                  <input
                    id="confirm" type={showPassword ? "text" : "password"} required
                    autoComplete="new-password"
                    value={confirm} onChange={e => setConfirm(e.target.value)}
                    placeholder="Re-enter your new password"
                    style={inputStyle}
                    onFocus={e => e.target.style.borderColor = "#087CC1"}
                    onBlur={e => e.target.style.borderColor = "#E5E7EB"}
                  />
                </div>

                <button type="submit" disabled={submitting}
                  style={{
                    width: "100%", padding: "13px", borderRadius: "50px", border: "none",
                    fontSize: "15px", fontWeight: "600", color: "white",
                    cursor: submitting ? "not-allowed" : "pointer",
                    background: submitting ? "#7EC1E0" : "linear-gradient(135deg, #087CC1, #1596D1)",
                    boxShadow: "0 4px 16px rgba(8,124,193,0.4)",
                    display: "flex", alignItems: "center", justifyContent: "center", gap: "8px",
                    marginTop: "4px", letterSpacing: "0.01em",
                  }}>
                  {submitting && <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} />}
                  {submitting ? "Updating…" : "Reset password"}
                </button>
              </form>
            </>
          )}

          <div style={{ textAlign: "center", marginTop: "24px" }}>
            <Link to="/login"
              style={{
                display: "inline-flex", alignItems: "center", gap: "6px",
                fontSize: "13px", color: "#374151", textDecoration: "none", fontWeight: "500",
              }}>
              <ArrowLeft size={14} />
              Back to sign in
            </Link>
          </div>
        </div>
      </div>
      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
      `}</style>
      <Footer />
    </div>
  );
}
