import { useEffect, useRef, useState } from "react";
import {
  approveBeIdentifierReveal, createBeIdentifier, deleteBeIdentifier, listBeIdentifiers, requestBeIdentifierReveal,
  revealBeIdentifier,
} from "../../../service/payrollService";
import { card, useLoad } from "../../../components/jurisdiction/japan/jpFormat";
import { btn } from "../../../components/jurisdiction/japan/JPRecordSection";
import { errorText } from "../../../components/jurisdiction/new_zealand/nzOrgOptions";

// Belgian NISS / INSZ or BIS number (ZP-BE-ENG-001 §15, BE-040, D14). Held only
// in the encrypted identifier vault and shown masked. A reveal needs a reason,
// a SECOND user's approval and is used once by the requester (all enforced
// server-side); the value lives only in this component's state for
// REVEAL_SECONDS and is wiped on timeout or unmount — never written to storage,
// the URL or the console. Only the digit COUNT is checked here: the check-digit
// rule is unverified (gap G-16) and the server decides.
export const REVEAL_SECONDS = 60;
const PERSON_NUMBER_DIGITS = 11;

const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
const digitsOnly = (text) => String(text || "").replace(/\D/g, "");

function IdentifierRow({ row, onChanged }) {
  const [reason, setReason] = useState("");
  const [revealed, setRevealed] = useState(null);
  const [state, setState] = useState({ busy: false, error: null, notice: null });
  const timer = useRef(null);
  useEffect(() => () => { clearTimeout(timer.current); setRevealed(null); }, []);

  const act = async (fn, notice) => {
    setState({ busy: true, error: null, notice: null });
    try {
      await fn();
      setState({ busy: false, error: null, notice });
      onChanged();
    } catch (e) {
      setState({ busy: false, error: errorText(e), notice: null });
    }
  };
  const reveal = () => act(async () => {
    const result = await revealBeIdentifier(row.id);
    clearTimeout(timer.current);
    setRevealed(result?.value || null);
    timer.current = setTimeout(() => setRevealed(null), REVEAL_SECONDS * 1000);
  }, null);

  return (
    <div className="flex flex-col gap-2 border-t border-border pt-2 text-[12px]" data-testid={`be-identifier-${row.identifierType}`}>
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-semibold">{row.identifierType}</span>
        <span className="font-mono">{revealed || row.masked || "deleted"}</span>
        {revealed && (
          <>
            <span className="text-warning">Visible for {REVEAL_SECONDS}s — every reveal is audited.</span>
            <button type="button" className={btn} onClick={() => { clearTimeout(timer.current); setRevealed(null); }}>Hide</button>
          </>
        )}
      </div>
      {row.onFile && !revealed && (
        <div className="flex flex-wrap items-center gap-2">
          <input className={input} placeholder="Reason (reveal or delete)" value={reason}
            onChange={(e) => setReason(e.target.value)} aria-label={`Reason for ${row.identifierType}`} />
          <button type="button" className={btn} disabled={state.busy || !reason.trim()}
            onClick={() => act(async () => { await requestBeIdentifierReveal(row.id, reason.trim()); setReason(""); },
              "Reveal requested — a second user must approve it.")}>Request reveal</button>
          <button type="button" className={btn} disabled={state.busy}
            onClick={() => act(() => approveBeIdentifierReveal(row.id), "Reveal approved.")}>Approve reveal</button>
          <button type="button" className={btn} disabled={state.busy} onClick={reveal}>Reveal (once)</button>
          <button type="button" className={btn} disabled={state.busy || !reason.trim()}
            onClick={() => act(async () => { await deleteBeIdentifier(row.id, reason.trim()); setReason(""); },
              "Deleted — the history is kept.")}>Delete</button>
        </div>
      )}
      {state.error && <span role="alert" className="text-error">{state.error}</span>}
      {state.notice && <span role="status" className="text-success">{state.notice}</span>}
    </div>
  );
}

export default function BEIdentifierField({ employeeId, identifierTypes }) {
  const [rows, loadError, loading, reload] = useLoad(() => listBeIdentifiers(employeeId));
  const types = identifierTypes || [];
  const [kind, setKind] = useState("");
  const [value, setValue] = useState("");
  const [state, setState] = useState({ error: null, notice: null });
  const chosen = kind || types[0] || "";
  const valid = digitsOnly(value).length === PERSON_NUMBER_DIGITS;

  const store = async (e) => {
    e.preventDefault();
    const typed = value;
    setValue("");                               // never keep the typed digits around
    try {
      await createBeIdentifier(employeeId, chosen, typed);
      setState({ error: null, notice: `${chosen} stored (encrypted). Only the masked form is shown.` });
      reload();
    } catch (err) {
      setState({ error: errorText(err), notice: null });
    }
  };

  return (
    <section className={card} data-testid="be-identifiers">
      <h3 className="text-[14px] font-semibold text-foreground">National number (NISS / INSZ) or BIS number</h3>
      <p className="mb-2 text-[12px] text-foreground-muted">
        Stored only in the encrypted vault, bound to this employee, and never kept as an employee field. A reveal
        needs a reason and a second user&apos;s approval, and is used once. The format is checked here; the
        check-digit rule is still unverified and the server decides.
      </p>
      {loadError && <p role="alert" className="text-[12px] text-error">{loadError}</p>}
      {loading ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (rows || []).map((row) => (
        <IdentifierRow key={row.id} row={row} onChanged={reload} />
      ))}
      <form onSubmit={store} className="mt-3 flex flex-wrap items-end gap-2" aria-label="Store a national or BIS number">
        <select className={input} value={chosen} onChange={(e) => setKind(e.target.value)} aria-label="Identifier type">
          {types.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <input className={input} type="password" autoComplete="off" inputMode="numeric" aria-label={chosen || "Identifier"}
          placeholder={chosen || "Identifier"} value={value}
          onChange={(e) => setValue(e.target.value.replace(/[^\d.\- ]/g, ""))} />
        <button type="submit" className={btn} disabled={!valid || !chosen}>Store {chosen}</button>
        {value && !valid && <span className="text-[11px] text-warning">Enter the {PERSON_NUMBER_DIGITS} digits.</span>}
        {state.error && <span role="alert" className="text-[12px] text-error">{state.error}</span>}
        {state.notice && <span role="status" className="text-[12px] text-success">{state.notice}</span>}
      </form>
    </section>
  );
}
