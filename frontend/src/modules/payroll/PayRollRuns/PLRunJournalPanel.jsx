import { getPlRunJournal } from "../../../service/payrollService";
import { useLoad } from "../../../components/jurisdiction/japan/jpFormat";
import { Table } from "../../../components/jurisdiction/japan/jpShared";

// Poland journal of a PAID run (ZP-PL-ENG-001 §10, Phase 8). Built only from
// the frozen payslips and the employer's own account map (registration
// pl_journal_accounts); debits always equal credits, otherwise the server
// says BLOCKED and why — it is never posted to a guessed account.

export default function PLRunJournalPanel({ runId }) {
  const [journal, error, loading] = useLoad(() => getPlRunJournal(runId));
  return (
    <div className="mt-3 rounded-xl border border-border bg-surface p-4" data-testid="pl-run-journal">
      <p className="text-[13px] font-semibold text-foreground">Poland journal</p>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {loading && <p className="text-[12px] text-foreground-muted">Loading…</p>}
      {journal?.status === "BLOCKED" && <p className="text-[12px] text-error">Blocked — {journal.reason}</p>}
      {journal?.status === "READY" && (
        <>
          <p className="mt-1 text-[12px] text-foreground-muted">Debits {journal.debit} = credits {journal.credit}</p>
          <Table rows={journal.lines} rowKey={(l) => `${l.side}-${l.account}`} empty="No lines."
            columns={[{ label: "Side", key: "side" }, { label: "Account", key: "account" },
              { label: "Amount (PLN)", key: "amount" }, { label: "Memo", key: "memo" }]} />
        </>
      )}
    </div>
  );
}
