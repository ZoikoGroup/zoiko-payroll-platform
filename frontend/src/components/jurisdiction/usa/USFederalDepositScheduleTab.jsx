import { useState } from "react";
import { calculateUsFederalDepositSchedule } from "../../../service/payrollService";
import { inputClass, labelClass } from "../constants";

// US federal deposit/filing calendar (ZP-TAX-US-2026-001 §3.5) — org-
// scoped, not employee-scoped, so this lives as its own USA Compliance
// section rather than an employee-detail modal (same reasoning
// SuiEmployerRatesPanel/ReciprocityRulesPanel already use for org-level
// data). A standalone calculator: enter this employer's real lookback-
// period liability (and optionally accumulated undeposited liability /
// quarterly FUTA liability) to get depositor status, deposit due date,
// the $100,000 next-day rule check, the FUTA deposit trigger, and the
// Form W-2/W-3 deadline. This does not create any accounting entry.

export default function USFederalDepositScheduleTab() {
  const [lookbackPeriodLiability, setLookbackPeriodLiability] = useState("");
  const [payrollDate, setPayrollDate] = useState("");
  const [accumulated, setAccumulated] = useState("");
  const [quarterlyFuta, setQuarterlyFuta] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [calculating, setCalculating] = useState(false);

  async function handleCalculate() {
    setError("");
    setResult(null);
    setCalculating(true);
    try {
      const data = await calculateUsFederalDepositSchedule({
        lookbackPeriodLiability: lookbackPeriodLiability || 0,
        payrollDate,
        accumulatedUndepositedLiability: accumulated || null,
        quarterlyFutaLiability: quarterlyFuta || null,
      });
      setResult(data);
    } catch (err) {
      setError(err.message || "Could not calculate the federal deposit schedule.");
    } finally {
      setCalculating(false);
    }
  }

  return (
    <div className="rounded-xl border border-border bg-surface p-5">
      <div className="mb-4">
        <h2 className="text-lg font-bold text-foreground">Federal Deposit &amp; Filing Calendar</h2>
        <p className="mt-0.5 text-xs text-foreground-muted">
          IRS Pub. 15 depositor status, deposit due dates, the $100,000 next-day rule, the $500 FUTA quarterly
          deposit trigger, and the Form W-2/W-3 deadline. See ZP-TAX-US-2026-001 §3.5. Form 941's own due date is
          not shown here — this document doesn't give that figure literally, so it isn't guessed at.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <label className="block">
          <span className={labelClass}>Lookback-period tax liability</span>
          <input type="number" min="0" step="0.01" className={inputClass} value={lookbackPeriodLiability} onChange={(e) => setLookbackPeriodLiability(e.target.value)} placeholder="e.g. 35000" />
        </label>
        <label className="block">
          <span className={labelClass}>Payroll / pay date</span>
          <input type="date" className={inputClass} value={payrollDate} onChange={(e) => setPayrollDate(e.target.value)} />
        </label>
        <label className="block">
          <span className={labelClass}>Accumulated undeposited liability <span className="font-normal normal-case tracking-normal text-foreground-disabled">(optional — for the $100,000 next-day rule)</span></span>
          <input type="number" min="0" step="0.01" className={inputClass} value={accumulated} onChange={(e) => setAccumulated(e.target.value)} />
        </label>
        <label className="block">
          <span className={labelClass}>Quarterly FUTA liability <span className="font-normal normal-case tracking-normal text-foreground-disabled">(optional — for the $500 deposit trigger)</span></span>
          <input type="number" min="0" step="0.01" className={inputClass} value={quarterlyFuta} onChange={(e) => setQuarterlyFuta(e.target.value)} />
        </label>
      </div>

      <div className="mt-3 flex justify-end">
        <button
          onClick={handleCalculate} disabled={calculating || !lookbackPeriodLiability || !payrollDate}
          className="rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover disabled:opacity-50"
        >
          {calculating ? "Calculating…" : "Calculate"}
        </button>
      </div>

      {error && <div className="mt-3 rounded-lg bg-error/10 px-4 py-3 text-[13px] text-error border border-error/20">{error}</div>}

      {result && (
        <dl className="mt-4 space-y-1.5 rounded-xl border border-border-light bg-background p-4 text-xs">
          <div className="flex justify-between">
            <dt className="text-foreground-muted">Depositor status</dt>
            <dd className="font-bold text-foreground">{result.depositorStatus === "MONTHLY" ? "Monthly" : "Semiweekly"}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-foreground-muted">Deposit due date</dt>
            <dd className="font-semibold text-foreground">{result.depositDueDate}</dd>
          </div>
          {result.nextDayRuleTriggered && (
            <div className="flex justify-between rounded-md bg-warning/10 px-2 py-1">
              <dt className="font-semibold text-warning">$100,000 next-day rule triggered</dt>
              <dd className="font-bold text-warning">Due {result.nextDayDepositDueDate}</dd>
            </div>
          )}
          {result.futaDepositRequired !== null && (
            <div className="flex justify-between">
              <dt className="text-foreground-muted">FUTA deposit required this quarter</dt>
              <dd className={`font-semibold ${result.futaDepositRequired ? "text-warning" : "text-foreground"}`}>{result.futaDepositRequired ? "Yes" : "No"}</dd>
            </div>
          )}
          <div className="flex justify-between border-t border-border-light pt-1.5">
            <dt className="text-foreground-muted">Form W-2 / W-3 deadline</dt>
            <dd className="font-semibold text-foreground">{result.formW2W3Deadline}</dd>
          </div>
        </dl>
      )}
    </div>
  );
}
