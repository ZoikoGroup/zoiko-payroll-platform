import { useEffect, useState } from "react";
import { TriangleAlert } from "lucide-react";

import { apiFetch } from "../api/client";

const TRIALING = "TRIALING";

function formatEnd(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
}

export default function TrialBanner() {
  const [trial, setTrial] = useState(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch("/api/billing/trial-status")
      .then((data) => {
        if (!cancelled && data && data.status === TRIALING) setTrial(data);
      })
      .catch(() => {
        if (!cancelled) setTrial(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!trial) return null;

  const end = formatEnd(trial.current_period_end);

  return (
    <div className="flex items-center gap-2 bg-amber-50 px-4 py-2 text-sm text-amber-800">
      <TriangleAlert size={16} className="shrink-0" aria-hidden="true" />
      <span>
        You're on a 30-day Zoiko Payroll evaluation (Professional plan). Your evaluation ends on{" "}
        <strong>{end}</strong>.
      </span>
    </div>
  );
}