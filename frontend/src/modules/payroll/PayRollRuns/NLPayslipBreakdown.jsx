import { useState } from "react";
import { ListTree } from "lucide-react";
import Drawer from "../../../components/Drawer";
import { formatCurrency } from "../../../utils/currency";
import { nlEmployeeLines, nlEmployerLines } from "./nlPayslipLines";

// Netherlands payslip breakdown (NL-048): what the EMPLOYEE gets (gross →
// deductions → net) and what the EMPLOYER pays on top, kept apart so an
// employer premium is never read as a deduction. Every amount is the engine's
// own figure from the payslip's frozen nl_calculation_snapshot — nothing is
// computed here.
const eur = (v) => formatCurrency(Number(v) || 0, "EUR");

function Lines({ title, lines, total, totalLabel }) {
  return (
    <div className="rounded-[14px] border border-border p-4">
      <h5 className="mb-2 text-[11px] font-bold uppercase tracking-widest text-foreground-muted">{title}</h5>
      <dl className="space-y-1 text-[12px]">
        {lines.map(([label, value]) => (
          <div key={label} className="flex justify-between gap-3">
            <dt className="text-foreground-secondary">{label}</dt><dd className="text-foreground">{eur(value)}</dd>
          </div>
        ))}
        <div className="flex justify-between gap-3 border-t border-border pt-1 font-semibold">
          <dt className="text-foreground">{totalLabel}</dt><dd className="text-foreground">{eur(total)}</dd>
        </div>
      </dl>
    </div>
  );
}

function TraceStep({ step }) {
  const { code, ...rest } = step || {};
  return (
    <li className="rounded-[10px] border border-border px-3 py-2">
      <p className="text-[12px] font-semibold text-foreground">{code || "step"}</p>
      <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px]">
        {Object.entries(rest).map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-foreground-muted">{k}</dt>
            <dd className="break-all text-foreground">{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>
          </div>
        ))}
      </dl>
    </li>
  );
}

export default function NLPayslipBreakdown({ snapshot, employeeName }) {
  const [traceOpen, setTraceOpen] = useState(false);
  if (!snapshot) return null;
  const t = snapshot.totals || {};
  const exceptions = snapshot.exceptions || [];
  return (
    <div className="mb-4">
      <div className="mb-2 flex items-center justify-between">
        <h4 className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">
          Netherlands — employee pay and employer cost
        </h4>
        {snapshot.trace?.length > 0 && (
          <button type="button" onClick={(e) => { e.stopPropagation(); setTraceOpen(true); }}
            className="flex items-center gap-1.5 rounded-[10px] border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground hover:border-primary hover:text-primary">
            <ListTree size={13} /> Calculation trace
          </button>
        )}
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <Lines title="Employee — deducted from pay" lines={[["Gross", t.gross], ...nlEmployeeLines(snapshot)]}
          total={t.netPay} totalLabel="Net pay" />
        <Lines title="Employer — paid on top, never deducted" lines={nlEmployerLines(snapshot)}
          total={t.employerCost} totalLabel="Total employer cost" />
      </div>
      {exceptions.length > 0 && (
        <ul className="mt-2 space-y-1 text-[12px]">
          {exceptions.map((x, i) => (
            <li key={`${x.code}-${i}`} className={x.severity === "BLOCK" ? "text-error" : "text-warning"}>
              {x.severity}: {x.message}
            </li>
          ))}
        </ul>
      )}
      {traceOpen && (
        <Drawer title={`Calculation trace — ${employeeName}`} width="max-w-2xl"
          subtitle={`Netherlands · engine ${snapshot.engineVersion || "—"} · input hash ${(snapshot.inputHash || "").slice(0, 12)}…`}
          onClose={() => setTraceOpen(false)}>
          <ol className="space-y-2">
            {snapshot.trace.map((step, i) => <TraceStep key={i} step={step} />)}
          </ol>
        </Drawer>
      )}
    </div>
  );
}
