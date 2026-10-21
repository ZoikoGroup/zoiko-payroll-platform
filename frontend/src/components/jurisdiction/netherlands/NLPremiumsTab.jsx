import WorkerDataLocked from "../../WorkerDataLocked";

// Employer premium decisions (Aof size class, Whk WGA / ZW-flex — NL-017).
// ZP-PRIV decision 3: an employer's own Belastingdienst premium decisions are
// tenant configuration. The organization records and activates them from its
// workspace (Payroll → Employer statutory → Netherlands); the Super Admin
// route is retired, so this tab no longer calls it.
export default function NLPremiumsTab() {
  return (
    <WorkerDataLocked variant="tenant" title="Premium decisions are recorded by the organization">
      <p className="text-xs text-slate-500 dark:text-slate-400">
        Aof size class and Whk WGA / ZW-flex decisions are entered and activated (four-eyes) by the organization&apos;s
        own admins from the Belastingdienst decision letter.
      </p>
    </WorkerDataLocked>
  );
}
