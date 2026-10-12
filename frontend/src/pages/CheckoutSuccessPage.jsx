/**
 * pages/CheckoutSuccessPage.jsx
 * ------------------------------
 * Stripe redirects here after a successful payment.
 * Route: /billing/checkout/success
 *
 * Re-fetches the subscription to confirm ACTIVE status (the webhook may
 * arrive slightly before Stripe's redirect, or slightly after — polling is
 * intentionally short-lived). Shows a clear success state with a link
 * back to the dashboard.
 */

import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, Loader2 } from "lucide-react";
import { getMySubscription } from "../service/billingService";

const MAX_POLL_ATTEMPTS = 8;
const POLL_INTERVAL_MS = 2000;

const containerStyle = {
  minHeight: "100vh",
  background: "linear-gradient(135deg, #F0FDF4 0%, #DCFCE7 100%)",
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  justifyContent: "center",
  padding: "40px 24px",
  fontFamily: "'Inter', system-ui, sans-serif",
};

const cardStyle = {
  background: "#FFFFFF",
  borderRadius: "20px",
  padding: "48px 40px",
  boxShadow: "0 8px 40px rgba(0,0,0,0.10)",
  maxWidth: "480px",
  width: "100%",
  textAlign: "center",
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  gap: "20px",
};

const buttonStyle = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  gap: "8px",
  padding: "12px 28px",
  borderRadius: "10px",
  border: "none",
  background: "linear-gradient(135deg, #22C55E, #16A34A)",
  color: "#FFFFFF",
  fontWeight: "700",
  fontSize: "15px",
  cursor: "pointer",
  textDecoration: "none",
  marginTop: "8px",
};

export default function CheckoutSuccessPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState("polling"); // "polling" | "active" | "pending"
  const attempts = useRef(0);

  useEffect(() => {
    const timer = setInterval(async () => {
      attempts.current += 1;
      try {
        const sub = await getMySubscription();
        if (sub?.subscription?.status === "ACTIVE") {
          clearInterval(timer);
          setStatus("active");
          return;
        }
      } catch {
        // ignore — may 404 until webhook fires
      }
      if (attempts.current >= MAX_POLL_ATTEMPTS) {
        clearInterval(timer);
        setStatus("pending");
      }
    }, POLL_INTERVAL_MS);

    return () => clearInterval(timer);
  }, []);

  return (
    <div style={containerStyle}>
      <div style={cardStyle}>
        <CheckCircle2 size={64} style={{ color: "#22C55E" }} />

        <h1 style={{ fontSize: "26px", fontWeight: "800", color: "#0F172A", margin: 0 }}>
          Payment successful!
        </h1>

        {status === "polling" && (
          <>
            <p style={{ color: "#6B7280", fontSize: "15px", margin: 0 }}>
              Activating your subscription…
            </p>
            <Loader2 size={24} className="animate-spin" style={{ color: "#22C55E" }} />
          </>
        )}

        {status === "active" && (
          <>
            <p style={{ color: "#6B7280", fontSize: "15px", margin: 0 }}>
              Your subscription is now <strong style={{ color: "#16A34A" }}>ACTIVE</strong>.
              Welcome aboard! You now have full access to all payroll features.
            </p>
            <button style={buttonStyle} onClick={() => navigate("/")}>
              Go to Dashboard
            </button>
          </>
        )}

        {status === "pending" && (
          <>
            <p style={{ color: "#6B7280", fontSize: "15px", margin: 0 }}>
              Your payment was received. Your subscription will be activated shortly
              — you may need to refresh in a moment.
            </p>
            <button style={buttonStyle} onClick={() => navigate("/")}>
              Go to Dashboard
            </button>
          </>
        )}
      </div>
    </div>
  );
}
