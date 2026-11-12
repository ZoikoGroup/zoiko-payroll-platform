import { useState } from "react";
import {
  approveBePaymentBatch, createBePaymentBatch, downloadBePaymentFile, listBePaymentBatches, reconcileBePaymentBatch,
  recordBePaymentBankResult, submitBePaymentBatch,
} from "../../../service/payrollService";
import { useLoad } from "../../../components/jurisdiction/japan/jpFormat";
import { btn } from "../../../components/jurisdiction/japan/JPRecordSection";
import { errorText } from "../../../components/jurisdiction/new_zealand/nzOrgOptions";

// Belgium salary payment (ZP-BE-ENG-001 D13; Block B3): a SEPA pain.001 batch of
// the committed run's Belgian payslips, built by the shared SEPA builder. A
// SECOND person approves it before the file is released or submitted. Amounts
// are the frozen net pay — never editable here; IBANs are shown masked.

export default function BEPaymentPanel({ runId }) {
  const [batches, error, loading, reload] = useLoad(() => listBePaymentBatches(runId));
  const [state, setState] = useState({ busy: false, error: null, notice: null });
  const act = async (fn, notice) => {
    setState({ busy: true, error: null, notice: null });
    try {
      await fn();
      setState({ busy: false, error: null, notice });
      reload();
    } catch (e) {
      setState({ busy: false, error: errorText(e), notice: null });
    }
  };
  const live = (batches || []).filter((b) => !["REJECTED", "RETURNED"].includes(b.status));
  return (
    <div className="mt-3 rounded-xl border border-border bg-surface p-4" data-testid="be-payment-panel">
      <p className="text-[13px] font-semibold text-foreground">Belgium salary payment</p>
      <p className="text-[12px] text-foreground-muted">
        Belgian payslips are paid only through this batch (never the generic bank file).
      </p>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {loading && <p className="text-[12px] text-foreground-muted">Loading…</p>}
      {live.length === 0 && (
        <button type="button" className={`${btn} mt-2`} disabled={state.busy}
          onClick={() => act(() => createBePaymentBatch(runId, {}), "Batch built — a second person must approve it.")}>
          Build payment batch
        </button>
      )}
      <ul className="mt-2 space-y-2">
        {(batches || []).map((b) => (
          <li key={b.id} className="flex flex-wrap items-center gap-2 text-[12px]" data-testid={`be-payment-batch-${b.id}`}>
            <span className="font-mono">{b.messageId}</span>
            <span className="font-semibold">{b.status}</span>
            {b.status === "DRAFT" && (
              <button type="button" className={btn} disabled={state.busy}
                onClick={() => act(() => approveBePaymentBatch(b.id), "Batch approved.")}>Approve</button>
            )}
            {b.status !== "DRAFT" && (
              <button type="button" className={btn} disabled={state.busy}
                onClick={() => act(() => downloadBePaymentFile(b.id), "File downloaded.")}>Download file</button>
            )}
            {b.status === "APPROVED" && (
              <button type="button" className={btn} disabled={state.busy}
                onClick={() => act(() => submitBePaymentBatch(b.id), "Marked as submitted.")}>Mark submitted</button>
            )}
            {["SUBMITTED", "UNKNOWN"].includes(b.status) && ["ACCEPTED", "REJECTED"].map((outcome) => (
              <button key={outcome} type="button" className={btn} disabled={state.busy}
                onClick={() => act(() => recordBePaymentBankResult(b.id, outcome), `Bank result ${outcome.toLowerCase()}.`)}>
                Bank {outcome.toLowerCase()}
              </button>
            ))}
            {b.status === "ACCEPTED" && (
              <button type="button" className={btn} disabled={state.busy}
                onClick={() => act(() => reconcileBePaymentBatch(b.id), "Reconciled.")}>Reconcile</button>
            )}
          </li>
        ))}
      </ul>
      {state.error && <p role="alert" className="mt-2 text-[12px] text-error">{state.error}</p>}
      {state.notice && <p role="status" className="mt-2 text-[12px] text-success">{state.notice}</p>}
    </div>
  );
}
