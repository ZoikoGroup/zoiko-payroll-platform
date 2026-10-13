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
export { default as SGStatutoryPage } from "./SGStatutoryPage";
export { default as HKStatutoryPage } from "./HKStatutoryPage";
export { default as SEStatutoryPage } from "./SEStatutoryPage";

// Same countries, same route slugs as Compliance, reused directly rather
// than re-declared here, so the two feature areas can never drift apart on
// naming. Deliberate exceptions: France (FR) and Switzerland (CH).
// Statutory Rates (canonical TaxSlab/ContributionRate quick-edit via
// StatutoryRatesLayout.jsx) does not exist for those two yet — France's and
// Switzerland's mandatory contributions are the engine's content-as-data
// rate_map, resolved from the authority artifacts inside each jurisdiction's
// OWN Compliance workspace (DGFiP PAS rates / URSSAF establishment rate packs
// for France; QST tariff files / scheme catalog / canton wage floors for
// Switzerland), so StatutoryRates must NOT render a France or Switzerland
// card pointing at a route that doesn't exist. Filtering keeps every shared
// name identical and leaves only those two out.
import { COUNTRY_CODE_TO_ROUTE as COMPLIANCE_COUNTRY_CODE_TO_ROUTE } from "../JurisdictionCompliance";

export const COUNTRY_CODE_TO_ROUTE = Object.fromEntries(
  Object.entries(COMPLIANCE_COUNTRY_CODE_TO_ROUTE).filter(([code]) => !["FR", "CH"].includes(code)),
);
