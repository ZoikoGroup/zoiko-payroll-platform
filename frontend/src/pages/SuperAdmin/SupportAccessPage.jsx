import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Copy, Check, Eye, EyeOff, ExternalLink, Loader2, ShieldAlert, RefreshCw } from "lucide-react";
import { getStoredUser } from "../../api/client";
import ConfirmDialog from "../../components/ConfirmDialog";
import Modal from "../../components/Modal";
import { SCOPE_LABELS, supportAccessOperator as svc } from "../../service/supportAccessService";
import { formatCountdown, formatDateTime, msUntil } from "../../utils/time";
import useNow from "../../utils/useNow";

// JIT Support Access - operator / Platform Security page (ZP-PRIV Part D.6).
// Tabs are role-aware; a role never calls an endpoint it cannot use.
const card = "rounded-xl border border-border-light bg-surface p-5 shadow-sm";
const btn = "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium disabled:opacity-50";
const primary = `${btn} bg-blue-600 text-white hover:bg-blue-700`;
const subtle = `${btn} border border-border-light text-foreground hover:bg-surface-muted`;
const danger = `${btn} bg-red-600 text-white hover:bg-red-700`;
const input = "w-full rounded-lg border border-border-light bg-surface px-3 py-2 text-sm text-foreground";

function useIsNarrow() {
  const [narrow, setNarrow] = useState(() => typeof window !== "undefined" && window.innerWidth < 640);
  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < 640);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return narrow;
}

function NarrowNotice() {
  return (
    <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800 dark:bg-amber-900/30 dark:text-amber-200">
      Support access actions are disabled on small screens. Use a wider window to request, end or approve access.
    </p>
  );
}

function Banner({ tone = "info", children }) {
  const tones = {
    info: "bg-blue-50 text-blue-800 dark:bg-blue-900/30 dark:text-blue-200",
    error: "bg-red-50 text-red-800 dark:bg-red-900/30 dark:text-red-200",
    success: "bg-emerald-50 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-200",
  };
  return <div role={tone === "error" ? "alert" : "status"} className={`rounded-lg p-3 text-sm ${tones[tone]}`}>{children}</div>;
}

const STEPS = ["Request", "Organization approves", "Temporary login", "Auto-ends"];

function Tracker({ grant }) {
  let current = 0;
  if (grant?.status === "pending_approval") current = 1;
  if (grant?.status === "active") current = 2;
  return (
    <ol className="flex flex-wrap gap-2 text-xs">
      {STEPS.map((label, i) => (
        <li
          key={label}
          className={`rounded-full px-3 py-1 ${i <= current ? "bg-blue-600 text-white" : "bg-surface-muted text-foreground-secondary"}`}
        >
          {i + 1}. {label}
        </li>
      ))}
    </ol>
  );
}

