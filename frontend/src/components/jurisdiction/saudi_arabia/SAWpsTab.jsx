import WorkerDataLocked from "../../WorkerDataLocked";

// ZP-PRIV decision 3: WPS files are the tenant's filings; the Super Admin routes behind this tab are
// retired, so it no longer calls them and only explains where the work is.
export function SAWpsTab({ organizationCode }) {
  return (
    <WorkerDataLocked variant="tenant" title="WPS files are generated and filed by the organization" organizationCode={organizationCode}>
      <p className="text-xs text-slate-500 dark:text-slate-400">
        The WPS SIE extract, its observations and the bank accepted/rejected outcome are handled by the organization. Run preflight and fingerprints are worker-level and not available here.
      </p>
    </WorkerDataLocked>
  );
}
