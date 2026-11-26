import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Download, Loader2, Mail, Receipt, Send } from "lucide-react";

import Drawer from "../Drawer";
import StatusPill from "../StatusPill";
import {
  getBillingEmailLog,
  getOrganizationInvoiceDownload,
  listOrganizationInvoices,
  resendOrganizationInvoice,
} from "../../service/commandCenterService";

// Super Admin view of an organization's invoices and every billing /
// welcome email sent for it (communication_events). organization = null shows
// the platform-wide log (no invoices section).

const EVENT_LABEL = {
  "billing.payment_succeeded": "Payment receipt",
  "billing.invoice_issued": "Invoice",
  "billing.payment_failed": "Payment failed",
  "billing.renewal_upcoming": "Renewal reminder",
  "commercial.organization_created": "Organization created",
  "commercial.evaluation_created": "Evaluation created",
};

const OUTCOME_PILL = {
  sent: { status: "active", label: "Sent" },
  failed: { status: "rejected", label: "Failed" },
  not_delivered: { status: "pending", label: "Not delivered" },
  pending: { status: "pending", label: "Pending" },
  skipped_duplicate: { status: "inactive", label: "Duplicate skipped" },
};

function formatDateTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

const BTN = "inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted disabled:opacity-50";

function InvoiceRow({ organizationId, invoice, onSent }) {
  const [busy, setBusy] = useState(null);
  const [note, setNote] = useState(null);
  const paid = invoice.status === "PAID";

  const download = async () => {
    setBusy("download");
    setNote(null);
    try {
      const links = await getOrganizationInvoiceDownload(organizationId, invoice.id);
      window.open(links.pdfUrl || links.hostedUrl, "_blank", "noopener,noreferrer");
    } catch (err) {
      setNote({ ok: false, text: err.message || "PDF not available." });
    } finally {
      setBusy(null);
    }
  };

  const resend = async (kind) => {
    setBusy(kind);
    setNote(null);
    try {
      const { results = [] } = await resendOrganizationInvoice(organizationId, invoice.id, kind);
      const sent = results.filter((r) => r.outcome === "sent").length;
      const problem = results.find((r) => r.outcome !== "sent");
      setNote(results.length && sent === results.length
        ? { ok: true, text: `Sent to ${[...new Set(results.map((r) => r.recipient))].join(", ")}` }
        : { ok: false, text: results.length ? `${sent}/${results.length} sent. ${problem?.error || problem?.outcome || ""}` : "No billing contact." });
      onSent?.();
    } catch (err) {
      setNote({ ok: false, text: err.message || "Resend failed." });
    } finally {
      setBusy(null);
    }
  };

  const spin = <Loader2 size={13} className="animate-spin" />;
  return (
    <li className="py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm">
          <span className="font-semibold text-foreground">{invoice.currency} {Number(invoice.total).toFixed(2)}</span>
          <span className="ml-2 text-foreground-muted">{formatDateTime(invoice.issued_at)}</span>
          <span className="ml-2"><StatusPill status={paid ? "active" : "pending"} label={invoice.status} /></span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <button type="button" className={BTN} onClick={download} disabled={!!busy}>
            {busy === "download" ? spin : <Download size={13} />} PDF
          </button>
          <button type="button" className={BTN} onClick={() => resend(paid ? "invoice" : "both")} disabled={!!busy}>
            {busy === "invoice" || busy === "both" ? spin : <Send size={13} />} {paid ? "Resend invoice" : "Resend notice"}
          </button>
          {paid && (
            <button type="button" className={BTN} onClick={() => resend("receipt")} disabled={!!busy}>
              {busy === "receipt" ? spin : <Receipt size={13} />} Resend receipt
            </button>
          )}
        </div>
      </div>
      {note && <p className={`mt-1 text-xs ${note.ok ? "text-success" : "text-error"}`}>{note.text}</p>}
    </li>
  );
}

