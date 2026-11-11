import { useState } from "react";
import EarningClassMatrix from "../EarningClassMatrix";
import { card } from "../japan/jpFormat";
import { Table } from "../japan/jpShared";
import { EditButton } from "../new_zealand/NZPackRowsTab";
import { SignedPill } from "../new_zealand/nzShared";
import PLRowEditor from "./PLRowEditor";
import { COMPONENTS, OBLIGATIONS, isEditablePack } from "./plContent";

// Earning classification: one base per obligation, never a universal "taxable
// gross". REVIEW blocks a live calculation while the amount is non-zero; a
// treatment changes — and is signed — only through the governed console.

export default function PLEarningClassTab({ pack, slabs, onReload }) {
  const [editing, setEditing] = useState(null);
  const editable = isEditablePack(pack);
  const rows = (slabs || []).filter((row) => row.ruleType === "PL_EARNING_CLASS")
    .sort((a, b) => OBLIGATIONS.indexOf(a.taxRegime) - OBLIGATIONS.indexOf(b.taxRegime)
      || COMPONENTS.indexOf(a.filingStatus) - COMPONENTS.indexOf(b.filingStatus));
  return (
    <div className="space-y-4">
      <EarningClassMatrix
        slabs={slabs}
        ruleType="PL_EARNING_CLASS"
        title="Earning classification (PIT / ZUS / health / funds / PPK / minimum wage)"
        description="Each obligation has its own base (spec Critical refinements). PPK and FEP follow the pension base; overtime, night supplement and seniority never count toward the minimum-wage test (PL-015)."
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
        <PLRowEditor kind="slab" row={editing} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); onReload?.(); }} />
      )}
    </div>
  );
}
