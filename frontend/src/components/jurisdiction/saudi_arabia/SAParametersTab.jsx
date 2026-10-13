import { useCallback, useEffect, useRef, useState } from "react";
import {
  getCanonicalContributionRates,
  upsertCanonicalContributionRate,
  deleteCanonicalContributionRate,
} from "../../../service/superAdminService";

const card = "rounded-xl border border-border bg-surface p-4";
const th = "px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-foreground-muted";
const td = "px-2 py-1.5 text-[12px] text-foreground align-top";
const btn = "rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground hover:bg-surface-muted disabled:opacity-40";
const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
const label = (s) => (s || "").replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());

const PARAM_KINDS = [
  { key: "sa_rate_selection_basis", label: "GOSI Rate Selection Basis", kind: "text", allowed: ["CONTRIBUTION_MONTH_START", "CONTRIBUTION_MONTH_END", "PENDING_G1"] },
  { key: "sa_gosi_below_min_behaviour", label: "Below Min Behaviour", kind: "text", allowed: ["BLOCK", "FLOOR"] },
  { key: "sa_rounding_mode", label: "Rounding Mode", kind: "text", allowed: ["HALF_UP", "DOWN", "UP"] },
  { key: "sa_rounding_precision", label: "Rounding Precision (decimals)", kind: "amount" },
  { key: "sa_gosi_due_day", label: "GOSI Due Day", kind: "amount" },
  { key: "sa_normal_hours_daily", label: "Normal Daily Hours", kind: "amount" },
  { key: "sa_normal_hours_weekly", label: "Normal Weekly Hours", kind: "amount" },
  { key: "sa_ramadan_hours_daily", label: "Ramadan Daily Hours", kind: "amount" },
  { key: "sa_ramadan_hours_weekly", label: "Ramadan Weekly Hours", kind: "amount" },
  { key: "sa_overtime_basic_premium_pct", label: "OT Basic Premium %", kind: "employee_pct" },
  { key: "sa_monthly_hours_divisor", label: "Monthly Hours Divisor", kind: "amount" },
  { key: "sa_loan_cap_pct", label: "Loan Cap %", kind: "employee_pct" },
  { key: "sa_damage_cap_pct", label: "Damage Cap %", kind: "employee_pct" },
  { key: "sa_aggregate_deduction_cap_pct", label: "Aggregate Deduction Cap %", kind: "employee_pct" },
  { key: "sa_annual_leave_days_base", label: "Annual Leave Base Days", kind: "amount" },
  { key: "sa_annual_leave_days_after_5_years", label: "Annual Leave After 5y Days", kind: "amount" },
  { key: "sa_sick_leave_full_pay_days", label: "Sick Leave Full Pay Days", kind: "amount" },
  { key: "sa_sick_leave_75_pct_days", label: "Sick Leave 75% Days", kind: "amount" },
  { key: "sa_sick_leave_unpaid_days", label: "Sick Leave Unpaid Days", kind: "amount" },
  { key: "sa_maternity_leave_weeks", label: "Maternity Leave Weeks", kind: "amount" },
  { key: "sa_maternity_mandatory_post_birth_weeks", label: "Maternity Post-Birth Weeks", kind: "amount" },
  { key: "sa_eos_first_5_years_months", label: "EOS First 5 Years Months", kind: "amount" },
  { key: "sa_eos_after_5_years_months", label: "EOS After 5 Years Months", kind: "amount" },
  { key: "sa_eos_resign_frac_under_2", label: "EOS Resign <2y", kind: "text" },
  { key: "sa_eos_resign_frac_2_to_5", label: "EOS Resign 2-5y", kind: "text" },
  { key: "sa_eos_resign_frac_5_to_10", label: "EOS Resign 5-10y", kind: "text" },
  { key: "sa_eos_resign_frac_10_plus", label: "EOS Resign 10+y", kind: "text" },
  { key: "sa_settlement_deadline_termination_days", label: "Settlement Deadline Term", kind: "amount" },
  { key: "sa_settlement_deadline_resignation_days", label: "Settlement Deadline Resign", kind: "amount" },
];

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

