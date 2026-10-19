import { useCallback, useEffect, useState } from "react";
import { X } from "lucide-react";
import { confirmMxCfdiRetry, getMxCfdiDocument, queryMxCfdiStatus } from "../../../../service/payrollService";
import MXCancelReplaceDialog from "./MXCancelReplaceDialog";

// One CFDI document: lineage (replaces / replaced by), the append-only event
// timeline and the outbox attempts — never XML (MX-061). For an UNKNOWN stamp
// the only actions are "Query status" and, after a NOT FOUND answer, an
// operator-confirmed retry with a reason (recorded as an event).
export default function MXCfdiDetailDrawer({ docId, onClose }) {
  const [doc, setDoc] = useState(null);
  const [error, setError] = useState(null);
  const [reason, setReason] = useState("");
  const [cancelOpen, setCancelOpen] = useState(false);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let active = true;
    getMxCfdiDocument(docId)
      .then((d) => { if (active) { setDoc(d); setError(null); } })
      .catch((err) => active && setError(err?.message || "The CFDI document could not be loaded."));
    return () => { active = false; };
  }, [docId, tick]);

  async function act(fn) {
    setError(null);
    try {
      await fn();
      reload();
    } catch (err) {
      setError(err?.message || "Refused.");
    }
  }

  const retry = doc?.retry;
  return (
    <div className="fixed inset-0 z-[9999] flex justify-end bg-background/40" role="dialog" aria-label="CFDI document">
      <div className="h-full w-full max-w-xl overflow-y-auto bg-surface p-5 shadow-xl" data-testid="mx-cfdi-drawer">
        <div className="mb-3 flex items-center justify-between">
          <h4 className="text-[14px] font-bold text-foreground">CFDI folio {doc?.folio || "…"}</h4>
          <button type="button" onClick={onClose} aria-label="Close"><X size={16} /></button>
        </div>
        {error && <p className="mb-3 text-[12px] text-error" role="alert">{error}</p>}
        {doc && (
          <>
            <dl className="mb-4 grid grid-cols-2 gap-1 text-[12px]">
              <dt className="text-foreground-muted">Status</dt><dd className="font-semibold">{doc.status}{doc.unknownAction ? ` (${doc.unknownAction})` : ""}</dd>
              <dt className="text-foreground-muted">UUID</dt><dd className="font-mono text-[11px]">{doc.uuid || "—"}</dd>
              <dt className="text-foreground-muted">PAC</dt><dd>{doc.pacProvider} · {doc.pacEnvironment}</dd>
              <dt className="text-foreground-muted">Payload hash</dt><dd className="font-mono text-[11px] break-all">{doc.payloadHash}</dd>
              <dt className="text-foreground-muted">Replaces</dt><dd className="font-mono text-[11px]">{doc.replacesUuid || "—"}</dd>
              <dt className="text-foreground-muted">Replaced by</dt><dd className="font-mono text-[11px]">{doc.replacedByUuid || "—"}</dd>
              <dt className="text-foreground-muted">Cancellation reason</dt><dd>{doc.cancellationReasonCode || "—"}</dd>
            </dl>
            {(doc.status === "UNKNOWN" || doc.status === "CANCEL_REQUESTED") && (
              <div className="mb-4 rounded-[10px] border border-error/40 p-3 text-[12px]" data-testid="mx-cfdi-unknown-actions">
                <p className="mb-2 text-error">
                  The PAC outcome is not known. Query its status first — a retry is never sent blind (MX-062).
                  {retry && ` NOT FOUND answers so far: ${retry.notFoundQueries}.`}
                  {retry && !retry.providerConfig && " No provider rule defines “definitively not found” yet, so a retry needs your explicit confirmation."}
                </p>
                <button type="button" className="mr-2 rounded-[8px] border border-border px-2 py-1 font-semibold"
                  onClick={() => act(() => queryMxCfdiStatus(doc.id))}>Query status</button>
                {doc.status === "UNKNOWN" && doc.unknownAction === "STAMP" && (
                  <span className="mt-2 flex flex-wrap items-center gap-2">
                    <input aria-label="Retry reason" placeholder="Reason for the confirmed retry" value={reason}
                      onChange={(e) => setReason(e.target.value)}
                      className="min-w-[220px] rounded-[8px] border border-border bg-background px-2 py-1" />
                    <button type="button" disabled={!reason.trim() || !retry || retry.notFoundQueries < 1}
                      title={retry && retry.notFoundQueries < 1 ? "Query the status first" : ""}
                      className="rounded-[8px] border border-border px-2 py-1 font-semibold disabled:opacity-40"
                      onClick={() => act(() => confirmMxCfdiRetry(doc.id, reason))}>
                      Confirm retry (same payload, same key)
                    </button>
                  </span>
                )}
              </div>
            )}
            {doc.status === "STAMPED" && (
              <button type="button" className="mb-4 rounded-[8px] border border-border px-2 py-1 text-[12px] font-semibold"
                onClick={() => setCancelOpen(true)}>Cancel / replace…</button>
            )}
            <p className="mb-1 text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Events</p>
            <ol className="mb-4 space-y-1 text-[12px]" data-testid="mx-cfdi-events">
              {doc.events.map((e) => (
                <li key={e.id}><code className="text-[11px]">{e.type}</code>{e.from || e.to ? ` · ${e.from || "—"} → ${e.to || "—"}` : ""}
                  <span className="text-foreground-muted"> · {e.at}</span></li>
              ))}
            </ol>
            <p className="mb-1 text-[11px] font-bold uppercase tracking-widest text-foreground-muted">PAC queue</p>
            <ul className="space-y-1 text-[12px]">
              {doc.outbox.map((o) => (
                <li key={o.id}>{o.action} #{o.attempt} · {o.status}{o.operatorConfirmedById ? " · operator-confirmed" : ""}
                  {o.lastError ? <span className="text-foreground-muted"> · {o.lastError}</span> : null}</li>
              ))}
            </ul>
          </>
        )}
        {cancelOpen && doc && <MXCancelReplaceDialog doc={doc} onClose={() => { setCancelOpen(false); reload(); }} />}
      </div>
    </div>
  );
}
