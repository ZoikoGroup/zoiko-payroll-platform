import { useEffect, useState } from "react";
import { CheckCircle2, CircleAlert } from "lucide-react";
import { getSwissReadiness } from "../../../service/superAdminService";
import WorkerDataLocked from "../../WorkerDataLocked";

// Switzerland release gates G1-G7 (re-derived server-side on every read —
// never cached, never fabricated). The calculation preview against a real
// CH employee is retired for Super Admin (ZP-PRIV, worker data). Matches how SEReadinessTab/ITReadinessTab sit
// in their own workspaces: the same pack-management surface, Switzerland's
// readiness is org-independent so it renders for any selected pack.
function Readiness() {
  const [result, setResult] = useState({ data: null, error: null });
  useEffect(() => {
    let live = true;
    getSwissReadiness()
      .then((data) => { if (live) setResult({ data, error: null }); })
      .catch((e) => { if (live) setResult({ data: null, error: e?.message || "Failed to load readiness" }); });
    return () => { live = false; };
  }, []);
  if (result.error) return <p role="alert" className="text-xs text-error">{result.error}</p>;
  const { ready, gates = [], cantons = [], onDate } = result.data || {};
  if (!onDate) return <p className="text-xs text-foreground-muted">Loading readiness…</p>;

  const readyCantons = cantons.filter((c) => c.ready).length;

  return (
    <section aria-labelledby="ch-gates-heading" className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id="ch-gates-heading" className="text-sm font-semibold text-foreground">
          Release gates <span className="font-normal text-foreground-muted">(as of {onDate})</span>
        </h3>
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${ready ? "bg-success-light text-success" : "bg-warning-light text-warning"}`}>
          {ready ? "Ready to activate" : "Not ready — live Swiss payroll stays disabled"}
        </span>
        <span className="rounded-full bg-surface-muted px-2 py-0.5 text-[11px] text-foreground-muted">
          {readyCantons}/26 cantons staged
        </span>
      </div>
      <ul className="divide-y divide-border-light rounded-xl border border-border">
        {gates.map((g) => (
          <li key={g.key} className="flex items-start gap-2 px-3 py-2 text-xs">
            {g.complete
              ? <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-success" aria-label="Complete" />
              : <CircleAlert size={14} className="mt-0.5 shrink-0 text-warning" aria-label="Incomplete" />}
            <div>
              <p className="font-medium text-foreground">{g.label}</p>
              {g.detail && <p className="text-foreground-muted">{g.detail}</p>}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

// ZP-PRIV: the Swiss calculation preview loads a REAL PayrollEmployee
// (organizationId + employeeId) and echoes worker data, so the Super Admin
// route is retired (it needs a JIT Support Access grant). The preview is no
// longer offered here.
function Preview() {
  return (
    <section aria-labelledby="ch-preview-heading" className="space-y-3">
      <h3 id="ch-preview-heading" className="text-sm font-semibold text-foreground">Calculation preview</h3>
      <WorkerDataLocked variant="support" title="The Swiss preview runs on a real employee">
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Unlike the synthetic previews of other jurisdictions, this preview needs an actual employee record.
        </p>
      </WorkerDataLocked>
    </section>
  );
}

export default function CHReadinessTab() {
  return (
    <div className="space-y-6">
      <Readiness />
      <Preview />
    </div>
  );
}