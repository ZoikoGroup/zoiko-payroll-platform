import WorkerDataLocked from "../../WorkerDataLocked";

// ZP-PRIV decision 3: Employee contract versions are tenant-run worker records; the Super Admin routes behind this tab are
// retired, so it no longer calls them and only explains where the work is.
export function SAContractVersionTab({ organizationCode }) {
  return (
    <WorkerDataLocked variant="tenant" title="Employee contracts are managed by the organization" organizationCode={organizationCode}>
      <p className="text-xs text-slate-500 dark:text-slate-400">
        Contract versions belong to individual employees and are recorded and approved by the organization in its own payroll workspace.
      </p>
    </WorkerDataLocked>
  );
}
