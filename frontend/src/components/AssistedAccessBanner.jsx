import { useEffect, useState } from "react";
import { Headphones, Clock } from "lucide-react";
import { apiFetch } from "../api/client";

const POLL_MS = 30000;

function formatCountdown(expiresMs) {
  const msLeft = expiresMs - Date.now();
  if (msLeft <= 0) return "expired";
  const totalSec = Math.floor(msLeft / 1000);
  const mm = String(Math.floor(totalSec / 60)).padStart(2, "0");
  const ss = String(totalSec % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

export default function AssistedAccessBanner() {
  const [status, setStatus] = useState(null);
  const [expiresMs, setExpiresMs] = useState(null);
  const [countdown, setCountdown] = useState("");

  useEffect(() => {
    let cancelled = false;
    const check = () => {
      apiFetch("/api/organization-admin/assisted-access/status")
        .then((data) => {
          if (cancelled) return;
          setStatus(data.active ? data : null);
          setExpiresMs(data.active && data.expires_at ? new Date(data.expires_at).getTime() : null);
        })
        .catch(() => {
          if (!cancelled) setStatus(null);
        });
    };
    check();
    const interval = setInterval(check, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    if (!expiresMs) {
      setCountdown("");
      return;
    }
    let interval = null;
    const tick = () => {
      const left = expiresMs - Date.now();
      if (left <= 0) {
        setCountdown("expired");
        setStatus(null);
        if (interval) clearInterval(interval);
        return;
      }
      setCountdown(formatCountdown(expiresMs));
    };
    tick();
    interval = setInterval(tick, 1000);
    return () => {
      if (interval) clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expiresMs]);

  if (!status) return null;

  return (
    <div
      role="region"
      aria-label="Zoiko assisted access active"
      className="w-full border-b border-sky-200 bg-gradient-to-r from-sky-50 to-indigo-50 px-6 py-2.5 text-sky-900 shadow-sm"
    >
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <div className="flex items-center gap-2 text-xs sm:text-sm font-medium">
          <Headphones size={15} className="shrink-0 text-sky-600" />
          <span>
            Zoiko support is currently assisting your organization.
            {status.started_at && (
              <span className="text-sky-700/80"> Started {new Date(status.started_at).toLocaleTimeString()}.</span>
            )}
          </span>
        </div>
        <div className="flex items-center gap-1.5 text-xs font-semibold text-sky-800">
          <Clock size={13} className="shrink-0" />
          <span>Session ends in {countdown || "—"}.</span>
        </div>
      </div>
    </div>
  );
}