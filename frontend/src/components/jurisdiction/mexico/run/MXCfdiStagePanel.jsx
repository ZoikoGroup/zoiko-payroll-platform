import { useCallback, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { generateMxCfdi, getMxRunCfdi, processMxCfdiOutbox } from "../../../../service/payrollService";
import MXCfdiDetailDrawer from "./MXCfdiDetailDrawer";

// Mexico run stage 6 — CFDI 4.0 + Nómina 1.2 (spec §13, MX-016/017/062).
// Only a committed run can be stamped; the server lists every precondition
// that is not met. An UNKNOWN document has no "retry" here — only its
// detail drawer can query the PAC and, after a NOT_FOUND answer, record an
// operator-confirmed retry with the same payload and idempotency key.
const TONE = { STAMPED: "text-success", UNKNOWN: "text-error", REJECTED: "text-error", VOIDED: "text-foreground-muted" };

export default function MXCfdiStagePanel({ runId }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [refused, setRefused] = useState(false);
  const [busy, setBusy] = useState(false);
  const [openDoc, setOpenDoc] = useState(null);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let active = true;
    getMxRunCfdi(runId)
      .then((d) => { if (active) { setData(d); setError(null); } })
      .catch((err) => {
        if (!active) return;
        // 403 = Mexico dormant (or not a Mexican org): the run's preflight panel
        // already shows that refusal, so the CFDI stage is not rendered at all.
        if (err?.status === 403) setRefused(true);
        else setError(err?.message || "Mexico CFDI could not be loaded.");
      });
    return () => { active = false; };
  }, [runId, tick]);

  async function act(fn) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      reload();
    } catch (err) {
      setError(err?.message || "The CFDI action was refused.");
    } finally {
      setBusy(false);
    }
  }

  if (refused) return null;
  if (!data && !error) {
    return (
      <div className="mb-5 flex items-center gap-2 text-[12px] text-foreground-muted" role="status">
        <Loader2 size={14} className="animate-spin" /> Loading Mexico CFDI…
      </div>
    );
  }
  const docs = data?.documents || [];
  const unknown = docs.filter((d) => d.status === "UNKNOWN");
  return (
    <section className="mb-5 rounded-[18px] border border-border p-5" data-testid="mx-cfdi-stage" aria-labelledby="mx-cfdi-heading">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h4 id="mx-cfdi-heading" className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">
          Mexico CFDI 4.0 + Nómina 1.2
        </h4>
        {data && <p className="text-[12px] text-foreground-muted">{data.summary?.detail}</p>}
      </div>
      {error && <p className="mb-3 text-[12px] text-error" role="alert">{error}</p>}
      {data && !data.ready && (
        <ul className="mb-3 space-y-1 text-[12px]" data-testid="mx-cfdi-preflight">
          {data.reasons.map((r) => (
            <li key={r.code + r.message}><span className="font-semibold text-error">BLOCK</span> · <code className="text-[11px]">{r.code}</code> · {r.message}</li>
          ))}
        </ul>
      )}
      {unknown.length > 0 && (
        <p className="mb-3 rounded-[10px] border border-error/40 px-3 py-2 text-[12px] text-error" role="alert" data-testid="mx-cfdi-unknown-banner">
          {unknown.length} document(s) UNKNOWN — the PAC outcome is not known. Nothing is resent automatically: open the
          document, query its status, and only after a NOT FOUND answer may an admin confirm a retry (same payload, same key).
        </p>
      )}
      <div className="mb-3 flex flex-wrap gap-2">
        <button type="button" disabled={busy || !data?.ready} onClick={() => act(() => generateMxCfdi(runId))}
          title={data?.ready ? "" : "Blocked — see the reasons above"}
          className="rounded-[10px] border border-border px-3 py-1.5 text-[12px] font-semibold disabled:opacity-40">
          Generate CFDI
        </button>
        <button type="button" disabled={busy || docs.length === 0} onClick={() => act(() => processMxCfdiOutbox())}
          className="rounded-[10px] border border-border px-3 py-1.5 text-[12px] font-semibold disabled:opacity-40">
          Process PAC queue
        </button>
      </div>
      {docs.length === 0 ? (
        <p className="text-[12px] text-foreground-muted">No CFDI documents for this run.</p>
      ) : (
        <table className="w-full max-w-3xl text-[12px]">
          <thead><tr className="text-left text-foreground-muted"><th className="py-1">Folio</th><th>Payslip</th><th>Status</th><th>UUID</th><th /></tr></thead>
          <tbody>
            {docs.map((d) => (
              <tr key={d.id} className="border-b border-border/50" data-testid="mx-cfdi-row">
                <td className="py-1">{d.series ? `${d.series}-` : ""}{d.folio}</td>
                <td>#{d.payslipItemId}</td>
                <td className={`font-semibold ${TONE[d.status] || "text-foreground"}`}>{d.status}</td>
                <td className="font-mono text-[11px]">{d.uuid || "—"}</td>
                <td><button type="button" className="text-primary underline" onClick={() => setOpenDoc(d.id)}>Details</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {openDoc && <MXCfdiDetailDrawer docId={openDoc} onClose={() => { setOpenDoc(null); reload(); }} />}
    </section>
  );
}
