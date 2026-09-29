import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { getSgRunPreflight } from "../../../service/payrollService";

// Singapore run workspace — stages 1 (Preflight), 2 (Earnings: CPF OW/AW and
// IRAS chips) and 4 (Exceptions) of ZP-SG-ENG-001 §11. The server dry-runs
// the engine and decides every check; BLOCK items refuse approval
// server-side. This panel only displays the result.

const SEVERITY_STYLE = {
  BLOCK: "bg-error/10 text-error border-error/30",
  WARN: "bg-warning/10 text-warning border-warning/30",
  INFO: "bg-surface-muted text-foreground-muted border-border",
};
const STATUS_STYLE = { BLOCKED: "text-error", REVIEW: "text-warning", CLEAR: "text-primary" };
const IRAS_LABEL = {
  iras_gross_salary: "IR8A a · Salary", iras_bonus: "IR8A b · Bonus", iras_director_fees: "IR8A c · Director fees",
  iras_allowances: "IR8A d1 · Allowances", iras_gross_commission: "Gross commission", iras_lump_sum: "IR8A d3 · Lump sum",
  iras_exempt: "Exempt", UNCLASSIFIED: "Unclassified",
};

export default function SGRunPreflightPanel({ runId }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    getSgRunPreflight(runId)
      .then((res) => active && setData(res))
      .catch((err) => active && setError(err?.message || "Singapore preflight could not be loaded."));
    return () => { active = false; };
  }, [runId]);

  if (error) return <p className="mb-5 text-[12px] text-error" role="alert">{error}</p>;
  if (!data) {
    return (
      <div className="mb-5 flex items-center gap-2 text-[12px] text-foreground-muted" role="status">
        <Loader2 size={14} className="animate-spin" /> Running Singapore preflight…
      </div>
    );
  }
  const earnings = Object.entries(data.earnings || {});
  return (
    <section className="mb-5 rounded-[18px] border border-border p-5" aria-labelledby="sg-preflight-heading">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h4 id="sg-preflight-heading" className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">
          Singapore preflight &amp; exceptions
        </h4>
        <p className="text-[12px] text-foreground-muted">
          Wage month {data.wageMonth || "—"} · {data.pack || "no Active pack"} ·{" "}
          <span className={`font-semibold ${STATUS_STYLE[data.status] || ""}`}>{data.status}</span>{" "}
          ({data.counts?.BLOCK || 0} block · {data.counts?.WARN || 0} warn · {data.counts?.INFO || 0} info)
        </p>
      </div>
      {data.status === "BLOCKED" && (
        <p className="mb-3 text-[12px] text-error">Approval is refused until every BLOCK item is resolved.</p>
      )}
      {data.checks?.length ? (
        <ul className="space-y-2">
          {data.checks.map((c, i) => (
            <li key={`${c.code}-${c.employeeId ?? "run"}-${i}`}
                className={`rounded-[12px] border px-3 py-2 text-[12px] ${SEVERITY_STYLE[c.severity] || ""}`}>
              <span className="font-semibold">{c.severity}</span> · {c.employeeCode ? `${c.employeeCode} · ` : ""}
              <span className="font-mono">{c.code}</span> — {c.message}
              {c.action && <span className="block text-foreground-muted">Action: {c.action}</span>}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[12px] text-foreground-muted">No preflight findings.</p>
      )}
      {earnings.length > 0 && (
        <div className="mt-4">
          <h5 className="mb-2 text-[11px] font-bold uppercase tracking-widest text-foreground-muted">
            Earnings — CPF and IRAS classification
          </h5>
          <div className="overflow-x-auto rounded-[12px] border border-border">
            <table className="w-full text-[12px]">
              <caption className="sr-only">Per-earning CPF Ordinary/Additional Wage and IRAS IR8A classification</caption>
              <thead className="bg-surface-muted text-foreground-muted">
                <tr>
                  <th scope="col" className="px-3 py-2 text-left">Employee</th>
                  <th scope="col" className="px-3 py-2 text-left">Earning</th>
                  <th scope="col" className="px-3 py-2 text-right">Amount (S$)</th>
                  <th scope="col" className="px-3 py-2 text-left">CPF</th>
                  <th scope="col" className="px-3 py-2 text-left">IRAS</th>
                </tr>
              </thead>
              <tbody>
                {earnings.flatMap(([id, e]) => (e.lines || []).map((l) => (
                  <tr key={`${id}-${l.component}`} className="border-t border-border">
                    <td className="px-3 py-1.5">{e.employeeCode}</td>
                    <td className="px-3 py-1.5">{l.label}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{l.amount}</td>
                    <td className="px-3 py-1.5">{l.cpfClass === "NON_CPF" ? "Not CPF wages" : l.cpfClass}{l.cpfSource === "rule" ? " (rule)" : ""}</td>
                    <td className="px-3 py-1.5">{IRAS_LABEL[l.irasCategory] || l.irasCategory || "—"}</td>
                  </tr>
                )))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
