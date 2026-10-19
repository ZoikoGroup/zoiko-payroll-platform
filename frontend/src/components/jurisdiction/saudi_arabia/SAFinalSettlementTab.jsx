import WorkerDataLocked from "../../WorkerDataLocked";

// ZP-PRIV decision 3: Final settlements are tenant-run statutory data; the Super Admin routes behind this tab are
// retired, so it no longer calls them and only explains where the work is.
export function SAFinalSettlementTab({ organizationCode }) {
  return (
    <WorkerDataLocked variant="tenant" title="Final settlements are run by the organization" organizationCode={organizationCode}>
      <p className="text-xs text-slate-500 dark:text-slate-400">
        Final settlements are created, approved and paid by the organization for its own leavers.
      </p>
    </WorkerDataLocked>
  );
}
