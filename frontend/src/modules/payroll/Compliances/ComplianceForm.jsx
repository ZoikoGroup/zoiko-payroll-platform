import { useState } from "react";
import { Shield, Upload, Info } from "lucide-react";
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
    <div className="flex items-center gap-4 mb-5 pb-5 border-b border-border">
      <div className="h-14 w-14 shrink-0 overflow-hidden rounded-[12px] border border-border bg-background flex items-center justify-center">
        {organization?.logo_data_uri ? (
          <img src={organization.logo_data_uri} alt="" className="h-full w-full object-contain" />
        ) : (
          <span className="text-[9px] font-semibold uppercase tracking-wide text-foreground-muted">No logo</span>
        )}
      </div>
      <div>
        <p className="text-[13px] font-bold text-foreground mb-1.5">Company Logo</p>
        <label
          className="inline-flex items-center gap-1.5 rounded-[10px] border border-border bg-surface px-3 py-1.5 text-[12px] font-semibold text-foreground transition-all duration-200 hover:border-primary"
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
        <p className="text-[11px] text-foreground-muted mt-1.5">JPG or SVG only, up to 2 MB. Appears in the app header.</p>
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
    <div className="bg-surface border border-border rounded-[18px] p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
      <div className="flex items-center gap-2 mb-5">
        <div className="p-1.5 rounded-[10px] bg-primary/10">
          <Shield size={16} className="text-primary" />
        </div>
        <h3 className="text-[15px] font-bold text-foreground">Company Compliance Details</h3>
      </div>

      <CompanyLogoField addToast={addToast} />

      <div className="rounded-[12px] bg-info/5 border border-info/15 px-4 py-3 mb-5 text-[12px] text-foreground-muted flex items-center gap-2">
        <Info size={14} className="text-info shrink-0" />
        <span>Values below are inherited from the <strong>Super Admin's</strong> compliance configuration. You can overwrite fields where permitted — changes apply only to your organization.</span>
      </div>

      <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
        {FIELDS.map((f) => (
          <div key={f.field}>
            <label className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted mb-1.5 flex items-center gap-1.5">
              {f.label}
            </label>

            {f.type === "text" && (
              <input
                type="text"
                value={companyDetails?.[f.field] || ""}
                onChange={(e) => handleChange(f.field, e.target.value)}
                className="w-full rounded-[12px] border border-border bg-background px-3.5 py-2.5 text-[13px] text-foreground placeholder:text-foreground-muted focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200"
              />
            )}

            {(f.type === "readonly" || f.type === "readonly-country") && (
              <div className="w-full rounded-[12px] border border-border bg-surface px-3.5 py-2.5 text-[13px] text-foreground">
                {f.type === "readonly-country"
                  ? (companyDetails?.jurisdictionCountry ? getCountryMeta(companyDetails.jurisdictionCountry).name : "— Not set —")
                  : (companyDetails?.[f.field] || "— Not set —")}
              </div>
            )}
          </div>
        ))}

        {taxFields.length === 0 && (
          <div>
            <label className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted mb-1.5 flex items-center gap-1.5">
              {taxIdLabel}
            </label>
            <input
              type="text"
              value={companyDetails?.taxNo || ""}
              onChange={(e) => handleChange("taxNo", e.target.value)}
              className="w-full rounded-[12px] border border-border bg-background px-3.5 py-2.5 text-[13px] text-foreground placeholder:text-foreground-muted focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200"
            />
          </div>
        )}
      </div>

      {taxFields.length > 0 && (
        <div className="mt-6 pt-5 border-t border-border">
          <p className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">
            Business Registration & Tax Identification
          </p>
          <p className="text-[12px] text-foreground-muted mt-0.5 mb-3">
            Edit / override the {getCountryMeta(companyDetails?.jurisdictionCountry).name} registration IDs. Format is validated as you enter.
          </p>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {taxFields.map((f) => {
              const value = companyDetails?.taxIdentifiers?.[f.key] ?? (f.primary ? companyDetails?.taxNo || "" : "");
              const invalid = Boolean(value) && !isJurisdictionTaxValueValid(f, value);
              return (
                <div key={f.key}>
                  <label className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted mb-1.5 flex items-center gap-1.5">
                    {f.label} {f.primary && <span className="text-error">*</span>}
                  </label>
                  <input
                    type="text"
                    value={value}
                    onChange={(e) => onTaxIdentifierChange?.(f.key, e.target.value)}
                    placeholder={`e.g. ${f.example}`}
                    className={`w-full rounded-[12px] border bg-background px-3.5 py-2.5 text-[13px] text-foreground placeholder:text-foreground-muted focus:outline-none focus:ring-2 transition-all duration-200 ${
                      invalid
                        ? "border-error focus:border-error focus:ring-error/20"
                        : "border-border focus:border-primary focus:ring-primary/20"
                    }`}
                  />
                  {invalid && (
                    <p className="text-[11px] text-error mt-1">
                      Invalid format — e.g. {f.example}.
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      <p className="text-[13px] text-foreground-muted mt-5">
        Jurisdiction is set automatically from your organization's registration details and can't be changed here.
        {" "}{stateRuleNote}
      </p>
    </div>
  );
}
