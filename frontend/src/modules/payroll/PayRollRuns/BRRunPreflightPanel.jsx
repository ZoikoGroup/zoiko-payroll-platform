import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { getBrRunPreflight, getBrRunFingerprint } from "../../../service/payrollService";

// Brazil run workspace — preflight + exceptions (ZP-BR-ENG-001 Phase 6).
// The server decides every check; a BLOCK refuses approval server-side.
// The approval fingerprint binds every payslip's frozen BR inputs
// (content hash, trace, bases, employer charges) — BR-034.

const TONE = { BLOCK: "text-error", WARN: "text-warning" };

export default function BRRunPreflightPanel({ runId }) {
  const [data, setData] = useState(null);
  const [fingerprint, setFingerprint] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    Promise.all([getBrRunPreflight(runId), getBrRunFingerprint(runId)])
      .then(([pre, fp]) => { if (active) { setData(pre); setFingerprint(fp); } })
      .catch((err) => active && setError(err?.message || "Brazil preflight could not be loaded."));
    return () => { active = false; };
  }, [runId]);

  if (error) return <p className="mb-5 text-[12px] text-error" role="alert">{error}</p>;
  if (!data) {
    return (
      <div className="mb-5 flex items-center gap-2 text-[12px] text-foreground-muted" role="status">
        <Loader2 size={14} className="animate-spin" /> Running Brazil preflight…
      </div>
    );
  }
  const checks = data.checks || [];
  return (
    <section className="mb-5 rounded-[18px] border border-border p-5" aria-labelledby="br-preflight-heading">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h4 id="br-preflight-heading" className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">
          Brazil preflight & exceptions
        </h4>
        <p className="text-[12px] text-foreground-muted">
          {data.status === "OK" ? "No findings" : data.status === "BLOCKED" ? "Blocked" : "Warnings only"}
          {fingerprint?.fingerprint && <> · fingerprint <code className="text-[11px]">{fingerprint.fingerprint.slice(0, 12)}…</code></>}
          {fingerprint?.stored && " · bound at approval"}
        </p>
      </div>
      {data.status === "BLOCKED" && (
        <p className="mb-3 text-[12px] text-error">Approval is refused until every BLOCK item is resolved.</p>
      )}
      {checks.length === 0 ? (
        <p className="text-[12px] text-foreground-muted">No preflight findings.</p>
      ) : (
        <ul className="space-y-2">
          {checks.map((c, i) => (
            <li key={`${c.key}-${c.employeeId}-${i}`} className="rounded-[12px] border border-border px-3 py-2 text-[12px]">
              <span className={`font-semibold ${TONE[c.severity] || "text-foreground"}`}>{c.severity}</span>
              <span className="text-foreground"> · {c.reason}</span>
              {c.employeeId && <span className="text-foreground-muted"> · employee #{c.employeeId}</span>}
              {c.action && <p className="mt-0.5 text-foreground-muted">{c.action}</p>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}