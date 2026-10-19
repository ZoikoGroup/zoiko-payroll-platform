import { useEffect, useState } from "react";
import { btn, btnPrimary, card, input, Messages, Table, useAction } from "../mxShared";
import {
  approveMxSuaDifference, enterMxSuaFigures, explainMxSuaDifference, getMxSuaPeriod, openMxSuaPeriod,
  reconcileMxSuaPeriod, recordMxSuaPayment,
} from "../../../../service/payrollService";
import { MarkUnknownButton, money, PromptButton, Status, UnknownActions } from "./authShared";

// SUA reconciliation (MX-033 / MX-042): Zoiko's per-worker × per-branch
// totals against the figures you enter from SUA (Zoiko template — the SUA
// file layout S12 is not transcribed). Zero tolerance: every difference is
// BLOCKING until explained and approved by a second person.
export default function MXSuaPanel({ rows, registrations, reload }) {
  const { run, error, notice, busy } = useAction(reload);
  const [reg, setReg] = useState("");
  const [period, setPeriod] = useState("");
  const [openId, setOpenId] = useState(null);
  return (
    <section className={card} data-testid="mx-sua">
      <h3 className="mb-2 text-[14px] font-semibold text-foreground">SUA reconciliation</h3>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <select className={input} aria-label="IMSS registration" value={reg} onChange={(e) => setReg(e.target.value)}>
          <option value="">IMSS registration…</option>
          {(registrations || []).map((r) => <option key={r.id} value={r.id}>{r.registroPatronal}</option>)}
        </select>
        <input className={input} aria-label="Month (YYYY-MM)" placeholder="YYYY-MM" value={period} onChange={(e) => setPeriod(e.target.value)} />
        <button type="button" className={btn} disabled={busy || !reg || !/^\d{4}-\d{2}$/.test(period)}
          onClick={() => run(async () => { const p = await openMxSuaPeriod(Number(reg), period); setOpenId(p.id); }, "SUA period opened.")}>
          Open period
        </button>
      </div>
      <Messages error={error} notice={notice} />
      <Table rows={rows} empty="No SUA period yet." columns={[
        { key: "periodKey", label: "Month" },
        { key: "registrationId", label: "Registration" },
        { key: "suaVersion", label: "SUA version" },
        { key: "openDifferences", label: "Open differences", render: (r) => (r.figuresEntered ? r.openDifferences : "figures not entered") },
        { key: "status", label: "Status", render: (r) => <Status value={r.status} /> },
        { key: "act", label: "", render: (r) => (
          <span className="flex flex-col gap-1">
            <button type="button" className={btn} onClick={() => setOpenId(openId === r.id ? null : r.id)}>{openId === r.id ? "Close" : "Open"}</button>
            <UnknownActions kind="sua-periods" row={r} run={run} />
          </span>
        ) },
      ]} />
      {openId && <SuaDetail id={openId} reloadList={reload} />}
    </section>
  );
}

