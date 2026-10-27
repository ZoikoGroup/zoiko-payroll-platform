import { ChevronDown, ListTree } from "lucide-react";
import { useState } from "react";

// South Africa payslip breakdown (ZP-ZA-ENG-001 ZA-009; "ZA" — "SA" is Saudi
// Arabia). Reads the frozen za_calculation_snapshot exactly as
// south_africa_service.za_payslip_snapshot stores it: the separate PAYE / UIF /
// SDL bases, the PAYE trace (annualised taxable income, band, rebates, medical
// credit, directive), UIF cap and SDL. ETI is the EMPLOYER's incentive and is
// shown in its own box — never as an employee deduction (ZA-010).

const zar = (value) => {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  return new Intl.NumberFormat("en-ZA", { style: "currency", currency: "ZAR" }).format(n);
};

function Rows({ title, rows, tone }) {
  const visible = rows.filter(([, v]) => v !== null && v !== undefined && v !== "");
  if (!visible.length) return null;
  return (
    <div>
      <p className={`mb-1 text-[11px] font-bold uppercase tracking-widest ${tone}`}>{title}</p>
      <dl className="divide-y divide-border">
        {visible.map(([label, value]) => (
          <div key={label} className="flex justify-between py-1 text-[12px]">
            <dt className="text-foreground-muted">{label}</dt>
            <dd className="font-mono text-foreground">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export default function ZAPayslipBreakdown({ snapshot, employeeName }) {
  const [traceOpen, setTraceOpen] = useState(false);
  if (!snapshot) return null;
  const trace = snapshot.trace || {};
  const paye = trace.paye || {};
  const directive = trace.directive || {};
  const uif = trace.uif || {};
  const sdl = trace.sdl || {};
  const bases = trace.bases || {};
  const eti = snapshot.za_eti || {};
  const rebates = (paye.rebates || []).map((r) => `${r.rebate} ${zar(r.amount)}`).join(" + ");

  return (
    <div className="mt-3 rounded-xl border border-border bg-surface p-4" data-testid="za-payslip-breakdown">
      <div className="mb-3 flex items-center gap-2">
        <ListTree size={14} className="text-primary" />
        <p className="text-[13px] font-semibold text-foreground">South Africa calculation{employeeName ? ` — ${employeeName}` : ""}</p>
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Rows title="Independent bases (spec §4)" tone="text-info" rows={[
          ["PAYE remuneration", zar(bases.PAYE?.base ?? snapshot.za_paye_remuneration)],
          ["UIF remuneration", zar(bases.UIF?.base ?? snapshot.za_uif_base)],
          ["SDL leviable remuneration", zar(bases.SDL?.base ?? snapshot.za_sdl_base)],
        ]} />
        <Rows title="PAYE" tone="text-error" rows={[
          ["Retirement fund deduction", zar(paye.retirementDeduction)],
          ["Annual taxable income", zar(paye.annualTaxable)],
          ["Annual tax before rebates", zar(paye.annualTaxBeforeRebates)],
          ["Age at tax-year end", paye.ageAtTaxYearEnd ?? null],
          ["Rebates", rebates || null],
          ["Monthly before medical credit", zar(paye.monthlyBeforeMedicalCredit)],
          ["Medical scheme fees tax credit", zar(paye.medicalCreditApplied)],
          ["Directive applied", directive.applied ? `${directive.applied.directiveNumber || directive.applied.id} (${directive.applied.type})` : null],
          ["PAYE computed (before directive)", directive.applied ? zar(directive.computedPaye) : null],
          ["PAYE withheld", zar(snapshot.za_paye)],
        ]} />
        <Rows title="Employee deductions" tone="text-error" rows={[
          ["PAYE", zar(snapshot.za_paye)],
          ["UIF (employee)", zar(snapshot.za_uif_employee)],
          ["Retirement fund contribution", zar(snapshot.za_retirement_contribution)],
          ["Employee total", zar(snapshot.za_employee_total)],
        ]} />
        <Rows title="Employer contributions (not deducted from pay)" tone="text-category-teal" rows={[
          ["UIF (employer)", zar(snapshot.za_uif_employer)],
          ["UIF ceiling applied", uif.ceilingApplied === undefined ? null : (uif.ceilingApplied ? "Yes" : "No")],
          ["SDL", sdl.status === "EXEMPT" ? `Exempt — ${sdl.reason || ""}` : zar(snapshot.za_sdl)],
          ["Employer total", zar(snapshot.za_employer_total)],
        ]} />
      </div>
      <div className="mt-4 rounded-lg border border-dashed border-border bg-surface-muted p-3" data-testid="za-eti-box">
        <p className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Employer incentive — ETI</p>
        <p className="mt-1 text-[12px] text-foreground">
          {eti.status || "NOT_EVALUATED"}
          {eti.status === "ELIGIBLE" ? ` · ${zar(snapshot.za_eti_amount)} · month ${eti.qualifyingMonthNo} (${eti.period})` : ""}
          {eti.reasons?.length ? ` · ${eti.reasons.join("; ")}` : ""}
        </p>
        <p className="mt-1 text-[11px] text-foreground-muted">
          Offset against the employer&apos;s EMP201 PAYE remittance only — it never changes the employee&apos;s PAYE or net pay.
        </p>
      </div>
      <button type="button" onClick={() => setTraceOpen((o) => !o)}
        className="mt-3 flex items-center gap-1 text-[12px] font-semibold text-primary">
        <ChevronDown size={14} className={traceOpen ? "rotate-180" : ""} /> {traceOpen ? "Hide" : "Show"} full calculation trace
      </button>
      {traceOpen && (
        <pre className="mt-2 max-h-80 overflow-auto rounded-lg bg-surface-muted p-3 text-[11px] text-foreground">
          {JSON.stringify(trace, null, 2)}
        </pre>
      )}
    </div>
  );
}
