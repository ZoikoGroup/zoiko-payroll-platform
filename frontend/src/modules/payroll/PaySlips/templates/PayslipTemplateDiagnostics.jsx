import { Info } from "lucide-react";

// Why a payslip would be shown in the standard format instead of through this
// template (diagnostic from the server: preview / Sample PDF with a payslip).

const money = (v) =>
  typeof v === "number" ? v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : v;

const TITLES = {
  TIE_OUT_MISMATCH: "Totals don't match the lines",
  PAYSLIP_BLOCKED: "Payslip blocked",
  BELGIUM: "Belgian payslip",
  RENDER_ERROR: "Template error with this payslip",
  ENGINE_FAILURE: "PDF engine failed",
  NOT_ASSIGNED: "No template assigned",
};

export default function PayslipTemplateDiagnostics({ diagnostics, payslipId }) {
  if (!diagnostics) return null;
  const d = diagnostics.detail || {};
  return (
    <div className="flex items-start gap-2 px-5 py-2.5 text-[12px] border-b border-border bg-warning/10 text-foreground"
      role="status">
      <Info size={14} className="shrink-0 mt-0.5 text-warning" />
      <div className="space-y-1">
        <p>
          <strong>{TITLES[diagnostics.code] || diagnostics.code}</strong>
          {payslipId ? ` — payslip #${payslipId}` : ""}: {diagnostics.message}
        </p>
        {diagnostics.code === "TIE_OUT_MISMATCH" && (
          <table className="text-[11px]">
            <tbody>
              <tr>
                <td className="pr-3 text-foreground-muted">Earnings lines / stored gross</td>
                <td className="pr-3">{money(d.earningsLines)} / {money(d.storedGross)}</td>
                <td className={d.earningsDifference ? "text-warning font-semibold" : "text-foreground-muted"}>
                  difference {money(d.earningsDifference)}
                </td>
              </tr>
              <tr>
                <td className="pr-3 text-foreground-muted">Deduction lines / stored total deductions</td>
                <td className="pr-3">{money(d.deductionLines)} / {money(d.storedTotalDeductions)}</td>
                <td className={d.deductionsDifference ? "text-warning font-semibold" : "text-foreground-muted"}>
                  difference {money(d.deductionsDifference)}
                </td>
              </tr>
            </tbody>
          </table>
        )}
        {(d.explanation || []).map((e) => <p key={e} className="text-[11px] text-foreground-muted">{e}</p>)}
        <p className="text-[11px] text-foreground-muted">
          Downloads and e-mails of this payslip are not affected: they use the standard payslip.
        </p>
      </div>
    </div>
  );
}
