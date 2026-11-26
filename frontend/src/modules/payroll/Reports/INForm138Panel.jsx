import { useMemo, useState } from "react";
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

function formatDue(iso) {
  if (!iso) return "";
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

// years / filingCalendar come from the Super Admin report catalog (Reports
// page); without them the panel keeps its original free-text year and the
// standard quarter due dates.
export default function INForm138Panel({ years = [], filingCalendar = [] } = {}) {
  const [reportingYear, setReportingYear] = useState(() => {
    const current = currentIndiaTaxYear();
    return years.length && !years.includes(current) ? years[0] : current;
  });
  const [periodKey, setPeriodKey] = useState("Q1");
  // Quarter labels carry the real due date Super Admin published for the
  // chosen year when there is one.
  const quarters = useMemo(() => QUARTERS.map((q) => {
    const row = filingCalendar.find((c) => c.reportingYear === reportingYear && c.periodKey === q.value);
    return row?.dueDate ? { ...q, label: `${q.label.split(" (")[0]} (due ${formatDue(row.dueDate)})` } : q;
  }), [filingCalendar, reportingYear]);
  const due = filingCalendar.find((c) => c.reportingYear === reportingYear && c.periodKey === periodKey);
  const [status, setStatus] = useState("idle");
  const [message, setMessage] = useState("");
  const [result, setResult] = useState(null);

  async function handleGenerate() {
    setStatus("generating");
    setMessage("");
    setResult(null);
    try {
      const { template } = await getApplicableReportTemplate({ reportingYear, reportType: "FORM_138", country: "IN" });
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
          pay period falls within the chosen quarter&apos;s real calendar date range, not just one payroll run.
        </p>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Reporting year (India FY)">
            {years.length > 0 ? (
              <select className={inputClass} value={reportingYear} onChange={(e) => setReportingYear(e.target.value)}>
                {[...new Set([...years, reportingYear])].map((y) => <option key={y} value={y}>{y}</option>)}
              </select>
            ) : (
              <input className={inputClass} value={reportingYear} onChange={(e) => setReportingYear(e.target.value)} placeholder="2026-27" />
            )}
          </Field>
          <Field label="Quarter">
            <select className={inputClass} value={periodKey} onChange={(e) => setPeriodKey(e.target.value)}>
              {quarters.map((q) => <option key={q.value} value={q.value}>{q.label}</option>)}
            </select>
          </Field>
        </div>
        {due?.dueDate && (
          <p className="mt-3 text-[12px] text-foreground-secondary" data-testid="form138-due-date">
            Due date: <span className="font-semibold text-foreground">{formatDue(due.dueDate)}</span>
            {due.paymentDueDate ? ` · payment due ${formatDue(due.paymentDueDate)}` : ""}
          </p>
        )}
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
