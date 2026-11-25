import { listPapReleases } from "../../../../service/superAdminService";

// Shared pieces of the Germany page on the shared pack layout.

// The wage-tax warning (same text as payroll/germany_overview.UNCERTIFIED_TARIFF_WARNING).
// The second sentence follows the PAP release registry: today it is empty.
export const DE_TARIFF_WARNING = "German wage tax is currently calculated by an internal reference tariff that is not BMF-certified.";
export const DE_NO_PAP_RELEASE = "No PAP release is configured.";
export const DE_PAP_NOT_EXECUTABLE = "A PAP release record exists, but no PAP execution engine is implemented, so it is not used.";

export function papWarningText(releases) {
  return `${DE_TARIFF_WARNING} ${Array.isArray(releases) && releases.length > 0 ? DE_PAP_NOT_EXECUTABLE : DE_NO_PAP_RELEASE}`;
}

export const loadPapWarning = () => listPapReleases().then(papWarningText);

// Old ?section= keys of the Germany page (and the /germany/registries page's
// tabs) -> the tab that now holds them.
export const GERMANY_TAB_ALIASES = {
  "compliance-pack": "versions",
  pap: "de-slabs",
  "health-funds": "de-rates",
  ceilings: "de-rates",
  pv: "de-rates",
  "minijob-midijob": "de-rates",
  "earning-taxability": "de-policy",
  "overtime-premium-categories": "de-policy",
  "overtime-grundlohn-caps": "de-policy",
  "church-tax": "de-policy",
  "employer-levies": "de-levies",
  "elstam-batches": "de-elstam",
  elster: "de-elster",
  deuv: "de-deuv",
  "payroll-summary": "de-payroll-summary",
  "source-evidence": "de-sources",
  audit: "de-registry-audit",
  "release-readiness": "de-readiness",
};

export const GERMANY_PAGE = "/super-admin/compliance/germany";

// Source files named for engineers next to values held in code.
export const ENGINE_FILES = {
  defaults: "hardcoded_defaults.py",
  tariff: "engine/jurisdictions/germany/tax.py",
  churchTax: "engine/jurisdictions/germany/pap/core.py",
};
