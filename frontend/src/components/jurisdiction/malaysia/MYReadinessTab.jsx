import { useState } from "react";
import { CheckCircle2, Circle } from "lucide-react";
import { addMyAuthorityExample, getMySummary, runMyGoldenCheck } from "../../../service/superAdminService";
import { card, useLoad } from "../japan/jpFormat";

// Malaysia release gates G1-G7 (ZP-MY-ENG-001 §16, Phase 10). Every check is
// re-derived on the server from the canonical pack, the platform state and
// the recorded evidence (MY-GATE-Gn, reviewed by someone other than its
// uploader); nothing is ticked here. Malaysia may be made AVAILABLE only when
// every gate and launch-blocking owner decision passes. The golden check
// replays the pack's official worked examples through the engine (read-only);
// while PCB is blocked (Phase 4) contribution-only examples can still be
// proven, but gate G1 needs a HASiL PCB example. An example is added only
// with a reviewed source.

const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
const button = "rounded-lg border border-border px-3 py-1.5 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted disabled:opacity-50";

function Mark({ ok }) {
  return ok
    ? <CheckCircle2 size={14} className="shrink-0 text-success" aria-label="met" />
    : <Circle size={14} className="shrink-0 text-warning" aria-label="not met" />;
}

function AddExample({ pack, onAdded }) {
  const empty = { name: "", taxFormula: "", sourceDocumentId: "", reason: "" };
  const [form, setForm] = useState(empty);
  const [state, setState] = useState({ busy: false, error: null, notice: null });
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const submit = async (e) => {
    e.preventDefault();
    setState({ busy: true, error: null, notice: null });
    try {
      await addMyAuthorityExample(pack.id, { ...form, sourceDocumentId: Number(form.sourceDocumentId) });
      setForm(empty);
      setState({ busy: false, error: null, notice: "Example added. Run the golden check." });
      onAdded();
    } catch (err) {
      setState({ busy: false, error: err.message || "The example was refused.", notice: null });
    }
  };
  return (
    <form onSubmit={submit} className="mt-3 grid gap-2 sm:grid-cols-2" aria-label="Add an authority example"
      data-testid="my-add-example">
      <input className={input} value={form.name} onChange={set("name")} maxLength={20} required
        placeholder="Name (e.g. EPF-2026-01)" aria-label="Example name" />
      <input className={input} value={form.sourceDocumentId} onChange={set("sourceDocumentId")} required
        inputMode="numeric" placeholder="Reviewed source document id" aria-label="Source document id" />
      <input className={`${input} sm:col-span-2 font-mono`} value={form.taxFormula} onChange={set("taxFormula")}
        maxLength={150} required aria-label="Example formula"
        placeholder="G=…;D=YYYY-MM-DD;CLS=MY_PR_BELOW_60 => epfEe=…;epfEr=…;socsoEe=…;eisEe=…;pcb=…" />
      <input className={`${input} sm:col-span-2`} value={form.reason} onChange={set("reason")} required
        placeholder="Reason (where the example comes from)" aria-label="Reason" />
      <div className="sm:col-span-2 flex items-center gap-2">
        <button type="submit" className={button} disabled={state.busy}>Add example</button>
        {state.error && <span role="alert" className="text-[12px] text-error">{state.error}</span>}
        {state.notice && <span role="status" className="text-[12px] text-success">{state.notice}</span>}
      </div>
    </form>
  );
}

