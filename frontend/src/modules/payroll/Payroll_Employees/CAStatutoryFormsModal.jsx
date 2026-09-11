import { useState } from "react";
import Modal from "../../../components/Modal";
import {
  getApplicableReportTemplate, generateCaT4, generateCaRl1, generateCaRoe, calculateCaSpecialPayment,
  calculateCaRetiringAllowance, calculateCaTd1xCommission, updateEmployee,
} from "../../../service/payrollService";

// Canada T4 / RL-1 / ROE per-employee statutory forms (ZP-TAX-CA-2026-001
// forms/reports gap-closure). Mirrors IndiaStatutoryFormsModal's
// GenerateCertificateBlock pattern — resolve the applicable Published/
// Active template for the report type first, no template picker, same
// reasoning as that file's own version of this block.

function currentCalendarYear() {
  return new Date().getFullYear();
}

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

function GenerateCertificateBlock({ reportType, reportingYear, asOfDate, buttonLabel, hint, onGenerate }) {
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
          onClick={handleGenerate} disabled={status === "generating" || !asOfDate}
          className="shrink-0 rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground-secondary hover:border-primary hover:text-primary disabled:opacity-50"
        >
          {status === "generating" ? "Generating…" : buttonLabel}
        </button>
      </div>
      {message && <p className={`mt-2 text-[11px] ${status === "error" ? "text-error" : "text-success"}`}>{message}</p>}
    </div>
  );
}

// Bonus/retroactive-pay/vacation-not-taken/accumulated-overtime
// special-payment method (§19) — CRA's real incremental-tax calculation,
// not a flat supplemental rate. regularAnnualPay is required from the
// operator — see calculate_ca_special_payment_withholding's own
// docstring for why this isn't guessed from stored fields.
function SpecialPaymentSection({ employee }) {
  const [regularAnnualPay, setRegularAnnualPay] = useState("");
  const [specialPaymentAmount, setSpecialPaymentAmount] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [calculating, setCalculating] = useState(false);

  async function handleCalculate() {
    setError("");
    setResult(null);
    setCalculating(true);
    try {
      const data = await calculateCaSpecialPayment({
        employeeId: employee.id,
        regularAnnualPay: regularAnnualPay || 0,
        specialPaymentAmount: specialPaymentAmount || 0,
      });
      setResult(data);
    } catch (err) {
      setError(err.message || "Could not calculate special-payment withholding.");
    } finally {
      setCalculating(false);
    }
  }

  return (
    <div className="mt-5 border-t border-border pt-4">
      <p className="mb-3 rounded-[12px] bg-info/10 px-3.5 py-2.5 text-[12px] text-foreground-secondary">
        For a bonus, retroactive pay increase, vacation pay paid without leave being taken, or accumulated
        overtime paid separately. Computes the INCREMENTAL federal + provincial tax (tax on regular pay plus the
        special payment, minus tax on regular pay alone) — not a flat rate. This does not create a payslip line.
      </p>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Regular annual pay (excluding this payment)">
          <input type="number" min="0" step="0.01" className={inputClass} value={regularAnnualPay} onChange={(e) => setRegularAnnualPay(e.target.value)} />
        </Field>
        <Field label="Special payment amount">
          <input type="number" min="0" step="0.01" className={inputClass} value={specialPaymentAmount} onChange={(e) => setSpecialPaymentAmount(e.target.value)} />
        </Field>
      </div>
      <div className="mt-3 flex justify-end">
        <button
          onClick={handleCalculate} disabled={calculating || !regularAnnualPay || !specialPaymentAmount}
          className="rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground-secondary hover:border-primary hover:text-primary disabled:opacity-50"
        >
          {calculating ? "Calculating…" : "Calculate withholding"}
        </button>
      </div>
      {error && <div className="mt-3 rounded-[12px] bg-error/10 px-4 py-3 text-[13px] text-error border border-error/20">{error}</div>}
      {result && (
        <dl className="mt-3 space-y-1 rounded-[12px] border border-border-light bg-surface p-3.5 text-[12px]">
          <div className="flex justify-between"><dt className="text-foreground-muted">Federal withholding</dt><dd className="font-semibold text-foreground">${Number(result.federalWithholding).toLocaleString("en-CA")}</dd></div>
          <div className="flex justify-between"><dt className="text-foreground-muted">Provincial{result.isQuebec ? " (Quebec)" : ""} withholding</dt><dd className="font-semibold text-foreground">${Number(result.provincialWithholding).toLocaleString("en-CA")}</dd></div>
          <div className="flex justify-between border-t border-border-light pt-1"><dt className="font-semibold text-foreground">Total withholding</dt><dd className="font-bold text-foreground">${Number(result.totalWithholding).toLocaleString("en-CA")}</dd></div>
        </dl>
      )}
    </div>
  );
}

