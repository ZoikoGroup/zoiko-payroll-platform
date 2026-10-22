import { useCallback, useEffect, useState } from "react";
import {
  cancelMxPaymentBatch, createMxPaymentBatch, exportMxPaymentWorklist, listMxPaymentBatches, recordMxPaymentOutcome,
  releaseMxPaymentBatch, reissueMxPayments,
} from "../../../service/payrollService";
import { Messages, Table, useAction } from "../../../components/jurisdiction/mexico/mxShared";
import { Badge, MiniForm, Panel } from "../../../components/jurisdiction/mexico/employer/employerShared";

const link = "text-[12px] text-primary underline disabled:opacity-40";

// Salary payments (ZP-MX-ENG-001 §20, Phase 10a). A batch per committed run,
// released by a second person. No bank file layout is saved, so the file is a
// Zoiko WORKLIST to key into online banking (SPEI) — never a bank file, built on
// request, the full CLABE never stored. Each payment's outcome is recorded with
// the bank reference; failed or returned payments are re-issued in a new batch.
export default function MXPaymentsPanel() {
  const [batches, setBatches] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [refs, setRefs] = useState({});
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  const { run, error, notice, busy } = useAction(reload);

  useEffect(() => {
    let active = true;
    listMxPaymentBatches()
      .then((b) => { if (active) { setBatches(b); setLoadError(null); } })
      .catch((e) => active && setLoadError(e?.message || "The payment batches could not be loaded."));
    return () => { active = false; };
  }, [tick]);

  const outcome = (item, value) => {
    const ref = refs[item.id] || "";
    return run(() => recordMxPaymentOutcome(item.id, {
      outcome: value, reference: ref || null,
      reason: value === "RETURNED" || value === "FAILED" ? `Recorded from the Compliance Centre (${ref})` : null,
    }), `Recorded ${value}.`);
  };

  return (
    <Panel title="Salary payments" testId="mx-payments"
      hint="The file is a Zoiko worklist to key into your online banking — not a bank file. Record each payment's outcome with its SPEI reference.">
      {loadError && <p className="text-[12px] text-error" role="alert">{loadError}</p>}
      <Messages error={error} notice={notice} />
      {(batches || []).map((b) => (
        <div key={b.id} className="flex flex-col gap-2 rounded-lg border border-border p-3" data-testid="mx-payment-batch">
          <p className="flex flex-wrap items-center gap-2 text-[12px] text-foreground-muted">
            Batch #{b.id} · run #{b.runId}{b.reissueOfBatchId ? ` · re-issue of #${b.reissueOfBatchId}` : ""} · {b.itemCount} payment(s) · {b.totalAmount} MXN ·
            <Badge value={b.status} /> {b.exports ? `· worklist built ${b.exports}×` : ""}
          </p>
          <Table rows={b.items} rowKey={(i) => i.id} columns={[
            { key: "employeeId", label: "Employee" },
            { key: "clabeLast4", label: "CLABE", render: (i) => `•••• ${i.clabeLast4}` },
            { key: "amount", label: "Amount" },
            { key: "status", label: "Status", render: (i) => <Badge value={i.status} /> },
            { key: "reference", label: "Reference", render: (i) => i.reference || "—" },
            { key: "act", label: "", render: (i) => (["PENDING", "UNKNOWN"].includes(i.status) && ["RELEASED", "CLOSED"].includes(b.status) ? (
              <span className="flex flex-wrap items-center gap-2">
                <input aria-label={`Reference ${i.id}`} placeholder="SPEI reference" className="rounded border border-border px-1 text-[12px]"
                  value={refs[i.id] || ""} onChange={(e) => setRefs((s) => ({ ...s, [i.id]: e.target.value }))} />
                {["SETTLED", "RETURNED", "FAILED", "UNKNOWN"].map((o) => (
                  <button key={o} type="button" className={link} disabled={busy} onClick={() => outcome(i, o)}>{o.toLowerCase()}</button>
                ))}
              </span>
            ) : (i.reissuedByItemId ? `re-issued as #${i.reissuedByItemId}` : "")) },
          ]} />
          <span className="flex flex-wrap gap-3">
            {b.status === "DRAFT" && (
              <>
                <button type="button" className={link} disabled={busy} onClick={() => run(() => releaseMxPaymentBatch(b.id), "Released.")}>
                  Release (another person)
                </button>
                <button type="button" className="text-[12px] text-foreground-muted underline" disabled={busy}
                  onClick={() => run(() => cancelMxPaymentBatch(b.id, "Cancelled from the Compliance Centre"), "Cancelled.")}>Cancel</button>
              </>
            )}
            {["RELEASED", "CLOSED"].includes(b.status) && (
              <button type="button" className={link} disabled={busy}
                onClick={() => run(() => exportMxPaymentWorklist(b.id), "Worklist downloaded — it is not a bank file.")}>
                Download worklist
              </button>
            )}
            {b.items.some((i) => ["FAILED", "RETURNED"].includes(i.status) && !i.reissuedByItemId) && (
              <button type="button" className={link} disabled={busy} onClick={() => run(() => reissueMxPayments(b.id), "Re-issue batch created.")}>
                Re-issue failed / returned
              </button>
            )}
          </span>
        </div>
      ))}
      <MiniForm
        testId="mx-new-payment-batch" submitLabel="Build payment batch" busy={busy}
        fields={[{ key: "runId", label: "Committed run id", required: true }]}
        onSubmit={(s) => run(() => createMxPaymentBatch(Number(s.runId)), "Batch built — another person releases it.")}
      />
    </Panel>
  );
}
