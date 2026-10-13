import { useCallback, useEffect, useRef, useState } from "react";
import {
  listSaGosiLiabilities,
  buildSaGosiLiability,
  markSaGosiLiabilityPaid,
} from "../../../service/superAdminService";

const card = "rounded-xl border border-border bg-surface p-4";
const th = "px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-foreground-muted";
const td = "px-2 py-1.5 text-[12px] text-foreground align-top";
const btn = "rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground hover:bg-surface-muted disabled:opacity-40";
const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
const label = (s) => (s || "").replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());

function useLoad(loadFn, deps = []) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadFnRef = useRef(loadFn);
  useEffect(() => { loadFnRef.current = loadFn; }, [loadFn]);

  const reload = useCallback(() => {
    setLoading(true);
    setError(null);
    loadFnRef.current()
      .then((d) => { setData(d); setError(null); })
      .catch((e) => setError(e?.message || "Could not load."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { reload(); }, deps);

  return [data, error, loading, reload];
}

function Messages({ error, notice }) {
  return (
    <>
      {error && <p role="alert" className="text-[13px] text-error">{error}</p>}
      {notice && <p role="status" className="text-[13px] text-success">{notice}</p>}
    </>
  );
}

export function SAGosiLiabilityTab({ organizationId, packId, disabled }) {
  const [liabilities, liabilitiesError, liabilitiesLoading, reloadLiabilities] = useLoad(
    () => listSaGosiLiabilities(organizationId),
    [organizationId]
  );
  const [buildRunId, setBuildRunId] = useState("");
  const [payId, setPayId] = useState("");
  const [payRef, setPayRef] = useState("");
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  async function act(fn, ok) {
    setError(null); setNotice(null);
    try { await fn(); setNotice(ok); reloadLiabilities(); } catch (e) { setError(e?.message || "Refused."); }
  }

  if (disabled) {
    return (
      <div className="space-y-4">
        <div className="rounded-xl border border-border bg-surface/50 p-4 text-center">
          <p className="text-[13px] text-foreground-muted">Select an organization from the picker above to manage GOSI Liability.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Messages error={error || liabilitiesError} notice={notice} />
      <section className={card} aria-labelledby="sa-gosi-liab">
        <h3 id="sa-gosi-liab" className="mb-1 text-[14px] font-semibold text-foreground">Monthly GOSI Liability (SA-024)</h3>
        <p className="mb-2 rounded-lg bg-surface-muted p-2 text-[12px] text-foreground-secondary">
          Aggregated employer/employee pension, SANED, and occupational hazard from a committed payroll run. Idempotent per month.
        </p>
        {liabilitiesLoading ? (
          <p className="text-center text-[12px] text-foreground-muted py-4">Loading…</p>
        ) : liabilities && (
          <table className="w-full" aria-label="GOSI liabilities">
            <thead>
              <tr>{["Month", "Emp. Pension", "Er. Pension", "Emp. SANED", "Er. SANED", "Er. OH", "Total Due", "Status", "Source Run", "Paid Ref", ""].map((h) => <th key={h} className={th}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {liabilities.length === 0 && <tr><td className={td} colSpan={11}>No GOSI liabilities recorded.</td></tr>}
              {liabilities.map((g) => (
                <tr key={g.id} className="border-t border-border">
                  <td className={td}>{g.contributionMonth ? new Date(g.contributionMonth).toLocaleDateString("en-GB", { month: "short", year: "numeric" }) : "—"}</td>
                  <td className={td}>SAR {g.pensionEmployee ?? "—"}</td>
                  <td className={td}>SAR {g.pensionEmployer ?? "—"}</td>
                  <td className={td}>SAR {g.sanedEmployee ?? "—"}</td>
                  <td className={td}>SAR {g.sanedEmployer ?? "—"}</td>
                  <td className={td}>SAR {g.occupationalHazardEmployer ?? "—"}</td>
                  <td className={td}>SAR {g.totalDue ?? "—"}</td>
                  <td className={td}><span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold ${g.status === "PAID" ? "bg-success/10 text-success" : "bg-warning/10 text-warning"}`}>{label(g.status)}</span></td>
                  <td className={td}>{g.sourceRunId ?? "—"}</td>
                  <td className={td}>{g.paymentReference || "—"}</td>
                  <td className={td}>{g.status === "DRAFT" && <button type="button" className={btn} onClick={() => act(() => markSaGosiLiabilityPaid(organizationId, g.id, window.prompt("Payment reference") || ""), `Liability marked paid.`)}>Mark Paid</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div className="mt-3 flex flex-wrap items-end gap-2">
          <input aria-label="Run ID to build liability from" placeholder="Run ID" className={`${input} w-28`} value={buildRunId} onChange={(e) => setBuildRunId(e.target.value)} />
          <button type="button" className={btn} disabled={!buildRunId} onClick={() => act(() => buildSaGosiLiability(organizationId, Number(buildRunId)), "GOSI liability built from run.")}>Build from Run</button>
        </div>
      </section>
    </div>
  );
}