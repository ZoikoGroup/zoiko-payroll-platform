import { useMemo, useState } from "react";
import { Percent, Plus } from "lucide-react";
import INComponentCard from "./INComponentCard";
import INComponentFormModal from "./INComponentFormModal";
import INComponentPickerModal from "./INComponentPickerModal";
import { classifyIndiaContributionRate } from "./inComponentConfig";

// Wired into indiaComplianceConfig's extraTabs (INCompliancePage.jsx),
// replacing the plain Contribution Rates table (hidden via
// JurisdictionLayout's `hiddenTabs`) with a grouped, component-driven,
// India-specific presentation of the EXACT SAME data — `rates` is what
// JurisdictionLayout's extraTabs.render() already passes down, zero new
// fetching. Direct structural port of usa/USTaxComponentsTab.jsx.
//
// `paramKeys` (INCompliancePage.jsx's exported PARAM_KEYS) excludes every
// row already owned by the Tax Parameters tab (Standard Deduction, 87A
// Rebate, Surcharge, Retirement & Exemption Limits) from this tab's card
// list — those fields are edited there, not duplicated here.
//
// This is also the orchestrator for Contribution Rate Add/Edit: it
// deliberately does NOT call the onAddRate/onEditRate callbacks handed
// down by JurisdictionLayout (those open the generic, every-country-shared
// RateFormModal) — instead it owns its own modal state and renders the
// India-only, component-driven INComponentFormModal, then calls the
// existing `onReload` prop to refresh rates in JurisdictionLayout after a
// save. JurisdictionLayout.jsx and RateFormModal.jsx needed ZERO changes.
//
// Delete stays on the existing shared path (onDeleteRate ->
// JurisdictionLayout's own ConfirmDialog + deleteCanonicalContributionRate)
// since deletion needs no field-type-awareness.
export default function INTaxComponentsTab({ pack, rates, onReload, onDeleteRate, onNavigateTab, paramKeys }) {
  const [showPicker, setShowPicker] = useState(false);
  const [addingRate, setAddingRate] = useState(false); // false | true (custom) | {componentKey,displayName,uiType} (known component)
  const [editingRate, setEditingRate] = useState(null);

  const rateGroups = useMemo(() => {
    const relevant = (rates || []).filter((r) => !paramKeys?.has(r.componentKey));
    const all = groupByComponentKey(relevant);
    const presentKeys = new Set(all.map((g) => g.componentKey));
    const mergedAway = new Set();
    for (const g of all) {
      const desc = classifyIndiaContributionRate(g.rows[0]);
      if (desc.associatedKey && presentKeys.has(desc.associatedKey)) mergedAway.add(desc.associatedKey);
    }
    return all.filter((g) => !mergedAway.has(g.componentKey));
  }, [rates, paramKeys]);

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="flex items-center gap-1.5 text-sm font-bold text-foreground"><Percent size={15} /> Contribution Components</h3>
          <p className="mt-0.5 text-xs text-foreground-muted">Provident Fund, ESI, Professional Tax, and every other scalar rate configured for this pack.</p>
        </div>
        <button
          onClick={() => setShowPicker(true)}
          className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white hover:bg-primary-hover"
        >
          <Plus size={13} /> Add Component
        </button>
      </div>

      {rateGroups.length === 0 ? (
        <EmptyState text="No contribution components configured yet." />
      ) : (
        <div className="space-y-2">
          {rateGroups.map((group) => (
            <INComponentCard
              key={group.componentKey} group={group} allRates={rates || []}
              onEdit={setEditingRate} onDelete={onDeleteRate}
            />
          ))}
        </div>
      )}

      {showPicker && (
        <INComponentPickerModal
          pack={pack} rates={rates || []}
          onClose={() => setShowPicker(false)}
          onEditExisting={(row) => { setShowPicker(false); setEditingRate(row); }}
          onAddNew={(entry) => {
            setShowPicker(false);
            const { uiType } = classifyIndiaContributionRate({ componentKey: entry.componentKey });
            setAddingRate({ componentKey: entry.componentKey, displayName: entry.displayName, uiType });
          }}
          onCustom={() => { setShowPicker(false); setAddingRate(true); }}
          onNavigate={(tabKey) => { setShowPicker(false); onNavigateTab?.(tabKey); }}
        />
      )}
      {addingRate && (
        <INComponentFormModal
          pack={pack} initial={addingRate === true ? undefined : addingRate}
          onClose={() => setAddingRate(false)}
          onSaved={() => { setAddingRate(false); onReload(); }}
        />
      )}
      {editingRate && (
        <INComponentFormModal
          pack={pack} rate={editingRate} onClose={() => setEditingRate(null)}
          onSaved={() => { setEditingRate(null); onReload(); }}
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

function EmptyState({ text }) {
  return (
    <div className="rounded-xl border border-dashed border-border bg-surface-muted py-8 text-center text-xs text-foreground-disabled">
      {text}
    </div>
  );
}
