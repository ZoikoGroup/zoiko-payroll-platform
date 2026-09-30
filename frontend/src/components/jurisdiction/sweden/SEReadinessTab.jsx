import { useEffect, useState } from "react";
import { CheckCircle2, CircleAlert } from "lucide-react";
import { getSwedenReadiness, previewSwedenCalculation } from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";

// Sweden release gates (spec §16/§37) and the read-only calculation preview
// (spec §13 "simulation before activation"). Rendered exactly as the backend
// returns it — nothing is evaluated or defaulted here, and no gate is ever
// shown as passed without backend evidence. The preview runs the production
// engine server-side; this component never computes a statutory figure.
function Readiness({ packId }) {
  const [result, setResult] = useState({ key: null, data: null, error: null });
  useEffect(() => {
    let live = true;
    getSwedenReadiness(packId)
      .then((data) => { if (live) setResult({ key: packId, data, error: null }); })
      .catch((e) => { if (live) setResult({ key: packId, data: null, error: e?.message || "Failed to load readiness" }); });
    return () => { live = false; };
  }, [packId]);
  if (result.key !== packId) return <p className="text-xs text-foreground-muted">Loading readiness…</p>;
  if (result.error) return <p role="alert" className="text-xs text-error">{result.error}</p>;
  const { ready, items = [] } = result.data || {};
  return (
    <section aria-labelledby="se-readiness-heading" className="space-y-2">
      <div className="flex items-center gap-2">
        <h3 id="se-readiness-heading" className="text-sm font-semibold text-foreground">Release gates</h3>
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${ready ? "bg-success-light text-success" : "bg-warning-light text-warning"}`}>
          {ready ? "Ready to activate" : "Not ready — live Swedish payroll stays disabled"}
        </span>
      </div>
      <ul className="divide-y divide-border-light rounded-xl border border-border">
        {items.map((i) => (
          <li key={i.key} className="flex items-start gap-2 px-3 py-2 text-xs">
            {i.complete
              ? <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-success" aria-label="Complete" />
              : <CircleAlert size={14} className="mt-0.5 shrink-0 text-warning" aria-label="Incomplete" />}
            <div>
              <p className="font-medium text-foreground">{i.label}{!i.required && <span className="ml-1 text-foreground-muted">(informational)</span>}</p>
              {i.detail && <p className="text-foreground-muted">{i.detail}</p>}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

const PREVIEW_DEFAULTS = {
  payDate: "", gross: "", dateOfBirth: "", taxStatus: "A_TAX", incomeRole: "MAIN_INCOME",
  taxTable: "", taxColumn: "1", sinkStatus: "", annualIncome: "", monthToDatePrior: "", pensionCostBase: "",
};

function Preview({ pack }) {
  const [form, setForm] = useState(PREVIEW_DEFAULTS);
  const [running, setRunning] = useState(false);
  const [out, setOut] = useState(null);
  const [error, setError] = useState(null);
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));
  const blank = (v) => (v === "" ? null : v);

  async function run() {
    if (!form.payDate || !form.gross || !form.dateOfBirth) {
      setError("Payment date, gross pay and date of birth are required.");
      return;
    }
    setRunning(true); setError(null);
    try {
      setOut(await previewSwedenCalculation({
        jurisdictionPackId: pack.id, payDate: form.payDate, gross: form.gross, dateOfBirth: form.dateOfBirth,
        taxStatus: form.taxStatus, incomeRole: form.incomeRole, taxTable: blank(form.taxTable),
        taxColumn: blank(form.taxColumn), sinkStatus: blank(form.sinkStatus), annualIncome: blank(form.annualIncome),
        monthToDatePrior: blank(form.monthToDatePrior), pensionCostBase: blank(form.pensionCostBase),
      }));
    } catch (e) {
      setError(e?.message || "Preview failed.");
    } finally {
      setRunning(false);
    }
  }

  const se = out && !out.blocked ? out.sweden : null;
  return (
    <section aria-labelledby="se-preview-heading" className="space-y-3">
      <h3 id="se-preview-heading" className="text-sm font-semibold text-foreground">Calculation preview (read-only)</h3>
      <p className="text-xs text-foreground-muted">Runs the production Sweden engine against this pack&apos;s rows in force on the payment date. Nothing is saved.</p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div><label className={labelClass} htmlFor="se-pv-date">Payment date</label>
          <input id="se-pv-date" type="date" className={inputClass} value={form.payDate} onChange={set("payDate")} /></div>
        <div><label className={labelClass} htmlFor="se-pv-gross">Monthly gross (SEK)</label>
          <input id="se-pv-gross" className={inputClass} inputMode="decimal" value={form.gross} onChange={set("gross")} /></div>
        <div><label className={labelClass} htmlFor="se-pv-dob">Date of birth</label>
          <input id="se-pv-dob" type="date" className={inputClass} value={form.dateOfBirth} onChange={set("dateOfBirth")} /></div>
        <div><label className={labelClass} htmlFor="se-pv-status">Tax status</label>
          <select id="se-pv-status" className={inputClass} value={form.taxStatus} onChange={set("taxStatus")}>
            <option value="A_TAX">A-tax</option><option value="SINK">SINK</option>
          </select></div>
        <div><label className={labelClass} htmlFor="se-pv-role">Income role</label>
          <select id="se-pv-role" className={inputClass} value={form.incomeRole} onChange={set("incomeRole")}>
            <option value="MAIN_INCOME">Main income</option>
            <option value="SUPPLEMENTARY_INCOME">Supplementary income (30%)</option>
            <option value="ONE_TIME_PAYMENT">One-time payment</option>
          </select></div>
        {form.taxStatus === "SINK" ? (
          <div><label className={labelClass} htmlFor="se-pv-sink">SINK status</label>
            <select id="se-pv-sink" className={inputClass} value={form.sinkStatus} onChange={set("sinkStatus")}>
              <option value="">Not set</option><option value="VALID">Valid</option><option value="EXPIRED">Expired</option>
            </select></div>
        ) : (
          <div className="grid grid-cols-2 gap-2">
            <div><label className={labelClass} htmlFor="se-pv-table">Table</label>
              <input id="se-pv-table" className={inputClass} value={form.taxTable} onChange={set("taxTable")} placeholder="32" /></div>
            <div><label className={labelClass} htmlFor="se-pv-col">Column</label>
              <input id="se-pv-col" className={inputClass} value={form.taxColumn} onChange={set("taxColumn")} /></div>
          </div>
        )}
        {form.incomeRole === "ONE_TIME_PAYMENT" && (
          <div><label className={labelClass} htmlFor="se-pv-annual">Expected annual income (SEK)</label>
            <input id="se-pv-annual" className={inputClass} inputMode="decimal" value={form.annualIncome} onChange={set("annualIncome")} /></div>
        )}
        <div><label className={labelClass} htmlFor="se-pv-prior">Already paid this month (SEK)</label>
          <input id="se-pv-prior" className={inputClass} inputMode="decimal" value={form.monthToDatePrior} onChange={set("monthToDatePrior")} /></div>
        <div><label className={labelClass} htmlFor="se-pv-slp">Pension-cost base for SLP (SEK)</label>
          <input id="se-pv-slp" className={inputClass} inputMode="decimal" value={form.pensionCostBase} onChange={set("pensionCostBase")} /></div>
      </div>
      <button type="button" onClick={run} disabled={running}
        className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary-hover disabled:opacity-60">
        {running ? "Calculating…" : "Run preview"}
      </button>
      {error && <p role="alert" className="text-xs text-error">{error}</p>}
      {out?.blocked && (
        <p role="status" className="rounded-lg border border-warning/40 bg-warning-light px-3 py-2 text-xs text-foreground-secondary">
          Blocked on <span className="font-mono">{out.blockedKey}</span>: {out.blockedReason}
        </p>
      )}
      {se && (
        <dl className="grid grid-cols-1 gap-x-6 gap-y-1 rounded-xl border border-border p-3 text-xs sm:grid-cols-2">
          <dt className="text-foreground-muted">Withholding ({se.withholding.strategy})</dt><dd className="font-medium text-foreground">SEK {se.withholding.amount}</dd>
          <dt className="text-foreground-muted">Employer contributions ({se.employer_contribution.cohort})</dt><dd className="font-medium text-foreground">SEK {se.employer_contribution.amount}</dd>
          <dt className="text-foreground-muted">SLP</dt><dd className="font-medium text-foreground">SEK {se.slp}</dd>
          <dt className="text-foreground-muted">Net pay</dt><dd className="font-medium text-foreground">SEK {out.result.netPay}</dd>
          {(se.employer_contribution.components || []).map((c) => (
            <div key={c.key} className="contents">
              <dt className="pl-3 text-foreground-muted">{c.key} @ {c.ratePct}%{c.base ? ` on ${c.base}` : ""}</dt>
              <dd className="text-foreground-secondary">SEK {c.amount}</dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}

export default function SEReadinessTab({ pack }) {
  if (!pack) return <p className="text-xs text-foreground-muted">Select a Sweden tax pack.</p>;
  return (
    <div className="space-y-6">
      <Readiness packId={pack.id} />
      <Preview pack={pack} />
    </div>
  );
}
