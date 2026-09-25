import { Send, Inbox, AlertTriangle } from "lucide-react";
import StatusPill from "../../StatusPill";
import { listFranceDsnSubmissions, listFranceDsnOutboxItems } from "../../../service/superAdminService";
import { loadErrorText } from "../../../service/errorClassification";
import { DSN_STATUS_TONE, OUTBOX_STATUS_TONE } from "./franceStatutoryConfig";
import { useFranceOrgData } from "./useFranceOrgData";

const loadAll = (params) => Promise.all([listFranceDsnSubmissions(params), listFranceDsnOutboxItems(params)])
  .then(([submissions, outbox]) => ({ submissions: submissions || [], outbox: outbox || [] }));

function crmSummary(crm) {
  if (!crm) return "—";
  if (Array.isArray(crm.anomalies)) return crm.anomalies.length ? `${crm.anomalies.length} anomaly(ies)` : "No anomaly";
  return "Received";
}

// Read-only DSN transport / CRM diagnostics (FR-032/FR-033). The employer
// opens and drives each filing from the org payroll surface; here the four
// lifecycle signals are shown SEPARATELY — transport acknowledgement,
// business CRM, payment settlement, and the lifecycle status — never one
// merged "status". Authority states can only be recorded with evidence and
// UNKNOWN is reconciled, never replayed (enforced by the backend).
export default function FranceDsnDiagnosticsPanel({ organizationId }) {
  const { data, error, loading } = useFranceOrgData(organizationId, loadAll);

  if (!organizationId) {
    return <p className="py-10 text-xs text-foreground-muted">Select a France organization to inspect its DSN filings.</p>;
  }
  if (loading) {
    return <p className="py-8 text-center text-xs text-foreground-disabled">Loading DSN diagnostics…</p>;
  }
  if (error) {
    return (
      <p className="py-8 text-center text-xs text-foreground-muted">
        <AlertTriangle size={14} className="inline mr-1" /> {loadErrorText(error)}
      </p>
    );
  }
  const state = data;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-1.5 text-sm font-bold text-foreground">
            <Send size={15} className="text-primary" /> DSN submissions (read-only diagnostics)
          </h2>
          <p className="mt-0.5 text-xs text-foreground-muted">
            The employer opens each filing and drives its lifecycle from the org payroll surface (/payroll/france/dsn-submissions).
          </p>
        </div>
      </div>

      {state.submissions.length ? (
        <div className="overflow-x-auto rounded-xl border border-border bg-surface">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border-light text-left text-foreground-muted">
                <th className="px-4 py-2 font-semibold">Period</th>
                <th className="px-4 py-2 font-semibold">Due</th>
                <th className="px-4 py-2 font-semibold">Release / version</th>
                <th className="px-4 py-2 font-semibold">Transport ack</th>
                <th className="px-4 py-2 font-semibold">Business CRM</th>
                <th className="px-4 py-2 font-semibold">Payment</th>
                <th className="px-4 py-2 font-semibold">Lifecycle</th>
              </tr>
            </thead>
            <tbody>
              {state.submissions.map((d) => (
                <tr key={d.id} className="border-b border-border-light last:border-0 align-top">
                  <td className="px-4 py-2.5">
                    <span className="font-mono tabular-nums">{d.periodStart} → {d.periodEnd}</span>
                    {d.validationErrors?.length ? (
                      <div className="mt-1 text-warning">
                        {d.validationErrors.map((e) => (
                          <p key={e}>· {e}</p>
                        ))}
                      </div>
                    ) : null}
                  </td>
                  <td className="px-4 py-2.5 font-mono tabular-nums">{d.dueDate}</td>
                  <td className="px-4 py-2.5">
                    <p>{d.releaseRef}</p>
                    <p className="text-foreground-disabled">{d.dsnVersion} · {d.payloadHash?.slice(0, 10)}…</p>
                    {d.correctionOfId ? <p className="text-foreground-muted">Correction of #{d.correctionOfId}</p> : null}
                    {d.blockedReason ? <p className="mt-0.5 text-warning">{d.blockedReason}</p> : null}
                  </td>
                  <td className="px-4 py-2.5">{d.technicalAck || "—"}</td>
                  <td className="px-4 py-2.5">{crmSummary(d.businessCrm)}</td>
                  <td className="px-4 py-2.5">{d.paymentState || "—"}</td>
                  <td className="px-4 py-2.5">
                    <StatusPill status={DSN_STATUS_TONE[d.status] || "inactive"} label={d.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="rounded-xl border border-dashed border-border bg-surface-muted px-4 py-8 text-center text-xs text-foreground-disabled">
          No DSN submissions opened for this organization yet.
        </div>
      )}

      <div className="flex items-start justify-between gap-3 pt-1">
        <div>
          <h2 className="flex items-center gap-1.5 text-sm font-bold text-foreground">
            <Inbox size={15} className="text-primary" /> DSN outbox (durable idempotent actions)
          </h2>
          <p className="mt-0.5 text-xs text-foreground-muted">Enqueued transport actions and their delivery state.</p>
        </div>
      </div>

      {state.outbox.length ? (
        <div className="overflow-x-auto rounded-xl border border-border bg-surface">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border-light text-left text-foreground-muted">
                <th className="px-4 py-2 font-semibold">Submission</th>
                <th className="px-4 py-2 font-semibold">Action</th>
                <th className="px-4 py-2 font-semibold">Idempotency key</th>
                <th className="px-4 py-2 font-semibold">Attempts</th>
                <th className="px-4 py-2 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody>
              {state.outbox.map((o) => (
                <tr key={o.id} className="border-b border-border-light last:border-0">
                  <td className="px-4 py-2.5 font-mono text-foreground-secondary">#{o.submissionId}</td>
                  <td className="px-4 py-2.5 font-medium text-foreground">{o.action}</td>
                  <td className="px-4 py-2.5 font-mono text-foreground-disabled">{o.idempotencyKey?.slice(0, 12)}…</td>
                  <td className="px-4 py-2.5 tabular-nums">{o.attempts}</td>
                  <td className="px-4 py-2.5">
                    <StatusPill status={OUTBOX_STATUS_TONE[o.status] || "inactive"} label={o.status} />
                    {o.lastError ? <p className="mt-0.5 text-error">{o.lastError}</p> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="rounded-xl border border-dashed border-border bg-surface-muted px-4 py-8 text-center text-xs text-foreground-disabled">
          No outbox actions enqueued yet.
        </div>
      )}

      <p className="text-[11px] text-foreground-disabled">
        This Super Admin view is the transport/CRM audit the authority reviews. Preflight of a filing happens inside the
        org&apos;s own DSN submission flow (gate H), not here — there is no period-selector linkage on this screen.
      </p>
    </div>
  );
}