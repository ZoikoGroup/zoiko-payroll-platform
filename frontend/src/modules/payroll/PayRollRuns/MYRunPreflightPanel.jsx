import { getMyRunPreflight } from "../../../service/payrollService";
import { useLoad } from "../../../components/jurisdiction/japan/jpFormat";

// Malaysia run preflight (ZP-MY-ENG-001): every MY payslip needs its frozen
// calculation, an ACTIVE verified employer registration, a work assignment,
// an NRIC in the vault (or a passport), a reviewed tax residence, a valid
// work pass for non-citizens, no overdue / undated employer event, a
// clearance hold where one is required and no open statutory exception
// (minimum wage). Approval is refused server-side; this panel only shows why.

export default function MYRunPreflightPanel({ runId }) {
  const [problems, error, loading] = useLoad(() => getMyRunPreflight(runId));
  const list = problems || [];
  return (
    <div className="mt-3 rounded-xl border border-border bg-surface p-4" data-testid="my-run-preflight">
      <p className="text-[13px] font-semibold text-foreground">Malaysia preflight</p>
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
