import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Loader2, Eye, EyeOff, AlertCircle, Zap } from "lucide-react";
import { apiFetch } from "../api/client";
import { REGISTRATION_COUNTRIES } from "../utils/registrationRegions";
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

export default function TrialSignupPage() {
  const navigate = useNavigate();

  const [form, setForm] = useState({
    orgName: "",
    adminName: "",
    adminEmail: "",
    password: "",
    country: "",
    termsAccepted: false,
  });
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [localError, setLocalError] = useState(null);

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setLocalError(null);
    setSubmitting(true);
    try {
      await apiFetch("/api/auth/register-trial", {
        method: "POST",
        body: {
          organization: form.orgName,
          name: form.adminName,
          email: form.adminEmail,
          password: form.password,
          country: form.country,
        },
      });
      navigate("/register/success", {
        state: {
          organizationName: form.orgName,
          email: form.adminEmail,
        },
      });
    } catch (err) {
      setLocalError(err.message || "Unable to create your evaluation account.");
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
        <div style={{ width: "100%", maxWidth: "680px" }}>
          <div style={{ textAlign: "center", marginBottom: "36px" }}>
            <div style={{
              display: "inline-flex", alignItems: "center", gap: "6px",
              background: "#EEF6FB", border: "1px solid #BFDBEE", color: "#087CC1",
              borderRadius: "9999px", padding: "5px 14px", fontSize: "12px", fontWeight: "700",
              marginBottom: "14px"
            }}>
              <Zap size={13} />
              30-DAY PROFESSIONAL EVALUATION
            </div>
            <h1 style={{ fontSize: "26px", fontWeight: "800", color: "#111827", margin: 0, letterSpacing: "-0.5px" }}>
              Try Zoiko Payroll free
            </h1>
            <p style={{ fontSize: "14px", color: "#6B7280", margin: "8px 0 0 0" }}>
              Explore pay runs, statutory rates and payslips for 30 days. No tax identifiers required.
            </p>
          </div>

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
                  <label htmlFor="trial-orgName" style={labelStyle}>
                    Organization Name
                  </label>
                  <input
                    id="trial-orgName"
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
                  <label htmlFor="trial-adminName" style={labelStyle}>
                    Admin Name
                  </label>
                  <input
                    id="trial-adminName"
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
                  <label htmlFor="trial-adminEmail" style={labelStyle}>
                    Admin Email
                  </label>
                  <input
                    id="trial-adminEmail"
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
                  <label htmlFor="trial-password" style={labelStyle}>
                    Password
                  </label>
                  <div style={{ position: "relative" }}>
                    <input
                      id="trial-password"
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
              </div>

              <div>
                <label htmlFor="trial-country" style={labelStyle}>
                  Country
                </label>
                <select
                  id="trial-country"
                  required
                  value={form.country}
                  onChange={(e) => update("country", e.target.value)}
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

              <div style={{
                background: "#F0FDF4", border: "1px solid #BBF7D0",
                borderRadius: "10px", padding: "12px 14px"
              }}>
                <p style={{ margin: 0, fontSize: "13px", color: "#15803D", lineHeight: "1.5" }}>
                  Free for 30 days. Convert to a production account any time — you'll be asked for
                  business and tax details only when you do.
                </p>
              </div>

              <div style={{ display: "flex", alignItems: "flex-start", gap: "10px" }}>
                <input
                  id="trial-termsAccepted"
                  type="checkbox"
                  required
                  checked={form.termsAccepted}
                  onChange={(e) => update("termsAccepted", e.target.checked)}
                  style={{
                    marginTop: "2px", width: "16px", height: "16px", flexShrink: 0,
                    accentColor: "#087CC1", cursor: "pointer"
                  }}
                />
                <label htmlFor="trial-termsAccepted" style={{ fontSize: "13px", color: "#374151", cursor: "pointer", lineHeight: "1.4" }}>
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
                {submitting ? "Creating evaluation…" : "Start 30-day evaluation"}
              </button>
            </form>

            <p style={{ textAlign: "center", fontSize: "13px", color: "#6B7280", marginTop: "20px", marginBottom: 0 }}>
              Want the full production setup?{" "}
              <Link to="/register" style={{ color: "#087CC1", fontWeight: "600", textDecoration: "none" }}>
                Register your organization
              </Link>
            </p>
          </div>

          <p style={{ textAlign: "center", marginTop: "20px" }}>
            <Link to="/login" style={{ fontSize: "13px", color: "#9CA3AF", textDecoration: "none" }}>
              ← Back to sign in
            </Link>
          </p>
        </div>
      </div>

      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
      `}</style>
      <Footer />
    </div>
  );
}