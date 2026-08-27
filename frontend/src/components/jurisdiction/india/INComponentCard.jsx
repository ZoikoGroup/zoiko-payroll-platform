import { useState } from "react";
import { ChevronDown, Pencil, Trash2, ArrowRight } from "lucide-react";
import { classifyIndiaContributionRate } from "./inComponentConfig";

// India-only replacement for the generic "Employee % / Employer % / Flat
// Amount / Sort Order" table row — each group renders only the field(s)
// actually relevant to that component, per classifyIndiaContributionRate.
// Only used for India (imported solely by INTaxComponentsTab.jsx); every
// other country still renders the original RatesTab.jsx table untouched.
// Direct structural port of usa/USAComponentCard.jsx.
export default function INComponentCard({ group, allRates, onEdit, onDelete }) {
  const [open, setOpen] = useState(true);
  const desc = classifyIndiaContributionRate(group.rows[0]);

  if (desc.pointer) {
    return (
      <div className="flex items-center justify-between rounded-xl border border-dashed border-border bg-surface-muted px-4 py-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-foreground">{group.label}</span>
            <span className="rounded-md bg-surface px-1.5 py-0.5 font-mono text-[11px] text-foreground-muted">{group.componentKey}</span>
          </div>
          <p className="mt-0.5 flex items-center gap-1 text-xs text-foreground-muted">
            Configured via the Tax Slabs tab <ArrowRight size={11} />
          </p>
        </div>
      </div>
    );
  }

  const associatedRow = desc.associatedKey ? allRates.find((r) => r.componentKey === desc.associatedKey) : null;
  const associatedDesc = associatedRow ? classifyIndiaContributionRate(associatedRow) : null;

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
                  {desc.employeeRate && desc.employerRate && (<><th className="px-4 py-2">Employee Contribution Rate %</th><th className="px-4 py-2">Employer Contribution Rate %</th></>)}
                  {desc.flatAmount && <th className="px-4 py-2">{desc.flatAmountLabel}</th>}
                  <th className="px-4 py-2">Sort Order</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody>
                {group.rows.map((r) => (
                  <tr key={r.id} className="border-b border-border-light last:border-0">
                    {desc.employeeRate && desc.employerRate && (
                      <>
                        <td className="px-4 py-2.5">{r.employeeRatePct != null ? `${r.employeeRatePct}%` : "—"}</td>
                        <td className="px-4 py-2.5">{r.employerRatePct != null ? `${r.employerRatePct}%` : "—"}</td>
                      </>
                    )}
                    {desc.flatAmount && <td className="px-4 py-2.5">{r.flatAmount ?? "—"}</td>}
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
          {associatedRow && (
            <div className="flex items-center justify-between border-t border-border-light bg-surface-muted px-4 py-2 text-xs">
              <span className="text-foreground-muted">
                {associatedDesc.flatAmountLabel} — <span className="font-semibold text-foreground">{associatedRow.flatAmount ?? "—"}</span>
              </span>
              <div className="flex items-center gap-1">
                <button onClick={() => onEdit(associatedRow)} className="rounded-md p-1 text-foreground-muted hover:bg-surface"><Pencil size={12} /></button>
                <button onClick={() => onDelete(associatedRow)} className="rounded-md p-1 text-error hover:bg-error-light"><Trash2 size={12} /></button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
