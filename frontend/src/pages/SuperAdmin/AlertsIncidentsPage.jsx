import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  Bell,
  RefreshCcw,
  PlayCircle,
  FileText,
  Activity,
  CreditCard,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import StatusPill from "../../components/StatusPill";
import { useToast } from "../../context/ToastContext";
import { listAlerts } from "../../service/commandCenterService";
import { getStoredUser } from "../../api/client";
import { Badge, Banner, NotAvailable, Tabs, actionError, card, input, subtle } from "../../components/SecurityUi";
import { isUnavailable, securityPlatform as securitySvc } from "../../service/securityService";
import { formatDateTime } from "../../utils/time";

// Same token vocabulary as StatusPill usage elsewhere in the Command
// Center — high = rejected (red), medium = pending (amber), low = inactive
// (muted). Groups are rendered in this order (high first); anything a
// backend ever emits outside these three maps defensively to the muted
// state rather than crashing the page.
const SEVERITY_LABEL = {
  high: "High",
  medium: "Medium",
  low: "Low",
};
const SEVERITY_PILL = {
  high: "rejected",
  medium: "pending",
  low: "inactive",
};

const CATEGORY_META = {
  payroll_run: { label: "Payroll Runs", icon: PlayCircle },
  filing: { label: "Filings", icon: FileText },
  platform: { label: "Platform", icon: Activity },
  billing: { label: "Billing", icon: CreditCard },
  security: { label: "Security", icon: ShieldAlert }, // break-glass reviews, assisted-access audit gaps
};

function AlertRow({ alert }) {
  const meta = CATEGORY_META[alert.category] || { label: alert.category, icon: Activity };
  const Icon = meta.icon;
  const protectedRun = alert.category === "billing" && alert.message.includes("(protected)");
  return (
    <div className="flex items-center gap-3 border-t border-border-light px-4 py-3">
      <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${protectedRun ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-400" : "bg-surface-muted text-foreground-muted"}`}>
        <Icon size={15} />
      </span>
      <div className="min-w-0 flex-1">
        <p className={`break-words text-sm font-medium ${protectedRun ? "text-emerald-700 dark:text-emerald-400" : "text-foreground"}`}>{alert.message}</p>
        <p className="text-xs text-foreground-muted">{meta.label}</p>
      </div>
      <div className="shrink-0">
        <StatusPill status={SEVERITY_PILL[alert.severity] || "inactive"} label={SEVERITY_LABEL[alert.severity] || alert.severity} />
      </div>
      <Link
        to={alert.link}
        className="shrink-0 rounded-lg border border-border px-3 py-1.5 text-xs font-semibold text-foreground-secondary transition hover:bg-surface-muted"
      >
        Open →
      </Link>
    </div>
  );
}

function IncidentsFeed() {
  const { addToast } = useToast() || {};
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listAlerts();
      setData(res);
    } catch (err) {
      addToast?.(err.message, "error");
    } finally {
      setLoading(false);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { load(); }, [load]);

  const alerts = data?.alerts || [];
  const bySeverity = alerts.reduce((acc, alert) => {
    (acc[alert.severity] = acc[alert.severity] || []).push(alert);
    return acc;
  }, {});
  const groups = ["high", "medium", "low"].filter((s) => (bySeverity[s] || []).length > 0);

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <Bell size={22} className="text-primary" /> Alerts &amp; Incidents
          </h1>
          <p className="text-sm text-foreground-muted mt-0.5">
            Unified triage across Payroll Runs, Filings, Security, Platform, and Billing — one feed over signals each
            page already computes. Every alert links back to its source page; this never replaces them.
            Payroll-run and filing alerts are counts across organizations, never a named tenant&apos;s run or filing.
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5 disabled:opacity-50"
        >
          <RefreshCcw size={15} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>

      <div className="flex flex-wrap gap-4 mb-6">
        <div className="flex items-center gap-3 rounded-xl border border-border bg-surface p-4 shadow-sm min-w-[180px]">
          <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-error/10 text-error">
            <ShieldAlert size={20} />
          </span>
          <div>
            <p className="text-2xl font-bold text-foreground leading-none">{data?.high_severity_count ?? "—"}</p>
            <p className="mt-1 text-xs text-foreground-muted">High-severity open</p>
          </div>
        </div>
        <div className="flex items-center gap-3 rounded-xl border border-border bg-surface p-4 shadow-sm min-w-[180px]">
          <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-400">
            <ShieldCheck size={20} />
          </span>
          <div>
            <p className="text-2xl font-bold text-foreground leading-none">{data?.total ?? "—"}</p>
            <p className="mt-1 text-xs text-foreground-muted">Total alerts across all severities</p>
          </div>
        </div>
      </div>

      {!loading && groups.length === 0 && (
        <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-border bg-surface px-4 py-16 text-center shadow-sm">
          <ShieldCheck size={32} className="text-border-strong" />
          <p className="text-sm font-medium text-foreground">No alerts right now.</p>
          <p className="text-xs text-foreground-disabled">
            Nothing is at risk in Payroll Runs, Filings, Security, Platform, or Billing. The count in the sidebar updates automatically.
          </p>
        </div>
      )}

      {groups.map((severity) => (
        <div key={severity} className="bg-surface rounded-xl shadow-sm border border-border overflow-hidden overflow-x-auto mb-4">
          <div className="px-4 py-3 border-b border-border-light flex items-center justify-between">
            <h2 className="text-sm font-semibold text-foreground-secondary">
              {SEVERITY_LABEL[severity]} severity
              <span className="ml-2 text-xs font-normal text-foreground-muted">({bySeverity[severity].length} open)</span>
            </h2>
            <StatusPill status={SEVERITY_PILL[severity] || "inactive"} label={SEVERITY_LABEL[severity] || severity} />
          </div>
          {bySeverity[severity].map((alert, idx) => (
            <AlertRow key={`${severity}-${idx}`} alert={alert} />
          ))}
        </div>
      ))}
      {!loading && groups.length > 0 && (
        <p className="text-xs text-foreground-muted">
          Alerts are derived from each source page&apos;s own query logic — resolving one here is the same as resolving it
          on its source page.
        </p>
      )}
    </div>
  );
}

