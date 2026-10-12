import { useCallback, useEffect, useState } from "react";
import { listHkAccessEvents, listHkLegalHolds, placeHkLegalHold, releaseHkLegalHold } from "../../../service/payrollService";
import { hkLabel } from "../../../components/jurisdiction/hong_kong/hkLabels";

// Hong Kong privacy controls (gap-closure D-19): legal holds (no HK record in
// scope can be deleted while one is active; release needs a different user)
// and the access log of HK statutory data (downloads and profile views).
// No retention period is set here — that is an owner / privacy-counsel decision.
const input = "w-full rounded-lg border border-border bg-surface px-3 py-2 text-[13px] text-foreground";
const labelCls = "mb-1 block text-[12px] font-semibold text-foreground-secondary";
const btn = "rounded-lg bg-primary px-3 py-1.5 text-[12px] font-semibold text-white disabled:opacity-60";
const btnGhost = "rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground";
const card = "rounded-xl border border-border bg-surface p-4";
const th = "px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-foreground-muted";
const td = "px-2 py-1.5 text-[12px] text-foreground align-top";

export default function HKPrivacyPanel({ employees = [] }) {
  const [holds, setHolds] = useState([]);
  const [events, setEvents] = useState([]);
  const [form, setForm] = useState({ employeeId: "", reason: "", reference: "" });
  const [releaseReason, setReleaseReason] = useState({});
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const load = useCallback(() => {
    listHkLegalHolds().then(setHolds).catch(() => setHolds([]));
    listHkAccessEvents().then(setEvents).catch(() => setEvents([]));
  }, []);
  useEffect(() => { load(); }, [load]);
  const name = (id) => employees.find((e) => e.id === id)?.name || (id ? `#${id}` : "—");

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
    <div className="space-y-4">
      <p className="text-[12px] text-foreground-secondary">
        A legal hold stops any Hong Kong record in its scope from being deleted. Retention periods are not set here.
      </p>
      <form className={`${card} grid grid-cols-1 gap-3 sm:grid-cols-4`} aria-label="Place a legal hold"
        onSubmit={(e) => {
          e.preventDefault();
          act(() => placeHkLegalHold({ employeeId: form.employeeId ? Number(form.employeeId) : null, reason: form.reason,
            reference: form.reference || null }), "Legal hold placed.");
        }}>
        <div>
          <label className={labelCls} htmlFor="hk-lh-emp">Scope</label>
          <select id="hk-lh-emp" className={input} value={form.employeeId} onChange={(e) => setForm({ ...form, employeeId: e.target.value })}>
            <option value="">Whole organisation</option>
            {employees.map((e) => <option key={e.id} value={e.id}>{e.name} ({e.employeeCode})</option>)}
          </select>
        </div>
        <div>
          <label className={labelCls} htmlFor="hk-lh-reason">Reason</label>
          <input id="hk-lh-reason" className={input} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
        </div>
        <div>
          <label className={labelCls} htmlFor="hk-lh-ref">Reference (optional)</label>
          <input id="hk-lh-ref" className={input} value={form.reference} onChange={(e) => setForm({ ...form, reference: e.target.value })} />
        </div>
        <div className="flex items-end"><button type="submit" className={btn}>Place legal hold</button></div>
      </form>
      <div aria-live="polite">
        {error && <p role="alert" className="text-[12px] font-medium text-error">{error}</p>}
        {notice && <p role="status" className="text-[12px] font-medium text-success">{notice}</p>}
      </div>
      <table className="w-full">
        <caption className="sr-only">Legal holds</caption>
        <thead><tr><th scope="col" className={th}>Scope</th><th scope="col" className={th}>Status</th><th scope="col" className={th}>Reason</th><th scope="col" className={th}>Placed</th><th scope="col" className={th}>Action</th></tr></thead>
        <tbody>
          {holds.map((h) => (
            <tr key={h.id} className="border-t border-border">
              <td className={td}>{h.employeeId ? name(h.employeeId) : hkLabel("ORGANISATION")}</td>
              <td className={td}>{hkLabel(h.status)}</td>
              <td className={td}>{h.reason}{h.reference ? ` (${h.reference})` : ""}</td>
              <td className={td}>{(h.placedAt || "").slice(0, 10)}</td>
              <td className={td}>
                {h.status === "ACTIVE" && (
                  <div className="flex flex-wrap gap-1">
                    <input aria-label={`Release reason for hold ${h.id}`} placeholder="Release reason" className={input}
                      onChange={(e) => setReleaseReason({ ...releaseReason, [h.id]: e.target.value })} />
                    <button type="button" className={btnGhost} onClick={() => act(() => releaseHkLegalHold(h.id, releaseReason[h.id] || ""), "Legal hold released.")}>
                      Release (different user)
                    </button>
                  </div>
                )}
              </td>
            </tr>
          ))}
          {!holds.length && <tr><td className={td} colSpan={5}>No legal holds.</td></tr>}
        </tbody>
      </table>
      <h3 className="text-[13px] font-semibold text-foreground">Access to Hong Kong statutory data</h3>
      <table className="w-full">
        <caption className="sr-only">Hong Kong statutory data access log</caption>
        <thead><tr><th scope="col" className={th}>When</th><th scope="col" className={th}>Action</th><th scope="col" className={th}>Employee</th><th scope="col" className={th}>Document</th><th scope="col" className={th}>By</th></tr></thead>
        <tbody>
          {events.map((e) => (
            <tr key={e.id} className="border-t border-border">
              <td className={td}>{(e.occurredAt || "").replace("T", " ").slice(0, 16)}</td>
              <td className={td}>{hkLabel(e.action)}{e.assistedAccessSessionId ? " (support session)" : ""}</td>
              <td className={td}>{name(e.employeeId)}</td>
              <td className={td}>{e.reportType ? hkLabel(e.reportType) : "Statutory profile"}</td>
              <td className={td}>{e.actorId ? `User #${e.actorId}` : "—"}</td>
            </tr>
          ))}
          {!events.length && <tr><td className={td} colSpan={5}>No access recorded yet.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
