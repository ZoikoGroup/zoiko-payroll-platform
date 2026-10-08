import { Building2, Coins, FileCheck2, FileSearch, Landmark, ListChecks, MapPin, Scale, ShieldCheck } from "lucide-react";
import CHParameterTab from "../../components/jurisdiction/switzerland/CHParameterTab";
import CHCantonStatusTab from "../../components/jurisdiction/switzerland/CHCantonStatusTab";
import CHQstTariffTab from "../../components/jurisdiction/switzerland/CHQstTariffTab";
import CHSchemeCatalogTab from "../../components/jurisdiction/switzerland/CHSchemeCatalogTab";
import CHTaxabilityTab from "../../components/jurisdiction/switzerland/CHTaxabilityTab";
import CHWageFloorTab from "../../components/jurisdiction/switzerland/CHWageFloorTab";
import CHReadinessTab from "../../components/jurisdiction/switzerland/CHReadinessTab";
import { CH_CANTON_CODES, CH_CANTON_KEYS, CH_FEDERAL_KEYS } from "../../components/jurisdiction/switzerland/chComponentConfig";
import SourceEvidencePanel from "../../components/jurisdiction/SourceEvidencePanel";
import TestCertificationPanel from "../../components/jurisdiction/TestCertificationPanel";

// Switzerland (ZP-CH-PAYROLL-001). One pack per canton (jurisdiction_state =
// the CH-XX code) plus a federal pack (jurisdiction_state NULL), so the
// canton dropdown above selects which canton's tax pack to manage. The
// generic single-list rates/slabs tabs are replaced because a federal scalar
// row (ch_ahv, …) and a canton scaffold row (ch_qst_model, ch_fak_child, …)
// would otherwise be mixed in one undifferentiated list — see chComponentConfig.
export const switzerlandComplianceConfig = {
  extraTabs: [
    {
      key: "federal", label: "Federal Parameters", icon: Landmark, after: "overview",
      isVisible: () => true,
      render: ({ pack, ...props }) => {
        const isCantonPack = Boolean(pack?.jurisdictionState);
        return (
          <CHParameterTab {...props} keys={isCantonPack ? CH_CANTON_KEYS : CH_FEDERAL_KEYS}
            description={isCantonPack
              ? "This canton pack's scaffold rows — QST model, QST tariff file, FAK child/education amounts and the FAK employee share. The federal scalar rows (AHV/IV/EO/ALV, BVG thresholds…) live in the federal pack — select \"Switzerland — federal pack\" above."
              : "Federal statutory scalar rows — AHV/IV/EO/ALV rates, the ALV/UVG ceilings, the BVG entry threshold / coordination deduction / upper and minimum coordinated salary, the FAK federal minimums, the EO parental share and daily cap, and the Swiss 5-Rappen rounding rule. The engine reads them from the Active federal pack."} />
        );
      },
    },
    {
      key: "cantons", label: "Canton Status", icon: MapPin, after: "federal",
      isVisible: () => true,
      render: () => <CHCantonStatusTab />,
    },
    {
      key: "qst", label: "QST Tariff Files", icon: FileSearch, after: "cantons",
      isVisible: () => true,
      render: (props) => <CHQstTariffTab {...props} />,
    },
    {
      key: "schemes", label: "Scheme Catalog", icon: Building2, after: "qst",
      isVisible: () => true,
      render: (props) => <CHSchemeCatalogTab {...props} />,
    },
    {
      key: "classification", label: "Earning Classification", icon: Scale, after: "schemes",
      isVisible: () => true,
      render: (props) => <CHTaxabilityTab {...props} />,
    },
    {
      key: "wagefloors", label: "Wage Floors", icon: Coins, after: "classification",
      isVisible: () => true,
      render: (props) => <CHWageFloorTab {...props} />,
    },
    {
      key: "readiness", label: "Readiness", icon: ListChecks, after: "wagefloors",
      isVisible: () => true,
      render: (props) => <CHReadinessTab {...props} />,
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
          jurisdiction="CH" label="Switzerland (Federal Social Insurance / cantons)"
          fixturesPath="backend/tests/fixtures/ch_golden/README.md"
        />
      ),
    },
  ],
  // Canton packs carry BOTH federal and canton key rows — the generic
  // single-list tabs would overwrite a canton scaffold row's text value with
  // a percent/decimal form. Hidden here (same reason as Italy/Sweden).
  hiddenTabs: ["rates", "slabs"],
  slabsTabOverride: undefined,
  // Switzerland packs are per-canton; offer all 26 as selectable before any
  // pack exists so a Super Admin can create the first canton pack the same
  // way they create any other state's.
  additionalStateOptions: CH_CANTON_CODES,
  countryLevelLabel: "Switzerland — federal pack",
};