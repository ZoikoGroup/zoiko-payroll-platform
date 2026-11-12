import { ChevronDown, ListTree } from "lucide-react";
import { useState } from "react";

// Malaysia payslip breakdown (ZP-MY-ENG-001 "Calculation detail"). Reads the
// frozen my_result exactly as the engine wrote it (engine/countries/malaysia.py):
// coverage per obligation with its reason, the base of each obligation, the
// EPF / SOCSO / EIS schedule rows used, the HRD levy (employer cost), PCB,
// the labour territory and overtime check, minimum wage, exceptions and the
// hashes. Nothing is recomputed here, and no identifier is ever in the snapshot.

const myr = (value) => {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  return new Intl.NumberFormat("ms-MY", { style: "currency", currency: "MYR" }).format(n);
};

function Rows({ title, rows, tone = "text-info" }) {
  const visible = rows.filter(([, v]) => v !== null && v !== undefined && v !== "" && v !== "—");
  if (!visible.length) return null;
  return (
    <div>
      <p className={`mb-1 text-[11px] font-bold uppercase tracking-widest ${tone}`}>{title}</p>
      <dl className="divide-y divide-border">
        {visible.map(([label, value]) => (
          <div key={label} className="flex justify-between gap-3 py-1 text-[12px]">
            <dt className="text-foreground-muted">{label}</dt>
            <dd className="font-mono text-foreground">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

const OBLIGATIONS = ["EPF", "SOCSO", "EIS", "HRD"];

export default function MYPayslipBreakdown({ snapshot, employeeName }) {
  const [traceOpen, setTraceOpen] = useState(false);
  if (!snapshot) return null;
  const s = snapshot;
  const trace = s.trace || {};
  const bases = trace.bases || {};
  const coverage = s.coverage || {};
  const place = trace.labour?.territory || {};
  const overtime = trace.labour?.overtime || {};
  const minimum = trace.minimumWage || {};
  const schedule = (name) => {
    const t = (trace.obligations || {})[name];
    if (!t) return null;
    return t.rule ? `${t.rule}${t.band ? ` band ${t.band.join(" – ")}` : ""}` : (t.method || null);
  };

  return (
    <div className="mt-3 rounded-xl border border-border bg-surface p-4" data-testid="my-payslip-breakdown">
      <p className="mb-3 flex items-center gap-2 text-[13px] font-semibold text-foreground">
        <ListTree size={14} /> Malaysia calculation — {employeeName}
      </p>
      <div className="grid gap-4 md:grid-cols-2">
        <Rows title="Employee deductions" rows={[
          ["PCB / MTD", myr(s.my_pcb)],
          ["EPF (employee)", myr(s.my_epf?.employee)],
          ["SOCSO (employee)", myr(s.my_socso?.employee)],
          ["EIS (employee)", myr(s.my_eis?.employee)],
          ["Total employee contributions", myr(s.my_employee_total)],
          ["Net pay", myr(s.my_net)],
        ]} />
        <Rows title="Employer cost (never deducted)" tone="text-warning" rows={[
          ["EPF (employer)", myr(s.my_epf?.employer)],
          ["SOCSO (employer)", myr(s.my_socso?.employer)],
          ["EIS (employer)", myr(s.my_eis?.employer)],
          ["HRD levy", myr(s.my_hrd)],
          ["Total employer cost", myr(s.my_employer_total)],
        ]} />
        <Rows title="Coverage per obligation" rows={OBLIGATIONS.map((name) => [
          name, coverage[name] ? `${coverage[name].applies ? "Applies" : "Not applicable"} · ${coverage[name].reason}` : "—"])} />
        <Rows title="Bases (one per obligation)" rows={Object.entries(bases).map(([name, b]) => [name, myr(b?.base)])} />
        <Rows title="Schedule rows used" rows={OBLIGATIONS.slice(0, 3).map((name) => [name, schedule(name)])} />
        <Rows title="Labour (territory)" rows={[
          ["Territory", place.territory || "—"],
          ["Holiday state", place.holidayState || "—"],
          ["Transfer rule", place.rule || "—"],
          ["Overtime", overtime.status ? `${overtime.status}${overtime.expected ? ` · ${myr(overtime.expected)}` : ""}` : "—"],
          ["Minimum wage", minimum.status ? `${minimum.status}${minimum.floor ? ` (floor ${myr(minimum.floor)})` : ""}` : "—"],
        ]} />
      </div>
      {(s.exceptions || []).length > 0 && (
        <ul className="mt-3 space-y-1" data-testid="my-payslip-exceptions">
          {s.exceptions.map((e, i) => (
            <li key={`${e.code}-${i}`} className="text-[12px] text-error"><span className="font-mono">{e.code}</span> — {e.detail}</li>
          ))}
        </ul>
      )}
      <button type="button" onClick={() => setTraceOpen((v) => !v)}
        className="mt-3 inline-flex items-center gap-1 text-[12px] font-semibold text-primary">
        <ChevronDown size={13} className={traceOpen ? "rotate-180" : ""} /> {traceOpen ? "Hide" : "Show"} trace and hashes
      </button>
      {traceOpen && (
        <pre className="mt-2 max-h-80 overflow-auto rounded-lg bg-surface-muted p-3 text-[11px] text-foreground-secondary">
          {JSON.stringify({ hashes: s.hashes, legalPeriods: trace.legalPeriods, rounding: trace.rounding,
            contentUsed: trace.contentUsed }, null, 2)}
        </pre>
      )}
    </div>
  );
}
