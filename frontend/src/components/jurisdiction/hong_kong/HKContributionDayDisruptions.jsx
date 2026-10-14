import { useCallback, useEffect, useState } from "react";
import { getHkContributionDayDisruptions, recordHkContributionDayDisruption } from "../../../service/superAdminService";

// MPF contribution-day deferral — operator override. A day on which a black
// rainstorm warning or a No. 8 or higher signal was in force is recorded here
// (reason required, audited); the governed deferral rule ([G1] UNVERIFIED)
// then skips it when it sets eMPF contribution deadlines. Nothing is read
// from a weather feed. Territory-wide: one record per date.
const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
const btn = "rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground hover:bg-surface-muted disabled:opacity-40";

export default function HKContributionDayDisruptions() {
  const [rows, setRows] = useState([]);
  const [form, setForm] = useState({ disruptionDate: "", signal: "BLACK_RAINSTORM", reason: "", evidenceReference: "" });
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const load = useCallback(() => {
    getHkContributionDayDisruptions().then((d) => setRows(d?.disruptions || [])).catch(() => setRows([]));
  }, []);
  useEffect(() => { load(); }, [load]);
  async function record() {
    setError(null); setNotice(null);
    try {
      await recordHkContributionDayDisruption({ ...form, evidenceReference: form.evidenceReference || null });
      setNotice(`${form.disruptionDate} recorded — contribution deadlines on that day move to the next working day.`);
      setForm({ ...form, disruptionDate: "", reason: "", evidenceReference: "" });
      load();
    } catch (e) {
      setError(e?.message || "Not recorded.");
    }
  }
  return (
    <section className="rounded-xl border border-border bg-surface p-4" aria-labelledby="hk-disruptions">
      <h3 id="hk-disruptions" className="mb-1 text-[14px] font-semibold text-foreground">MPF contribution-day disruption days</h3>
      <p className="mb-2 text-[12px] text-foreground-secondary">
        Record a day with a black rainstorm warning or a No. 8+ signal. The contribution-day deferral rule is
        <strong> unverified (G1)</strong> until the Hong Kong specialist certifies it.
      </p>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {notice && <p role="status" className="text-[12px] text-success">{notice}</p>}
      <ul className="mb-2 space-y-0.5 text-[12px] text-foreground">
        {rows.length === 0 && <li className="text-foreground-muted">None recorded.</li>}
        {rows.map((r) => <li key={r.id}>{r.date} · {r.signal} · {r.reason}{r.evidenceReference ? ` (${r.evidenceReference})` : ""}</li>)}
      </ul>
      <div className="flex flex-wrap items-end gap-2">
        <input type="date" className={input} aria-label="Disruption date" value={form.disruptionDate}
          onChange={(e) => setForm({ ...form, disruptionDate: e.target.value })} />
        <select className={input} aria-label="Signal" value={form.signal} onChange={(e) => setForm({ ...form, signal: e.target.value })}>
          <option value="BLACK_RAINSTORM">Black rainstorm warning</option>
          <option value="TYPHOON_SIGNAL_8_OR_ABOVE">Tropical cyclone signal No. 8 or above</option>
        </select>
        <input className={input} aria-label="Reason" placeholder="Reason (warning and its times)" value={form.reason}
          onChange={(e) => setForm({ ...form, reason: e.target.value })} />
        <input className={input} aria-label="Evidence reference" placeholder="Observatory reference (optional)" value={form.evidenceReference}
          onChange={(e) => setForm({ ...form, evidenceReference: e.target.value })} />
        <button type="button" className={btn} disabled={!form.disruptionDate || !form.reason.trim()} onClick={record}>Record day</button>
      </div>
    </section>
  );
}
