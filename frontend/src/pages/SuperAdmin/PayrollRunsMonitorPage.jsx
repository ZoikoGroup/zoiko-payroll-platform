import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { PlayCircle, RefreshCcw, AlertTriangle } from "lucide-react";
import StatusPill from "../../components/StatusPill";
import { useToast } from "../../context/ToastContext";
import { listAllPayrollRuns } from "../../service/commandCenterService";

const STATUS_PILL_MAP = { Paid: "active", Closed: "active", Approved: "approved", Authorized: "approved", Review: "pending", Draft: "inactive" };

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

export default function PayrollRunsMonitorPage() {
  const { addToast } = useToast() || {};
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState({ at_risk: [], all_runs: [], at_risk_window_days: 5 });
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState(searchParams.get("status") || "");

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

      <div className="mb-6">
        <h2 className="text-sm font-semibold text-foreground-secondary mb-3 flex items-center gap-1.5">
          <AlertTriangle size={15} className="text-amber-500" />
          At Risk — due within {data.at_risk_window_days} day(s), not yet Authorized/Paid
        </h2>
        <RunsTable rows={data.at_risk} emptyLabel="Nothing at risk right now." />
      </div>

      <div>
        <h2 className="text-sm font-semibold text-foreground-secondary mb-3">All Runs</h2>
        <RunsTable rows={data.all_runs} emptyLabel="No payroll runs match these filters." />
      </div>
    </div>
  );
}
