import { useState } from "react";
import { runMxSandbox } from "../../../service/superAdminService";
import { Messages, Table, btn, btnPrimary, card, input } from "./mxShared";

// Mexico calculation sandbox (final mile X2). The backend runs the production
// engine on SYNTHETIC inputs and the content in force on the pay date (Draft
// packs allowed, labelled) and writes nothing. What-if candidates for decisions
// not yet approved are never persisted and every such answer is watermarked.
// No statutory maths in React.
const BASE = {
  payDate: "2026-06-15", periodStart: "2026-06-01", periodEnd: "2026-06-15", dailySalary: "600", zone: "GENERAL",
  workState: "CDMX", payFrequencyCode: "04", seniorityDate: "2026-01-01", riskPremiumPct: "",
};
// Spec §21 engineering fixtures (inputs only — the expectation is the spec's, not this screen's).
const PRESETS = [
  ["F1 Jan (UMA 113.14)", { payDate: "2026-01-15", periodStart: "2026-01-01", periodEnd: "2026-01-15" }],
  ["F1 Feb (UMA 117.31)", { payDate: "2026-02-15", periodStart: "2026-02-01", periodEnd: "2026-02-15" }],
  ["F2 first-year SBC", { seniorityDate: "2026-01-01", dailySalary: "600" }],
  ["F3 CEAV high band", { dailySalary: "1000" }],
  ["F4 general zone", { zone: "GENERAL", dailySalary: "400" }],
  ["F4 ZLFN", { zone: "ZLFN", dailySalary: "400" }],
];
const FIELDS = [
  ["payDate", "Pay date", "date"], ["periodStart", "Period start", "date"], ["periodEnd", "Period end", "date"],
  ["dailySalary", "Daily salary (MXN)", "text"], ["seniorityDate", "Seniority date", "date"],
  ["payFrequencyCode", "Pay frequency (c_PeriodicidadPago)", "text"], ["workState", "Work state", "text"],
  ["riskPremiumPct", "Work-risk premium % (blank = synthetic default)", "text"],
];

