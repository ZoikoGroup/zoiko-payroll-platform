import { useEffect, useRef, useState } from "react";
import {
  approveNzIrdReveal, deleteNzIrdNumber, getNzIrdNumber, requestNzIrdReveal, revealNzIrdNumber, setNzIrdNumber,
} from "../../../service/payrollService";
import { card, useLoad } from "../../../components/jurisdiction/japan/jpFormat";
import { btn } from "../../../components/jurisdiction/japan/JPRecordSection";
import { errorText } from "../../../components/jurisdiction/new_zealand/nzOrgOptions";

// New Zealand IRD number (ZP-NZ-ENG-001 §13, NZ-023). Shown masked only. A
// reveal needs a reason, a SECOND user's approval and then a single-use reveal
// to the requester (all enforced server-side); the digits live only in this
// component's state for REVEAL_SECONDS and are wiped on timeout or unmount —
// never written to storage, the URL, the console or any other component.
export const REVEAL_SECONDS = 60;

const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";

export default function NZIrdNumberField({ employeeId }) {
  const [record, loadError, loading, reload] = useLoad(() => getNzIrdNumber(employeeId));
  const [number, setNumber] = useState("");
  const [reason, setReason] = useState("");
  const [revealed, setRevealed] = useState(null);
  const [state, setState] = useState({ busy: false, error: null, notice: null });
  const timer = useRef(null);

  useEffect(() => () => {
    clearTimeout(timer.current);
    setRevealed(null);
  }, []);

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

  const store = (e) => {
    e.preventDefault();
    const value = number;
    setNumber("");                              // never keep the typed digits around
    act(() => setNzIrdNumber(employeeId, value), "IRD number stored (encrypted). Only the masked form is shown.");
  };

  const reveal = () => act(async () => {
    const result = await revealNzIrdNumber(record.id);
    clearTimeout(timer.current);
    setRevealed(result?.irdNumber || null);
    timer.current = setTimeout(() => setRevealed(null), REVEAL_SECONDS * 1000);
  }, null);

  const hide = () => {
    clearTimeout(timer.current);
    setRevealed(null);
  };

  return (
    <section className={card} data-testid="nz-ird-number">
      <h3 className="text-[14px] font-semibold text-foreground">IRD number</h3>
      <p className="mb-2 text-[12px] text-foreground-muted">
        Stored encrypted and bound to this employee. Shown masked; a reveal needs a reason, a second user&apos;s
        approval, and is used once.
      </p>
      {loadError && <p role="alert" className="text-[12px] text-error">{loadError}</p>}
      {loading ? <p className="text-[12px] text-foreground-muted">Loading…</p> : record?.onFile ? (
        <div className="flex flex-col gap-2 text-[12px]">
          <div className="flex flex-wrap items-center gap-3">
            <span className="font-mono">{revealed || record.masked}</span>
            {revealed && (
              <>
                <span className="text-warning">Visible for {REVEAL_SECONDS}s — every reveal is audited.</span>
                <button type="button" className={btn} onClick={hide}>Hide</button>
              </>
            )}
          </div>
          {!revealed && (
            <div className="flex flex-wrap items-center gap-2">
              <input className={input} placeholder="Reason (reveal or delete)" value={reason}
                onChange={(e) => setReason(e.target.value)} aria-label="Reason" />
              <button type="button" className={btn} disabled={state.busy || !reason.trim()}
                onClick={() => act(async () => { await requestNzIrdReveal(record.id, reason.trim()); setReason(""); },
                  "Reveal requested — a second user must approve it.")}>
                Request reveal
              </button>
              <button type="button" className={btn} disabled={state.busy}
                onClick={() => act(() => approveNzIrdReveal(record.id), "Reveal approved.")}>
                Approve request (second user)
              </button>
              <button type="button" className={btn} disabled={state.busy} onClick={reveal}>Reveal</button>
              <button type="button" className={btn} disabled={state.busy || !reason.trim()}
                onClick={() => act(async () => { await deleteNzIrdNumber(record.id, reason.trim()); setReason(""); },
                  "IRD number deleted from the vault.")}>
                Delete
              </button>
            </div>
          )}
        </div>
      ) : (
        <form onSubmit={store} className="flex flex-wrap items-end gap-2" aria-label="Record an IRD number">
          <input className={input} type="password" autoComplete="off" inputMode="numeric" maxLength={9}
            pattern="\d{8,9}" required aria-label="IRD number (8 or 9 digits)" placeholder="8 or 9 digits"
            value={number} onChange={(e) => setNumber(e.target.value.replace(/\D/g, ""))} />
          <button type="submit" className={btn} disabled={state.busy}>Store</button>
        </form>
      )}
      {state.error && <p role="alert" className="mt-2 text-[12px] text-error">{state.error}</p>}
      {state.notice && <p role="status" className="mt-2 text-[12px] text-success">{state.notice}</p>}
    </section>
  );
}