// Retiring allowance / severance (§19) — federal lump-sum rate-table
// lookup. Resolves to 0% until real CRA-sourced bands are entered via
// Super Admin (Compliance > Canada > Rate & Threshold Registry, rule
// type CA_RETIRING_ALLOWANCE_BAND) — no hardcoded rate exists anywhere.
function RetiringAllowanceSection({ employee }) {
  const [amount, setAmount] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [calculating, setCalculating] = useState(false);

  async function handleCalculate() {
    setError("");
    setResult(null);
    setCalculating(true);
    try {
      const data = await calculateCaRetiringAllowance({ employeeId: employee.id, amount: amount || 0 });
      setResult(data);
    } catch (err) {
      setError(err.message || "Could not calculate retiring-allowance withholding.");
    } finally {
      setCalculating(false);
    }
  }

  return (
    <div className="mt-5 border-t border-border pt-4">
      <p className="mb-3 rounded-[12px] bg-info/10 px-3.5 py-2.5 text-[12px] text-foreground-secondary">
        Federal lump-sum withholding for a retiring allowance or severance payment. Resolves to 0% until a Super
        Admin has entered real CRA-sourced rate bands — this platform does not guess a statutory rate. Quebec's
        own combined federal+provincial rate is not modeled here.
      </p>
      <Field label="Retiring allowance / severance amount">
        <input type="number" min="0" step="0.01" className={inputClass} value={amount} onChange={(e) => setAmount(e.target.value)} />
      </Field>
      <div className="mt-3 flex justify-end">
        <button
          onClick={handleCalculate} disabled={calculating || !amount}
          className="rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground-secondary hover:border-primary hover:text-primary disabled:opacity-50"
        >
          {calculating ? "Calculating…" : "Calculate withholding"}
        </button>
      </div>
      {error && <div className="mt-3 rounded-[12px] bg-error/10 px-4 py-3 text-[13px] text-error border border-error/20">{error}</div>}
      {result && (
        <dl className="mt-3 space-y-1 rounded-[12px] border border-border-light bg-surface p-3.5 text-[12px]">
          {!result.configured && (
            <p className="mb-2 text-[11px] font-semibold text-warning">No rate bands configured — withholding shown is $0, not a real calculation.</p>
          )}
          <div className="flex justify-between"><dt className="text-foreground-muted">Rate applied</dt><dd className="font-semibold text-foreground">{Number(result.ratePct)}%</dd></div>
          <div className="flex justify-between border-t border-border-light pt-1"><dt className="font-semibold text-foreground">Withholding</dt><dd className="font-bold text-foreground">${Number(result.withholding).toLocaleString("en-CA")}</dd></div>
        </dl>
      )}
    </div>
  );
}

// TD1X commission formula (§18/§19) — reads the employee's own on-file
// estimated annual commission/expenses. No dedicated employee-form field
// exists for these yet (matching the same pre-existing gap TD1/
// provincial-TD1/LSVCC declarations already have — none of them have a
// UI either), so this section itself doubles as the entry point:
// save the election here, then calculate.
function Td1xCommissionSection({ employee, onEmployeeUpdated }) {
  const [commission, setCommission] = useState(employee.td1xEstimatedAnnualCommission ?? "");
  const [expenses, setExpenses] = useState(employee.td1xEstimatedAnnualExpenses ?? "");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [calculating, setCalculating] = useState(false);
  const hasElection = employee.td1xEstimatedAnnualCommission != null;

  async function handleSave() {
    setSaveError("");
    setSaving(true);
    try {
      const updated = await updateEmployee(employee.id, {
        td1xEstimatedAnnualCommission: commission || 0,
        td1xEstimatedAnnualExpenses: expenses || 0,
      });
      onEmployeeUpdated?.(updated);
    } catch (err) {
      setSaveError(err.message || "Could not save the TD1X election.");
    } finally {
      setSaving(false);
    }
  }

  async function handleCalculate() {
    setError("");
    setResult(null);
    setCalculating(true);
    try {
      const data = await calculateCaTd1xCommission({ employeeId: employee.id });
      setResult(data);
    } catch (err) {
      setError(err.message || "Could not calculate TD1X commission withholding.");
    } finally {
      setCalculating(false);
    }
  }

  return (
    <div className="mt-5 border-t border-border pt-4">
      <p className="mb-3 rounded-[12px] bg-info/10 px-3.5 py-2.5 text-[12px] text-foreground-secondary">
        CRA's real commission formula for an employee with a TD1X election on file — uses estimated annual
        commission income minus estimated annual expenses, not annualized periodic salary.
      </p>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Estimated annual commission">
          <input type="number" min="0" step="0.01" className={inputClass} value={commission} onChange={(e) => setCommission(e.target.value)} />
        </Field>
        <Field label="Estimated annual expenses">
          <input type="number" min="0" step="0.01" className={inputClass} value={expenses} onChange={(e) => setExpenses(e.target.value)} />
        </Field>
      </div>
      <div className="mt-3 flex justify-end gap-2">
        <button
          onClick={handleSave} disabled={saving || !commission}
          className="rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground-secondary hover:border-primary hover:text-primary disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save election"}
        </button>
        <button
          onClick={handleCalculate} disabled={calculating || !hasElection}
          className="rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground-secondary hover:border-primary hover:text-primary disabled:opacity-50"
        >
          {calculating ? "Calculating…" : "Calculate per-period withholding"}
        </button>
      </div>
      {saveError && <div className="mt-3 rounded-[12px] bg-error/10 px-4 py-3 text-[13px] text-error border border-error/20">{saveError}</div>}
      {error && <div className="mt-3 rounded-[12px] bg-error/10 px-4 py-3 text-[13px] text-error border border-error/20">{error}</div>}
      {result && (
        <dl className="mt-3 space-y-1 rounded-[12px] border border-border-light bg-surface p-3.5 text-[12px]">
          <div className="flex justify-between"><dt className="text-foreground-muted">Net annual commission income</dt><dd className="text-foreground">${Number(result.netAnnualCommissionIncome).toLocaleString("en-CA")}</dd></div>
          <div className="flex justify-between"><dt className="text-foreground-muted">Total annual tax</dt><dd className="text-foreground">${Number(result.totalAnnualTax).toLocaleString("en-CA")}</dd></div>
          <div className="flex justify-between border-t border-border-light pt-1"><dt className="font-semibold text-foreground">Recommended per-period withholding</dt><dd className="font-bold text-foreground">${Number(result.perPeriodWithholding).toLocaleString("en-CA")}</dd></div>
        </dl>
      )}
    </div>
  );
}

