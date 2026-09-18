import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, RefreshCcw, Info } from "lucide-react";
import { useToast } from "../../context/ToastContext";
import { listExceptions } from "../../service/commandCenterService";

export default function ExceptionsReconciliationPage() {
  const { addToast } = useToast() || {};
  const [data, setData] = useState({ stuck_reviews: [], bwm_scale_limit_overages: [], bwm_invoice_mismatches: [], note: "" });
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listExceptions();
      setData(res);
    } catch (err) {
      addToast?.(err.message, "error");
    } finally {
      setLoading(false);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <AlertTriangle size={22} className="text-primary" /> Exceptions & Reconciliation
          </h1>
          <p className="text-sm text-foreground-muted mt-0.5">Cross-organization anomalies worth a look — no remediation actions here.</p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5 disabled:opacity-50"
        >
          <RefreshCcw size={15} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>

      <div className="mb-6">
        <h2 className="text-sm font-semibold text-foreground-secondary mb-3">Stuck in Review</h2>
        <div className="bg-surface rounded-xl shadow-sm border border-border overflow-hidden overflow-x-auto">
          <table className="w-full text-sm min-w-[700px]">
            <thead className="bg-background text-left text-xs text-foreground-muted">
              <tr>
                <th className="px-4 py-3">Organization</th>
                <th className="px-4 py-3">Period</th>
                <th className="px-4 py-3">Pay Date</th>
                <th className="px-4 py-3">Stuck Since</th>
              </tr>
            </thead>
            <tbody>
              {data.stuck_reviews.map((row) => (
                <tr key={row.run_id} className="border-t border-border-light">
                  <td className="px-4 py-3 font-medium text-foreground">{row.organization_name}</td>
                  <td className="px-4 py-3 text-foreground-secondary">{row.period_label}</td>
                  <td className="px-4 py-3 text-foreground-muted">{row.pay_date}</td>
                  <td className="px-4 py-3 text-foreground-muted">{new Date(row.stuck_since).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.stuck_reviews.length === 0 && (
            <div className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-center">
              <p className="text-sm text-foreground-disabled">No runs stuck in review.</p>
            </div>
          )}
        </div>
      </div>

      <div className="mb-6">
        <h2 className="text-sm font-semibold text-foreground-secondary mb-3">Over Plan Limit (Billable Worker-Months)</h2>
        <div className="bg-surface rounded-xl shadow-sm border border-border overflow-hidden overflow-x-auto">
          <table className="w-full text-sm min-w-[700px]">
            <thead className="bg-background text-left text-xs text-foreground-muted">
              <tr>
                <th className="px-4 py-3">Organization</th>
                <th className="px-4 py-3">Billing Month</th>
                <th className="px-4 py-3 text-right">BWM Count</th>
                <th className="px-4 py-3 text-right">Plan Limit</th>
                <th className="px-4 py-3 text-right">Over By</th>
              </tr>
            </thead>
            <tbody>
              {data.bwm_scale_limit_overages.map((row) => (
                <tr key={`${row.organization_id}-${row.billing_month}`} className="border-t border-border-light">
                  <td className="px-4 py-3 font-medium text-foreground">{row.organization_name}</td>
                  <td className="px-4 py-3 text-foreground-muted">{row.billing_month}</td>
                  <td className="px-4 py-3 text-right text-foreground-secondary">{row.bwm_count}</td>
                  <td className="px-4 py-3 text-right text-foreground-muted">{row.plan_limit}</td>
                  <td className="px-4 py-3 text-right font-semibold text-error">+{row.over_by}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.bwm_scale_limit_overages.length === 0 && (
            <div className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-center">
              <p className="text-sm text-foreground-disabled">No organizations over their plan's worker-month limit this month.</p>
            </div>
          )}
        </div>
        {data.note && (
          <div className="mt-3 flex items-start gap-2 rounded-lg border border-info/30 bg-info-light px-4 py-3 text-sm text-info">
            <Info size={16} className="mt-0.5 shrink-0" />
            <span>{data.note}</span>
          </div>
        )}
      </div>

      <div className="mb-6">
        <h2 className="text-sm font-semibold text-foreground-secondary mb-3">BWM / Invoice Mismatches</h2>
        <p className="text-xs text-foreground-disabled mb-3">
          An invoice's billed worker-month quantity that doesn't match the actual counted records for that org/month —
          a real billing bug, not an edge case to defer.
        </p>
        <div className="bg-surface rounded-xl shadow-sm border border-border overflow-hidden overflow-x-auto">
          <table className="w-full text-sm min-w-[700px]">
            <thead className="bg-background text-left text-xs text-foreground-muted">
              <tr>
                <th className="px-4 py-3">Organization</th>
                <th className="px-4 py-3">Billing Month</th>
                <th className="px-4 py-3 text-right">Invoiced Qty</th>
                <th className="px-4 py-3 text-right">Actual BWM Count</th>
                <th className="px-4 py-3 text-right">Difference</th>
              </tr>
            </thead>
            <tbody>
              {data.bwm_invoice_mismatches.map((row) => (
                <tr key={row.invoice_id} className="border-t border-border-light">
                  <td className="px-4 py-3 font-medium text-foreground">{row.organization_name || `Org #${row.organization_id}`}</td>
                  <td className="px-4 py-3 text-foreground-muted">{row.billing_month}</td>
                  <td className="px-4 py-3 text-right text-foreground-secondary">{row.invoiced_quantity}</td>
                  <td className="px-4 py-3 text-right text-foreground-secondary">{row.actual_bwm_count}</td>
                  <td className="px-4 py-3 text-right font-semibold text-error">
                    {row.difference > 0 ? `+${row.difference}` : row.difference}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.bwm_invoice_mismatches.length === 0 && (
            <div className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-center">
              <p className="text-sm text-foreground-disabled">No BWM/invoice mismatches found.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
