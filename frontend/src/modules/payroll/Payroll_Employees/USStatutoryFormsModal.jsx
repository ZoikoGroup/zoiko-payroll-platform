import { useState } from "react";
import Modal from "../../../components/Modal";
import { calculateUsSupplementalWages, getApplicableReportTemplate, generateUsW2 } from "../../../service/payrollService";

// US supplemental wages flat-rate method (ZP-TAX-US-2026-001 §3.1, IRS
// Pub. 15) — a standalone calculator, same footing/UI pattern as
// CAStatutoryFormsModal's SpecialPaymentSection: 22% flat on qualifying
// supplemental wages, with the mandatory 37% rate applying instead to
// whatever portion of this employee's cumulative calendar-year
// supplemental wages exceeds $1,000,000. This does not create a payslip
// line — it's an on-demand calculator for a bonus/commission/severance
// payment an employer has separately identified as supplemental.

function Field({ label, children, hint }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[11px] font-bold uppercase tracking-widest text-foreground-muted">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-foreground-muted">{hint}</span>}
    </label>
  );
}

const inputClass =
  "w-full rounded-[12px] border border-border bg-background px-3.5 py-2.5 text-[13px] text-foreground placeholder:text-foreground-muted focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200";

function SupplementalWageSection({ employee }) {
  const [supplementalWageAmount, setSupplementalWageAmount] = useState("");
  const [cytdBefore, setCytdBefore] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [calculating, setCalculating] = useState(false);

  async function handleCalculate() {
    setError("");
    setResult(null);
    setCalculating(true);
    try {
      const data = await calculateUsSupplementalWages({
        employeeId: employee.id,
        supplementalWageAmount: supplementalWageAmount || 0,
        cytdSupplementalWagesBefore: cytdBefore || 0,
      });
      setResult(data);
    } catch (err) {
      setError(err.message || "Could not calculate supplemental-wage withholding.");
    } finally {
      setCalculating(false);
    }
  }

  return (
    <div className="mt-5 border-t border-border pt-4">
      <p className="mb-3 rounded-[12px] bg-info/10 px-3.5 py-2.5 text-[12px] text-foreground-secondary">
        For a bonus, commission, severance, or other payment separately identified as a supplemental wage under
        IRS Pub. 15. 22% flat on qualifying amounts; the 37% rate is MANDATORY (not elective) on whatever portion
        of this employee's cumulative calendar-year supplemental wages exceeds $1,000,000. This does not create a
        payslip line.
      </p>
      <div className="grid grid-cols-2 gap-3">
        <Field label="This supplemental payment">
          <input type="number" min="0" step="0.01" className={inputClass} value={supplementalWageAmount} onChange={(e) => setSupplementalWageAmount(e.target.value)} />
        </Field>
        <Field label="Supplemental wages paid so far this calendar year" hint="Before this payment — enter 0 if this is the first this year.">
          <input type="number" min="0" step="0.01" className={inputClass} value={cytdBefore} onChange={(e) => setCytdBefore(e.target.value)} />
        </Field>
      </div>
      <div className="mt-3 flex justify-end">
        <button
          onClick={handleCalculate} disabled={calculating || !supplementalWageAmount}
          className="rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground-secondary hover:border-primary hover:text-primary disabled:opacity-50"
        >
          {calculating ? "Calculating…" : "Calculate withholding"}
        </button>
      </div>
      {error && <div className="mt-3 rounded-[12px] bg-error/10 px-4 py-3 text-[13px] text-error border border-error/20">{error}</div>}
      {result && (
        <dl className="mt-3 space-y-1 rounded-[12px] border border-border-light bg-surface p-3.5 text-[12px]">
          <div className="flex justify-between"><dt className="text-foreground-muted">At {Number(result.flatRatePct)}% (${Number(result.amountAtFlatRate).toLocaleString("en-US")})</dt><dd className="font-semibold text-foreground">${Number(result.withholdingAtFlatRate).toLocaleString("en-US")}</dd></div>
          {Number(result.amountAtHighRate) > 0 && (
            <div className="flex justify-between"><dt className="text-foreground-muted">At {Number(result.highRatePct)}% (${Number(result.amountAtHighRate).toLocaleString("en-US")}, over $1,000,000 CYTD)</dt><dd className="font-semibold text-foreground">${Number(result.withholdingAtHighRate).toLocaleString("en-US")}</dd></div>
          )}
          <div className="flex justify-between border-t border-border-light pt-1"><dt className="font-semibold text-foreground">Total withholding</dt><dd className="font-bold text-foreground">${Number(result.totalWithholding).toLocaleString("en-US")}</dd></div>
        </dl>
      )}
    </div>
  );
}

