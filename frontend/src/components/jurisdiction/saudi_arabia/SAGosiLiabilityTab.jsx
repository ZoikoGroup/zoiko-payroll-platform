import WorkerDataLocked from "../../WorkerDataLocked";

// ZP-PRIV decision 3: The monthly GOSI liability is one tenant's wages; the Super Admin routes behind this tab are
// retired, so it no longer calls them and only explains where the work is.
export function SAGosiLiabilityTab({ organizationCode }) {
  return (
    <WorkerDataLocked variant="tenant" title="GOSI liabilities are run by the organization" organizationCode={organizationCode}>
      <p className="text-xs text-slate-500 dark:text-slate-400">
        The monthly GOSI liability is built from the organization&apos;s committed payroll and marked paid by its own admins.
      </p>
    </WorkerDataLocked>
  );
}
