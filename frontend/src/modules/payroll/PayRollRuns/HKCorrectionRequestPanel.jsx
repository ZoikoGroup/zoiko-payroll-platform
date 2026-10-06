import { useState } from "react";
import { requestHkCorrection } from "../../../service/payrollService";

// Hong Kong linked correction request (gap-closure D-14), shown on a COMMITTED
// run. The server recalculates the payslip on its own frozen statutory pack
// from the employee's current facts and creates a delta for a different
// operator to approve — the original payslip is never edited.
const COMMITTED = ["Approved", "Authorized", "Paid", "Closed", "APPROVED", "AUTHORIZED", "PAID", "CLOSED"];
const input = "w-full rounded-lg border border-border bg-surface px-3 py-2 text-[13px] text-foreground";
const btn = "rounded-lg bg-primary px-3 py-1.5 text-[12px] font-semibold text-white disabled:opacity-60";

export default function HKCorrectionRequestPanel({ run, items }) {
  const [reasons, setReasons] = useState({});
  const [results, setResults] = useState({});
  const [errors, setErrors] = useState({});
  const hkItems = (items || []).filter((i) => (i.country || i.countryCode) === "HK");
  if (!hkItems.length) return null;
  if ((run?.notes || "").startsWith("[HK-CORRECTION]")) {
    return (
      <p className="mb-5 rounded-[12px] border border-info/20 bg-info/5 px-3 py-2 text-[12px] text-info">
        This is a Hong Kong correction run (a linked delta of a committed payslip). Approve or reject it in
        Compliance → Hong Kong Compliance Centre → Corrections.
      </p>
    );
  }
  if (!COMMITTED.includes(run?.status)) return null;

  async function request(item) {
    setErrors((e) => ({ ...e, [item.id]: null }));
    try {
      const out = await requestHkCorrection(item.id, reasons[item.id] || "");
      setResults((r) => ({ ...r, [item.id]: out }));
    } catch (err) {
      setErrors((e) => ({ ...e, [item.id]: err?.message || "The correction was not accepted." }));
    }
  }

  return (
    <section className="mb-5 rounded-[18px] border border-border p-5" aria-labelledby="hk-correction-heading">
      <h4 id="hk-correction-heading" className="mb-2 text-[11px] font-bold uppercase tracking-widest text-foreground-muted">
        Hong Kong corrections
      </h4>
      <p className="mb-3 text-[12px] text-foreground-muted">
        Correct the employee&apos;s facts first (pay, attendance, hours, statutory profile), then request the correction here.
      </p>
      <ul className="space-y-2">
        {hkItems.map((item) => (
          <li key={item.id} className="text-[12px]">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold text-foreground">{item.employeeName || item.name || `Payslip ${item.id}`}</span>
              <input aria-label={`Correction reason for payslip ${item.id}`} placeholder="Reason for the correction"
                className={`${input} max-w-sm`} onChange={(e) => setReasons({ ...reasons, [item.id]: e.target.value })} />
              <button type="button" className={btn} onClick={() => request(item)}>Request correction</button>
            </div>
            {errors[item.id] && <p role="alert" className="mt-1 text-error">{errors[item.id]}</p>}
            {results[item.id] && (
              <p role="status" className="mt-1 text-success">
                Correction #{results[item.id].id} requested: net pay HK$ {results[item.id].netPayDelta} — awaiting approval by a different operator.
              </p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
