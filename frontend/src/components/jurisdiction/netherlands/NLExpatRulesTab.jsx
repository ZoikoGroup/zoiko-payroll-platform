import WorkerDataLocked from "../../WorkerDataLocked";

// 30% facility decisions (NL-026). ZP-PRIV: a decision names one employee and
// is tenant-run statutory data (decision 3); the Super Admin employee list and
// expat-decision routes are retired, so this tab no longer calls them.
export default function NLExpatRulesTab() {
  return (
    <WorkerDataLocked variant="tenant" title="30% facility decisions are run by the organization">
      <p className="text-xs text-slate-500 dark:text-slate-400">
        Each decision belongs to one employee and is recorded, verified and revoked by the organization from its own
        payroll workspace.
      </p>
    </WorkerDataLocked>
  );
}
