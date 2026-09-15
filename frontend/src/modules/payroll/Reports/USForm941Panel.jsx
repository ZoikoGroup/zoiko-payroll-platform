import { useState } from "react";
import { getApplicableReportTemplate, generateUs941 } from "../../../service/payrollService";

// US Form 941 — Employer's Quarterly Federal Tax Return (Production-
// Readiness Plan Phase 5). A fixed IRS calendar quarter, employer-level,
// never tied to a single PayrollRun — same reasoning as CAPd7aPanel for
// its own tab rather than being forced into the run-scoped Generate
// Report flow.
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

function currentYear() {
  return new Date().getFullYear();
}

function currentQuarter() {
  return Math.floor(new Date().getMonth() / 3) + 1;
}

export default function USForm941Panel() {
  const [year, setYear] = useState(currentYear());
  const [quarter, setQuarter] = useState(currentQuarter());
  const [status, setStatus] = useState("idle");
  const [message, setMessage] = useState("");

  async function handleGenerate() {
    setStatus("generating");
    setMessage("");
    try {
      const { template } = await getApplicableReportTemplate({ reportingYear: String(year), reportType: "941" });
      if (!template) {
        setStatus("error");
        setMessage(`No Published/Active 941 template found for ${year} — a Super Admin needs to author and activate one first (Compliance > United States > Report Templates).`);
        return;
      }
      const generated = await generateUs941({ reportTemplateId: template.id, year: Number(year), quarter: Number(quarter) });
      setStatus("done");
      const totalTax = generated.renderedData?.employer?.line6_total_taxes_before_adjustments ?? 0;
      setMessage(`Generated — report #${generated.id}. Total taxes before adjustments for Q${quarter} ${year}: $${Number(totalTax).toLocaleString("en-US")}.`);
    } catch (err) {
      setStatus("error");
      setMessage(err.message || "Could not generate this return.");
    }
  }

  return (
    <div className="max-w-xl space-y-4">
      <div className="rounded-[14px] border border-border bg-surface p-5">
        <h3 className="mb-1 text-[15px] font-bold text-foreground">Form 941 — Employer's Quarterly Federal Tax Return</h3>
        <p className="mb-4 text-[12px] text-foreground-secondary">
          Sums wages, federal income tax withheld, and combined employee + employer Social Security/Medicare tax
          across every finalized (Approved/Authorized/Paid/Closed — never Draft/Review) US payslip paid within the
          chosen IRS calendar quarter. Lines 5c/5d (regular vs. Additional Medicare) are combined — see the
          generated report's own "knownGaps" for the full list of disclosed simplifications, including that total
          deposits/balance due are not computed (no deposits-made ledger exists in this platform).
        </p>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Year">
            <input type="number" className={inputClass} value={year} onChange={(e) => setYear(e.target.value)} />
          </Field>
          <Field label="Quarter">
            <select className={inputClass} value={quarter} onChange={(e) => setQuarter(e.target.value)}>
              <option value={1}>Q1 (Jan–Mar)</option>
              <option value={2}>Q2 (Apr–Jun)</option>
              <option value={3}>Q3 (Jul–Sep)</option>
              <option value={4}>Q4 (Oct–Dec)</option>
            </select>
          </Field>
        </div>
        <div className="mt-4 flex justify-end">
          <button
            onClick={handleGenerate} disabled={status === "generating" || !year || !quarter}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50"
          >
            {status === "generating" ? "Generating…" : "Generate Form 941"}
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
