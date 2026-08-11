import { useState } from "react";
import { Shield, Upload } from "lucide-react";
import { getCountryMeta } from "../../../service/payrollService";
import { getComplianceLabels } from "../../../utils/jurisdictionLabels";
import {
  getJurisdictionTaxFields,
  isJurisdictionTaxValueValid,
} from "../../../utils/jurisdictionTax";
import { uploadOrganizationLogo } from "../../../service/orgAdminService";
import { useOrganization } from "../../../context/OrganizationContext";

function getBaseFields(country) {
  return [
    { label: "Company Legal Name", field: "name", type: "text" },
    { label: "Company Type", field: "type", type: "text" },
    { label: "Employer ID / Registration No.", field: "employerId", type: "text" },
    { label: "Registered Address", field: "address", type: "text" },
    { label: "Industry", field: "industry", type: "text" },
    { label: "Email", field: "email", type: "text" },
    { label: "Phone", field: "phone", type: "text" },
    { label: "Jurisdiction — Country", field: "jurisdictionCountry", type: "readonly-country" },
    { label: "Jurisdiction — State / Province", field: "jurisdictionState", type: "readonly" },
    { label: "Compliance Pack", field: "compliancePack", type: "text" },
    { label: "Settlement Bank", field: "settlementBank", type: "text" },
    { label: "Settlement Account Number", field: "settlementAcc", type: "text" },
  ];
}

function CompanyLogoField({ addToast }) {
  const { organization, refresh } = useOrganization();
  const [uploading, setUploading] = useState(false);

  const handleLogoChange = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    if (!["image/jpeg", "image/jpg", "image/svg+xml"].includes(file.type) || ![".jpg", ".jpeg", ".svg"].includes(ext)) {
      addToast?.("Logo must be a JPG or SVG image.", "error");
      return;
    }
    if (file.size > 2 * 1024 * 1024) {
      addToast?.("Logo must be smaller than 2 MB.", "error");
      return;
    }
    setUploading(true);
    try {
      await uploadOrganizationLogo(file);
      await refresh();
      addToast?.("Company logo updated successfully.", "success");
    } catch (err) {
      addToast?.(err?.message || "Failed to upload logo.", "error");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="flex items-center gap-4 mb-5 pb-5 border-b border-[#F0EDE8] dark:border-[#38312D]">
      <div className="h-14 w-14 shrink-0 overflow-hidden rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] flex items-center justify-center">
        {organization?.logo_data_uri ? (
          <img src={organization.logo_data_uri} alt="" className="h-full w-full object-contain" />
        ) : (
          <span className="text-[9px] font-semibold uppercase tracking-wide text-[#9E9690]">No logo</span>
        )}
      </div>
      <div>
        <p className="text-[13px] font-bold text-[#1A1816] dark:text-[#F0EDE8] mb-1.5">Company Logo</p>
        <label
          className="inline-flex items-center gap-1.5 rounded-[10px] border border-[#E5E0D9] dark:border-[#38312D] bg-white dark:bg-[#221D1A] px-3 py-1.5 text-[12px] font-semibold text-[#1A1816] dark:text-[#F0EDE8] transition-all duration-200 hover:border-[#19C58A]"
          style={{ cursor: uploading ? "not-allowed" : "pointer", opacity: uploading ? 0.6 : 1 }}
        >
          <Upload className="w-3.5 h-3.5" />
          {uploading ? "Uploading…" : organization?.logo_data_uri ? "Replace logo" : "Upload logo"}
          <input
            type="file"
            accept="image/jpeg,image/jpg,.jpg,.jpeg,.svg,image/svg+xml"
            onChange={handleLogoChange}
            disabled={uploading}
            style={{ display: "none" }}
          />
        </label>
        <p className="text-[11px] text-[#9E9690] mt-1.5">JPG or SVG only, up to 2 MB. Appears in the app header.</p>
      </div>
    </div>
  );
}

