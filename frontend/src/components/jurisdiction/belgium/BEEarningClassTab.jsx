import { useState } from "react";
import EarningClassMatrix from "../EarningClassMatrix";
import { card, useLoad } from "../japan/jpFormat";
import { Table } from "../japan/jpShared";
import { EditButton } from "../new_zealand/NZPackRowsTab";
import { ErrorNote, SignedPill } from "../new_zealand/nzShared";
import BEPackRowsTab from "./BEPackRowsTab";
import BERowEditor from "./BERowEditor";
import { TAB_GROUPS, isEditablePack, loadConfiguration } from "./beShared";

// Earning classification (BE-006 / BE-007): one independent base per
// obligation, never a universal "taxable gross". Obligations, components,
// treatments and the rule type come from the configuration API; REVIEW blocks a
// live calculation while the amount is non-zero. Treatments change — and are
// signed — only through the governed console.

function Matrix({ pack }) {
  const [config, error, , reload] = useLoad(() => loadConfiguration(pack));
  const [editing, setEditing] = useState(null);
  if (error) return <ErrorNote message={error} />;
  if (!config) return <p className="text-[12px] text-foreground-muted">Loading…</p>;
  const meta = config.earningClass;
  // The shared matrix reads ruleType / taxRegime / filingStatus / assessmentBasis.
  const slabs = (config.earningClasses || []).map((row) => ({ ...row, taxRegime: row.obligation,
    filingStatus: row.component, assessmentBasis: row.treatment }));
  const editable = isEditablePack(pack);
  return (
    <div className="space-y-4">
      <EarningClassMatrix slabs={slabs} ruleType={meta.ruleType}
        title="Earning classification (independent statutory bases, BE-006 / BE-007)"
        description="Each obligation has its own base. REVIEW blocks the calculation while the component is non-zero; a treatment is signed by a Belgian payroll specialist (gate G1)."
        obligations={meta.obligations} componentOrder={meta.components} />
      <div className={card}>
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">Treatments</h3>
        <Table rows={config.earningClasses || []} columns={[
          { label: "Obligation", render: (row) => row.obligation },
          { label: "Component", render: (row) => row.component },
          { label: "Treatment", render: (row) => row.treatment },
          { label: "Status", render: (row) => <SignedPill row={row} /> },
          ...(editable ? [{ label: "", render: (row) => <EditButton onClick={() => setEditing(row)} /> }] : []),
        ]} />
      </div>
      {editing && (
        <BERowEditor kind="slab" row={editing} config={config} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); reload(); }} />
      )}
    </div>
  );
}

export default function BEEarningClassTab({ pack }) {
  if (!pack) return <p className="text-[12px] text-foreground-muted">Select a Belgium pack.</p>;
  return (
    <div className="space-y-4">
      <Matrix key={pack.id} pack={pack} />
      <BEPackRowsTab pack={pack} groups={TAB_GROUPS.earningClass} />
    </div>
  );
}
