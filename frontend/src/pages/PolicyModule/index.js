// Single source of truth for the Policy module's per-jurisdiction pages —
// mirrors frontend/src/pages/JurisdictionCompliance/index.js exactly.
// Used by PolicyConfigPage.jsx (the thin dispatcher every existing "New
// Policy"/"Edit Policy"/"New Version" link still navigates to, unchanged)
// to pick the right jurisdiction's page by country code.
import INPolicyPage from "./INPolicyPage";
import USPolicyPage from "./USPolicyPage";
import UKPolicyPage from "./UKPolicyPage";
import AUPolicyPage from "./AUPolicyPage";
import CAPolicyPage from "./CAPolicyPage";
import DEPolicyPage from "./DEPolicyPage";

export { INPolicyPage, USPolicyPage, UKPolicyPage, AUPolicyPage, CAPolicyPage, DEPolicyPage };

export const COUNTRY_CODE_TO_POLICY_PAGE = {
  IN: INPolicyPage,
  US: USPolicyPage,
  UK: UKPolicyPage,
  AU: AUPolicyPage,
  CA: CAPolicyPage,
  DE: DEPolicyPage,
};
