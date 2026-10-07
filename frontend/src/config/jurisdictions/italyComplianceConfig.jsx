import { Calculator, Coins, FileCheck2, Gift, Landmark, ListChecks, MapPin, ShieldCheck, Users } from "lucide-react";
import ITParameterTab from "../../components/jurisdiction/italy/ITParameterTab";
import ITInpsMatrixTab from "../../components/jurisdiction/italy/ITInpsMatrixTab";
import ITBandsTab from "../../components/jurisdiction/italy/ITBandsTab";
import ITReadinessTab from "../../components/jurisdiction/italy/ITReadinessTab";
import {
  IT_BENEFIT_KEYS, IT_INPS_KEYS, IT_TAX_KEYS, IT_TFR_KEYS,
} from "../../components/jurisdiction/italy/itComponentConfig";
import SourceEvidencePanel from "../../components/jurisdiction/SourceEvidencePanel";

// Italy (ZP-IT-ENG-001) — tab-by-statutory-concept, the same shape as
// swedenComplianceConfig.jsx. Every tab reads and writes the SAME canonical
// ContributionRate / TaxSlab rows; the generic Rates/Slabs tabs are hidden
// because their forms would overwrite an INPS matrix row's worker class and
// clear a band's table code and amount.
//
// Italy is a COUNTRY-LEVEL pack: locality lives in the rows themselves (INPS
// classification scope, tax-domicile region/comune tables), never in a
// pack-level state.
export const italyComplianceConfig = {
  extraTabs: [
    {
      key: "inps", label: "INPS Matrix", icon: Users, after: "overview",
      isVisible: () => true,
      render: (props) => <ITInpsMatrixTab {...props} />,
    },
    {
      key: "contributions", label: "Contribution Parameters", icon: Landmark, after: "inps",
      isVisible: () => true,
      render: (props) => (
        <ITParameterTab {...props} keys={IT_INPS_KEYS}
          description="The additional 1% IVS threshold (cumulative, IT-016), the contribution ceiling (cohort evidence only, IT-017), the 2026 contributory minimum (not a wage floor, IT-004) and the FIS shares (IT-020)." />
      ),
    },
    {
      key: "irpef", label: "IRPEF & Deductions", icon: Calculator, after: "contributions",
      isVisible: () => true,
      render: (props) => (
        <div className="space-y-6">
          <ITBandsTab {...props} group="national" />
          <ITParameterTab {...props} keys={IT_TAX_KEYS}
            description="Mensilità default, the detrazione floors, wedge-recovery rules and the local-surtax instalment calendar." />
        </div>
      ),
    },
    {
      key: "localtax", label: "Local Surtax", icon: MapPin, after: "irpef",
      isVisible: () => true,
      render: (props) => <ITBandsTab {...props} group="local" />,
    },
    {
      key: "tfr", label: "TFR", icon: Coins, after: "localtax",
      isVisible: () => true,
      render: (props) => (
        <ITParameterTab {...props} keys={IT_TFR_KEYS}
          description="TFR accrual (pay / 13.5 less the 0.50% INPS offset), annual revaluation and its separate taxation, and the Fondo Tesoreria headcount threshold (§13/§14)." />
      ),
    },
    {
      key: "benefits", label: "Benefits", icon: Gift, after: "tfr",
      isVisible: () => true,
      render: (props) => (
        <div className="space-y-6">
          <ITParameterTab {...props} keys={IT_BENEFIT_KEYS}
            description="Fringe-benefit annual exemption (the child-linked limit needs the employee's own declaration, IT-032) and meal-voucher daily thresholds." />
          <ITParameterTab {...props} keys={null}
            description="Other Italy parameters in this pack." />
        </div>
      ),
    },
    {
      key: "readiness", label: "Readiness", icon: ListChecks, after: "benefits",
      isVisible: () => true,
      render: (props) => <ITReadinessTab {...props} />,
    },
    {
      key: "sources", label: "Sources", icon: FileCheck2, after: "readiness",
      isVisible: () => true,
      render: () => <SourceEvidencePanel />,
    },
    {
      key: "tests", label: "Tests", icon: ShieldCheck, after: "sources",
      isVisible: () => true,
      render: () => (
        <p className="text-xs text-foreground-muted">
          Italy&apos;s golden cases run in the backend test suite (backend/tests/fixtures/it_golden). They are not wired
          into the certification console yet, so the Readiness tab&apos;s certification gate stays open.
        </p>
      ),
    },
  ],
  hiddenTabs: ["rates", "slabs"],
  slabsTabOverride: undefined,
};

