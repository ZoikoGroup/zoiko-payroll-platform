import { useState } from "react";
import { previewHongKongCalculation } from "../../../service/superAdminService";

// Hong Kong calculation preview — the backend runs the production engine
// (countries/hong_kong.py) against the rows of the pack covering the pay
// date (Draft included) and writes nothing. No statutory maths in React.
const input = "w-full rounded-lg border border-border bg-surface px-3 py-2 text-[13px] text-foreground";
const label = "mb-1 block text-[12px] font-semibold text-foreground-secondary";
const FREQUENCIES = ["Monthly", "Weekly", "Fortnightly", "Daily"];

export default function HKCalculationPreviewTab() {
  const [form, setForm] = useState({
    payDate: "2026-06-30", periodStart: "", periodEnd: "", payFrequency: "Monthly", gross: "20000",
    dateOfBirth: "1990-01-01", dateOfJoining: "2024-01-01",
  });
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e) {
    e.preventDefault();
    setError(null);
    try {
      setResult(await previewHongKongCalculation({
        ...form, periodStart: form.periodStart || undefined, periodEnd: form.periodEnd || undefined,
      }));
    } catch (err) {
      setError(err?.message || "The preview was refused.");
    }
  }

  const fields = [
    ["payDate", "Pay date", "date"], ["periodStart", "Period start (optional)", "date"],
    ["periodEnd", "Period end (optional)", "date"], ["gross", "Gross (HK$)", "text"],
    ["dateOfBirth", "Date of birth", "date"], ["dateOfJoining", "Employment start", "date"],
  ];
  return (
    <div className="space-y-4">
      <form onSubmit={submit} className="grid grid-cols-1 gap-3 rounded-xl border border-border bg-surface p-4 sm:grid-cols-3"
        aria-label="Hong Kong calculation preview">
        {fields.map(([k, text, type]) => (
          <div key={k}>
            <label className={label} htmlFor={`hkp-${k}`}>{text}</label>
            <input id={`hkp-${k}`} type={type} inputMode={k === "gross" ? "decimal" : undefined} className={input}
              value={form[k]} onChange={set(k)} />
          </div>
        ))}
        <div>
          <label className={label} htmlFor="hkp-freq">Pay frequency</label>
          <select id="hkp-freq" className={input} value={form.payFrequency} onChange={set("payFrequency")}>
            {FREQUENCIES.map((f) => <option key={f}>{f}</option>)}
          </select>
        </div>
        <div className="sm:col-span-3">
          <button type="submit" className="rounded-lg bg-primary px-4 py-2 text-[13px] font-semibold text-white">Preview</button>
        </div>
      </form>
      {error && <p role="alert" className="text-[13px] text-error">{error}</p>}
      {result && (
        <div className="rounded-xl border border-border bg-surface p-4 text-[13px]">
          <p className="mb-2 font-semibold text-foreground">
            {result.status} · {result.packId} {result.packVersion ? `v${result.packVersion}` : ""} ({result.packStatus})
          </p>
          {result.status === "BLOCKED" ? (
            <p className="text-warning">{result.reason} ({result.key})</p>
          ) : (
            <dl className="grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-4">
              <dt className="text-foreground-muted">MPF employee</dt><dd>HK$ {result.mpfEmployee}</dd>
              <dt className="text-foreground-muted">MPF employer</dt><dd>HK$ {result.mpfEmployer}</dd>
              <dt className="text-foreground-muted">Salaries Tax withheld</dt><dd>None (employee-assessed)</dd>
              <dt className="text-foreground-muted">Net pay</dt><dd>HK$ {result.netPay}</dd>
              <dt className="text-foreground-muted">MPF coverage</dt><dd>{result.trace?.mpf?.coverage?.status}</dd>
              <dt className="text-foreground-muted">Threshold branch</dt><dd>{result.trace?.mpf?.currentPeriod?.branch}</dd>
              <dt className="text-foreground-muted">Minimum wage</dt><dd>{result.trace?.minimumWage?.status}</dd>
              <dt className="text-foreground-muted">Year of assessment</dt><dd>{result.trace?.ird?.yearOfAssessment}</dd>
            </dl>
          )}
          <details className="mt-3">
            <summary className="cursor-pointer text-[12px] text-foreground-secondary">Full calculation trace</summary>
            <pre className="mt-2 max-h-96 overflow-auto rounded bg-surface-muted p-2 text-[11px]">{JSON.stringify(result.trace, null, 2)}</pre>
          </details>
        </div>
      )}
    </div>
  );
}
