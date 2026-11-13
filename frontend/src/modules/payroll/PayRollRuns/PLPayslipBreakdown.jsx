import { ChevronDown, ListTree } from "lucide-react";
import { useState } from "react";

// Poland payslip breakdown (ZP-PL-ENG-001 §12 "Calculation detail"). Reads the
// frozen pl_result exactly as the engine wrote it (engine/countries/poland.py):
// gross -> obligation-specific bases -> employee contributions -> PIT -> net,
// with employer social insurance, funds and PPK shown separately, the 30x cap,
// the labour and sickness checks, exceptions and the hashes. Nothing is
// recomputed here, and no identifier or medical detail is ever in the snapshot.

const pln = (value) => {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  return new Intl.NumberFormat("pl-PL", { style: "currency", currency: "PLN" }).format(n);
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

const ZUS_LABEL = { EMERYTALNE: "Pension (emerytalne)", RENTOWE: "Disability (rentowe)", CHOROBOWE: "Sickness (chorobowe)",
  WYPADKOWE: "Accident (wypadkowe)" };
const FUND_LABEL = { FP_FS: "Labour / Solidarity Fund (FP/FS)", FGSP: "FGŚP", FEP: "FEP" };

export default function PLPayslipBreakdown({ snapshot, employeeName }) {
  const [traceOpen, setTraceOpen] = useState(false);
  if (!snapshot) return null;
  const s = snapshot;
  const trace = s.trace || {};
  const pit = trace.pit || {};
  const zus = trace.zus || {};
  const labour = trace.labour || {};
  const sickness = trace.sickness || {};
  const bases = trace.bases || {};

  return (
    <div className="mt-3 rounded-xl border border-border bg-surface p-4" data-testid="pl-payslip-breakdown">
      <div className="mb-3 flex items-center gap-2">
        <ListTree size={14} className="text-primary" />
        <p className="text-[13px] font-semibold text-foreground">Poland calculation — {employeeName}</p>
      </div>
      {(s.exceptions || []).length > 0 && (
        <ul className="mb-3 space-y-1 rounded-lg border border-warning/40 bg-warning/10 p-2" data-testid="pl-exceptions">
          {s.exceptions.map((e) => (
            <li key={e.code} className="text-[12px] text-foreground"><span className="font-mono">{e.code}</span> — {e.detail}</li>
          ))}
        </ul>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        <Rows title="Bases (one per obligation)" rows={Object.entries(bases).map(([name, b]) => [name, pln(b.base)])} />
        <div className="space-y-4">
          <Rows title="Employee deductions" tone="text-error" rows={[
            ...Object.entries(s.pl_zus_employee || {}).map(([k, v]) => [`ZUS ${ZUS_LABEL[k] || k}`, pln(v)]),
            ["Health (zdrowotne)", pln(s.pl_health)],
            ["PPK basic (employee)", pln(s.pl_ppk_employee?.BASIC)],
            ["PPK additional (employee)", Number(s.pl_ppk_employee?.ADDITIONAL) ? pln(s.pl_ppk_employee.ADDITIONAL) : null],
            ["PIT advance (zaliczka)", pln(s.pl_pit_advance)],
            ["Net pay", pln(s.pl_net)],
          ]} />
          <Rows title="Employer cost (not deducted)" tone="text-foreground-muted" rows={[
            ...Object.entries(s.pl_zus_employer || {}).map(([k, v]) => [`ZUS ${ZUS_LABEL[k] || k}`, pln(v)]),
            ...Object.entries(s.pl_funds || {}).map(([k, v]) => [FUND_LABEL[k] || k, Number(v) ? pln(v) : null]),
            ["PPK basic (employer)", pln(s.pl_ppk_employer?.BASIC)],
            ["PPK additional (employer)", Number(s.pl_ppk_employer?.ADDITIONAL) ? pln(s.pl_ppk_employer.ADDITIONAL) : null],
            ["Total employer cost", pln(s.pl_employer_total)],
          ]} />
        </div>
        <Rows title="PIT (cumulative)" rows={[
          ["Revenue", pln(pit.incomeClassification?.revenue)],
          ["Employer PPK as income", Number(pit.incomeClassification?.employerPpkAsIncome) ? pln(pit.incomeClassification.employerPpkAsIncome) : null],
          ["Employee social deducted", pln(pit.socialDeduction?.amount)],
          ["Deductible costs", pit.employeeCosts ? `${pln(pit.employeeCosts.applied)} (${pit.employeeCosts.kind})` : null],
          ["Taxable base", pln(pit.taxableBase)],
          ["Year-to-date before", pln(pit.cumulativeTaxableBefore)],
          ["At lower rate", pln(pit.rateTransition?.atLowRate)],
          ["At higher rate", Number(pit.rateTransition?.atHighRate) ? pln(pit.rateTransition.atHighRate) : null],
          ["PIT-2 reduction", pit.taxReducingAmount ? `${pln(pit.taxReducingAmount.monthlyReduction)} (${pit.taxReducingAmount.allocation})` : "none"],
          ["PIT-0 relief", pit.relief ? `${pit.relief.relief}: ${pln(pit.relief.exemptThisPeriod)} exempt` : null],
        ]} />
        <div className="space-y-4">
          <Rows title="30x annual cap (pension / disability)" rows={[
            ["Cap", pln(zus.cap)],
            ["Pension base YTD before", pln(zus.pension?.ytdBefore)],
            ["Remaining before this run", pln(zus.pension?.remainingBefore)],
            ["Excluded this run", Number(zus.pension?.excluded) ? pln(zus.pension.excluded) : null],
          ]} />
          <Rows title="Labour" rows={[
            ["Minimum-wage test", labour.minimumWage ? `${labour.minimumWage.status} (base ${pln(labour.minimumWage.base)} vs ${pln(labour.minimumWage.minimumWage)})` : null],
            ["Overtime", labour.overtime?.status && labour.overtime.status !== "NONE" ? `${labour.overtime.events.length} event(s), matched` : null],
            ["Pay timing", labour.payTiming?.status],
          ]} />
          {sickness.status === "CALCULATED" && (
            <Rows title="Sickness" rows={[
              ["Employer days", sickness.employerDays], ["ZUS benefit days", sickness.zusDays],
              ["Employer sick pay", pln(sickness.amount)],
            ]} />
          )}
        </div>
      </div>
      <button type="button" onClick={() => setTraceOpen(!traceOpen)}
        className="mt-3 inline-flex items-center gap-1 text-[11px] font-semibold text-foreground-muted hover:text-foreground">
        <ChevronDown size={12} className={traceOpen ? "rotate-180" : ""} /> Applicability, hashes and full trace
      </button>
      {traceOpen && (
        <div className="mt-2 space-y-2 text-[11px]">
          <Rows title="Applicability (PL-006)" rows={Object.entries(s.obligations || {}).map(([k, o]) => [k, `${o.applies ? "applies" : "does not apply"} · ${o.reason}`])} />
          <p className="font-mono text-foreground-muted">input {s.hashes?.input?.slice(0, 16)}… · content {s.hashes?.content?.slice(0, 16)}… · {s.hashes?.engineBuild}</p>
          <pre className="max-h-64 overflow-auto rounded bg-surface-muted p-2 text-[10px]">{JSON.stringify(trace, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}
