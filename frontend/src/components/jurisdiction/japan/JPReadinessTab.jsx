import { CheckCircle2, Circle } from "lucide-react";
import { getJpStatutorySummary } from "../../../service/superAdminService";
import { card, useLoad } from "./jpFormat";

// Japan release gates G0-G8 (ZP-JP-ENG-001 §14). Every check is re-derived
// on the server from the canonical pack and the recorded evidence; nothing
// is ticked here. Japan opens only when every gate and owner decision passes.

function Mark({ ok }) {
  return ok
    ? <CheckCircle2 size={14} className="shrink-0 text-success" aria-label="met" />
    : <Circle size={14} className="shrink-0 text-warning" aria-label="not met" />;
}

export default function JPReadinessTab() {
  const [summary, error, loading] = useLoad(() => getJpStatutorySummary());
  const state = summary?.readiness;
  return (
    <div className="space-y-4" data-testid="jp-readiness">
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {loading && <p className="text-[12px] text-foreground-muted">Loading…</p>}
      {state && (
        <>
          <div className={`rounded-xl border p-3 text-[12px] ${state.allPassed ? "border-success/40 bg-success/10" : "border-warning/40 bg-warning/10"}`}>
            {state.allPassed
              ? "Every release gate passes. Japan may be made available."
              : "Japan stays PLANNED: the gates below show exactly what is still missing."}
          </div>
          {state.gates.map((gate) => (
            <section key={gate.gate} className={card} data-testid={`jp-gate-${gate.gate}`}>
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
        </>
      )}
    </div>
  );
}
