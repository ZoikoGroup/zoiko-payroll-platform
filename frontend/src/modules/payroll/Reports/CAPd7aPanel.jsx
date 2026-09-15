import { useState } from "react";
import { getApplicableReportTemplate, generateCaPd7a } from "../../../service/payrollService";

// Canada PD7A — Statement of Account for Current Source Deductions
// (ZP-TAX-CA-2026-001, forms/reports gap-closure). Period-based,
// employer-level, never tied to a single PayrollRun — a CRA remittance
// period is monthly/quarterly/threshold-based, same reasoning as
// INForm138Panel for why this isn't folded into the run-scoped
// Generate Report flow.
const inputClass =
  "w-full rounded-[12px] border border-border bg-background px-3.5 py-2.5 text-[13px] text-foreground placeholder:text-foreground-muted focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200";

function Field({ label, children }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[11px] font-bold uppercase tracking-widest text-foreground-muted">{label}</span>
      {children}
    </label>
  );
}

function currentReportingYear() {
  return String(new Date().getFullYear());
}

export default function CAPd7aPanel() {
  const [reportingYear] = useState(currentReportingYear());
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [status, setStatus] = useState("idle");
  const [message, setMessage] = useState("");

  async function handleGenerate() {
    setStatus("generating");
    setMessage("");
    try {
      const { template } = await getApplicableReportTemplate({ reportingYear, reportType: "PD7A" });
      if (!template) {
        setStatus("error");
        setMessage(`No Published/Active PD7A template found for ${reportingYear} — a Super Admin needs to author and activate one first (Compliance > Canada > Report Templates).`);
        return;
      }
      const generated = await generateCaPd7a({ reportTemplateId: template.id, periodStart, periodEnd });
      setStatus("done");
      setMessage(`Generated — report #${generated.id}. Total remittance for this period: $${Number(generated.renderedData?.totalRemittance ?? 0).toLocaleString("en-CA")}.`);
    } catch (err) {
      setStatus("error");
      setMessage(err.message || "Could not generate this statement.");
    }
  }

  return (
    <div className="max-w-xl space-y-4">
      <div className="rounded-[14px] border border-border bg-surface p-5">
        <h3 className="mb-1 text-[15px] font-bold text-foreground">PD7A — Statement of Account for Current Source Deductions</h3>
        <p className="mb-4 text-[12px] text-foreground-secondary">
          Sums income tax withheld plus CPP/CPP2 and EI (employee + employer) across every finalized
          (Approved/Authorized/Paid/Closed — never Draft/Review) Canada payslip whose pay period falls within the
          chosen remittance date range, not just one payroll run.
        </p>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Period start">
            <input type="date" className={inputClass} value={periodStart} onChange={(e) => setPeriodStart(e.target.value)} />
          </Field>
          <Field label="Period end">
            <input type="date" className={inputClass} value={periodEnd} onChange={(e) => setPeriodEnd(e.target.value)} />
          </Field>
        </div>
        <div className="mt-4 flex justify-end">
          <button
            onClick={handleGenerate} disabled={status === "generating" || !periodStart || !periodEnd}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50"
          >
            {status === "generating" ? "Generating…" : "Generate PD7A"}
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