function TenantPicker({ value, onChange, initialCode }) {
  const [query, setQuery] = useState(initialCode || "");
  const [options, setOptions] = useState([]);
  const [open, setOpen] = useState(false);
  const seq = useRef(0);

  useEffect(() => {
    const mine = ++seq.current;
    const timer = setTimeout(async () => {
      try {
        const rows = await svc.searchTenants(query);
        if (mine !== seq.current) return; // an older, slower response: ignore it
        setOptions(rows);
        if (initialCode && !value) {
          const match = rows.find((r) => r.code === initialCode);
          if (match) onChange(match);
        }
      } catch {
        if (mine === seq.current) setOptions([]);
      }
    }, 250);
    return () => clearTimeout(timer);
  }, [query, initialCode, value, onChange]);

  return (
    <div className="relative">
      <input
        className={input}
        placeholder="Search organizations by name or code"
        value={value ? `${value.name} (${value.code})` : query}
        onChange={(e) => {
          onChange(null);
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        aria-label="Organization"
      />
      {open && !value && options.length > 0 && (
        <ul className="absolute z-10 mt-1 max-h-56 w-full overflow-auto rounded-lg border border-border-light bg-surface shadow">
          {options.map((o) => (
            <li key={o.id}>
              <button
                type="button"
                className="w-full px-3 py-2 text-left text-sm hover:bg-surface-muted"
                onClick={() => {
                  onChange(o);
                  setOpen(false);
                }}
              >
                <span className="font-medium text-foreground">{o.name}</span>{" "}
                <span className="text-foreground-secondary">· {o.code}{o.jurisdiction ? ` · ${o.jurisdiction}` : ""}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const DEFAULT_REASONS = [
  "Payroll calculation discrepancy",
  "Payslip generation or delivery issue",
  "Statutory filing or tax submission issue",
  "Employee data correction requested by the organization",
  "Bank file or salary payment issue",
  "Sign-in or access issue reported by the organization",
  "Data import or integration failure",
  "Investigating a reported defect",
  "Other",
];

function RequestForm({ config, initialCode, onCreated, narrow }) {
  const [tenant, setTenant] = useState(null);
  // Reason: one of the standard reasons, or "Other" with a description.
  const [reasonChoice, setReasonChoice] = useState("");
  const [otherReason, setOtherReason] = useState("");
  const [ticket, setTicket] = useState("");
  const [minutes, setMinutes] = useState(15);
  const [scopeType, setScopeType] = useState("diagnostics");
  const [scopeOptions, setScopeOptions] = useState({ legalEntities: [], payGroups: [] });
  const [entityId, setEntityId] = useState("");
  const [groupId, setGroupId] = useState("");
  const [codes, setCodes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  // The server issues the ticket number; shown read-only and sent back.
  const loadTicket = () => svc.ticketNumber().then((r) => setTicket(r.ticketReference)).catch(() => setTicket(""));
  useEffect(() => { loadTicket(); }, []);

  useEffect(() => {
    if (!tenant) return;
    svc.scopeOptions(tenant.id).then(setScopeOptions).catch(() => setScopeOptions({ legalEntities: [], payGroups: [] }));
  }, [tenant]);

  const reasons = config?.reasons?.length ? config.reasons : DEFAULT_REASONS;
  const isOther = reasonChoice === "Other";
  const reason = isOther ? (otherReason.trim() ? `Other: ${otherReason.trim()}` : "") : reasonChoice;

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const employeeCodes = codes.split(/[\s,;]+/).map((c) => c.trim()).filter(Boolean);
      const grant = await svc.request({
        organizationId: tenant.id,
        reason,
        ticketReference: ticket || undefined, // server generates one if this is empty
        minutes: Number(minutes),
        scopeType,
        scopeEntityId: scopeType === "entity" ? Number(entityId) : undefined,
        scopePayGroupId: scopeType === "pay_group" ? Number(groupId) : undefined,
        employeeCodes: scopeType === "employees" ? employeeCodes : undefined,
      });
      setCodes(""); // codes are never kept or shown back
      loadTicket(); // a new number for the next request
      onCreated(grant);
    } catch (err) {
      setError(err.message || "The request could not be sent.");
    } finally {
      setBusy(false);
    }
  }

  const ready = tenant && reason.trim() &&
    (scopeType !== "entity" || entityId) && (scopeType !== "pay_group" || groupId) &&
    (scopeType !== "employees" || codes.trim());

  return (
    <form onSubmit={submit} className={`${card} space-y-4`}>
      <h3 className="text-base font-semibold text-foreground">Request access</h3>
      {narrow && <NarrowNotice />}
      <label className="block space-y-1 text-sm">
        <span className="text-foreground-secondary">Organization</span>
        <TenantPicker value={tenant} onChange={setTenant} initialCode={initialCode} />
      </label>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="block space-y-1 text-sm">
          <span className="text-foreground-secondary">Ticket number (generated automatically)</span>
          <input className={`${input} font-mono`} value={ticket || "Generating…"} readOnly aria-readonly="true" />
        </div>
        <label className="block space-y-1 text-sm">
          <span className="text-foreground-secondary">Duration</span>
          <select className={input} value={minutes} onChange={(e) => setMinutes(e.target.value)}>
            {(config?.allowedMinutes || [5, 15, 30]).map((m) => (
              <option key={m} value={m}>{m} minutes</option>
            ))}
          </select>
        </label>
      </div>
      <label className="block space-y-1 text-sm">
        <span className="text-foreground-secondary">Reason (required, shown to the organization)</span>
        <select className={input} value={reasonChoice} onChange={(e) => setReasonChoice(e.target.value)}>
          <option value="">Select a reason…</option>
          {reasons.map((r) => (
            <option key={r} value={r}>{r === "Other" ? "Other (describe)" : r}</option>
          ))}
        </select>
      </label>
      {isOther && (
        <label className="block space-y-1 text-sm">
          <span className="text-foreground-secondary">Describe the reason</span>
          <textarea className={input} rows={2} maxLength={400} value={otherReason}
            onChange={(e) => setOtherReason(e.target.value)} />
        </label>
      )}
      <fieldset className="space-y-2 text-sm">
        <legend className="text-foreground-secondary">Scope</legend>
        {["diagnostics", "entity", "pay_group", "employees"].map((s) => (
          <label key={s} className="flex items-center gap-2 text-foreground">
            <input type="radio" name="scope" checked={scopeType === s} onChange={() => setScopeType(s)} />
            {SCOPE_LABELS[s]}
          </label>
        ))}
        {scopeType === "entity" && (
          <select className={input} value={entityId} onChange={(e) => setEntityId(e.target.value)} aria-label="Legal entity">
            <option value="">Choose a legal entity</option>
            {scopeOptions.legalEntities.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
          </select>
        )}
        {scopeType === "pay_group" && (
          <select className={input} value={groupId} onChange={(e) => setGroupId(e.target.value)} aria-label="Pay group">
            <option value="">Choose a pay group</option>
            {scopeOptions.payGroups.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
          </select>
        )}
        {scopeType === "employees" && (
          <textarea
            className={input}
            rows={2}
            value={codes}
            onChange={(e) => setCodes(e.target.value)}
            placeholder={`Employee codes from the ticket, up to ${config?.maxEmployees || 10}, separated by commas`}
            aria-label="Employee codes"
          />
        )}
        {scopeType !== "diagnostics" && (
          <p className="text-xs text-foreground-secondary">
            Worker-level scope also needs an independent Platform Security approval.
          </p>
        )}
      </fieldset>
      {error && <Banner tone="error">{error}</Banner>}
      <button type="submit" className={primary} disabled={!ready || busy || narrow}>
        {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />} Send request
      </button>
    </form>
  );
}

function CredentialsPanel({ grantId }) {
  const [creds, setCreds] = useState(null);
  const [error, setError] = useState(null);
  const [reveal, setReveal] = useState(false);
  const [copied, setCopied] = useState("");

  async function load() {
    setError(null);
    try {
      setCreds(await svc.credentials(grantId));
    } catch (err) {
      setError(err.message || "The temporary login is not available.");
    }
  }

  async function copy(label, value) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(label);
      setTimeout(() => setCopied(""), 1500);
    } catch {
      setCopied("");
    }
  }

  if (!creds) {
    return (
      <div className="space-y-2">
        <button type="button" className={primary} onClick={load}>Show temporary login</button>
        <p className="text-xs text-foreground-secondary">Every view of the login is recorded in the audit trail.</p>
        {error && <Banner tone="error">{error}</Banner>}
      </div>
    );
  }
  return (
    <div className="space-y-3 rounded-lg bg-surface-muted p-4 text-sm">
      {[["User ID", creds.username, true], ["Password", creds.password, reveal]].map(([label, value, shown]) => (
        <div key={label} className="flex flex-wrap items-center gap-2">
          <span className="w-20 text-foreground-secondary">{label}</span>
          <code className="rounded bg-surface px-2 py-1 font-mono text-foreground">{shown ? value : "•".repeat(16)}</code>
          {label === "Password" && (
            <button type="button" className={subtle} onClick={() => setReveal((v) => !v)} aria-label={reveal ? "Hide password" : "Reveal password"}>
              {reveal ? <EyeOff className="h-4 w-4" aria-hidden="true" /> : <Eye className="h-4 w-4" aria-hidden="true" />}
            </button>
          )}
          <button type="button" className={subtle} onClick={() => copy(label, value)} aria-label={`Copy ${label}`}>
            {copied === label ? <Check className="h-4 w-4" aria-hidden="true" /> : <Copy className="h-4 w-4" aria-hidden="true" />}
          </button>
        </div>
      ))}
      <a href="/login" target="_blank" rel="noreferrer" className={`${subtle} w-fit`}>
        Open login page <ExternalLink className="h-4 w-4" aria-hidden="true" />
      </a>
      <p className="text-xs text-foreground-secondary">
        Sign in from a private (incognito) window so your admin session stays separate. The login is read-only and
        stops working when the session ends.
      </p>
    </div>
  );
}

function MyAccess({ config, role, initialCode, narrow, onCounts }) {
  const now = useNow(1000);
  const [active, setActive] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [confirm, setConfirm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [breakGlass, setBreakGlass] = useState(false);
  const lastStatus = useRef(null);

  const refresh = useCallback(async () => {
    try {
      const [a, mine] = await Promise.all([svc.active(), svc.mine()]);
      const grant = a.grant;
      if (lastStatus.current === "pending_approval" && grant?.status === "active") {
        setNotice("Approved — your temporary login is ready.");
      }
      lastStatus.current = grant?.status || null;
      setActive(grant);
      setHistory(mine.filter((g) => !["pending_approval", "active"].includes(g.status)));
      onCounts?.(grant ? 1 : 0);
      setError(null);
    } catch (err) {
      setError(err.message || "Could not load your support access.");
    } finally {
      setLoading(false);
    }
  }, [onCounts]);

  useEffect(() => {
    // Initial load + polling of server state (an external system).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refresh();
    const id = setInterval(refresh, 10000);
    return () => clearInterval(id);
  }, [refresh]);

  async function act(fn) {
    setBusy(true);
    try {
      await fn();
      setConfirm(null);
      await refresh();
    } catch (err) {
      setError(err.message || "The action failed.");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <p className="text-sm text-foreground-secondary">Loading…</p>;
  const pendingMs = msUntil(active?.approvalExpiresAt, now);
  const activeMs = msUntil(active?.expiresAt, now);

  return (
    <div className="space-y-5">
      {error && <Banner tone="error">{error}</Banner>}
      {notice && <Banner tone="success">{notice}</Banner>}
      {active ? (
        <div className={`${card} space-y-4`}>
          <Tracker grant={active} />
          {active.status === "pending_approval" ? (
            <>
              <h3 className="text-base font-semibold text-foreground">Waiting for {active.organizationName} to approve</h3>
              <dl className="grid gap-2 text-sm sm:grid-cols-2">
                <div><dt className="text-foreground-secondary">Ticket</dt><dd className="text-foreground">{active.ticketReference}</dd></div>
                <div><dt className="text-foreground-secondary">Duration</dt><dd className="text-foreground">{active.requestedMinutes} minutes</dd></div>
                <div><dt className="text-foreground-secondary">Scope</dt><dd className="text-foreground">{active.scopeLabel}</dd></div>
                <div><dt className="text-foreground-secondary">Status</dt><dd className="text-foreground">{active.outcome}</dd></div>
                <div className="sm:col-span-2"><dt className="text-foreground-secondary">Reason</dt><dd className="text-foreground">{active.reason}</dd></div>
              </dl>
              <p className="text-sm text-foreground">Request expires in <strong>{formatCountdown(pendingMs)}</strong></p>
              <div className="flex flex-wrap gap-2">
                <button type="button" className={subtle} onClick={refresh}><RefreshCw className="h-4 w-4" aria-hidden="true" /> Check now</button>
                <button type="button" className={subtle} disabled={narrow} onClick={() => setConfirm("cancel")}>Cancel request</button>
              </div>
            </>
          ) : (
            <>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-base font-semibold text-foreground">
                  Access to {active.organizationName}
                  {active.isBreakGlass && (
                    <span className="ml-2 rounded-full bg-red-600 px-2 py-0.5 text-xs text-white">Emergency</span>
                  )}
                </h3>
                <span className="text-lg font-semibold tabular-nums text-foreground">{formatCountdown(activeMs)}</span>
              </div>
              <p className="text-sm text-foreground-secondary">
                {active.scopeLabel}. Fields: {(active.allowedFieldClasses || []).join(", ")}. Ends {formatDateTime(active.expiresAt)}.
              </p>
              <p className="text-sm text-foreground-secondary">
                Ticket <span className="font-mono text-foreground">{active.ticketReference}</span> · {active.reason}
              </p>
              <CredentialsPanel grantId={active.id} />
              <button type="button" className={danger} disabled={narrow} onClick={() => setConfirm("exit")}>End session</button>
            </>
          )}
        </div>
      ) : (
        <>
          <div className={`${card} space-y-2 text-sm text-foreground`}>
            <h3 className="text-base font-semibold">How Support Access works</h3>
            <p>Zoiko staff have no standing access to employees, salaries, bank details, tax IDs or payslips.</p>
            <ol className="list-decimal space-y-1 pl-5 text-foreground-secondary">
              <li>Request time-limited, read-only access with a reason and ticket.</li>
              <li>The organization&apos;s administrator approves (and Platform Security for employee data).</li>
              <li>A temporary login appears here; it ends by itself after at most 30 minutes.</li>
            </ol>
          </div>
          <RequestForm config={config} initialCode={initialCode} narrow={narrow} onCreated={() => refresh()} />
          {role === "platform_security" && (
            <button type="button" className={danger} disabled={narrow} onClick={() => setBreakGlass(true)}>
              <ShieldAlert className="h-4 w-4" aria-hidden="true" /> Emergency access
            </button>
          )}
        </>
      )}
      <div className={card}>
        <h3 className="mb-3 text-base font-semibold text-foreground">History</h3>
        {history.length === 0 ? (
          <p className="text-sm text-foreground-secondary">No earlier requests.</p>
        ) : (
          <ul className="divide-y divide-border-light text-sm">
            {history.map((g) => (
              <li key={g.id} className="flex flex-wrap justify-between gap-2 py-2">
                <span className="text-foreground">#{g.id} · {g.organizationName} · {g.ticketReference}</span>
                <span className="text-foreground-secondary">{g.outcome} · {formatDateTime(g.requestedAt)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      {confirm && (
        <ConfirmDialog
          title={confirm === "exit" ? "End this session?" : "Cancel this request?"}
          message={confirm === "exit" ? "The temporary login stops working immediately." : "The organization will no longer see it."}
          confirmLabel={confirm === "exit" ? "End session" : "Cancel request"}
          busy={busy}
          onClose={() => setConfirm(null)}
          onConfirm={() => act(() => (confirm === "exit" ? svc.exit(active.id) : svc.cancel(active.id)))}
        />
      )}
      {breakGlass && <BreakGlassModal onClose={() => setBreakGlass(false)} onOpened={refresh} />}
    </div>
  );
}

function BreakGlassModal({ onClose, onOpened }) {
  const [tenant, setTenant] = useState(null);
  const [incident, setIncident] = useState("");
  const [reason, setReason] = useState("");
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await svc.breakGlass({ organizationId: tenant.id, incidentReference: incident, reason, acknowledged: ack });
      onOpened();
      onClose();
    } catch (err) {
      setError(err.message || "Emergency access could not be opened.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Emergency (break-glass) access" onClose={onClose}>
      <form onSubmit={submit} className="space-y-3 text-sm">
        <Banner tone="error">
          30 minutes, tenant-wide, read-only, names and contact details only, no exports. The organization is told
          immediately and a different Platform Security officer must review it within 24 hours.
        </Banner>
        <TenantPicker value={tenant} onChange={setTenant} />
        <input className={input} placeholder="Incident reference" value={incident} onChange={(e) => setIncident(e.target.value)} />
        <textarea className={input} rows={2} placeholder="Reason" value={reason} onChange={(e) => setReason(e.target.value)} />
        
        <label className="flex items-center gap-2 text-foreground">
          <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
          I understand this will be reviewed.
        </label>
        {error && <Banner tone="error">{error}</Banner>}
        <div className="flex justify-end gap-2">
          <button type="button" className={subtle} onClick={onClose}>Cancel</button>
          <button type="submit" className={danger} disabled={busy || !tenant || !incident || !reason || !ack}>
            Open emergency access
          </button>
        </div>
      </form>
    </Modal>
  );
}

function GrantTable({ rows, now, actions }) {
  if (!rows.length) return <p className="text-sm text-foreground-secondary">Nothing here right now.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-foreground-secondary">
          <tr>
            <th className="py-2 pr-3">Organization</th><th className="pr-3">Requested by</th><th className="pr-3">Scope</th>
            <th className="pr-3">Ticket / reason</th><th className="pr-3">Status</th><th className="pr-3">Time left</th><th />
          </tr>
        </thead>
        <tbody className="divide-y divide-border-light text-foreground">
          {rows.map((g) => (
            <tr key={g.id}>
              <td className="py-2 pr-3">{g.organizationName}</td>
              <td className="pr-3">{g.requesterEmail}</td>
              <td className="pr-3">{g.scopeLabel}{g.employeeCount ? ` (${g.employeeCount})` : ""}</td>
              <td className="pr-3">{g.ticketReference} — {g.reason}</td>
              <td className="pr-3">{g.outcome}</td>
              <td className="pr-3 tabular-nums">
                {formatCountdown(msUntil(g.status === "active" ? g.expiresAt : g.approvalExpiresAt, now))}
              </td>
              <td className="py-2">{actions(g)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SecurityQueues({ kind, narrow, onCounts }) {
  const now = useNow(1000);
  const me = getStoredUser();
  const [rows, setRows] = useState([]);
  const [error, setError] = useState(null);
  const [revoke, setRevoke] = useState(null);
  const [reason, setReason] = useState("");
  const [review, setReview] = useState(null);

  const load = useCallback(async () => {
    try {
      const data = kind === "approvals" ? await svc.approvals() : kind === "live" ? await svc.live() : await svc.pendingReview();
      setRows(data);
      onCounts?.(data.length);
      setError(null);
    } catch (err) {
      setError(err.message || "Could not load.");
    }
  }, [kind, onCounts]);

  useEffect(() => {
    // Initial load + polling of server state (an external system).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, [load]);

  async function run(fn) {
    try {
      await fn();
      await load();
    } catch (err) {
      setError(err.message || "The action failed.");
    }
  }

  return (
    <div className={`${card} space-y-3`}>
      {error && <Banner tone="error">{error}</Banner>}
      {narrow && <NarrowNotice />}
      {kind === "reviews" ? (
        rows.length === 0 ? (
          <p className="text-sm text-foreground-secondary">No break-glass access is waiting for review.</p>
        ) : (
          <ul className="divide-y divide-border-light text-sm">
            {rows.map((g) => (
              <li key={g.id} className={`flex flex-wrap items-center justify-between gap-2 py-3 ${g.reviewOverdue ? "rounded bg-red-50 px-2 dark:bg-red-900/30" : ""}`}>
                <span className="text-foreground">
                  #{g.id} · {g.organizationName} · {g.incidentReference} · opened by {g.requesterEmail}
                  {g.reviewOverdue && <strong className="ml-2 text-red-700">Overdue</strong>}
                </span>
                <span className="text-foreground-secondary">Due {formatDateTime(g.reviewDueAt)}</span>
                <button
                  type="button"
                  className={primary}
                  disabled={narrow || g.requesterEmail === me?.email}
                  title={g.requesterEmail === me?.email ? "A different officer must review" : undefined}
                  onClick={() => setReview(g)}
                >
                  Review
                </button>
              </li>
            ))}
          </ul>
        )
      ) : (
        <GrantTable
          rows={rows}
          now={now}
          actions={(g) =>
            kind === "approvals" ? (
              <button
                type="button"
                className={primary}
                disabled={narrow || g.requesterEmail === me?.email}
                title={g.requesterEmail === me?.email ? "You cannot approve your own request" : undefined}
                onClick={() => run(() => svc.zoikoApprove(g.id))}
              >
                Approve
              </button>
            ) : (
              <button type="button" className={danger} disabled={narrow} onClick={() => setRevoke(g)}>Revoke</button>
            )
          }
        />
      )}
      {revoke && (
        <Modal title={`Revoke access #${revoke.id}`} onClose={() => setRevoke(null)}>
          <textarea className={input} rows={3} placeholder="Reason (required)" value={reason} onChange={(e) => setReason(e.target.value)} />
          <div className="mt-3 flex justify-end gap-2">
            <button type="button" className={subtle} onClick={() => setRevoke(null)}>Cancel</button>
            <button
              type="button"
              className={danger}
              disabled={!reason.trim()}
              onClick={() => run(async () => {
                await svc.revoke(revoke.id, reason);
                setRevoke(null);
                setReason("");
              })}
            >
              Revoke now
            </button>
          </div>
        </Modal>
      )}
      {review && <ReviewModal grant={review} onClose={() => setReview(null)} onDone={load} />}
    </div>
  );
}

function ReviewModal({ grant, onClose, onDone }) {
  const [outcome, setOutcome] = useState(null);
  const [findings, setFindings] = useState("");
  const [error, setError] = useState(null);

  async function submit() {
    try {
      await svc.review(grant.id, outcome, findings);
      onDone();
      onClose();
    } catch (err) {
      setError(err.message || "The review could not be saved.");
    }
  }

  return (
    <Modal title={`Post-incident review #${grant.id}`} onClose={onClose}>
      <div className="space-y-3 text-sm">
        <p className="text-foreground-secondary">{grant.organizationName} · {grant.incidentReference} · {grant.reason}</p>
        <div className="grid gap-2 sm:grid-cols-2">
          {[["justified", "Justified", "The emergency access was necessary and proportionate."],
            ["not_justified", "Not justified", "The access was not warranted; follow up with the officer."]].map(([key, label, help]) => (
            <button
              key={key}
              type="button"
              onClick={() => setOutcome(key)}
              className={`rounded-lg border p-3 text-left ${outcome === key ? "border-blue-600 ring-2 ring-blue-600" : "border-border-light"}`}
            >
              <span className="block font-semibold text-foreground">{label}</span>
              <span className="text-xs text-foreground-secondary">{help}</span>
            </button>
          ))}
        </div>
        <textarea className={input} rows={3} placeholder="Findings (required)" value={findings} onChange={(e) => setFindings(e.target.value)} />
        {error && <Banner tone="error">{error}</Banner>}
        <div className="flex justify-end gap-2">
          <button type="button" className={subtle} onClick={onClose}>Cancel</button>
          <button type="button" className={primary} disabled={!outcome || !findings.trim()} onClick={submit}>Close review</button>
        </div>
      </div>
    </Modal>
  );
}

export default function SupportAccessPage() {
  const [params, setParams] = useSearchParams();
  const role = getStoredUser()?.role;
  const narrow = useIsNarrow();
  const [config, setConfig] = useState(null);
  const [counts, setCounts] = useState({});
  const isSecurity = role === "platform_security";

  const tabs = useMemo(() => {
    const t = [{ key: "mine", label: "My Access" }];
    if (isSecurity) {
      t.push({ key: "approvals", label: "Approvals" }, { key: "live", label: "Live Sessions" },
        { key: "reviews", label: "Break-Glass Reviews" });
    }
    return t;
  }, [isSecurity]);
  const tab = tabs.some((t) => t.key === params.get("tab")) ? params.get("tab") : "mine";

  useEffect(() => {
    svc.config().then(setConfig).catch(() => setConfig(null));
  }, []);

  const setCount = useCallback((key) => (n) => setCounts((c) => (c[key] === n ? c : { ...c, [key]: n })), []);
  const countSetters = useMemo(
    () => ({ mine: setCount("mine"), approvals: setCount("approvals"), live: setCount("live"), reviews: setCount("reviews") }),
    [setCount],
  );

  if (!["super_admin", "support_operator", "platform_security"].includes(role)) {
    return <p className="p-6 text-sm text-foreground-secondary">Support Access is available to Zoiko platform staff only.</p>;
  }

  return (
    <div className="space-y-5 p-4 sm:p-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Support Access</h1>
        <p className="text-sm text-foreground-secondary">
          Time-limited, read-only, tenant-approved access to worker data. Nothing is visible without it.
        </p>
      </div>
      <div role="tablist" className="flex flex-wrap gap-2 border-b border-border-light">
        {tabs.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            type="button"
            onClick={() => setParams((p) => { p.set("tab", t.key); return p; })}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${tab === t.key ? "border-blue-600 font-semibold text-foreground" : "border-transparent text-foreground-secondary"}`}
          >
            {t.label}
            {counts[t.key] ? <span className="ml-1.5 rounded-full bg-blue-600 px-1.5 text-xs text-white">{counts[t.key]}</span> : null}
          </button>
        ))}
      </div>
      {tab === "mine" && (
        <MyAccess config={config} role={role} narrow={narrow} initialCode={params.get("organization") || ""} onCounts={countSetters.mine} />
      )}
      {tab !== "mine" && isSecurity && <SecurityQueues key={tab} kind={tab} narrow={narrow} onCounts={countSetters[tab]} />}
    </div>
  );
}
