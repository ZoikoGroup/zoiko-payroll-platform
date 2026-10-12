import { useMemo, useState } from "react";
import { Plus, Landmark } from "lucide-react";
import ConfirmDialog from "../../ConfirmDialog";
import { useToast } from "../../../context/ToastContext";
import { deleteCanonicalTaxSlab } from "../../../service/superAdminService";
import TTNisClassFormModal from "./TTNisClassFormModal";

// Trinidad and Tobago's 16-earnings-class fixed NIS table
// (rule_type="TT_NIS_CLASS") — a flat weekly employee/employer dollar
// amount per class, not a percentage, so it needs its own display/CRUD
// rather than the generic Tax Slabs table (which would render the
// row's unused ratePct=0 as a misleading "0% rate" — see
// engine/countries/trinidad_and_tobago.py's own docstring). Mirrors
// australia/AUCoefficientBandsPanel.jsx's exact CRUD shape, simplified
// (no family/scale grouping — one flat, sorted class list).
export default function TTNisClassPanel({ pack, slabs, onReload }) {
  const { addToast } = useToast() || {};
  const [adding, setAdding] = useState(false);
  const [editingSlab, setEditingSlab] = useState(null);
  const [deletingSlab, setDeletingSlab] = useState(null);

  const groups = useMemo(() => {
    const classRows = (slabs || []).filter((s) => s.ruleType === "TT_NIS_CLASS");
    const byVariant = { MONTHLY: [], WEEKLY: [] };
    classRows.forEach((r) => { (byVariant[r.filingStatus || "MONTHLY"] ||= []).push(r); });
    return [
      { key: "MONTHLY", label: "Monthly-Paid Employees", rows: byVariant.MONTHLY.sort((a, b) => Number(a.minAmount) - Number(b.minAmount)) },
      { key: "WEEKLY", label: "Weekly-Paid Employees", rows: byVariant.WEEKLY.sort((a, b) => Number(a.minAmount) - Number(b.minAmount)) },
    ];
  }, [slabs]);

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="flex items-center gap-1.5 text-sm font-bold text-foreground"><Landmark size={15} /> NIS Earnings Classes</h3>
          <p className="mt-0.5 text-xs text-foreground-muted">
            NIBTT's 16-class fixed weekly contribution table (ZP-TT-ENG-001 §5) — a flat dollar amount per earnings
            band, not a percentage. Monthly- and Weekly-paid employees use different band boundaries.
          </p>
        </div>
        <button
          onClick={() => setAdding(true)}
          className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover"
        >
          <Plus size={13} /> Add Class
        </button>
      </div>

      {groups.map((group) => (
        <div key={group.key} className="rounded-xl border border-border bg-surface">
          <div className="px-4 py-3"><p className="text-sm font-semibold text-foreground">{group.label}</p></div>
          {group.rows.length === 0 ? (
            <div className="border-t border-border-light px-4 py-6 text-center">
              <p className="text-xs text-foreground-disabled">No NIS earnings classes configured yet for {group.label.toLowerCase()}.</p>
            </div>
          ) : (
            <div className="overflow-x-auto border-t border-border-light">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-foreground-muted">
                    <th className="px-4 py-2 text-left font-medium">Class</th>
                    <th className="px-4 py-2 text-left font-medium">Earnings — from</th>
                    <th className="px-4 py-2 text-left font-medium">Earnings — to</th>
                    <th className="px-4 py-2 text-left font-medium">Weekly employee</th>
                    <th className="px-4 py-2 text-left font-medium">Weekly employer</th>
                    <th className="px-4 py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {group.rows.map((row) => (
                    <tr key={row.id} className="border-t border-border-light">
                      <td className="px-4 py-2 font-semibold text-foreground">{row.rateLabel}</td>
                      <td className="px-4 py-2 font-mono tabular-nums text-foreground-secondary">${Number(row.minAmount).toLocaleString()}</td>
                      <td className="px-4 py-2 font-mono tabular-nums text-foreground-secondary">{row.maxAmount != null ? `$${Number(row.maxAmount).toLocaleString()}` : "and above"}</td>
                      <td className="px-4 py-2 font-mono tabular-nums text-foreground">${row.flatAmount != null ? Number(row.flatAmount).toFixed(2) : "0.00"}</td>
                      <td className="px-4 py-2 font-mono tabular-nums text-foreground">${row.adjustmentAmount != null ? Number(row.adjustmentAmount).toFixed(2) : "0.00"}</td>
                      <td className="px-4 py-2 text-right">
                        <button onClick={() => setEditingSlab(row)} className="mr-2 rounded p-1 text-foreground-disabled hover:text-primary hover:bg-surface-muted">
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>
                        </button>
                        <button onClick={() => setDeletingSlab(row)} className="rounded p-1 text-foreground-disabled hover:text-error hover:bg-error-light">
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ))}

      {adding && (
        <TTNisClassFormModal pack={pack} onClose={() => setAdding(false)} onSaved={() => { setAdding(false); onReload(); }} />
      )}
      {editingSlab && (
        <TTNisClassFormModal pack={pack} slab={editingSlab} onClose={() => setEditingSlab(null)} onSaved={() => { setEditingSlab(null); onReload(); }} />
      )}
      {deletingSlab && (
        <ConfirmDialog
          title="Delete NIS Earnings Class"
          message={`Delete "${deletingSlab.rateLabel}"? This cannot be undone.`}
          onConfirm={async () => {
            try { await deleteCanonicalTaxSlab(deletingSlab.id); addToast?.("Deleted.", "success"); }
            catch (err) { addToast?.(err.message || "Failed to delete.", "error"); }
            setDeletingSlab(null);
            onReload();
          }}
          onClose={() => setDeletingSlab(null)}
        />
      )}
    </div>
  );
}
