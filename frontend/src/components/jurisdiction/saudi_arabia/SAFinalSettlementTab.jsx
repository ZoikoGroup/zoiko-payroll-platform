import { useCallback, useEffect, useRef, useState } from "react";
import {
  listSaFinalSettlements,
  createSaFinalSettlement,
  approveSaFinalSettlement,
  paySaFinalSettlement,
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

const EXIT_REASONS = ["TERMINATION", "RESIGNATION"];

export function SAFinalSettlementTab({ organizationId, packId, disabled }) {
  const [settlements, settlementsError, settlementsLoading, reloadSettlements] = useLoad(
    () => listSaFinalSettlements(organizationId),
    [organizationId]
  );
  const [form, setForm] = useState({ 
    employeeId: "", 
    terminationType: "TERMINATION", 
    terminationDate: new Date().toISOString().slice(0, 10), 
    noticeDays: 0, 
    unusedLeaveDays: 0, 
    repatriationAmount: 0, 
    otherDues: 0, 
    status: "DRAFT" 
  });
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  async function act(fn, ok) {
    setError(null); setNotice(null);
    try { await fn(); setNotice(ok); reloadSettlements(); } catch (e) { setError(e?.message || "Refused."); }
  }

  if (disabled) {
    return (
      <div className="space-y-4">
        <div className="rounded-xl border border-border bg-surface/50 p-4 text-center">
          <p className="text-[13px] text-foreground-muted">Select an organization from the picker above to manage Final Settlement.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Messages error={error || settlementsError} notice={notice} />
      <section className={card} aria-labelledby="sa-final-sttl">
        <h3 id="sa-final-sttl" className="mb-1 text-[14px] font-semibold text-foreground">Final Settlement (SA-026/SA-027)</h3>
        <p className="mb-2 rounded-lg bg-surface-muted p-2 text-[12px] text-foreground-secondary">
          EOS award (Art. 84/85/87) plus leave/notice/repatriation dues. Maker-checker: a distinct Super Admin approves, then pays.
        </p>
        {settlementsLoading ? (
          <p className="text-center text-[12px] text-foreground-muted py-4">Loading…</p>
        ) : settlements && (
          <table className="w-full" aria-label="Final settlements">
            <thead>
              <tr>{["Employee", "Exit Reason", "Exit Date", "EOS Award", "Notice Pay", "Leave Pay", "Repatriation", "Other", "Total", "Status", "Approved By", "Paid Ref", ""].map((h) => <th key={h} className={th}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {settlements.length === 0 && <tr><td className={td} colSpan={13}>No final settlements yet.</td></tr>}
              {settlements.map((s) => (
                <tr key={s.id} className="border-t border-border">
                  <td className={td}>{s.employeeName || s.employeeId}</td>
                  <td className={td}>{label(s.terminationType)}</td>
                  <td className={td}>{s.terminationDate ? new Date(s.terminationDate).toLocaleDateString() : "—"}</td>
                  <td className={td}>SAR {s.eosAward ?? "—"}</td>
                  <td className={td}>SAR {s.noticePay ?? "—"}</td>
                  <td className={td}>SAR {s.leavePay ?? "—"}</td>
                  <td className={td}>SAR {s.repatriationAmount ?? "—"}</td>
                  <td className={td}>SAR {s.otherDues ?? "—"}</td>
                  <td className={td}>SAR {s.totalAmount ?? "—"}</td>
                  <td className={td}><span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold ${s.status === "PAID" ? "bg-success/10 text-success" : s.status === "APPROVED" ? "bg-info/10 text-info" : s.status === "DRAFT" ? "bg-warning/10 text-warning" : "bg-foreground-muted/10 text-foreground-muted"}`}>{label(s.status)}</span></td>
                  <td className={td}>{s.approvedById ?? "—"}</td>
                  <td className={td}>{s.paymentReference || "—"}</td>
                  <td className={td}>
                    {s.status === "DRAFT" && <button type="button" className={btn} onClick={() => act(() => approveSaFinalSettlement(organizationId, s.id), `Settlement approved.`)}>Approve</button>}
                    {s.status === "APPROVED" && <button type="button" className={btn} onClick={() => act(() => paySaFinalSettlement(organizationId, s.id, window.prompt("Payment reference") || ""), `Settlement marked paid.`)}>Pay</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div className="mt-3 flex flex-wrap items-end gap-2">
          <input aria-label="Employee ID" placeholder="Employee ID" className={`${input} w-28`} value={form.employeeId} onChange={(e) => setForm({ ...form, employeeId: e.target.value })} />
          <label className="text-[12px] text-foreground-secondary">Exit Reason
            <select aria-label="Exit reason" className={`${input} ml-1`} value={form.terminationType} onChange={(e) => setForm({ ...form, terminationType: e.target.value })}>
              {EXIT_REASONS.map((r) => <option key={r} value={r}>{label(r)}</option>)}
            </select>
          </label>
          <input aria-label="Exit Date" type="date" className={`${input} w-36`} value={form.terminationDate} onChange={(e) => setForm({ ...form, terminationDate: e.target.value })} />
          <input aria-label="Notice Days" placeholder="Notice Days" className={`${input} w-28`} value={form.noticeDays} onChange={(e) => setForm({ ...form, noticeDays: Number(e.target.value) })} />
          <input aria-label="Leave Balance Days" placeholder="Leave Balance Days" className={`${input} w-32`} value={form.unusedLeaveDays} onChange={(e) => setForm({ ...form, unusedLeaveDays: Number(e.target.value) })} />
          <input aria-label="Repatriation (SAR)" placeholder="Repatriation (SAR)" className={`${input} w-36`} value={form.repatriationAmount} onChange={(e) => setForm({ ...form, repatriationAmount: e.target.value })} />
          <input aria-label="Other Dues (SAR)" placeholder="Other Dues (SAR)" className={`${input} w-32`} value={form.otherDues} onChange={(e) => setForm({ ...form, otherDues: e.target.value })} />
          <button type="button" className={btn} disabled={!form.employeeId || !form.terminationDate} onClick={() => act(() => createSaFinalSettlement(organizationId, form), "Draft settlement created — a second Super Admin approves it.")}>Create draft</button>
        </div>
      </section>
    </div>
  );
}