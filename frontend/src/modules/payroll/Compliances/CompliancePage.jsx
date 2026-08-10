import { useState, useEffect } from "react";
import { useLocation } from "react-router-dom";
import { Shield, Lock } from "lucide-react";
import { useToast } from "../ToastContext";
import ComplianceForm from "./ComplianceForm";
import PackMetadataPanel from "./PackMetadataPanel";
import ContributionRatesTable from "./ContributionRatesTable";
import TaxSlabTable from "./TaxSlabTable";
import ComplianceDocumentUpload from "./ComplianceDocuments";
import EnterpriseOnboardingBanner from "./EnterpriseOnboarding/EnterpriseOnboardingBanner";
import EnterpriseJurisdictionsTab from "./EnterpriseOnboarding/EnterpriseJurisdictionsTab";
import {
  fetchComplianceData,
  updateCompanyDetails,
  getCountryMeta,
  DEFAULT_COUNTRY,
  getActivePolicy,
  getEnterpriseJurisdictions,
} from "../../../service/payrollService";
import { usePayrollSetup } from "../PayrollSetupContext";

const BASE_TABS = ["Overview", "Company Details", "Contribution Rates", "Tax Slabs", "Documents"];

const defaultCompany = {
  name: "",
  type: "",
  taxNo: "",
  employerId: "",
  address: "",
  industry: "",
  jurisdictionCountry: DEFAULT_COUNTRY,
  jurisdictionState: "",
  compliancePack: "",
  settlementBank: "",
  settlementAcc: "",
};

