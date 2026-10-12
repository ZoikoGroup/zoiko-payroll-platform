import { useCallback, useEffect, useState } from "react";
import { approveHkCorrection, listHkCorrections, rejectHkCorrection } from "../../../service/payrollService";
import { hkLabel } from "../../../components/jurisdiction/hong_kong/hkLabels";

// Hong Kong payroll corrections (gap-closure D-14). A committed payslip is never
// edited: a correction is a linked delta in its own correction run, booked to
// the original period. The requester can never approve (the server enforces
// it); approval applies every statutory consequence in one step, listed here.
const input = "w-full rounded-lg border border-border bg-surface px-3 py-2 text-[13px] text-foreground";
const btn = "rounded-lg bg-primary px-3 py-1.5 text-[12px] font-semibold text-white disabled:opacity-60";
const btnGhost = "rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground";
const card = "rounded-xl border border-border bg-surface p-4";

const GROUPS = [
  ["ird", "IRD returns"], ["empf", "eMPF"], ["taxClearance", "IR56G tax clearance"], ["payment", "Payment"],
  ["averageWage", "Average wage"], ["termination", "Termination"], ["reports", "Generated reports"],
  ["employeeCopies", "Employee copies"],
];

function Consequences({ consequences }) {
  if (!consequences || consequences.discarded) return null;
  const rows = GROUPS.flatMap(([key, label]) => (consequences[key] || []).map((c, i) => ({ key: `${key}-${i}`, label, c })));
  if (!rows.length) return <p className="text-[12px] text-foreground-muted">No statutory follow-up needed.</p>;
  return (
    <ul className="mt-2 space-y-1 text-[12px] text-foreground">
      {rows.map(({ key, label, c }) => (
        <li key={key}>
          <span className="font-semibold">{label}:</span> {hkLabel(c.action)}
          {c.form ? ` · ${c.form}` : ""}{c.caseId ? ` case #${c.caseId}` : ""}{c.amendmentCaseId ? ` → amendment #${c.amendmentCaseId}` : ""}
          {c.period ? ` · ${c.period}` : ""}{c.reportType ? ` · ${hkLabel(c.reportType)}` : ""}
          {c.netDelta !== undefined ? ` · HK$ ${c.netDelta}` : ""}
        </li>
      ))}
    </ul>
  );
}

export default function HKCorrectionsPanel() {
  const [rows, setRows] = useState([]);
  const [reasons, setReasons] = useState({});
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const load = useCallback(() => listHkCorrections().then(setRows).catch(() => setRows([])), []);
  useEffect(() => { load(); }, [load]);

  async function act(fn, ok) {
    setError(null);
    setNotice(null);
    try {
      await fn();
      setNotice(ok);
      load();
    } catch (err) {
      setError(err?.message || "The step was not accepted.");
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-[12px] text-foreground-secondary">
        Request a correction from a committed payroll run (Payroll Runs → run detail). A different operator approves it here.
        The original payslip and its filed evidence are never changed.
      </p>
      <div aria-live="polite">
        {error && <p role="alert" className="text-[12px] font-medium text-error">{error}</p>}
        {notice && <p role="status" className="text-[12px] font-medium text-success">{notice}</p>}
      </div>
      {!rows.length && <p className="text-[12px] text-foreground-muted">No payroll corrections.</p>}
      {rows.map((c) => (
        <div key={c.id} className={card}>
          <p className="text-[13px] font-semibold text-foreground">
            Correction #{c.id} · payslip {c.originalPayslipId} · {hkLabel(c.status)}
          </p>
          <p className="text-[12px] text-foreground-secondary">
            Net pay HK$ {c.netPayDelta} · gross HK$ {c.grossPayDelta} · MPF employee HK$ {c.employeeMpfDelta} · employer HK$ {c.employerMpfDelta}
          </p>
          <p className="text-[12px] text-foreground-muted">Reason: {c.reason}</p>
          {(c.warnings || []).length > 0 && (
            <ul className="mt-1 list-disc pl-5 text-[12px] text-warning">
              {c.warnings.map((w) => <li key={w.code}>{w.message}</li>)}
            </ul>
          )}
          {c.status === "REQUESTED" && (
            <div className="mt-2 flex flex-wrap gap-1">
              <button type="button" className={btn} onClick={() => act(() => approveHkCorrection(c.id), `Correction #${c.id} approved.`)}>
                Approve (different operator)
              </button>
              <input aria-label={`Rejection reason for correction ${c.id}`} placeholder="Reason for rejecting" className={input}
                onChange={(e) => setReasons({ ...reasons, [c.id]: e.target.value })} />
              <button type="button" className={btnGhost} onClick={() => act(() => rejectHkCorrection(c.id, reasons[c.id] || ""), `Correction #${c.id} rejected.`)}>
                Reject
              </button>
            </div>
          )}
          {c.status === "APPROVED" && <Consequences consequences={c.consequences} />}
          {c.status === "REJECTED" && <p className="mt-1 text-[12px] text-foreground-muted">Rejected: {c.rejectedReason}</p>}
        </div>
      ))}
    </div>
  );
}
