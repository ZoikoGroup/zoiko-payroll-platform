import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { PlayCircle, RefreshCcw, AlertTriangle, ShieldCheck, Building2, ChevronDown, ChevronUp } from "lucide-react";
import StatusPill from "../../components/StatusPill";
import { useToast } from "../../context/ToastContext";
import { listAllPayrollRuns } from "../../service/commandCenterService";
import { listAllOrganizationsBrief } from "../../service/superAdminService";

const STATUS_PILL_MAP = { Paid: "active", Closed: "active", Approved: "approved", Authorized: "approved", Review: "pending", Draft: "inactive" };

const SECTION_LABEL_CLS = "text-xs font-semibold uppercase tracking-wider text-foreground-muted";

function RunsTable({ rows, emptyLabel }) {
  return (
    <div className="bg-surface rounded-xl shadow-sm border border-border overflow-hidden overflow-x-auto">
      <table className="w-full text-sm min-w-[900px]">
        <thead className="bg-background text-left text-xs text-foreground-muted">
          <tr>
            <th className="px-4 py-3">Organization</th>
            <th className="px-4 py-3">Run</th>
            <th className="px-4 py-3">Period</th>
            <th className="px-4 py-3">Pay Date</th>
            <th className="px-4 py-3">Status</th>
            <th className="px-4 py-3 text-right">Employees</th>
            <th className="px-4 py-3 text-right">Net</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.run_id} className="border-t border-border-light">
              <td className="px-4 py-3 font-medium text-foreground">{row.organization_name}</td>
              <td className="px-4 py-3 text-foreground-muted">{row.run_code || `#${row.run_id}`}</td>
              <td className="px-4 py-3 text-foreground-secondary">{row.period_label}</td>
              <td className="px-4 py-3 text-foreground-muted">{row.pay_date}</td>
              <td className="px-4 py-3"><StatusPill status={STATUS_PILL_MAP[row.status] || "pending"} label={row.status} /></td>
              <td className="px-4 py-3 text-right text-foreground-muted">{row.employee_count}</td>
              <td className="px-4 py-3 text-right font-medium text-foreground">{row.total_net ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && (
        <div className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-center">
          <p className="text-sm text-foreground-disabled">{emptyLabel}</p>
        </div>
      )}
    </div>
  );
}

// At-Risk gets a structurally distinct shell, not just first position: an
// amber-tinted escalation card when something needs attention, or a calm,
// unmistakably reassuring panel when nothing does — "0 at risk" is the good
// outcome here and should read as one, not as a blank table shell.
function AtRiskSection({ rows, windowDays }) {
  const count = rows.length;
  if (count === 0) {
    return (
      <div className="mb-6 flex flex-col items-center justify-center gap-2 rounded-xl border border-border bg-surface px-4 py-10 text-center shadow-sm">
        <ShieldCheck size={26} className="text-success" />
        <p className="text-sm font-medium text-foreground">Nothing at risk right now.</p>
        <p className="text-xs text-foreground-disabled">
          Every run due within {windowDays} day(s) is already Authorized or Paid.
        </p>
      </div>
    );
  }
  return (
    <div className="mb-6 rounded-xl border-2 border-warning/40 bg-warning-light/20 p-3">
      <h2 className={`${SECTION_LABEL_CLS} mb-3 flex items-center gap-1.5`}>
        <AlertTriangle size={14} className="text-warning" />
        At Risk
        <StatusPill status="pending" label={`${count} due within ${windowDays}d, not Authorized`} />
      </h2>
      <RunsTable rows={rows} emptyLabel="" />
    </div>
  );
}

