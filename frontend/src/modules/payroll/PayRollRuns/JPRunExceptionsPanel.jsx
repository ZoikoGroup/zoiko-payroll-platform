import { useState } from "react";
import { approveJpRunException, listJpRunExceptions } from "../../../service/payrollService";
import { useLoad } from "../../../components/jurisdiction/japan/jpFormat";
import { btn } from "../../../components/jurisdiction/japan/JPRecordSection";

// Japan run exceptions (ZP-JP-ENG-001 §8). Each must be approved by a second
// person — never the run's preparer — before the run can be approved. An
// approval covers the payload it saw: a later change to the payslips needs a
// new one. Enforced server-side; this panel only submits the decision.

const OPEN = ["Draft", "Review"];

export default function JPRunExceptionsPanel({ runId, runStatus }) {
  const [rows, error, loading, reload] = useLoad(() => listJpRunExceptions(runId));
  const [notes, setNotes] = useState({});
  const [state, setState] = useState({ busy: false, error: null });
  const open = OPEN.some((s) => s.toUpperCase() === String(runStatus || "").toUpperCase());

  const approve = async (key) => {
    setState({ busy: true, error: null });
    try {
      await approveJpRunException(runId, key, notes[key] || "");
      setState({ busy: false, error: null });
      reload();
    } catch (e) {
      const detail = e?.response?.data?.detail;
      setState({ busy: false, error: typeof detail === "string" ? detail : "The approval failed." });
    }
  };

  return (
    <div className="mt-3 rounded-xl border border-border bg-surface p-4" data-testid="jp-run-exceptions">
      <p className="text-[13px] font-semibold text-foreground">Japan exceptions</p>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {state.error && <p role="alert" className="text-[12px] text-error">{state.error}</p>}
      {loading ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        (rows || []).length === 0 ? <p className="text-[12px] text-foreground-muted">No exceptions.</p> : (
          <ul className="mt-2 space-y-2">
            {rows.map((row) => (
              <li key={row.key} className="rounded-lg border border-border p-2 text-[12px]">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span><span className="font-mono">{row.code}</span>{row.employeeId ? ` · employee #${row.employeeId}` : " · run"}</span>
                  {row.approved
                    ? <span className="text-success">Approved by user #{row.approved.approvedById}</span>
                    : <span className="text-warning">Needs a second person</span>}
                </div>
                <p className="mt-1 text-foreground-muted">{row.detail}</p>
                {!row.approved && open && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    <input className="rounded-lg border border-border bg-surface px-2 py-1 text-[12px]" placeholder="Note"
                      value={notes[row.key] || ""} onChange={(e) => setNotes((n) => ({ ...n, [row.key]: e.target.value }))} />
                    <button type="button" className={btn} disabled={state.busy} onClick={() => approve(row.key)}>Approve</button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )
      )}
    </div>
  );
}
