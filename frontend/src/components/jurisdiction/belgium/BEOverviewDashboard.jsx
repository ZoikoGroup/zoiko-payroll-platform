import { useState } from "react";
import { AlertTriangle } from "lucide-react";
import {
  addBeAuthorityExample, getBeGoldenCheck, getBeSigningStatus, getBeSummary, runBeGoldenCertification, seedBeDraftPack,
} from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";
import { card, useLoad } from "../japan/jpFormat";
import { ErrorNote } from "../new_zealand/nzShared";

// Belgium pack overview (ZP-BE-ENG-001 §14 "Belgium readiness"): pack status,
// the release gates G1–G7 exactly as the backend computes them from evidence
// (Block C2, belgium_readiness) with every failing check, the golden
// certification (authority examples replayed exactly; the shared certification
// run the activation reads) and the signing counts. With no Belgian pack yet,
// offers the governed "create the Draft pack" action. No "ready" status is ever
// shown while a gate is NOT MET.

function SeedDraftPanel({ onDone }) {
  const [reason, setReason] = useState("");
  const [state, setState] = useState({ busy: false, error: null });
  const submit = async (e) => {
    e.preventDefault();
    setState({ busy: true, error: null });
    try {
      await seedBeDraftPack(reason.trim());
      setState({ busy: false, error: null });
      onDone?.();
    } catch (err) {
      setState({ busy: false, error: err.message || "Could not create the Draft pack." });
    }
  };
  return (
    <form onSubmit={submit} className={`${card} space-y-2`} data-testid="be-seed-draft">
      <h3 className="text-[14px] font-semibold text-foreground">No Belgium pack yet</h3>
      <p className="text-[12px] text-foreground-secondary">
        Creates the Draft pack from the content catalogue: every row PENDING G1 with no value. Nothing becomes Active here.
      </p>
      <label className={labelClass} htmlFor="be-seed-reason">Reason *</label>
      <input id="be-seed-reason" className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} />
      <ErrorNote message={state.error} />
      <button type="submit" disabled={state.busy || !reason.trim()}
        className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
        {state.busy ? "Creating…" : "Create the Draft pack"}
      </button>
    </form>
  );
}

function SigningCounts({ pack }) {
  const [status, error] = useLoad(() => getBeSigningStatus(pack.id));
  if (error) return <ErrorNote message={error} />;
  if (!status) return null;
  const items = [
    ["Pending (unsigned) rows", status.pendingRates.length],
    ["Rows without a value", status.emptyValues.length],
    ["Rows without a source", status.unsourced.length],
    ["Signed NOT_SUPPORTED", status.notSupported.length],
    ["Earning classes still REVIEW", status.reviewClasses],
  ];
  return (
    <div className={card} data-testid="be-signing-counts">
      <h3 className="mb-2 text-[14px] font-semibold text-foreground">Signing — {status.packId} v{status.version} ({status.status})</h3>
      <dl className="grid grid-cols-2 gap-2 text-[12px] md:grid-cols-5">
        {items.map(([label, value]) => (
          <div key={label} className="rounded-lg bg-surface-muted p-2">
            <dt className="text-foreground-muted">{label}</dt>
            <dd className="text-[16px] font-semibold text-foreground">{value}</dd>
          </div>
        ))}
      </dl>
      {status.activationRefusal && (
        <p className="mt-3 flex items-start gap-2 text-[12px] text-warning"><AlertTriangle size={14} /> {status.activationRefusal}</p>
      )}
    </div>
  );
}

