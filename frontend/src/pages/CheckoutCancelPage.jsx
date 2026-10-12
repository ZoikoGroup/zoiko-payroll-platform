/**
 * pages/CheckoutCancelPage.jsx
 * -----------------------------
 * Stripe redirects here when the user abandons the Checkout Session.
 * Route: /billing/checkout/cancel
 *
 * No subscription state changes — this is purely a UI landing to let
 * the user go back to plan selection or the dashboard.
 */

import { useNavigate } from "react-router-dom";
import { XCircle } from "lucide-react";

const containerStyle = {
  minHeight: "100vh",
  background: "linear-gradient(135deg, #FFF7ED 0%, #FFEDD5 100%)",
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

const primaryButtonStyle = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  gap: "8px",
  padding: "12px 28px",
  borderRadius: "10px",
  border: "none",
  background: "linear-gradient(135deg, #0EA5E9, #0369A1)",
  color: "#FFFFFF",
  fontWeight: "700",
  fontSize: "15px",
  cursor: "pointer",
  marginTop: "8px",
  width: "100%",
};

const secondaryButtonStyle = {
  ...primaryButtonStyle,
  background: "transparent",
  border: "1.5px solid #E5E7EB",
  color: "#374151",
};

export default function CheckoutCancelPage() {
  const navigate = useNavigate();

  return (
    <div style={containerStyle}>
      <div style={cardStyle}>
        <XCircle size={64} style={{ color: "#FB923C" }} />

        <h1 style={{ fontSize: "26px", fontWeight: "800", color: "#0F172A", margin: 0 }}>
          Checkout cancelled
        </h1>

        <p style={{ color: "#6B7280", fontSize: "15px", margin: 0 }}>
          No charge was made. You can choose a plan whenever you're ready —
          your trial access continues in the meantime.
        </p>

        <div style={{ display: "flex", flexDirection: "column", gap: "12px", width: "100%" }}>
          <button style={primaryButtonStyle} onClick={() => navigate("/billing/plans")}>
            View plans again
          </button>
          <button style={secondaryButtonStyle} onClick={() => navigate("/")}>
            Back to Dashboard
          </button>
        </div>
      </div>
    </div>
  );
}
