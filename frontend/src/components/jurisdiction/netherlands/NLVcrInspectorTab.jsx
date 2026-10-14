import { useState } from "react";
import { getNlVcr, listNlEmployees } from "../../../service/superAdminService";
import { NeedOrg, Messages, Field, Table, card, input, useLoad, yesNo } from "./nlShared";

// Read-only view of the committed VCR series (NL-012): one row per committed
// revision; corrections are appended revisions, never edits.
const FAMILIES = [["EI", "Employee insurance (AWf / Aof / Wko / Whk)"], ["ZVW_LEVY", "Zvw employer levy"], ["ZVW_CONTRIB", "Zvw employee contribution"]];

export default function NLVcrInspectorTab({ orgId }) {
  const [employees, empError] = useLoad(() => (orgId ? listNlEmployees(orgId) : Promise.resolve([])), [orgId]);
  const [employeeId, setEmployeeId] = useState("");
  const [taxYear, setTaxYear] = useState(new Date().getFullYear());
  const [vcr, vcrError] = useLoad(() => (orgId && employeeId ? getNlVcr(orgId, employeeId, taxYear) : Promise.resolve(null)),
    [orgId, employeeId, taxYear]);
  if (!orgId) return <NeedOrg />;
  return (
    <div className="flex flex-col gap-4">
      <Messages error={empError || vcrError} />
      <div className={`${card} flex gap-4`}>
        <Field label="Employee">
          <select className={input} value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}>
            <option value="">—</option>
            {(employees || []).map((e) => <option key={e.id} value={e.id}>{e.name} ({e.employee_code})</option>)}
          </select>
        </Field>
        <Field label="Tax year"><input type="number" className={input} value={taxYear} onChange={(e) => setTaxYear(e.target.value)} /></Field>
      </div>
      {vcr && FAMILIES.map(([fam, title]) => (
        <div key={fam} className={card}>
          <h3 className="mb-2 text-[14px] font-semibold text-foreground">{title}</h3>
          <Table rows={vcr[fam]} empty="No committed revision yet." columns={[
            { key: "revision", label: "Rev" }, { key: "period_count", label: "Periods" },
            { key: "cumulative_wage", label: "Cum. wage" }, { key: "cumulative_max", label: "Cum. max" },
            { key: "cumulative_base", label: "Cum. base" }, { key: "base_increment", label: "Increment" },
            { key: "payroll_run_id", label: "Run" }, { key: "is_correction", label: "Correction", render: (r) => yesNo(r.is_correction) },
          ]} />
        </div>
      ))}
    </div>
  );
}
