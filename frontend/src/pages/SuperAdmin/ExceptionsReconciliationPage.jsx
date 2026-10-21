import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, RefreshCcw, Info, ShieldCheck } from "lucide-react";
import StatusPill from "../../components/StatusPill";
import WorkerDataLocked from "../../components/WorkerDataLocked";
import { LoadError, LoadingBlocks } from "../../components/LoadState";
import { listExceptions } from "../../service/commandCenterService";

const SECTION_LABEL_CLS = "text-xs font-semibold uppercase tracking-wider text-foreground-muted";

// Same high/medium/low -> rejected/pending/inactive vocabulary as
// AlertsIncidentsPage.jsx. These 3 categories aren't in that feed yet, so
// there's no precedent severity value to copy — the level below is taken
// from each endpoint's own docstring in command_center_router.py:
// stuck-in-review blocks payroll the same way an at-risk run does (high);
// the plan-limit endpoint calls itself "informational only... nothing
// currently blocks this" (medium); the BWM/invoice mismatch endpoint calls
// itself "a real billing bug, not an edge case to defer" (high).
const EXCEPTION_SEVERITY = {
  stuck: "high",
  overLimit: "medium",
  mismatch: "high",
};
const SEVERITY_PILL = { high: "rejected", medium: "pending", low: "inactive" };

const EMPTY_DATA = {
  stuck_reviews: { run_count: 0, organization_count: 0, older_than_days: 3 },
  bwm_scale_limit_overages: [],
  bwm_invoice_mismatches: [],
  note: "",
};

// "2026-10-01" / "2026-10" -> "Oct 2026" (UTC, never shifted by the viewer's zone).
function formatMonth(value) {
  const m = /^(\d{4})-(\d{2})/.exec(String(value || ""));
  if (!m) return value || "—";
  return new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, 1))
    .toLocaleDateString(undefined, { month: "short", year: "numeric", timeZone: "UTC" });
}

function ExceptionCountBadge({ label, count, severityKey }) {
  const active = count > 0;
  return (
    <div className="flex items-center gap-3 rounded-xl border border-border bg-surface p-4 shadow-sm min-w-[180px]">
      <span className={`flex h-10 w-10 items-center justify-center rounded-lg ${active ? "bg-error/10 text-error" : "bg-surface-muted text-foreground-muted"}`}>
        {active ? <AlertTriangle size={20} /> : <ShieldCheck size={20} />}
      </span>
      <div>
        <p className="text-2xl font-bold text-foreground leading-none">{count}</p>
        <p className="mt-1 text-xs text-foreground-muted">{label}</p>
      </div>
      {active && (
        <StatusPill status={SEVERITY_PILL[EXCEPTION_SEVERITY[severityKey]]} label={EXCEPTION_SEVERITY[severityKey] === "high" ? "High" : "Medium"} />
      )}
    </div>
  );
}

