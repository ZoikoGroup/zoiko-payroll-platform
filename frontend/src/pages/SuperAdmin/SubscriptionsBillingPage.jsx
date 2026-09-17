import { useCallback, useEffect, useState } from "react";
import { CreditCard, RefreshCcw } from "lucide-react";
import StatusPill from "../../components/StatusPill";
import { useToast } from "../../context/ToastContext";
import { listAllSubscriptions } from "../../service/commandCenterService";

const STATUS_PILL_MAP = {
  ACTIVE: "active",
  TRIALING: "pending",
  GRACE_READONLY: "on_hold",
  PAST_DUE: "on_hold",
  CANCELED: "deactivated",
  CLOSED: "deactivated",
};

function formatDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString();
}

export default function SubscriptionsBillingPage() {
  const { addToast } = useToast() || {};
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState("");
  const [workspaceType, setWorkspaceType] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listAllSubscriptions({ status: status || undefined, workspace_type: workspaceType || undefined });
      setRows(res.subscriptions || []);
    } catch (err) {
      addToast?.(err.message, "error");
    } finally {
      setLoading(false);
    }
  }, [status, workspaceType]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <CreditCard size={22} className="text-primary" /> Subscriptions & Billing
          </h1>
          <p className="text-sm text-foreground-muted mt-0.5">Cross-organization view of who's on what plan and their billing status.</p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5 disabled:opacity-50"
        >
          <RefreshCcw size={15} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2 mb-4">
        <select value={status} onChange={(e) => setStatus(e.target.value)} className="rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground">
          <option value="">All Statuses</option>
          <option value="ACTIVE">Active</option>
          <option value="TRIALING">Trialing</option>
          <option value="GRACE_READONLY">Grace (Read-Only)</option>
          <option value="PAST_DUE">Past Due</option>
          <option value="CANCELED">Canceled</option>
        </select>
        <select value={workspaceType} onChange={(e) => setWorkspaceType(e.target.value)} className="rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground">
          <option value="">All Workspace Types</option>
          <option value="PRODUCTION">Production</option>
          <option value="EVALUATION">Evaluation</option>
        </select>
      </div>

      <div className="bg-surface rounded-xl shadow-sm border border-border overflow-hidden overflow-x-auto">
        <table className="w-full text-sm min-w-[900px]">
          <thead className="bg-background text-left text-xs text-foreground-muted">
            <tr>
              <th className="px-4 py-3">Organization</th>
              <th className="px-4 py-3">Workspace</th>
              <th className="px-4 py-3">Plan</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Period Start</th>
              <th className="px-4 py-3">Period End</th>
              <th className="px-4 py-3">Grace Ends</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.subscription_id} className="border-t border-border-light">
                <td className="px-4 py-3 font-medium text-foreground">{row.organization_name}</td>
                <td className="px-4 py-3 text-foreground-muted">{row.workspace_type}</td>
                <td className="px-4 py-3 text-foreground-secondary">{row.plan_name || row.plan_code || "—"}</td>
                <td className="px-4 py-3"><StatusPill status={STATUS_PILL_MAP[row.status] || "pending"} label={row.status} /></td>
                <td className="px-4 py-3 text-foreground-muted">{formatDate(row.current_period_start)}</td>
                <td className="px-4 py-3 text-foreground-muted">{formatDate(row.current_period_end)}</td>
                <td className="px-4 py-3 text-foreground-muted">{formatDate(row.grace_period_ends_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && rows.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 px-4 py-14 text-center">
            <CreditCard size={28} className="text-border-strong" />
            <p className="text-sm text-foreground-disabled">No subscriptions match these filters.</p>
          </div>
        )}
      </div>
    </div>
  );
}
