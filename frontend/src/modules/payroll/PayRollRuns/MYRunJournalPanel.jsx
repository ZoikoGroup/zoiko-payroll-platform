import { getMyRunJournal } from "../../../service/payrollService";
import { useLoad } from "../../../components/jurisdiction/japan/jpFormat";
import { Table } from "../../../components/jurisdiction/japan/jpShared";

// Malaysia journal of a PAID run (ZP-MY-ENG-001 Phase 9). Built only from the
// frozen payslips and the employer's own account map (registration
// my_journal_accounts); debits always equal credits, otherwise the server says
// BLOCKED and why — it is never posted to a guessed account. Net pay held
// under a tax-clearance hold is still net pay payable (owed, not deducted).

export default function MYRunJournalPanel({ runId }) {
  const [journal, error, loading] = useLoad(() => getMyRunJournal(runId));
  return (
    <div className="mt-3 rounded-xl border border-border bg-surface p-4" data-testid="my-run-journal">
      <p className="text-[13px] font-semibold text-foreground">Malaysia journal</p>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {loading && <p className="text-[12px] text-foreground-muted">Loading…</p>}
      {journal?.status === "BLOCKED" && <p className="text-[12px] text-error">Blocked — {journal.reason}</p>}
      {journal?.status === "READY" && (
        <>
          <p className="mt-1 text-[12px] text-foreground-muted">Debits {journal.debit} = credits {journal.credit}</p>
          <Table rows={journal.lines} rowKey={(l) => `${l.side}-${l.account}`} empty="No lines."
            columns={[{ label: "Side", key: "side" }, { label: "Account", key: "account" },
              { label: "Amount (RM)", key: "amount" }, { label: "Memo", key: "memo" }]} />
        </>
      )}
    </div>
  );
}
