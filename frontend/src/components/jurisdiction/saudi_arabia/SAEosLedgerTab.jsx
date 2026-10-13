import { useCallback, useEffect, useRef, useState } from "react";
import {
  listSaEosLedger,
  accrueSaEos,
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

export function SAEosLedgerTab({ organizationId, packId, disabled }) {
  const [ledger, ledgerError, ledgerLoading, reloadLedger] = useLoad(
    () => listSaEosLedger(organizationId),
    [organizationId]
  );
  const [accrueRunId, setAccrueRunId] = useState("");
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  async function act(fn, ok) {
    setError(null); setNotice(null);
    try { await fn(); setNotice(ok); reloadLedger(); } catch (e) { setError(e?.message || "Refused."); }
  }

  if (disabled) {
    return (
      <div className="space-y-4">
        <div className="rounded-xl border border-border bg-surface/50 p-4 text-center">
          <p className="text-[13px] text-foreground-muted">Select an organization from the picker above to manage EOS Ledger.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Messages error={error || ledgerError} notice={notice} />
      <section className={card} aria-labelledby="sa-eos-ledger">
        <h3 id="sa-eos-ledger" className="mb-1 text-[14px] font-semibold text-foreground">End-of-Service Accrual Ledger (SA-020/SA-021)</h3>
        <p className="mb-2 rounded-lg bg-surface-muted p-2 text-[12px] text-foreground-secondary">
          Incremental EOS award accrual per payroll run (Art. 84/85/87). Resignation fractions applied at final settlement.
        </p>
        {ledgerLoading ? (
          <p className="text-center text-[12px] text-foreground-muted py-4">Loading…</p>
        ) : ledger && (
          <table className="w-full" aria-label="EOS ledger entries">
            <thead>
              <tr>{["Employee", "Period From", "Period To", "Service Years", "Monthly Base", "Award Months", "Award Accrued", "Cumulative Award", "Status", "Source Run", ""].map((h) => <th key={h} className={th}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {ledger.length === 0 && <tr><td className={td} colSpan={11}>No EOS ledger entries yet.</td></tr>}
              {ledger.map((e) => (
                <tr key={e.id} className="border-t border-border">
                  <td className={td}>{e.employeeName || e.employeeId}</td>
                  <td className={td}>{e.periodFrom ? new Date(e.periodFrom).toLocaleDateString() : "—"}</td>
                  <td className={td}>{e.periodTo ? new Date(e.periodTo).toLocaleDateString() : "—"}</td>
                  <td className={td}>{e.serviceYears?.toFixed(2) ?? "—"}</td>
                  <td className={td}>SAR {e.monthlyBase ?? "—"}</td>
                  <td className={td}>{e.accrualMonths ?? "—"}</td>
                  <td className={td}>SAR {e.eosAwardAccrued ?? "—"}</td>
                  <td className={td}>SAR {e.cumulativeAward ?? "—"}</td>
                  <td className={td}><span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold ${e.status === "ACCRUED" ? "bg-success/10 text-success" : "bg-warning/10 text-warning"}`}>{label(e.status)}</span></td>
                  <td className={td}>{e.sourceRunId ?? "—"}</td>
                  <td className={td}></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div className="mt-3 flex flex-wrap items-end gap-2">
          <input aria-label="Run ID to accrue EOS from" placeholder="Run ID" className={`${input} w-28`} value={accrueRunId} onChange={(e) => setAccrueRunId(e.target.value)} />
          <button type="button" className={btn} disabled={!accrueRunId} onClick={() => act(() => accrueSaEos(organizationId, Number(accrueRunId)), "EOS accrual completed.")}>Accrue from Run</button>
        </div>
      </section>
    </div>
  );
}