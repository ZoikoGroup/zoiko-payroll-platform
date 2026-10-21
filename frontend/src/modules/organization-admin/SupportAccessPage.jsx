import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Loader2 } from "lucide-react";
import Modal from "../../components/Modal";
import { FIELD_CLASS_LABELS, supportAccessTenant as svc } from "../../service/supportAccessService";
import { formatCountdown, formatDateTime, msUntil } from "../../utils/time";
import useNow from "../../utils/useNow";

// "Platform Support Access" for organization admins (ZP-PRIV D.6): approve,
// decline or revoke Zoiko support's temporary, read-only access, and read the
// organization's own support-access audit trail.
const card = "rounded-xl border border-border-light bg-surface p-5 shadow-sm";
const btn = "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium disabled:opacity-50";
const primary = `${btn} bg-blue-600 text-white hover:bg-blue-700`;
const subtle = `${btn} border border-border-light text-foreground hover:bg-surface-muted`;
const danger = `${btn} bg-red-600 text-white hover:bg-red-700`;
const input = "w-full rounded-lg border border-border-light bg-surface px-3 py-2 text-sm text-foreground";

const STATUS_BADGE = {
  active: "bg-emerald-100 text-emerald-800",
  denied: "bg-slate-200 text-slate-700",
  cancelled: "bg-slate-200 text-slate-700",
  revoked: "bg-red-100 text-red-800",
  exited: "bg-slate-200 text-slate-700",
  expired: "bg-slate-200 text-slate-700",
  expired_unused: "bg-amber-100 text-amber-800",
  pending_approval: "bg-blue-100 text-blue-800",
};

function Detail({ label, children }) {
  return (
    <div>
      <dt className="text-xs text-foreground-secondary">{label}</dt>
      <dd className="text-sm text-foreground">{children}</dd>
    </div>
  );
}

function scopeText(g) {
  if (g.scopeEntityName) return `${g.scopeLabel}: ${g.scopeEntityName}`;
  if (g.scopePayGroupName) return `${g.scopeLabel}: ${g.scopePayGroupName}`;
  return g.scopeLabel;
}

