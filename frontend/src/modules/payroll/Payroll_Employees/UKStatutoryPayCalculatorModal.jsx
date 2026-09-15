import { useState } from "react";
import Modal from "../../../components/Modal";
import { calculateUkStatutoryPay } from "../../../service/payrollService";

// On-demand UK Statutory Sick Pay / Statutory Family Pay calculator
// (ZP-TAX-UK-2026-27-001 §11/§12 gap-closure Phase 5, 2026-09-09).
// Deliberately a PREVIEW tool, not a payslip mutation — there is no
// leave-management model in this codebase tracking illness/maternity/
// paternity/adoption start dates or claim week-numbers, so a payroll
// processor supplies the event details here and reads the result off to
// apply manually via whatever existing off-cycle/ad-hoc payslip addition
// the org already uses (see the "Add/override a payslip" action on a
// Payroll Run). This never creates or edits a payslip itself.
const PAYMENT_TYPES = [
  { value: "SSP", label: "Statutory Sick Pay (SSP)" },
  { value: "SMP", label: "Statutory Maternity Pay (SMP)" },
  { value: "SPP", label: "Statutory Paternity Pay (SPP)" },
  { value: "SAP", label: "Statutory Adoption Pay (SAP)" },
  { value: "SHPP", label: "Statutory Shared Parental Pay (ShPP)" },
  { value: "SPBP", label: "Statutory Parental Bereavement Pay (SPBP)" },
  { value: "SNCP", label: "Statutory Neonatal Care Pay (SNCP)" },
];

const inputClass =
  "w-full rounded-[12px] border border-border bg-background px-3.5 py-2.5 text-[13px] text-foreground placeholder:text-foreground-muted focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200";
const selectClass = inputClass;

function Field({ label, children, hint }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[11px] font-bold uppercase tracking-widest text-foreground-muted">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-foreground-muted">{hint}</span>}
    </label>
  );
}

