import { useCallback, useEffect, useState } from "react";
import { getHkEarningCodes, getSourceArtifacts, splitHkEarningCodeRow } from "../../../service/superAdminService";

// Hong Kong earning-code catalogue (HK-006). Read from the governed pack rows
// server-side: each code's EO wages / MPF relevant income / SMW wages / IR56B
// mapping, its status (Sourced — pending specialist review, or Pending with
// the specialist's question), the archived source and SHA-256, and the pay
// sources bound to it. A mid-year change is a governed, dated split (Draft
// packs only; reason + source; audited) — never an in-place rewrite.
const card = "rounded-xl border border-border bg-surface p-4";
const th = "px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-foreground-muted";
const td = "px-2 py-1.5 text-[12px] text-foreground align-top";
const btn = "rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground hover:bg-surface-muted disabled:opacity-40";
const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
const OBLIGATIONS = [["EO_WAGES", "EO wages"], ["MPF_RI", "MPF relevant income"], ["SMW_WAGES", "SMW wages"], ["IRD", "IR56B"]];

function Mapping({ m, onSplit }) {
  if (!m) return <span className="text-foreground-muted">—</span>;
  const pending = m.status === "PENDING";
  return (
    <div className="space-y-0.5">
      <div className="font-semibold">
        {m.irdField ? `${m.irdField}${m.irdItem ? ` (${m.irdItem})` : ""}` : m.treatment}
        {m.irdField && m.treatment !== "INCLUDED" ? ` — ${m.treatment}` : ""}
      </div>
      <div className={`text-[11px] ${pending ? "text-amber-600" : "text-foreground-secondary"}`}>
        {pending ? "Pending — specialist question" : "Sourced — pending specialist review"}
      </div>
      <div className="text-[11px] text-foreground-secondary">{pending ? m.question : m.basis}</div>
      {m.source && (
        <div className="text-[10px] text-foreground-muted" title={m.source.url}>
          {m.source.agency} · sha256 {String(m.source.sha256 || "").slice(0, 12)}…
        </div>
      )}
      <div className="text-[10px] text-foreground-muted">{m.effectiveFrom} → {m.effectiveTo || "open"}</div>
      <button type="button" className="text-[11px] font-semibold text-primary underline" onClick={() => onSplit(m)}>
        Change from a date…
      </button>
    </div>
  );
}

