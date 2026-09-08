import { useParams, useNavigate } from "react-router-dom";
import { ScrollText, CheckCircle2 } from "lucide-react";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";
import SlabsTab from "../../components/jurisdiction/SlabsTab";
import ComplianceConfigModal, { CONFIG_TYPES } from "../../components/jurisdiction/ComplianceConfigModal";
import UKTaxComponentsTab from "../../components/jurisdiction/uk/UKTaxComponentsTab";
import UKOverviewDashboard from "../../components/jurisdiction/uk/UKOverviewDashboard";

// UK — country-specific configuration object consumed by JurisdictionLayout.
// All UK statutory configuration (National Insurance, Workplace Pension,
// Student Loans, statutory thresholds, NI category bands) is consolidated
// into a single unified "Tax Components" tab; PAYE Income Tax is handled by
// the dedicated PAYE Income Tax Slabs tab. Individual components live in
// components/jurisdiction/uk/ following the india/ and usa/ pattern.

// PAYE Income Tax Slabs: sub-jurisdiction packs (Scotland today) get the
// dedicated "PAYE Tax Band" form (Min/Max/Rate) via slabsTabOverride —
// National Insurance/Pension/Student Loans/Thresholds are national-only,
// so restrictTabsTo hides the unified Tax Components tab for a
// sub-jurisdiction pack (matching real HMRC structure where Scotland only
// publishes its own income tax bands).
const slabsTabOverride = {
  isActive: (pack) => Boolean(pack.jurisdictionState),
  label: "Income Tax Rules",
  restrictTabsTo: ["overview", "slabs", "organizations", "audit"],
  renderTab: ({ pack, slabs, onAdd, onEdit, onDelete }) => (
    <div>
      {pack.jurisdictionState && (
        <div className="mb-3 rounded-lg border border-border-light bg-surface-muted/50 p-3">
          <p className="text-xs font-semibold text-foreground-secondary mb-1.5">Inherited from UK National</p>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {["Personal Allowance", "National Insurance", "Student Loan Rules", "Statutory Payments"].map((rule) => (
              <span key={rule} className="flex items-center gap-1 text-xs text-foreground-muted">
                <CheckCircle2 size={12} className="text-success" /> {rule}
              </span>
            ))}
          </div>
        </div>
      )}
      <SlabsTab pack={pack} slabs={slabs} onAdd={onAdd} onEdit={onEdit} onDelete={onDelete} />
    </div>
  ),
  renderAddModal: ({ pack, onClose, onSaved, addToast }) => (
    <ComplianceConfigModal configType={CONFIG_TYPES.TAX_SLAB} mode="add" pack={pack} addToast={addToast} onClose={onClose} onSaved={onSaved} />
  ),
  renderEditModal: ({ pack, slab, onClose, onSaved, addToast }) => (
    <ComplianceConfigModal configType={CONFIG_TYPES.TAX_SLAB} mode="edit" pack={pack} initialData={slab} addToast={addToast} onClose={onClose} onSaved={onSaved} />
  ),
  deleteTitle: "Delete PAYE Tax Band",
  deleteMessage: (slab) => `Delete the "${slab.rateLabel}" tax band? This cannot be undone.`,
};

const ukComplianceConfig = {
  overviewTabOverride: {
    isActive: (pack) => Boolean(pack),
    render: (props) => <UKOverviewDashboard {...props} />,
  },
  extraTabs: [
    {
      key: "tax-components",
      label: "Tax Components",
      icon: ScrollText,
      after: "overview",
      isVisible: (pack) => !pack.jurisdictionState,
      render: (props) => <UKTaxComponentsTab {...props} />,
    },
  ],
  slabsTabOverride,
  hiddenTabs: ["rates", "versions"],
  slabsLabel: "PAYE Income Tax Slabs",
  countryLevelLabel: "UK National (Personal Allowance, NI, Pension, Student Loans)",
  additionalStateOptions: ["England", "Wales", "Northern Ireland"],
  // NI Category bands (Section D) live as TaxSlab rows too (rule_type=
  // "NI_BAND") — filtered out here so they don't show up as bogus extra
  // brackets in the PAYE Income Tax Slabs table. They're edited from the
  // Tax Components tab instead.
  slabsFilter: (slabs) => slabs.filter((s) => s.ruleType !== "NI_BAND"),
};

export default function UKCompliancePage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <JurisdictionLayout
      country="UK" countryName="United Kingdom"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/compliance/united-kingdom/${encodeURIComponent(state)}` : "/super-admin/compliance/united-kingdom")
      }
      {...ukComplianceConfig}
    />
  );
}
