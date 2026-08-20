import { Plus, Pencil, Trash2 } from "lucide-react";

// Generic Contribution Rates table — used by every country's compliance
// page for country-level (or state-level, via jurisdictionState) PF/ESI/PT
// style split employer/employee rates. Extracted verbatim from the old
// monolithic CompliancePage.jsx.
export default function RatesTab({ pack, rates, onAdd, onEdit, onDelete }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-foreground-muted">Canonical contribution rates linked to this pack — org-scoped rows sync from these.</p>
        <button onClick={onAdd} className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover">
          <Plus size={13} /> Add Rate
        </button>
      </div>
      {rates.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border-light px-3 py-8 text-center text-xs text-foreground-disabled">No contribution rates yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-xs">
            <thead className="bg-background text-left text-foreground-muted">
              <tr><th className="px-3 py-2">Component</th><th className="px-3 py-2">State</th><th className="px-3 py-2">Employee %</th><th className="px-3 py-2">Employer %</th><th className="px-3 py-2">Flat Amount</th><th className="px-3 py-2 w-16"></th></tr>
            </thead>
            <tbody>
              {rates.map((r) => (
                <tr key={r.id} className="border-t border-border-light">
                  <td className="px-3 py-2"><p className="font-semibold text-foreground">{r.label}</p><p className="font-mono text-[10px] text-foreground-disabled">{r.componentKey}</p></td>
                  <td className="px-3 py-2 text-foreground-secondary">{r.jurisdictionState || "—"}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{r.employeeRatePct != null ? `${r.employeeRatePct}%` : "—"}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{r.employerRatePct != null ? `${r.employerRatePct}%` : "—"}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{r.flatAmount != null ? r.flatAmount : "—"}</td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-1">
                      <button onClick={() => onEdit(r)} className="rounded p-1 text-foreground-disabled hover:text-primary hover:bg-surface-muted"><Pencil size={12} /></button>
                      <button onClick={() => onDelete(r)} className="rounded p-1 text-foreground-disabled hover:text-error hover:bg-error-light"><Trash2 size={12} /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