function SplitForm({ target, sources, onDone, onCancel }) {
  const [form, setForm] = useState({ effectiveFrom: "", treatment: "", irdField: "", reason: "", sourceDocumentId: "" });
  const [error, setError] = useState(null);
  async function save() {
    setError(null);
    const payload = { effectiveFrom: form.effectiveFrom, reason: form.reason, sourceDocumentId: Number(form.sourceDocumentId) };
    if (form.treatment) payload.treatment = form.treatment;
    if (form.irdField) payload.irdField = form.irdField;
    try { onDone(await splitHkEarningCodeRow(target.rowId, payload)); } catch (e) { setError(e?.message || "Change refused."); }
  }
  return (
    <div className={`${card} space-y-2`} aria-label="Change mapping from a date">
      <div className="text-[12px] font-semibold">{target.code} → {target.obligation}: change from a date (Draft versions only)</div>
      <div className="flex flex-wrap gap-2">
        <label className="text-[11px]">From <input type="date" className={`${input} ml-1`} value={form.effectiveFrom}
          onChange={(e) => setForm({ ...form, effectiveFrom: e.target.value })} /></label>
        <label className="text-[11px]">Treatment <select className={`${input} ml-1`} value={form.treatment}
          onChange={(e) => setForm({ ...form, treatment: e.target.value })}>
          <option value="">unchanged</option><option>INCLUDED</option><option>EXCLUDED</option><option>REVIEW</option>
        </select></label>
        {target.obligation === "IRD" && (
          <label className="text-[11px]">IR56B field <input className={`${input} ml-1 w-56`} value={form.irdField}
            onChange={(e) => setForm({ ...form, irdField: e.target.value })} /></label>
        )}
        <label className="text-[11px]">Source <select className={`${input} ml-1 w-64`} value={form.sourceDocumentId}
          onChange={(e) => setForm({ ...form, sourceDocumentId: e.target.value })}>
          <option value="">choose…</option>
          {sources.map((s) => <option key={s.id} value={s.id}>{s.title || s.agency}</option>)}
        </select></label>
      </div>
      <textarea className={`${input} w-full`} rows={2} placeholder="Reason for the change (required)" value={form.reason}
        onChange={(e) => setForm({ ...form, reason: e.target.value })} />
      {error && <div role="alert" className="text-[12px] text-red-600">{error}</div>}
      <div className="flex gap-2">
        <button type="button" className={btn} onClick={save} disabled={!form.effectiveFrom || !form.reason || !form.sourceDocumentId}>Save</button>
        <button type="button" className={btn} onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

export default function HKEarningCodesTab() {
  const [on, setOn] = useState(() => new Date().toISOString().slice(0, 10));
  const [data, setData] = useState(null);
  const [sources, setSources] = useState([]);
  const [error, setError] = useState(null);
  const [split, setSplit] = useState(null);
  const [notice, setNotice] = useState(null);

  const [version, setVersion] = useState(0);
  const load = useCallback(() => setVersion((v) => v + 1), []);
  useEffect(() => {
    let live = true;
    getHkEarningCodes(on)
      .then((out) => { if (live) { setData(out); setError(null); } })
      .catch((e) => { if (live) setError(e?.message || "Could not load the catalogue."); });
    return () => { live = false; };
  }, [on, version]);
  useEffect(() => { getSourceArtifacts().then((r) => setSources(Array.isArray(r) ? r : r?.items || [])).catch(() => {}); }, []);

  const pending = (data?.codes || []).reduce((n, c) => n + (c.pendingCount || 0), 0);
  return (
    <div className="space-y-3">
      <div className={card}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="text-[14px] font-semibold">Earning codes (HK-006)</div>
            <div className="text-[12px] text-foreground-secondary">
              {data ? `${data.pack.packId} v${data.pack.version} (${data.pack.status}) · ${data.codes.length} codes · ${pending} mappings pending a specialist answer · none specialist-verified` : "…"}
            </div>
          </div>
          <label className="text-[12px]">As of <input type="date" className={`${input} ml-1`} value={on} onChange={(e) => setOn(e.target.value)} /></label>
        </div>
        {(data?.rules || []).map((r) => <div key={r} className="mt-1 text-[11px] text-foreground-secondary">• {r}</div>)}
      </div>
      {error && <div role="alert" className="text-[12px] text-red-600">{error}</div>}
      {notice && <div role="status" className="text-[12px] text-green-700">{notice}</div>}
      {split && (
        <SplitForm target={split} sources={sources} onCancel={() => setSplit(null)}
          onDone={(out) => { setSplit(null); setNotice(`Mapping changed from ${out.effectiveFrom} (previous row ends ${out.endedOn}).`); load(); }} />
      )}
      {data && (
        <div className={`${card} overflow-x-auto`}>
          <table className="w-full min-w-[960px]">
            <thead><tr><th className={th}>Code</th>{OBLIGATIONS.map(([k, l]) => <th key={k} className={th}>{l}</th>)}<th className={th}>Pay sources</th></tr></thead>
            <tbody>
              {data.codes.map((c) => (
                <tr key={c.code} className="border-t border-border">
                  <td className={td}><div className="font-semibold">{c.code}</div><div className="text-[11px] text-foreground-secondary">{c.label}</div></td>
                  {OBLIGATIONS.map(([k]) => (
                    <td key={k} className={td}>
                      <Mapping m={c.mappings[k]} onSplit={(m) => setSplit({ ...m, code: c.code, obligation: k })} />
                    </td>
                  ))}
                  <td className={td}>{c.boundSources.length ? c.boundSources.join(", ") : <span className="text-foreground-muted">none</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