export default function MXSandboxTab() {
  const [form, setForm] = useState(BASE);
  const [candidates, setCandidates] = useState([]);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const setCandidate = (i, k) => (e) => setCandidates((cs) => cs.map((c, j) => (j === i ? { ...c, [k]: e.target.value } : c)));

  async function run(e) {
    e?.preventDefault();
    setError(null);
    setResult(null);
    try {
      setResult(await runMxSandbox({ ...form, candidates: candidates.filter((c) => c.decision && c.value) }));
    } catch (err) {
      setError(err?.message || "The sandbox refused the request.");
    }
  }

  const r = result?.result?.mx_result;
  return (
    <div className="flex flex-col gap-4">
      <form onSubmit={run} className={card} aria-label="Mexico calculation sandbox">
        <p className="mb-2 text-[12px] text-foreground-muted">
          Synthetic inputs only. The engine runs against the packs covering the pay date (Draft included) and nothing is written.
          Every run stops at the first block until its decision is made; a what-if candidate for a decision not yet approved
          can be tried here, never stored.
        </p>
        <div className="mb-3 flex flex-wrap gap-2" aria-label="Spec §21 presets">
          {PRESETS.map(([label, over]) => (
            <button key={label} type="button" className={btn} onClick={() => setForm({ ...BASE, ...over })}>{label}</button>
          ))}
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {FIELDS.map(([k, label, type]) => (
            <label key={k} className="text-[12px] font-semibold text-foreground-secondary">{label}
              <input aria-label={label} type={type} className={`${input} mt-1 w-full`} value={form[k]} onChange={set(k)} />
            </label>
          ))}
          <label className="text-[12px] font-semibold text-foreground-secondary">Minimum-wage zone
            <select aria-label="Minimum-wage zone" className={`${input} mt-1 w-full`} value={form.zone} onChange={set("zone")}>
              <option>GENERAL</option><option>ZLFN</option>
            </select>
          </label>
        </div>
        <div className="mt-3" aria-label="What-if candidates">
          <p className="text-[12px] font-semibold text-foreground-secondary">What-if candidates (decisions not yet approved; pack-row keys only)</p>
          {candidates.map((c, i) => (
            <div key={i} className="mt-1 flex flex-wrap gap-2">
              <input aria-label={`Candidate ${i + 1} decision`} className={input} placeholder="D-01" value={c.decision} onChange={setCandidate(i, "decision")} />
              <input aria-label={`Candidate ${i + 1} value`} className={input} placeholder="HALF_UP:0.01" value={c.value} onChange={setCandidate(i, "value")} />
              <button type="button" className={btn} onClick={() => setCandidates((cs) => cs.filter((_, j) => j !== i))}>Remove</button>
            </div>
          ))}
          <button type="button" className={`${btn} mt-1`} onClick={() => setCandidates((cs) => [...cs, { decision: "", value: "" }])}>Add candidate</button>
        </div>
        <div className="mt-3"><button type="submit" className={btnPrimary}>Run sandbox</button></div>
      </form>
      <Messages error={error} />
      {result && (
        <div className={card} data-testid="mx-sandbox-result">
          <div className="mb-2 flex flex-wrap gap-2" data-testid="mx-sandbox-watermarks">
            {result.watermarks.map((w) => (
              <span key={w} className={`rounded px-2 py-1 text-[11px] font-bold ${w.startsWith("CANDIDATE") ? "bg-warning/20 text-warning" : "bg-surface-muted text-foreground-secondary"}`}>{w}</span>
            ))}
          </div>
          <p className="text-[12px] text-foreground-muted">
            Content: {result.pack?.label || "no pack"} · State ISN: {result.isnPack?.label || "no pack"}
            {result.candidates?.length ? ` · Candidates: ${result.candidates.map((c) => `${c.decision} ${c.contentKey}=${c.value}`).join("; ")}` : ""}
          </p>
          {result.outcome === "BLOCKED" ? (
            <div className="mt-2" data-testid="mx-sandbox-block">
              <p className="text-[13px] font-semibold text-error">Blocked: {result.block.code}</p>
              <p className="text-[12px] text-foreground">{result.block.message}</p>
              <ul className="mt-1 text-[12px]">
                {(result.block.reasons || []).map((x) => (
                  <li key={x.code + x.message}>
                    <code>{x.code}</code> — {x.clearedBy?.length
                      ? `cleared by ${x.clearedBy.map((d) => `${d.code} (${d.status})`).join(", ")} — see the Decisions tab`
                      : "no decision clears it: an input or a source does"}
                  </li>
                ))}
              </ul>
            </div>
          ) : r && (
            <div className="mt-2 flex flex-col gap-3" data-testid="mx-sandbox-calculated">
              <Table rows={[
                ["Gross", r.gross], ["Tariff period", r.tariff_period], ["ISR (tariff)", r.isr], ["Subsidy applied", r.subsidy?.applied],
                ["ISR withheld", r.isr_withheld], ["IMSS employee", r.imss_employee], ["IMSS employer", r.imss_employer],
                ["INFONAVIT employer", r.infonavit_employer], ["State ISN", r.isn?.amount], ["Employer total", r.employer_total],
              ].map(([k, v]) => ({ k, v }))} rowKey={(x) => x.k} columns={[{ key: "k", label: "Line" }, { key: "v", label: "Amount" }]} />
              <Table rows={r.sbc?.segments || []} rowKey={(s) => s.start} columns={[
                { key: "start", label: "SBC segment" }, { key: "sbc", label: "SBC" }, { key: "uma_daily", label: "UMA daily" },
                { key: "cap", label: "25-UMA cap" }, { key: "floor", label: "Minimum-wage floor" },
              ]} />
              <p className="text-[12px] text-foreground-muted">SBC factor {r.sbc?.components?.factor} (service year {r.sbc?.components?.service_year})</p>
              <Table rows={r.imss || []} rowKey={(b) => `${b.branch}-${b.side}`} columns={[
                { key: "branch", label: "IMSS branch" }, { key: "side", label: "Side" },
                { key: "rate", label: "Rate %", render: (b) => b.lines?.[0]?.rate_pct }, { key: "band", label: "Band", render: (b) => b.lines?.[0]?.band || "" },
                { key: "amount", label: "Amount" },
              ]} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
