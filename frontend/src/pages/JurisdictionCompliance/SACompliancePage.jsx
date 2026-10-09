import { useCallback, useEffect, useState } from "react";
import { Building2, Calculator, ClipboardList, FileCheck2, FileText, Gauge, Landmark, Lock, Settings2, ShieldCheck, ToggleRight, Users, Building, FileSignature, History, Search, ChevronDown } from "lucide-react";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";
import SourceEvidencePanel from "../../components/jurisdiction/SourceEvidencePanel";
import TestCertificationPanel from "../../components/jurisdiction/TestCertificationPanel";
import { SAEmployerProfileTab } from "../../components/jurisdiction/saudi_arabia/SAEmployerProfileTab";
import { SAContractVersionTab } from "../../components/jurisdiction/saudi_arabia/SAContractVersionTab";
import { SAGosiLiabilityTab } from "../../components/jurisdiction/saudi_arabia/SAGosiLiabilityTab";
import { SAEosLedgerTab } from "../../components/jurisdiction/saudi_arabia/SAEosLedgerTab";
import { SAFinalSettlementTab } from "../../components/jurisdiction/saudi_arabia/SAFinalSettlementTab";
import { SAWpsTab } from "../../components/jurisdiction/saudi_arabia/SAWpsTab";
import { SAOrgPickerBar } from "../../components/jurisdiction/saudi_arabia/SAOrgPickerBar";
import { SAGosiBranchesTab } from "../../components/jurisdiction/saudi_arabia/SAGosiBranchesTab";
import { SAEarningClassesTab } from "../../components/jurisdiction/saudi_arabia/SAEarningClassesTab";
import { SAParametersTab } from "../../components/jurisdiction/saudi_arabia/SAParametersTab";
import { SAReadinessPreviewTab } from "../../components/jurisdiction/saudi_arabia/SAReadinessPreviewTab";
import { getCompliancePolicyOrganizations, getCompliancePolicyEligibleOrganizations } from "../../service/superAdminService";
import { useToast } from "../../context/ToastContext";

function saAutoSelectPack(packs) {
  const today = new Date().toISOString().slice(0, 10);
  const tax = packs.filter((p) => p.packType === "tax");
  return tax.find((p) => (!p.effectiveFrom || p.effectiveFrom <= today) && (!p.effectiveTo || p.effectiveTo >= today))
    || tax[0] || null;
}

const isTax = (pack) => pack.packType === "tax";

