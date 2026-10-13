import { useEffect, useState } from "react";
import { CheckCircle2, CircleAlert } from "lucide-react";
import { getSwissReadiness, previewSwissCalculation } from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";
import StatutoryTraceDrawer from "../../payroll/StatutoryTraceDrawer";

// Switzerland release gates G1-G7 (re-derived server-side on every read —
// never cached, never fabricated) plus the read-only calculation preview
// against a real CH employee. Matches how SEReadinessTab/ITReadinessTab sit
// in their own workspaces: the same pack-management surface, Switzerland's
// readiness is org-independent so it renders for any selected pack.
function Readiness() {
  const [result, setResult] = useState({ data: null, error: null });
  useEffect(() => {
    let live = true;
    getSwissReadiness()
      .then((data) => { if (live) setResult({ data, error: null }); })
      .catch((e) => { if (live) setResult({ data: null, error: e?.message || "Failed to load readiness" }); });
    return () => { live = false; };
  }, []);
  if (result.error) return <p role="alert" className="text-xs text-error">{result.error}</p>;
  const { ready, gates = [], cantons = [], onDate } = result.data || {};
  if (!onDate) return <p className="text-xs text-foreground-muted">Loading readiness…</p>;

  const readyCantons = cantons.filter((c) => c.ready).length;

  return (
    <section aria-labelledby="ch-gates-heading" className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id="ch-gates-heading" className="text-sm font-semibold text-foreground">
          Release gates <span className="font-normal text-foreground-muted">(as of {onDate})</span>
        </h3>
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${ready ? "bg-success-light text-success" : "bg-warning-light text-warning"}`}>
          {ready ? "Ready to activate" : "Not ready — live Swiss payroll stays disabled"}
        </span>
        <span className="rounded-full bg-surface-muted px-2 py-0.5 text-[11px] text-foreground-muted">
          {readyCantons}/26 cantons staged
        </span>
      </div>
      <ul className="divide-y divide-border-light rounded-xl border border-border">
        {gates.map((g) => (
          <li key={g.key} className="flex items-start gap-2 px-3 py-2 text-xs">
            {g.complete
              ? <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-success" aria-label="Complete" />
              : <CircleAlert size={14} className="mt-0.5 shrink-0 text-warning" aria-label="Incomplete" />}
            <div>
              <p className="font-medium text-foreground">{g.label}</p>
              {g.detail && <p className="text-foreground-muted">{g.detail}</p>}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

const PREVIEW_DEFAULTS = { organizationId: "", employeeId: "", payDate: "", monthlyBaseSalary: "" };

function Preview() {
  const [form, setForm] = useState(PREVIEW_DEFAULTS);
  const [running, setRunning] = useState(false);
  const [out, setOut] = useState(null);
  const [error, setError] = useState(null);
  const [traceOpen, setTraceOpen] = useState(false);

  async function run() {
    if (!form.organizationId || !form.employeeId || !form.payDate) {
      setError("Organization id, employee id and payment date are required."); return;
    }
    setRunning(true); setError(null);
    try {
      const payload = {
        organizationId: Number(form.organizationId), employeeId: Number(form.employeeId), payDate: form.payDate,
        ...(form.monthlyBaseSalary ? { earnings: { base_salary: form.monthlyBaseSalary } } : {}),
      };
      setOut(await previewSwissCalculation(payload));
    } catch (e) {
      setError(e?.message || "Preview failed.");
    } finally {
      setRunning(false);
    }
  }

  const t = out && !out.blocked ? out.switzerland?.totals : null;
  const money = (v) => `CHF ${v ?? "—"}`;

  return (
    <section aria-labelledby="ch-preview-heading" className="space-y-3">
      <h3 id="ch-preview-heading" className="text-sm font-semibold text-foreground">Calculation preview (read-only)</h3>
      <p className="text-xs text-foreground-muted">
        Runs the production resolver and Swiss engine for one real CH employee on the payment date. Nothing is saved; a
        missing fact or row returns the engine&apos;s own block, never a guessed figure.
      </p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
        <div><label className={labelClass} htmlFor="ch-pv-org">Organization id</label>
          <input id="ch-pv-org" type="number" className={inputClass} value={form.organizationId} onChange={(e) => setForm({ ...form, organizationId: e.target.value })} /></div>
        <div><label className={labelClass} htmlFor="ch-pv-emp">Employee id</label>
          <input id="ch-pv-emp" type="number" className={inputClass} value={form.employeeId} onChange={(e) => setForm({ ...form, employeeId: e.target.value })} /></div>
        <div><label className={labelClass} htmlFor="ch-pv-date">Payment date</label>
          <input id="ch-pv-date" type="date" className={inputClass} value={form.payDate} onChange={(e) => setForm({ ...form, payDate: e.target.value })} /></div>
        <div><label className={labelClass} htmlFor="ch-pv-basic">Monthly base salary (optional; defaults to CTC/12)</label>
          <input id="ch-pv-basic" className={inputClass} inputMode="decimal" value={form.monthlyBaseSalary} onChange={(e) => setForm({ ...form, monthlyBaseSalary: e.target.value })} /></div>
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
      {t && (
        <dl className="grid grid-cols-1 gap-x-6 gap-y-1 rounded-xl border border-border p-3 text-xs sm:grid-cols-2">
          <dt className="text-foreground-muted">Gross</dt><dd className="font-medium text-foreground">{money(out.result?.gross)}</dd>
          <dt className="text-foreground-muted">Total deductions</dt><dd className="font-medium text-foreground">{money(out.result?.totalDeductions)}</dd>
          <dt className="text-foreground-muted">Net pay</dt><dd className="font-semibold text-foreground">{money(out.result?.netPay)}</dd>
          {/* ch_employee_total / ch_employer_total are the engine's full statutory
              totals (AHV/IV/EO/ALV, BVG, UVG, KTG, QST, FAK, admin cost) */}
          <dt className="text-foreground-muted">Employee statutory deductions (incl. QST)</dt><dd className="font-medium text-foreground">{money(t.ch_employee_total)}</dd>
          <dt className="text-foreground-muted">QST withheld (source tax)</dt><dd className="font-medium text-foreground">{money(t.ch_qst_total)}</dd>
          <dt className="text-foreground-muted">BVG employee share</dt><dd className="font-medium text-foreground">{money(t.ch_bvg_employee)}</dd>
          <dt className="text-foreground-muted">Employer statutory cost</dt><dd className="font-medium text-foreground">{money(t.ch_employer_total)}</dd>
          {out.switzerland?.trace && (
            <>
              <dt className="text-foreground-muted">Input / rule hash</dt>
              <dd className="font-mono text-[10px] text-foreground-disabled break-all">
                {(out.switzerland.trace.input_hash || "").slice(0, 12)} / {(out.switzerland.trace.rule_hash || "").slice(0, 12)}
              </dd>
            </>
          )}
        </dl>
      )}
      {t && out.switzerland?.trace && (
        <button type="button" onClick={() => setTraceOpen(true)}
          className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:bg-surface-muted">
          View statutory trace
        </button>
      )}
      <StatutoryTraceDrawer open={traceOpen} onClose={() => setTraceOpen(false)}
        snapshot={out?.switzerland} title="Swiss calculation preview" currency="CHF" />
    </section>
  );
}

export default function CHReadinessTab() {
  return (
    <div className="space-y-6">
      <Readiness />
      <Preview />
    </div>
  );
}