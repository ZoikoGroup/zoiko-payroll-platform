import { useState, useEffect } from "react";
import { useLocation } from "react-router-dom";
import { Shield, Lock, Info } from "lucide-react";
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
  getPayslips,
} from "../../../service/payrollService";
import { getJurisdictionTaxFields } from "../../../utils/jurisdictionTax";
import { usePayrollSetup } from "../PayrollSetupContext";

const BASE_TABS = ["Overview", "Company Details", "Contribution Rates", "Tax Slabs", "Documents"];

const defaultCompany = {
  name: "",
  type: "",
  taxNo: "",
  taxIdentifiers: {},
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
  const [resolvedRegions, setResolvedRegions] = useState([]);
  const countryMeta = getCountryMeta(companyDetails.jurisdictionCountry);
  const taxIdsDisplay = getJurisdictionTaxFields(companyDetails.jurisdictionCountry)
    .map((f) => (companyDetails.taxIdentifiers?.[f.key] ? `${f.label}: ${companyDetails.taxIdentifiers[f.key]}` : null))
    .filter(Boolean)
    .join(" · ");

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
    // Which region/locality actually resolved for this org's most recent
    // payroll run — sourced from each payslip's own snapshot, not just the
    // company's configured jurisdiction, so a state/locality-specific rate
    // (e.g. Maharashtra Professional Tax) is visibly reflected here.
    getPayslips().then((rows) => {
      if (!rows?.length) { setResolvedRegions([]); return; }
      const latestPeriod = rows[0].period;
      const seen = new Set();
      const regions = [];
      rows.filter((r) => r.period === latestPeriod).forEach((r) => {
        const label = [r.workState, r.workLocality].filter(Boolean).join(" · ");
        if (label && !seen.has(label)) { seen.add(label); regions.push(label); }
      });
      setResolvedRegions(regions);
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

  // Edit / Override mode for the jurisdiction tax/registration IDs. Merges the
  // new value into taxIdentifiers and mirrors the primary field into the
  // legacy tax_no so the overview/footers keep reading a single value.
  const handleTaxIdentifierChange = (key, value) => {
    setCompanyDetails((prev) => {
      const taxIdentifiers = { ...(prev.taxIdentifiers || {}), [key]: value };
      const next = { ...prev, taxIdentifiers };
      const primaryField = getJurisdictionTaxFields(prev.jurisdictionCountry).find((f) => f.primary);
      if (primaryField && key === primaryField.key) {
        next.taxNo = value;
      }
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
    <div className="bg-background min-h-screen p-6 lg:p-8 space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-[12px] bg-primary flex items-center justify-center shadow-[0_2px_8px_rgba(25,197,138,0.3)]">
            <Shield size={20} className="text-white" />
          </div>
          <div>
            <h1 className="text-[28px] font-extrabold tracking-tight text-foreground">Audit & Compliance</h1>
            <p className="text-[13px] font-medium text-foreground-muted">Manage your statutory compliance</p>
          </div>
        </div>
        <span className="rounded-full bg-primary/10 border border-primary/20 px-3.5 py-1.5 text-[11px] font-bold text-primary">
          {countryMeta.name} compliance pack
        </span>
      </div>

      {showOnboardingBanner && (
        <EnterpriseOnboardingBanner jurisdictions={enterpriseJurisdictions} enterpriseStatus={enterpriseStatus} />
      )}

      {calcMode === "simple" && (
        <div className="bg-warning/5 border border-warning/15 rounded-[14px] px-4 py-3 text-[13px] text-foreground-muted flex items-center gap-2">
          <Lock size={14} className="text-warning" />
          <span>Statutory compliance tabs are locked in <strong>Simple Payroll</strong> mode. Switch to <strong>Standard</strong> or <strong>Enterprise</strong> in Payroll Policy to enable Contribution Rates, Tax Slabs, Documents, and Enterprise Jurisdictions.</span>
        </div>
      )}

      {calcMode === "standard" && (
        <div className="bg-info/5 border border-info/15 rounded-[14px] px-4 py-3 text-[13px] text-foreground-muted flex items-center gap-2">
          <Lock size={14} className="text-info" />
          <span>Enterprise Jurisdictions is only available in <strong>Enterprise Payroll</strong> mode.</span>
        </div>
      )}

      <div className="flex gap-1 bg-surface-muted rounded-[14px] p-1 w-fit flex-wrap">
        {tabs.map((t, i) => {
          const disabled = (calcMode === "simple" && (t === "Contribution Rates" || t === "Tax Slabs" || t === "Documents" || t === "Jurisdiction Hierarchy" || t === "Enterprise Jurisdictions")) || (calcMode === "standard" && !arrivedForOnboarding && t === "Enterprise Jurisdictions");
          return (
            <button
              key={t}
              onClick={() => !disabled && setActiveTab(i)}
              className={`px-4 py-2 rounded-[12px] text-[13px] font-semibold transition-all duration-200 ${
                disabled ? "text-foreground-muted opacity-40 cursor-not-allowed" : activeTab === i ? "bg-surface text-primary shadow-[0_1px_3px_rgba(0,0,0,0.08)]" : "text-foreground-muted hover:text-foreground"
              }`}
            >
              <span className="flex items-center gap-1.5">{disabled && <Lock size={12} />}{t}</span>
            </button>
          );
        })}
      </div>

      {activeTab === 0 && (
        <div className="bg-surface border border-border rounded-[18px] p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
          <div className="flex items-center justify-between mb-5">
            <h3 className="text-[15px] font-bold text-foreground">Compliance Overview</h3>
            <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-foreground-muted rounded-full bg-info/10 px-2.5 py-1">
              <Info size={12} /> Inherited from Super Admin
            </span>
          </div>
          <div className="grid md:grid-cols-2 gap-6">
            <div className="space-y-3">
              <p className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Company</p>
              <p className="text-[13px] font-bold text-foreground">{companyDetails.name}</p>
              <p className="text-[13px] text-foreground-muted">{companyDetails.type} · {companyDetails.industry}</p>
              <p className="text-[13px] text-foreground-muted">{taxIdsDisplay || `Tax ID: ${companyDetails.taxNo}`}</p>
              {companyDetails.email && <p className="text-[13px] text-foreground-muted">Email: {companyDetails.email}</p>}
              {companyDetails.phone && <p className="text-[13px] text-foreground-muted">Phone: {companyDetails.phone}</p>}
            </div>
            <div className="space-y-3">
              <p className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Jurisdiction</p>
              <p className="text-[13px] font-bold text-foreground">{countryMeta.name}</p>
              <p className="text-[13px] text-foreground-muted">{companyDetails.jurisdictionState || "All states"}</p>
              <p className="text-[13px] text-foreground-muted">Pack: {companyDetails.compliancePack}</p>
              <p className="text-[13px] text-foreground-muted">
                Resolved region (latest payroll run):{" "}
                <span className="font-semibold text-foreground">
                  {resolvedRegions.length === 0
                    ? "—"
                    : resolvedRegions.length === 1
                    ? resolvedRegions[0]
                    : `${resolvedRegions.length} regions (${resolvedRegions.join(", ")})`}
                </span>
              </p>
            </div>
          </div>
        </div>
      )}

      {activeTab === 1 && (
        <div className="space-y-4">
          <ComplianceForm
            companyDetails={companyDetails}
            onUpdate={handleUpdate}
            onTaxIdentifierChange={handleTaxIdentifierChange}
            addToast={addToast}
          />
          <div className="flex justify-end">
            <button
              onClick={handleSaveCompany}
              className="rounded-[12px] bg-primary px-5 py-2.5 text-[13px] font-bold text-white transition-all duration-200 hover:bg-primary-hover shadow-[0_2px_8px_rgba(25,197,138,0.3)]"
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
        <div className="bg-surface border border-border rounded-[18px] p-12 shadow-[0_1px_3px_rgba(0,0,0,0.04)] text-center">
          <div className="mx-auto mb-4 h-14 w-14 rounded-full bg-foreground-muted/10 flex items-center justify-center">
            <Lock size={24} className="text-foreground-muted" />
          </div>
          <h3 className="text-[17px] font-bold text-foreground mb-2">Contribution Rates</h3>
          <p className="text-[13px] text-foreground-muted max-w-md mx-auto">Contribution rates are not available in Simple Payroll mode.</p>
        </div>
      )}

      {activeTab === 3 && calcMode !== "simple" && (
        <TaxSlabTable documents={documents} country={companyDetails.jurisdictionCountry} />
      )}
      {activeTab === 3 && calcMode === "simple" && (
        <div className="bg-surface border border-border rounded-[18px] p-12 shadow-[0_1px_3px_rgba(0,0,0,0.04)] text-center">
          <div className="mx-auto mb-4 h-14 w-14 rounded-full bg-foreground-muted/10 flex items-center justify-center">
            <Lock size={24} className="text-foreground-muted" />
          </div>
          <h3 className="text-[17px] font-bold text-foreground mb-2">Tax Slabs</h3>
          <p className="text-[13px] text-foreground-muted max-w-md mx-auto">Tax slabs are not available in Simple Payroll mode.</p>
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
        <div className="bg-surface border border-border rounded-[18px] p-12 shadow-[0_1px_3px_rgba(0,0,0,0.04)] text-center">
          <div className="mx-auto mb-4 h-14 w-14 rounded-full bg-foreground-muted/10 flex items-center justify-center">
            <Lock size={24} className="text-foreground-muted" />
          </div>
          <h3 className="text-[17px] font-bold text-foreground mb-2">Compliance Documents</h3>
          <p className="text-[13px] text-foreground-muted max-w-md mx-auto">Compliance documents are not available in Simple Payroll mode.</p>
        </div>
      )}

      {showEnterpriseTab && activeTab === BASE_TABS.length && (calcMode === "enterprise" || arrivedForOnboarding) && (
        <EnterpriseJurisdictionsTab
          enterpriseStatus={enterpriseStatus}
          onEnterpriseChanged={refreshEnterpriseState}
        />
      )}
      {showEnterpriseTab && activeTab === BASE_TABS.length && !(calcMode === "enterprise" || arrivedForOnboarding) && (
        <div className="bg-surface border border-border rounded-[18px] p-12 shadow-[0_1px_3px_rgba(0,0,0,0.04)] text-center">
          <div className="mx-auto mb-4 h-14 w-14 rounded-full bg-foreground-muted/10 flex items-center justify-center">
            <Lock size={24} className="text-foreground-muted" />
          </div>
          <h3 className="text-[17px] font-bold text-foreground mb-2">Enterprise Jurisdictions</h3>
          <p className="text-[13px] text-foreground-muted max-w-md mx-auto">Enterprise jurisdictions are only available in Enterprise Payroll mode.</p>
        </div>
      )}
    </div>
  );
}
