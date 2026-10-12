import { Landmark } from "lucide-react";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";
import TTNisClassPanel from "../../components/jurisdiction/trinidad/TTNisClassPanel";

// Trinidad and Tobago — country-level only. PAYE bands and the flat
// Health Surcharge fee are editable through JurisdictionLayout's generic
// Tax Slabs / Contribution Rates tabs — see engine/countries/
// trinidad_and_tobago.py's docstring.
//
// The 16-class fixed NIS table (rule_type="TT_NIS_CLASS") gets its own
// dedicated tab (TTNisClassPanel) rather than the generic Tax Slabs
// table — a flat weekly dollar amount per class, not a percentage, so
// the generic table would render a misleading "0% rate" for it (see
// engine/countries/shared.py's own docstring for the column-reuse
// convention). slabsFilter strips these rows OUT of the generic Tax
// Slabs tab for the same reason.
const extraTabs = [
  {
    key: "nis-classes", label: "NIS Earnings Classes", icon: Landmark, after: "rates",
    isVisible: () => true,
    render: (p) => <TTNisClassPanel {...p} />,
  },
];

export default function TTCompliancePage() {
  return (
    <JurisdictionLayout
      country="TT" countryName="Trinidad and Tobago"
      extraTabs={extraTabs}
      slabsFilter={(rows) => rows.filter((r) => r.ruleType !== "TT_NIS_CLASS")}
    />
  );
}
