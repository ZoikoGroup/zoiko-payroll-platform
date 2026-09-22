import { useMemo, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { Loader2, Sparkles } from "lucide-react";
import { apiFetch } from "../api/client";
import LandingHeader from "../landing/LandingHeader";
import Footer from "../landing/Footer";
import DelayedBillingBanner from "../components/DelayedBillingBanner";
import { PlanCapabilityRow, planCardStyle, badgeStyle } from "./RegisterPage";

const THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000;

// Reached immediately after registration succeeds (RegisterPage.jsx has
// already created the account and logged the browser in by the time it
// navigates here) — this is the one place that actually calls
// POST /billing/checkout, computing the deferred service_commencement_at
// that makes this a "30-day trial, first charge later" signup rather than
// an immediate charge.
export default function PlanReviewPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { planCode, plan } = location.state || {};

  // Which button is in flight, if any — kept separate per-action so the two
  // buttons don't fight over one shared "submitting" flag.
  const [submittingAction, setSubmittingAction] = useState(null); // null | "pay" | "trial"
  const [error, setError] = useState(null);

  // Computed once per page load, not recomputed on every render — this
  // exact value is what both the banner displays AND what gets sent to
  // /billing/checkout, so the two can never drift apart.
  const commencementDate = useMemo(() => new Date(Date.now() + THIRTY_DAYS_MS), []);

  // A direct URL visit or a refresh that lost route state has no plan to
  // review — bounce back to plan selection rather than rendering a broken
  // page against undefined plan data.
  if (!planCode || !plan) {
    return <Navigate to="/register" replace />;
  }

  // A $0 plan has nothing to defer a charge on — the 30-day-delayed-billing
  // framing only makes sense for a plan that actually charges something.
  const isPaidPlan = plan.priceLabel !== "Free";

  // Trial is offered on Core and Professional, not Business — Business
  // buyers pay directly. Note this app still has no per-plan trial concept:
  // POST /billing/start-trial always grants the same single "30-day
  // Professional Evaluation" /register-trial already offers, regardless of
  // whether this button was reached from Core's or Professional's review
  // page — clicking it from Core is an upsell into trying Professional
  // free, not a "Core trial" (there's nothing to trial on a $0 plan).
  const trialAvailable = planCode === "PROFESSIONAL" || planCode === "CORE";

  const busy = submittingAction !== null;

  async function handlePay() {
    setError(null);
    setSubmittingAction("pay");
    try {
      const body = { plan_code: planCode };
      if (isPaidPlan) {
        body.service_commencement_at = commencementDate.toISOString();
      }
      const { checkout_url } = await apiFetch("/api/billing/checkout", {
        method: "POST",
        body,
      });
      window.location.href = checkout_url;
    } catch (err) {
      setError(err.message || "Could not start checkout. Please try again.");
      setSubmittingAction(null);
    }
  }

  async function handleStartTrial() {
    setError(null);
    setSubmittingAction("trial");
    try {
      await apiFetch("/api/billing/start-trial", { method: "POST" });
      navigate("/payroll");
    } catch (err) {
      setError(err.message || "Could not start your trial. Please try again.");
      setSubmittingAction(null);
    }
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        background: "linear-gradient(135deg, #eef6fb 0%, #ffffff 50%, #eef6fb 100%)",
        fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
      }}
    >
      <LandingHeader />
      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: "40px 24px",
        }}
      >
        <div style={{ width: "100%", maxWidth: "480px" }}>
          <div style={{ textAlign: "center", marginBottom: "24px" }}>
            <h1 style={{ fontSize: "26px", fontWeight: "800", color: "#111827", margin: "0 0 8px 0", letterSpacing: "-0.5px" }}>
              Review your plan
            </h1>
            <p style={{ fontSize: "14px", color: "#6B7280", margin: 0 }}>
              Confirm what you're signing up for before we take you to secure checkout.
            </p>
          </div>

          <div style={planCardStyle(plan.recommended)}>
            {plan.recommended && (
              <div style={badgeStyle}>
                <Sparkles size={11} style={{ display: "inline", marginRight: 4, marginBottom: -1 }} />
                Recommended plan
              </div>
            )}
            <div>
              <div style={{ fontSize: "18px", fontWeight: "700", color: "#111827" }}>{plan.name}</div>
              <div style={{ fontSize: "22px", fontWeight: "800", color: "#087CC1", marginTop: 2 }}>{plan.priceLabel}</div>
              {plan.tagline && (
                <p style={{ fontSize: "12px", color: "#6B7280", marginTop: 6 }}>{plan.tagline}</p>
              )}
            </div>
            <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: "6px" }}>
              {plan.capabilities.map(([label, on]) => (
                <PlanCapabilityRow key={label} label={label} on={on} />
              ))}
            </ul>
            {plan.scale.length > 0 && (
              <ul
                style={{
                  listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: "4px",
                  borderTop: "1px solid #F3F4F6", paddingTop: "10px",
                }}
              >
                {plan.scale.map((s) => (
                  <li key={s} style={{ fontSize: "12px", color: "#4B5563", fontWeight: 500 }}>{s}</li>
                ))}
              </ul>
            )}
          </div>

          {isPaidPlan && <DelayedBillingBanner commencementDate={commencementDate} />}

          {error && (
            <p style={{ fontSize: "13px", color: "#DC2626", margin: "16px 0 0 0", textAlign: "center" }}>{error}</p>
          )}

          <div style={{ marginTop: 20, display: "flex", flexDirection: "column", gap: "10px" }}>
            <button
              type="button"
              disabled={busy}
              onClick={handlePay}
              style={{
                padding: "13px", borderRadius: "10px", border: "none", fontSize: "15px", fontWeight: "700",
                color: "white", cursor: busy ? "not-allowed" : "pointer",
                background: busy ? "#7EC1E0" : "linear-gradient(135deg, #087CC1, #1596D1)",
                display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
              }}
            >
              {submittingAction === "pay" && <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} />}
              {submittingAction === "pay" ? "Starting checkout…" : "Continue to Payment"}
            </button>

            {trialAvailable && (
              <button
                type="button"
                disabled={busy}
                onClick={handleStartTrial}
                style={{
                  padding: "13px", borderRadius: "10px", border: "1.5px solid #087CC1", fontSize: "15px", fontWeight: "700",
                  color: busy ? "#7EC1E0" : "#087CC1", background: "white", cursor: busy ? "not-allowed" : "pointer",
                  display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
                }}
              >
                {submittingAction === "trial" && <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} />}
                {submittingAction === "trial" ? "Starting your trial…" : "Start Trial Instead — No Card Required"}
              </button>
            )}

            <button
              type="button"
              disabled={busy}
              onClick={() => navigate("/billing/plans")}
              style={{
                padding: "8px", borderRadius: "10px", border: "none", fontSize: "13px",
                fontWeight: "600", color: "#6B7280", background: "transparent", cursor: busy ? "not-allowed" : "pointer",
              }}
            >
              Go to plan selection instead
            </button>
          </div>
        </div>
      </div>
      <Footer />
    </div>
  );
}
