import { useState } from "react";
import { btn, card, input, Messages, Table, useAction } from "../mxShared";
import { draftMxIsnReturn, fileMxIsnReturn, getMxIsnReturn, recordMxIsnOutcome } from "../../../../service/payrollService";
import { DueCell, MarkUnknownButton, money, PromptButton, Status, UnknownActions } from "./authShared";

// State ISN returns (MX-046): one per state × month from the committed ISN
// liability, reconciled employee detail → return → ledger. A filed return is
// never edited — later committed runs produce an amendment.
export default function MXIsnReturnsPanel({ rows, reload }) {
  const { run, error, notice, busy } = useAction(reload);
  const [state, setState] = useState("CDMX");
  const [period, setPeriod] = useState("");
  const [open, setOpen] = useState(null);
  const [detail, setDetail] = useState(null);
  async function show(id) {
    if (open === id) { setOpen(null); setDetail(null); return; }
    setOpen(id);
    setDetail(await getMxIsnReturn(id));
  }
  return (
    <section className={card} data-testid="mx-isn-returns">
      <h3 className="mb-2 text-[14px] font-semibold text-foreground">State ISN returns</h3>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <input className={`${input} w-20`} aria-label="State" value={state} onChange={(e) => setState(e.target.value.toUpperCase())} />
        <input className={input} aria-label="ISN month (YYYY-MM)" placeholder="YYYY-MM" value={period} onChange={(e) => setPeriod(e.target.value)} />
        <button type="button" className={btn} disabled={busy || !state || !/^\d{4}-\d{2}$/.test(period)}
          onClick={() => run(() => draftMxIsnReturn(state, period), "Return drafted from the committed ISN liability.")}>
          Draft / refresh / amend
        </button>
      </div>
      <Messages error={error} notice={notice} />
      <Table rows={rows} empty="No ISN return yet." columns={[
        { key: "stateCode", label: "State" },
        { key: "periodKey", label: "Month", render: (r) => `${r.periodKey}${r.amendmentOfId ? ` · amendment #${r.sequence}` : ""}` },
        { key: "baseTotal", label: "Base", render: (r) => money(r.baseTotal) },
        { key: "amount", label: "ISN", render: (r) => money(r.amount) },
        { key: "due", label: "Due", render: (r) => <DueCell row={r} /> },
        { key: "status", label: "Status", render: (r) => <Status value={r.status} /> },
        { key: "act", label: "", render: (r) => (
          <span className="flex flex-col gap-1">
            <span className="flex flex-wrap gap-1">
              <button type="button" className={btn} onClick={() => show(r.id)}>{open === r.id ? "Hide" : "Reconciliation"}</button>
              {r.status === "DRAFT" && (
                <>
                  <PromptButton label="Record filed…" placeholder="State portal folio"
                    onSubmit={(ref) => run(() => fileMxIsnReturn(r.id, ref), "Filed.")} />
                  <MarkUnknownButton kind="isn-returns" row={r} run={run} />
                </>
              )}
              {r.status === "FILED" && (
                <>
                  <button type="button" className={btn} onClick={() => run(() => recordMxIsnOutcome(r.id, "ACCEPTED"), "Accepted.")}>Accepted (second person)</button>
                  <button type="button" className={btn} onClick={() => run(() => recordMxIsnOutcome(r.id, "REJECTED"), "Rejected.")}>Rejected</button>
                </>
              )}
            </span>
            <UnknownActions kind="isn-returns" row={r} run={run} />
            {open === r.id && detail?.reconciliation && (
              <div className="rounded-lg border border-border p-2 text-[11px]" data-testid="mx-isn-reconciliation">
                Employee detail {money(detail.reconciliation.detailTotal)} · return {money(detail.reconciliation.returnAmount)} ·
                ledger {money(detail.reconciliation.ledgerTotal)} — <Status value={detail.reconciliation.matches ? "RECONCILED" : "OPEN"} />
              </div>
            )}
          </span>
        ) },
      ]} />
    </section>
  );
}
