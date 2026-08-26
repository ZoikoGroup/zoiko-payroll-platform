import { Plus, Pencil, Trash2 } from "lucide-react";

// Generic percentage-bracket Tax Slabs table — the default for every
// country (US state income tax, UK's Scotland bands, country-level income
// tax everywhere). India's state-level Professional Tax overrides this via
// JurisdictionLayout's `slabsTabOverride` prop instead of changing this
// component — this one stays untouched for everyone else. Extracted
// verbatim from the old monolithic CompliancePage.jsx.
export default function SlabsTab({ pack, slabs, onAdd, onEdit, onDelete }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-foreground-muted">Canonical tax brackets linked to this pack.</p>
        <button onClick={onAdd} className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover">
          <Plus size={13} /> Add Bracket
        </button>
      </div>
      {slabs.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border-light px-3 py-8 text-center text-xs text-foreground-disabled">No tax slabs yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-xs">
            <thead className="bg-background text-left text-foreground-muted">
              <tr><th className="px-3 py-2">Min</th><th className="px-3 py-2">Max</th><th className="px-3 py-2">Rate %</th><th className="px-3 py-2">Label</th><th className="px-3 py-2">State</th><th className="px-3 py-2">Filing Status</th><th className="px-3 py-2 w-16"></th></tr>
            </thead>
            <tbody>
              {slabs.map((s) => (
                <tr key={s.id} className="border-t border-border-light">
                  <td className="px-3 py-2 text-foreground-secondary">{s.minAmount}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{s.maxAmount ?? "and above"}</td>
                  <td className="px-3 py-2 font-medium text-foreground">{s.ratePct}%</td>
                  <td className="px-3 py-2 text-foreground-secondary">{s.rateLabel}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{s.jurisdictionState || "—"}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{s.filingStatus || "—"}</td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-1">
                      <button onClick={() => onEdit(s)} className="rounded p-1 text-foreground-disabled hover:text-primary hover:bg-surface-muted"><Pencil size={12} /></button>
                      <button onClick={() => onDelete(s)} className="rounded p-1 text-foreground-disabled hover:text-error hover:bg-error-light"><Trash2 size={12} /></button>
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