export default function CompliancePage() {
  const { addToast } = useToast();
  const { refresh: refreshPayrollSetup } = usePayrollSetup();
  const location = useLocation();
  const [companyDetails, setCompanyDetails] = useState(defaultCompany);
  const [activeTab, setActiveTab] = useState(0);
  const [documents, setDocuments] = useState([]);
  const [calcMode, setCalcMode] = useState("standard");
  const [enterpriseStatus, setEnterpriseStatus] = useState("not_configured");
  const [enterpriseJurisdictions, setEnterpriseJurisdictions] = useState([]);
  const countryMeta = getCountryMeta(companyDetails.jurisdictionCountry);

  const refreshEnterpriseState = () => {
    getActivePolicy()
      .then((p) => {
        if (p?.calculationMode) setCalcMode(p.calculationMode);
        if (p?.enterpriseStatus) setEnterpriseStatus(p.enterpriseStatus);
      })
      .catch(() => {});
    getEnterpriseJurisdictions().then(setEnterpriseJurisdictions).catch(() => {});
  };

  useEffect(() => {
    refreshEnterpriseState();
    fetchComplianceData().then((data) => {
      if (data && data.company) {
        setCompanyDetails(data.company);
      }
    }).catch(() => {});
  }, []);

  // "Enterprise Jurisdictions" shows for Enterprise mode, mid-onboarding
  // (jurisdictions already started, calc mode not switched back yet — so an
  // admin who navigates away before finishing never loses access to it), or
  // when arriving fresh via the "Configure Compliance" modal button.
  const arrivedForOnboarding = Boolean(location.state?.enterpriseOnboarding);
  const showEnterpriseTab = calcMode === "enterprise" || enterpriseJurisdictions.length > 0 || arrivedForOnboarding;
  const tabs = showEnterpriseTab ? [...BASE_TABS, "Enterprise Jurisdictions"] : BASE_TABS;
  const showOnboardingBanner = arrivedForOnboarding || (enterpriseJurisdictions.length > 0 && enterpriseStatus !== "active");

  useEffect(() => {
    if (arrivedForOnboarding) setActiveTab(BASE_TABS.length);
  }, [arrivedForOnboarding]);

  const handleUpdate = (field, value) => {
    setCompanyDetails((prev) => {
      const next = { ...prev, [field]: value };
      return next;
    });
  };

  const handleSaveCompany = async () => {
    try {
      await updateCompanyDetails(companyDetails);
      // Refresh the shared module-wide context so the onboarding gate (and
      // every other sub-module reading currency/jurisdiction from it) picks
      // up "configured" immediately, without a reload.
      refreshPayrollSetup();
      addToast?.("Company details saved successfully.", "success");
    } catch (err) {
      addToast?.(err?.status === 423 ? err.message : "Failed to save company details.", "error");
    }
  };

  return (
    <div className="bg-[#F8F7F4] dark:bg-[#1A1816] min-h-screen p-6 lg:p-8 space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-[12px] bg-[#19C58A] flex items-center justify-center shadow-[0_2px_8px_rgba(25,197,138,0.3)]">
            <Shield size={20} className="text-white" />
          </div>
          <div>
            <h1 className="text-[28px] font-extrabold tracking-tight text-[#1A1816] dark:text-[#F0EDE8]">Audit & Compliance</h1>
            <p className="text-[13px] font-medium text-[#9E9690]">Manage your statutory compliance</p>
          </div>
        </div>
        <span className="rounded-full bg-[#19C58A]/10 border border-[#19C58A]/20 px-3.5 py-1.5 text-[11px] font-bold text-[#19C58A]">
          {countryMeta.name} compliance pack
        </span>
      </div>

      {showOnboardingBanner && (
        <EnterpriseOnboardingBanner jurisdictions={enterpriseJurisdictions} enterpriseStatus={enterpriseStatus} />
      )}

      {calcMode === "simple" && (
        <div className="bg-[#F8A60A]/5 border border-[#F8A60A]/15 rounded-[14px] px-4 py-3 text-[13px] text-[#6B6560] dark:text-[#A69B93] flex items-center gap-2">
          <Lock size={14} className="text-[#F8A60A]" />
          <span>Statutory compliance tabs are locked in <strong>Simple Payroll</strong> mode. Switch to <strong>Standard</strong> or <strong>Enterprise</strong> in Payroll Policy to enable Contribution Rates, Tax Slabs, Documents, and Enterprise Jurisdictions.</span>
        </div>
      )}

      {calcMode === "standard" && (
        <div className="bg-[#35B6F5]/5 border border-[#35B6F5]/15 rounded-[14px] px-4 py-3 text-[13px] text-[#6B6560] dark:text-[#A69B93] flex items-center gap-2">
          <Lock size={14} className="text-[#35B6F5]" />
          <span>Enterprise Jurisdictions is only available in <strong>Enterprise Payroll</strong> mode.</span>
        </div>
      )}

      <div className="flex gap-1 bg-[#F0EDE8] dark:bg-[#38312D] rounded-[14px] p-1 w-fit flex-wrap">
        {tabs.map((t, i) => {
          const disabled = (calcMode === "simple" && (t === "Contribution Rates" || t === "Tax Slabs" || t === "Documents" || t === "Enterprise Jurisdictions")) || (calcMode === "standard" && !arrivedForOnboarding && t === "Enterprise Jurisdictions");
          return (
            <button
              key={t}
              onClick={() => !disabled && setActiveTab(i)}
              className={`px-4 py-2 rounded-[12px] text-[13px] font-semibold transition-all duration-200 ${
                disabled ? "text-[#9E9690] opacity-40 cursor-not-allowed" : activeTab === i ? "bg-white dark:bg-[#221D1A] text-[#19C58A] shadow-[0_1px_3px_rgba(0,0,0,0.08)]" : "text-[#9E9690] hover:text-[#1A1816] dark:hover:text-[#F0EDE8]"
              }`}
            >
              <span className="flex items-center gap-1.5">{disabled && <Lock size={12} />}{t}</span>
            </button>
          );
        })}
      </div>

      {activeTab === 0 && (
        <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
          <h3 className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8] mb-5">Compliance Overview</h3>
          <div className="grid md:grid-cols-2 gap-6">
            <div className="space-y-3">
              <p className="text-[11px] font-bold uppercase tracking-widest text-[#9E9690]">Company</p>
              <p className="text-[13px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">{companyDetails.name}</p>
              <p className="text-[13px] text-[#6B6560] dark:text-[#A69B93]">{companyDetails.type} · {companyDetails.industry}</p>
              <p className="text-[13px] text-[#9E9690]">Tax ID: {companyDetails.taxNo}</p>
              {companyDetails.email && <p className="text-[13px] text-[#9E9690]">Email: {companyDetails.email}</p>}
              {companyDetails.phone && <p className="text-[13px] text-[#9E9690]">Phone: {companyDetails.phone}</p>}
            </div>
            <div className="space-y-3">
              <p className="text-[11px] font-bold uppercase tracking-widest text-[#9E9690]">Jurisdiction</p>
              <p className="text-[13px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">{countryMeta.name}</p>
              <p className="text-[13px] text-[#6B6560] dark:text-[#A69B93]">{companyDetails.jurisdictionState || "All states"}</p>
              <p className="text-[13px] text-[#9E9690]">Pack: {companyDetails.compliancePack}</p>
            </div>
          </div>
        </div>
      )}

      {activeTab === 1 && (
        <div className="space-y-4">
          <ComplianceForm
            companyDetails={companyDetails}
            onUpdate={handleUpdate}
          />
          <div className="flex justify-end">
            <button
              onClick={handleSaveCompany}
              className="rounded-[12px] bg-[#19C58A] px-5 py-2.5 text-[13px] font-bold text-white transition-all duration-200 hover:bg-[#15B07A] shadow-[0_2px_8px_rgba(25,197,138,0.3)]"
            >
              Save Company Details
            </button>
          </div>
          <PackMetadataPanel
            country={companyDetails.jurisdictionCountry}
            state={companyDetails.jurisdictionState}
            addToast={addToast}
          />
        </div>
      )}

      {activeTab === 2 && calcMode !== "simple" && (
        <ContributionRatesTable documents={documents} country={companyDetails.jurisdictionCountry} />
      )}
      {activeTab === 2 && calcMode === "simple" && (
        <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-12 shadow-[0_1px_3px_rgba(0,0,0,0.04)] text-center">
          <div className="mx-auto mb-4 h-14 w-14 rounded-full bg-[#9E9690]/10 flex items-center justify-center">
            <Lock size={24} className="text-[#9E9690]" />
          </div>
          <h3 className="text-[17px] font-bold text-[#1A1816] dark:text-[#F0EDE8] mb-2">Contribution Rates</h3>
          <p className="text-[13px] text-[#9E9690] max-w-md mx-auto">Contribution rates are not available in Simple Payroll mode.</p>
        </div>
      )}

      {activeTab === 3 && calcMode !== "simple" && (
        <TaxSlabTable documents={documents} country={companyDetails.jurisdictionCountry} />
      )}
      {activeTab === 3 && calcMode === "simple" && (
        <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-12 shadow-[0_1px_3px_rgba(0,0,0,0.04)] text-center">
          <div className="mx-auto mb-4 h-14 w-14 rounded-full bg-[#9E9690]/10 flex items-center justify-center">
            <Lock size={24} className="text-[#9E9690]" />
          </div>
          <h3 className="text-[17px] font-bold text-[#1A1816] dark:text-[#F0EDE8] mb-2">Tax Slabs</h3>
          <p className="text-[13px] text-[#9E9690] max-w-md mx-auto">Tax slabs are not available in Simple Payroll mode.</p>
        </div>
      )}

      {activeTab === 4 && calcMode !== "simple" && (
        <ComplianceDocumentUpload
          country={companyDetails.jurisdictionCountry}
          addToast={addToast}
          documents={documents}
          setDocuments={setDocuments}
        />
      )}
      {activeTab === 4 && calcMode === "simple" && (
        <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-12 shadow-[0_1px_3px_rgba(0,0,0,0.04)] text-center">
          <div className="mx-auto mb-4 h-14 w-14 rounded-full bg-[#9E9690]/10 flex items-center justify-center">
            <Lock size={24} className="text-[#9E9690]" />
          </div>
          <h3 className="text-[17px] font-bold text-[#1A1816] dark:text-[#F0EDE8] mb-2">Compliance Documents</h3>
          <p className="text-[13px] text-[#9E9690] max-w-md mx-auto">Compliance documents are not available in Simple Payroll mode.</p>
        </div>
      )}

      {showEnterpriseTab && activeTab === 5 && (calcMode === "enterprise" || arrivedForOnboarding) && (
        <EnterpriseJurisdictionsTab
          enterpriseStatus={enterpriseStatus}
          onEnterpriseChanged={refreshEnterpriseState}
        />
      )}
      {showEnterpriseTab && activeTab === 5 && !(calcMode === "enterprise" || arrivedForOnboarding) && (
        <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-12 shadow-[0_1px_3px_rgba(0,0,0,0.04)] text-center">
          <div className="mx-auto mb-4 h-14 w-14 rounded-full bg-[#9E9690]/10 flex items-center justify-center">
            <Lock size={24} className="text-[#9E9690]" />
          </div>
          <h3 className="text-[17px] font-bold text-[#1A1816] dark:text-[#F0EDE8] mb-2">Enterprise Jurisdictions</h3>
          <p className="text-[13px] text-[#9E9690] max-w-md mx-auto">Enterprise jurisdictions are only available in Enterprise Payroll mode.</p>
        </div>
      )}
    </div>
  );
}
