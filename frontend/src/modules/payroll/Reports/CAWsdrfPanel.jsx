import { useState } from "react";
import { calculateCaWsdrf } from "../../../service/payrollService";

// Quebec WSDRF (Workforce Skills Development and Recognition Fund,
// ZP-TAX-CA-2026-001 §13/§15, gap-closure Phase 7) — an ANNUAL
// reconciliation figure (1% of total Quebec payroll minus declared
// eligible training expenditure), not tied to any single payroll run,
// same reasoning as CAPd7aPanel/INForm138Panel for its own tab.
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

export default function CAWsdrfPanel() {
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [result, setResult] = useState(null);
  const [status, setStatus] = useState("idle");
  const [message, setMessage] = useState("");

  async function handleCalculate() {
    setStatus("calculating");
    setMessage("");
    setResult(null);
    try {
      const data = await calculateCaWsdrf({ periodStart, periodEnd });
      setResult(data);
      setStatus("done");
    } catch (err) {
      setStatus("error");
      setMessage(err.message || "Could not calculate WSDRF.");
    }
  }

  return (
    <div className="max-w-xl space-y-4">
      <div className="rounded-[14px] border border-border bg-surface p-5">
        <h3 className="mb-1 text-[15px] font-bold text-foreground">WSDRF — Workforce Skills Development and Recognition Fund</h3>
        <p className="mb-4 text-[12px] text-foreground-secondary">
          1% of total Quebec payroll (real, finalized payslips only) for the period, minus this employer's own
          declared eligible training expenditure (Compliance &gt; Canada &gt; Workers' Compensation &amp; Employer
          Profiles — component QC_WSDRF_TRAINING_EXPENDITURE). An annual reconciliation figure, not a per-payslip
          deduction.
        </p>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Period start"><input type="date" className={inputClass} value={periodStart} onChange={(e) => setPeriodStart(e.target.value)} /></Field>
          <Field label="Period end"><input type="date" className={inputClass} value={periodEnd} onChange={(e) => setPeriodEnd(e.target.value)} /></Field>
        </div>
        <div className="mt-4 flex justify-end">
          <button
            onClick={handleCalculate} disabled={status === "calculating" || !periodStart || !periodEnd}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50"
          >
            {status === "calculating" ? "Calculating…" : "Calculate WSDRF"}
          </button>
        </div>
        {message && (
          <p className="mt-3 rounded-[12px] bg-error/10 px-3.5 py-2.5 text-[12px] text-error">{message}</p>
        )}
        {result && (
          <dl className="mt-3 space-y-1 rounded-[12px] border border-border-light bg-surface p-3.5 text-[12px]">
            <div className="flex justify-between"><dt className="text-foreground-muted">Total Quebec payroll</dt><dd className="text-foreground">${Number(result.totalQuebecPayroll).toLocaleString("en-CA")}</dd></div>
            <div className="flex justify-between"><dt className="text-foreground-muted">Required investment ({Number(result.wsdrfRatePct)}%)</dt><dd className="text-foreground">${Number(result.requiredInvestment).toLocaleString("en-CA")}</dd></div>
            <div className="flex justify-between"><dt className="text-foreground-muted">Eligible training expenditure</dt><dd className="text-foreground">${Number(result.trainingExpenditure).toLocaleString("en-CA")}</dd></div>
            <div className="flex justify-between border-t border-border-light pt-1"><dt className="font-semibold text-foreground">Shortfall owed</dt><dd className="font-bold text-foreground">${Number(result.shortfall).toLocaleString("en-CA")}</dd></div>
          </dl>
        )}
      </div>
    </div>
  );
}
