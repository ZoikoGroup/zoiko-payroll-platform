/**
 * pages/CheckoutSuccessPage.jsx
 * ------------------------------
 * Stripe redirects here after a successful payment.
 * Route: /billing/checkout/success
 *
 * Stripe appends ?session_id={CHECKOUT_SESSION_ID}. The page asks the
 * server to confirm that session (POST /billing/checkout/confirm): the
 * server re-reads it from Stripe and activates the subscription itself, so
 * activation no longer depends on the webhook reaching this environment.
 * Without a session_id (an old link) it falls back to polling the
 * subscription. A deferred-commencement checkout lands as TRIALING, which
 * is a success too (no charge until the commencement date).
 */

import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";
import { confirmCheckoutSession, getMySubscription } from "../service/billingService";

const MAX_ATTEMPTS = 10;
const RETRY_INTERVAL_MS = 2000;
const SUCCESS_STATUSES = ["ACTIVE", "TRIALING"];
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

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
  const [searchParams] = useSearchParams();
  const sessionId = searchParams.get("session_id");
  // "polling" | "active" | "deferred" | "pending" | "error"
  const [status, setStatus] = useState("polling");
  const [detail, setDetail] = useState({ planCode: null, trialEndsAt: null, message: "" });

  useEffect(() => {
    let cancelled = false;

    // One attempt: confirm the session (authoritative, activates it) or, for
    // a link without session_id, read the subscription the webhook wrote.
    const attempt = async () => {
      if (sessionId) {
        const res = await confirmCheckoutSession(sessionId);
        return { status: res?.status, planCode: res?.plan_code, deferred: !!res?.deferred,
          trialEndsAt: res?.trial_ends_at || null };
      }
      const sub = (await getMySubscription())?.subscription;
      return { status: sub?.status, planCode: null, deferred: sub?.status === "TRIALING", trialEndsAt: null };
    };

    (async () => {
      let lastMessage = "";
      for (let i = 0; i < MAX_ATTEMPTS && !cancelled; i += 1) {
        try {
          const result = await attempt();
          if (cancelled) return;
          if (SUCCESS_STATUSES.includes(result.status)) {
            setDetail({ planCode: result.planCode, trialEndsAt: result.trialEndsAt, message: "" });
            setStatus(result.deferred ? "deferred" : "active");
            return;
          }
        } catch (e) {
          if (cancelled) return;
          // Wrong organisation / unknown session: retrying cannot help.
          if (e?.status === 403 || (sessionId && e?.status === 404)) {
            setDetail((d) => ({ ...d, message: e.message }));
            setStatus("error");
            return;
          }
          // 400 "not completed yet" (async payment) or 404 before the
          // webhook wrote the row — keep trying for a little while.
          lastMessage = e?.message || "";
        }
        await sleep(RETRY_INTERVAL_MS);
      }
      if (!cancelled) {
        setDetail((d) => ({ ...d, message: lastMessage }));
        setStatus("pending");
      }
    })();

    return () => { cancelled = true; };
  }, [sessionId]);

  const trialEndsLabel = detail.trialEndsAt
    ? new Date(detail.trialEndsAt.endsWith("Z") ? detail.trialEndsAt : `${detail.trialEndsAt}Z`).toLocaleDateString()
    : null;

  return (
    <div style={containerStyle}>
      <div style={cardStyle}>
        {status === "error"
          ? <AlertTriangle size={64} style={{ color: "#F59E0B" }} />
          : <CheckCircle2 size={64} style={{ color: "#22C55E" }} />}

        <h1 style={{ fontSize: "26px", fontWeight: "800", color: "#0F172A", margin: 0 }}>
          {status === "error" ? "We couldn't confirm this checkout" : "Payment successful!"}
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
              Your {detail.planCode ? <strong>{detail.planCode}</strong> : null} subscription is now{" "}
              <strong style={{ color: "#16A34A" }}>ACTIVE</strong>.
              Welcome aboard! You now have full access to all payroll features.
            </p>
            <button style={buttonStyle} onClick={() => navigate("/")}>
              Go to Dashboard
            </button>
          </>
        )}

        {status === "deferred" && (
          <>
            <p style={{ color: "#6B7280", fontSize: "15px", margin: 0 }}>
              Your {detail.planCode ? <strong>{detail.planCode}</strong> : null} subscription is set up.
              You have full payroll access during your trial, and you won&apos;t be charged
              {trialEndsLabel ? ` until ${trialEndsLabel}` : " until your service start date"}.
            </p>
            <button style={buttonStyle} onClick={() => navigate("/")}>
              Go to Dashboard
            </button>
          </>
        )}

        {status === "pending" && (
          <>
            <p style={{ color: "#6B7280", fontSize: "15px", margin: 0 }}>
              Your payment was received, but Stripe hasn&apos;t confirmed it to us yet. Your
              subscription activates automatically as soon as it does — check the Subscription
              page in a minute.
            </p>
            {detail.message && (
              <p style={{ color: "#9CA3AF", fontSize: "13px", margin: 0 }}>{detail.message}</p>
            )}
            <button style={buttonStyle} onClick={() => window.location.reload()}>
              Check again
            </button>
          </>
        )}

        {status === "error" && (
          <>
            <p style={{ color: "#6B7280", fontSize: "15px", margin: 0 }}>
              {detail.message || "This checkout could not be matched to your organization."} If you
              were charged, contact support with the time of your payment.
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
