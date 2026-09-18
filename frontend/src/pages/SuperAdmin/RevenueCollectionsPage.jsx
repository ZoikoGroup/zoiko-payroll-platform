import { useCallback, useEffect, useState } from "react";
import { CircleDollarSign, RefreshCcw, ShieldCheck, AlertTriangle } from "lucide-react";
import StatusPill from "../../components/StatusPill";
import { useToast } from "../../context/ToastContext";
import { getRevenueCollections } from "../../service/commandCenterService";

// Same dunning vocabulary as SubscriptionsBillingPage.jsx — raw
// BillingDunningState.stage values, identical labels and pill tokens. One
// visual language for dunning across the Command Center; not a second one.
const DUNNING_STAGE_LABEL = {
  RETRY: "Retry",
  RESTRICT_EXPANSION: "Restrict Expansion",
  RESTRICT_NEW_RUN: "Restrict New Runs",
  READ_ONLY: "Read-Only",
};
const DUNNING_STAGE_PILL = {
  RETRY: "pending",
  RESTRICT_EXPANSION: "on_hold",
  RESTRICT_NEW_RUN: "on_hold",
  READ_ONLY: "rejected",
};

function formatMoney(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return value || "—";
  return new Intl.NumberFormat(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(num);
}

function StatCard({ icon: Icon, label, value, detail }) {
  return (
    <div className="bg-surface border border-border rounded-xl shadow-sm p-5 min-w-[200px]">
      <div className="flex items-center gap-2 text-foreground-muted mb-1">
        <Icon size={16} className="text-primary" />
        <span className="text-sm font-medium">{label}</span>
      </div>
      <p className="text-2xl font-bold text-foreground">{value}</p>
      {detail && <p className="mt-1 text-xs text-foreground-muted">{detail}</p>}
    </div>
  );
}

export default function RevenueCollectionsPage() {
  const { addToast } = useToast() || {};
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getRevenueCollections();
      setData(res);
    } catch (err) {
      addToast?.(err.message, "error");
    } finally {
      setLoading(false);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  const pastDue = data?.past_due || [];

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <CircleDollarSign size={22} className="text-primary" /> Revenue & Collections
          </h1>
          <p className="text-sm text-foreground-muted mt-0.5">
            Zoiko's own subscription revenue (PAID invoices) — distinct from Funding &amp; Payments, which reports customers'
            payroll money movement. These are never merged.
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

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4 mb-6">
        <StatCard
          icon={CircleDollarSign}
          label="MRR This Month"
          value={formatMoney(data?.mrr_this_month)}
          detail={
            data && data.paid_invoices_this_month > 0
              ? `${data.paid_invoices_this_month} paid invoice(s) this month`
              : "No paid invoices issued this month"
          }
        />
        <StatCard
          icon={CircleDollarSign}
          label="Active Subscriptions"
          value={data?.active_subscriptions ?? "—"}
          detail={data && data.cancelled_this_month > 0 ? `${data.cancelled_this_month} cancelled this month` : "No cancellations this month"}
        />
        <StatCard
          icon={CircleDollarSign}
          label="Churn This Month"
          value={data ? `${data.churn_pct}%` : "—"}
          detail="Cancelled / (active + cancelled)"
        />
        <StatCard
          icon={AlertTriangle}
          label="Past-Due Orgs"
          value={pastDue.length}
          detail={pastDue.length > 0 ? "Org(s) in a dunning stage" : "Nothing in dunning"}
        />
      </div>

      {data && data.mrr_by_currency.length > 0 && (
        <div className="mb-6 flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-foreground-muted">By currency:</span>
          {data.mrr_by_currency.map((c) => (
            <span key={c.currency} className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface px-2.5 py-1 text-xs text-foreground-secondary">
              <span className="font-semibold text-foreground">{c.currency}</span>
              {formatMoney(c.total)}
              <span className="text-foreground-disabled">({c.invoices} invoice{c.invoices === 1 ? "" : "s"})</span>
            </span>
          ))}
        </div>
      )}

      <div className="bg-surface rounded-xl shadow-sm border border-border overflow-hidden overflow-x-auto">
        <div className="px-4 py-3 border-b border-border-light">
          <h2 className="text-sm font-semibold text-foreground-secondary flex items-center gap-1.5">
            <AlertTriangle size={15} className="text-amber-500" />
            Past Due — dunning stages and in-flight-run protection
          </h2>
        </div>
        <table className="w-full text-sm min-w-[640px]">
          <thead className="bg-background text-left text-xs text-foreground-muted">
            <tr>
              <th className="px-4 py-3">Organization</th>
              <th className="px-4 py-3">Dunning Stage</th>
              <th className="px-4 py-3">Protection</th>
            </tr>
          </thead>
          <tbody>
            {pastDue.map((row) => (
              <tr key={row.organization_id} className="border-t border-border-light">
                <td className="px-4 py-3 font-medium text-foreground">{row.organization_name}</td>
                <td className="px-4 py-3">
                  <StatusPill
                    status={DUNNING_STAGE_PILL[row.dunning_stage] || "inactive"}
                    label={DUNNING_STAGE_LABEL[row.dunning_stage] || row.dunning_stage}
                  />
                </td>
                <td className="px-4 py-3">
                  {row.in_flight_run_guard ? (
                    <span
                      className="inline-flex items-center gap-1 text-xs font-semibold"
                      style={{ color: "#166534" }}
                      title="An authorized payroll run is currently in flight for this org — dunning is frozen at this stage and that run will complete normally."
                    >
                      <ShieldCheck size={12} className="shrink-0" />
                      Payment overdue, but protected — an authorized run is in flight
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-xs font-semibold text-amber-600 dark:text-amber-500">
                      <AlertTriangle size={12} className="shrink-0" />
                      At risk — no authorized run in flight to shield this org
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && pastDue.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 px-4 py-14 text-center">
            <ShieldCheck size={28} className="text-border-strong" />
            <p className="text-sm text-foreground-disabled">No past-due orgs right now.</p>
          </div>
        )}
      </div>
    </div>
  );
}