import { useState } from "react";
import { btn, card, Messages, Table, useAction } from "../mxShared";
import {
  accrueMxLiabilities, fileMxLiability, getMxLiability, payMxLiability, reconcileMxLiability,
} from "../../../../service/payrollService";
import { DueCell, MarkUnknownButton, money, PromptButton, Status, UnknownActions } from "./authShared";

const SCOPE = (r) => (r.authority === "SAT_ISR" ? "Organisation" : r.stateCode ? `State ${r.stateCode}` : `Registration #${r.registrationId}`);

// Authority liability ledger (B3) — ISR remittance (B6), IMSS, INFONAVIT and
// state ISN, accrued only from committed runs. A payment is recorded evidence
// of a payment made outside Zoiko (bank payment is Phase 10).
export default function MXLiabilitiesPanel({ rows, reload }) {
  const { run, error, notice, busy } = useAction(reload);
  const [open, setOpen] = useState(null);
  const [detail, setDetail] = useState(null);
  async function show(id) {
    if (open === id) { setOpen(null); setDetail(null); return; }
    setOpen(id);
    setDetail(await getMxLiability(id));
  }
  return (
    <section className={card} data-testid="mx-liabilities">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-[14px] font-semibold text-foreground">Authority liabilities (ISR · IMSS · INFONAVIT · ISN)</h3>
        <button type="button" className={btn} disabled={busy} data-testid="mx-accrue"
          onClick={() => run(async () => {
            const out = await accrueMxLiabilities();
            if (out.skipped?.length) throw new Error(`${out.sourcesAdded} row(s) accrued; skipped: ${out.skipped.map((s) => s.code).join(", ")}`);
          }, "Accrued from committed runs.")}>
          Accrue from committed runs
        </button>
      </div>
      <Messages error={error} notice={notice} />
      <Table
        rows={rows}
        empty="Nothing accrued yet."
        columns={[
          { key: "authority", label: "Authority", render: (r) => <span data-testid="mx-liability-row">{r.authority.replace("_", " ")}</span> },
          { key: "scope", label: "Scope", render: SCOPE },
          { key: "periodKey", label: "Month", render: (r) => `${r.periodKey}${r.complementary ? ` · complementary #${r.sequence}` : ""}` },
          { key: "amount", label: "Amount", render: (r) => money(r.amount) },
          { key: "due", label: "Due", render: (r) => <DueCell row={r} /> },
          { key: "status", label: "Status", render: (r) => <Status value={r.status} /> },
          { key: "ref", label: "References", render: (r) => [r.declarationReference, r.paymentReference].filter(Boolean).join(" · ") || "—" },
          { key: "act", label: "", render: (r) => (
            <span className="flex flex-col gap-1">
              <span className="flex flex-wrap gap-1">
                <button type="button" className={btn} onClick={() => show(r.id)}>{open === r.id ? "Hide" : "Sources"}</button>
                {r.status === "ACCRUED" && r.authority !== "ISN" && (
                  <>
                    <PromptButton label="Record filed…" placeholder="Declaration acuse / folio"
                      onSubmit={(ref) => run(() => fileMxLiability(r.id, ref), "Filed.")} />
                    <MarkUnknownButton kind="liabilities" row={r} run={run} />
                  </>
                )}
                {r.status === "FILED" && (
                  <PromptButton label="Record payment…" placeholder="Payment reference (paid outside Zoiko)"
                    onSubmit={(ref) => run(() => payMxLiability(r.id, ref), "Payment recorded.")} />
                )}
                {r.status === "PAID" && (
                  <button type="button" className={btn} onClick={() => run(() => reconcileMxLiability(r.id), "Reconciled.")}>
                    Reconcile (second person)
                  </button>
                )}
              </span>
              <UnknownActions kind="liabilities" row={r} run={run} />
              {open === r.id && detail && (
                <div className="rounded-lg border border-border p-2 text-[11px]" data-testid="mx-liability-sources">
                  {(detail.sources || []).map((s) => (
                    <div key={s.id}>run #{s.runId} · payslip #{s.payslipItemId} · employee #{s.employeeId} · {s.branch} {s.side || ""} · {money(s.amount)}</div>
                  ))}
                </div>
              )}
            </span>
          ) },
        ]}
      />
    </section>
  );
}