export default function UKStatutoryPayCalculatorModal({ employee, onClose }) {
  const [paymentType, setPaymentType] = useState("SSP");
  const [eventStartDate, setEventStartDate] = useState("");
  const [weekNumber, setWeekNumber] = useState("1");
  const [qualifyingDaysInPeriod, setQualifyingDaysInPeriod] = useState("");
  const [qualifyingDaysPerWeek, setQualifyingDaysPerWeek] = useState("");
  const [averageWeeklyEarnings, setAverageWeeklyEarnings] = useState("");
  const [includeEmployerRecovery, setIncludeEmployerRecovery] = useState(false);
  const [priorYearTotalClass1Nic, setPriorYearTotalClass1Nic] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [calculating, setCalculating] = useState(false);

  const isSsp = paymentType === "SSP";

  async function handleCalculate() {
    setError("");
    setResult(null);
    if (!eventStartDate) {
      setError("Event start date is required.");
      return;
    }
    if (isSsp && (!qualifyingDaysInPeriod || !qualifyingDaysPerWeek)) {
      setError("Qualifying days in period and qualifying days per week are required for SSP.");
      return;
    }
    setCalculating(true);
    try {
      const data = await calculateUkStatutoryPay({
        employeeId: employee.id,
        paymentType,
        eventStartDate,
        weekNumber: isSsp ? undefined : Number(weekNumber) || 1,
        qualifyingDaysInPeriod: isSsp ? Number(qualifyingDaysInPeriod) : null,
        qualifyingDaysPerWeek: isSsp ? Number(qualifyingDaysPerWeek) : null,
        averageWeeklyEarnings: averageWeeklyEarnings !== "" ? averageWeeklyEarnings : null,
        includeEmployerRecovery: !isSsp && includeEmployerRecovery,
        priorYearTotalClass1Nic: !isSsp && includeEmployerRecovery && priorYearTotalClass1Nic !== "" ? priorYearTotalClass1Nic : null,
      });
      setResult(data);
    } catch (err) {
      setError(err.message || "Could not calculate statutory pay.");
    } finally {
      setCalculating(false);
    }
  }

  return (
    <Modal title={`Statutory Pay Calculator — ${employee.name}`} onClose={onClose} maxWidth="max-w-xl">
      <p className="mb-4 rounded-[12px] bg-info/10 px-3.5 py-2.5 text-[12px] text-foreground-secondary">
        This is a preview calculation only — it does not create or change any payslip.
        Apply the result yourself via an off-cycle payslip addition on the relevant payroll run.
      </p>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Payment type">
          <select className={selectClass} value={paymentType} onChange={(e) => { setPaymentType(e.target.value); setResult(null); }}>
            {PAYMENT_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </Field>
        <Field label={isSsp ? "Illness start date" : "Leave/claim start date"}>
          <input type="date" className={inputClass} value={eventStartDate} onChange={(e) => setEventStartDate(e.target.value)} />
        </Field>

        {isSsp ? (
          <>
            <Field label="Qualifying days in period">
              <input type="number" min="1" className={inputClass} value={qualifyingDaysInPeriod} onChange={(e) => setQualifyingDaysInPeriod(e.target.value)} />
            </Field>
            <Field label="Qualifying days per week">
              <input type="number" min="1" max="7" className={inputClass} value={qualifyingDaysPerWeek} onChange={(e) => setQualifyingDaysPerWeek(e.target.value)} />
            </Field>
          </>
        ) : (
          <Field label="Week number of claim" hint="1-indexed — used to detect SMP/SAP's uncapped first 6 weeks.">
            <input type="number" min="1" className={inputClass} value={weekNumber} onChange={(e) => setWeekNumber(e.target.value)} />
          </Field>
        )}

        <Field label="Average Weekly Earnings (optional)" hint="Leave blank to derive automatically from this employee's pay history.">
          <input type="number" min="0" step="0.01" className={inputClass} value={averageWeeklyEarnings} onChange={(e) => setAverageWeeklyEarnings(e.target.value)} placeholder="Auto-derive" />
        </Field>

        {!isSsp && (
          <Field label="Employer recovery">
            <label className="flex items-center gap-2 pt-2.5 text-[13px] text-foreground">
              <input type="checkbox" checked={includeEmployerRecovery} onChange={(e) => setIncludeEmployerRecovery(e.target.checked)} />
              Also calculate employer recovery
            </label>
          </Field>
        )}

        {!isSsp && includeEmployerRecovery && (
          <Field label="Employer's prior-year total Class 1 NIC">
            <input type="number" min="0" step="0.01" className={inputClass} value={priorYearTotalClass1Nic} onChange={(e) => setPriorYearTotalClass1Nic(e.target.value)} />
          </Field>
        )}
      </div>

      {error && (
        <div className="mt-4 rounded-[12px] bg-error/10 px-4 py-3 text-[13px] text-error border border-error/20">{error}</div>
      )}

      {result && (
        <div className={`mt-4 rounded-[12px] border px-4 py-3.5 ${result.eligible ? "border-success/30 bg-success/10" : "border-warning/30 bg-warning/10"}`}>
          {result.eligible ? (
            <>
              <p className="text-[13px] font-bold text-foreground">Amount: {Number(result.amount).toFixed(2)}</p>
              <p className="mt-1 text-[12px] text-foreground-secondary">
                Average Weekly Earnings: {Number(result.averageWeeklyEarnings).toFixed(2)} ({result.averageWeeklyEarningsSource})
              </p>
              {result.employerRecovery && (
                <p className="mt-2 text-[12px] text-foreground-secondary border-t border-border-light pt-2">
                  {result.employerRecovery.eligible
                    ? `Employer recovery: ${Number(result.employerRecovery.recoveryAmount).toFixed(2)}`
                    : `Employer recovery not available: ${result.employerRecovery.reason}`}
                </p>
              )}
            </>
          ) : (
            <p className="text-[13px] font-semibold text-warning">Not eligible / not computable: {result.reason}</p>
          )}
        </div>
      )}

      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Close</button>
        <button
          onClick={handleCalculate} disabled={calculating}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50"
        >
          {calculating ? "Calculating…" : "Calculate"}
        </button>
      </div>
    </Modal>
  );
}
