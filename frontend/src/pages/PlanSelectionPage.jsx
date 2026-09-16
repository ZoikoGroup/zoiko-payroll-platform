/**
 * pages/PlanSelectionPage.jsx
 * ----------------------------
 * Self-service plan comparison and Stripe Checkout redirect.
 *
 * Route: /billing/plans
 * Auth: org_admin only (redirected from app router if not authenticated)
 *
 * Flow:
 *  1. Load published plans via GET /billing/plans
 *  2. Show plan cards with pricing, features, and a "Choose Plan" button
 *  3. On button click → POST /billing/checkout → redirect window to checkout_url
 */

import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2, Check, AlertCircle, Zap, ArrowLeft, ShieldX } from "lucide-react";
import { listPublishedPlans, createCheckoutSession } from "../service/billingService";
import { useAuth } from "../context/AuthContext";
import { ROLES } from "../config/roles";

// ── Styles ────────────────────────────────────────────────────────────────

const containerStyle = {
  minHeight: "100vh",
  background: "linear-gradient(135deg, #F0F9FF 0%, #E0F2FE 100%)",
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  padding: "60px 24px",
  fontFamily: "'Inter', system-ui, sans-serif",
};

const headingStyle = {
  fontSize: "32px",
  fontWeight: "800",
  color: "#0F172A",
  textAlign: "center",
  marginBottom: "8px",
};

const subheadingStyle = {
  fontSize: "17px",
  color: "#64748B",
  textAlign: "center",
  marginBottom: "48px",
};

const gridStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
  gap: "24px",
  width: "100%",
  maxWidth: "960px",
};

const cardBase = {
  background: "#FFFFFF",
  borderRadius: "16px",
  padding: "32px",
  boxShadow: "0 4px 24px rgba(0,0,0,0.08)",
  display: "flex",
  flexDirection: "column",
  gap: "16px",
  border: "2px solid transparent",
  transition: "border-color 0.2s, box-shadow 0.2s",
  position: "relative",
};

const cardHighlightedStyle = {
  ...cardBase,
  border: "2px solid #0EA5E9",
  boxShadow: "0 8px 32px rgba(14,165,233,0.20)",
};

const planNameStyle = {
  fontSize: "20px",
  fontWeight: "700",
  color: "#0F172A",
};

const featureListStyle = {
  listStyle: "none",
  padding: 0,
  margin: 0,
  display: "flex",
  flexDirection: "column",
  gap: "8px",
  flexGrow: 1,
};

const featureItemStyle = {
  display: "flex",
  alignItems: "center",
  gap: "8px",
  fontSize: "14px",
  color: "#374151",
};

const buttonStyle = {
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  gap: "8px",
  padding: "12px 20px",
  borderRadius: "10px",
  border: "none",
  background: "linear-gradient(135deg, #0EA5E9, #0369A1)",
  color: "#FFFFFF",
  fontWeight: "700",
  fontSize: "15px",
  cursor: "pointer",
  transition: "opacity 0.15s",
  width: "100%",
  marginTop: "8px",
};

const disabledButtonStyle = {
  ...buttonStyle,
  background: "#E2E8F0",
  color: "#94A3B8",
  cursor: "not-allowed",
};

const badgeStyle = {
  position: "absolute",
  top: "-12px",
  left: "50%",
  transform: "translateX(-50%)",
  background: "linear-gradient(135deg, #0EA5E9, #0369A1)",
  color: "#FFFFFF",
  fontSize: "12px",
  fontWeight: "700",
  padding: "4px 14px",
  borderRadius: "20px",
  whiteSpace: "nowrap",
};

const errorBoxStyle = {
  display: "flex",
  alignItems: "flex-start",
  gap: "10px",
  background: "#FEF2F2",
  border: "1px solid #FCA5A5",
  borderRadius: "10px",
  padding: "14px 18px",
  color: "#B91C1C",
  fontSize: "14px",
  maxWidth: "960px",
  width: "100%",
  marginBottom: "24px",
};

// ── Helpers ───────────────────────────────────────────────────────────────

/** Extract a human-readable price string from a plan's published price */
function getPriceLabel(plan) {
  if (plan.monthly_price_usd === 0) return "Free";
  if (plan.monthly_price_usd > 0) return `$${plan.monthly_price_usd}/mo`;
  return "Custom pricing";
}

/** Plans to highlight as "Most Popular" */
const HIGHLIGHTED_PLANS = ["PROFESSIONAL", "BUSINESS"];

// ── Component ─────────────────────────────────────────────────────────────

