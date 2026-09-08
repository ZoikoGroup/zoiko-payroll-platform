import { useState, useEffect, useCallback } from "react";
import { Search, Plus } from "lucide-react";
import { getCompliancePolicies, getCanonicalContributionRates, getCanonicalTaxSlabs } from "../../../../service/superAdminService";
import useConfiguredUSStates from "../../../../pages/JurisdictionCompliance/components/usa/useConfiguredUSStates";
import USANewPackModal from "../USANewPackModal";
import USStateAccordionRow from "./USStateAccordionRow";

// Replaces the old two-panel (state sidebar + JurisdictionLayout) State/
// District UI with one unified list — each state's row expands inline to
// show its full configuration, no second sidebar, no page navigation.
// JurisdictionLayout.jsx has no extraction boundary for its pack-detail
// portion (verified by a full read), so this is a dedicated new surface
// built from the same underlying API calls, not a reuse of that component
// per row. See valiant-pondering-gizmo.md for the full plan.
export default function USStateAccordionWorkspace({ initialSelectedState = "", onActiveScopeChange }) {
  const { states, loading: statesLoading, refresh: refreshConfiguredStates } = useConfiguredUSStates();
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState(initialSelectedState || null);
  const [byState, setByState] = useState({}); // { [state]: { packs, pack, rates, slabs } }
  const [loadingDetail, setLoadingDetail] = useState(true);
  // True once the list has rendered at least once — after that, a
  // background loadAll() (e.g. refreshing one row's summary counts after a
  // save) updates `byState` silently instead of hiding the whole list
  // behind a full-screen spinner again. Editing/saving one component must
  // only update that component's own card, never the entire page.
  const [hasLoadedOnce, setHasLoadedOnce] = useState(false);
  const [showNewPack, setShowNewPack] = useState(false);
  // A state whose pack was JUST created has no rate/slab row yet, and
  // useConfiguredUSStates() only discovers a state via a real rate/slab row
  // (its OWN packs-union query always passes no `state` filter, which the
  // backend's list_all_jurisdiction_packs treats as "country-level only" —
  // see its docstring — so that part of the union has never actually found
  // a state-scoped pack). Without this, a freshly created empty state pack
  // would be invisible until an admin added its first component. Tracked
  // purely from the `created` pack the modal already returns — no new API
  // call — and pruned once the real hook independently reports the same
  // state (its data then takes over normally).
  const [locallyKnownPacks, setLocallyKnownPacks] = useState({}); // { [state]: JurisdictionPack }

  const knownStates = Array.from(new Set([...states, ...Object.keys(locallyKnownPacks)]));

  const loadAll = useCallback(async () => {
    if (knownStates.length === 0) { setByState({}); setLoadingDetail(false); setHasLoadedOnce(true); return; }
    setLoadingDetail(true);
    try {
      const entries = await Promise.all(
        knownStates.map(async (state) => {
          const packs = await getCompliancePolicies({ country: "US", state, packType: "tax" }).catch(() => []);
          if (packs.length === 0 && locallyKnownPacks[state]) {
            // Not discoverable via the packs endpoint yet (see comment
            // above) — show the just-created pack we already have in hand
            // rather than an empty row.
            return [state, { packs: [locallyKnownPacks[state]], pack: locallyKnownPacks[state], rates: [], slabs: [] }];
          }
          const pack = packs.find((p) => p.status === "Active") || packs[0] || null;
          if (!pack) return [state, { packs, pack: null, rates: [], slabs: [] }];
          const [rates, slabs] = await Promise.all([
            getCanonicalContributionRates({ jurisdictionPackId: pack.id }).catch(() => []),
            getCanonicalTaxSlabs({ jurisdictionPackId: pack.id }).catch(() => []),
          ]);
          return [state, { packs, pack, rates, slabs }];
        })
      );
      setByState(Object.fromEntries(entries));
      // Prune any locally-known state the real hook now reports itself —
      // its data is fully live from here on.
      setLocallyKnownPacks((prev) => {
        const next = { ...prev };
        for (const s of states) delete next[s];
        return next;
      });
    } finally {
      setLoadingDetail(false);
      setHasLoadedOnce(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [knownStates.join("|")]);

  // Guarded on !statesLoading (same pattern USOverviewDashboard.jsx uses):
  // useConfiguredUSStates returns a brand-new `[]` literal on every render
  // while its own data is still loading, which would otherwise retrigger
  // this effect forever (new `states` reference -> new `loadAll` -> effect
  // fires -> setState -> re-render -> new `[]` -> ...).
  useEffect(() => { if (!statesLoading) loadAll(); }, [statesLoading, loadAll]);

  function toggle(state) {
    const next = expanded === state ? null : state;
    setExpanded(next);
    onActiveScopeChange?.(next || "");
  }

  // Used after a rate/slab edit, status change, or approval — the set of
  // configured states can't change from these, only the detail within it.
  function reloadDetail() {
    loadAll();
  }

  // Used after a pack is created or hard-deleted — either can add/remove a
  // state from the configured list, so the states list itself is refetched
  // first (loadAll re-runs automatically via the effect above once `states`
  // changes; called here too for an immediate refresh of what's unchanged).
  function reloadAfterStructuralChange() {
    refreshConfiguredStates();
    loadAll();
  }

  const filteredStates = knownStates.filter((s) => s.toLowerCase().includes(search.trim().toLowerCase()));

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative min-w-[220px] max-w-xs flex-1">
          <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-foreground-disabled" />
          <input
            value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Search state…"
            className="w-full rounded-lg border border-border-strong bg-background py-2 pl-8 pr-3 text-xs text-foreground shadow-sm focus:outline-none focus:ring-2 focus:ring-focus-ring/30"
          />
        </div>
        <button
          onClick={() => setShowNewPack(true)}
          className="ml-auto flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-white hover:bg-primary-hover"
        >
          <Plus size={14} /> New State / Tax
        </button>
      </div>

      {(statesLoading || loadingDetail) && !hasLoadedOnce ? (
        <p className="py-12 text-center text-xs text-foreground-disabled">Loading configured states…</p>
      ) : filteredStates.length === 0 ? (
        <div className="flex min-h-[200px] items-center justify-center rounded-xl border border-dashed border-border bg-surface-muted text-xs text-foreground-disabled">
          {knownStates.length === 0 ? "No states configured yet — use “New State / Tax” to add one." : "No state matches your search."}
        </div>
      ) : (
        <div className="space-y-2">
          {filteredStates.map((state) => {
            const detail = byState[state] || { packs: [], pack: null, rates: [], slabs: [] };
            return (
              <USStateAccordionRow
                key={state}
                stateName={state}
                pack={detail.pack}
                packs={detail.packs}
                rates={detail.rates}
                slabs={detail.slabs}
                isExpanded={expanded === state}
                onToggle={() => toggle(state)}
                onPackUpdated={reloadDetail}
                onReloadSummary={reloadDetail}
              />
            );
          })}
        </div>
      )}

      {showNewPack && (
        <USANewPackModal
          country="US" state="" packType="tax"
          onClose={() => setShowNewPack(false)}
          onCreated={(created) => {
            setShowNewPack(false);
            if (created.jurisdictionState) {
              // Show it immediately from the create response itself — don't
              // wait on a re-fetch that (per the comment above) won't find
              // a brand-new, still-empty pack until it has a real component.
              setLocallyKnownPacks((prev) => ({ ...prev, [created.jurisdictionState]: created }));
              setByState((prev) => ({
                ...prev,
                [created.jurisdictionState]: { packs: [created], pack: created, rates: [], slabs: [] },
              }));
              setExpanded(created.jurisdictionState);
              onActiveScopeChange?.(created.jurisdictionState);
            }
            reloadAfterStructuralChange();
          }}
        />
      )}
    </div>
  );
}
