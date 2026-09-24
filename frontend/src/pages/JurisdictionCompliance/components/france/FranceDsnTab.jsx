import { useEffect, useState } from "react";
import { Send, Inbox, AlertTriangle, RefreshCcw } from "lucide-react";
import { listFranceDsnSubmissions, listFranceDsnOutboxItems } from "../../../../service/superAdminService";
import { describeLoadError } from "../../../../service/errorClassification";
import { DSN_STATUS_CHIP, OUTBOX_STATUS_CHIP } from "./franceOverviewSummaries";

// Read-only DSN transport / CRM diagnostics (FR-032/FR-033) for the
// selected organization. DSN SUBMISSIONS ARE OPENED BY THE ORG ITSELF via
// /api/payroll/france/dsn-submissions (payrollService) — the Super Admin
// surface below is the audit/diagnostics view the authority holds, exactly
// as the backend split intends.
export default function FranceDsnTab({ organizationId }) {
  const [state, setState] = useState({ loading: true, submissions: [], outbox: [], error: null });

  useEffect(() => {
    if (!organizationId) {
      setState({ loading: false, submissions: [], outbox: [], error: null });
      return;
    }
    let cancelled = false;
    setState({ loading: true, submissions: [], outbox: [], error: null });
    Promise.all([
      listFranceDsnSubmissions({ organizationId }),
      listFranceDsnOutboxItems({ organizationId }),
    ])
      .then(([submissions, outbox]) => {
        if (cancelled) return;
        setState({
          loading: false,
          submissions: Array.isArray(submissions) ? submissions : [],
          outbox: Array.isArray(outbox) ? outbox : [],
          error: null,
        });
      })
      .catch((err) => {
        if (!cancelled) setState({ loading: false, error: describeLoadError(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [organizationId]);

  if (!organizationId) {
    return <p className="py-10 text-sm text-foreground-muted">Select an organization to inspect its DSN filings.</p>;
  }
  if (state.loading) {
    return <p className="py-10 text-sm text-foreground-disabled">Loading DSN diagnostics…</p>;
  }
  if (state.error) {
    return (
      <p className="py-10 text-sm text-foreground-muted">
        <AlertTriangle size={14} className="inline mr-1" /> {state.error}
      </p>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2">
        <Send size={16} className="text-primary" />
        <h2 className="text-sm font-bold text-foreground">DSN submissions (read-only diagnostics)</h2>
      </div>
      <p className="text-[11px] text-foreground-disabled">
        The employer opens each filing and drives its lifecycle from the org payroll surface (/payroll/france/dsn-submissions).
        This Super Admin view is the transport/CRM audit the authority reviews.
      </p>

      {state.submissions.length ? (
        <div className="rounded-lg border border-border bg-surface p-4">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-foreground-muted">
                <th className="py-1 pr-3 font-semibold">Period</th>
                <th className="py-1 pr-3 font-semibold">Due</th>
                <th className="py-1 pr-3 font-semibold">Release / version</th>
                <th className="py-1 pr-3 font-semibold">TRA</th>
                <th className="py-1 pr-3 font-semibold">Payment</th>
                <th className="py-1 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody>
              {state.submissions.map((d) => (
                <tr key={d.id} className="border-t border-border align-top">
                  <td className="py-2 pr-3">
                    {d.periodStart} → {d.periodEnd}
                    {d.validationErrors?.length ? (
                      <div className="mt-1 text-amber-700">
                        {d.validationErrors.map((e) => (
                          <p key={e}>· {e}</p>
                        ))}
                      </div>
                    ) : null}
                  </td>
                  <td className="py-2 pr-3">{d.dueDate}</td>
                  <td className="py-2 pr-3">
                    <p>{d.releaseRef}</p>
                    <p className="text-foreground-disabled">{d.dsnVersion} · {d.payloadHash?.slice(0, 10)}…</p>
                    {d.blockedReason ? <p className="mt-0.5 text-warning">{d.blockedReason}</p> : null}
                  </td>
                  <td className="py-2 pr-3">{d.technicalAck || "—"}</td>
                  <td className="py-2 pr-3">{d.paymentState || "—"}</td>
                  <td className="py-2">
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${DSN_STATUS_CHIP[d.status] || "bg-surface-muted text-foreground-muted"}`}>
                      {d.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="rounded-lg border border-border bg-surface p-4 text-xs text-foreground-muted">
          No DSN submissions opened for this organization yet.
        </div>
      )}

      <div className="flex items-center gap-2 pt-2">
        <Inbox size={16} className="text-primary" />
        <h2 className="text-sm font-bold text-foreground">DSN outbox (durable idempotent actions)</h2>
      </div>
      {state.outbox.length ? (
        <div className="rounded-lg border border-border bg-surface p-4">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-foreground-muted">
                <th className="py-1 pr-3 font-semibold">Submission</th>
                <th className="py-1 pr-3 font-semibold">Action</th>
                <th className="py-1 pr-3 font-semibold">Idempotency key</th>
                <th className="py-1 pr-3 font-semibold">Attempts</th>
                <th className="py-1 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody>
              {state.outbox.map((o) => (
                <tr key={o.id} className="border-t border-border">
                  <td className="py-1.5 pr-3">#{o.submissionId}</td>
                  <td className="py-1.5 pr-3 font-medium text-foreground">{o.action}</td>
                  <td className="py-1.5 pr-3 text-foreground-disabled">{o.idempotencyKey?.slice(0, 12)}…</td>
                  <td className="py-1.5 pr-3">{o.attempts}</td>
                  <td className="py-1.5">
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${OUTBOX_STATUS_CHIP[o.status] || "bg-surface-muted text-foreground-muted"}`}>
                      {o.status}
                    </span>
                    {o.lastError ? <p className="mt-0.5 text-red-600">{o.lastError}</p> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="rounded-lg border border-border bg-surface p-4 text-xs text-foreground-muted">
          No outbox actions enqueued yet.
        </div>
      )}

      <p className="flex items-center gap-1.5 text-[11px] text-foreground-disabled">
        <RefreshCcw size={12} />
        Select a period from the readiness overview to preflight the next filing (FR A11 gate H).
      </p>
    </div>
  );
}