export default function PlanSelectionPage() {
  const navigate = useNavigate();
  const { role } = useAuth();
  const canManage = role === ROLES.ORG_ADMIN;
  const [plans, setPlans] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [checkingOut, setCheckingOut] = useState(null); // plan_code being checked out

  useEffect(() => {
    setLoading(true);
    listPublishedPlans()
      .then(setPlans)
      .catch((err) => setError(err.message || "Failed to load plans."))
      .finally(() => setLoading(false));
  }, []);

  async function handleChoosePlan(planCode) {
    setError(null);
    setCheckingOut(planCode);
    try {
      const { checkout_url } = await createCheckoutSession(planCode);
      // Hard redirect to Stripe — not a client-side navigation
      window.location.href = checkout_url;
    } catch (err) {
      setError(err.message || "Could not start checkout. Please try again.");
      setCheckingOut(null);
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────

  return (
    <div style={containerStyle}>
      {/* Top Header Navigation */}
      <div style={{ width: "100%", maxWidth: "960px", marginBottom: "24px", display: "flex", justifyContent: "flex-start" }}>
        <button
          onClick={() => navigate("/")}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "8px",
            background: "#FFFFFF",
            border: "1px solid #CBD5E1",
            borderRadius: "8px",
            padding: "8px 16px",
            fontSize: "14px",
            fontWeight: "600",
            color: "#334155",
            cursor: "pointer",
            boxShadow: "0 1px 2px rgba(0,0,0,0.05)",
          }}
        >
          <ArrowLeft size={16} />
          Back to Dashboard
        </button>
      </div>

      <h1 style={headingStyle}>Choose your plan</h1>
      <p style={subheadingStyle}>
        Upgrade to unlock full payroll features. Cancel any time.
      </p>

      {error && (
        <div style={errorBoxStyle}>
          <AlertCircle size={18} style={{ flexShrink: 0, marginTop: 2 }} />
          <span>{error}</span>
        </div>
      )}

      {loading ? (
        <Loader2 size={36} className="animate-spin" style={{ color: "#0EA5E9", marginTop: 40 }} />
      ) : plans.length === 0 ? (
        <p style={{ color: "#64748B", fontSize: "16px" }}>
          No plans are available at the moment. Please contact support.
        </p>
      ) : (
        <div style={gridStyle}>
          {plans.map((plan) => {
            const isHighlighted = HIGHLIGHTED_PLANS.includes(plan.code);
            const isLoadingThis = checkingOut === plan.code;
            const anyLoading = checkingOut !== null;

            // Extract feature names from entitlement_flags. Backend shape is a
            // dict {feature_key: limit_value} — normalize to entries so the
            // rendering below never assumes an array.
            const flags = plan.entitlement_flags || {};
            const features = (Array.isArray(flags)
              ? flags
              : Object.entries(flags).map(([feature_key, limit_value]) => ({ feature_key, limit_value }))
            )
              .filter((f) => f.limit_value !== 0)
              .map((f) => f.feature_key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()));

            return (
              <div
                key={plan.plan_id}
                style={isHighlighted ? cardHighlightedStyle : cardBase}
              >
                {isHighlighted && (
                  <div style={badgeStyle}>
                    <Zap size={12} style={{ display: "inline", marginRight: 4 }} />
                    Most Popular
                  </div>
                )}

                <div>
                  <div style={planNameStyle}>{plan.name || plan.code}</div>
                  <div style={{ fontSize: "24px", fontWeight: "800", color: "#0EA5E9", marginTop: 4 }}>
                    {getPriceLabel(plan)}
                  </div>
                </div>

                <ul style={featureListStyle}>
                  {features.slice(0, 8).map((feat) => (
                    <li key={feat} style={featureItemStyle}>
                      <Check size={15} style={{ color: "#10B981", flexShrink: 0 }} />
                      {feat}
                    </li>
                  ))}
                  {features.length === 0 && (
                    <li style={{ ...featureItemStyle, color: "#94A3B8" }}>
                      Contact us for details
                    </li>
                  )}
                </ul>

                {canManage ? (
                  <button
                    style={anyLoading ? disabledButtonStyle : buttonStyle}
                    disabled={anyLoading}
                    onClick={() => handleChoosePlan(plan.code)}
                  >
                    {isLoadingThis ? (
                      <>
                        <Loader2 size={16} className="animate-spin" />
                        Redirecting to Stripe…
                      </>
                    ) : (
                      `Choose ${plan.name || plan.code}`
                    )}
                  </button>
                ) : (
                  <div style={{ ...buttonStyle, background: "#F1F5F9", color: "#64748B", cursor: "not-allowed", opacity: 1 }}>
                    <ShieldX size={16} />
                    Org Admin can subscribe
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <p style={{ marginTop: 40, fontSize: 13, color: "#94A3B8", textAlign: "center" }}>
        All prices in USD. Subscriptions renew automatically. Secure checkout via Stripe.
      </p>
    </div>
  );
}
