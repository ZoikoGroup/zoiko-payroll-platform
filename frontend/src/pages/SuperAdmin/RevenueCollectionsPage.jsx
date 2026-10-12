import { useCallback, useEffect, useState } from "react";
import { CircleDollarSign, RefreshCcw, ShieldCheck, AlertTriangle } from "lucide-react";
import StatusPill from "../../components/StatusPill";
import { useToast } from "../../context/ToastContext";
import { getRevenueCollections } from "../../service/commandCenterService";

const SECTION_LABEL_CLS = "text-xs font-semibold uppercase tracking-wider text-foreground-muted";

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

// Deliberately quieter than a "hero" figure: no border/shadow competing for
// attention, smaller data-value size — these are supporting context next to
// the MRR figure, not four equally-weighted cards.
function QuietStat({ icon: Icon, label, value, detail, tone }) {
  const toneCls = tone === "warning" ? "text-warning" : "text-foreground";
  return (
    <div className="p-3">
      <div className="flex items-center gap-1.5 text-foreground-muted mb-1">
        <Icon size={14} className={tone === "warning" ? "text-warning" : "text-primary"} />
        <span className="text-xs font-medium">{label}</span>
      </div>
      <p className={`text-xl font-bold ${toneCls}`}>{value}</p>
      {detail && <p className="mt-0.5 text-xs text-foreground-muted">{detail}</p>}
    </div>
  );
}

export default function RevenueCollectionsPage() {
  const { addToast } = useToast() || {};
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [revealed, setRevealed] = useState(false);

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

  // One deliberate reveal moment for the MRR figure itself — not applied to
  // every card, per the "avoid generic fade-and-slide-up" guidance.
  useEffect(() => {
    if (data) {
      const frame = requestAnimationFrame(() => setRevealed(true));
      return () => cancelAnimationFrame(frame);
    }
  }, [data]);

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

      <div className="mb-8 flex flex-col gap-6 border-b border-border-light pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2 text-foreground-muted mb-1">
            <CircleDollarSign size={16} className="text-primary" />
            <span className={SECTION_LABEL_CLS}>MRR This Month</span>
          </div>
          <p
            className={`text-6xl font-extrabold tracking-tight text-foreground transition-opacity duration-500 ease-out ${
              revealed ? "opacity-100" : "opacity-0"
            }`}
          >
            {formatMoney(data?.mrr_this_month)}
          </p>
          <p className="mt-1 text-sm text-foreground-muted">
            {data && data.paid_invoices_this_month > 0
              ? `${data.paid_invoices_this_month} paid invoice(s) this month`
              : "No paid invoices issued this month"}
          </p>
        </div>

        <div className="grid grid-cols-1 divide-y divide-border-light rounded-lg bg-surface-muted sm:grid-cols-3 sm:divide-x sm:divide-y-0 lg:min-w-[440px]">
          <QuietStat
            icon={CircleDollarSign}
            label="Active Subscriptions"
            value={data?.active_subscriptions ?? "—"}
            detail={data && data.cancelled_this_month > 0 ? `${data.cancelled_this_month} cancelled this month` : "No cancellations this month"}
          />
          <QuietStat
            icon={CircleDollarSign}
            label="Churn This Month"
            value={data ? `${data.churn_pct}%` : "—"}
            detail="Cancelled / (active + cancelled)"
          />
          <QuietStat
            icon={AlertTriangle}
            label="Past-Due Orgs"
            value={pastDue.length}
            detail={pastDue.length > 0 ? "Org(s) in a dunning stage" : "Nothing in dunning"}
            tone={pastDue.length > 0 ? "warning" : undefined}
          />
        </div>
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
          <h2 className={`${SECTION_LABEL_CLS} flex items-center gap-1.5`}>
            <AlertTriangle size={14} className="text-warning" />
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
              <tr
                key={row.organization_id}
                className={`border-t border-border-light ${!row.in_flight_run_guard ? "bg-warning-light/40" : ""}`}
              >
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
                      className="inline-flex items-center gap-1.5"
                      title="An authorized payroll run is currently in flight for this org — dunning is frozen at this stage and that run will complete normally."
                    >
                      <ShieldCheck size={13} className="shrink-0 text-success" />
                      <StatusPill status="active" label="Protected — run in flight" />
                    </span>
                  ) : (
                    <span
                      className="inline-flex items-center gap-1.5"
                      title="No authorized payroll run is currently in flight to shield this org from the next dunning escalation."
                    >
                      <AlertTriangle size={13} className="shrink-0 text-warning" />
                      <StatusPill status="on_hold" label="At risk — no run in flight" />
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