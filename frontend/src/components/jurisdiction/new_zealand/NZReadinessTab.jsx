import { useState } from "react";
import { CheckCircle2, Circle } from "lucide-react";
import { getNzStatutorySummary, runNzGoldenCheck } from "../../../service/superAdminService";
import { card, useLoad } from "../japan/jpFormat";
import { ErrorNote } from "./nzShared";

// New Zealand release gates G1-G7 (ZP-NZ-ENG-001 §15, Phase 9). Every check is
// re-derived on the server from the canonical pack, the platform state and the
// recorded evidence (NZ-GATE-Gn, reviewed by someone other than its uploader);
// nothing is ticked here. New Zealand may be made AVAILABLE only when every
// gate and owner decision passes. The golden check replays the pack's Inland
// Revenue examples through the engine (read-only).

function Mark({ ok }) {
  return ok
    ? <CheckCircle2 size={14} className="shrink-0 text-success" aria-label="met" />
    : <Circle size={14} className="shrink-0 text-warning" aria-label="not met" />;
}

function GoldenCheck({ pack }) {
  const [report, setReport] = useState(null);
  const [state, setState] = useState({ busy: false, error: null });
  const run = async () => {
    setState({ busy: true, error: null });
    try {
      setReport(await runNzGoldenCheck(pack.id));
      setState({ busy: false, error: null });
    } catch (err) {
      setState({ busy: false, error: err.message || "The golden check failed to run." });
    }
  };
  return (
    <section className={card} data-testid="nz-golden-check">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-[14px] font-semibold text-foreground">Golden check (gate G1)</h3>
          <p className="text-[11px] text-foreground-muted">
            Replays every Inland Revenue example of {pack.packId} v{pack.version} through the engine with this pack&apos;s
            own values. Every expected figure must match exactly.
          </p>
        </div>
        <button type="button" onClick={run} disabled={state.busy}
          className="rounded-lg border border-border px-3 py-1.5 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted disabled:opacity-50">
          Run golden check
        </button>
      </div>
      <ErrorNote message={state.error} />
      {report && (
        <div className="mt-2 text-[12px]">
          <p className={report.passed ? "text-success" : "text-warning"}>
            {report.examples === 0 ? "No Inland Revenue examples are loaded yet (Authority tables tab)."
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
    </section>
  );
}

export default function NZReadinessTab({ pack }) {
  const [summary, error, loading] = useLoad(() => getNzStatutorySummary());
  const state = summary?.readiness;
  return (
    <div className="space-y-4" data-testid="nz-readiness">
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {loading && <p className="text-[12px] text-foreground-muted">Loading…</p>}
      {state && (
        <>
          <div className={`rounded-xl border p-3 text-[12px] ${state.allPassed ? "border-success/40 bg-success/10" : "border-warning/40 bg-warning/10"}`}>
            {state.allPassed
              ? "Every release gate and owner decision passes. New Zealand may be made available."
              : `New Zealand stays PLANNED: ${state.gates.filter((g) => g.passed).length} of ${state.gates.length} gates pass. The gates below show exactly what is still missing.`}
          </div>
          {pack && <GoldenCheck pack={pack} />}
          {state.gates.map((gate) => (
            <section key={gate.gate} className={card} data-testid={`nz-gate-${gate.gate}`}>
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
          <section className={card} data-testid="nz-owner-decisions">
            <h3 className="mb-2 text-[14px] font-semibold text-foreground">Owner decisions</h3>
            <ul className="space-y-1">
              {(state.decisions || []).map((d) => (
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
