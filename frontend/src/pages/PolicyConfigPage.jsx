import { useSearchParams } from "react-router-dom";
import { COUNTRY_CODE_TO_POLICY_PAGE, INPolicyPage } from "./PolicyModule";

// Thin dispatcher — the Policy module was split into one page per
// jurisdiction (frontend/src/pages/PolicyModule/), mirroring the Tax side's
// JurisdictionCompliance/*.jsx pages. This file keeps its original route
// (`/super-admin/compliance/policy/new`) and `country` query param
// untouched on purpose: every existing "+ New Policy"/"Edit"/"New Version"
// link (inside the shared JurisdictionLayout.jsx, used by all 6 Tax
// compliance pages) already navigates here with `country` in the URL —
// so routing to the right jurisdiction's page needed zero changes to
// App.jsx or JurisdictionLayout.jsx, only this file becoming a router
// into the new module instead of being the page itself.
//
// Falls back to India's page if `country` is missing/unrecognized (matches
// PolicyModule's own emptyForm default) — every real link into this route
// always carries a valid country, so this only matters for a bare/malformed
// direct URL visit.
export default function PolicyConfigPage() {
  const [searchParams] = useSearchParams();
  const country = searchParams.get("country");
  const Page = COUNTRY_CODE_TO_POLICY_PAGE[country] || INPolicyPage;
  return <Page />;
}