function GoldenCheck({ pack }) {
  const [report, setReport] = useState(null);
  const [state, setState] = useState({ busy: false, error: null });
  const run = async () => {
    setState({ busy: true, error: null });
    try {
      setReport(await runMyGoldenCheck(pack.id));
      setState({ busy: false, error: null });
    } catch (err) {
      setState({ busy: false, error: err.message || "The golden check failed to run." });
    }
  };
  return (
    <section className={card} data-testid="my-golden-check">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-[14px] font-semibold text-foreground">Golden check (gate G1)</h3>
          <p className="text-[11px] text-foreground-muted">
            Replays every official or independently prepared example of {pack.packId} v{pack.version} through the
            engine with this pack&apos;s own values. Every expected figure must match exactly.
          </p>
        </div>
        <button type="button" onClick={run} disabled={state.busy} className={button}>Run golden check</button>
      </div>
      {state.error && <p role="alert" className="mt-2 text-[12px] text-error">{state.error}</p>}
      {report && (
        <div className="mt-2 text-[12px]">
          <p className={report.passed ? "text-success" : "text-warning"}>
            {report.examples === 0 ? "No authority examples are recorded yet."
              : report.passed ? `All ${report.examples} example(s) match exactly.`
                : `${report.results.filter((r) => !r.ok).length} of ${report.examples} example(s) do not match.`}
          </p>
          <ul className="mt-1 space-y-1">
            {report.results.map((r) => (
              <li key={r.rowId} className="flex items-start gap-2">
                <Mark ok={r.ok} />
                <span>
                  <span className="font-mono text-[11px]">{r.example}</span>
                  {r.error && <> — {r.error}</>}
                  {r.failures.map((f) => (
                    <span key={f.field} className="block text-foreground-muted">
                      {f.field}: expected {f.expected}, engine {f.actual}
                    </span>
                  ))}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {pack.status === "Draft" && <AddExample pack={pack} onAdded={() => setReport(null)} />}
    </section>
  );
}

export default function MYReadinessTab({ pack }) {
  const [summary, error, loading] = useLoad(() => getMySummary());
  const state = summary?.readiness;
  const decisions = summary?.decisions || [];
  return (
    <div className="space-y-4" data-testid="my-readiness">
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {loading && <p className="text-[12px] text-foreground-muted">Loading…</p>}
      {state && (
        <>
          <div className={`rounded-xl border p-3 text-[12px] ${state.allPassed ? "border-success/40 bg-success/10" : "border-warning/40 bg-warning/10"}`}>
            {state.allPassed
              ? "Every release gate and launch-blocking owner decision passes. Malaysia may be made available."
              : `Malaysia stays PLANNED: ${state.gates.filter((g) => g.passed).length} of ${state.gates.length} gates pass. The gates below show exactly what is still missing.`}
          </div>
          {pack && <GoldenCheck pack={pack} />}
          {state.gates.map((gate) => (
            <section key={gate.gate} className={card} data-testid={`my-gate-${gate.gate}`}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-[14px] font-semibold text-foreground">{gate.gate} — {gate.label}</h3>
                  <p className="text-[11px] text-foreground-muted">Owner: {gate.owner} · checklist {gate.checklist}</p>
                </div>
                <span className={`text-[12px] font-semibold ${gate.passed ? "text-success" : "text-warning"}`}>
                  {gate.passed ? "Passed" : "Open"}
                </span>
              </div>
              <ul className="mt-2 space-y-1">
                {gate.checks.map((check) => (
                  <li key={check.key} className="flex items-start gap-2 text-[12px]">
                    <Mark ok={check.ok} />
                    <span><span className="font-mono text-[11px]">{check.key}</span> — {check.detail}</span>
                  </li>
                ))}
                {gate.evidence.map((ev) => (
                  <li key={ev.tag} className="flex items-start gap-2 text-[12px]">
                    <Mark ok={ev.state === "RECORDED"} />
                    <span>Evidence <span className="font-mono text-[11px]">{ev.tag}</span> — {ev.state}</span>
                  </li>
                ))}
              </ul>
            </section>
          ))}
          <section className={card} data-testid="my-owner-decisions">
            <h3 className="mb-2 text-[14px] font-semibold text-foreground">Owner decisions</h3>
            <ul className="space-y-1">
              {decisions.map((d) => (
                <li key={d.key} className="flex items-start gap-2 text-[12px]">
                  <Mark ok={d.state === "RECORDED"} />
                  <span>{d.key} — {d.label} · <span className="font-mono text-[11px]">{d.evidenceTag}</span> {d.state}
                    {d.blocksLaunch && d.state !== "RECORDED" ? " (blocks launch)" : ""}</span>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  );
}