function SuaDetail({ id, reloadList }) {
  const [p, setP] = useState(null);
  const [tick, setTick] = useState(0);
  const [figures, setFigures] = useState({});
  const [version, setVersion] = useState("");
  const { run, error, notice, busy } = useAction(() => { setTick((t) => t + 1); reloadList?.(); });
  useEffect(() => {
    let active = true;
    getMxSuaPeriod(id).then((d) => {
      if (!active) return;
      setP(d);
      setFigures(Object.fromEntries(Object.keys(d.zoikoTotals || {}).map((k) => [k, (d.suaTotals || {})[k] ?? ""])));
    });
    return () => { active = false; };
  }, [id, tick]);
  if (!p) return null;
  const keys = Object.keys(p.zoikoTotals || {});
  const rows = keys.map((k) => {
    const [emp, bs] = k.split("|");
    const [branch, side] = bs.split(":");
    return { employeeId: Number(emp), branch, side, amount: figures[k] };
  });
  return (
    <div className="mt-3 rounded-lg border border-border p-3" data-testid="mx-sua-detail">
      <p className="mb-2 text-[12px] font-semibold">SUA period {p.periodKey} · <Status value={p.status} /></p>
      <Messages error={error} notice={notice} />
      {p.status === "DRAFT" && (
        <>
          <p className="mb-1 text-[11px] text-foreground-muted">Enter each figure exactly as SUA shows it (worker × branch × side).</p>
          <table className="mb-2 w-full text-[11px]">
            <thead><tr className="text-left text-foreground-muted"><th>Employee</th><th>Branch</th><th>Side</th><th>Zoiko</th><th>SUA</th></tr></thead>
            <tbody>
              {keys.map((k) => {
                const [emp, bs] = k.split("|");
                const [branch, side] = bs.split(":");
                return (
                  <tr key={k} className="border-t border-border">
                    <td>#{emp}</td><td>{branch}</td><td>{side}</td><td>{money(p.zoikoTotals[k])}</td>
                    <td><input className={`${input} w-28`} aria-label={`SUA ${k}`} value={figures[k] ?? ""}
                      onChange={(e) => setFigures((f) => ({ ...f, [k]: e.target.value }))} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <span className="flex flex-wrap items-center gap-2">
            <input className={input} aria-label="SUA version" placeholder="SUA version (as shown)" value={version} onChange={(e) => setVersion(e.target.value)} />
            <button type="button" className={btn} disabled={busy || rows.some((r) => r.amount === "" || r.amount === undefined)}
              onClick={() => run(() => enterMxSuaFigures(id, rows, version || null), "SUA figures recorded.")}>Record SUA figures</button>
            <button type="button" className={btnPrimary} disabled={busy || !p.figuresEntered}
              onClick={() => run(() => reconcileMxSuaPeriod(id), "Reconciled.")}>Reconcile (second person)</button>
          </span>
        </>
      )}
      {(p.differenceRows || []).length > 0 && (
        <div className="mt-2" data-testid="mx-sua-differences">
          <p className="text-[12px] font-semibold text-error">Differences — BLOCKING until explained and approved</p>
          {p.differenceRows.map((d) => (
            <div key={d.id} className="mt-1 flex flex-wrap items-center gap-2 text-[11px]">
              <span>#{d.employeeId} {d.branch}: Zoiko {money(d.zoiko)} · SUA {money(d.sua)} · Δ {money(d.difference)}</span>
              <Status value={d.status} />
              {d.status === "OPEN" && (
                <Explain codes={p.explanationCodes} onSubmit={(code, text) => run(() => explainMxSuaDifference(d.id, code, text), "Explained.")} />
              )}
              {d.status === "EXPLAINED" && (
                <>
                  <span className="text-foreground-muted">{d.code}: {d.explanation}</span>
                  <button type="button" className={btn} onClick={() => run(() => approveMxSuaDifference(d.id), "Approved.")}>Approve (second person)</button>
                </>
              )}
            </div>
          ))}
        </div>
      )}
      {p.status === "RECONCILED" && (
        <span className="mt-2 flex flex-wrap gap-2">
          <PromptButton label="Record SIPARE payment…" placeholder="Payment reference (paid outside Zoiko)"
            onSubmit={(ref) => run(() => recordMxSuaPayment(id, ref, null), "Payment recorded.")} />
          <MarkUnknownButton kind="sua-periods" row={p} run={run} />
        </span>
      )}
      <UnknownActions kind="sua-periods" row={p} run={run} />
    </div>
  );
}

function Explain({ codes, onSubmit }) {
  const [code, setCode] = useState("");
  const [text, setText] = useState("");
  return (
    <span className="flex flex-wrap items-center gap-1">
      <select className={input} aria-label="Explanation code" value={code} onChange={(e) => setCode(e.target.value)}>
        <option value="">Code…</option>
        {(codes || []).map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
      <input className={`${input} min-w-[180px]`} aria-label="Explanation" placeholder="Explanation" value={text} onChange={(e) => setText(e.target.value)} />
      <button type="button" className={btn} disabled={!code || !text.trim()} onClick={() => onSubmit(code, text.trim())}>Explain</button>
    </span>
  );
}
