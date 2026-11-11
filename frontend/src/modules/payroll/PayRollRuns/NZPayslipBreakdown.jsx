import { ChevronDown, ListTree } from "lucide-react";
import { useState } from "react";

// New Zealand payslip breakdown (ZP-NZ-ENG-001). Reads the frozen nz_result
// exactly as the engine wrote it (engine/countries/new_zealand.py): one base
// per obligation, PAYE (regular / extra pay), the ACC earner levy and its
// annual cap, student loan, KiwiSaver employee / employer gross → ESCT → net
// with its destination, child support with the protected net, the minimum-wage
// result, leave-pay and final-pay lines and the hashes. Nothing is recomputed.

const nzd = (value) => {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  return new Intl.NumberFormat("en-NZ", { style: "currency", currency: "NZD" }).format(n);
};
const pct = (value) => (value === null || value === undefined || value === "" ? "—" : `${value}%`);

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

const KIND_LABEL = {
  REGULAR: "Regular pay", OUT_OF_CYCLE: "Out-of-cycle payment", LUMP_SUM: "Lump sum", FINAL: "Final pay",
  HOLIDAY_PAY_ADVANCE: "Holiday pay in advance", CORRECTION: "Correction (differences only)",
};

function CorrectionView({ s }) {
  const deltas = s.deltas || {};
  return (
    <div className="space-y-3">
      <p className="text-[12px] text-foreground-muted">
        Compensating correction of payslip #{s.correctionOf}: the original payslip is unchanged; these are the differences.
      </p>
      <Rows title="Differences" rows={[
        ["Gross", nzd(deltas.gross)], ["Net pay", nzd(deltas.netPay)],
        ...Object.entries(deltas.obligations || {}).map(([k, v]) => [k, nzd(v)]),
      ]} />
    </div>
  );
}

export default function NZPayslipBreakdown({ snapshot, employeeName }) {
  const [traceOpen, setTraceOpen] = useState(false);
  if (!snapshot) return null;
  const s = snapshot;
  const o = s.obligations || {};
  const ks = s.kiwisaver || {};
  const acc = s.acc || {};
  const cs = s.childSupport || {};
  const mw = s.minimumWage || {};
  const sl = s.studentLoan || {};
  const correction = s.paymentKind === "CORRECTION" && s.deltas;

  return (
    <div className="mt-3 rounded-xl border border-border bg-surface p-4" data-testid="nz-payslip-breakdown">
      <div className="mb-3 flex items-center gap-2">
        <ListTree size={14} className="text-primary" />
        <p className="text-[13px] font-semibold text-foreground">
          New Zealand calculation{employeeName ? ` — ${employeeName}` : ""} · {KIND_LABEL[s.paymentKind] || s.paymentKind}
        </p>
      </div>
      {correction ? <CorrectionView s={s} /> : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Rows title="Tax code and bases" rows={[
            ["Tax code", s.taxCode ? `${s.taxCode} (${s.incomeClass})` : null], ["Frequency", s.frequency],
            ["Payday", s.payDate],
            ...Object.entries(s.bases || {}).map(([k, v]) => [`${k} base`, nzd(v)]),
            ...Object.entries(s.extraPay?.bases || {}).map(([k, v]) => [`${k} extra-pay base`, nzd(v)]),
          ]} />
          <Rows title="PAYE and ACC earner levy" rows={[
            ["PAYE (regular)", nzd(o.payeRegular)], ["PAYE (extra pay)", Number(o.payeExtra) ? nzd(o.payeExtra) : null],
            ["Extra-pay method", s.extraPay?.method], ["ACC earner levy", nzd(o.accLevy)],
            ["ACC liable this pay", nzd(acc.liable)], ["ACC year to date → after", `${nzd(acc.ytdBefore)} → ${nzd(acc.ytdAfter)}`],
            ["ACC annual cap", nzd(acc.cap)], ["Cap crossed this pay", acc.capCrossed ? "Yes" : null],
            ["PAYE total", nzd(o.payeTotal)],
          ]} />
          <Rows title="KiwiSaver and ESCT" rows={[
            ["Status", ks.status], ["Employee", `${nzd(o.ksEmployee)} (${pct(ks.employeeRate)})`],
            ["Employer gross", `${nzd(o.ksEmployerGross)} (${pct(ks.employerRate)})`],
            ["ESCT", `${nzd(o.esct)} (${pct(ks.esctRate)})`], ["Employer net", nzd(o.ksEmployerNet)],
            ["Destination", ks.destination], ["Temporary reduction", ks.reductionApplied ? "Applied" : null],
          ]} tone="text-success" />
          <Rows title="Student loan and child support" rows={[
            ["Student loan", nzd(o.studentLoan)], ["Basis", sl.basis], ["Pay-period threshold", nzd(sl.threshold)],
            ["Extra notices", Number(o.studentLoanExtra) ? nzd(o.studentLoanExtra) : null],
            ["On extra pay", Number(o.studentLoanExtraPay) ? nzd(o.studentLoanExtraPay) : null],
            ["Child support", nzd(o.childSupport)], ["Protected net", Number(cs.protectedNet) ? nzd(cs.protectedNet) : null],
            ["Shortfall", Number(cs.shortfall) ? nzd(cs.shortfall) : null], ["Variation code", cs.variationCode],
          ]} tone="text-warning" />
          <Rows title="Minimum wage" rows={[
            ["Result", mw.status], ["Category", mw.category], ["Hours", mw.hours ? `${mw.hours} (${mw.hoursSource})` : null],
            ["Effective rate", mw.effectiveRate ? nzd(mw.effectiveRate) : null], ["Floor", mw.floor ? nzd(mw.floor) : null],
            ["Note", mw.reason],
          ]} />
          <Rows title="Leave and final pay" rows={[
            ...(s.leavePay || []).map((l, i) => [`${l.purpose === "RESTRICTED_LEAVE" ? "Restricted leave" : l.purpose} #${i + 1}`,
              `${nzd(l.amount)} (replaces ${nzd(l.displaced)})`]),
            ...(s.finalPay || []).map((l, i) => [`${l.purpose} #${i + 1}`, nzd(l.amount)]),
          ]} />
          <Rows title="Result" rows={[["Employee deductions", nzd(s.employeeTotal)], ["Net pay", nzd(s.netPay)]]} tone="text-primary" />
        </div>
      )}
      {(s.exceptions || []).length > 0 && (
        <ul className="mt-3 space-y-1" data-testid="nz-payslip-exceptions">
          {s.exceptions.map((e, i) => (
            <li key={`${e.code}-${i}`} className="text-[12px] text-error">
              <span className="font-mono">{e.code}</span>{e.shortfall ? ` — shortfall ${nzd(e.shortfall)}` : ""}{e.reason ? ` — ${e.reason}` : ""}
            </li>
          ))}
        </ul>
      )}
      <button type="button" onClick={() => setTraceOpen(!traceOpen)}
        className="mt-3 inline-flex items-center gap-1 text-[12px] font-semibold text-primary">
        <ChevronDown size={13} className={traceOpen ? "rotate-180" : ""} /> Trace and hashes
      </button>
      {traceOpen && (
        <pre className="mt-2 max-h-72 overflow-auto rounded-lg bg-surface-muted p-2 text-[10px] text-foreground-secondary">
          {JSON.stringify({ hashes: s.hashes, precedence: s.precedence, trace: s.trace }, null, 2)}
        </pre>
      )}
    </div>
  );
}