export default function ExceptionsReconciliationPage() {
  const [data, setData] = useState(EMPTY_DATA);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await listExceptions();
      setData({ ...EMPTY_DATA, ...res, stuck_reviews: { ...EMPTY_DATA.stuck_reviews, ...(res?.stuck_reviews || {}) } });
      setLoaded(true);
    } catch (err) {
      setError(err?.message || "Exceptions could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { load(); }, [load]);

  // ZP-PRIV B.1: stuck reviews arrive as counts only, never run rows.
  const stuckRuns = data.stuck_reviews.run_count || 0;
  const stuckOrgs = data.stuck_reviews.organization_count || 0;
  const stuckDays = data.stuck_reviews.older_than_days ?? 3;

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <AlertTriangle size={22} className="text-primary" /> Exceptions &amp; Reconciliation
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

      <LoadError message={error} onRetry={load} />
      {!loaded && !error && <LoadingBlocks count={3} />}
      {loaded && <>
      {/* Count-first: which of the 3 problem types need a look, before
          reading a single row. */}
      <div className="flex flex-wrap gap-4 mb-6">
        <ExceptionCountBadge label="Runs Stuck in Review" count={stuckRuns} severityKey="stuck" />
        <ExceptionCountBadge label="Over Plan Limit" count={data.bwm_scale_limit_overages.length} severityKey="overLimit" />
        <ExceptionCountBadge label="BWM/Invoice Mismatches" count={data.bwm_invoice_mismatches.length} severityKey="mismatch" />
      </div>

      <div className="mb-6">
        <h2 className={`${SECTION_LABEL_CLS} mb-3`}>Stuck in Review</h2>
        <div
          className={`flex flex-wrap items-center gap-3 rounded-xl border p-4 shadow-sm ${
            stuckRuns > 0 ? "border-2 border-error/40 bg-error-light/20" : "border-border bg-surface"
          }`}
        >
          {stuckRuns > 0 ? (
            <AlertTriangle size={22} className="shrink-0 text-error" />
          ) : (
            <ShieldCheck size={22} className="shrink-0 text-success" />
          )}
          <p className="min-w-0 flex-1 text-sm font-medium text-foreground">
            {stuckRuns > 0
              ? `${stuckRuns} payroll run${stuckRuns === 1 ? "" : "s"} across ${stuckOrgs} organization${stuckOrgs === 1 ? "" : "s"} ${stuckRuns === 1 ? "has" : "have"} been in Review for more than ${stuckDays} day(s).`
              : `No runs have been in Review for more than ${stuckDays} day(s).`}
          </p>
        </div>
        <div className="mt-3">
          <WorkerDataLocked variant="support" title="Which runs are stuck is tenant data">
            <p className="leading-relaxed">
              Individual payroll runs belong to each organization. Contact the tenant, or look at a specific run through
              a Support Access grant the organization approves.
            </p>
          </WorkerDataLocked>
        </div>
      </div>

      <div className="mb-6">
        <h2 className={`${SECTION_LABEL_CLS} mb-3`}>Over Plan Limit (Billable Worker-Months) ({data.bwm_scale_limit_overages.length})</h2>
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
                <tr key={`${row.organization_id}-${row.billing_month}`} className="border-t border-border-light border-l-4 border-l-warning bg-warning-light/30">
                  <td className="px-4 py-3 font-medium text-foreground">{row.organization_name}</td>
                  <td className="px-4 py-3 text-foreground-muted">{formatMonth(row.billing_month)}</td>
                  <td className="px-4 py-3 text-right text-foreground-secondary">{row.bwm_count}</td>
                  <td className="px-4 py-3 text-right text-foreground-muted">{row.plan_limit}</td>
                  <td className="px-4 py-3 text-right font-semibold text-error">+{row.over_by}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.bwm_scale_limit_overages.length === 0 && (
            <div className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-center">
              <ShieldCheck size={22} className="text-success" />
              <p className="text-sm text-foreground-disabled">No organizations currently over their plan limit.</p>
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
        <h2 className={`${SECTION_LABEL_CLS} mb-3`}>BWM / Invoice Mismatches ({data.bwm_invoice_mismatches.length})</h2>
        <p className="text-xs text-foreground-disabled mb-3">
          A billed worker-month quantity on an invoice that does not match the actual counted records for that org and month —
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
                <tr key={row.invoice_id} className="border-t border-border-light border-l-4 border-l-error bg-error-light/30">
                  <td className="px-4 py-3 font-medium text-foreground">{row.organization_name || `Org #${row.organization_id}`}</td>
                  <td className="px-4 py-3 text-foreground-muted">{formatMonth(row.billing_month)}</td>
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
              <ShieldCheck size={22} className="text-success" />
              <p className="text-sm text-foreground-disabled">No invoices whose billed worker-months differ from the counted records.</p>
            </div>
          )}
        </div>
      </div>
      </>}
    </div>
  );
}
