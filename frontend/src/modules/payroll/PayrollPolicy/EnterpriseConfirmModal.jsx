import { Globe2 } from "lucide-react";

export default function EnterpriseConfirmModal({ onCancel, onEnableLater, onConfigure }) {
  return (
    <div
      className="fixed inset-0 z-[9998] flex items-center justify-center bg-[#1A1816]/40 backdrop-blur-sm"
      onClick={onCancel}
    >
      <div
        className="bg-white dark:bg-[#221D1A] rounded-[18px] shadow-[0_24px_48px_rgba(0,0,0,0.15)] p-6 w-full max-w-md"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 mb-4">
          <div className="h-10 w-10 rounded-[12px] bg-[#9D7BF2] flex items-center justify-center shadow-[0_2px_8px_rgba(157,123,242,0.3)]">
            <Globe2 size={20} className="text-white" />
          </div>
          <h3 className="text-[16px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">
            Enable Enterprise Payroll Policy
          </h3>
        </div>

        <p className="text-[13px] text-[#6B6560] dark:text-[#A69B93] leading-relaxed mb-2">
          Enterprise Payroll supports multiple countries, jurisdictions, tax rules, statutory
          contributions, and compliance requirements.
        </p>
        <p className="text-[13px] text-[#6B6560] dark:text-[#A69B93] leading-relaxed mb-6">
          Before enabling this policy, you must configure the jurisdictions and compliance
          settings applicable to your organization. Would you like to continue?
        </p>

        <div className="flex flex-col sm:flex-row justify-end gap-3">
          <button
            onClick={onCancel}
            className="rounded-[10px] px-4 py-2.5 text-[13px] font-semibold text-[#6B6560] dark:text-[#A69B93] hover:bg-[#F0EDE8] dark:hover:bg-[#38312D] transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onEnableLater}
            className="rounded-[10px] border border-[#E5E0D9] dark:border-[#38312D] px-4 py-2.5 text-[13px] font-semibold text-[#1A1816] dark:text-[#F0EDE8] hover:border-[#9D7BF2] hover:text-[#9D7BF2] transition-colors"
          >
            Enable Later
          </button>
          <button
            onClick={onConfigure}
            className="rounded-[10px] bg-[#9D7BF2] px-4 py-2.5 text-[13px] font-bold text-white hover:bg-[#8A65E0] shadow-[0_2px_8px_rgba(157,123,242,0.3)] transition-colors"
          >
            Configure Compliance
          </button>
        </div>
      </div>
    </div>
  );
}