export default function SACompliancePage() {
  const { addToast } = useToast();
  const [selectedOrgId, setSelectedOrgId] = useState(null);
  const [orgSearch, setOrgSearch] = useState("");
  const [orgDropdownOpen, setOrgDropdownOpen] = useState(false);
  const [eligibleOrgs, setEligibleOrgs] = useState([]);
  const [loadingOrgs, setLoadingOrgs] = useState(false);

  const loadEligibleOrgs = useCallback(async (packId) => {
    if (!packId) return;
    setLoadingOrgs(true);
    try {
      const orgs = await getCompliancePolicyEligibleOrganizations(packId);
      setEligibleOrgs(orgs);
      if (!orgs.find(o => o.id === selectedOrgId) && orgs.length > 0) {
        setSelectedOrgId(orgs[0].id);
      }
    } catch (err) {
      console.error("Failed to load eligible organizations:", err);
    } finally {
      setLoadingOrgs(false);
    }
  }, [selectedOrgId]);

  const onPackChange = useCallback((pack) => {
    if (pack) {
      loadEligibleOrgs(pack.id);
    } else {
      setEligibleOrgs([]);
      setSelectedOrgId(null);
    }
  }, [loadEligibleOrgs]);

  const filteredOrgs = eligibleOrgs.filter(o =>
    o.name.toLowerCase().includes(orgSearch.toLowerCase()) ||
    o.code.toLowerCase().includes(orgSearch.toLowerCase())
  );

  const orgDisplayName = eligibleOrgs.find(o => o.id === selectedOrgId)?.name || "Select organization…";

  const handleOrgSelect = (orgId) => {
    setSelectedOrgId(orgId);
    setOrgDropdownOpen(false);
    setOrgSearch("");
  };

  const saComplianceConfig = {
    autoSelectPack: saAutoSelectPack,
    extraTabs: [
      { key: "sa-employer-profiles", label: "Employer GOSI Profiles", icon: Building, after: "organizations", isVisible: isTax,
        render: ({ pack, addToast, onReload }) => (
          <SAEmployerProfileTab 
            organizationId={selectedOrgId} 
            packId={pack?.id}
            disabled={!selectedOrgId}
          />
        )},
      { key: "sa-contract-versions", label: "Employee Contracts", icon: Users, after: "sa-employer-profiles", isVisible: isTax,
        render: ({ pack, addToast, onReload }) => (
          <SAContractVersionTab 
            organizationId={selectedOrgId} 
            packId={pack?.id}
            disabled={!selectedOrgId}
          />
        )},
      { key: "sa-gosi-liability", label: "GOSI Liability", icon: FileSignature, after: "sa-contract-versions", isVisible: isTax,
        render: ({ pack, addToast, onReload }) => (
          <SAGosiLiabilityTab 
            organizationId={selectedOrgId} 
            packId={pack?.id}
            disabled={!selectedOrgId}
          />
        )},
      { key: "sa-eos-ledger", label: "EOS Ledger", icon: History, after: "sa-gosi-liability", isVisible: isTax,
        render: ({ pack, addToast, onReload }) => (
          <SAEosLedgerTab 
            organizationId={selectedOrgId} 
            packId={pack?.id}
            disabled={!selectedOrgId}
          />
        )},
      { key: "sa-final-settlement", label: "Final Settlement", icon: ClipboardList, after: "sa-eos-ledger", isVisible: isTax,
        render: ({ pack, addToast, onReload }) => (
          <SAFinalSettlementTab 
            organizationId={selectedOrgId} 
            packId={pack?.id}
            disabled={!selectedOrgId}
          />
        )},
      { key: "sa-wps", label: "WPS SIE Extract", icon: FileText, after: "sa-final-settlement", isVisible: isTax,
        render: ({ pack, addToast, onReload }) => (
          <SAWpsTab 
            organizationId={selectedOrgId} 
            packId={pack?.id}
            disabled={!selectedOrgId}
          />
        )},
      { key: "sa-gosi-branches", label: "GOSI Branches", icon: Settings2, after: "sa-wps", isVisible: isTax,
        render: ({ pack, addToast, onReload }) => (
          <SAGosiBranchesTab packId={pack?.id} />
        )},
      { key: "sa-earning-classes", label: "Earning Classification", icon: ClipboardList, after: "sa-gosi-branches", isVisible: isTax,
        render: ({ pack, addToast, onReload }) => (
          <SAEarningClassesTab packId={pack?.id} />
        )},
      { key: "sa-parameters", label: "Parameters", icon: Landmark, after: "sa-gosi-branches", isVisible: isTax,
        render: ({ pack, addToast, onReload }) => (
          <SAParametersTab packId={pack?.id} />
        )},
      { key: "sa-readiness-preview", label: "Readiness & Preview", icon: Gauge, after: "sa-parameters", isVisible: isTax,
        render: ({ pack, addToast, onReload }) => (
          <SAReadinessPreviewTab packId={pack?.id} />
        )},
      { key: "sa-evidence", label: "Source Evidence", icon: FileCheck2, after: "sa-readiness-preview", isVisible: isTax,
        render: () => <SourceEvidencePanel /> },
      { key: "sa-golden", label: "Golden Vectors", icon: ShieldCheck, after: "sa-evidence", isVisible: isTax,
        render: () => (
          <TestCertificationPanel jurisdiction="SA" label="Saudi Arabia (GOSI / MHRSD / Mudad)"
            fixturesPath="backend/tests/fixtures/sa_golden/README.md" />
        ) },
    ],
    hiddenTabs: ["slabs", "rates"],
    countryLevelLabel: "Saudi Arabia (country-level)",
  };

  return (
    <>
      <div>
        <SAOrgPickerBar
        orgDisplayName={orgDisplayName}
        orgDropdownOpen={orgDropdownOpen}
        setOrgDropdownOpen={setOrgDropdownOpen}
        orgSearch={orgSearch}
        setOrgSearch={setOrgSearch}
        loadingOrgs={loadingOrgs}
        filteredOrgs={filteredOrgs}
        selectedOrgId={selectedOrgId}
        eligibleOrgs={eligibleOrgs}
        handleOrgSelect={handleOrgSelect}
      />
      </div>
      <JurisdictionLayout 
        country="SA" 
        countryName="Saudi Arabia" 
        {...saComplianceConfig}
        onPackChange={onPackChange}
      />
    </>
  );
}