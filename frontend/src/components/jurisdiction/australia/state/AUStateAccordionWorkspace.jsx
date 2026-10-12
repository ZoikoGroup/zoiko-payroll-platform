import { useState, useEffect, useCallback } from "react";
import { Plus } from "lucide-react";
import { getCompliancePolicies, getCanonicalContributionRates, getCanonicalTaxSlabs } from "../../../../service/superAdminService";
import NewPackModal from "../../NewPackModal";
import AUStateAccordionRow from "./AUStateAccordionRow";
import { AU_STATE_CODES, AU_STATE_NAMES } from "./auStateCodes";

// Australia's "State Payroll Tax" surface (§14-18/§20) — the 8-state
// accordion, cloned from USStateAccordionWorkspace.jsx's own list+expand
// pattern. Simpler than USA's version in one respect: Australia has a
// FIXED, constitutionally-bounded set of 8 states/territories (unlike
// USA's 50+, which are only discoverable by which ones already have a
// configured pack) — so this always lists all 8 up front rather than
// running a separate "which states are configured" discovery query, and
// has no bulk-CSV-import modal (nothing in ZP-TAX-AU-2026-27-001 asks
// for one; WA/QLD/VIC/NT/SA are a handful of named parameters each, not
// a 50-bracket table worth importing in bulk).
export default function AUStateAccordionWorkspace({ initialSelectedState = "" }) {
  const [expanded, setExpanded] = useState(initialSelectedState || null);
  const [byState, setByState] = useState({}); // { [stateCode]: { packs, pack, rates, slabs } }
  const [loading, setLoading] = useState(true);
  const [hasLoadedOnce, setHasLoadedOnce] = useState(false);
  const [showNewPackFor, setShowNewPackFor] = useState(null); // stateCode or null

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const entries = await Promise.all(
        AU_STATE_CODES.map(async (stateCode) => {
          const packs = await getCompliancePolicies({ country: "AU", state: stateCode, packType: "tax" }).catch(() => []);
          const pack = packs.find((p) => p.status === "Active") || packs[0] || null;
          if (!pack) return [stateCode, { packs, pack: null, rates: [], slabs: [] }];
          const [rates, slabs] = await Promise.all([
            getCanonicalContributionRates({ jurisdictionPackId: pack.id }).catch(() => []),
            getCanonicalTaxSlabs({ jurisdictionPackId: pack.id }).catch(() => []),
          ]);
          return [stateCode, { packs, pack, rates, slabs }];
        })
      );
      setByState(Object.fromEntries(entries));
    } finally {
      setLoading(false);
      setHasLoadedOnce(true);
    }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  function toggle(stateCode) {
    setExpanded((prev) => (prev === stateCode ? null : stateCode));
  }

  return (
    <div>
      <p className="mb-4 text-xs text-foreground-muted">
        Each state/territory levies its own payroll tax as an employer liability — it never reduces an
        employee's own net pay. Expand a state to configure its threshold/rate parameters or bracket table.
      </p>

      {loading && !hasLoadedOnce ? (
        <p className="py-12 text-center text-xs text-foreground-disabled">Loading state configuration…</p>
      ) : (
        <div className="space-y-2">
          {AU_STATE_CODES.map((stateCode) => {
            const detail = byState[stateCode] || { packs: [], pack: null, rates: [], slabs: [] };
            return (
              <div key={stateCode}>
                <AUStateAccordionRow
                  stateCode={stateCode}
                  pack={detail.pack}
                  packs={detail.packs}
                  rates={detail.rates}
                  slabs={detail.slabs}
                  isExpanded={expanded === stateCode}
                  onToggle={() => toggle(stateCode)}
                  onPackUpdated={loadAll}
                  onReloadSummary={loadAll}
                />
                {expanded === stateCode && !detail.pack && (
                  <div className="mt-2 flex justify-end">
                    <button
                      onClick={() => setShowNewPackFor(stateCode)}
                      className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white hover:bg-primary-hover"
                    >
                      <Plus size={13} /> New State Pack for {AU_STATE_NAMES[stateCode] || stateCode}
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {showNewPackFor && (
        <NewPackModal
          country="AU" state={showNewPackFor} packType="tax" stateOptions={AU_STATE_CODES}
          onClose={() => setShowNewPackFor(null)}
          onCreated={() => { setShowNewPackFor(null); loadAll(); setExpanded(showNewPackFor); }}
        />
      )}
    </div>
  );
}