function GoldenCertification({ pack }) {
  const [check, error, loading, reload] = useLoad(() => getBeGoldenCheck(pack.id));
  const [form, setForm] = useState({ name: "", description: "", case: "", sourceDocumentId: "", reason: "" });
  const [state, setState] = useState({ busy: false, error: null, notice: null });
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const act = async (fn, notice) => {
    setState({ busy: true, error: null, notice: null });
    try {
      const out = await fn();
      setState({ busy: false, error: null, notice: typeof notice === "function" ? notice(out) : notice });
      reload();
    } catch (err) {
      setState({ busy: false, error: err.message || "Refused.", notice: null });
    }
  };
  const register = (e) => {
    e.preventDefault();
    act(() => addBeAuthorityExample(pack.id, { ...form, sourceDocumentId: Number(form.sourceDocumentId) }),
      "Authority example registered.");
  };
  return (
    <div className={card} data-testid="be-golden">
      <h3 className="mb-1 text-[14px] font-semibold text-foreground">Golden certification (gate G1)</h3>
      <p className="text-[12px] text-foreground-secondary">
        Each official or independently prepared example is replayed through the engine with this pack&apos;s own rows;
        every expected figure must match exactly. The certification run is what pack activation requires.
      </p>
      <ErrorNote message={error || state.error} />
      {state.notice && <p role="status" className="text-[12px] text-success">{state.notice}</p>}
      {loading || !check ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        <>
          <p className="mt-2 text-[12px] text-foreground">
            {check.examples} example(s) · {check.passed ? "all replay exactly" : "not passing"}
          </p>
          <ul className="mt-1 space-y-1 text-[12px]">
            {check.results.map((r) => (
              <li key={r.rowId} className={r.ok ? "text-success" : "text-error"}>
                {r.example}: {r.ok ? "match" : r.error || r.failures.map((f) => `${f.field} expected ${f.expected}, got ${f.actual}`).join("; ")}
              </li>
            ))}
          </ul>
        </>
      )}
      <button type="button" disabled={state.busy} className="mt-2 rounded-lg bg-primary px-3 py-1.5 text-[12px] font-semibold text-white disabled:opacity-50"
        onClick={() => act(() => runBeGoldenCertification(pack.id), (out) => `Certification run #${out?.runId}: ${out?.status}.`)}>
        Record certification run
      </button>
      <form onSubmit={register} className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-2" aria-label="Register an authority example">
        <label className={labelClass}>Name *<input className={inputClass} value={form.name} onChange={set("name")} /></label>
        <label className={labelClass}>Reviewed source id *<input className={inputClass} inputMode="numeric"
          value={form.sourceDocumentId} onChange={set("sourceDocumentId")} /></label>
        <label className={`${labelClass} md:col-span-2`}>Description *<input className={inputClass} value={form.description}
          onChange={set("description")} /></label>
        <label className={`${labelClass} md:col-span-2`}>Worked case (inputs =&gt; expected; figures from the source)
          <input className={inputClass} value={form.case} onChange={set("case")} /></label>
        <label className={labelClass}>Reason *<input className={inputClass} value={form.reason} onChange={set("reason")} /></label>
        <div className="flex items-end">
          <button type="submit" disabled={state.busy} className="rounded-lg border border-border px-3 py-1.5 text-[12px]">Register example</button>
        </div>
      </form>
    </div>
  );
}

function GateDetails({ details }) {
  const red = (details || []).filter((g) => !g.passed);
  if (!red.length) return null;
  return (
    <ul className="mt-2 space-y-1 text-[12px]" data-testid="be-gate-details">
      {red.map((g) => (
        <li key={g.gate} className="text-foreground-secondary">
          <strong className="text-foreground">{g.gate} — {g.label}</strong>: {g.checks.filter((c) => !c.ok).map((c) => c.detail).join("; ")}
        </li>
      ))}
    </ul>
  );
}

export default function BEOverviewDashboard({ pack }) {
  const [summary, error, , reload] = useLoad(getBeSummary);
  if (error) return <ErrorNote message={error} />;
  if (!summary) return <p className="text-[12px] text-foreground-muted">Loading…</p>;
  return (
    <div className="space-y-4" data-testid="be-overview">
      <div className={card}>
        <h3 className="mb-1 text-[14px] font-semibold text-foreground">Belgium — {summary.spec}</h3>
        <p className="text-[12px] text-foreground-secondary">
          Engine status: <strong>{summary.status}</strong> · available for onboarding: <strong>{summary.available ? "yes" : "no"}</strong>
        </p>
        <h4 className="mt-3 mb-1 text-[12px] font-semibold text-foreground">Release gates</h4>
        <ul className="grid grid-cols-2 gap-1 text-[12px] md:grid-cols-7" data-testid="be-gates">
          {Object.entries(summary.gates || {}).map(([gate, state]) => (
            <li key={gate} className={state === "MET" ? "rounded border border-success/30 bg-success/5 px-2 py-1 text-success"
              : "rounded border border-error/30 bg-error/5 px-2 py-1 text-error"}>{gate}: {state}</li>
          ))}
        </ul>
        <GateDetails details={summary.gateDetails} />
      </div>
      {(summary.packs || []).length === 0 ? <SeedDraftPanel onDone={reload} /> : pack && <SigningCounts key={pack.id} pack={pack} />}
      {pack && <GoldenCertification key={`g${pack.id}`} pack={pack} />}
    </div>
  );
}
