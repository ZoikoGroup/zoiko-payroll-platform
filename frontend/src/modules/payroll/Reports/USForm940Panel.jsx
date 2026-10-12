import { useState } from "react";
import { getApplicableReportTemplate, generateUs940 } from "../../../service/payrollService";

// US Form 940 — Employer's Annual Federal Unemployment (FUTA) Tax Return
// (Production-Readiness Plan Phase 5). Calendar year, employer-level,
// never tied to a single PayrollRun — same reasoning as USForm941Panel.
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

export default function USForm940Panel() {
  const [year, setYear] = useState(currentYear());
  const [status, setStatus] = useState("idle");
  const [message, setMessage] = useState("");

  async function handleGenerate() {
    setStatus("generating");
    setMessage("");
    try {
      const { template } = await getApplicableReportTemplate({ reportingYear: String(year), reportType: "940" });
      if (!template) {
        setStatus("error");
        setMessage(`No Published/Active 940 template found for ${year} — a Super Admin needs to author and activate one first (Compliance > United States > Report Templates).`);
        return;
      }
      const generated = await generateUs940({ reportTemplateId: template.id, year: Number(year) });
      setStatus("done");
      const taxDue = generated.renderedData?.employer?.futa_tax_due ?? 0;
      setMessage(`Generated — report #${generated.id}. FUTA tax due for ${year}: $${Number(taxDue).toLocaleString("en-US")}.`);
    } catch (err) {
      setStatus("error");
      setMessage(err.message || "Could not generate this return.");
    }
  }

  return (
    <div className="max-w-xl space-y-4">
      <div className="rounded-[14px] border border-border bg-surface p-5">
        <h3 className="mb-1 text-[15px] font-bold text-foreground">Form 940 — Employer's Annual FUTA Tax Return</h3>
        <p className="mb-4 text-[12px] text-foreground-secondary">
          Sums total payments and FUTA tax across every finalized (Approved/Authorized/Paid/Closed — never Draft/
          Review) US payslip paid during the calendar year. Taxable FUTA wages independently re-applies the real
          $7,000/employee/year wage-base cap. Payments exempt from FUTA and credit-reduction states are not
          modeled — see the generated report's own "knownGaps" for details.
        </p>
        <Field label="Year">
          <input type="number" className={inputClass} value={year} onChange={(e) => setYear(e.target.value)} />
        </Field>
        <div className="mt-4 flex justify-end">
          <button
            onClick={handleGenerate} disabled={status === "generating" || !year}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50"
          >
            {status === "generating" ? "Generating…" : "Generate Form 940"}
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
