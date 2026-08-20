// Australia has no country-specific UI extensions and no state-level tax
// construct at all in this codebase today (state payroll tax has never
// been implemented, engine-side or otherwise). Deliberately empty rather
// than inventing a state list with nothing real behind it — the state
// picker will correctly show no options until real data exists.
export const australiaComplianceConfig = {
  extraTabs: [],
  slabsTabOverride: undefined,
};
