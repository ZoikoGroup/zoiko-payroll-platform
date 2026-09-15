import { Link } from "react-router-dom";
import { ExternalLink, Info } from "lucide-react";

// India Gratuity (ZP-TAX-IN-2026-27-001 §11, gap-closure Phase F,
// 2026-09-11) — a READ view of the current rate-map params
// india.py's calculate_gratuity() actually consumes
// (gratuity_max_amt/gratuity_min_yrs, both already editable on the "Tax
// Parameters" tab's Retirement & Exemption Limits section), plus a link
// to the existing employee-scoped gratuity calculator ("Gratuity &
// Statutory Forms" on an employee's own record, Payroll > Employees) —
// NOT a new calculation engine. calculate_gratuity() is explicitly
// documented (india.py) as a standalone function with no callers from
// the recurring payroll cycle, tied instead to a one-time termination/
// retirement event with its own inputs — this tab does not change that.
const GRATUITY_KEYS = ["gratuity_max_amt", "gratuity_min_yrs"];
const LABELS = {
  gratuity_max_amt: "Gratuity Maximum Notified Amount",
  gratuity_min_yrs: "Gratuity Minimum Qualifying Years",
};

export default function INGratuityTab({ rates }) {
  const rows = (rates || []).filter((r) => GRATUITY_KEYS.includes(r.componentKey));

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-info/30 bg-info/5 px-3 py-2 text-[11px] text-foreground-secondary flex gap-2">
        <Info size={14} className="mt-0.5 shrink-0" />
        <span>
          Gratuity is an employer termination/retirement LIABILITY, not a recurring payroll deduction (§11) — this
          is a read-only view of the rate-map parameters india.py's calculate_gratuity() actually uses. To edit
          them, use the "Tax Parameters" tab's Retirement &amp; Exemption Limits section (they're the same
          canonical rows). To test the calculation for a real employee, use the calculator embedded on that
          employee's own record.
        </span>
      </div>

      <div className="rounded-xl border border-border">
        <div className="border-b border-border-light px-4 py-3">
          <p className="text-sm font-bold text-foreground">Current Rate-Map Parameters</p>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 p-4">
          {GRATUITY_KEYS.map((key) => {
            const row = rows.find((r) => r.componentKey === key);
            return (
              <div key={key}>
                <p className="text-[11px] font-semibold uppercase tracking-wide text-foreground-muted">{LABELS[key]}</p>
                <p className="mt-1 text-lg font-bold text-foreground">
                  {row?.flatAmount != null ? (key === "gratuity_max_amt" ? `₹${Number(row.flatAmount).toLocaleString("en-IN")}` : row.flatAmount) : (
                    <span className="text-sm font-normal text-foreground-disabled">Not configured</span>
                  )}
                </p>
              </div>
            );
          })}
        </div>
      </div>

      <div className="rounded-xl border border-border p-4">
        <p className="text-sm font-bold text-foreground">Test a Real Calculation</p>
        <p className="mt-1 text-xs text-foreground-muted">
          The actual "15 days' wages per completed year" gratuity calculator is embedded on each employee's own
          record — open Payroll &gt; Employees, select an employee, and use its "Gratuity &amp; Statutory Forms
          (122/123/124)" section.
        </p>
        <Link
          to="/payroll/employees"
          className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted"
        >
          <ExternalLink size={13} /> Go to Payroll &gt; Employees
        </Link>
      </div>
    </div>
  );
}
