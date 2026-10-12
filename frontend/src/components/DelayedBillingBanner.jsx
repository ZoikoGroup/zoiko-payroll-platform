import { Clock } from "lucide-react";

// Distinct from TrialBanner.jsx on purpose — that component is wired to
// /auth/me/trial-status for EVALUATION workspaces and has no meaning here.
// This is a paid-plan signup where the card is collected now but the first
// Stripe charge is deferred via service_commencement_at; same calm/confident
// blue palette as TrialBanner's non-warning state, borrowed for visual
// consistency, but its own component with its own (much simpler) data.
export default function DelayedBillingBanner({ commencementDate }) {
  const formatted = commencementDate.toLocaleDateString(undefined, {
    month: "long",
    day: "numeric",
    year: "numeric",
  });

  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: "10px",
        background: "linear-gradient(90deg, #F0F9FF 0%, #E0F2FE 100%)",
        border: "1px solid #BAE6FD",
        borderRadius: "12px",
        padding: "14px 16px",
        margin: "20px 0",
      }}
    >
      <Clock size={18} color="#0369A1" style={{ flexShrink: 0, marginTop: "1px" }} />
      <p style={{ fontSize: "13px", color: "#075985", margin: 0, lineHeight: 1.5 }}>
        <strong>Your 30-day trial starts today.</strong> You won't be charged until{" "}
        <strong>{formatted}</strong> — cancel anytime before then.
      </p>
    </div>
  );
}
