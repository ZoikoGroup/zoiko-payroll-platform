// UK has no country-specific UI extensions today. Scotland's own income
// tax bands (seeded earlier this session, real 2024-25 data) already
// render correctly through the generic Tax Slabs tab, engine-side via
// ctx.state_slabs in engine/countries/uk.py — no PT-style fixed-amount
// shape exists for the UK, so no override is needed. England/Wales/
// Northern Ireland have no separate real data and are correctly absent
// from the state picker (it's driven by real backend data, not a
// hardcoded list of the UK's nations).
export const ukComplianceConfig = {
  extraTabs: [],
  slabsTabOverride: undefined,
};
