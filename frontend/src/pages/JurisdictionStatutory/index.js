export { default as INStatutoryPage } from "./INStatutoryPage";
export { default as USAStatutoryPage } from "./USAStatutoryPage";
export { default as UKStatutoryPage } from "./UKStatutoryPage";
export { default as AUStatutoryPage } from "./AUStatutoryPage";
export { default as CAStatutoryPage } from "./CAStatutoryPage";
export { default as DEStatutoryPage } from "./DEStatutoryPage";

// Same six countries, same route slugs as Compliance — reused directly
// rather than re-declared here, so the two feature areas can never drift
// apart on naming.
export { COUNTRY_CODE_TO_ROUTE } from "../JurisdictionCompliance";
