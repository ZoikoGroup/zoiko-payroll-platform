import { useCallback, useEffect, useState } from "react";
import { Landmark, Calculator } from "lucide-react";
import {
  getUkEmployerChargesSummary,
  calculateUkEmploymentAllowance,
  calculateUkClass1A1BCharge,
} from "../../../service/payrollService";

// UK Employer Annual Charges — Employment Allowance + Class 1A/1B
// (ZP-TAX-UK-2026-27-001 §9.3/§14 gap-closure Phase 6, 2026-09-09).
// Whole-tax-year, run-independent employer liabilities — deliberately NOT
// folded into the run-scoped "Generate Report" flow above, since neither
// figure is tied to a single PayrollRun (see the backend's own comments
// on get_uk_employer_charges_summary/calculate_uk_employment_allowance/
// calculate_uk_class_1a_1b_charge for why).
const inputClass =
  "w-full rounded-[12px] border border-border bg-background px-3.5 py-2.5 text-[13px] text-foreground placeholder:text-foreground-muted focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200";

const CHARGE_TYPES = [
  { value: "BENEFITS", label: "Benefits & Expenses" },
  { value: "TERMINATION_AWARDS", label: "Termination Award" },
  { value: "SPORTING_TESTIMONIAL", label: "Sporting Testimonial" },
  { value: "PSA", label: "PAYE Settlement Agreement (PSA) item" },
];

function Field({ label, children, hint }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[11px] font-bold uppercase tracking-widest text-foreground-muted">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-foreground-muted">{hint}</span>}
    </label>
  );
}

function fmt(n) {
  const v = Number(n);
  return Number.isFinite(v) ? v.toFixed(2) : "0.00";
}