// Runs grouped under an organization's own header don't need to repeat the
// organization name in every row — same columns as RunsTable minus that one.
function OrgRunsTable({ rows }) {
  return (
    <table className="w-full text-sm min-w-[700px]">
      <thead className="bg-background text-left text-xs text-foreground-muted">
        <tr>
          <th className="px-4 py-2.5">Run</th>
          <th className="px-4 py-2.5">Period</th>
          <th className="px-4 py-2.5">Pay Date</th>
          <th className="px-4 py-2.5">Status</th>
          <th className="px-4 py-2.5 text-right">Employees</th>
          <th className="px-4 py-2.5 text-right">Net</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.run_id} className="border-t border-border-light">
            <td className="px-4 py-2.5 text-foreground-muted">{row.run_code || `#${row.run_id}`}</td>
            <td className="px-4 py-2.5 text-foreground-secondary">{row.period_label}</td>
            <td className="px-4 py-2.5 text-foreground-muted">{row.pay_date}</td>
            <td className="px-4 py-2.5"><StatusPill status={STATUS_PILL_MAP[row.status] || "pending"} label={row.status} /></td>
            <td className="px-4 py-2.5 text-right text-foreground-muted">{row.employee_count}</td>
            <td className="px-4 py-2.5 text-right font-medium text-foreground">{row.total_net ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// Every organization gets exactly one row here, including one with zero
// payroll runs — same "don't silently drop orgs with nothing to join
// against" fix already applied to Funding & Payments' by-organization view.
// Expand/collapse keeps a fleet of many organizations scannable instead of
// one giant flat table where runs from different orgs interleave by date.
function OrgRunsGroup({ org, runs, atRiskCount, expanded, onToggle }) {
  const hasRuns = runs.length > 0;
  const totalNet = runs.reduce((sum, r) => sum + (Number(r.total_net) || 0), 0);

  return (
    <div className="bg-surface rounded-xl shadow-sm border border-border overflow-hidden">
      <button
        type="button"
        onClick={hasRuns ? onToggle : undefined}
        disabled={!hasRuns}
        aria-expanded={expanded}
        className={`flex w-full items-center gap-3 px-4 py-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-focus-ring ${hasRuns ? "hover:bg-surface-muted" : "cursor-default"}`}
      >
        <Building2 size={15} className="shrink-0 text-foreground-muted" />
        <span className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">{org.organization_name}</span>
        {atRiskCount > 0 && <StatusPill status="pending" label={`${atRiskCount} at risk`} />}
        <span className="shrink-0 text-xs text-foreground-muted">
          {hasRuns ? `${runs.length} run${runs.length === 1 ? "" : "s"} · net ${totalNet.toLocaleString()}` : "No payroll runs"}
        </span>
        {hasRuns && (expanded ? <ChevronUp size={15} className="shrink-0 text-foreground-muted" /> : <ChevronDown size={15} className="shrink-0 text-foreground-muted" />)}
      </button>
      {hasRuns && expanded && (
        <div className="overflow-x-auto border-t border-border-light">
          <OrgRunsTable rows={runs} />
        </div>
      )}
    </div>
  );
}

export default function PayrollRunsMonitorPage() {
  const { addToast } = useToast() || {};
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState({ at_risk: [], all_runs: [], at_risk_window_days: 5 });
  const [organizations, setOrganizations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState(searchParams.get("status") || "");
  const [keyword, setKeyword] = useState("");
  const [expandedOrgIds, setExpandedOrgIds] = useState(() => new Set());

  const setStatusAndUrl = (value) => {
    setStatus(value);
    const next = new URLSearchParams(searchParams);
    if (value) next.set("status", value); else next.delete("status");
    setSearchParams(next, { replace: true });
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listAllPayrollRuns({ status: status || undefined });
      setData(res);
    } catch (err) {
      addToast?.(err.message, "error");
    } finally {
      setLoading(false);
    }
  }, [status]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  // Every organization on the platform, not just ones that happen to have a
  // run matching the current filter — fetched once, independent of `status`,
  // so an org with zero matching runs still shows up (with "No payroll
  // runs") instead of silently vanishing the way a plain join would.
  useEffect(() => {
    listAllOrganizationsBrief()
      .then((res) => setOrganizations(res.organizations || []))
      .catch((err) => addToast?.(err.message, "error"));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const runsByOrgId = useMemo(() => {
    const map = new Map();
    data.all_runs.forEach((run) => {
      if (!map.has(run.organization_id)) map.set(run.organization_id, []);
      map.get(run.organization_id).push(run);
    });
    return map;
  }, [data.all_runs]);

  const atRiskCountByOrgId = useMemo(() => {
    const map = new Map();
    data.at_risk.forEach((run) => {
      map.set(run.organization_id, (map.get(run.organization_id) || 0) + 1);
    });
    return map;
  }, [data.at_risk]);

  const visibleOrganizations = useMemo(() => {
    const k = keyword.trim().toLowerCase();
    const filtered = k
      ? organizations.filter((o) => (o.organization_name || "").toLowerCase().includes(k))
      : organizations;
    return [...filtered].sort((a, b) => (a.organization_name || "").localeCompare(b.organization_name || ""));
  }, [organizations, keyword]);

  function toggleOrg(orgId) {
    setExpandedOrgIds((prev) => {
      const next = new Set(prev);
      if (next.has(orgId)) next.delete(orgId); else next.add(orgId);
      return next;
    });
  }

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <PlayCircle size={22} className="text-primary" /> Payroll Runs
          </h1>
          <p className="text-sm text-foreground-muted mt-0.5">Cross-organization payroll run monitor — read-only.</p>
        </div>
        <div className="flex items-center gap-2">
          <select value={status} onChange={(e) => setStatusAndUrl(e.target.value)} className="rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground">
            <option value="">All Statuses</option>
            {["Draft", "Review", "Approved", "Authorized", "Paid", "Closed"].map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5 disabled:opacity-50"
          >
            <RefreshCcw size={15} className={loading ? "animate-spin" : ""} /> Refresh
          </button>
        </div>
      </div>

      <AtRiskSection rows={data.at_risk} windowDays={data.at_risk_window_days} />

      <div>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 className={SECTION_LABEL_CLS}>
            Every Organization ({visibleOrganizations.length})
          </h2>
          <input
            type="text"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="Filter by organization name…"
            className="w-full max-w-xs rounded-lg border border-border bg-surface px-3 py-2 text-sm text-foreground"
          />
        </div>
        <div className="flex flex-col gap-2">
          {visibleOrganizations.map((org) => (
            <OrgRunsGroup
              key={org.id}
              org={org}
              runs={runsByOrgId.get(org.id) || []}
              atRiskCount={atRiskCountByOrgId.get(org.id) || 0}
              expanded={expandedOrgIds.has(org.id)}
              onToggle={() => toggleOrg(org.id)}
            />
          ))}
          {visibleOrganizations.length === 0 && !loading && (
            <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-border bg-surface px-4 py-10 text-center shadow-sm">
              <p className="text-sm text-foreground-disabled">No organizations match "{keyword}".</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
