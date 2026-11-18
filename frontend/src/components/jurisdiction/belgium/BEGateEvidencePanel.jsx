import { useState } from "react";
import { decideBeGateEvidence, listBeGateEvidence, recordBeGateEvidence } from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";
import { card, useLoad } from "../japan/jpFormat";
import { btn } from "../japan/JPRecordSection";
import { ErrorNote } from "../new_zealand/nzShared";

// Block K2: evidence per release gate. A Super Admin records evidence against a tag the gate's checks require (or
// SUPPORTING, never counted); ANOTHER Super Admin accepts or rejects it (the server refuses the recorder). Evidence
// never marks a gate met by itself: the gate's other checks are still derived from data. History stays visible.

const TONE = { ACCEPTED: "text-success", REJECTED: "text-error", PENDING: "text-warning" };

function GateEvidence({ gate, block, onChange }) {
  const types = [...(block.requiredEvidence || []), "SUPPORTING"];
  const [form, setForm] = useState({ evidenceType: types[0], reference: "", note: "" });
  const [state, setState] = useState({ busy: false, error: null });
  const run = async (fn) => {
    setState({ busy: true, error: null });
    try {
      await fn();
      setState({ busy: false, error: null });
      onChange();
    } catch (e) {
      setState({ busy: false, error: e.message || "Refused." });
    }
  };
  const record = (e) => {
    e.preventDefault();
    run(() => recordBeGateEvidence({ gate, ...form }));
  };
  const decide = (row, outcome) => {
    const reason = window.prompt(`Why is this evidence ${outcome.toLowerCase()}?`);
    if (reason && reason.trim()) run(() => decideBeGateEvidence(row.id, outcome, reason.trim()));
  };
  return (
    <details className="rounded-lg border border-border p-2" data-testid={`be-gate-evidence-${gate}`}>
      <summary className="cursor-pointer text-[12px] font-semibold text-foreground">
        {gate} evidence ({(block.evidence || []).length}) — required: {(block.requiredEvidence || []).join(", ") || "none (checks derived from data)"}
      </summary>
      <ul className="mt-2 space-y-1 text-[11px]">
        {(block.evidence || []).map((row) => (
          <li key={row.id} className="flex flex-wrap items-center gap-2">
            <span className="font-mono">{row.evidenceType}</span>
            <span>{row.reference}</span>
            <span className={`font-semibold ${TONE[row.status] || ""}`}>{row.status}</span>
            <span className="text-foreground-muted">recorded by #{row.recordedBy}{row.decidedBy ? `, decided by #${row.decidedBy}` : ""}</span>
            {row.status === "PENDING" && (
              <>
                <button type="button" className={btn} disabled={state.busy} onClick={() => decide(row, "ACCEPTED")}>Accept</button>
                <button type="button" className={btn} disabled={state.busy} onClick={() => decide(row, "REJECTED")}>Reject</button>
              </>
            )}
          </li>
        ))}
      </ul>
      <form onSubmit={record} className="mt-2 grid grid-cols-1 gap-2 md:grid-cols-3" aria-label={`Record ${gate} evidence`}>
        <label className={labelClass}>Evidence type
          <select className={inputClass} value={form.evidenceType} onChange={(e) => setForm({ ...form, evidenceType: e.target.value })}>
            {types.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label className={labelClass}>Reference *
          <input className={inputClass} value={form.reference} placeholder="document id / log reference / owner name + role"
            onChange={(e) => setForm({ ...form, reference: e.target.value })} />
        </label>
        <label className={labelClass}>Note
          <input className={inputClass} value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
        </label>
        <div><button type="submit" className={btn} disabled={state.busy || !form.reference.trim()}>Record evidence</button></div>
      </form>
      <ErrorNote message={state.error} />
    </details>
  );
}

export default function BEGateEvidencePanel({ onChange }) {
  const [data, error, loading, reload] = useLoad(listBeGateEvidence);
  if (error) return <ErrorNote message={error} />;
  if (loading || !data) return null;
  const changed = () => { reload(); if (onChange) onChange(); };
  return (
    <div className={`${card} space-y-2`} data-testid="be-gate-evidence">
      <h4 className="text-[12px] font-semibold text-foreground">Evidence</h4>
      <p className="text-[11px] text-foreground-secondary">
        Evidence counts only when a Super Admin other than the recorder accepts it, and only for the tag a gate check
        requires. A gate is met only when all its checks pass.
      </p>
      {Object.entries(data).map(([gate, block]) => <GateEvidence key={gate} gate={gate} block={block} onChange={changed} />)}
    </div>
  );
}
