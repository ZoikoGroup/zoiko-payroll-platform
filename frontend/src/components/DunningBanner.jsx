import { useEffect, useState } from "react";
import { AlertTriangle, ShieldCheck, ShieldAlert, CreditCard } from "lucide-react";
import { getDunningStatus, createBillingPortalSession } from "../service/billingService";

// Parallel component to TrialBanner.jsx — same escalation-color
// convention, but escalating over BillingDunningState.stage instead of
// trial days remaining. Step 4 / blocker #17.
const STAGE_COPY = {
  RETRY: {
    badge: "Payment Issue",
    message:
      "We couldn't process your last payment. Nothing is restricted yet — update your payment method to avoid any disruption.",
  },
  RESTRICT_EXPANSION: {
    badge: "Payment Overdue",
    message:
      "Adding new legal entities or jurisdictions is blocked until payment is resolved. Existing payroll runs are not affected.",
  },
  RESTRICT_NEW_RUN: {
    badge: "New Runs Blocked",
    message:
      "Creating new payroll runs is blocked until payment is resolved. Already-authorized runs are not affected and will complete normally.",
  },
  READ_ONLY: {
    badge: "Read-Only Mode",
    message:
      "Your workspace is read-only due to overdue payment. Update your payment method to restore full access.",
  },
};

const STAGE_THEME = {
  RETRY: {
    bg: "linear-gradient(90deg, #FFFBEB 0%, #FEF3C7 100%)",
    border: "#FDE68A",
    text: "#92400E",
    badgeBg: "#FEF3C7",
    badgeText: "#B45309",
    btnBg: "linear-gradient(135deg, #D97706, #B45309)",
  },
  RESTRICT_EXPANSION: {
    bg: "linear-gradient(90deg, #FFF7ED 0%, #FFEDD5 100%)",
    border: "#FDBA74",
    text: "#9A3412",
    badgeBg: "#FFEDD5",
    badgeText: "#C2410C",
    btnBg: "linear-gradient(135deg, #EA580C, #C2410C)",
  },
  RESTRICT_NEW_RUN: {
    bg: "linear-gradient(90deg, #FEF2F2 0%, #FFE4E6 100%)",
    border: "#FCA5A5",
    text: "#991B1B",
    badgeBg: "#FEE2E2",
    badgeText: "#B91C1C",
    btnBg: "linear-gradient(135deg, #DC2626, #B91C1C)",
  },
  READ_ONLY: {
    bg: "linear-gradient(90deg, #FEF2F2 0%, #FFF1F2 100%)",
    border: "#FCA5A5",
    text: "#991B1B",
    badgeBg: "#FEE2E2",
    badgeText: "#991B1B",
    btnBg: "linear-gradient(135deg, #E11D48, #BE123C)",
  },
};

export default function DunningBanner() {
  const [dunning, setDunning] = useState(null);
  const [portalLoading, setPortalLoading] = useState(false);
  const [portalError, setPortalError] = useState("");

  useEffect(() => {
    let cancelled = false;
    getDunningStatus()
      .then((data) => {
        if (!cancelled) setDunning(data || null);
      })
      .catch(() => {
        if (!cancelled) setDunning(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!dunning) return null;

  const stage = dunning.stage in STAGE_COPY ? dunning.stage : "RETRY";
  const copy = STAGE_COPY[stage];
  const theme = STAGE_THEME[stage];
  const protectedByInFlightRun = !!dunning.in_flight_run_guard;

  async function handleUpdatePaymentMethod() {
    setPortalLoading(true);
    setPortalError("");
    try {
      const { portal_url } = await createBillingPortalSession();
      window.location.href = portal_url;
    } catch (err) {
      setPortalError(err?.message || "Could not open the billing portal. Please try again.");
      setPortalLoading(false);
    }
  }

  return (
    <div
      role="region"
      aria-label="Payment issue status"
      style={{
        background: theme.bg,
        borderBottom: `1px solid ${theme.border}`,
        color: theme.text,
        padding: "12px 24px",
        fontFamily: "'Inter', system-ui, sans-serif",
      }}
      className="w-full transition-colors duration-200 shadow-sm"
    >
      <div className="mx-auto flex max-w-7xl flex-col gap-2.5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <div
              className="flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-bold uppercase tracking-wider shadow-sm"
              style={{ backgroundColor: theme.badgeBg, color: theme.badgeText }}
            >
              {stage === "READ_ONLY" ? (
                <ShieldAlert size={14} className="shrink-0" />
              ) : (
                <AlertTriangle size={14} className="shrink-0" />
              )}
              <span>{copy.badge}</span>
            </div>

            <div className="text-xs sm:text-sm font-medium">{copy.message}</div>

            {protectedByInFlightRun && (
              <div
                className="flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-bold"
                style={{ backgroundColor: "#DCFCE7", color: "#166534" }}
                title="A payroll run you already authorized is protected and will complete normally."
              >
                <ShieldCheck size={14} className="shrink-0" />
                <span>Authorized run protected</span>
              </div>
            )}
          </div>

          <button
            type="button"
            onClick={handleUpdatePaymentMethod}
            disabled={portalLoading}
            style={{ background: theme.btnBg, color: "#FFFFFF", boxShadow: "0 2px 8px rgba(0,0,0,0.12)" }}
            className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg px-4 py-1.5 text-xs font-bold transition-all hover:opacity-95 hover:shadow-md active:scale-95 disabled:opacity-60"
          >
            <CreditCard size={14} />
            <span>{portalLoading ? "Opening…" : "Update Payment Method"}</span>
          </button>
        </div>

        {portalError && <div className="text-xs font-semibold">{portalError}</div>}
      </div>
    </div>
  );
}