export default function CAStatutoryFormsModal({ employee: initialEmployee, onClose }) {
  const [employee, setEmployee] = useState(initialEmployee);
  const [taxYear, setTaxYear] = useState(currentCalendarYear());
  const yearEndDate = `${taxYear}-12-31`;
  const [roeAsOfDate, setRoeAsOfDate] = useState("");

  return (
    <Modal title={`Canada Statutory Forms — ${employee.name}`} onClose={onClose} maxWidth="max-w-2xl">
      <p className="mb-4 rounded-[12px] bg-info/10 px-3.5 py-2.5 text-[12px] text-foreground-secondary">
        T4 and RL-1 (Quebec) are calendar-year-end slips. ROE (Record of Employment) is triggered by an actual
        interruption of earnings — set the last day worked below before generating it. ROE's insurable-hours
        block (15C) is not populated; only insurable earnings and EI premiums are.
      </p>

      <div className="mb-4">
        <Field label="Calendar year (for T4 / RL-1)" hint={`Year-end date used: ${yearEndDate}`}>
          <input
            type="number" className={inputClass} value={taxYear}
            onChange={(e) => setTaxYear(e.target.value)}
          />
        </Field>
      </div>

      <GenerateCertificateBlock
        reportType="T4" reportingYear={taxYear} asOfDate={yearEndDate}
        buttonLabel="Generate T4"
        hint={`T4 - Statement of Remuneration Paid, for ${taxYear} (as of ${yearEndDate}).`}
        onGenerate={(templateId) => generateCaT4({ reportTemplateId: templateId, employeeId: employee.id, asOfDate: yearEndDate })}
      />

      <GenerateCertificateBlock
        reportType="RL1" reportingYear={taxYear} asOfDate={yearEndDate}
        buttonLabel="Generate RL-1"
        hint={`RL-1 - Releve de renseignements (Quebec), for ${taxYear} (as of ${yearEndDate}).`}
        onGenerate={(templateId) => generateCaRl1({ reportTemplateId: templateId, employeeId: employee.id, asOfDate: yearEndDate })}
      />

      <div className="mt-5 border-t border-border pt-4">
        <Field label="Last day worked / interruption date" hint="Required before generating an ROE.">
          <input type="date" className={inputClass} value={roeAsOfDate} onChange={(e) => setRoeAsOfDate(e.target.value)} />
        </Field>
        <GenerateCertificateBlock
          reportType="ROE" reportingYear={taxYear} asOfDate={roeAsOfDate}
          buttonLabel="Generate ROE"
          hint="Record of Employment, as of the interruption date above."
          onGenerate={(templateId) => generateCaRoe({ reportTemplateId: templateId, employeeId: employee.id, asOfDate: roeAsOfDate })}
        />
      </div>

      <SpecialPaymentSection employee={employee} />
      <RetiringAllowanceSection employee={employee} />
      <Td1xCommissionSection employee={employee} onEmployeeUpdated={setEmployee} />

      <div className="mt-5 flex justify-end">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Close</button>
      </div>
    </Modal>
  );
}
