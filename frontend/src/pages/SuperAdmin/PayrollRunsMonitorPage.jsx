import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { PlayCircle, RefreshCcw, AlertTriangle, ShieldCheck, Info } from "lucide-react";
import StatusPill from "../../components/StatusPill";
import WorkerDataLocked from "../../components/WorkerDataLocked";
import { LoadError, LoadingBlocks } from "../../components/LoadState";
import { listAllPayrollRuns } from "../../service/commandCenterService";

const RUN_STATUSES = ["Draft", "Review", "Approved", "Authorized", "Paid", "Closed"];

const STATUS_PILL_MAP = { Paid: "active", Closed: "active", Approved: "approved", Authorized: "approved", Review: "pending", Draft: "inactive" };

const SECTION_LABEL_CLS = "text-xs font-semibold uppercase tracking-wider text-foreground-muted";

const EMPTY_DATA = { by_status: [], at_risk: { run_count: 0, organization_count: 0 }, at_risk_window_days: 5, privacy_note: "" };

// At-Risk gets a structurally distinct shell: an amber escalation card when
// something needs attention, or a calm reassuring panel when nothing does.
// Counts only (ZP-PRIV B.1) — which runs/organizations is tenant data.
function AtRiskSection({ atRisk, windowDays }) {
  const runs = atRisk?.run_count || 0;
  const orgs = atRisk?.organization_count || 0;
  if (runs === 0) {
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
    <div className="mb-6 flex flex-wrap items-center gap-3 rounded-xl border-2 border-warning/40 bg-warning-light/20 p-4">
      <AlertTriangle size={22} className="shrink-0 text-warning" />
      <div className="min-w-0 flex-1">
        <h2 className={`${SECTION_LABEL_CLS} mb-1`}>At Risk</h2>
        <p className="text-sm font-medium text-foreground">
          {runs} payroll run{runs === 1 ? "" : "s"} across {orgs} organization{orgs === 1 ? "" : "s"} due within{" "}
          {windowDays} day(s) and not yet Authorized.
        </p>
        <p className="mt-0.5 text-xs text-foreground-muted">
          Each organization sees and resolves its own runs. Contact the tenant, or use Support Access with their approval.
        </p>
      </div>
      <StatusPill status="pending" label={`${runs} at risk`} />
    </div>
  );
}

