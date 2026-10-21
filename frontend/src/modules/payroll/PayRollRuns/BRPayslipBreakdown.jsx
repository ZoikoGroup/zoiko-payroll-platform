import { ChevronDown, ListTree } from "lucide-react";
import { useState } from "react";
import {
  formatBRL,
  getBrEarningsLines,
  getBrDeductionsLines,
  getBrEmployerLines,
  getBrBasesLines,
  getBrTrace,
  BR_LABELS,
} from "./brPayslipLines";

const SECTION_STYLE = {
  earnings: "text-primary",
  deductions: "text-error",
  employer: "text-category-teal",
  bases: "text-info",
};

export default function BRPayslipBreakdown({ snapshot, employeeName }) {
  const [traceOpen, setTraceOpen] = useState(false);

  const earnings = getBrEarningsLines(snapshot);
  const deductions = getBrDeductionsLines(snapshot);
  const employer = getBrEmployerLines(snapshot);
  const bases = getBrBasesLines(snapshot);
  const trace = getBrTrace(snapshot);

  function renderSection(title, items, colorClass) {
    if (!items.length) return null;
    return (
      <div>
        <p className={`text-[11px] font-bold uppercase tracking-widest ${SECTION_STYLE[colorClass] || "text-foreground"} mb-2`}>{title}</p>
        {items.length === 0 ? (
          <p className="text-[12px] text-foreground-muted">No line items.</p>
        ) : (
          <dl className="space-y-1.5">
            {items.map(({ label, amount }, idx) => (
              <div key={`${label}-${idx}`} className="flex items-center justify-between text-[12px]">
                <dt className="text-foreground-muted">{label}</dt>
                <dd className="font-semibold text-foreground">{amount}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {trace && (
        <div className="flex items-center justify-end mb-3">
          <button
            type="button"
            onClick={() => setTraceOpen(true)}
            className="flex items-center gap-1.5 text-[12px] font-semibold px-3 py-1.5 rounded-[10px] border border-border text-foreground transition-all duration-200 hover:border-primary hover:text-primary"
          >
            <ListTree size={13} />
            Statutory trace
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {renderSection("Earnings", earnings, "earnings")}
        {renderSection("Deductions", deductions, "deductions")}
        {renderSection("Employer Contributions", employer, "employer")}
        {renderSection("Bases", bases, "bases")}
      </div>

      <div className="mt-4 rounded-[14px] border border-border p-4 bg-surface-muted">
        <p className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted mb-3">Key Figures</p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-[12px]">
          {[
            ["Gross Pay", snapshot.grossPay || snapshot.salary],
            ["Total Deductions", snapshot.totalDeductions],
            ["Net Pay", snapshot.netPay],
          ].map(([label, val]) => (
            <div key={label} className="flex items-center justify-between">
              <span className="text-foreground-muted">{label}</span>
              <span className="font-semibold text-foreground">{formatBRL(val)}</span>
            </div>
          ))}
        </div>
      </div>

      {trace && (
        <div className="mt-4 rounded-[14px] border border-border p-4 bg-surface-muted">
          <p className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted mb-3">Engine Trace (JSON)</p>
          <pre className="text-[10px] font-mono text-foreground overflow-x-auto max-h-[300px]">
            {JSON.stringify(trace, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}