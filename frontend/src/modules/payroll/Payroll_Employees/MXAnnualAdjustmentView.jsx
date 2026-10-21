import { useEffect, useState } from "react";
import { getMxEmployeeAnnualAdjustments } from "../../../service/payrollService";
import { Table } from "../../../components/jurisdiction/mexico/mxShared";
import { Badge, Panel } from "../../../components/jurisdiction/mexico/employer/employerShared";

// The worker's annual ISR adjustments (Phase 9e): the year's inputs from
// committed runs, the annual ISR, the difference and where it was applied.
export default function MXAnnualAdjustmentView({ employeeId }) {
  const [rows, setRows] = useState(null);
  const [loadError, setLoadError] = useState(null);

  useEffect(() => {
    let active = true;
    getMxEmployeeAnnualAdjustments(employeeId)
      .then((d) => { if (active) { setRows(d); setLoadError(null); } })
      .catch((e) => active && setLoadError(e?.message || "The annual adjustments could not be loaded."));
    return () => { active = false; };
  }, [employeeId]);

  return (
    <Panel title="Annual ISR adjustment" testId="mx-employee-annual"
      hint="Computed per fiscal year from committed runs; applied in a later ordinary payslip.">
      {loadError && <p className="text-[12px] text-error" role="alert">{loadError}</p>}
      {rows && (
        <Table rows={rows} rowKey={(r) => r.id} empty="No annual adjustment yet." columns={[
          { key: "fiscalYear", label: "Fiscal year" },
          { key: "annualTaxable", label: "Annual taxable" }, { key: "withheldTotal", label: "Withheld" },
          { key: "annualIsr", label: "Annual ISR", render: (r) => r.annualIsr ?? "—" },
          { key: "difference", label: "Difference", render: (r) => r.difference ?? "—" },
          { key: "status", label: "Status", render: (r) => <Badge value={r.status} /> },
          { key: "carryForward", label: "Carry-forward", render: (r) => r.carryForward ?? "—" },
        ]} />
      )}
    </Panel>
  );
}