// ── Security alerts and rules (ZP-PRIV E03) ────────────────────────────────
// Readable by super_admin and platform_security; only platform_security may
// test-fire a rule (a drill). Acknowledging is open to both readers.
const SECURITY_READERS = ["super_admin", "platform_security"];
const ALERT_SEVERITY_BADGE = {
  critical: "bg-red-100 text-red-800",
  high: "bg-red-100 text-red-800",
  medium: "bg-amber-100 text-amber-800",
  low: "bg-slate-200 text-slate-700",
};
const ALERT_STATUS_BADGE = {
  open: "bg-blue-100 text-blue-800",
  acknowledged: "bg-slate-200 text-slate-700",
  resolved: "bg-emerald-100 text-emerald-800",
};

function SecurityAlerts() {
  const [status, setStatus] = useState("open");
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [unavailable, setUnavailable] = useState(false);
  const [busy, setBusy] = useState(null);

  const load = useCallback(async () => {
    try {
      setRows(await securitySvc.alertEvents(status));
      setError(null);
    } catch (err) {
      if (isUnavailable(err)) setUnavailable(true);
      else setError(err.message || "Could not load security alerts.");
    }
  }, [status]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  async function acknowledge(id) {
    setBusy(id);
    try {
      await securitySvc.acknowledgeAlert(id);
      await load();
    } catch (err) {
      setError(actionError(err, "The alert could not be acknowledged."));
    } finally {
      setBusy(null);
    }
  }

  if (unavailable) return <NotAvailable what="Security alerts" />;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <select className={`${input} max-w-[12rem]`} value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Alert status">
          <option value="open">Open</option>
          <option value="acknowledged">Acknowledged</option>
          <option value="resolved">Resolved</option>
          <option value="">All</option>
        </select>
        <button type="button" className={subtle} onClick={load}><RefreshCcw size={14} aria-hidden="true" /> Refresh</button>
      </div>
      {error && <Banner tone="error">{error}</Banner>}
      <div className={`${card} overflow-x-auto`}>
        {!rows ? <p className="text-sm text-foreground-secondary">Loading…</p> : rows.length === 0 ? (
          <p className="text-sm text-foreground-secondary">No security alerts with this status.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="text-foreground-secondary">
              <tr><th className="py-2 pr-3">Alert</th><th className="pr-3">Severity</th><th className="pr-3">Status</th>
                <th className="pr-3">Org</th><th className="pr-3">Count</th><th className="pr-3">First / last seen</th>
                <th className="pr-3">Delivery</th><th><span className="sr-only">Actions</span></th></tr>
            </thead>
            <tbody className="divide-y divide-border-light text-foreground">
              {rows.map((a) => (
                <tr key={a.id}>
                  <td className="py-2 pr-3">
                    <p className="font-medium">{a.ruleKey}{a.isDrill ? <span className="ml-1.5 text-xs text-foreground-secondary">(drill)</span> : null}</p>
                    <p className="text-xs text-foreground-secondary">{a.summary}</p>
                  </td>
                  <td className="pr-3"><Badge className={ALERT_SEVERITY_BADGE[a.severity] || "bg-slate-200 text-slate-700"}>{a.severity}</Badge></td>
                  <td className="pr-3">
                    <Badge className={ALERT_STATUS_BADGE[a.status] || ""}>{a.status}</Badge>
                    {a.acknowledgedAt && (
                      <p className="text-xs text-foreground-secondary">by #{a.acknowledgedBy} · {formatDateTime(a.acknowledgedAt)}</p>
                    )}
                  </td>
                  <td className="pr-3">{a.organizationId ?? "—"}</td>
                  <td className="pr-3">{a.count}</td>
                  <td className="pr-3 whitespace-nowrap text-xs">{formatDateTime(a.firstSeen)}<br />{formatDateTime(a.lastSeen)}</td>
                  <td className="pr-3 font-mono text-xs">{a.deliveryReceipt || "—"}</td>
                  <td>
                    {a.status === "open" && (
                      <button type="button" className={subtle} disabled={busy === a.id} onClick={() => acknowledge(a.id)}>Acknowledge</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function AlertRules({ isSecurity }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [unavailable, setUnavailable] = useState(false);
  const [busy, setBusy] = useState(null);
  const [receipt, setReceipt] = useState(null);

  useEffect(() => {
    securitySvc.alertRules().then(setRows).catch((err) => {
      if (isUnavailable(err)) setUnavailable(true);
      else setError(err.message || "Could not load alert rules.");
    });
  }, []);

  async function testFire(key) {
    setBusy(key);
    setReceipt(null);
    setError(null);
    try {
      const res = await securitySvc.testFire(key);
      setReceipt({ key: res.ruleKey || key, deliveryReceipt: res.deliveryReceipt, id: res.id });
    } catch (err) {
      setError(actionError(err, "The drill could not be fired."));
    } finally {
      setBusy(null);
    }
  }

  if (unavailable) return <NotAvailable what="Alert rules" />;
  return (
    <div className="space-y-3">
      {error && <Banner tone="error">{error}</Banner>}
      {receipt && (
        <Banner tone="success">
          Drill alert #{receipt.id} fired for <strong>{receipt.key}</strong>. Delivery receipt:{" "}
          <code className="break-all">{receipt.deliveryReceipt || "none"}</code>
        </Banner>
      )}
      <div className={`${card} overflow-x-auto`}>
        {!rows ? <p className="text-sm text-foreground-secondary">Loading…</p> : (
          <table className="w-full text-left text-sm">
            <thead className="text-foreground-secondary">
              <tr><th className="py-2 pr-3">Rule</th><th className="pr-3">Threshold</th><th className="pr-3">Severity</th>
                <th className="pr-3">Channel</th><th className="pr-3">Enabled</th>
                {isSecurity && <th><span className="sr-only">Actions</span></th>}</tr>
            </thead>
            <tbody className="divide-y divide-border-light text-foreground">
              {rows.map((r) => (
                <tr key={r.key}>
                  <td className="py-2 pr-3">
                    <p className="font-mono text-xs">{r.key}</p>
                    <p className="text-xs text-foreground-secondary">{r.description}</p>
                  </td>
                  <td className="pr-3 whitespace-nowrap">{r.threshold} in {r.windowSeconds}s</td>
                  <td className="pr-3"><Badge className={ALERT_SEVERITY_BADGE[r.severity] || "bg-slate-200 text-slate-700"}>{r.severity}</Badge></td>
                  <td className="pr-3">{r.channel}</td>
                  <td className="pr-3">{r.enabled ? "Yes" : "No"}</td>
                  {isSecurity && (
                    <td>
                      <button type="button" className={subtle} disabled={busy === r.key} onClick={() => testFire(r.key)}>Test fire</button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

export default function AlertsIncidentsPage() {
  const role = getStoredUser()?.role;
  const isSuperAdmin = role === "super_admin";
  const isSecurity = role === "platform_security";
  const [params, setParams] = useSearchParams();
  const tabs = [
    // The cross-module incident feed is a Super Admin surface only.
    ...(isSuperAdmin ? [{ key: "incidents", label: "Incidents" }] : []),
    ...(SECURITY_READERS.includes(role)
      ? [{ key: "security", label: "Security alerts" }, { key: "rules", label: "Alert rules" }]
      : []),
  ];
  if (tabs.length === 0) return <NotAvailable what="Alerts" />;
  const tab = tabs.some((t) => t.key === params.get("tab")) ? params.get("tab") : tabs[0].key;

  return (
    <div className="space-y-5">
      {!isSuperAdmin && (
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <Bell size={22} className="text-primary" /> Security Alerts
          </h1>
          <p className="text-sm text-foreground-muted mt-0.5">Deduplicated security alerts and the rules that raise them.</p>
        </div>
      )}
      <Tabs tabs={tabs} value={tab} onChange={(key) => setParams((p) => { p.set("tab", key); return p; })} />
      {tab === "incidents" && isSuperAdmin && <IncidentsFeed />}
      {tab === "security" && <SecurityAlerts />}
      {tab === "rules" && <AlertRules isSecurity={isSecurity} />}
    </div>
  );
}