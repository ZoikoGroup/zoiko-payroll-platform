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
 *  3. On button click → GET /billing/plan-change-impact; if the plan would
 *     pause or restore countries, confirm in a dialog first (a pause needs
 *     the acknowledgement checkbox) → POST /billing/checkout → redirect
 *     window to checkout_url
 */

import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2, AlertCircle, ArrowLeft, ShieldX } from "lucide-react";
import PlanCard from "../components/billing/PlanCard";
import { listPublishedPlans, createCheckoutSession, getPlanChangeImpact } from "../service/billingService";
import { PlanChangeCountryDialog } from "../components/billing/PlanChangeCountryNotice";
import {
  formatPlanFeature,
  getCountryPauseImpact,
  impactNeedsReview,
  impactPausesCountries,
} from "../utils/planLimits";
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
  const [selectedPlanCode, setSelectedPlanCode] = useState(null);
  // { planCode, planName, impact } while the country-impact dialog is open.
  const [pendingChange, setPendingChange] = useState(null);
  const [acknowledged, setAcknowledged] = useState(false);

  useEffect(() => {
    listPublishedPlans()
      .then(setPlans)
      .catch((err) => setError(err.message || "Failed to load plans."))
      .finally(() => setLoading(false));
  }, []);

  function reviewCountryImpact(planCode, planName, impact) {
    setAcknowledged(false);
    setPendingChange({ planCode, planName, impact });
    setCheckingOut(null);
  }

  async function startCheckout(planCode, planName, acknowledgeCountryPause) {
    setError(null);
    setCheckingOut(planCode);
    try {
      const result = await createCheckoutSession(planCode, { acknowledgeCountryPause });
      if (result?.plan_changed) {
        // Existing paid subscription changed in place (prorated by Stripe) —
        // show it on the subscription page instead of redirecting to Stripe.
        navigate("/organization-admin/subscription", {
          replace: true,
          state: { planChangedMessage: result.message || `You're now on the ${planName} plan.` },
        });
        return;
      }
      // Hard redirect to Stripe — not a client-side navigation
      window.location.href = result.checkout_url;
    } catch (err) {
      // The backend refuses an unacknowledged change that pauses countries —
      // show the same confirmation instead of the raw error.
      const impact = getCountryPauseImpact(err);
      if (impact) {
        reviewCountryImpact(planCode, planName, impact);
        return;
      }
      setPendingChange(null);
      setError(err.message || "Could not start checkout. Please try again.");
      setCheckingOut(null);
    }
  }

  async function handleChoosePlan(plan) {
    const planName = plan.name || plan.code;
    setError(null);
    setCheckingOut(plan.code);
    // Best effort: if the impact lookup fails, checkout's own 409 still
    // catches a change that would pause countries.
    const impact = await getPlanChangeImpact(plan.code).catch(() => null);
    if (impactNeedsReview(impact)) {
      reviewCountryImpact(plan.code, planName, impact);
      return;
    }
    await startCheckout(plan.code, planName, false);
  }

  const selectedPlan = selectedPlanCode ? plans.find((p) => p.code === selectedPlanCode) : null;

  function handleContinue() {
    if (selectedPlan) handleChoosePlan(selectedPlan);
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
        <>
          <div style={gridStyle}>
            {plans.map((plan) => {
              const isHighlighted = HIGHLIGHTED_PLANS.includes(plan.code);

              // Extract feature names from entitlement_flags. Backend shape is a
              // dict {feature_key: limit_value} — normalize to entries so the
              // rendering below never assumes an array.
              const flags = plan.entitlement_flags || {};
              const features = (Array.isArray(flags)
                ? flags
                : Object.entries(flags).map(([feature_key, limit_value]) => ({ feature_key, limit_value }))
              )
                .filter((f) => f.limit_value !== 0)
                .map((f) => formatPlanFeature(f.feature_key, f.limit_value));

              const planCode = plan.code;

              return (
                <PlanCard
                  key={plan.plan_id}
                  name={plan.name || plan.code}
                  priceLabel={getPriceLabel(plan)}
                  priceComponents={plan.price_components}
                  features={features}
                  recommended={isHighlighted}
                  badgeLabel="Most Popular"
                  selected={selectedPlanCode === planCode}
                  disabled={checkingOut !== null}
                  onSelect={canManage ? () => { setSelectedPlanCode(planCode); setError(null); } : undefined}
                  footer={!canManage ? (
                    <div style={{ ...buttonStyle, background: "#F1F5F9", color: "#64748B", cursor: "not-allowed", opacity: 1 }}>
                      <ShieldX size={16} />
                      Org Admin can subscribe
                    </div>
                  ) : null}
                />
              );
            })}
          </div>

          {canManage && (
            <div style={{ width: "100%", maxWidth: "960px", marginTop: "28px", display: "flex", justifyContent: "center" }}>
              <button
                style={{
                  ...(selectedPlan && checkingOut === null ? buttonStyle : disabledButtonStyle),
                  width: "auto",
                  minWidth: "260px",
                  marginTop: 0,
                }}
                disabled={!selectedPlan || checkingOut !== null}
                onClick={handleContinue}
              >
                {checkingOut !== null ? (
                  <>
                    <Loader2 size={16} className="animate-spin" />
                    Redirecting to Stripe…
                  </>
                ) : selectedPlan ? (
                  `Continue with ${selectedPlan.name || selectedPlan.code}`
                ) : (
                  "Select a plan to continue"
                )}
              </button>
            </div>
          )}
        </>
      )}

      {pendingChange && (
        <PlanChangeCountryDialog
          impact={pendingChange.impact}
          planName={pendingChange.planName}
          acknowledged={acknowledged}
          onAcknowledgedChange={setAcknowledged}
          busy={checkingOut === pendingChange.planCode}
          onClose={() => setPendingChange(null)}
          onConfirm={() =>
            startCheckout(pendingChange.planCode, pendingChange.planName, impactPausesCountries(pendingChange.impact))
          }
        />
      )}

      <p style={{ marginTop: 40, fontSize: 13, color: "#94A3B8", textAlign: "center" }}>
        All prices in USD. Subscriptions renew automatically. Secure checkout via Stripe.
      </p>
    </div>
  );
}
