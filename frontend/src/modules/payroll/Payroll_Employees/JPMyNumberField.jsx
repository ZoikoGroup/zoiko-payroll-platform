import { useEffect, useRef, useState } from "react";
import {
  approveJpMyNumberReveal, createJpMyNumber, listJpMyNumbers, requestJpMyNumberReveal, revealJpMyNumber,
} from "../../../service/payrollService";
import { card, useLoad } from "../../../components/jurisdiction/japan/jpFormat";
import { btn } from "../../../components/jurisdiction/japan/JPRecordSection";

// Japan My Number (ZP-JP-ENG-001 §12). Lists show the masked form only. A
// reveal needs a reason, a SECOND user's approval and then an explicit reveal
// (all enforced server-side); the 12 digits live only in this component's
// state for REVEAL_SECONDS and are wiped on timeout or unmount. They are never
// written to storage, the URL, the console or any other component.
export const REVEAL_SECONDS = 60;

const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";

function errorText(e) {
  const detail = e?.response?.data?.detail ?? e?.detail;
  return typeof detail === "string" ? detail : "The action failed.";
}

function RevealRow({ row, onChanged }) {
  const [reason, setReason] = useState("");
  const [revealed, setRevealed] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef(null);

  useEffect(() => () => {
    clearTimeout(timer.current);
    setRevealed(null);
  }, []);

  const act = async (fn) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const reveal = () => act(async () => {
    const result = await revealJpMyNumber(row.id);
    clearTimeout(timer.current);
    setRevealed(result?.myNumber || null);
    timer.current = setTimeout(() => setRevealed(null), REVEAL_SECONDS * 1000);
    onChanged();
  });

  const hide = () => {
    clearTimeout(timer.current);
    setRevealed(null);
  };

  return (
    <div className="flex flex-col gap-2 border-t border-border py-2 text-[12px]" data-testid="jp-my-number-row">
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-mono">{revealed || row.masked}</span>
        <span className="text-foreground-muted">{row.subjectType} · {row.subjectRef} · {row.status}</span>
        {revealed && (
          <>
            <span className="text-warning">Visible for {REVEAL_SECONDS}s — every reveal is audited.</span>
            <button type="button" className={btn} onClick={hide}>Hide</button>
          </>
        )}
      </div>
      {row.status === "ACTIVE" && !revealed && (
        <div className="flex flex-wrap items-center gap-2">
          <input className={input} placeholder="Reason for the reveal" value={reason}
            onChange={(e) => setReason(e.target.value)} aria-label="Reveal reason" />
          <button type="button" className={btn} disabled={busy || !reason.trim()}
            onClick={() => act(async () => { await requestJpMyNumberReveal(row.id, reason.trim()); setReason(""); })}>
            Request reveal
          </button>
          <button type="button" className={btn} disabled={busy}
            onClick={() => act(() => approveJpMyNumberReveal(row.id))}>
            Approve request (second user)
          </button>
          <button type="button" className={btn} disabled={busy} onClick={reveal}>Reveal</button>
        </div>
      )}
      {error && <p role="alert" className="text-error">{error}</p>}
    </div>
  );
}

export default function JPMyNumberField({ employeeId }) {
  const [rows, loadError, loading, reload] = useLoad(() => listJpMyNumbers(employeeId));
  const [number, setNumber] = useState("");
  const [state, setState] = useState({ busy: false, error: null, notice: null });

  const submit = async (e) => {
    e.preventDefault();
    const value = number;
    setNumber("");                              // never keep the typed digits around
    setState({ busy: true, error: null, notice: null });
    try {
      await createJpMyNumber(employeeId, { myNumber: value, subjectType: "EMPLOYEE", subjectRef: "self" });
      setState({ busy: false, error: null, notice: "My Number stored (encrypted). Only the masked form is shown." });
      reload();
    } catch (err) {
      setState({ busy: false, error: errorText(err), notice: null });
    }
  };

  return (
    <section className={card} data-testid="jp-my-number">
      <h3 className="text-[14px] font-semibold text-foreground">My Number (Individual Number)</h3>
      <p className="mb-2 text-[12px] text-foreground-muted">
        Stored encrypted and bound to this record. Shown masked; a reveal needs a reason and a second user&apos;s approval.
      </p>
      {loadError && <p role="alert" className="text-[12px] text-error">{loadError}</p>}
      {loading ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        (rows || []).length === 0
          ? <p className="py-2 text-[12px] text-foreground-muted">No My Number recorded.</p>
          : rows.map((row) => <RevealRow key={row.id} row={row} onChanged={reload} />)
      )}
      <form onSubmit={submit} className="mt-3 flex flex-wrap items-end gap-2" aria-label="Record a My Number">
        <input className={input} type="password" autoComplete="off" inputMode="numeric" maxLength={12}
          pattern="\d{12}" required aria-label="My Number (12 digits)" placeholder="12 digits"
          value={number} onChange={(e) => setNumber(e.target.value.replace(/\D/g, ""))} />
        <button type="submit" className={btn} disabled={state.busy}>Store</button>
      </form>
      {state.error && <p role="alert" className="text-[12px] text-error">{state.error}</p>}
      {state.notice && <p role="status" className="text-[12px] text-success">{state.notice}</p>}
    </section>
  );
}