export default function ComplianceForm({ companyDetails, onUpdate, onTaxIdentifierChange, addToast }) {
  const handleChange = (field, value) => {
    if (onUpdate) onUpdate(field, value);
  };

  const { taxIdLabel, stateRuleNote } = getComplianceLabels(companyDetails?.jurisdictionCountry);
  const FIELDS = getBaseFields(companyDetails?.jurisdictionCountry);
  const taxFields = getJurisdictionTaxFields(companyDetails?.jurisdictionCountry);

  return (
    <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
      <div className="flex items-center gap-2 mb-5">
        <div className="p-1.5 rounded-[10px] bg-[#19C58A]/10">
          <Shield size={16} className="text-[#19C58A]" />
        </div>
        <h3 className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">Company Compliance Details</h3>
      </div>

      <CompanyLogoField addToast={addToast} />

      <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
        {FIELDS.map((f) => (
          <div key={f.field}>
            <label className="text-[11px] font-bold uppercase tracking-widest text-[#9E9690] mb-1.5 flex items-center gap-1.5">
              {f.label}
            </label>

            {f.type === "text" && (
              <input
                type="text"
                value={companyDetails?.[f.field] || ""}
                onChange={(e) => handleChange(f.field, e.target.value)}
                className="w-full rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-3.5 py-2.5 text-[13px] text-[#1A1816] dark:text-[#F0EDE8] placeholder:text-[#9E9690] focus:outline-none focus:border-[#19C58A] focus:ring-2 focus:ring-[#19C58A]/20 transition-all duration-200"
              />
            )}

            {(f.type === "readonly" || f.type === "readonly-country") && (
              <div className="w-full rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F1EFEA] dark:bg-[#241F1B] px-3.5 py-2.5 text-[13px] text-[#1A1816] dark:text-[#F0EDE8]">
                {f.type === "readonly-country"
                  ? (companyDetails?.jurisdictionCountry ? getCountryMeta(companyDetails.jurisdictionCountry).name : "— Not set —")
                  : (companyDetails?.[f.field] || "— Not set —")}
              </div>
            )}
          </div>
        ))}

        {taxFields.length === 0 && (
          <div>
            <label className="text-[11px] font-bold uppercase tracking-widest text-[#9E9690] mb-1.5 flex items-center gap-1.5">
              {taxIdLabel}
            </label>
            <input
              type="text"
              value={companyDetails?.taxNo || ""}
              onChange={(e) => handleChange("taxNo", e.target.value)}
              className="w-full rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-3.5 py-2.5 text-[13px] text-[#1A1816] dark:text-[#F0EDE8] placeholder:text-[#9E9690] focus:outline-none focus:border-[#19C58A] focus:ring-2 focus:ring-[#19C58A]/20 transition-all duration-200"
            />
          </div>
        )}
      </div>

      {taxFields.length > 0 && (
        <div className="mt-6 pt-5 border-t border-[#F0EDE8] dark:border-[#38312D]">
          <p className="text-[11px] font-bold uppercase tracking-widest text-[#9E9690]">
            Business Registration & Tax Identification
          </p>
          <p className="text-[12px] text-[#9E9690] mt-0.5 mb-3">
            Edit / override the {getCountryMeta(companyDetails?.jurisdictionCountry).name} registration IDs. Format is validated as you enter.
          </p>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {taxFields.map((f) => {
              const value = companyDetails?.taxIdentifiers?.[f.key] ?? (f.primary ? companyDetails?.taxNo || "" : "");
              const invalid = Boolean(value) && !isJurisdictionTaxValueValid(f, value);
              return (
                <div key={f.key}>
                  <label className="text-[11px] font-bold uppercase tracking-widest text-[#9E9690] mb-1.5 flex items-center gap-1.5">
                    {f.label} {f.primary && <span className="text-[#EF4444]">*</span>}
                  </label>
                  <input
                    type="text"
                    value={value}
                    onChange={(e) => onTaxIdentifierChange?.(f.key, e.target.value)}
                    placeholder={`e.g. ${f.example}`}
                    className={`w-full rounded-[12px] border bg-[#F8F7F4] dark:bg-[#1A1816] px-3.5 py-2.5 text-[13px] text-[#1A1816] dark:text-[#F0EDE8] placeholder:text-[#9E9690] focus:outline-none focus:ring-2 transition-all duration-200 ${
                      invalid
                        ? "border-[#EF4444] focus:border-[#EF4444] focus:ring-[#EF4444]/20"
                        : "border-[#E5E0D9] dark:border-[#38312D] focus:border-[#19C58A] focus:ring-[#19C58A]/20"
                    }`}
                  />
                  {invalid && (
                    <p className="text-[11px] text-[#EF4444] mt-1">
                      Invalid format — e.g. {f.example}.
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      <p className="text-[13px] text-[#9E9690] mt-5">
        Jurisdiction is set automatically from your organization's registration details and can't be changed here.
        {" "}{stateRuleNote}
      </p>
    </div>
  );
}
