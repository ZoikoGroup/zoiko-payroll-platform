export { default as INStatutoryPage } from "./INStatutoryPage";
export { default as USAStatutoryPage } from "./USAStatutoryPage";
export { default as UKStatutoryPage } from "./UKStatutoryPage";
export { default as AUStatutoryPage } from "./AUStatutoryPage";
export { default as CAStatutoryPage } from "./CAStatutoryPage";
export { default as DEStatutoryPage } from "./DEStatutoryPage";
export { default as BBStatutoryPage } from "./BBStatutoryPage";
export { default as KYStatutoryPage } from "./KYStatutoryPage";
export { default as DOStatutoryPage } from "./DOStatutoryPage";
export { default as GYStatutoryPage } from "./GYStatutoryPage";
export { default as JMStatutoryPage } from "./JMStatutoryPage";
export { default as BSStatutoryPage } from "./BSStatutoryPage";
export { default as TTStatutoryPage } from "./TTStatutoryPage";
export { default as PRStatutoryPage } from "./PRStatutoryPage";
export { default as IEStatutoryPage } from "./IEStatutoryPage";

// Same six countries, same route slugs as Compliance — reused directly
// rather than re-declared here, so the two feature areas can never drift
// apart on naming.
// Same countries, same route slugs as Compliance, reused directly rather
// than re-declared here, so the two feature areas can never drift apart on
// naming. One deliberate exception: France (FR). Statutory Rates (canonical
// TaxSlab/ContributionRate quick-edit via StatutoryRatesLayout.jsx) does
// not exist for France yet -- France's mandatory contributions are the
// engine's content-as-data rate_map, resolved from the France authority
// artifacts (DGFiP PAS rates, URSSAF establishment rate packs) inside
// France's own Compliance workspace, so StatutoryRates must NOT render a
// France card pointing at a route that doesn't exist. Filtering keeps every
// shared name identical and leaves only France out.
import { COUNTRY_CODE_TO_ROUTE as COMPLIANCE_COUNTRY_CODE_TO_ROUTE } from "../JurisdictionCompliance";

export const COUNTRY_CODE_TO_ROUTE = Object.fromEntries(
  Object.entries(COMPLIANCE_COUNTRY_CODE_TO_ROUTE).filter(([code]) => code !== "FR"),
);
