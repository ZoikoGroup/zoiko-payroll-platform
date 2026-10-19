import WorkerDataLocked from "../../WorkerDataLocked";

// Loonaangifte (spec §13). ZP-PRIV decision 3: returns are the organization's
// own filings — building, reconciling, correcting, filing, Digipoort
// submission and authority payments are tenant actions run from the
// organization's payroll workspace (Reports → Loonaangifte). The Super Admin
// routes are retired, so this tab no longer calls them.
export default function NLLoonaangifteTab() {
  return (
    <WorkerDataLocked variant="tenant" title="Loonaangifte is filed by the organization">
      <p className="text-xs text-slate-500 dark:text-slate-400">
        Payroll-tax returns and their lines are built, reconciled, corrected and submitted by the organization.
        Platform readiness for the Netherlands is on the <b>Readiness G1–G8</b> tab.
      </p>
    </WorkerDataLocked>
  );
}