function currentCalendarYear() {
  return new Date().getFullYear();
}

// Mirrors CAStatutoryFormsModal's GenerateCertificateBlock exactly —
// resolve the applicable Published/Active template for the report type
// first, no template picker, same reasoning as that file's own version.
function GenerateCertificateBlock({ reportType, reportingYear, buttonLabel, hint, onGenerate }) {
  const [status, setStatus] = useState("idle"); // idle | generating | done | error
  const [message, setMessage] = useState("");

  async function handleGenerate() {
    setStatus("generating");
    setMessage("");
    try {
      const { template } = await getApplicableReportTemplate({ reportingYear: String(reportingYear), reportType });
      if (!template) {
        setStatus("error");
        setMessage(`No Published/Active ${reportType} template found for ${reportingYear} — a Super Admin needs to author and activate one first (Super Admin > Report Templates).`);
        return;
      }
      const generated = await onGenerate(template.id);
      setStatus("done");
      setMessage(`Generated — report #${generated.id}. See it under this org's Reports screen.`);
    } catch (err) {
      setStatus("error");
      setMessage(err.message || "Could not generate this report.");
    }
  }

  return (
    <div className="mt-4 rounded-[14px] border border-border-light bg-surface p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-[12px] text-foreground-secondary">{hint}</p>
        <button
          onClick={handleGenerate} disabled={status === "generating"}
          className="shrink-0 rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground-secondary hover:border-primary hover:text-primary disabled:opacity-50"
        >
          {status === "generating" ? "Generating…" : buttonLabel}
        </button>
      </div>
      {message && <p className={`mt-2 text-[11px] ${status === "error" ? "text-error" : "text-success"}`}>{message}</p>}
    </div>
  );
}

function W2Section({ employee }) {
  const [taxYear, setTaxYear] = useState(currentCalendarYear());

  return (
    <div className="mt-5 border-t border-border pt-4">
      <p className="mb-3 rounded-[12px] bg-info/10 px-3.5 py-2.5 text-[12px] text-foreground-secondary">
        W-2 is a calendar-year-end wage statement, summed from this employee's own finalized (Approved/Authorized/
        Paid/Closed) payslips for the year. Boxes 1/3/5/16/18 use gross pay — no pre-tax deduction (401k/HSA/
        Section 125) reduces taxable wages in this platform yet. Box 12/13 and employee address (Box f) are not
        populated — see the generated report's own "knownGaps" for the full list.
      </p>
      <Field label="Tax year">
        <input type="number" className={inputClass} value={taxYear} onChange={(e) => setTaxYear(e.target.value)} />
      </Field>
      <GenerateCertificateBlock
        reportType="W2" reportingYear={taxYear}
        buttonLabel="Generate W-2"
        hint={`W-2 - Wage and Tax Statement, for ${taxYear}.`}
        onGenerate={(templateId) => generateUsW2({ reportTemplateId: templateId, employeeId: employee.id, taxYear: String(taxYear) })}
      />
    </div>
  );
}

export default function USStatutoryFormsModal({ employee, onClose }) {
  return (
    <Modal title={`United States Statutory Forms — ${employee.name}`} onClose={onClose} maxWidth="max-w-2xl">
      <W2Section employee={employee} />
      <SupplementalWageSection employee={employee} />
      <div className="mt-5 flex justify-end">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Close</button>
      </div>
    </Modal>
  );
}
