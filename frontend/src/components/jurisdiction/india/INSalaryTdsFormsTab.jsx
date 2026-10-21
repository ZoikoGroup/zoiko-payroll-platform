import WorkerDataLocked from "../../WorkerDataLocked";

// India Salary TDS / Forms (ZP-TAX-IN-2026-27-001 §6.1-§6.3).
//
// ZP-PRIV: Forms 122 (declarations), 124 (claims) and 123/130/138 (generated
// certificates and statements) are per-employee tax records. The Super Admin
// cross-org endpoints are retired; the organization works with these from its
// own payroll workspace, and Zoiko staff need an organization-approved,
// time-limited Support Access grant to view them. This tab no longer calls
// the retired endpoints.
export default function INSalaryTdsFormsTab() {
  return (
    <WorkerDataLocked variant="support" title="Salary TDS declarations, claims and forms are worker-level data">
      <p className="text-xs text-slate-500 dark:text-slate-400">
        Forms 122, 124, 123, 130 and 138 are generated for and by each organization&apos;s employees.
      </p>
    </WorkerDataLocked>
  );
}
