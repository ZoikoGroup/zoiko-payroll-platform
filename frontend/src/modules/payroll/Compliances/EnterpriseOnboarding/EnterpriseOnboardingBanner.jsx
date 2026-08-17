import { Check, Globe2 } from "lucide-react";

const STEPS = [
  { id: "jurisdictions", label: "Select Jurisdictions" },
  { id: "contributions", label: "Configure Statutory Contributions" },
  { id: "tax", label: "Configure Tax Rules" },
  { id: "review", label: "Review" },
  { id: "activate", label: "Activate Enterprise Policy" },
];

export default function EnterpriseOnboardingBanner({ jurisdictions = [], enterpriseStatus }) {
  const hasJurisdictions = jurisdictions.length > 0;
  const allConfigured = hasJurisdictions && jurisdictions.every((j) => j.status !== "draft");
  const isActive = enterpriseStatus === "active";

  // Steps are driven off real state, not hardcoded checkmarks.
  const completed = {
    jurisdictions: hasJurisdictions,
    contributions: allConfigured,
    tax: allConfigured,
    review: allConfigured,
    activate: isActive,
  };

  return (
    <div className="bg-gradient-to-br from-category-teal/10 to-info/5 border border-category-teal/20 rounded-[18px] p-6">
      <div className="flex items-center gap-3 mb-1">
        <div className="h-9 w-9 rounded-[10px] bg-category-teal flex items-center justify-center shadow-[0_2px_8px_rgba(157,123,242,0.3)]">
          <Globe2 size={17} className="text-white" />
        </div>
        <h3 className="text-[16px] font-bold text-foreground">Enterprise Payroll Setup</h3>
      </div>
      <p className="text-[13px] text-foreground-muted mb-5">
        Complete your compliance configuration before enabling Enterprise Payroll.
      </p>

      <div className="flex flex-wrap gap-4">
        {STEPS.map((step, i) => {
          const done = completed[step.id];
          return (
            <div key={step.id} className="flex items-center gap-2">
              <div
                className={`flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-bold ${
                  done ? "bg-primary text-white" : "bg-surface border border-border text-foreground-muted"
                }`}
              >
                {done ? <Check size={12} /> : i + 1}
              </div>
              <span className={`text-[12px] font-semibold ${done ? "text-foreground" : "text-foreground-muted"}`}>
                {step.label}
              </span>
              {i < STEPS.length - 1 && <span className="text-foreground-disabled mx-1">→</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