export default function PayrollRunsMonitorPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState(EMPTY_DATA);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState(searchParams.get("status") || "");

  const setStatusAndUrl = (value) => {
    setStatus(value);
    const next = new URLSearchParams(searchParams);
    if (value) next.set("status", value); else next.delete("status");
    setSearchParams(next, { replace: true });
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await listAllPayrollRuns({ status: status || undefined });
      setData({ ...EMPTY_DATA, ...res });
      setLoaded(true);
    } catch (err) {
      setError(err?.message || "Payroll run totals could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [status]);

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { load(); }, [load]);

  // Totals per status across every jurisdiction (run counts add up; the
  // organization count does not, so it's shown per jurisdiction only).
  const runsByStatus = useMemo(() => {
    const map = new Map();
    (data.by_status || []).forEach((row) => {
      map.set(row.status, (map.get(row.status) || 0) + (row.run_count || 0));
    });
    return map;
  }, [data.by_status]);

  const byJurisdiction = useMemo(() => {
    const map = new Map();
    (data.by_status || []).forEach((row) => {
      if (!map.has(row.jurisdiction)) map.set(row.jurisdiction, []);
      map.get(row.jurisdiction).push(row);
    });
    return [...map.entries()].sort(([a], [b]) => String(a).localeCompare(String(b)));
  }, [data.by_status]);

  const totalRuns = [...runsByStatus.values()].reduce((sum, n) => sum + n, 0);
  const statusesShown = status ? [status] : RUN_STATUSES;

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <PlayCircle size={22} className="text-primary" /> Payroll Runs
          </h1>
          <p className="text-sm text-foreground-muted mt-0.5">
            Cross-organization payroll run counts by jurisdiction and status — read-only.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select value={status} onChange={(e) => setStatusAndUrl(e.target.value)} className="rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground">
            <option value="">All Statuses</option>
            {RUN_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
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

      <div className="mb-5 flex items-start gap-2 rounded-lg border border-info/30 bg-info-light px-4 py-3 text-sm text-info">
        <Info size={16} className="mt-0.5 shrink-0" />
        <span>
          {data.privacy_note || "Individual payroll runs are tenant data. Use Support Access with the tenant's approval to look at a specific run."}
        </span>
      </div>

      <LoadError message={error} onRetry={load} />
      {!loaded && !error && <LoadingBlocks count={3} />}
      {loaded && <AtRiskSection atRisk={data.at_risk} windowDays={data.at_risk_window_days} />}

      <div className="mb-6">
        <h2 className={`${SECTION_LABEL_CLS} mb-3`}>Runs by Status ({totalRuns} total)</h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          {statusesShown.map((s) => (
            <div key={s} className="bg-surface border border-border rounded-xl shadow-sm p-4">
              <div className="text-2xl font-bold text-foreground">{runsByStatus.get(s) || 0}</div>
              <div className="mt-1.5"><StatusPill status={STATUS_PILL_MAP[s] || "pending"} label={s} /></div>
            </div>
          ))}
        </div>
      </div>

      <div className="mb-6">
        <h2 className={`${SECTION_LABEL_CLS} mb-1`}>By Jurisdiction ({byJurisdiction.length})</h2>
        <p className="mb-3 text-xs text-foreground-muted">
          Run counts per status. Hover a number to see how many organizations it covers.
        </p>
        <div className="bg-surface rounded-xl shadow-sm border border-border overflow-hidden overflow-x-auto">
          <table className="w-full text-sm min-w-[720px]">
            <thead className="bg-background text-left text-xs text-foreground-muted">
              <tr>
                <th className="px-4 py-3">Jurisdiction</th>
                {statusesShown.map((s) => (
                  <th key={s} className="px-3 py-3 text-right">
                    <span className="inline-flex justify-end"><StatusPill status={STATUS_PILL_MAP[s] || "pending"} label={s} /></span>
                  </th>
                ))}
                <th className="px-4 py-3 text-right">Total</th>
              </tr>
            </thead>
            <tbody>
              {byJurisdiction.map(([jurisdiction, rows]) => {
                const cell = Object.fromEntries(rows.map((r) => [r.status, r]));
                const total = rows.reduce((n, r) => n + (r.run_count || 0), 0);
                return (
                  <tr key={jurisdiction} className="border-t border-border-light">
                    <td className="px-4 py-3 font-medium text-foreground">
                      {jurisdiction === "UNASSIGNED" ? "Unassigned" : jurisdiction}
                    </td>
                    {statusesShown.map((s) => (
                      <td key={s} className="px-3 py-3 text-right tabular-nums"
                        title={cell[s] ? `${cell[s].organization_count} organization(s)` : undefined}>
                        {cell[s]?.run_count ? (
                          <span className="text-foreground">{cell[s].run_count}</span>
                        ) : (
                          <span className="text-foreground-disabled">–</span>
                        )}
                      </td>
                    ))}
                    <td className="px-4 py-3 text-right font-semibold tabular-nums text-foreground">{total}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {loaded && !loading && byJurisdiction.length === 0 && (
            <div className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-center">
              <p className="text-sm text-foreground-disabled">No payroll runs match this filter.</p>
            </div>
          )}
        </div>
      </div>

      <WorkerDataLocked variant="support" title="Need to look at a specific run?">
        <p className="leading-relaxed">
          Run details — employees, amounts and pay dates — belong to the organization. Zoiko staff can view them only
          through a time-limited Support Access grant the organization approves.
        </p>
      </WorkerDataLocked>
    </div>
  );
}