export default function UKEmployerChargesPanel() {
  const [summary, setSummary] = useState(null);
  const [summaryError, setSummaryError] = useState("");

  const [employerHasClaimed, setEmployerHasClaimed] = useState(false);
  const [allowanceResult, setAllowanceResult] = useState(null);
  const [allowanceError, setAllowanceError] = useState("");
  const [calculatingAllowance, setCalculatingAllowance] = useState(false);

  const [chargeType, setChargeType] = useState("BENEFITS");
  const [chargeAmount, setChargeAmount] = useState("");
  const [chargeResult, setChargeResult] = useState(null);
  const [chargeError, setChargeError] = useState("");
  const [calculatingCharge, setCalculatingCharge] = useState(false);

  const loadSummary = useCallback(async () => {
    setSummaryError("");
    try {
      setSummary(await getUkEmployerChargesSummary());
    } catch (err) {
      setSummaryError(err.message || "Could not load the employer charges summary.");
    }
  }, []);

  useEffect(() => {
    loadSummary();
  }, [loadSummary]);

  async function handleCalculateAllowance() {
    setAllowanceError("");
    setAllowanceResult(null);
    setCalculatingAllowance(true);
    try {
      setAllowanceResult(await calculateUkEmploymentAllowance(employerHasClaimed));
    } catch (err) {
      setAllowanceError(err.message || "Could not calculate Employment Allowance.");
    } finally {
      setCalculatingAllowance(false);
    }
  }

  async function handleCalculateCharge() {
    setChargeError("");
    setChargeResult(null);
    if (!chargeAmount) {
      setChargeError("Enter an amount for this event.");
      return;
    }
    setCalculatingCharge(true);
    try {
      setChargeResult(await calculateUkClass1A1BCharge(chargeType, chargeAmount));
    } catch (err) {
      setChargeError(err.message || "Could not calculate this Class 1A/1B charge.");
    } finally {
      setCalculatingCharge(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="bg-surface border border-border rounded-[18px] p-5">
        <div className="mb-3 flex items-center gap-2">
          <Landmark size={16} className="text-primary" />
          <h3 className="text-[14px] font-bold text-foreground">Current UK tax-year position</h3>
        </div>
        {summaryError ? (
          <p className="text-[13px] text-error">{summaryError}</p>
        ) : summary ? (
          <div className="grid grid-cols-3 gap-4">
            <div>
              <p className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Tax Year</p>
              <p className="mt-1 text-[15px] font-bold text-foreground">{summary.taxYear}</p>
            </div>
            <div>
              <p className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Cumulative Employer NI</p>
              <p className="mt-1 text-[15px] font-bold text-foreground">{fmt(summary.cumulativeEmployerNi)}</p>
            </div>
            <div>
              <p className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Apprenticeship Levy Pay Bill</p>
              <p className="mt-1 text-[15px] font-bold text-foreground">{fmt(summary.cumulativeApprenticeshipLevyPayBill)}</p>
            </div>
          </div>
        ) : (
          <p className="text-[13px] text-foreground-muted">Loading…</p>
        )}
      </div>

      <div className="bg-surface border border-border rounded-[18px] p-5">
        <div className="mb-3 flex items-center gap-2">
          <Calculator size={16} className="text-primary" />
          <h3 className="text-[14px] font-bold text-foreground">Employment Allowance</h3>
        </div>
        <label className="flex items-center gap-2 text-[13px] text-foreground">
          <input type="checkbox" checked={employerHasClaimed} onChange={(e) => setEmployerHasClaimed(e.target.checked)} />
          This employer has claimed Employment Allowance for the current tax year
        </label>
        {allowanceError && <p className="mt-2 text-[13px] text-error">{allowanceError}</p>}
        {allowanceResult && (
          <div className={`mt-3 rounded-[12px] border px-4 py-3 ${allowanceResult.eligible ? "border-success/30 bg-success/10" : "border-warning/30 bg-warning/10"}`}>
            {allowanceResult.eligible ? (
              <>
                <p className="text-[13px] font-bold text-foreground">Net employer NIC liability: {fmt(allowanceResult.netLiability)}</p>
                <p className="mt-1 text-[12px] text-foreground-secondary">Allowance remaining: {fmt(allowanceResult.allowanceRemaining)}</p>
              </>
            ) : (
              <p className="text-[13px] font-semibold text-warning">{allowanceResult.reason}</p>
            )}
          </div>
        )}
        <div className="mt-4 flex justify-end">
          <button
            onClick={handleCalculateAllowance} disabled={calculatingAllowance}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50"
          >
            {calculatingAllowance ? "Calculating…" : "Calculate"}
          </button>
        </div>
      </div>

      <div className="bg-surface border border-border rounded-[18px] p-5">
        <div className="mb-3 flex items-center gap-2">
          <Calculator size={16} className="text-primary" />
          <h3 className="text-[14px] font-bold text-foreground">Class 1A / Class 1B charge</h3>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Event type">
            <select className={inputClass} value={chargeType} onChange={(e) => { setChargeType(e.target.value); setChargeResult(null); }}>
              {CHARGE_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </Field>
          <Field label="Amount" hint="For Termination Award / Sporting Testimonial, this is the full amount — the threshold is applied automatically.">
            <input type="number" min="0" step="0.01" className={inputClass} value={chargeAmount} onChange={(e) => setChargeAmount(e.target.value)} />
          </Field>
        </div>
        {chargeError && <p className="mt-2 text-[13px] text-error">{chargeError}</p>}
        {chargeResult && (
          <div className={`mt-3 rounded-[12px] border px-4 py-3 ${chargeResult.eligible ? "border-success/30 bg-success/10" : "border-warning/30 bg-warning/10"}`}>
            {chargeResult.eligible ? (
              <p className="text-[13px] font-bold text-foreground">Charge amount: {fmt(chargeResult.chargeAmount)}</p>
            ) : (
              <p className="text-[13px] font-semibold text-warning">{chargeResult.reason}</p>
            )}
          </div>
        )}
        <div className="mt-4 flex justify-end">
          <button
            onClick={handleCalculateCharge} disabled={calculatingCharge}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50"
          >
            {calculatingCharge ? "Calculating…" : "Calculate"}
          </button>
        </div>
      </div>
    </div>
  );
}
