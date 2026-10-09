import { useCallback, useEffect, useState } from "react";
import {
  listSaEmployerProfiles,
  createSaEmployerProfile,
  approveSaEmployerProfile,
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

export function SAEmployerProfileTab({ organizationId, packId, disabled }) {
  const [profiles, profilesError, profilesLoading, reloadProfiles] = useLoad(
    () => listSaEmployerProfiles(organizationId),
    [organizationId]
  );
  const [form, setForm] = useState({ 
    gosiEmployerCode: "", 
    branchCode: "", 
    activityCode: "", 
    riskCategory: "", 
    crNumber: "", 
    effectiveFrom: new Date().toISOString().slice(0, 10), 
    status: "DRAFT" 
  });
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  async function act(fn, ok) {
    setError(null); setNotice(null);
    try { await fn(); setNotice(ok); reloadProfiles(); } catch (e) { setError(e?.message || "Refused."); }
  }

  if (disabled) {
    return (
      <div className="space-y-4">
        <div className="rounded-xl border border-border bg-surface/50 p-4 text-center">
          <p className="text-[13px] text-foreground-muted">Select an organization from the picker above to manage Employer GOSI Profiles.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Messages error={error || profilesError} notice={notice} />
      <section className={card} aria-labelledby="sa-emp-profiles">
        <h3 id="sa-emp-profiles" className="mb-1 text-[14px] font-semibold text-foreground">Employer GOSI Registration (SA-011)</h3>
        <p className="mb-2 rounded-lg bg-surface-muted p-2 text-[12px] text-foreground-secondary">
          Effective-dated employer GOSI registration versions. Only one DRAFT at a time; a distinct Super Admin approves.
        </p>
        {profilesLoading ? (
          <p className="text-center text-[12px] text-foreground-muted py-4">Loading…</p>
        ) : profiles && (
          <table className="w-full" aria-label="Employer GOSI profiles">
            <thead>
              <tr>{["CR Number", "GOSI Employer #", "Branch Code", "Activity Code", "Risk Category", "Effective From", "Status", "Created By", "Approved By", ""].map((h) => <th key={h} className={th}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {profiles.length === 0 && <tr><td className={td} colSpan={10}>No employer GOSI profiles yet.</td></tr>}
              {profiles.map((p) => (
                <tr key={p.id} className="border-t border-border">
                  <td className={td}>{p.crNumber || "—"}</td>
                  <td className={td}>{p.gosiEmployerCode || "—"}</td>
                  <td className={td}>{p.branchCode || "—"}</td>
                  <td className={td}>{p.activityCode || "—"}</td>
                  <td className={td}>{p.riskCategory || "—"}</td>
                  <td className={td}>{p.effectiveFrom ? new Date(p.effectiveFrom).toLocaleDateString() : "—"}</td>
                  <td className={td}><span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold ${p.status === "APPROVED" ? "bg-success/10 text-success" : p.status === "DRAFT" ? "bg-warning/10 text-warning" : "bg-foreground-muted/10 text-foreground-muted"}`}>{label(p.status)}</span></td>
                  <td className={td}>{p.createdById ?? "—"}</td>
                  <td className={td}>{p.approvedById ?? "—"}</td>
                  <td className={td}>{p.status === "DRAFT" && <button type="button" className={btn} onClick={() => act(() => approveSaEmployerProfile(organizationId, p.id), `Profile ${p.crNumber} approved.`)}>Approve</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div className="mt-3 flex flex-wrap items-end gap-2">
          <input aria-label="CR Number" placeholder="CR Number (10 digits)" className={`${input} w-40`} value={form.crNumber} onChange={(e) => setForm({ ...form, crNumber: e.target.value })} />
          <input aria-label="GOSI Employer Number" placeholder="GOSI Employer # (6-10 digits)" className={`${input} w-44`} value={form.gosiEmployerCode} onChange={(e) => setForm({ ...form, gosiEmployerCode: e.target.value })} />
          <input aria-label="Branch Code" placeholder="Branch Code" className={`${input} w-36`} value={form.branchCode} onChange={(e) => setForm({ ...form, branchCode: e.target.value })} />
          <input aria-label="Activity Code" placeholder="Activity Code" className={`${input} w-36`} value={form.activityCode} onChange={(e) => setForm({ ...form, activityCode: e.target.value })} />
          <input aria-label="Risk Category" placeholder="Risk Category" className={`${input} w-36`} value={form.riskCategory} onChange={(e) => setForm({ ...form, riskCategory: e.target.value })} />
          <input aria-label="Effective From" type="date" className={`${input} w-36`} value={form.effectiveFrom} onChange={(e) => setForm({ ...form, effectiveFrom: e.target.value })} />
          <button type="button" className={btn} disabled={!form.gosiEmployerCode || !form.effectiveFrom} onClick={() => act(() => createSaEmployerProfile(organizationId, form), "Draft profile created — a second Super Admin approves it.")}>Create draft</button>
        </div>
      </section>
    </div>
  );
}