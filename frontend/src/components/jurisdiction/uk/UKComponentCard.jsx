import { useState } from "react";
import { ChevronDown, Pencil, Trash2, ArrowRight } from "lucide-react";
import { classifyUKContributionRate } from "./ukComponentConfig";

const PENSION_BASIS_LABELS = {
  QUALIFYING_EARNINGS: "Qualifying Earnings",
  BASIC_PAY: "Basic Pay",
  PENSIONABLE_EARNINGS: "Pensionable Earnings",
};

// UK-only display card for a grouped contribution rate — renders only the
// field(s) actually relevant to that component, per classifyUKContributionRate.
// Follows the same structure as india/INComponentCard.jsx.
export default function UKComponentCard({ group, allRates, onEdit, onDelete }) {
  const [open, setOpen] = useState(true);
  const desc = classifyUKContributionRate(group.rows[0]);

  if (desc.pointer) {
    return (
      <div className="flex items-center justify-between rounded-xl border border-dashed border-border bg-surface-muted px-4 py-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-foreground">{group.label}</span>
            <span className="rounded-md bg-surface px-1.5 py-0.5 font-mono text-[11px] text-foreground-muted">{group.componentKey}</span>
          </div>
          <p className="mt-0.5 flex items-center gap-1 text-xs text-foreground-muted">
            Configured via the {group.navigatesTo === "paye" ? "PAYE Income Tax" : "NI Bands"} tab <ArrowRight size={11} />
          </p>
        </div>
      </div>
    );
  }

  const associatedRow = desc.associatedKey ? allRates.find((r) => r.componentKey === desc.associatedKey) : null;

  // Special handling for pension_basis: show the text value as a label
  // alongside the employer-pension rate, not as a numeric row.
  const pensionBasisValue = associatedRow?.textValue || null;
  const pensionBasisLabel = pensionBasisValue ? (PENSION_BASIS_LABELS[pensionBasisValue] || pensionBasisValue) : null;

  return (
    <div className="rounded-xl border border-border bg-surface">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center justify-between px-4 py-3 text-left">
        <div className="flex items-center gap-2">
          <ChevronDown size={15} className={`text-foreground-muted transition-transform ${open ? "" : "-rotate-90"}`} />
          <span className="text-sm font-semibold text-foreground">{group.label}</span>
          <span className="rounded-md bg-surface-muted px-1.5 py-0.5 font-mono text-[11px] text-foreground-muted">{group.componentKey}</span>
        </div>
        <span className="text-xs text-foreground-disabled">{group.rows.length} row{group.rows.length === 1 ? "" : "s"}</span>
      </button>
      {open && (
        <div className="border-t border-border-light">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border-light text-left text-foreground-muted">
                  {desc.employeeRate && desc.employerRate && (
                    <>
                      <th className="px-4 py-2">Employee Rate %</th>
                      <th className="px-4 py-2">Employer Rate %</th>
                    </>
                  )}
                  {desc.employeeRate && !desc.employerRate && (
                    <th className="px-4 py-2">Employee Rate %</th>
                  )}
                  {desc.employerRate && !desc.employeeRate && (
                    <th className="px-4 py-2">Employer Rate %</th>
                  )}
                  {desc.flatAmount && <th className="px-4 py-2">{desc.flatAmountLabel || "Threshold Amount"}</th>}
                  <th className="px-4 py-2">Sort Order</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody>
                {group.rows.map((r) => (
                  <tr key={r.id} className="border-b border-border-light last:border-0">
                    {desc.employeeRate && desc.employerRate && (
                      <>
                        <td className="px-4 py-2.5 font-mono tabular-nums">{r.employeeRatePct != null ? `${r.employeeRatePct}%` : "—"}</td>
                        <td className="px-4 py-2.5 font-mono tabular-nums">{r.employerRatePct != null ? `${r.employerRatePct}%` : "—"}</td>
                      </>
                    )}
                    {desc.employeeRate && !desc.employerRate && (
                      <td className="px-4 py-2.5 font-mono tabular-nums">{r.employeeRatePct != null ? `${r.employeeRatePct}%` : "—"}</td>
                    )}
                    {desc.employerRate && !desc.employeeRate && (
                      <td className="px-4 py-2.5 font-mono tabular-nums">{r.employerRatePct != null ? `${r.employerRatePct}%` : "—"}</td>
                    )}
                    {desc.flatAmount && (
                      <td className="px-4 py-2.5 font-mono tabular-nums">
                        {r.flatAmount != null ? `£${Number(r.flatAmount).toLocaleString()}` : "—"}
                      </td>
                    )}
                    <td className="px-4 py-2.5">{r.sortOrder ?? "—"}</td>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-1">
                        <button onClick={() => onEdit(r)} className="rounded-md p-1.5 text-foreground-muted hover:bg-surface-muted"><Pencil size={13} /></button>
                        <button onClick={() => onDelete(r)} className="rounded-md p-1.5 text-error hover:bg-error-light"><Trash2 size={13} /></button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {pensionBasisLabel && (
            <div className="flex items-center justify-between border-t border-border-light bg-surface-muted px-4 py-2 text-xs">
              <span className="text-foreground-muted">
                Calculation Basis — <span className="font-semibold text-foreground">{pensionBasisLabel}</span>
              </span>
              <div className="flex items-center gap-1">
                {associatedRow && (
                  <>
                    <button onClick={() => onEdit(associatedRow)} className="rounded-md p-1 text-foreground-muted hover:bg-surface"><Pencil size={12} /></button>
                    <button onClick={() => onDelete(associatedRow)} className="rounded-md p-1 text-error hover:bg-error-light"><Trash2 size={12} /></button>
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
