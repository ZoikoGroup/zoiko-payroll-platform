import { ChevronDown, ListTree } from "lucide-react";
import { useState } from "react";

// Japan payslip breakdown (ZP-JP-ENG-001). Reads the frozen jp_result exactly
// as the engine wrote it (engine/countries/japan.py): separate WHT / SI / EI
// bases, every employee and employer share, resident tax from its notice, the
// bonus section and the labour trace. Nothing is recomputed here.

const yen = (value) => {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  return new Intl.NumberFormat("ja-JP", { style: "currency", currency: "JPY", maximumFractionDigits: 0 }).format(n);
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

const pair = (employee, employer) => `${yen(employee)} / ${yen(employer)}`;

export default function JPPayslipBreakdown({ snapshot, employeeName }) {
  const [traceOpen, setTraceOpen] = useState(false);
  if (!snapshot) return null;
  const s = snapshot;
  const trace = s.trace || {};
  const bases = trace.bases || {};
  const bonus = s.jp_bonus || null;
  const labour = trace.labour || null;
  const notice = s.jp_resident_tax_notice || {};

  return (
    <div className="mt-3 rounded-xl border border-border bg-surface p-4" data-testid="jp-payslip-breakdown">
      <div className="mb-3 flex items-center gap-2">
        <ListTree size={14} className="text-primary" />
        <p className="text-[13px] font-semibold text-foreground">
          Japan calculation{employeeName ? ` — ${employeeName}` : ""} · {s.jp_payment_kind === "BONUS" ? "Bonus payment" : "Salary payment"}
        </p>
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Rows title="Separate bases" rows={[
          ["Withholding base (before SI)", yen(bases.WHT?.base)],
          ["Social-insurance base", yen(bases.SI?.base)],
          ["Employment-insurance base", yen(bases.EI?.base ?? s.jp_ei_base)],
          ["Health SMR", yen(s.jp_smr_health)],
          ["Pension SMR", yen(s.jp_smr_pension)],
        ]} />
        <Rows title="Withholding income tax" tone="text-error" rows={[
          ["Column / dependants", s.jp_declaration_class ? `${s.jp_declaration_class} / ${s.jp_dependants}` : null],
          ["Base after social insurance", yen(s.jp_wht_base)],
          ["Method", s.jp_wht_branch],
          ["Salary withholding", yen(s.jp_wht)],
          ["Total withholding (incl. bonus)", yen(s.jp_wht_total)],
        ]} />
        <Rows title="Social insurance (employee / employer)" tone="text-warning" rows={[
          ["Employees' pension", pair(s.jp_epi_employee, s.jp_epi_employer)],
          ["Health insurance", pair(s.jp_health_employee, s.jp_health_employer)],
          ["Care insurance", pair(s.jp_care_employee, s.jp_care_employer)],
          ["Child-support contribution", pair(s.jp_child_support_employee, s.jp_child_support_employer)],
          ["Employment insurance", pair(s.jp_ei_employee, s.jp_ei_employer)],
        ]} />
        <Rows title="Resident tax (municipal notice)" tone="text-warning" rows={[
          ["This month", yen(s.jp_resident_tax)],
          ["Municipality", notice.municipality],
          ["Notice year / version", notice.noticeYear ? `${notice.noticeYear} / v${notice.version}` : null],
        ]} />
        {bonus && (
          <Rows title="Bonus" tone="text-success" rows={[
            ["Bonus", yen(bonus.jp_bonus)],
            ["Standard bonus amount", yen(bonus.jp_bonus_sba)],
            ["Health / pension SBA counted", `${yen(bonus.jp_bonus_health_sba_base)} / ${yen(bonus.jp_bonus_pension_sba_base)}`],
            ["Bonus social insurance (employee)", yen(bonus.jp_bonus_si_employee_total)],
            ["Bonus employment insurance (employee)", yen(bonus.jp_bonus_ei_employee)],
            ["Bonus withholding", `${yen(bonus.jp_bonus_wht)} (${bonus.jp_bonus_wht_rate_pct}% of ${yen(bonus.jp_bonus_wht_base)})`],
            ["JPS bonus report due", bonus.jp_bonus_report_due],
          ]} />
        )}
        {labour && (
          <Rows title="Working time (approved attendance)" tone="text-info" rows={[
            ["Overtime outside the schedule", `${labour.hours?.statutoryOvertimeMinutes ?? 0} min`],
            ["Overtime above 60 h", `${labour.hours?.over60Minutes ?? 0} min`],
            ["Statutory day off", `${labour.hours?.statutoryHolidayMinutes ?? 0} min`],
            ["Night", `${labour.hours?.nightMinutes ?? 0} min`],
            ["Overtime paid / statutory minimum", `${yen(labour.premiumPaid)} / ${yen(labour.premiumFloor)}`],
            ["Minimum wage (hourly) / pay (hourly)", `${yen(labour.minimumWage)} / ${yen(labour.minimumWageHourly)}`],
          ]} />
        )}
        <Rows title="Totals" tone="text-foreground" rows={[
          ["Employee statutory deductions", yen(s.jp_employee_total)],
          ["Employer contributions", yen(s.jp_employer_total)],
        ]} />
      </div>
      <button type="button" onClick={() => setTraceOpen((o) => !o)}
        className="mt-3 inline-flex items-center gap-1 text-[12px] font-semibold text-primary">
        <ChevronDown size={13} className={traceOpen ? "rotate-180" : ""} /> Calculation trace
      </button>
      {traceOpen && (
        <pre className="mt-2 max-h-80 overflow-auto rounded-lg bg-surface-muted p-3 text-[11px] text-foreground-secondary">
          {JSON.stringify(trace, null, 2)}
        </pre>
      )}
    </div>
  );
}
