import { getNzRunFingerprint, getNzRunPreflight } from "../../../service/payrollService";
import { useLoad } from "../../../components/jurisdiction/japan/jpFormat";

// New Zealand run preflight (ZP-NZ-ENG-001 §12): every NZ payslip needs its
// frozen calculation, an ACTIVE verified employer profile, no open statutory
// exception (minimum wage, child-support shortfall), calculated leave pay and,
// for a FINAL run, an approved final pay case. After approval the fingerprint
// must still match. Approval and later steps are refused server-side; this
// panel only shows why.

export default function NZRunPreflightPanel({ runId }) {
  const [preflight, error, loading] = useLoad(() => getNzRunPreflight(runId));
  const [fingerprint] = useLoad(() => getNzRunFingerprint(runId));
  const problems = preflight?.problems || [];
  return (
    <div className="mt-3 rounded-xl border border-border bg-surface p-4" data-testid="nz-run-preflight">
      <p className="text-[13px] font-semibold text-foreground">New Zealand preflight</p>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {loading && <p className="text-[12px] text-foreground-muted">Loading…</p>}
      {preflight && (
        <>
          <p className={`mt-1 text-[12px] font-semibold ${problems.length ? "text-error" : "text-success"}`}>
            {problems.length ? "Blocked" : "Ready for approval"}
          </p>
          <ul className="mt-2 space-y-1">
            {problems.map((p, index) => (
              <li key={`${p.code}-${index}`} className="text-[12px] text-error">
                <span className="font-mono">{p.code}</span>
                {p.employeeId ? ` (employee #${p.employeeId})` : ""} — {p.message}
              </li>
            ))}
          </ul>
        </>
      )}
      {fingerprint?.stored && (
        <p className={`mt-2 text-[12px] ${fingerprint.matches ? "text-success" : "text-error"}`}>
          {fingerprint.matches
            ? "Approved calculation unchanged."
            : "The calculation changed after approval — recalculate and approve again."}
        </p>
      )}
    </div>
  );
}
