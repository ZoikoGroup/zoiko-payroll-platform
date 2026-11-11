import { getPlRunPreflight } from "../../../service/payrollService";
import { useLoad } from "../../../components/jurisdiction/japan/jpFormat";

// Poland run preflight (ZP-PL-ENG-001 §12): every PL payslip needs its frozen
// calculation, an ACTIVE verified employer registration, a PESEL in the vault
// (or a passport), the ZUS insurance title and no open statutory exception
// (minimum wage, cap crossing, PPK anomaly, pay timing). Approval and later
// steps are refused server-side; this panel only shows why.

export default function PLRunPreflightPanel({ runId }) {
  const [problems, error, loading] = useLoad(() => getPlRunPreflight(runId));
  const list = problems || [];
  return (
    <div className="mt-3 rounded-xl border border-border bg-surface p-4" data-testid="pl-run-preflight">
      <p className="text-[13px] font-semibold text-foreground">Poland preflight</p>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {loading && <p className="text-[12px] text-foreground-muted">Loading…</p>}
      {problems && (
        <>
          <p className={`mt-1 text-[12px] font-semibold ${list.length ? "text-error" : "text-success"}`}>
            {list.length ? "Blocked" : "Ready for approval"}
          </p>
          <ul className="mt-2 space-y-1">
            {list.map((p, index) => (
              <li key={`${p.code}-${index}`} className="text-[12px] text-error">
                <span className="font-mono">{p.code}</span>
                {p.employeeId ? ` (employee #${p.employeeId})` : ""} — {p.message}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
