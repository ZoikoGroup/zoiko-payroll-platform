import { Calculator, FileCheck2, Handshake, Landmark, PiggyBank, ShieldCheck, Table2, CalendarHeart, ListChecks } from "lucide-react";
import SEParameterTab from "../../components/jurisdiction/sweden/SEParameterTab";
import SETaxTablesTab from "../../components/jurisdiction/sweden/SETaxTablesTab";
import SEAgreementsTab from "../../components/jurisdiction/sweden/SEAgreementsTab";
import SEReadinessTab from "../../components/jurisdiction/sweden/SEReadinessTab";
import {
  SE_COHORT_COMPONENT_KEYS, SE_EMPLOYER_COMPONENT_KEYS, SE_LEAVE_SICK_COMPONENT_KEYS, SE_SLP_COMPONENT_KEYS,
  SE_WITHHOLDING_COMPONENT_KEYS,
} from "../../components/jurisdiction/sweden/seComponentConfig";
import SourceEvidencePanel from "../../components/jurisdiction/SourceEvidencePanel";
import TestCertificationPanel from "../../components/jurisdiction/TestCertificationPanel";

// Sweden (ZP-SE-ENG-001) — tab-by-statutory-concept, the same shape as
// irelandComplianceConfig.jsx: each concept filters the SAME canonical
// ContributionRate / TaxSlab CRUD by key or rule type (seComponentConfig.js).
//
// Sweden is a COUNTRY-LEVEL jurisdiction for payroll: the tax table follows
// the worker's residence municipality (a worker fact, SE-002), never a
// county, so every Sweden pack has jurisdiction_state = NULL.
export const swedenComplianceConfig = {
  extraTabs: [
    {
      key: "employer", label: "Employer Contributions", icon: Landmark, after: "overview",
      isVisible: () => true,
      render: (props) => (
        <div className="space-y-6">
          <SEParameterTab {...props} keys={SE_EMPLOYER_COMPONENT_KEYS}
            description="Arbetsgivaravgifter as statutory components — their sum is the standard rate (spec §3). The engine sums the configured components; it never uses a hard-coded total." />
          <SEParameterTab {...props} keys={SE_COHORT_COMPONENT_KEYS}
            description="Birth-year cohorts (0% / pension component only) and the temporary youth reduction. The youth rows carry their own payment-date window; payments outside it use the full rate (SE-005)." />
        </div>
      ),
    },
    {
      key: "withholding", label: "Withholding", icon: Calculator, after: "employer",
      isVisible: () => true,
      render: (props) => (
        <SEParameterTab {...props} keys={SE_WITHHOLDING_COMPONENT_KEYS}
          description="SINK (non-resident special income tax, only with a valid decision) and the 30% supplementary-income rate. Each is its own withholding strategy and is never blended with the main-income tax table (spec §5)." />
      ),
    },
    {
      key: "taxtables", label: "Tax Tables", icon: Table2, after: "withholding",
      isVisible: () => true,
      render: (props) => <SETaxTablesTab {...props} />,
    },
    {
      key: "slp", label: "SLP", icon: PiggyBank, after: "taxtables",
      isVisible: () => true,
      render: (props) => (
        <SEParameterTab {...props} keys={SE_SLP_COMPONENT_KEYS}
          description="Särskild löneskatt on pension costs. Applied to the employer's pension-cost ledger, never to employee gross pay (SE-007)." />
      ),
    },
    {
      key: "leavesick", label: "Leave & Sick Pay", icon: CalendarHeart, after: "slp",
      isVisible: () => true,
      render: (props) => (
        <SEParameterTab {...props} keys={SE_LEAVE_SICK_COMPONENT_KEYS}
          description="Vacation-pay percentage rule and the sick-pay qualifying deduction. Leave days and vacation money are separate ledgers (SE-006); sick-pay episodes are recorded per employee by the organisation." />
      ),
    },
    {
      key: "agreements", label: "Collective Agreements", icon: Handshake, after: "leavesick",
      isVisible: () => true,
      render: () => <SEAgreementsTab />,
    },
    {
      key: "readiness", label: "Readiness", icon: ListChecks, after: "agreements",
      isVisible: () => true,
      render: (props) => <SEReadinessTab {...props} />,
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
        <TestCertificationPanel
          jurisdiction="SE" label="Sweden (Skatteverket)"
          fixturesPath="backend/tests/fixtures/se_golden/README.md"
        />
      ),
    },
  ],
  // The generic single-list rates/slabs tabs are replaced by the per-concept
  // tabs above; the generic slab form would also clear a band's amount/basis.
  hiddenTabs: ["rates", "slabs"],
  slabsTabOverride: undefined,
};
