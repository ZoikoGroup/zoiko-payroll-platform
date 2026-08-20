// USA has no country-specific UI extensions today. US state income tax
// (California/New York, seeded earlier this session) already renders
// correctly through the generic Tax Slabs tab — it's a percentage bracket
// like every other country's, not a new shape needing an override. There
// is no backend concept of county/city-level tax in this codebase, so
// nothing is invented here to represent one — JurisdictionLayout falls
// back to the real, backend-driven state list exactly as every country
// already does.
export const usaComplianceConfig = {
  extraTabs: [],
  slabsTabOverride: undefined,
};
