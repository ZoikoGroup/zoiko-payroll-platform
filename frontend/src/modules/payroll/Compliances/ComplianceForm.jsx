import { Shield, Lock } from "lucide-react";
import { COMPLIANCE_COUNTRIES, getStatesForCountry } from "../../../service/payrollService";
import { getComplianceLabels } from "../../../utils/jurisdictionLabels";

function getFields(country) {
  const { taxIdLabel } = getComplianceLabels(country);
  return [
    { label: "Company Legal Name", field: "name", type: "text" },
    { label: "Company Type", field: "type", type: "text" },
    { label: taxIdLabel, field: "taxNo", type: "text" },
    { label: "Employer ID / Registration No.", field: "employerId", type: "text" },
    { label: "Registered Address", field: "address", type: "text" },
    { label: "Industry", field: "industry", type: "text" },
    { label: "Email", field: "email", type: "text" },
    { label: "Phone", field: "phone", type: "text" },
    { label: "Jurisdiction — Country", field: "jurisdictionCountry", type: "country-select" },
    { label: "Jurisdiction — State / Province", field: "jurisdictionState", type: "state-select" },
    { label: "Compliance Pack", field: "compliancePack", type: "text" },
    { label: "Settlement Bank", field: "settlementBank", type: "text" },
    { label: "Settlement Account Number", field: "settlementAcc", type: "text" },
  ];
}

export default function ComplianceForm({ companyDetails, onUpdate, addToast }) {
  const handleChange = (field, value) => {
    if (onUpdate) onUpdate(field, value);
  };

  const states = getStatesForCountry(companyDetails?.jurisdictionCountry);
  const jurisdictionLocked = Boolean(companyDetails?.isConfigured);
  const FIELDS = getFields(companyDetails?.jurisdictionCountry);
  const { stateRuleNote } = getComplianceLabels(companyDetails?.jurisdictionCountry);

  return (
    <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
      <div className="flex items-center gap-2 mb-5">
        <div className="p-1.5 rounded-[10px] bg-[#19C58A]/10">
          <Shield size={16} className="text-[#19C58A]" />
        </div>
        <h3 className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">Company Compliance Details</h3>
      </div>
      <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
        {FIELDS.map((f) => (
          <div key={f.field}>
            <label className="text-[11px] font-bold uppercase tracking-widest text-[#9E9690] mb-1.5 flex items-center gap-1.5">
              {f.label}
              {f.type === "country-select" && jurisdictionLocked && (
                <Lock size={11} className="text-[#9E9690]" title="Jurisdiction is locked after Compliance has been configured" />
              )}
            </label>

            {f.type === "text" && (
              <input
                type="text"
                value={companyDetails?.[f.field] || ""}
                onChange={(e) => handleChange(f.field, e.target.value)}
                className="w-full rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-3.5 py-2.5 text-[13px] text-[#1A1816] dark:text-[#F0EDE8] placeholder:text-[#9E9690] focus:outline-none focus:border-[#19C58A] focus:ring-2 focus:ring-[#19C58A]/20 transition-all duration-200"
              />
            )}

            {f.type === "country-select" && (
              <>
                <select
                  value={companyDetails?.[f.field] || ""}
                  onChange={(e) => {
                    handleChange(f.field, e.target.value);
                    handleChange("jurisdictionState", "");
                  }}
                  disabled={jurisdictionLocked}
                  title={jurisdictionLocked ? "Jurisdiction is locked after Compliance has been configured — changing jurisdictions requires a controlled migration process." : undefined}
                  className="w-full rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-3.5 py-2.5 text-[13px] text-[#1A1816] dark:text-[#F0EDE8] placeholder:text-[#9E9690] focus:outline-none focus:border-[#19C58A] focus:ring-2 focus:ring-[#19C58A]/20 transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <option value="">— Select country —</option>
                  {COMPLIANCE_COUNTRIES.map((c) => (
                    <option key={c.code} value={c.code}>{c.name}</option>
                  ))}
                </select>
                {jurisdictionLocked && (
                  <p className="mt-1 text-[11px] text-[#9E9690]">Locked — changing jurisdictions requires a controlled migration process.</p>
                )}
              </>
            )}

            {f.type === "state-select" && (
              <select
                value={companyDetails?.[f.field] || ""}
                onChange={(e) => handleChange(f.field, e.target.value)}
                disabled={states.length === 0}
                className="w-full rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-3.5 py-2.5 text-[13px] text-[#1A1816] dark:text-[#F0EDE8] placeholder:text-[#9E9690] focus:outline-none focus:border-[#19C58A] focus:ring-2 focus:ring-[#19C58A]/20 transition-all duration-200 disabled:text-[#9E9690]"
              >
                <option value="">
                  {states.length === 0 ? "— No states configured for this country —" : "— All states —"}
                </option>
                {states.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            )}
          </div>
        ))}
      </div>

      <p className="text-[13px] text-[#9E9690] mt-5">
        {stateRuleNote} Selecting a specific state here applies
        that state's rules company-wide — per-employee state assignment isn't supported yet.
      </p>
    </div>
  );
}
