import { useEffect, useState } from "react";
import { TriangleAlert } from "lucide-react";

import { apiFetch } from "../api/client";

const DAY_MS = 86400000;
const ESCALATE_BELOW_DAYS = 7;

function daysRemaining(iso) {
  if (!iso) return null;
  const end = new Date(iso).getTime();
  if (Number.isNaN(end)) return null;
  return Math.ceil((end - Date.now()) / DAY_MS);
}

export default function TrialBanner() {
  const [trial, setTrial] = useState(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch("/api/auth/me/trial-status")
      .then((data) => {
        if (cancelled) return;
        if (data && data.workspace_type === "EVALUATION") setTrial(data);
      })
      .catch(() => {
        if (!cancelled) setTrial(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!trial) return null;

  const remaining = daysRemaining(trial.trial_expires_at);
  const escalated =
    trial.trial_status !== "ACTIVE" ||
    (remaining !== null && remaining < ESCALATE_BELOW_DAYS);

  const summary = trial.trial_status === "GRACE_READONLY"
    ? "Your Zoiko Payroll evaluation period has ended — this workspace is now read-only."
    : trial.trial_status === "CLOSED"
      ? "Your Zoiko Payroll evaluation is closed."
      : "You're on a 30-day Zoiko Payroll evaluation (Professional plan).";

  const expiry = trial.trial_expires_at
    ? new Date(trial.trial_expires_at).toLocaleDateString(undefined, {
        year: "numeric",
        month: "long",
        day: "numeric",
      })
    : "";

  const palette = escalated
    ? { bg: "var(--color-error-light)", color: "var(--color-error)", border: "var(--color-error)" }
    : { bg: "var(--color-warning-light)", color: "var(--color-warning)", border: "var(--color-warning)" };

  return (
    <div
      className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b px-4 py-2 text-sm"
      style={{ backgroundColor: palette.bg, color: palette.color, borderColor: palette.border }}
      role="region"
      aria-label="Evaluation workspace notice"
    >
      <TriangleAlert size={16} className="shrink-0" aria-hidden="true" />
      <span>
        {summary}
        {remaining !== null && remaining >= 0 ? (
          <>
            {" "}
            Your evaluation ends in <strong>{remaining} days</strong>
            {expiry ? ` (${expiry})` : ""}.
          </>
        ) : null}
      </span>
      <span className="hidden text-xs opacity-80 sm:inline">
        Preview only — no live payments, filings, or remittances are processed in this workspace.
        Your evaluation will not automatically convert to a paid subscription or charge you.
      </span>
      <a
        href="https://zoikoone.com"
        target="_blank"
        rel="noopener noreferrer"
        className="ml-auto whitespace-nowrap font-semibold underline-offset-2 hover:underline"
        style={{ color: palette.color }}
      >
        Choose a plan
      </a>
    </div>
  );
}