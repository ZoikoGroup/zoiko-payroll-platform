import { useCallback, useEffect, useState } from "react";
import { CreditCard, RefreshCcw } from "lucide-react";
import StatusPill from "../../components/StatusPill";
import { useToast } from "../../context/ToastContext";
import { listAllSubscriptions } from "../../service/commandCenterService";

const DAY_MS = 86400000;

// Raw BillingSubscription.status values (see billing/models.py
// SubscriptionStatus) plus two derived-only pseudo-statuses: NONE (no
// subscription row at all — a PRODUCTION org created before this
// feature, or any org that never subscribed) and GRACE_READONLY/CLOSED,
// which are trial *stages* computed from current_period_end /
// grace_period_ends_at (trial_lifecycle.resolve_trial_stage) — the raw
// `status` column stays "TRIALING" straight through grace and closure,
// so displaying it as-is would show a closed trial as still active.
const DISPLAY_META = {
  NONE: { pill: "inactive", label: "No Subscription" },
  TRIALING: { pill: "pending", label: "Trialing" },
  ACTIVE: { pill: "active", label: "Active" },
  PAST_DUE: { pill: "on_hold", label: "Past Due" },
  SUSPENDED: { pill: "suspended", label: "Suspended" },
  CANCELLED: { pill: "deactivated", label: "Cancelled" },
  GRACE_READONLY: { pill: "on_hold", label: "Grace (Read-Only)" },
  CLOSED: { pill: "rejected", label: "Trial Closed" },
};

function formatDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString();
}

function displayStatus(row) {
  if (row.status === "NONE") return "NONE";
  if (row.trial_stage === "GRACE_READONLY") return "GRACE_READONLY";
  if (row.trial_stage === "CLOSED") return "CLOSED";
  return row.status;
}

const BAR_COLOR = {
  success: "#16A34A",
  warning: "#D97706",
  error: "#DC2626",
};

// Percent of the current period (or, once in grace, the grace window)
// remaining, plus a human label — same "remaining/total" derivation
// TrialBanner.jsx uses for the trial banner's own progress bar.
function computeRemaining(row) {
  const now = Date.now();

  if (row.status === "NONE") return null;

  if (row.trial_stage === "CLOSED") {
    return { label: "Closed", percent: 0, tone: "error" };
  }

  if (row.trial_stage === "GRACE_READONLY" && row.grace_period_ends_at) {
    const graceEndMs = new Date(row.grace_period_ends_at).getTime();
    const periodEndMs = row.current_period_end ? new Date(row.current_period_end).getTime() : graceEndMs - DAY_MS;
    const totalMs = Math.max(1, graceEndMs - periodEndMs);
    const remainingMs = Math.max(0, graceEndMs - now);
    const days = Math.ceil(remainingMs / DAY_MS);
    return {
      label: `${days}d grace left`,
      percent: Math.min(100, Math.max(0, (remainingMs / totalMs) * 100)),
      tone: "warning",
    };
  }

  if (!row.current_period_end) return null;

  const periodEndMs = new Date(row.current_period_end).getTime();
  const periodStartMs = row.current_period_start ? new Date(row.current_period_start).getTime() : periodEndMs - 30 * DAY_MS;
  const totalMs = Math.max(1, periodEndMs - periodStartMs);
  const remainingMs = Math.max(0, periodEndMs - now);
  const percent = Math.min(100, Math.max(0, (remainingMs / totalMs) * 100));
  const days = Math.ceil(remainingMs / DAY_MS);
  const tone = remainingMs <= 0 ? "error" : percent < 20 ? "warning" : "success";
  return { label: `${Math.max(0, days)}d left`, percent, tone };
}

function RemainingBar({ row }) {
  const remaining = computeRemaining(row);
  if (!remaining) return <span className="text-foreground-disabled">—</span>;
  const color = BAR_COLOR[remaining.tone];
  return (
    <div className="min-w-[120px]">
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-muted">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${remaining.percent}%`, backgroundColor: color }}
        />
      </div>
      <span className="mt-1 block text-xs font-medium" style={{ color }}>{remaining.label}</span>
    </div>
  );
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
          <p className="text-sm text-foreground-muted mt-0.5">Every organization, whether or not it has a subscription yet — and their billing status.</p>
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
          <option value="NONE">No Subscription</option>
          <option value="TRIALING">Trialing</option>
          <option value="ACTIVE">Active</option>
          <option value="PAST_DUE">Past Due</option>
          <option value="SUSPENDED">Suspended</option>
          <option value="CANCELLED">Cancelled</option>
        </select>
        <select value={workspaceType} onChange={(e) => setWorkspaceType(e.target.value)} className="rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground">
          <option value="">All Workspace Types</option>
          <option value="PRODUCTION">Production</option>
          <option value="EVALUATION">Evaluation</option>
        </select>
      </div>

      <div className="bg-surface rounded-xl shadow-sm border border-border overflow-hidden overflow-x-auto">
        <table className="w-full text-sm min-w-[1000px]">
          <thead className="bg-background text-left text-xs text-foreground-muted">
            <tr>
              <th className="px-4 py-3">Organization</th>
              <th className="px-4 py-3">Workspace</th>
              <th className="px-4 py-3">Plan</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Period Start</th>
              <th className="px-4 py-3">Period End</th>
              <th className="px-4 py-3">Grace Ends</th>
              <th className="px-4 py-3">Remaining</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const ds = displayStatus(row);
              const meta = DISPLAY_META[ds] || { pill: "inactive", label: ds };
              return (
                <tr key={row.organization_id} className="border-t border-border-light">
                  <td className="px-4 py-3 font-medium text-foreground">{row.organization_name}</td>
                  <td className="px-4 py-3 text-foreground-muted">{row.workspace_type}</td>
                  <td className="px-4 py-3 text-foreground-secondary">{row.plan_name || row.plan_code || "—"}</td>
                  <td className="px-4 py-3"><StatusPill status={meta.pill} label={meta.label} /></td>
                  <td className="px-4 py-3 text-foreground-muted">{formatDate(row.current_period_start)}</td>
                  <td className="px-4 py-3 text-foreground-muted">{formatDate(row.current_period_end)}</td>
                  <td className="px-4 py-3 text-foreground-muted">{formatDate(row.grace_period_ends_at)}</td>
                  <td className="px-4 py-3"><RemainingBar row={row} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!loading && rows.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 px-4 py-14 text-center">
            <CreditCard size={28} className="text-border-strong" />
            <p className="text-sm text-foreground-disabled">No organizations match these filters.</p>
          </div>
        )}
      </div>
    </div>
  );
}
