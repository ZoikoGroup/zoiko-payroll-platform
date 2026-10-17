import { useCallback, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { acknowledgeMxPreflight, getMxRunPreflight, resetMxRun } from "../../../../service/payrollService";

// Mexico run preflight (spec §13 stage 1, MX-001 / MX-036). Exceptions are
// written by generation, one per blocking reason; the server refuses approval
// while any BLOCK or failed payslip remains, or a WARN is unacknowledged. A
// BLOCK can never be acknowledged (D8) — fix its cause and recalculate.
const TONE = { BLOCK: "text-error", WARN: "text-warning" };

export default function MXRunPreflightPanel({ runId, runStatus, onChanged }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [notes, setNotes] = useState({});
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const [tick, setTick] = useState(0);
  const load = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let active = true;
    getMxRunPreflight(runId)
      .then((d) => { if (active) { setData(d); setError(null); } })
      .catch((err) => active && setError(err?.message || "Mexico preflight could not be loaded."));
    return () => { active = false; };
  }, [runId, tick]);

  async function acknowledge(id) {
    setBusy(true);
    try {
      await acknowledgeMxPreflight(runId, id, notes[id] || "");
      load();
    } catch (err) {
      setError(err?.message || "The acknowledgement was refused.");
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    setBusy(true);
    try {
      await resetMxRun(runId, reason);
      setReason("");
      load();
      onChanged?.();
    } catch (err) {
      setError(err?.message || "The reset was refused.");
    } finally {
      setBusy(false);
    }
  }

  if (!data && !error) {
    return (
      <div className="mb-5 flex items-center gap-2 text-[12px] text-foreground-muted" role="status">
        <Loader2 size={14} className="animate-spin" /> Loading Mexico preflight…
      </div>
    );
  }
  const exceptions = data?.exceptions || [];
  return (
    <section className="mb-5 rounded-[18px] border border-border p-5" aria-labelledby="mx-preflight-heading"
      data-testid="mx-run-preflight">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h4 id="mx-preflight-heading" className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">
          Mexico preflight &amp; exceptions
        </h4>
        {data && (
          <p className="text-[12px] text-foreground-muted">
            {data.blocking} blocking · {data.unacknowledgedWarnings} warning(s) to acknowledge · {data.failedItems} of{" "}
            {data.items} payslip(s) failed
          </p>
        )}
      </div>
      {error && <p className="mb-3 text-[12px] text-error" role="alert">{error}</p>}
      {data && (data.blocking > 0 || data.failedItems > 0) && (
        <p className="mb-3 text-[12px] text-error">
          Approval is refused until every BLOCK is fixed and the payslips are recalculated.
        </p>
      )}
      {exceptions.length === 0 ? (
        <p className="text-[12px] text-foreground-muted">No preflight exceptions.</p>
      ) : (
        <ul className="space-y-2">
          {exceptions.map((e) => (
            <li key={e.id} className="rounded-[12px] border border-border px-3 py-2 text-[12px]" data-testid="mx-preflight-row">
              <span className={`font-semibold ${TONE[e.severity] || "text-foreground"}`}>{e.severity}</span>
              <span className="text-foreground"> · <code className="text-[11px]">{e.code}</code> · {e.message}</span>
              <span className="text-foreground-muted"> · employee #{e.employeeId}</span>
              {e.severity === "WARN" && !e.acknowledgedAt && (
                <span className="mt-1 flex flex-wrap items-center gap-2">
                  <input aria-label={`Acknowledgement note for ${e.code}`} value={notes[e.id] || ""}
                    onChange={(ev) => setNotes({ ...notes, [e.id]: ev.target.value })}
                    className="rounded-[8px] border border-border bg-background px-2 py-1 text-[12px]" />
                  <button type="button" disabled={busy || !(notes[e.id] || "").trim()} onClick={() => acknowledge(e.id)}
                    className="rounded-[8px] border border-border px-2 py-1 text-[12px] font-semibold disabled:opacity-40">
                    Acknowledge
                  </button>
                </span>
              )}
              {e.acknowledgedAt && <p className="mt-0.5 text-foreground-muted">Acknowledged: {e.acknowledgementNote}</p>}
            </li>
          ))}
        </ul>
      )}
      {runStatus === "Approved" && (
        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border pt-3">
          <input aria-label="Reset reason" placeholder="Reason for resetting to Review" value={reason}
            onChange={(ev) => setReason(ev.target.value)}
            className="min-w-[260px] rounded-[8px] border border-border bg-background px-2 py-1 text-[12px]" />
          <button type="button" disabled={busy || !reason.trim()} onClick={reset}
            className="rounded-[8px] border border-border px-3 py-1 text-[12px] font-semibold disabled:opacity-40">
            Reset to Review
          </button>
          <span className="text-[11px] text-foreground-muted">
            Removes this run&apos;s committed ledgers. Refused once a CFDI, authority filing or bank instruction has acted on it.
          </span>
        </div>
      )}
    </section>
  );
}
