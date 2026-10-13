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

const OBLIGATIONS = ["GOSI", "WPS", "EOS"];
const TREATMENTS = ["INCLUDED", "EXCLUDED", "REVIEW"];
const COMPONENTS = ["BASIC", "HOUSING", "HOUSING_IN_KIND", "ALLOWANCE_REGULAR", "OVERTIME", "COMMISSION", "BONUS", "OTHER_EARNINGS", "EOS_AWARD", "LEAVE_ENCASHMENT"];

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

export function SAEarningClassesTab({ packId }) {
  const [slabs, slabsError, slabsLoading, reloadSlabs] = useLoad(
    () => getCanonicalTaxSlabs({ jurisdictionPackId: packId, ruleType: "SA_EARNING_CLASS" }),
    [packId]
  );
  const [form, setForm] = useState({ 
    obligation: "GOSI", 
    treatment: "REVIEW", 
    component: "ALLOWANCE_REGULAR", 
  });
  const [editingId, setEditingId] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  async function act(fn, ok) {
    setError(null); setNotice(null);
    try { await fn(); setNotice(ok); reloadSlabs(); } catch (e) { setError(e?.message || "Refused."); }
  }

  const earningSlabs = slabs?.filter(s => s.ruleType === "SA_EARNING_CLASS") || [];

  return (
    <div className="space-y-4">
      {slabsLoading ? (
        <p className="text-center text-[12px] text-foreground-muted py-4">Loading…</p>
      ) : (
        <>
          <div className={card} aria-labelledby="sa-earning-classes">
            <h3 id="sa-earning-classes" className="mb-1 text-[14px] font-semibold text-foreground">Earning Classification (GOSI / WPS / EOS)</h3>
            <p className="mb-2 rounded-lg bg-surface-muted p-2 text-[12px] text-foreground-secondary">
              Maps pay components to their treatment under GOSI, WPS, and EOS. INCLUDED = counts in base; EXCLUDED = never counts; REVIEW = needs signed interpretation.
            </p>
            {slabsError && <p role="alert" className="text-[13px] text-error">{slabsError}</p>}
            {earningSlabs.length === 0 && <p className="text-[12px] text-foreground-muted py-4">No earning classification rows configured.</p>}
            <table className="w-full" aria-label="Earning classification rows">
              <thead>
                <tr>{["Obligation", "Treatment", "Component", "Label", ""].map((h) => <th key={h} className={th}>{h}</th>)}</tr>
              </thead>
              <tbody>
                {earningSlabs.map((s) => (
                  <tr key={s.id} className="border-t border-border">
                    <td className={td}>{s.taxRegime || "—"}</td>
                    <td className={td}>{s.assessmentBasis || "—"}</td>
                    <td className={td}>{s.filingStatus || "—"}</td>
                    <td className={td}>{s.rateLabel || "—"}</td>
                    <td className={td}>
                      {s.status === "Draft" && <button type="button" className={btn} onClick={() => { setForm(s); setEditingId(s.id); }}>Edit</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className={card} aria-labelledby="sa-earning-class-form">
            <h3 id="sa-earning-class-form" className="mb-1 text-[14px] font-semibold text-foreground">{editingId ? "Edit Earning Class" : "Create Earning Class"}</h3>
            <form className={`${card} grid grid-cols-1 gap-3 sm:grid-cols-3`} onSubmit={(e) => { e.preventDefault(); act(editingId ? () => upsertCanonicalTaxSlab(editingId, form) : () => upsertCanonicalTaxSlab(packId, form), editingId ? "Class updated." : "Class created."); setEditingId(null); setForm({ obligation: "GOSI", treatment: "REVIEW", component: "ALLOWANCE_REGULAR" }); }}>
              <label className="text-[12px] text-foreground-secondary">Obligation
                <select aria-label="Obligation" className={`${input} ml-1`} value={form.obligation} onChange={(e) => setForm({ ...form, obligation: e.target.value })}>
                  {OBLIGATIONS.map((t) => <option key={t} value={t}>{label(t)}</option>)}
                </select>
              </label>
              <label className="text-[12px] text-foreground-secondary">Treatment
                <select aria-label="Treatment" className={`${input} ml-1`} value={form.treatment} onChange={(e) => setForm({ ...form, treatment: e.target.value })}>
                  {TREATMENTS.map((t) => <option key={t} value={t}>{label(t)}</option>)}
                </select>
              </label>
              <label className="text-[12px] text-foreground-secondary">Component
                <select aria-label="Component" className={`${input} ml-1`} value={form.component} onChange={(e) => setForm({ ...form, component: e.target.value })}>
                  {COMPONENTS.map((t) => <option key={t} value={t}>{label(t)}</option>)}
                </select>
              </label>
              <div className="flex items-end"><button type="submit" className={btn} disabled={!form.component}>{editingId ? "Update" : "Create"}</button></div>
            </form>
          </div>
        </>
      )}
    </div>
  );
}