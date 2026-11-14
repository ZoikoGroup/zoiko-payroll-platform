import { useState } from "react";
import { acknowledgeBeRunException, getBeRunPreflight } from "../../../service/payrollService";
import { useLoad } from "../../../components/jurisdiction/japan/jpFormat";
import { btn } from "../../../components/jurisdiction/japan/JPRecordSection";
import { errorText } from "../../../components/jurisdiction/new_zealand/nzOrgOptions";

// Belgium run preflight (ZP-BE-ENG-001 §12; Block B3). Blocking reasons (the
// resolver, pending content) refuse approval and cannot be waived; an engine
// EXCEPTION (e.g. the special social security contribution that is never
// computed) stops approval until an org admin acknowledges it with a reason;
// Dimona IN is a placeholder until Block C. Approval (four-eyes) and the
// approval fingerprint are enforced server-side; this panel only shows them.

export default function BERunPreflightPanel({ runId }) {
  const [view, error, loading, reload] = useLoad(() => getBeRunPreflight(runId));
  const [state, setState] = useState({ error: null, notice: null });
  const acknowledge = async (p) => {
    const reason = window.prompt(`Why is ${p.code} acceptable for employee #${p.employeeId}?`);
    if (!reason || !reason.trim()) return;
    try {
      await acknowledgeBeRunException(runId, { employeeId: p.employeeId, code: p.code, reason: reason.trim() });
      setState({ error: null, notice: `${p.code} acknowledged.` });
      reload();
    } catch (e) {
      setState({ error: errorText(e), notice: null });
    }
  };
  const blocking = view?.blocking || [];
  return (
    <div className="mt-3 rounded-xl border border-border bg-surface p-4" data-testid="be-run-preflight">
      <p className="text-[13px] font-semibold text-foreground">Belgium preflight</p>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {loading && <p className="text-[12px] text-foreground-muted">Loading…</p>}
      {view && (
        <>
          <p className={`mt-1 text-[12px] font-semibold ${view.approvable ? "text-success" : "text-error"}`}>
            {view.approvable ? "Ready for approval by a second person" : "Blocked"}
          </p>
          <ul className="mt-2 space-y-1">
            {blocking.map((p, index) => (
              <li key={`${p.code}-${p.employeeId}-${index}`} className="flex flex-wrap items-center gap-2 text-[12px] text-error">
                <span className="font-mono">{p.code}</span>
                {p.employeeId ? `(employee #${p.employeeId})` : ""} — {p.message}
                {p.exception && <button type="button" className={btn} onClick={() => acknowledge(p)}>Acknowledge</button>}
              </li>
            ))}
            {(view.acknowledged || []).map((p, index) => (
              <li key={`ack-${p.code}-${p.employeeId}-${index}`} className="text-[12px] text-foreground-muted">
                <span className="font-mono">{p.code}</span> (employee #{p.employeeId}) — acknowledged
              </li>
            ))}
            {(view.pending || []).map((p, index) => (
              <li key={`pending-${p.code}-${p.employeeId}-${index}`} className="text-[12px] text-warning">
                <span className="font-mono">{p.code}</span> (employee #{p.employeeId}) — {p.message}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[11px] text-foreground-muted" data-testid="be-run-fingerprint">
            Approval fingerprint: {view.fingerprint?.approved ? (view.fingerprint.matches ? "matches the payslips"
              : "NO LONGER MATCHES — authorization and payment are refused") : "not approved yet"}
          </p>
          {state.error && <p role="alert" className="text-[12px] text-error">{state.error}</p>}
          {state.notice && <p role="status" className="text-[12px] text-success">{state.notice}</p>}
        </>
      )}
    </div>
  );
}
