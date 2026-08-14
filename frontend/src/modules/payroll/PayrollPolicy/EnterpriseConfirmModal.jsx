import { Globe2 } from "lucide-react";

export default function EnterpriseConfirmModal({ onCancel, onEnableLater, onConfigure }) {
  return (
    <div
      className="fixed inset-0 z-[9998] flex items-center justify-center bg-background/40 backdrop-blur-sm"
      onClick={onCancel}
    >
      <div
        className="bg-surface rounded-[18px] shadow-[0_24px_48px_rgba(0,0,0,0.15)] p-6 w-full max-w-md"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 mb-4">
          <div className="h-10 w-10 rounded-[12px] bg-category-teal flex items-center justify-center shadow-[0_2px_8px_rgba(157,123,242,0.3)]">
            <Globe2 size={20} className="text-white" />
          </div>
          <h3 className="text-[16px] font-bold text-foreground">
            Enable Enterprise Payroll Policy
          </h3>
        </div>

        <p className="text-[13px] text-foreground-muted leading-relaxed mb-2">
          Enterprise Payroll supports multiple countries, jurisdictions, tax rules, statutory
          contributions, and compliance requirements.
        </p>
        <p className="text-[13px] text-foreground-muted leading-relaxed mb-6">
          Before enabling this policy, you must configure the jurisdictions and compliance
          settings applicable to your organization. Would you like to continue?
        </p>

        <div className="flex flex-col sm:flex-row justify-end gap-3">
          <button
            onClick={onCancel}
            className="rounded-[10px] px-4 py-2.5 text-[13px] font-semibold text-foreground-muted hover:bg-surface-muted transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onEnableLater}
            className="rounded-[10px] border border-border px-4 py-2.5 text-[13px] font-semibold text-foreground hover:border-category-teal hover:text-category-teal transition-colors"
          >
            Enable Later
          </button>
          <button
            onClick={onConfigure}
            className="rounded-[10px] bg-category-teal px-4 py-2.5 text-[13px] font-bold text-white hover:bg-category-teal shadow-[0_2px_8px_rgba(157,123,242,0.3)] transition-colors"
          >
            Configure Compliance
          </button>
        </div>
      </div>
    </div>
  );
}
