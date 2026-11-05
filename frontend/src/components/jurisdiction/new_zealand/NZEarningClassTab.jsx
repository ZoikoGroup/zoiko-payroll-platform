import { useState } from "react";
import EarningClassMatrix from "../EarningClassMatrix";
import { card } from "../japan/jpFormat";
import { Table } from "../japan/jpShared";
import NZRowEditor from "./NZRowEditor";
import { COMPONENTS, OBLIGATIONS, isEditablePack } from "./nzContent";
import { EditButton } from "./NZPackRowsTab";
import { SignedPill } from "./nzShared";

// Earning classification: one base per obligation (no universal "taxable
// gross"). REVIEW blocks a live calculation (HOLIDAY_GROSS is recorded only);
// a treatment changes — and is signed — only through the governed console.

export default function NZEarningClassTab({ pack, slabs, onReload }) {
  const [editing, setEditing] = useState(null);
  const editable = isEditablePack(pack);
  const rows = (slabs || []).filter((row) => row.ruleType === "NZ_EARNING_CLASS")
    .sort((a, b) => OBLIGATIONS.indexOf(a.taxRegime) - OBLIGATIONS.indexOf(b.taxRegime)
      || COMPONENTS.indexOf(a.filingStatus) - COMPONENTS.indexOf(b.filingStatus));
  return (
    <div className="space-y-4">
      <EarningClassMatrix
        slabs={slabs}
        ruleType="NZ_EARNING_CLASS"
        title="Earning classification (PAYE / ACC / KiwiSaver / student loan / Holidays Act gross / minimum wage)"
        description="Each obligation has its own base. REVIEW blocks a live calculation until the component is classified with signed evidence; LUMP_SUM_PATH components are taxed by the extra-pay method."
        obligations={OBLIGATIONS}
        componentOrder={COMPONENTS}
      />
      <div className={card}>
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">Treatments</h3>
        <Table rows={rows} columns={[
          { label: "Obligation", render: (row) => row.taxRegime },
          { label: "Component", render: (row) => row.filingStatus },
          { label: "Treatment", render: (row) => row.assessmentBasis },
          { label: "Status", render: (row) => <SignedPill row={row} /> },
          ...(editable ? [{ label: "", render: (row) => <EditButton onClick={() => setEditing(row)} /> }] : []),
        ]} />
      </div>
      {editing && (
        <NZRowEditor kind="slab" row={editing} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); onReload?.(); }} />
      )}
    </div>
  );
}
