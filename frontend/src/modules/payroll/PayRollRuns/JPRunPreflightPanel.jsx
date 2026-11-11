import { getJpRunPreflight } from "../../../service/payrollService";
import { useLoad } from "../../../components/jurisdiction/japan/jpFormat";

// Japan run preflight (ZP-JP-ENG-001): every JP payslip must carry its frozen
// calculation snapshot, and the approval fingerprint must still match.
// Approval / authorisation is refused server-side; this only shows why.

const SEVERITY = { BLOCK: "text-error", WARN: "text-warning", INFO: "text-foreground-muted" };

export default function JPRunPreflightPanel({ runId }) {
  const [result, error, loading] = useLoad(() => getJpRunPreflight(runId));
  return (
    <div className="mt-3 rounded-xl border border-border bg-surface p-4" data-testid="jp-run-preflight">
      <p className="text-[13px] font-semibold text-foreground">Japan preflight</p>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {loading && <p className="text-[12px] text-foreground-muted">Loading…</p>}
      {result && (
        <>
          <p className={`mt-1 text-[12px] font-semibold ${result.status === "OK" ? "text-success" : "text-error"}`}>
            {result.status === "OK" ? "Ready for approval" : "Blocked"}
          </p>
          <ul className="mt-2 space-y-1">
            {(result.checks || []).map((check, index) => (
              <li key={`${check.code}-${index}`} className={`text-[12px] ${SEVERITY[check.severity] || ""}`}>
                <span className="font-mono">{check.code}</span> — {check.message}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
