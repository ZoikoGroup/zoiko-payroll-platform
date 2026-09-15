import { useEffect, useState } from "react";
import { Hourglass } from "lucide-react";

import { apiFetch } from "../../../api/client";

const DAY_MS = 86400000;
const WARN_BELOW_DAYS = 7;

function clamp01(value) {
  return Math.max(0, Math.min(1, value));
}

function daysBetween(isoEnd) {
  if (!isoEnd) return null;
  const end = new Date(isoEnd).getTime();
  if (Number.isNaN(end)) return null;
  return (end - Date.now()) / DAY_MS;
}

export default function TrialProgressBar() {
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

  if (!trial || !trial.trial_started_at || !trial.trial_expires_at) return null;

  const start = new Date(trial.trial_started_at).getTime();
  const end = new Date(trial.trial_expires_at).getTime();
  const now = Date.now();
  const totalMs = end - start;
  if (Number.isNaN(start) || Number.isNaN(end) || totalMs <= 0) return null;

  const remainingDays = Math.max(0, Math.ceil(daysBetween(trial.trial_expires_at) ?? 0));
  const remainingFraction = clamp01((end - now) / totalMs);

  const isClosed = trial.trial_status === "CLOSED";
  const isGrace = trial.trial_status === "GRACE_READONLY";
  const low = remainingDays < WARN_BELOW_DAYS;

  // Fill depletes as the trial window closes out. Status drives the color:
  // normal = primary, low = warning, grace/closed = error.
  const color = isGrace || isClosed
    ? "var(--color-error)"
    : low
      ? "var(--color-warning)"
      : "var(--color-primary)";
  const track = isGrace || isClosed
    ? "var(--color-error-light)"
    : low
      ? "var(--color-warning-light)"
      : "var(--color-primary-light)";

  const expiresLabel = new Date(trial.trial_expires_at).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });

  const subtitle = isGrace
    ? "Your evaluation has ended — this workspace is read-only."
    : isClosed
      ? "Your evaluation is closed."
      : `Evaluating since ${new Date(trial.trial_started_at).toLocaleDateString(undefined, {
          month: "short",
          day: "numeric",
        })} · ends ${expiresLabel}`;

  return (
    <div
      className="rounded-[18px] border p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]"
      style={{ backgroundColor: "var(--color-surface)", borderColor: "var(--color-border)" }}
      role="region"
      aria-label="Trial time remaining"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-[13px] font-bold text-foreground">
          <Hourglass size={16} aria-hidden="true" />
          Evaluation time remaining
        </div>
        <div
          className="text-[13px] font-extrabold"
          style={{ color }}
        >
          {isGrace || isClosed
            ? "Ended"
            : `${remainingDays} day${remainingDays === 1 ? "" : "s"} left`}
        </div>
      </div>

      <div
        className="mt-3 h-2.5 w-full overflow-hidden rounded-full"
        style={{ backgroundColor: track }}
      >
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${remainingFraction * 100}%`, backgroundColor: color }}
        />
      </div>

      <p className="mt-2 text-[11px] font-medium text-foreground-muted">{subtitle}</p>
    </div>
  );
}