export default function BillingEmailsDrawer({ organization, onClose }) {
  const orgId = organization?.organization_id ?? null;
  const [emails, setEmails] = useState(null);
  const [problems, setProblems] = useState([]);
  const [invoices, setInvoices] = useState(null);
  const [outcome, setOutcome] = useState("");
  const [error, setError] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;
    getBillingEmailLog({ organization_id: orgId, outcome, limit: 200 })
      .then((data) => {
        if (cancelled) return;
        setEmails(data.emails || []);
        setProblems(data.deliveryProblems || []);
      })
      .catch((err) => !cancelled && setError(err.message || "Could not load the email log."));
    if (orgId != null) {
      listOrganizationInvoices(orgId)
        .then((data) => !cancelled && setInvoices(data.invoices || []))
        .catch(() => !cancelled && setInvoices([]));
    }
    return () => { cancelled = true; };
  }, [orgId, outcome, refreshKey]);

  return (
    <Drawer
      title={organization ? `${organization.organization_name} — invoices & emails` : "Billing email log"}
      subtitle="Welcome, receipt, invoice, payment-failed and renewal emails, with delivery status"
      onClose={onClose}
      width="max-w-3xl"
    >
      {problems.length > 0 && (
        <div className="mb-4 rounded-lg border border-warning/40 bg-warning-light px-3 py-2 text-sm text-warning" data-testid="email-delivery-problems">
          <p className="mb-1 flex items-center gap-1.5 font-semibold"><AlertTriangle size={14} /> Email is not reaching inboxes on this server</p>
          <ul className="list-disc pl-5">
            {problems.map((p) => <li key={p}>{p}</li>)}
          </ul>
        </div>
      )}
      {error && <p className="mb-4 rounded-lg bg-error-light px-3 py-2 text-sm text-error">{error}</p>}

      {orgId != null && (
        <section className="mb-6">
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-foreground-muted">Invoices</h4>
          {invoices == null ? (
            <p className="text-sm text-foreground-muted">Loading…</p>
          ) : invoices.length === 0 ? (
            <p className="text-sm text-foreground-muted">No invoices recorded for this organization.</p>
          ) : (
            <ul className="divide-y divide-border-light">
              {invoices.map((inv) => <InvoiceRow key={inv.id} organizationId={orgId} invoice={inv} onSent={refresh} />)}
            </ul>
          )}
        </section>
      )}

      <section>
        <div className="mb-2 flex items-center justify-between gap-2">
          <h4 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-foreground-muted">
            <Mail size={13} /> Email log
          </h4>
          <select
            value={outcome}
            onChange={(e) => setOutcome(e.target.value)}
            className="rounded-lg border border-border bg-surface px-2 py-1 text-xs text-foreground"
            aria-label="Filter by status"
          >
            <option value="">All statuses</option>
            <option value="sent">Sent</option>
            <option value="failed">Failed</option>
            <option value="not_delivered">Not delivered</option>
            <option value="pending">Pending</option>
          </select>
        </div>
        {emails == null ? (
          <p className="text-sm text-foreground-muted">Loading…</p>
        ) : emails.length === 0 ? (
          <p className="text-sm text-foreground-muted">No billing emails recorded.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-foreground-muted">
                <tr>
                  <th className="py-2 pr-3">When</th>
                  {orgId == null && <th className="py-2 pr-3">Organization</th>}
                  <th className="py-2 pr-3">Email</th>
                  <th className="py-2 pr-3">Recipient</th>
                  <th className="py-2 pr-3">Status</th>
                  <th className="py-2">Error</th>
                </tr>
              </thead>
              <tbody>
                {emails.map((e) => {
                  const pill = OUTCOME_PILL[e.outcome] || { status: "inactive", label: e.outcome };
                  return (
                    <tr key={e.id} className="border-t border-border-light align-top">
                      <td className="py-2 pr-3 whitespace-nowrap text-foreground-muted">{formatDateTime(e.createdAt)}</td>
                      {orgId == null && <td className="py-2 pr-3 text-foreground-secondary">{e.organizationName || e.organizationId || "—"}</td>}
                      <td className="py-2 pr-3 text-foreground">{EVENT_LABEL[e.eventType] || e.eventType}</td>
                      <td className="py-2 pr-3 break-all text-foreground-secondary">{e.recipient}</td>
                      <td className="py-2 pr-3 whitespace-nowrap">
                        <StatusPill status={pill.status} label={pill.label} />
                        {e.attempts > 1 && <span className="ml-1 text-foreground-muted">×{e.attempts}</span>}
                      </td>
                      <td className="py-2 text-foreground-muted">{e.error || "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </Drawer>
  );
}
