import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Clock, AlertTriangle, ArrowRight, ShieldAlert, Sparkles } from "lucide-react";
import { apiFetch } from "../api/client";

const DAY_MS = 86400000;
const WARN_BELOW_DAYS = 7;
const STATUS_REFRESH_MS = 60000;

function daysRemaining(iso, now = Date.now()) {
  if (!iso) return null;
  const end = new Date(iso).getTime();
  if (Number.isNaN(end)) return null;
  return Math.ceil((end - now) / DAY_MS);
}

function dateMs(iso) {
  if (!iso) return null;
  const value = new Date(iso).getTime();
  return Number.isNaN(value) ? null : value;
}

export default function TrialBanner() {
  const [trial, setTrial] = useState(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    let cancelled = false;
    const loadTrialStatus = () => {
      apiFetch("/api/auth/me/trial-status")
        .then((data) => {
          if (cancelled) return;
          setTrial(data && data.workspace_type === "EVALUATION" ? data : null);
        })
        .catch(() => {
          if (!cancelled) setTrial(null);
        });
    };

    loadTrialStatus();
    const refreshTimer = window.setInterval(loadTrialStatus, STATUS_REFRESH_MS);
    const clockTimer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => {
      cancelled = true;
      window.clearInterval(refreshTimer);
      window.clearInterval(clockTimer);
    };
  }, []);

  if (!trial) return null;

  // Flexible field extraction supporting multiple backend payload structures
  const expiresIso = trial.trial_expires_at || trial.current_period_end || trial.expires_at;
  const startedIso = trial.trial_started_at || trial.current_period_start || trial.started_at;
  const statusStr = trial.trial_status || trial.status;

  const rawRemaining = daysRemaining(expiresIso, now);
  const displayDays = rawRemaining !== null ? Math.max(0, rawRemaining) : null;
  const startMs = dateMs(startedIso);
  const endMs = dateMs(expiresIso);
  const trialLengthDays = startMs !== null && endMs !== null && endMs > startMs
    ? Math.max(1, Math.ceil((endMs - startMs) / DAY_MS))
    : null;

  const isGrace = statusStr === "GRACE_READONLY";
  const isClosed = statusStr === "CLOSED";
  const isWarning = displayDays !== null && displayDays <= WARN_BELOW_DAYS && !isGrace && !isClosed;

  // Calculate progress percentage
  let percentRemaining = 100;
  if (expiresIso) {
    const totalMs = startMs !== null && endMs !== null ? Math.max(1, endMs - startMs) : 1;
    const remainingMs = endMs !== null ? Math.max(0, endMs - now) : 0;
    percentRemaining = isGrace || isClosed ? 0 : Math.min(100, Math.max(0, (remainingMs / totalMs) * 100));
  }

  // Format expiry date string
  const expiryFormatted = expiresIso
    ? new Date(expiresIso).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
      })
    : null;

  // Theme styling based on urgency
  const theme = (isGrace || isClosed)
    ? {
        bg: "linear-gradient(90deg, #FEF2F2 0%, #FFF1F2 100%)",
        border: "#FCA5A5",
        text: "#991B1B",
        badgeBg: "#FEE2E2",
        badgeText: "#991B1B",
        barTrack: "#FECDD3",
        barFill: "#E11D48",
        btnBg: "linear-gradient(135deg, #E11D48, #BE123C)",
        btnText: "#FFFFFF",
      }
    : isWarning
    ? {
        bg: "linear-gradient(90deg, #FFFBEB 0%, #FEF3C7 100%)",
        border: "#FDE68A",
        text: "#92400E",
        badgeBg: "#FEF3C7",
        badgeText: "#B45309",
        barTrack: "#FDE68A",
        barFill: "#D97706",
        btnBg: "linear-gradient(135deg, #D97706, #B45309)",
        btnText: "#FFFFFF",
      }
    : {
        bg: "linear-gradient(90deg, #F0F9FF 0%, #E0F2FE 100%)",
        border: "#BAE6FD",
        text: "#075985",
        badgeBg: "#E0F2FE",
        badgeText: "#0369A1",
        barTrack: "#BAE6FD",
        barFill: "#0EA5E9",
        btnBg: "linear-gradient(135deg, #0EA5E9, #0284C7)",
        btnText: "#FFFFFF",
      };

  return (
    <div
      role="region"
      aria-label="Evaluation workspace status"
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
        {/* Top Row: Badge, Summary Message & Upgrade CTA Button */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <div
              className="flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-bold uppercase tracking-wider shadow-sm"
              style={{ backgroundColor: theme.badgeBg, color: theme.badgeText }}
            >
              {isGrace || isClosed ? (
                <ShieldAlert size={14} className="shrink-0" />
              ) : isWarning ? (
                <AlertTriangle size={14} className="shrink-0" />
              ) : (
                <Sparkles size={14} className="shrink-0" />
              )}
              <span>{isGrace ? "Read-Only Mode" : isClosed ? "Trial Closed" : "Evaluation"}</span>
            </div>

            <div className="text-xs sm:text-sm font-medium">
              {isGrace ? (
                <span>Your evaluation period has ended — workspace is now read-only.</span>
              ) : isClosed ? (
                <span>Your evaluation workspace has closed. Upgrade to restore access.</span>
              ) : (
                <span>
                  You are on{trialLengthDays ? ` a ${trialLengthDays}-day` : " an"} evaluation of <strong>Zoiko Payroll</strong>.
                </span>
              )}
            </div>
          </div>

          <Link
            to="/billing/plans"
            style={{
              background: theme.btnBg,
              color: theme.btnText,
              boxShadow: "0 2px 8px rgba(0,0,0,0.12)",
            }}
            className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg px-4 py-1.5 text-xs font-bold transition-all hover:opacity-95 hover:shadow-md active:scale-95"
          >
            <span>Choose Plan</span>
            <ArrowRight size={14} />
          </Link>
        </div>

        {/* Progress Bar Component directly below the banner text */}
        <div className="flex flex-col gap-1 pt-1">
          <div className="flex items-center justify-between text-xs font-semibold">
            <span className="flex items-center gap-1.5">
              <Clock size={14} className="opacity-80 shrink-0" />
              {isGrace || isClosed ? (
                <span className="font-bold">Evaluation Expired</span>
              ) : (
                <span>
                  <strong className="text-sm font-black" style={{ color: theme.text }}>
                    {displayDays === null ? "Calculating" : `${displayDays} day${displayDays === 1 ? "" : "s"}`}
                  </strong>{" "}
                  {displayDays === null ? "remaining" : `remaining${expiryFormatted ? ` (ends ${expiryFormatted})` : ""}`}
                </span>
              )}
            </span>
            <span className="font-extrabold text-xs">
              {isGrace || isClosed ? "0 Days Left" : displayDays === null ? "Status unavailable" : `${displayDays} Days Left (${Math.round(percentRemaining)}%)`}
            </span>
          </div>

          {/* Full-width clean Progress Bar */}
          <div
            className="h-2.5 w-full overflow-hidden rounded-full shadow-inner"
            style={{ backgroundColor: theme.barTrack }}
          >
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width: `${percentRemaining}%`,
                backgroundColor: theme.barFill,
              }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}