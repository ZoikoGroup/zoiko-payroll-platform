import { useCallback, useEffect, useRef, useState } from "react";
import {
  listSaContractVersions,
  createSaContractVersion,
  approveSaContractVersion,
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

const CONTRACT_TYPES = ["LIMITED", "UNLIMITED", "PART_TIME", "TEMPORARY"];

export function SAContractVersionTab({ organizationId, packId, disabled }) {
  const [contracts, contractsError, contractsLoading, reloadContracts] = useLoad(
    () => listSaContractVersions(organizationId),
    [organizationId]
  );
  const [form, setForm] = useState({ 
    contractType: "LIMITED", 
    effectiveFrom: new Date().toISOString().slice(0, 10), 
    basicWage: "", 
    housingAllowance: "", 
    transportAllowance: "", 
    otherAllowances: "", 
    inKindHousingValue: "", 
    probationEndDate: "", 
    contractEndDate: "", 
    status: "DRAFT" 
  });
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  async function act(fn, ok) {
    setError(null); setNotice(null);
    try { await fn(); setNotice(ok); reloadContracts(); } catch (e) { setError(e?.message || "Refused."); }
  }

  if (disabled) {
    return (
      <div className="space-y-4">
        <div className="rounded-xl border border-border bg-surface/50 p-4 text-center">
          <p className="text-[13px] text-foreground-muted">Select an organization from the picker above to manage Employee Contracts.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Messages error={error || contractsError} notice={notice} />
      <section className={card} aria-labelledby="sa-contracts">
        <h3 id="sa-contracts" className="mb-1 text-[14px] font-semibold text-foreground">Employee Contract Versions (SA-012)</h3>
        <p className="mb-2 rounded-lg bg-surface-muted p-2 text-[12px] text-foreground-secondary">
          Effective-dated employment contract versions. Only one DRAFT at a time; a distinct Super Admin approves.
        </p>
        {contractsLoading ? (
          <p className="text-center text-[12px] text-foreground-muted py-4">Loading…</p>
        ) : contracts && (
          <table className="w-full" aria-label="Employee contract versions">
            <thead>
              <tr>{["Contract Type", "Effective From", "Basic Wage", "Housing Allowance", "Transport Allowance", "Other Allowances", "In-Kind Housing", "Status", "Created By", "Approved By", ""].map((h) => <th key={h} className={th}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {contracts.length === 0 && <tr><td className={td} colSpan={11}>No contract versions yet.</td></tr>}
              {contracts.map((c) => (
                <tr key={c.id} className="border-t border-border">
                  <td className={td}>{c.contractType || "—"}</td>
                  <td className={td}>{c.effectiveFrom ? new Date(c.effectiveFrom).toLocaleDateString() : "—"}</td>
                  <td className={td}>SAR {c.basicWage ?? "—"}</td>
                  <td className={td}>SAR {c.housingAllowance ?? "—"}</td>
                  <td className={td}>SAR {c.transportAllowance ?? "—"}</td>
                  <td className={td}>SAR {c.otherAllowances ?? "—"}</td>
                  <td className={td}>SAR {c.inKindHousingValue ?? "—"}</td>
                  <td className={td}><span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold ${c.status === "APPROVED" ? "bg-success/10 text-success" : c.status === "DRAFT" ? "bg-warning/10 text-warning" : "bg-foreground-muted/10 text-foreground-muted"}`}>{label(c.status)}</span></td>
                  <td className={td}>{c.createdById ?? "—"}</td>
                  <td className={td}>{c.approvedById ?? "—"}</td>
                  <td className={td}>{c.status === "DRAFT" && <button type="button" className={btn} onClick={() => act(() => approveSaContractVersion(organizationId, c.employeeId, c.id), `Contract approved.`)}>Approve</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div className="mt-3 flex flex-wrap items-end gap-2">
          <label className="text-[12px] text-foreground-secondary">Contract Type
            <select aria-label="Contract type" className={`${input} ml-1`} value={form.contractType} onChange={(e) => setForm({ ...form, contractType: e.target.value })}>
              {CONTRACT_TYPES.map((t) => <option key={t} value={t}>{label(t)}</option>)}
            </select>
          </label>
          <input aria-label="Effective From" type="date" className={`${input} w-36`} value={form.effectiveFrom} onChange={(e) => setForm({ ...form, effectiveFrom: e.target.value })} />
          <input aria-label="Basic Wage (SAR)" placeholder="Basic Wage (SAR)" className={`${input} w-36`} value={form.basicWage} onChange={(e) => setForm({ ...form, basicWage: e.target.value })} />
          <input aria-label="Housing Allowance (SAR)" placeholder="Housing Allowance (SAR)" className={`${input} w-40`} value={form.housingAllowance} onChange={(e) => setForm({ ...form, housingAllowance: e.target.value })} />
          <input aria-label="Transport Allowance (SAR)" placeholder="Transport Allowance (SAR)" className={`${input} w-36`} value={form.transportAllowance} onChange={(e) => setForm({ ...form, transportAllowance: e.target.value })} />
          <input aria-label="Other Allowances (SAR)" placeholder="Other Allowances (SAR)" className={`${input} w-36`} value={form.otherAllowances} onChange={(e) => setForm({ ...form, otherAllowances: e.target.value })} />
          <input aria-label="In-Kind Housing Value (SAR)" placeholder="In-Kind Housing (SAR)" className={`${input} w-36`} value={form.inKindHousingValue} onChange={(e) => setForm({ ...form, inKindHousingValue: e.target.value })} />
          <button type="button" className={btn} disabled={!form.effectiveFrom || !form.basicWage} onClick={() => act(() => createSaContractVersion(organizationId, form), "Draft contract created — a second Super Admin approves it.")}>Create draft</button>
        </div>
      </section>
    </div>
  );
}