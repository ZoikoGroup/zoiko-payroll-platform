import { useCallback, useEffect, useState } from "react";
import { Headphones, Clock, ShieldAlert } from "lucide-react";
import { apiFetch } from "../api/client";

const POLL_MS = 30000;

// The API sends naive UTC timestamps ("2026-10-13T07:51:55"); new Date() would
// read those as LOCAL time and, east of UTC, show a live session as expired.
function parseUtc(value) {
  if (!value) return null;
  const s = String(value);
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : `${s}Z`);
}

function formatCountdown(expiresMs) {
  const msLeft = expiresMs - Date.now();
  if (msLeft <= 0) return "expired";
  const totalSec = Math.floor(msLeft / 1000);
  const mm = String(Math.floor(totalSec / 60)).padStart(2, "0");
  const ss = String(totalSec % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

// Zoiko support access to this organisation. A support session needs this
// organisation's admin to approve it first (consent); an emergency
// "break-glass" session is approved by a second Zoiko Super Admin and is
// announced here and by email. The server enforces every rule — these buttons
// only route the decision.
function PendingRequests({ onDecided }) {
  const [requests, setRequests] = useState([]);
  const [reason, setReason] = useState({});
  const [error, setError] = useState(null);
  const load = useCallback(() => {
    apiFetch("/api/organization-admin/assisted-access/requests")
      .then((d) => setRequests(d?.requests || []))
      .catch(() => setRequests([]));
  }, []);
  useEffect(() => { load(); }, [load]);
  async function decide(id, action) {
    setError(null);
    try {
      await apiFetch(`/api/organization-admin/assisted-access/requests/${id}/${action}`, {
        method: "POST", body: { reason: reason[id] || "" },
      });
      load();
      onDecided();
    } catch (e) {
      setError(e?.message || "The decision was not accepted.");
    }
  }
  if (!requests.length) return null;
  return (
    <div role="region" aria-label="Zoiko support access requests"
      className="w-full border-b border-amber-200 bg-amber-50 px-6 py-2.5 text-amber-900">
      <div className="mx-auto max-w-7xl space-y-1.5">
        {error && <p role="alert" className="text-xs font-semibold text-red-700">{error}</p>}
        {requests.map((r) => (
          <div key={r.session_id} className="flex flex-wrap items-center gap-2 text-xs sm:text-sm">
            <Headphones size={15} className="shrink-0 text-amber-600" />
            <span className="font-medium">
              Zoiko support asks to access your organisation for {r.requested_minutes} min: “{r.reason}”.
            </span>
            <input aria-label={`Reason for decision on request ${r.session_id}`} placeholder="Reason (required to reject)"
              className="rounded border border-amber-300 bg-white px-2 py-0.5 text-xs"
              value={reason[r.session_id] || ""} onChange={(e) => setReason({ ...reason, [r.session_id]: e.target.value })} />
            <button type="button" className="rounded bg-amber-600 px-2 py-0.5 text-xs font-semibold text-white"
              onClick={() => decide(r.session_id, "approve")}>Approve</button>
            <button type="button" className="rounded border border-amber-400 px-2 py-0.5 text-xs font-semibold disabled:opacity-50"
              disabled={!(reason[r.session_id] || "").trim()} onClick={() => decide(r.session_id, "reject")}>Reject</button>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function AssistedAccessBanner() {
  const [status, setStatus] = useState(null);
  const [pending, setPending] = useState(0);
  const [expiresMs, setExpiresMs] = useState(null);
  const [countdown, setCountdown] = useState("");
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const check = () => {
      apiFetch("/api/organization-admin/assisted-access/status")
        .then((data) => {
          if (cancelled) return;
          setStatus(data.active ? data : null);
          setPending(data.pending_requests || 0);
          setExpiresMs(data.active && data.expires_at ? parseUtc(data.expires_at).getTime() : null);
        })
        .catch(() => {
          if (!cancelled) { setStatus(null); setPending(0); }
        });
    };
    check();
    const interval = setInterval(check, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [tick]);

  useEffect(() => {
    if (!expiresMs) {
      setCountdown("");
      return;
    }
    let interval = null;
    const step = () => {
      const left = expiresMs - Date.now();
      if (left <= 0) {
        setCountdown("expired");
        setStatus(null);
        if (interval) clearInterval(interval);
        return;
      }
      setCountdown(formatCountdown(expiresMs));
    };
    step();
    interval = setInterval(step, 1000);
    return () => {
      if (interval) clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expiresMs]);

  return (
    <>
      {pending > 0 && <PendingRequests onDecided={() => setTick((t) => t + 1)} />}
      {status && (
        <div
          role="region"
          aria-label="Zoiko assisted access active"
          className={`w-full border-b px-6 py-2.5 shadow-sm ${status.break_glass
            ? "border-red-200 bg-red-50 text-red-900" : "border-sky-200 bg-gradient-to-r from-sky-50 to-indigo-50 text-sky-900"}`}
        >
          <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-x-4 gap-y-1">
            <div className="flex items-center gap-2 text-xs sm:text-sm font-medium">
              {status.break_glass
                ? <ShieldAlert size={15} className="shrink-0 text-red-600" />
                : <Headphones size={15} className="shrink-0 text-sky-600" />}
              <span>
                {status.break_glass
                  ? "Zoiko support has EMERGENCY (break-glass) access to your organization, approved by a second Zoiko Super Admin. Your admins were emailed."
                  : "Zoiko support is currently assisting your organization (approved by your admin)."}
                {status.started_at && (
                  <span className="opacity-80"> Started {parseUtc(status.started_at).toLocaleTimeString()}.</span>
                )}
              </span>
            </div>
            <div className="flex items-center gap-1.5 text-xs font-semibold">
              <Clock size={13} className="shrink-0" />
              <span>Session ends in {countdown || "—"}.</span>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
