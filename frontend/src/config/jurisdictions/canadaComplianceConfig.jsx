// Canada has no country-specific UI extensions today. Provincial tax was
// explicitly deferred earlier this session (federal brackets only, by
// design — see engine/countries/canada.py) — there is no real
// province-level data to show, so nothing is invented here.
export const canadaComplianceConfig = {
  extraTabs: [],
  slabsTabOverride: undefined,
};
