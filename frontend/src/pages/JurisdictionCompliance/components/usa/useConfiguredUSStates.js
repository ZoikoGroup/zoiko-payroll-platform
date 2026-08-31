import { useEffect, useRef, useState } from "react";
import { getCanonicalContributionRates, getCanonicalTaxSlabs, getCompliancePolicies } from "../../../../service/superAdminService";

// Shared by USOverviewDashboard and USTaxPackWorkspace so switching between
// "Overview" and "State / District" doesn't re-issue the same country-wide
// query twice (section 14's "avoid duplicate requests"). Module-level cache
// (not React Query — this project has no caching library, see plan) with a
// simple in-flight guard; `refresh()` is exposed for after a rate/slab
// mutation so a newly-configured state shows up without a full page reload.
// Also exposes the total rate/slab counts from this SAME fetch, so
// USOverviewDashboard's summary cards don't need a second duplicate call.
let cache = null; // { states: string[], rateCount: number, slabCount: number } | null
let inFlight = null;

async function fetchConfiguredStates() {
  if (cache) return cache;
  if (inFlight) return inFlight;
  inFlight = (async () => {
    const [rates, slabs, packs] = await Promise.all([
      getCanonicalContributionRates({ country: "US" }),
      getCanonicalTaxSlabs({ country: "US" }),
      // A state can have a real JurisdictionPack with zero rates/slabs yet
      // (a Super Admin just created it and hasn't added its first rate) —
      // deriving "configured" purely from rate/slab rows made that pack
      // permanently unreachable from this sidebar: it never has data, so
      // it never appears, so there's never a way to select it to ADD that
      // data. Unioning in every pack's own jurisdictionState fixes that —
      // a freshly created empty pack shows up immediately.
      getCompliancePolicies({ country: "US", packType: "tax" }),
    ]);
    const states = Array.from(
      new Set(
        [...(rates || []), ...(slabs || []), ...(packs || [])]
          .map((r) => r.jurisdictionState)
          .filter(Boolean)
      )
    ).sort();
    cache = { states, rateCount: (rates || []).length, slabCount: (slabs || []).length };
    inFlight = null;
    return cache;
  })();
  return inFlight;
}

export function invalidateConfiguredUSStates() {
  cache = null;
}

export default function useConfiguredUSStates() {
  const [data, setData] = useState(cache);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    if (!cache) {
      fetchConfiguredStates().then((result) => { if (mounted.current) setData(result); });
    }
    return () => { mounted.current = false; };
  }, []);

  const refresh = () => {
    invalidateConfiguredUSStates();
    fetchConfiguredStates().then((result) => { if (mounted.current) setData(result); });
  };

  return {
    states: data?.states || [],
    rateCount: data?.rateCount || 0,
    slabCount: data?.slabCount || 0,
    loading: data === null,
    refresh,
  };
}
