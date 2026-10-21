import WorkerDataLocked from "../../WorkerDataLocked";

// ZP-PRIV decision 3: Employer GOSI registration (ZP-SA-ENG-001 §7) is tenant configuration; the Super Admin routes behind this tab are
// retired, so it no longer calls them and only explains where the work is.
export function SAEmployerProfileTab({ organizationCode }) {
  return (
    <WorkerDataLocked variant="tenant" title="Employer GOSI registration is maintained by the organization" organizationCode={organizationCode}>
      <p className="text-xs text-slate-500 dark:text-slate-400">
        GOSI employer profiles are recorded and approved (four-eyes) by the organization from Payroll → Employer statutory → Saudi Arabia.
      </p>
    </WorkerDataLocked>
  );
}
