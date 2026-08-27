import { useMemo, useState } from "react";
import { Percent, Plus } from "lucide-react";
import USAComponentCard from "./USAComponentCard";
import USAComponentFormModal from "./USAComponentFormModal";
import USAComponentPickerModal from "./USAComponentPickerModal";
import { classifyContributionRate } from "./usaComponentConfig";

// Wired into usaComplianceConfig.jsx's extraTabs, replacing the plain
// Contribution Rates table (hidden via JurisdictionLayout's `hiddenTabs`)
// with a grouped, component-driven, US-specific presentation of the EXACT
// SAME data — `rates` is what JurisdictionLayout's extraTabs.render()
// already passes down, so there is zero new fetching. Income Tax Brackets
// now live in their own adjacent tab (USIncomeTaxBracketsTab.jsx), per
// Venu's request to not mix them into this section.
//
// This is also the orchestrator for Contribution Rate Add/Edit: it
// deliberately does NOT call the onAddRate/onEditRate callbacks handed
// down by JurisdictionLayout (those just flip JurisdictionLayout's own
// showNewRate/editingRate state to open the generic, every-country-shared
// RateFormModal) — instead it owns its own modal state and renders the
// USA-only, component-type-driven USAComponentFormModal, then calls the
// existing `onReload` prop to refresh rates in JurisdictionLayout after a
// save, exactly like the shared modal already does. This means
// JurisdictionLayout.jsx and RateFormModal.jsx needed ZERO changes — they
// simply become unreachable for the USA path (nothing sets
// showNewRate/editingRate anymore here) while staying fully reachable,
// byte-for-byte unchanged, for every other country (RatesTab still calls
// those callbacks).
//
// Delete is the one exception, kept on the existing shared path
// (onDeleteRate -> JurisdictionLayout's own ConfirmDialog +
// deleteCanonicalContributionRate) since deletion needs no
// field-type-awareness — reusing it is simpler and safer.
export default function USTaxComponentsTab({ pack, rates, onReload, onDeleteRate, onNavigateTab }) {
  const [showPicker, setShowPicker] = useState(false);
  const [addingRate, setAddingRate] = useState(false); // false | true (custom) | {componentKey,label,uiType} (known component)
  const [editingRate, setEditingRate] = useState(null);

  // A component like Social Security's wage base, or Additional Medicare's
  // threshold, is shown as an inline line INSIDE its parent's card (see
  // USAComponentCard) instead of as its own separate top-level card — that
  // was pure duplication (the same value shown twice). Only excluded from
  // the top-level list when its parent's card is actually present, so a
  // wage-base/threshold row is never silently hidden if its parent is
  // missing for some pack.
  const rateGroups = useMemo(() => {
    const all = groupByComponentKey(rates || []);
    const presentKeys = new Set(all.map((g) => g.componentKey));
    const mergedAway = new Set();
    for (const g of all) {
      const desc = classifyContributionRate(g.rows[0]);
      if (desc.associatedKey && presentKeys.has(desc.associatedKey)) mergedAway.add(desc.associatedKey);
    }
    return all.filter((g) => !mergedAway.has(g.componentKey));
  }, [rates]);

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="flex items-center gap-1.5 text-sm font-bold text-foreground"><Percent size={15} /> Contribution Components</h3>
          <p className="mt-0.5 text-xs text-foreground-muted">Social Security, Medicare, FUTA, and every other scalar rate configured for this pack.</p>
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
            <USAComponentCard
              key={group.componentKey} group={group} allRates={rates || []}
              onEdit={setEditingRate} onDelete={onDeleteRate}
            />
          ))}
        </div>
      )}

      {showPicker && (
        <USAComponentPickerModal
          pack={pack} rates={rates || []}
          onClose={() => setShowPicker(false)}
          onEditExisting={(row) => { setShowPicker(false); setEditingRate(row); }}
          onAddNew={(entry) => {
            setShowPicker(false);
            // A not-yet-configured catalog entry still resolves to a real
            // uiType via the static map (classifyContributionRate checks
            // componentKey first, before any populated-field heuristics),
            // so the Add form goes straight to the right fields — no
            // technical-type screen, matching an already-configured Edit.
            const { uiType } = classifyContributionRate({ componentKey: entry.componentKey });
            setAddingRate({ componentKey: entry.componentKey, displayName: entry.displayName, uiType });
          }}
          onCustom={() => { setShowPicker(false); setAddingRate(true); }}
          onNavigateIncomeTax={() => { setShowPicker(false); onNavigateTab?.("incomeTax"); }}
        />
      )}
      {addingRate && (
        <USAComponentFormModal
          pack={pack} initial={addingRate === true ? undefined : addingRate}
          onClose={() => setAddingRate(false)}
          onSaved={() => { setAddingRate(false); onReload(); }}
        />
      )}
      {editingRate && (
        <USAComponentFormModal
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
