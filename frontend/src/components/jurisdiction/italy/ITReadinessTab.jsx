import { useEffect, useState } from "react";
import { CheckCircle2, CircleAlert } from "lucide-react";
import { getItalyReadiness, previewItalyCalculation } from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";
import { IT_CAP_COHORTS, IT_CONTRACT_TYPES, IT_LAUNCH_COMMUNI, IT_REGIONS, IT_TFR_DESTINATIONS } from "./itComponentConfig";

// Italy release gates (spec §27 G1-G8) and the read-only calculation preview.
// Rendered exactly as the backend returns it — no gate is shown as passed
// without backend evidence, and every figure comes from the production
// engine server-side. This component never computes a statutory amount.
function Readiness({ packId }) {
  const [result, setResult] = useState({ key: null, data: null, error: null });
  useEffect(() => {
    let live = true;
    getItalyReadiness(packId)
      .then((data) => { if (live) setResult({ key: packId, data, error: null }); })
      .catch((e) => { if (live) setResult({ key: packId, data: null, error: e?.message || "Failed to load readiness" }); });
    return () => { live = false; };
  }, [packId]);
  if (result.key !== packId) return <p className="text-xs text-foreground-muted">Loading readiness…</p>;
  if (result.error) return <p role="alert" className="text-xs text-error">{result.error}</p>;
  const { ready, items = [] } = result.data || {};
  return (
    <section aria-labelledby="it-readiness-heading" className="space-y-2">
      <div className="flex items-center gap-2">
        <h3 id="it-readiness-heading" className="text-sm font-semibold text-foreground">Release gates</h3>
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${ready ? "bg-success-light text-success" : "bg-warning-light text-warning"}`}>
          {ready ? "Ready to activate" : "Not ready — live Italian payroll stays disabled"}
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
  payDate: "", gross: "", workerClass: "IMPIEGATO", contractType: "INDETERMINATO", cigsApplies: false,
  capCohort: "", tfrDestination: "", pensionFund: "", taxDomicileRegion: "03", taxDomicileComune: "F205",
  cscCode: "70501", caCode: "", fund: "CIG", fisBand: "", priorYearAvgHeadcount: "",
  mensilitaPaidPrior: "0", ytdTaxablePrior: "0", ytdIrpefWithheldPrior: "0", ytdContributoryBasePrior: "0",
  workDaysInYear: "365", addregSaldoDue: "0", addcomSaldoDue: "0", addcomAccontoDue: "0",
};

const Money = ({ value }) => <>EUR {value ?? "—"}</>;

function Preview({ pack }) {
  const [form, setForm] = useState(PREVIEW_DEFAULTS);
  const [running, setRunning] = useState(false);
  const [out, setOut] = useState(null);
  const [error, setError] = useState(null);
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));
  const blank = (v) => (v === "" ? null : v);

  async function run() {
    if (!form.payDate || !form.gross) { setError("Payment date and monthly gross are required."); return; }
    setRunning(true); setError(null);
    try {
      setOut(await previewItalyCalculation({
        jurisdictionPackId: pack.id, payDate: form.payDate, gross: form.gross,
        workerClass: form.workerClass, contractType: form.contractType, cigsApplies: form.cigsApplies,
        capCohort: blank(form.capCohort), tfrDestination: blank(form.tfrDestination), pensionFund: blank(form.pensionFund),
        taxDomicileRegion: form.taxDomicileRegion, taxDomicileComune: form.taxDomicileComune,
        cscCode: form.cscCode, caCode: blank(form.caCode), fund: form.fund, fisBand: blank(form.fisBand),
        priorYearAvgHeadcount: blank(form.priorYearAvgHeadcount),
        mensilitaPaidPrior: Number(form.mensilitaPaidPrior || 0), ytdTaxablePrior: form.ytdTaxablePrior || "0",
        ytdIrpefWithheldPrior: form.ytdIrpefWithheldPrior || "0", ytdContributoryBasePrior: form.ytdContributoryBasePrior || "0",
        workDaysInYear: Number(form.workDaysInYear || 365),
        addregSaldoDue: blank(form.addregSaldoDue), addcomSaldoDue: blank(form.addcomSaldoDue),
        addcomAccontoDue: blank(form.addcomAccontoDue),
      }));
    } catch (e) {
      setError(e?.message || "Preview failed.");
    } finally {
      setRunning(false);
    }
  }

  const it = out && !out.blocked ? out.italy : null;
  const field = (id, label, input) => (
    <div><label className={labelClass} htmlFor={id}>{label}</label>{input}</div>
  );
  const text = (key, label, props = {}) => field(`it-pv-${key}`, label,
    <input id={`it-pv-${key}`} className={inputClass} value={form[key]} onChange={set(key)} {...props} />);
  const select = (key, label, options, allowBlank) => field(`it-pv-${key}`, label,
    <select id={`it-pv-${key}`} className={inputClass} value={form[key]} onChange={set(key)}>
      {allowBlank && <option value="">{allowBlank}</option>}
      {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>);
  const pairs = (list) => list.map((v) => [v, v]);

  return (
    <section aria-labelledby="it-preview-heading" className="space-y-3">
      <h3 id="it-preview-heading" className="text-sm font-semibold text-foreground">Calculation preview (read-only)</h3>
      <p className="text-xs text-foreground-muted">
        Runs the production Italy engine against this pack&apos;s rows in force on the payment date, for one ordinary
        full month. Nothing is saved. A missing fact or row returns the engine&apos;s own block, never a guessed figure.
      </p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {text("payDate", "Payment date", { type: "date" })}
        {text("gross", "Monthly gross (EUR)", { inputMode: "decimal" })}
        {text("workerClass", "Worker class")}
        {select("contractType", "Contract", pairs(IT_CONTRACT_TYPES))}
        {select("taxDomicileRegion", "Tax domicile region", IT_REGIONS.map(([c, n]) => [c, `${c} — ${n}`]))}
        {field("it-pv-comune", "Tax domicile comune (cadastral code)",
          <>
            <input id="it-pv-comune" className={inputClass} list="it-pv-communi" value={form.taxDomicileComune} onChange={set("taxDomicileComune")} />
            <datalist id="it-pv-communi">{IT_LAUNCH_COMMUNI.map(([c, n]) => <option key={c} value={c}>{n}</option>)}</datalist>
          </>)}
        {text("cscCode", "Employer CSC")}
        {text("caCode", "Employer CA (optional)")}
        {select("fund", "Income-support fund", [["CIG", "CIG"], ["FIS", "FIS"]])}
        {form.fund === "FIS" && select("fisBand", "FIS size band", [["UP_TO_5", "Up to 5 employees"], ["OVER_5", "Over 5 employees"]], "Select…")}
        {select("tfrDestination", "TFR destination", pairs(IT_TFR_DESTINATIONS), "Not elected")}
        {form.tfrDestination === "FONDO_PENSIONE" && text("pensionFund", "Pension fund")}
        {["AZIENDA", "FONDO_TESORERIA"].includes(form.tfrDestination) && text("priorYearAvgHeadcount", "Prior-year average headcount", { inputMode: "numeric" })}
        {select("capCohort", "Contribution-ceiling cohort", pairs(IT_CAP_COHORTS), "None (no evidence)")}
        {text("mensilitaPaidPrior", "Mensilità already paid this year", { inputMode: "numeric" })}
        {text("workDaysInYear", "Days employed in the year", { inputMode: "numeric" })}
        {text("ytdTaxablePrior", "YTD taxable income (EUR)", { inputMode: "decimal" })}
        {text("ytdIrpefWithheldPrior", "YTD IRPEF withheld (EUR)", { inputMode: "decimal" })}
        {text("ytdContributoryBasePrior", "YTD contributory base (EUR)", { inputMode: "decimal" })}
        {text("addregSaldoDue", "Regional surtax balance due this year (EUR)", { inputMode: "decimal" })}
        {text("addcomSaldoDue", "Municipal surtax balance due (EUR)", { inputMode: "decimal" })}
        {text("addcomAccontoDue", "Municipal surtax advance due (EUR)", { inputMode: "decimal" })}
        <label className="flex items-center gap-2 text-xs text-foreground-secondary">
          <input type="checkbox" checked={form.cigsApplies} onChange={set("cigsApplies")} /> CIGS applies to this worker
        </label>
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
      {it && (
        <dl className="grid grid-cols-1 gap-x-6 gap-y-1 rounded-xl border border-border p-3 text-xs sm:grid-cols-2">
          <dt className="text-foreground-muted">Employee INPS (incl. additional 1%: <Money value={it.inps.additional1pct} />)</dt>
          <dd className="font-medium text-foreground"><Money value={it.inps.employee} /></dd>
          <dt className="text-foreground-muted">IRPEF withheld</dt><dd className="font-medium text-foreground"><Money value={it.irpef.withheld} /></dd>
          <dt className="pl-3 text-foreground-muted">Annual net IRPEF / detrazione / additional deduction</dt>
          <dd className="text-foreground-secondary"><Money value={it.irpef.annualNet} /> / <Money value={it.irpef.detrazione} /> / <Money value={it.irpef.additionalDeduction} /></dd>
          <dt className="text-foreground-muted">Wedge non-taxable sum (added to net)</dt><dd className="font-medium text-foreground"><Money value={it.wedge.taxFreeSum} /></dd>
          <dt className="text-foreground-muted">Local surtax withheld (regional / municipal balance / municipal advance)</dt>
          <dd className="text-foreground-secondary"><Money value={it.localTax.regionalSaldo} /> / <Money value={it.localTax.municipalSaldo} /> / <Money value={it.localTax.municipalAcconto} /></dd>
          <dt className="text-foreground-muted">Net pay</dt><dd className="font-semibold text-foreground"><Money value={out.result.netPay} /></dd>
          <dt className="mt-2 text-foreground-muted">Employer INPS (remitted)</dt><dd className="mt-2 font-medium text-foreground"><Money value={it.inps.employer} /></dd>
          <dt className="text-foreground-muted">TFR accrual — employer reserve, not remitted ({it.tfr.destination || "no destination elected"})</dt>
          <dd className="font-medium text-foreground"><Money value={it.tfr.net} /></dd>
        </dl>
      )}
    </section>
  );
}

export default function ITReadinessTab({ pack }) {
  if (!pack) return <p className="text-xs text-foreground-muted">Select an Italy tax pack.</p>;
  return (
    <div className="space-y-6">
      <Readiness packId={pack.id} />
      <Preview pack={pack} />
    </div>
  );
}
