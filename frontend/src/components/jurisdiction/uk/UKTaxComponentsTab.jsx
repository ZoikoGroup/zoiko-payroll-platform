import { useMemo, useState } from "react";
import { Percent, Plus, Users2 } from "lucide-react";
import ConfirmDialog from "../../ConfirmDialog";
import { useToast } from "../../../context/ToastContext";
import { deleteCanonicalContributionRate, deleteCanonicalTaxSlab } from "../../../service/superAdminService";
import UKComponentCard from "./UKComponentCard";
import UKComponentFormModal from "./UKComponentFormModal";
import UKComponentPickerModal from "./UKComponentPickerModal";
import { classifyUKContributionRate } from "./ukComponentConfig";

const NI_CATEGORIES_ORDER = ["A", "B", "C", "D", "E", "F", "H", "I", "J", "K", "L", "M", "N", "S", "V", "Z"];

// Unified UK Tax Components tab — replaces the 4 separate tabs (NI
// Categories, Workplace Pension, Student Loans, HMRC Statutory Thresholds)
// with a single, component-driven presentation. ContributionRate rows are
// displayed as grouped cards; NI Band TaxSlab rows are displayed in a
// dedicated NI Bands section. Add/Edit goes through the UK-specific form
// modals; Delete uses the existing shared ConfirmDialog path.
export default function UKTaxComponentsTab({ pack, rates, slabs, onReload, onDeleteRate, onNavigateTab }) {
  const { addToast } = useToast() || {};
  const [showPicker, setShowPicker] = useState(false);
  const [addingRate, setAddingRate] = useState(false);
  const [editingRate, setEditingRate] = useState(null);
  const [editingSlab, setEditingSlab] = useState(null);
  const [deletingRate, setDeletingRate] = useState(null);
  const [deletingSlab, setDeletingSlab] = useState(null);

  // Filter NI_BAND rows from slabs
  const niBands = useMemo(() => (slabs || []).filter((s) => s.ruleType === "NI_BAND"), [slabs]);
  const niCategories = useMemo(() => {
    const byCat = {};
    niBands.forEach((b) => { (byCat[b.niCategory || "—"] ||= []).push(b); });
    return NI_CATEGORIES_ORDER.filter((c) => byCat[c]).map((c) => ({ category: c, bands: byCat[c].sort((a, b) => Number(a.minAmount) - Number(b.minAmount)) }));
  }, [niBands]);

  // Group ContributionRate rows by componentKey, hiding associated keys
  const rateGroups = useMemo(() => {
    const all = groupByComponentKey(rates || []);
    const presentKeys = new Set(all.map((g) => g.componentKey));
    const mergedAway = new Set();
    for (const g of all) {
      const desc = classifyUKContributionRate(g.rows[0]);
      if (desc.associatedKey && presentKeys.has(desc.associatedKey)) mergedAway.add(desc.associatedKey);
    }
    return all.filter((g) => !mergedAway.has(g.componentKey));
  }, [rates]);

  const totalComponents = rateGroups.length;
  const configuredThresholds = rateGroups.filter((g) => {
    const desc = classifyUKContributionRate(g.rows[0]);
    return desc.flatAmount;
  }).length;
  const configuredRates = rateGroups.filter((g) => {
    const desc = classifyUKContributionRate(g.rows[0]);
    return desc.employeeRate || desc.employerRate;
  }).length;

  function handleDeleteRate(row) {
    setDeletingRate(row);
  }

  function handleDeleteSlab(row) {
    setDeletingSlab(row);
  }

  return (
    <div className="space-y-5">
      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-3">
        <SummaryCard label="Total Components" value={totalComponents} />
        <SummaryCard label="Contribution Rates" value={configuredRates} />
        <SummaryCard label="Statutory Thresholds" value={configuredThresholds} />
      </div>

      {/* Header + Add button */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="flex items-center gap-1.5 text-sm font-bold text-foreground"><Percent size={15} /> Tax Components</h3>
          <p className="mt-0.5 text-xs text-foreground-muted">National Insurance, Workplace Pension, Student Loans, and statutory thresholds for this Compliance Pack.</p>
        </div>
        <button
          onClick={() => setShowPicker(true)}
          className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white hover:bg-primary-hover"
        >
          <Plus size={13} /> Add Component
        </button>
      </div>

      {/* Contribution Rate cards */}
      {rateGroups.length > 0 && (
        <div className="space-y-2">
          {rateGroups.map((group) => (
            <UKComponentCard
              key={group.componentKey} group={group} allRates={rates || []}
              onEdit={setEditingRate} onDelete={handleDeleteRate}
            />
          ))}
        </div>
      )}

      {/* NI Category Bands section */}
      <div className="rounded-xl border border-border bg-surface">
        <div className="flex items-center justify-between px-4 py-3">
          <div className="flex items-center gap-2">
            <Users2 size={15} className="text-foreground-muted" />
            <div>
              <p className="text-sm font-semibold text-foreground">NI Category Bands</p>
              <p className="text-xs text-foreground-muted">Per-category National Insurance bands — Employee % and Employer % by earnings range.</p>
            </div>
          </div>
          <button
            onClick={() => setEditingSlab({ mode: "add" })}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover"
          >
            <Plus size={13} /> Add Band
          </button>
        </div>

        {niCategories.length === 0 ? (
          <div className="border-t border-border-light px-4 py-8 text-center">
            <p className="text-xs text-foreground-disabled">No NI category bands configured yet — only a flat National Insurance % applies until bands exist.</p>
          </div>
        ) : (
          <div className="border-t border-border-light">
            {niCategories.map(({ category, bands }) => (
              <div key={category} className="border-b border-border-light last:border-0 px-4 py-3">
                <p className="mb-2 text-xs font-bold text-foreground">Category {category}</p>
                <div className="space-y-1">
                  {bands.map((band) => (
                    <div key={band.id} className="flex items-center justify-between rounded border border-border-light px-2.5 py-1.5 text-xs">
                      <span className="font-mono tabular-nums text-foreground-secondary">
                        £{Number(band.minAmount).toLocaleString()} – {band.maxAmount != null ? `£${Number(band.maxAmount).toLocaleString()}` : "and above"}
                      </span>
                      <span className="flex items-center gap-3">
                        <span className="font-mono tabular-nums text-foreground">Employee {Number(band.ratePct)}%</span>
                        <span className="font-mono tabular-nums text-foreground-muted">Employer {band.employerRatePct != null ? `${Number(band.employerRatePct)}%` : "—"}</span>
                        <button onClick={() => setEditingSlab({ mode: "edit", slab: band })} className="rounded p-1 text-foreground-disabled hover:text-primary hover:bg-surface-muted">
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>
                        </button>
                        <button onClick={() => handleDeleteSlab(band)} className="rounded p-1 text-foreground-disabled hover:text-error hover:bg-error-light">
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>
                        </button>
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Empty state when nothing is configured */}
      {rateGroups.length === 0 && niCategories.length === 0 && (
        <div className="rounded-xl border border-dashed border-border bg-surface-muted py-12 text-center">
          <p className="text-sm text-foreground-disabled">No tax components configured yet.</p>
          <p className="mt-1 text-xs text-foreground-disabled">Click "Add Component" to get started.</p>
        </div>
      )}

      {/* Picker modal */}
      {showPicker && (
        <UKComponentPickerModal
          pack={pack} rates={rates || []} slabs={slabs || []}
          onClose={() => setShowPicker(false)}
          onEditExisting={(row) => { setShowPicker(false); setEditingRate(row); }}
          onAddNew={(entry) => {
            setShowPicker(false);
            setAddingRate({ componentKey: entry.componentKey, displayName: entry.displayName });
          }}
          onCustom={() => { setShowPicker(false); setAddingRate(true); }}
          onNavigate={(target) => {
            setShowPicker(false);
            if (target === "paye") onNavigateTab?.("paye");
            if (target === "ni-bands") {/* already visible below */}
          }}
        />
      )}

      {/* Add form modal (ContributionRate) */}
      {addingRate && (
        <UKComponentFormModal
          mode="add"
          initial={addingRate === true ? undefined : addingRate}
          pack={pack} rates={rates || []}
          onClose={() => setAddingRate(false)}
          onSaved={() => { setAddingRate(false); onReload(); }}
          addToast={addToast}
        />
      )}

      {/* Edit form modal (ContributionRate) */}
      {editingRate && (
        <UKComponentFormModal
          mode="edit"
          rate={editingRate}
          pack={pack} rates={rates || []}
          onClose={() => setEditingRate(null)}
          onSaved={() => { setEditingRate(null); onReload(); }}
          addToast={addToast}
        />
      )}

      {/* NI Band form modal (TaxSlab) */}
      {editingSlab && (
        <UKComponentFormModal
          mode={editingSlab.mode}
          slab={editingSlab.slab || null}
          pack={pack}
          onClose={() => setEditingSlab(null)}
          onSaved={() => { setEditingSlab(null); onReload(); }}
          addToast={addToast}
        />
      )}

      {/* Delete confirmation (rate) */}
      {deletingRate && (
        <ConfirmDialog
          title="Delete Component"
          message={`Delete "${deletingRate.label}"? This cannot be undone.`}
          onConfirm={async () => {
            try {
              await deleteCanonicalContributionRate(deletingRate.id);
              addToast?.("Deleted.", "success");
            } catch (err) {
              addToast?.(err.message || "Failed to delete.", "error");
            }
            setDeletingRate(null);
            onReload();
          }}
          onClose={() => setDeletingRate(null)}
        />
      )}

      {/* Delete confirmation (slab / NI band) */}
      {deletingSlab && (
        <ConfirmDialog
          title="Delete NI Band"
          message={`Delete "${deletingSlab.rateLabel || `NI Category ${deletingSlab.niCategory} band`}"? This cannot be undone.`}
          onConfirm={async () => {
            try {
              await deleteCanonicalTaxSlab(deletingSlab.id);
              addToast?.("Deleted.", "success");
            } catch (err) {
              addToast?.(err.message || "Failed to delete.", "error");
            }
            setDeletingSlab(null);
            onReload();
          }}
          onClose={() => setDeletingSlab(null)}
        />
      )}
    </div>
  );
}

function groupByComponentKey(rates) {
  const map = new Map();
  for (const r of rates) {
    const key = r.componentKey || "—";
    if (!map.has(key)) map.set(key, { componentKey: key, label: r.label || key, rows: [] });
    map.get(key).rows.push(r);
  }
  return Array.from(map.values()).sort((a, b) => a.label.localeCompare(b.label));
}

function SummaryCard({ label, value }) {
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2">
      <p className="text-[11px] font-bold uppercase tracking-wider text-foreground-muted">{label}</p>
      <p className="mt-0.5 text-lg font-extrabold text-foreground">{value}</p>
    </div>
  );
}