export function SAParametersTab({ packId }) {
  const [rates, ratesError, ratesLoading, reloadRates] = useLoad(
    () => getCanonicalContributionRates({ jurisdictionPackId: packId }),
    [packId]
  );
  const [form, setForm] = useState({ 
    componentKey: PARAM_KINDS[0].key, 
    employeeRatePct: "", 
    employerRatePct: "", 
    flatAmount: "", 
    textValue: "" 
  });
  const [editingId, setEditingId] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  async function act(fn, ok) {
    setError(null); setNotice(null);
    try { await fn(); setNotice(ok); reloadRates(); } catch (e) { setError(e?.message || "Refused."); }
  }

  const paramRates = rates?.filter(r => PARAM_KINDS.some(k => k.key === r.componentKey)) || [];

  return (
    <div className="space-y-4">
      <Messages error={error} notice={notice} />
      {ratesLoading ? (
        <p className="text-center text-[12px] text-foreground-muted py-4">Loading…</p>
      ) : (
        <>
          <div className={card} aria-labelledby="sa-parameters">
            <h3 id="sa-parameters" className="mb-1 text-[14px] font-semibold text-foreground">Scalar Parameters (SA-007/SA-009/SA-010/SA-011/SA-013/SA-022)</h3>
            <p className="mb-2 rounded-lg bg-surface-muted p-2 text-[12px] text-foreground-secondary">
              Scalar parameters from the SA pack. Each row's kind determines which field holds the value: text = textValue, employee_pct/employer_pct = rate_pct, amount = flatAmount.
            </p>
            {ratesError && <p role="alert" className="text-[13px] text-error">{ratesError}</p>}
            {paramRates.length === 0 && <p className="text-[12px] text-foreground-muted py-4">No parameter rows configured.</p>}
            <div className="overflow-x-auto">
              <table className="w-full" aria-label="Scalar parameters">
                <thead>
                  <tr>{["Component Key", "Label", "EE Rate %", "ER Rate %", "Flat Amount", "Text Value", "Source Doc", ""].map((h) => <th key={h} className={th}>{h}</th>)}</tr>
                </thead>
                <tbody>
                  {paramRates.map((r) => (
                    <tr key={r.id} className="border-t border-border">
                      <td className={td}><code className="text-[10px] font-mono">{r.componentKey}</code></td>
                      <td className={td}>{r.label || "—"}</td>
                      <td className={td}>{r.employeeRatePct ?? "—"}</td>
                      <td className={td}>{r.employerRatePct ?? "—"}</td>
                      <td className={td}>{r.flatAmount ?? "—"}</td>
                      <td className={td}>{r.textValue || "—"}</td>
                      <td className={td}>{r.sourceDocumentId ?? "—"}</td>
                      <td className={td}>
                        {r.status === "Draft" && <button type="button" className={btn} onClick={() => { setForm(r); setEditingId(r.id); }}>Edit</button>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className={card} aria-labelledby="sa-parameter-form">
              <h3 id="sa-parameter-form" className="mb-1 text-[14px] font-semibold text-foreground">{editingId ? "Edit Parameter" : "Create Parameter"}</h3>
              <form className={`${card} grid grid-cols-1 gap-3 sm:grid-cols-3`} onSubmit={(e) => { e.preventDefault(); act(editingId ? () => upsertCanonicalContributionRate(editingId, form) : () => upsertCanonicalContributionRate(packId, form), editingId ? "Parameter updated." : "Parameter created."); setEditingId(null); setForm({ componentKey: PARAM_KINDS[0].key, employeeRatePct: "", employerRatePct: "", flatAmount: "", textValue: "" }); }}>
                <label className="text-[12px] text-foreground-secondary">Component Key
                  <select aria-label="Component key" className={`${input} ml-1`} value={form.componentKey} onChange={(e) => setForm({ ...form, componentKey: e.target.value })}>
                    {PARAM_KINDS.map((k) => <option key={k.key} value={k.key}>{k.label} ({k.kind})</option>)}
                  </select>
                </label>
                <input aria-label="EE Rate %" placeholder="EE Rate %" className={`${input} w-28`} value={form.employeeRatePct} onChange={(e) => setForm({ ...form, employeeRatePct: e.target.value })} />
                <input aria-label="ER Rate %" placeholder="ER Rate %" className={`${input} w-28`} value={form.employerRatePct} onChange={(e) => setForm({ ...form, employerRatePct: e.target.value })} />
                <input aria-label="Flat Amount" placeholder="Flat Amount" className={`${input} w-28`} value={form.flatAmount} onChange={(e) => setForm({ ...form, flatAmount: e.target.value })} />
                <input aria-label="Text Value" placeholder="Text Value (e.g. BASIC/GROSS, HALF_UP, 1/3)" className={`${input} w-40`} value={form.textValue} onChange={(e) => setForm({ ...form, textValue: e.target.value })} />
                <div className="flex items-end"><button type="submit" className={btn} disabled={!form.componentKey}>{editingId ? "Update" : "Create"}</button></div>
              </form>
          </div>
        </>
      )}
    </div>
  );
}