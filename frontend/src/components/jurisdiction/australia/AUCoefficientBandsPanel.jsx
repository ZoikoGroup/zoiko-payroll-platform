import { useMemo, useState } from "react";
import { Plus, Calculator } from "lucide-react";
import ConfirmDialog from "../../ConfirmDialog";
import { useToast } from "../../../context/ToastContext";
import { deleteCanonicalTaxSlab } from "../../../service/superAdminService";
import AUCoefficientRowFormModal from "./AUCoefficientRowFormModal";
import { labelForAuFamily } from "./auComponentConfig";

// Shared coefficient-band table + CRUD, parametrized by ruleType/
// familyOptions so ATO Schedule 1 (PAYG) and Schedule 8 (STSL) reuse one
// implementation rather than two near-duplicates — the only real
// difference between them is which rule_type/family list applies (see
// engine/countries/australia.py's _resolve_au_coefficient_band, which
// reads exactly these two rule_type values). Self-contained: manages its
// own Add/Edit/Delete modal state and calls the canonical TaxSlab API
// directly, then `onReload` — the same "extraTab owns its own modal
// state" pattern UKTaxComponentsTab already uses, since the generic
// SlabFormModal has no field for these coefficients at all.
export default function AUCoefficientBandsPanel({
  pack, slabs, onReload, ruleType, familyOptions, familyLabel, title, description,
}) {
  const { addToast } = useToast() || {};
  const [addingFor, setAddingFor] = useState(null); // family value, or null
  const [editingSlab, setEditingSlab] = useState(null);
  const [deletingSlab, setDeletingSlab] = useState(null);

  const groups = useMemo(() => {
    const rows = (slabs || []).filter((s) => s.ruleType === ruleType);
    const byFamily = {};
    rows.forEach((r) => { (byFamily[r.filingStatus || "—"] ||= []).push(r); });
    return familyOptions
      .map((o) => ({ ...o, rows: (byFamily[o.value] || []).sort((a, b) => Number(a.minAmount) - Number(b.minAmount)) }))
      .filter((g) => g.rows.length > 0 || familyOptions.length <= 6); // always show every family (small, fixed list)
  }, [slabs, ruleType, familyOptions]);

  return (
    <div className="space-y-5">
      <div>
        <h3 className="flex items-center gap-1.5 text-sm font-bold text-foreground"><Calculator size={15} /> {title}</h3>
        <p className="mt-0.5 text-xs text-foreground-muted">{description}</p>
      </div>

      {groups.map((group) => (
        <div key={group.value} className="rounded-xl border border-border bg-surface">
          <div className="flex items-center justify-between px-4 py-3">
            <p className="text-sm font-semibold text-foreground">{group.label}</p>
            <button
              onClick={() => setAddingFor(group.value)}
              className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover"
            >
              <Plus size={13} /> Add Band
            </button>
          </div>
          {group.rows.length === 0 ? (
            <div className="border-t border-border-light px-4 py-6 text-center">
              <p className="text-xs text-foreground-disabled">No coefficient bands configured yet for {labelForAuFamily(familyOptions, group.value)}.</p>
            </div>
          ) : (
            <div className="border-t border-border-light">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-foreground-muted">
                    <th className="px-4 py-2 text-left font-medium">Weekly x — from</th>
                    <th className="px-4 py-2 text-left font-medium">Weekly x — to</th>
                    <th className="px-4 py-2 text-left font-medium">a</th>
                    <th className="px-4 py-2 text-left font-medium">b</th>
                    <th className="px-4 py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {group.rows.map((row) => (
                    <tr key={row.id} className="border-t border-border-light">
                      <td className="px-4 py-2 font-mono tabular-nums text-foreground-secondary">${Number(row.minAmount).toLocaleString()}</td>
                      <td className="px-4 py-2 font-mono tabular-nums text-foreground-secondary">{row.maxAmount != null ? `$${Number(row.maxAmount).toLocaleString()}` : "and above"}</td>
                      <td className="px-4 py-2 font-mono tabular-nums text-foreground">{Number(row.ratePct)}</td>
                      <td className="px-4 py-2 font-mono tabular-nums text-foreground">{row.flatAmount != null ? Number(row.flatAmount) : "0"}</td>
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

      {addingFor && (
        <AUCoefficientRowFormModal
          pack={pack} ruleType={ruleType} familyOptions={familyOptions} familyLabel={familyLabel}
          slab={{ filingStatus: addingFor }}
          onClose={() => setAddingFor(null)}
          onSaved={() => { setAddingFor(null); onReload(); }}
        />
      )}
      {editingSlab && (
        <AUCoefficientRowFormModal
          pack={pack} ruleType={ruleType} familyOptions={familyOptions} familyLabel={familyLabel}
          slab={editingSlab}
          onClose={() => setEditingSlab(null)}
          onSaved={() => { setEditingSlab(null); onReload(); }}
        />
      )}
      {deletingSlab && (
        <ConfirmDialog
          title="Delete Coefficient Band"
          message={`Delete this ${labelForAuFamily(familyOptions, deletingSlab.filingStatus)} band ($${Number(deletingSlab.minAmount).toLocaleString()}–${deletingSlab.maxAmount != null ? `$${Number(deletingSlab.maxAmount).toLocaleString()}` : "and above"})? This cannot be undone.`}
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
