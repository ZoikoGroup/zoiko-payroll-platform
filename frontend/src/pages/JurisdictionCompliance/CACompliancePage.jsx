import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Landmark, Coins, MapPin, Compass } from "lucide-react";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";
import SuiEmployerRatesPanel from "../../components/jurisdiction/SuiEmployerRatesPanel";
import CARateGroupTab from "../../components/jurisdiction/canada/CARateGroupTab";
import { CPP_EI_KEYS, FEDERAL_PARAM_KEYS, QUEBEC_KEYS, buildTerritorialKeys } from "../../components/jurisdiction/canada/caComponentConfig";

// Canada — everything country-specific for this jurisdiction lives in
// this page file, same pattern as INCompliancePage.jsx/UKCompliancePage.jsx
// (extraTabs/additionalStateOptions defined right here; only the reusable
// sub-components — CARateGroupTab/CARateRow — and the key metadata live
// under components/jurisdiction/canada/, mirroring india/*).
//
// Every extraTab below uses ComplianceConfigModal WITHOUT a configType
// (via CARateGroupTab), which resolves to GenericFallbackForm —
// deliberately NOT CONFIG_TYPES.CONTRIBUTION_RATE, which hardcodes
// componentKey to "employer-pension" (it's genuinely UK Workplace-
// Pension-specific despite the generic-sounding name; using it here
// would silently save every CA row under the wrong key).
// Federal/provincial/Quebec/territorial income TAX BRACKETS are
// intentionally left on the shared "Tax Slabs" tab (no slabsTabOverride)
// — unlike UK's Scotland, Canada's provincial/Quebec brackets are the
// exact same min/max/rate shape as the federal ones, so a dedicated
// bracket form would add complexity without changing anything a user
// actually fills in.

const extraTabs = [
  {
    key: "cpp-ei", label: "CPP & EI", icon: Landmark, after: "rates",
    isVisible: (pack) => !pack.jurisdictionState,
    render: (p) => (
      <CARateGroupTab
        {...p}
        title="CPP & EI"
        description="Canada Pension Plan (first + second tier) and Employment Insurance — federal, applies outside Quebec's own QPP/QPIP."
        keys={CPP_EI_KEYS}
      />
    ),
  },
  {
    key: "federal-params", label: "Federal Tax Parameters", icon: Coins, after: "cpp-ei",
    isVisible: (pack) => !pack.jurisdictionState,
    render: (p) => (
      <CARateGroupTab
        {...p}
        title="Federal Tax Parameters"
        description="Basic Personal Amount (income-tapered), Canada Employment Amount credit, and the lowest federal rate used to convert it."
        keys={FEDERAL_PARAM_KEYS}
      />
    ),
  },
  {
    key: "quebec", label: "Quebec (QPP/QPIP)", icon: MapPin, after: "federal-params",
    isVisible: (pack) => pack.jurisdictionState === "QC",
    render: (p) => (
      <CARateGroupTab
        {...p}
        title="Quebec — QPP, QPIP & Federal Abatement"
        description="Quebec's split-authority module: QPP replaces CPP, QPIP replaces EI, and the federal abatement reduces (not replaces) CRA federal tax. Quebec's own income tax brackets are on the Tax Slabs tab."
        keys={QUEBEC_KEYS}
      />
    ),
  },
  {
    key: "territorial-tax", label: "Territorial Payroll Tax", icon: Compass, after: "quebec",
    isVisible: (pack) => pack.jurisdictionState === "NT" || pack.jurisdictionState === "NU",
    render: (p) => {
      const territoryName = p.pack.jurisdictionState === "NT" ? "Northwest Territories" : "Nunavut";
      return (
        <CARateGroupTab
          {...p}
          title={`${territoryName} Payroll Tax`}
          description="Employee-paid territorial payroll tax — an employee deduction, never an employer expense."
          keys={buildTerritorialKeys(p.pack.jurisdictionState)}
        />
      );
    },
  },
];

// Canada's 13 provinces/territories are offered as selectable in the
// state dropdown (and in NewPackModal's State field, once a real pack is
// created for one) even before any real pack exists, exactly like UK
// offers England/Wales/Northern Ireland — never fabricates pack DATA,
// only the option to create one.
const additionalStateOptions = ["AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"];

// Workers' compensation (WCB/WSIB/CNESST) is org+jurisdiction-scoped
// EmployerTaxProfile data, not attached to any single JurisdictionPack
// version — same reasoning USACompliancePage.jsx already documents for
// its own "sui" section. Canada doesn't have USA's multi-section
// workspace, so a lightweight view toggle above JurisdictionLayout is
// this page's equivalent of that section switch, rather than forcing
// this org-scoped panel into JurisdictionLayout's per-pack tabs (which
// it doesn't need a selected pack for at all).
const VIEWS = [
  { key: "tax", label: "Tax Configuration" },
  { key: "wcb", label: "Workers' Compensation" },
];

export default function CACompliancePage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  const [view, setView] = useState("tax");

  return (
    <div>
      <div className="mb-5 flex gap-1 rounded-lg border border-border bg-surface-muted p-1 w-fit">
        {VIEWS.map((v) => (
          <button
            key={v.key} onClick={() => setView(v.key)}
            className={`rounded-md px-3 py-1.5 text-xs font-semibold ${view === v.key ? "bg-surface text-primary shadow-sm" : "text-foreground-muted hover:text-foreground"}`}
          >
            {v.label}
          </button>
        ))}
      </div>
      {view === "tax" ? (
        <JurisdictionLayout
          country="CA" countryName="Canada"
          initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
          onStateChange={(state) =>
            // Push (not replace) — see INCompliancePage.jsx's matching comment.
            navigate(state ? `/super-admin/compliance/canada/${encodeURIComponent(state)}` : "/super-admin/compliance/canada")
          }
          extraTabs={extraTabs}
          additionalStateOptions={additionalStateOptions}
        />
      ) : (
        <SuiEmployerRatesPanel country="CA" />
      )}
    </div>
  );
}
