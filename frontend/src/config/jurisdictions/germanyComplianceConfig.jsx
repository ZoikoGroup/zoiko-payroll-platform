// Germany has no country-specific UI extensions today. Church tax
// (Kirchensteuer) is an employee-level opt-in flag consumed directly by
// the engine (engine/countries/germany.py), not a jurisdiction/pack-level
// construct — it has nothing to render here. There is no real
// Land (federal state)-level tax data in this codebase, so no state list
// is invented.
export const germanyComplianceConfig = {
  extraTabs: [],
  slabsTabOverride: undefined,
};
