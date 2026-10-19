import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Clock, LogOut, ShieldCheck } from "lucide-react";
import { api } from "../service/api";
import { apiFetch, clearSession, getStoredUser } from "../api/client";
import { FIELD_CLASS_LABELS } from "../service/supportAccessService";
import { formatCountdown, formatDateTime, msUntil } from "../utils/time";
import useNow from "../utils/useNow";

// The only screen a temporary support login (role support_temp) can use: a
// read-only view of the employee records its grant covers. The server decides
// which records and which fields arrive (grant scope + field projection);
// this page just renders what it is given and never offers an edit or export.
function label(key) {
  return key.replace(/([A-Z])/g, " $1").replace(/^./, (c) => c.toUpperCase());
}

export default function SupportSessionPage() {
  const navigate = useNavigate();
  const user = getStoredUser();
  const now = useNow(1000);
  const [session, setSession] = useState(null);
  const [rows, setRows] = useState(null);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState(null);
  const [ended, setEnded] = useState(false);

  useEffect(() => {
    apiFetch("/api/auth/me")
      .then((me) => setSession(me?.support_session || null))
      .catch(() => setSession(null));
    api.get("/api/payroll/employees")
      .then(setRows)
      .catch((err) => {
        setRows([]);
        if (err.status === 401) setEnded(true);
        else setError(err.status === 403
          ? "This session covers organization settings only (diagnostics); it has no employee records."
          : err.message || "Could not load records.");
      });
  }, []);

  const remaining = session?.expiresAt ? msUntil(session.expiresAt, now) : null;
  const expired = ended || (remaining != null && remaining <= 0);

  async function signOut() {
    try {
      await apiFetch("/api/auth/logout", { method: "POST", body: {} });
    } catch {
      // the session may already have ended
    }
    clearSession();
    navigate("/login", { replace: true });
  }

  const fields = (session?.allowedFieldClasses || []).map((c) => FIELD_CLASS_LABELS[c] || c);

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
        <div className="rounded-xl border border-warning/40 bg-warning-light p-4 text-sm">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="flex items-center gap-2 text-base font-semibold text-foreground">
                <ShieldCheck size={18} className="text-warning" />
                Support session{session?.organizationName ? ` · ${session.organizationName}` : ""}
                {session?.isBreakGlass && (
                  <span className="rounded-full bg-error-light px-2 py-0.5 text-xs font-semibold text-error">Emergency</span>
                )}
              </p>
              <p className="mt-1 text-foreground-secondary">
                Temporary, read-only login ({user?.email}). Every request is recorded in the organization&apos;s audit trail.
              </p>
            </div>
            <div className="flex items-center gap-3">
              {remaining != null && (
                <span className={`flex items-center gap-1.5 text-lg font-semibold tabular-nums ${expired ? "text-error" : "text-foreground"}`}
                  title={`Ends ${formatDateTime(session.expiresAt)}`}>
                  <Clock size={16} /> {expired ? "Ended" : formatCountdown(remaining)}
                </span>
              )}
              <button type="button" onClick={signOut}
                className="flex items-center gap-1.5 rounded-lg bg-warning px-3 py-1.5 font-medium text-white hover:opacity-90">
                <LogOut size={14} /> End session
              </button>
            </div>
          </div>
          {session && (
            <dl className="mt-3 grid gap-x-6 gap-y-1 text-xs sm:grid-cols-2 lg:grid-cols-4">
              <div><dt className="text-foreground-muted">Ticket</dt><dd className="font-mono text-foreground">{session.ticketReference || "—"}</dd></div>
              <div><dt className="text-foreground-muted">Reason</dt><dd className="text-foreground">{session.reason || "—"}</dd></div>
              <div><dt className="text-foreground-muted">Scope</dt><dd className="text-foreground">{session.scope || "—"}</dd></div>
              <div><dt className="text-foreground-muted">Fields you may see</dt><dd className="text-foreground">{fields.join(", ") || "—"}</dd></div>
            </dl>
          )}
        </div>

        {expired && (
          <div role="status" className="rounded-xl border border-border bg-surface p-4 text-sm text-foreground">
            This support session has ended. Sign out and ask for a new request if more time is needed.
          </div>
        )}
        {error && !expired && <p role="status" className="text-sm text-foreground-secondary">{error}</p>}

        {!expired && (rows === null ? (
          <p className="text-sm text-foreground-secondary">Loading…</p>
        ) : (
          <div className="grid gap-4 md:grid-cols-[18rem_1fr]">
            <div className="rounded-xl border border-border-light bg-surface text-sm">
              <p className="border-b border-border-light px-3 py-2 text-xs font-semibold uppercase tracking-wide text-foreground-muted">
                Records in scope ({rows.length})
              </p>
              <ul className="divide-y divide-border-light">
                {rows.map((r) => (
                  <li key={r.id}>
                    <button type="button" onClick={() => setSelected(r)}
                      className={`w-full px-3 py-2 text-left hover:bg-surface-muted ${selected?.id === r.id ? "bg-surface-muted" : ""}`}>
                      <span className={`block ${selected?.id === r.id ? "font-semibold" : ""} text-foreground`}>{r.name || `Record ${r.id}`}</span>
                      {r.employeeCode && <span className="block font-mono text-xs text-foreground-muted">{r.employeeCode}</span>}
                    </button>
                  </li>
                ))}
                {rows.length === 0 && !error && <li className="px-3 py-2 text-foreground-secondary">No records in scope.</li>}
              </ul>
            </div>
            <div className="rounded-xl border border-border-light bg-surface p-4 text-sm">
              {selected ? (
                <dl className="grid gap-3 sm:grid-cols-2">
                  {Object.entries(selected).filter(([, v]) => v !== null && v !== "" && typeof v !== "object").map(([k, v]) => (
                    <div key={k}>
                      <dt className="text-xs text-foreground-secondary">{label(k)}</dt>
                      <dd className="break-words text-foreground">{String(v)}</dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p className="text-foreground-secondary">
                  Choose a record. Only the fields the organization allowed are shown
                  {fields.length ? ` (${fields.join(", ")})` : ""}. Nothing here can be edited or exported.
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
