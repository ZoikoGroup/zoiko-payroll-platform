import { useEffect, useState } from "react";
import { getMxEmployeePtu } from "../../../service/payrollService";
import { Table } from "../../../components/jurisdiction/mexico/mxShared";
import { Badge, Panel } from "../../../components/jurisdiction/mexico/employer/employerShared";

// The worker's PTU by fiscal year (Phase 9d): qualifying days and salary from
// committed runs, the shares, the cap comparison, the final amount — or the
// exclusion with its reason. Cycles are run from the Compliance Centre.
export default function MXPtuPanel({ employeeId }) {
  const [rows, setRows] = useState(null);
  const [loadError, setLoadError] = useState(null);

  useEffect(() => {
    let active = true;
    getMxEmployeePtu(employeeId)
      .then((d) => { if (active) { setRows(d); setLoadError(null); } })
      .catch((e) => active && setLoadError(e?.message || "The PTU allocations could not be loaded."));
    return () => { active = false; };
  }, [employeeId]);

  return (
    <Panel title="PTU (profit sharing)" testId="mx-employee-ptu"
      hint="Allocated per fiscal year from committed runs by the transcribed rule; cycles are run from the Compliance Centre.">
      {loadError && <p className="text-[12px] text-error" role="alert">{loadError}</p>}
      {rows && (
        <Table rows={rows} rowKey={(r) => r.cycleId} empty="No PTU allocated yet." columns={[
          { key: "fiscalYear", label: "Fiscal year" },
          { key: "cycleStatus", label: "Cycle", render: (r) => <Badge value={r.cycleStatus} /> },
          { key: "qualifyingDays", label: "Days" },
          { key: "daysShare", label: "Days share" }, { key: "salaryShare", label: "Salary share" },
          { key: "finalAmount", label: "PTU" },
          { key: "excl", label: "Excluded", render: (r) => (r.eligible ? "—" : r.exclusionReason) },
        ]} />
      )}
    </Panel>
  );
}
