import { useState } from "react";
import {
  approveNzRunException, getNzRunJournal, listNzRunExceptions, rejectNzRunException, requestNzRunException,
} from "../../../service/payrollService";
import { useLoad } from "../../../components/jurisdiction/japan/jpFormat";
import { Table } from "../../../components/jurisdiction/japan/jpShared";
import { btn } from "../../../components/jurisdiction/japan/JPRecordSection";
import { errorText } from "../../../components/jurisdiction/new_zealand/nzOrgOptions";

// New Zealand run exceptions and journal (ZP-NZ-ENG-001 Phase 8, D-P8-1).
// Only a child-support shortfall can be approved — by a second user, with a
// reason, and only for the calculation as it stands (a recalculation makes
// the approval stale). A minimum-wage failure is never approvable: fix the
// payslip. The journal is shown for a PAID run, or why it is blocked.

const APPROVABLE = ["NZ_CS_SHORTFALL"];
const ask = (message) => {
  const value = window.prompt(message);
  return value && value.trim() ? value.trim() : null;
};

export default function NZRunFilingPanel({ runId, items = [], paid = false }) {
  const [rows, loadError, loading, reload] = useLoad(() => listNzRunExceptions(runId));
  const [journal, journalError] = useLoad(() => (paid ? getNzRunJournal(runId) : Promise.resolve(null)));
  const [state, setState] = useState({ busy: false, error: null, notice: null });

  const run = async (fn, notice) => {
    setState({ busy: true, error: null, notice: null });
    try {
      await fn();
      setState({ busy: false, error: null, notice });
      reload();
    } catch (err) {
      setState({ busy: false, error: errorText(err), notice: null });
    }
  };

  const open = items.flatMap((item) => ((item.nzCalculationSnapshot?.exceptions) || [])
    .filter((e) => APPROVABLE.includes(e.code)).map((e) => ({ item, code: e.code })));

  return (
    <div className="mt-3 rounded-xl border border-border bg-surface p-4" data-testid="nz-run-filing">
      <p className="text-[13px] font-semibold text-foreground">New Zealand exceptions and journal</p>
      {loadError && <p role="alert" className="text-[12px] text-error">{loadError}</p>}
      {state.error && <p role="alert" className="text-[12px] text-error">{state.error}</p>}
      {state.notice && <p role="status" className="text-[12px] text-success">{state.notice}</p>}
      {open.length > 0 && (
        <ul className="mt-2 space-y-1">
          {open.map(({ item, code }) => (
            <li key={`${item.id}-${code}`} className="flex flex-wrap items-center gap-2 text-[12px] text-foreground">
              <span className="font-mono">{code}</span> — {item.employee || `payslip #${item.id}`}
              <button type="button" className={btn} disabled={state.busy} onClick={() => {
                const reason = ask("Why may this child-support shortfall stand? (a second user approves it)");
                if (reason) run(() => requestNzRunException(runId, { code, payslip_item_id: item.id, reason }), "Approval requested.");
              }}>Request approval</button>
            </li>
          ))}
        </ul>
      )}
      {loading ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        <div className="mt-2">
          <Table rows={rows} empty="No exception approvals for this run."
            columns={[
              { label: "Payslip", render: (r) => `#${r.payslipItemId}` }, { label: "Code", key: "code" },
              { label: "Status", key: "status" },
              { label: "Actions", render: (r) => (r.status === "REQUESTED" ? (
                <div className="flex flex-wrap gap-1">
                  <button type="button" className={btn} disabled={state.busy}
                    onClick={() => run(() => approveNzRunException(r.id), "Exception approved.")}>Approve</button>
                  <button type="button" className={btn} disabled={state.busy} onClick={() => {
                    const reason = ask("Why is the exception rejected?");
                    if (reason) run(() => rejectNzRunException(r.id, reason), "Exception rejected.");
                  }}>Reject</button>
                </div>
              ) : "—") },
            ]} />
        </div>
      )}
      {paid && (
        <div className="mt-3" data-testid="nz-run-journal">
          <p className="text-[12px] font-semibold text-foreground">Journal</p>
          {journalError && <p role="alert" className="text-[12px] text-error">{journalError}</p>}
          {journal?.status === "BLOCKED" && <p className="text-[12px] text-error">Blocked — {journal.reason}</p>}
          {journal?.status === "READY" && (
            <Table rows={journal.lines} rowKey={(l) => `${l.side}-${l.account}`} empty="No lines."
              columns={[{ label: "Side", key: "side" }, { label: "Account", key: "account" },
                { label: "Amount", key: "amount" }, { label: "Memo", key: "memo" }]} />
          )}
        </div>
      )}
    </div>
  );
}
