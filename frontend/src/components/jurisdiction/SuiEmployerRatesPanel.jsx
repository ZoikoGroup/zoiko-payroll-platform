import WorkerDataLocked from "../WorkerDataLocked";

// Tenant-specific, agency-assigned rates (US SUI, Canada workers'
// compensation/WCB, Australia workers' comp and similar).
//
// ZP-PRIV decision 3: an employer's own agency-assigned rates and account
// numbers are tenant configuration. The Super Admin employer-tax-profile
// routes are retired; each organization maintains its rates from its own
// workspace (Payroll → Employer statutory → Employer tax profiles). This panel
// no longer calls the retired routes.
const LABELS = {
  US: "SUI employer rates",
  CA: "Workers' compensation / WCB employer rates",
  AU: "Workers' compensation employer rates",
};

export default function SuiEmployerRatesPanel({ country = "US" }) {
  const label = LABELS[country] || "Employer-specific tax rates";
  return (
    <WorkerDataLocked variant="tenant" title={`${label} are maintained by each organization`}>
      <p className="text-xs text-slate-500 dark:text-slate-400">
        Agency-assigned rates and employer account numbers come from each employer&apos;s own notices and are entered by
        the organization&apos;s admins. Canonical statutory rates remain on the pack&apos;s Rates tab.
      </p>
    </WorkerDataLocked>
  );
}
