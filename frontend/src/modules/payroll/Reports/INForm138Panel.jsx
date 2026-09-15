import { useState } from "react";
import { getApplicableReportTemplate, generateIndiaForm138 } from "../../../service/payrollService";

// India Form 138 — quarterly salary TDS statement (ZP-TAX-IN-2026-27-001
// §6.2/§6.3, successor to Form 24Q), gap-closure Phase E, 2026-09-10.
// Whole-quarter, employer-level, never tied to a single PayrollRun (a
// quarter spans ~3 monthly runs) — same reasoning as UKEmployerChargesPanel
// above for why this isn't folded into the run-scoped "Generate Report" tab.
const inputClass =
  "w-full rounded-[12px] border border-border bg-background px-3.5 py-2.5 text-[13px] text-foreground placeholder:text-foreground-muted focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200";

const QUARTERS = [
  { value: "Q1", label: "Q1 — April-June (due 31 Jul)" },
  { value: "Q2", label: "Q2 — July-September (due 31 Oct)" },
  { value: "Q3", label: "Q3 — October-December (due 31 Jan)" },
  { value: "Q4", label: "Q4 — January-March (due 31 May)" },
];

function currentIndiaTaxYear() {
  const now = new Date();
  const startYear = now.getMonth() + 1 >= 4 ? now.getFullYear() : now.getFullYear() - 1;
  return `${startYear}-${String(startYear + 1).slice(-2)}`;
}

function Field({ label, children }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[11px] font-bold uppercase tracking-widest text-foreground-muted">{label}</span>
      {children}
    </label>
  );
}

export default function INForm138Panel() {
  const [reportingYear, setReportingYear] = useState(currentIndiaTaxYear());
  const [periodKey, setPeriodKey] = useState("Q1");
  const [status, setStatus] = useState("idle");
  const [message, setMessage] = useState("");
  const [result, setResult] = useState(null);

  async function handleGenerate() {
    setStatus("generating");
    setMessage("");
    setResult(null);
    try {
      const { template } = await getApplicableReportTemplate({ reportingYear, reportType: "FORM_138" });
      if (!template) {
        setStatus("error");
        setMessage(`No Published/Active Form 138 template found for ${reportingYear} — a Super Admin needs to author and activate one first (Compliance > India > Report Templates).`);
        return;
      }
      const generated = await generateIndiaForm138({ reportTemplateId: template.id, reportingYear, periodKey });
      setResult(generated);
      setStatus("done");
      setMessage(`Generated — report #${generated.id}. Total TDS deducted this quarter: ₹${Number(generated.renderedData?.employer?.total_tds ?? 0).toLocaleString("en-IN")}.`);
    } catch (err) {
      setStatus("error");
      setMessage(err.message || "Could not generate this statement.");
    }
  }

  return (
    <div className="max-w-xl space-y-4">
      <div className="rounded-[14px] border border-border bg-surface p-5">
        <h3 className="mb-1 text-[15px] font-bold text-foreground">Form 138 — Quarterly Salary TDS Statement</h3>
        <p className="mb-4 text-[12px] text-foreground-secondary">
          Sums TDS across every finalized (Approved/Authorized/Paid/Closed — never Draft/Review) India payslip whose
          pay period falls within the chosen quarter's real calendar date range, not just one payroll run.
        </p>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Reporting year (India FY)">
            <input className={inputClass} value={reportingYear} onChange={(e) => setReportingYear(e.target.value)} placeholder="2026-27" />
          </Field>
          <Field label="Quarter">
            <select className={inputClass} value={periodKey} onChange={(e) => setPeriodKey(e.target.value)}>
              {QUARTERS.map((q) => <option key={q.value} value={q.value}>{q.label}</option>)}
            </select>
          </Field>
        </div>
        <div className="mt-4 flex justify-end">
          <button
            onClick={handleGenerate} disabled={status === "generating"}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50"
          >
            {status === "generating" ? "Generating…" : "Generate Form 138"}
          </button>
        </div>
        {message && (
          <p className={`mt-3 rounded-[12px] px-3.5 py-2.5 text-[12px] ${status === "error" ? "bg-error/10 text-error" : "bg-success/10 text-success"}`}>
            {message}
          </p>
        )}
      </div>
    </div>
  );
}
