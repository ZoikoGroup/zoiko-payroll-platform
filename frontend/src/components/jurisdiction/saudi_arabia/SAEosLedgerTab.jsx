import WorkerDataLocked from "../../WorkerDataLocked";

// ZP-PRIV decision 3: The EOS accrual ledger is tenant-run statutory data; the Super Admin routes behind this tab are
// retired, so it no longer calls them and only explains where the work is.
export function SAEosLedgerTab({ organizationCode }) {
  return (
    <WorkerDataLocked variant="tenant" title="The EOS ledger is run by the organization" organizationCode={organizationCode}>
      <p className="text-xs text-slate-500 dark:text-slate-400">
        End-of-service accruals are posted from the organization&apos;s committed payroll runs in its own workspace.
      </p>
    </WorkerDataLocked>
  );
}
