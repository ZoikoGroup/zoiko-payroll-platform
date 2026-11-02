import { useState } from "react";
import {
  approveJpObligation, getJpAnnualDetermination, getJpBonusReport, listJpObligations, recordJpObligationReceipt,
  submitJpObligation,
} from "../../../service/payrollService";
import { card, useLoad } from "../../../components/jurisdiction/japan/jpFormat";
import { Table } from "../../../components/jurisdiction/japan/jpShared";
import { btn } from "../../../components/jurisdiction/japan/JPRecordSection";
import { formatJpyAuto } from "../../../components/jurisdiction/japan/jpComponentConfig";

// Japan remittances and filings (ZP-JP-ENG-001 §2, §9). A PAID run writes its
// withholding, social-insurance and resident-tax remittances once; each is
// approved by a second person, recorded as made, then receipted. Filing
// previews are JSON only: every submission file is refused until G5.

function errorText(e) {
  const detail = e?.response?.data?.detail;
  return typeof detail === "string" ? detail : "The action failed.";
}

const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px]";

export default function JPObligationsPanel() {
  const [rows, error, loading, reload] = useLoad(() => listJpObligations());
  const [channel, setChannel] = useState({});
  const [receipt, setReceipt] = useState({});
  const [previewInput, setPreviewInput] = useState({ paidOn: "", year: "" });
  const [preview, setPreview] = useState(null);
  const [state, setState] = useState({ busy: false, error: null });
  const act = async (fn) => {
    setState({ busy: true, error: null });
    try {
      await fn();
      setState({ busy: false, error: null });
      reload();
    } catch (e) {
      setState({ busy: false, error: errorText(e) });
    }
  };
  return (
    <section className={card} data-testid="jp-obligations">
      <h3 className="text-[14px] font-semibold text-foreground">Remittances and filings</h3>
      <p className="mb-3 text-[12px] text-foreground-muted">
        Written once when a run is paid. A due date shows &quot;Not signed&quot; when its rule is not yet signed; due dates are
        never moved for holidays until that rule is signed.
      </p>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {state.error && <p role="alert" className="text-[12px] text-error">{state.error}</p>}
      {loading ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        <Table rows={rows} empty="No remittances yet."
          columns={[
            { label: "Type", render: (r) => `${r.obligation_type}${r.municipality_code ? ` · ${r.municipality_code}` : ""}` },
            { label: "Period", key: "period" },
            { label: "Amount", render: (r) => formatJpyAuto(r.amount) },
            { label: "Due", render: (r) => r.due_on || <span className="text-warning">Not signed</span> },
            { label: "Status", key: "status" },
            {
              label: "Actions",
              render: (r) => (
                <div className="flex flex-wrap items-center gap-1">
                  {r.status === "CREATED" && (
                    <button type="button" className={btn} disabled={state.busy} onClick={() => act(() => approveJpObligation(r.id))}>Approve (second user)</button>)}
                  {r.status === "APPROVED" && (
                    <>
                      <input className={`w-28 ${input}`} placeholder="Channel" value={channel[r.id] || ""}
                        onChange={(e) => setChannel((v) => ({ ...v, [r.id]: e.target.value }))} />
                      <button type="button" className={btn} disabled={state.busy || !(channel[r.id] || "").trim()}
                        onClick={() => act(() => submitJpObligation(r.id, channel[r.id]))}>Mark paid</button>
                    </>)}
                  {r.status === "SUBMITTED" && (
                    <>
                      <input className={`w-28 ${input}`} placeholder="Receipt ref" value={receipt[r.id] || ""}
                        onChange={(e) => setReceipt((v) => ({ ...v, [r.id]: e.target.value }))} />
                      <button type="button" className={btn} disabled={state.busy || !(receipt[r.id] || "").trim()}
                        onClick={() => act(() => recordJpObligationReceipt(r.id, true, receipt[r.id]))}>Accepted</button>
                      <button type="button" className={btn} disabled={state.busy}
                        onClick={() => act(() => recordJpObligationReceipt(r.id, false, receipt[r.id] || ""))}>Rejected</button>
                    </>)}
                </div>
              ),
            },
          ]} />
      )}
      <div className="mt-4 flex flex-wrap items-end gap-2">
        <input type="date" className={input} value={previewInput.paidOn}
          onChange={(e) => setPreviewInput((v) => ({ ...v, paidOn: e.target.value }))} aria-label="Bonus paid on" />
        <button type="button" className={btn} disabled={!previewInput.paidOn}
          onClick={() => act(async () => setPreview(await getJpBonusReport(previewInput.paidOn)))}>Bonus report preview</button>
        <input className={`w-20 ${input}`} placeholder="Year" value={previewInput.year}
          onChange={(e) => setPreviewInput((v) => ({ ...v, year: e.target.value.replace(/\D/g, "").slice(0, 4) }))} />
        <button type="button" className={btn} disabled={previewInput.year.length !== 4}
          onClick={() => act(async () => setPreview(await getJpAnnualDetermination(previewInput.year)))}>Annual determination preview</button>
      </div>
      {preview && (
        <pre className="mt-3 max-h-72 overflow-auto rounded-lg bg-surface-muted p-3 text-[11px]" data-testid="jp-filing-preview">
          {JSON.stringify(preview, null, 2)}
        </pre>
      )}
    </section>
  );
}
