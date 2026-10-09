import { useCallback, useEffect, useRef, useState } from "react";
import {
  getCanonicalTaxSlabs,
  upsertCanonicalTaxSlab,
  deleteCanonicalTaxSlab,
} from "../../../service/superAdminService";

const card = "rounded-xl border border-border bg-surface p-4";
const th = "px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-foreground-muted";
const td = "px-2 py-1.5 text-[12px] text-foreground align-top";
const btn = "rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground hover:bg-surface-muted disabled:opacity-40";
const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
const label = (s) => (s || "").replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());

const BRANCHES = ["PENSION_NEW", "PENSION_LEGACY", "SANED", "OCCUPATIONAL_HAZARDS"];
const WORKER_CLASSES = ["SAUDI", "NON_SAUDI"];

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

export function SAGosiBranchesTab({ packId }) {
  const [slabs, slabsError, slabsLoading, reloadSlabs] = useLoad(
    () => getCanonicalTaxSlabs({ jurisdictionPackId: packId, ruleType: "SA_GOSI_BRANCH" }),
    [packId]
  );
  const [form, setForm] = useState({ 
    workerClass: "SAUDI", 
    branch: "PENSION_NEW", 
    ratePct: "", 
    employerRatePct: "", 
    minAmount: "", 
    maxAmount: "", 
    effectiveFrom: new Date().toISOString().slice(0, 10), 
    effectiveTo: "" 
  });
  const [editingId, setEditingId] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  async function act(fn, ok) {
    setError(null); setNotice(null);
    try { await fn(); setNotice(ok); reloadSlabs(); } catch (e) { setError(e?.message || "Refused."); }
  }

  const gosiSlabs = slabs?.filter(s => s.ruleType === "SA_GOSI_BRANCH") || [];

  return (
    <div className="space-y-4">
      {slabsLoading ? (
        <p className="text-center text-[12px] text-foreground-muted py-4">Loading…</p>
      ) : (
        <>
          <div className={card} aria-labelledby="sa-gosi-branches">
            <h3 id="sa-gosi-branches" className="mb-1 text-[14px] font-semibold text-foreground">GOSI Branch Rates (SA-003/SA-009)</h3>
            <p className="mb-2 rounded-lg bg-surface-muted p-2 text-[12px] text-foreground-secondary">
              Effective-dated branch rates per worker class. Each branch (PENSION_NEW, PENSION_LEGACY, SANED, OCCUPATIONAL_HAZARDS) has its own rate, floor, ceiling, and effective dates.
            </p>
            {slabsError && <p role="alert" className="text-[13px] text-error">{slabsError}</p>}
            {gosiSlabs.length === 0 && <p className="text-[12px] text-foreground-muted py-4">No GOSI branch rows configured.</p>}
            <table className="w-full" aria-label="GOSI branch rows">
              <thead>
                <tr>{["Worker Class", "Branch", "EE Rate %", "ER Rate %", "Min (SAR)", "Max (SAR)", "Effective From", "Effective To", ""].map((h) => <th key={h} className={th}>{h}</th>)}</tr>
              </thead>
              <tbody>
                {gosiSlabs.map((s) => (
                  <tr key={s.id} className="border-t border-border">
                    <td className={td}>{s.filingStatus || "—"}</td>
                    <td className={td}>{s.taxRegime || "—"}</td>
                    <td className={td}>{s.ratePct ?? "—"}</td>
                    <td className={td}>{s.employerRatePct ?? "—"}</td>
                    <td className={td}>{s.minAmount ?? "—"}</td>
                    <td className={td}>{s.maxAmount ?? "—"}</td>
                    <td className={td}>{s.effectiveFrom ? new Date(s.effectiveFrom).toLocaleDateString() : "—"}</td>
                    <td className={td}>{s.effectiveTo ? new Date(s.effectiveTo).toLocaleDateString() : "open"}</td>
                    <td className={td}>
                      {s.status === "Draft" && <button type="button" className={btn} onClick={() => { setForm(s); setEditingId(s.id); }}>Edit</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className={card} aria-labelledby="sa-gosi-branch-form">
            <h3 id="sa-gosi-branch-form" className="mb-1 text-[14px] font-semibold text-foreground">{editingId ? "Edit GOSI Branch" : "Create GOSI Branch"}</h3>
            <form className={`${card} grid grid-cols-1 gap-3 sm:grid-cols-4`} onSubmit={(e) => { e.preventDefault(); act(editingId ? () => upsertCanonicalTaxSlab(editingId, form) : () => upsertCanonicalTaxSlab(packId, form), editingId ? "Branch updated." : "Branch created."); setEditingId(null); setForm({ workerClass: "SAUDI", branch: "PENSION_NEW", ratePct: "", employerRatePct: "", minAmount: "", maxAmount: "", effectiveFrom: new Date().toISOString().slice(0, 10), effectiveTo: "" }); }}>
              <label className="text-[12px] text-foreground-secondary">Worker Class
                <select aria-label="Worker class" className={`${input} ml-1`} value={form.workerClass} onChange={(e) => setForm({ ...form, workerClass: e.target.value })}>
                  {WORKER_CLASSES.map((t) => <option key={t} value={t}>{label(t)}</option>)}
                </select>
              </label>
              <label className="text-[12px] text-foreground-secondary">Branch
                <select aria-label="Branch" className={`${input} ml-1`} value={form.branch} onChange={(e) => setForm({ ...form, branch: e.target.value })}>
                  {BRANCHES.map((t) => <option key={t} value={t}>{label(t)}</option>)}
                </select>
              </label>
              <input aria-label="EE Rate %" placeholder="EE Rate %" className={`${input} w-28`} value={form.ratePct} onChange={(e) => setForm({ ...form, ratePct: e.target.value })} />
              <input aria-label="ER Rate %" placeholder="ER Rate %" className={`${input} w-28`} value={form.employerRatePct} onChange={(e) => setForm({ ...form, employerRatePct: e.target.value })} />
              <input aria-label="Min Amount" placeholder="Min (SAR)" className={`${input} w-28`} value={form.minAmount} onChange={(e) => setForm({ ...form, minAmount: e.target.value })} />
              <input aria-label="Max Amount" placeholder="Max (SAR)" className={`${input} w-28`} value={form.maxAmount} onChange={(e) => setForm({ ...form, maxAmount: e.target.value })} />
              <input aria-label="Effective From" type="date" className={`${input} w-36`} value={form.effectiveFrom} onChange={(e) => setForm({ ...form, effectiveFrom: e.target.value })} />
              <input aria-label="Effective To" type="date" className={`${input} w-36`} value={form.effectiveTo} onChange={(e) => setForm({ ...form, effectiveTo: e.target.value })} />
              <div className="flex items-end"><button type="submit" className={btn} disabled={!form.ratePct || !form.employerRatePct || !form.effectiveFrom}>{editingId ? "Update" : "Create"}</button></div>
            </form>
          </div>
        </>
      )}
    </div>
  );
}