function ApproveDialog({ grant, choices, defaults, onClose, onDone }) {
  const resolved = grant.resolvedEmployees?.resolved || [];
  const unresolved = grant.resolvedEmployees?.unresolved || [];
  const [fields, setFields] = useState(new Set(defaults));
  const [employees, setEmployees] = useState(new Set(resolved.map((e) => e.employeeId)));
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  function toggle(set, setter, key) {
    const next = new Set(set);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setter(next);
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await svc.approve(grant.id, {
        note: note || undefined,
        fieldClasses: [...fields],
        employeeIds: grant.scopeType === "employees" ? [...employees] : undefined,
      });
      onDone("Approved.");
      onClose();
    } catch (err) {
      setError(err.message || "The approval could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  const scopeSummary = grant.scopeType === "employees" ? `${employees.size} named employee(s)` : scopeText(grant);
  return (
    <Modal title="Approve support access" onClose={onClose} maxWidth="max-w-xl">
      <div className="space-y-4 text-sm">
        <p className="rounded-lg bg-blue-50 p-3 text-blue-900 dark:bg-blue-900/30 dark:text-blue-100">
          Zoiko support gets a temporary, read-only login for {grant.requestedMinutes} minutes, limited to {scopeSummary}
          {" "}and the fields you tick below. It stops automatically; you can revoke it at any time.
          {grant.zoikoRequired && " A Zoiko Platform Security officer must also approve before it starts."}
        </p>
        {grant.scopeType === "employees" && (
          <fieldset className="space-y-1">
            <legend className="font-medium text-foreground">Employees named in the request</legend>
            {resolved.map((e) => (
              <label key={e.employeeId} className="flex items-center gap-2 text-foreground">
                <input type="checkbox" checked={employees.has(e.employeeId)}
                  onChange={() => toggle(employees, setEmployees, e.employeeId)} />
                {e.name} · {e.employeeCode}
              </label>
            ))}
            {unresolved.length > 0 && (
              <p className="text-xs text-foreground-secondary">Not found in your organization: {unresolved.join(", ")}</p>
            )}
            <p className="text-xs text-foreground-secondary">You can remove employees but not add others.</p>
          </fieldset>
        )}
        <fieldset className="space-y-1">
          <legend className="font-medium text-foreground">Fields support may see</legend>
          {choices.map((c) => (
            <label key={c} className="flex items-center gap-2 text-foreground">
              <input type="checkbox" checked={fields.has(c)} disabled={c === "identifier"}
                onChange={() => toggle(fields, setFields, c)} />
              {FIELD_CLASS_LABELS[c] || c}
              {c === "identifier" && <span className="text-xs text-foreground-secondary">(always included)</span>}
            </label>
          ))}
        </fieldset>
        <textarea className={input} rows={2} placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
        {error && <p role="alert" className="text-red-600">{error}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" className={subtle} onClick={onClose}>Cancel</button>
          <button type="button" className={primary} onClick={submit}
            disabled={busy || (grant.scopeType === "employees" && employees.size === 0)}>
            {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />} Approve
          </button>
        </div>
      </div>
    </Modal>
  );
}

function ReasonDialog({ title, action, onSubmit, onClose }) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState(null);
  return (
    <Modal title={title} onClose={onClose}>
      <textarea className={input} rows={3} placeholder="Reason (required)" value={reason} onChange={(e) => setReason(e.target.value)} />
      {error && <p role="alert" className="mt-2 text-sm text-red-600">{error}</p>}
      <div className="mt-3 flex justify-end gap-2">
        <button type="button" className={subtle} onClick={onClose}>Cancel</button>
        <button
          type="button"
          className={danger}
          disabled={!reason.trim()}
          onClick={async () => {
            try {
              await onSubmit(reason);
              onClose();
            } catch (err) {
              setError(err.message || "The action failed.");
            }
          }}
        >
          {action}
        </button>
      </div>
    </Modal>
  );
}

function AuditTab() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    svc.audit().then(setRows).catch((err) => setError(err.message || "Could not load the audit trail."));
  }, []);
  if (error) return <p role="alert" className="text-sm text-red-600">{error}</p>;
  if (!rows) return <p className="text-sm text-foreground-secondary">Loading…</p>;
  if (!rows.length) return <p className="text-sm text-foreground-secondary">No support access activity yet.</p>;
  return (
    <div className={`${card} overflow-x-auto`}>
      <table className="w-full text-left text-sm">
        <thead className="text-foreground-secondary">
          <tr><th className="py-2 pr-3">When</th><th className="pr-3">Event</th><th className="pr-3">Who</th>
            <th className="pr-3">On behalf of</th><th className="pr-3">Access</th><th className="pr-3">Ticket</th><th>Details</th></tr>
        </thead>
        <tbody className="divide-y divide-border-light text-foreground">
          {rows.map((e) => (
            <tr key={e.id}>
              <td className="py-2 pr-3 whitespace-nowrap">{formatDateTime(e.recordedAt)}</td>
              <td className="pr-3">{e.eventType.replaceAll("_", " ").toLowerCase()}</td>
              <td className="pr-3">{e.actorEmail || e.supportUsername || e.actorRole}</td>
              <td className="pr-3">{e.requesterEmail || "—"}</td>
              <td className="pr-3">{e.grantId ? `#${e.grantId}` : "—"}</td>
              <td className="whitespace-nowrap pr-3 font-mono text-xs">{e.ticketReference || "—"}</td>
              <td>{e.reason || (e.detail?.route ? `${e.detail.method} ${e.detail.route}` : "—")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function OrganizationSupportAccessPage() {
  const now = useNow(1000);
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "audit" ? "audit" : "requests";
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [approving, setApproving] = useState(null);
  const [declining, setDeclining] = useState(null);
  const [revoking, setRevoking] = useState(null);

  const load = useCallback(async () => {
    try {
      setData(await svc.list());
      setError(null);
    } catch (err) {
      setError(err.message || "Could not load support access.");
    }
  }, []);

  useEffect(() => {
    // Initial load + 20 s refresh of server state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
    const id = setInterval(load, 20000);
    return () => clearInterval(id);
  }, [load]);

  const done = useCallback((msg) => {
    setNotice(msg);
    load();
  }, [load]);
  const pending = useMemo(() => data?.pending || [], [data]);

  return (
    <div className="space-y-5 p-4 sm:p-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Platform Support Access</h1>
        <p className="text-sm text-foreground-secondary">
          Zoiko staff cannot see your employees, salaries, bank details or payslips unless you approve a temporary,
          read-only session here.
        </p>
      </div>
      <div role="tablist" className="flex gap-2 border-b border-border-light">
        {[["requests", "Requests & sessions"], ["audit", "Audit"]].map(([key, label]) => (
          <button key={key} role="tab" type="button" aria-selected={tab === key}
            onClick={() => setParams((p) => { p.set("tab", key); return p; })}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${tab === key ? "border-blue-600 font-semibold text-foreground" : "border-transparent text-foreground-secondary"}`}>
            {label}{key === "requests" && pending.length ? <span className="ml-1.5 rounded-full bg-blue-600 px-1.5 text-xs text-white">{pending.length}</span> : null}
          </button>
        ))}
      </div>
      {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
      {notice && <p role="status" className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
      {tab === "audit" ? <AuditTab /> : !data ? (
        <p className="text-sm text-foreground-secondary">Loading…</p>
      ) : (
        <>
          <section className="space-y-3">
            <h2 className="text-lg font-semibold text-foreground">Waiting for your approval</h2>
            {pending.length === 0 && <p className="text-sm text-foreground-secondary">No requests are waiting.</p>}
            {pending.map((g) => (
              <div key={g.id} className={`${card} space-y-3`}>
                <dl className="grid gap-3 sm:grid-cols-3">
                  <Detail label="Requested by">Platform support ({g.requesterEmail})</Detail>
                  <Detail label="Ticket">{g.ticketReference}</Detail>
                  <Detail label="Duration">{g.requestedMinutes} minutes</Detail>
                  <Detail label="Reason">{g.reason}</Detail>
                  <Detail label="Scope">{scopeText(g)}</Detail>
                  <Detail label="Lapses in">{formatCountdown(msUntil(g.approvalExpiresAt, now))}</Detail>
                </dl>
                <div className="flex gap-2">
                  <button type="button" className={primary} onClick={() => setApproving(g)}>Approve…</button>
                  <button type="button" className={subtle} onClick={() => setDeclining(g)}>Decline</button>
                </div>
              </div>
            ))}
            {(data.awaitingZoiko || []).map((g) => (
              <div key={g.id} className={`${card} text-sm text-foreground`}>
                #{g.id} approved by you — waiting for Zoiko Platform Security&apos;s independent approval.
              </div>
            ))}
          </section>
          <section className="space-y-3">
            <h2 className="text-lg font-semibold text-foreground">Support has access now</h2>
            {(data.active || []).length === 0 && <p className="text-sm text-foreground-secondary">No active sessions.</p>}
            {(data.active || []).map((g) => (
              <div key={g.id} className={`${card} space-y-3 ${g.isBreakGlass ? "border-red-300" : ""}`}>
                {g.isBreakGlass && (
                  <p className="rounded bg-red-50 p-2 text-sm text-red-800">
                    Emergency access opened by Zoiko Platform Security (incident {g.incidentReference}).
                  </p>
                )}
                <dl className="grid gap-3 sm:grid-cols-3">
                  <Detail label="Reason">{g.reason}</Detail>
                  <Detail label="Ticket">{g.ticketReference}</Detail>
                  <Detail label="Ends">{formatDateTime(g.expiresAt)} ({formatCountdown(msUntil(g.expiresAt, now))})</Detail>
                  <Detail label="Temporary user">{g.supportUsername}</Detail>
                  <Detail label="Scope">{scopeText(g)}</Detail>
                  <Detail label="Fields">{(g.allowedFieldClasses || []).map((c) => FIELD_CLASS_LABELS[c] || c).join(", ")}</Detail>
                </dl>
                <button type="button" className={danger} onClick={() => setRevoking(g)}>Revoke now</button>
              </div>
            ))}
          </section>
          <section className="space-y-2">
            <h2 className="text-lg font-semibold text-foreground">History</h2>
            {(data.history || []).length === 0 ? (
              <p className="text-sm text-foreground-secondary">No earlier requests.</p>
            ) : (
              <ul className={`${card} divide-y divide-border-light text-sm`}>
                {data.history.map((g) => (
                  <li key={g.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                    <span className="text-foreground">#{g.id} · {g.ticketReference} · {g.reason}</span>
                    <span className="flex items-center gap-2">
                      <span className={`rounded-full px-2 py-0.5 text-xs ${STATUS_BADGE[g.status] || ""}`}>{g.status.replace("_", " ")}</span>
                      <span className="text-foreground-secondary">{g.outcome}</span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
      {approving && (
        <ApproveDialog grant={approving} choices={data?.fieldClassChoices || []} defaults={data?.defaultFieldClasses || []}
          onClose={() => setApproving(null)} onDone={done} />
      )}
      {declining && (
        <ReasonDialog title="Decline this request" action="Decline" onClose={() => setDeclining(null)}
          onSubmit={async (reason) => { await svc.deny(declining.id, reason); done("Declined."); }} />
      )}
      {revoking && (
        <ReasonDialog title="Revoke support access now" action="Revoke now" onClose={() => setRevoking(null)}
          onSubmit={async (reason) => { await svc.revoke(revoking.id, reason); done("Access revoked."); }} />
      )}
    </div>
  );
}
