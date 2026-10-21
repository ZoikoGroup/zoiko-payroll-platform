import WorkerDataLocked from "../../../WorkerDataLocked";

// State-scoped SUI employer rates. ZP-PRIV decision 3: an employer's own SUI
// rate and account number are tenant configuration; the Super Admin
// employer-tax-profile routes are retired, so this section no longer calls
// them. Canonical state wage bases and rate ranges stay on the state's other
// tabs.
export default function USStateSuiSection({ stateName }) {
  return (
    <WorkerDataLocked variant="tenant" title={`${stateName ? `${stateName} ` : ""}SUI employer rates are maintained by each organization`}>
      <p className="text-xs text-slate-500 dark:text-slate-400">
        Each employer enters its own agency-assigned SUI rate from its state notice in its payroll workspace.
      </p>
    </WorkerDataLocked>
  );
}
