import { useState } from "react";
import { Search, MapPin } from "lucide-react";
import JurisdictionLayout from "../../../../components/jurisdiction/JurisdictionLayout";
import { usaComplianceConfig } from "../../../../config/jurisdictions/usaComplianceConfig";
import useConfiguredUSStates from "./useConfiguredUSStates";

// Thin wrapper around the EXISTING JurisdictionLayout — no changes to that
// file. "Federal" is just JurisdictionLayout locked to the country-level
// pack (initialState=""); "State / District" adds a search+list of only
// the REAL configured states (from useConfiguredUSStates, never a
// hardcoded 50-state list) next to it. Selecting a state re-mounts
// JurisdictionLayout via `key`+`initialState` — initialState is already a
// one-way, read-on-mount prop there, so a key-based remount is the correct
// way to reset it from outside without touching JurisdictionLayout's
// internals or introducing a new controlled-prop API surface.
export default function USTaxPackWorkspace({ mode, initialSelectedState = "", onActiveScopeChange }) {
  const [selectedState, setSelectedState] = useState(mode === "state" ? initialSelectedState : "");
  const [search, setSearch] = useState("");
  const { states, loading } = useConfiguredUSStates();

  const filteredStates = states.filter((s) => s.toLowerCase().includes(search.trim().toLowerCase()));

  function selectState(state) {
    setSelectedState(state);
    onActiveScopeChange?.(state);
  }

  if (mode === "federal") {
    return (
      <JurisdictionLayout
        key="federal"
        country="US"
        countryName="United States"
        initialState=""
        onStateChange={() => {}}
        {...usaComplianceConfig}
      />
    );
  }

  // mode === "state"
  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-[240px_1fr]">
      <div className="rounded-xl border border-border bg-surface p-3">
        <div className="relative mb-3">
          <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-foreground-disabled" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search state…"
            className="w-full rounded-lg border border-border-strong bg-background py-2 pl-8 pr-3 text-xs text-foreground shadow-sm focus:outline-none focus:ring-2 focus:ring-focus-ring/30"
          />
        </div>
        <p className="mb-1.5 px-1 text-[11px] font-bold uppercase tracking-wider text-foreground-muted">Configured States</p>
        {loading ? (
          <p className="px-1 py-4 text-xs text-foreground-disabled">Loading…</p>
        ) : filteredStates.length === 0 ? (
          <p className="px-1 py-4 text-xs text-foreground-disabled">
            {states.length === 0 ? "No states configured yet." : "No match."}
          </p>
        ) : (
          <div className="space-y-0.5">
            {filteredStates.map((state) => (
              <button
                key={state}
                onClick={() => selectState(state)}
                className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-xs font-medium transition-colors ${
                  selectedState === state ? "bg-primary/10 text-primary" : "text-foreground-secondary hover:bg-surface-muted"
                }`}
              >
                <MapPin size={12} />
                {state}
              </button>
            ))}
          </div>
        )}
      </div>

      <div>
        {selectedState ? (
          <JurisdictionLayout
            key={selectedState}
            country="US"
            countryName="United States"
            initialState={selectedState}
            onStateChange={() => {}}
            {...usaComplianceConfig}
          />
        ) : (
          <div className="flex h-full min-h-[240px] items-center justify-center rounded-xl border border-dashed border-border bg-surface-muted text-xs text-foreground-disabled">
            Select a state from the list to view or configure its tax pack.
          </div>
        )}
      </div>
    </div>
  );
}
