import { useState } from "react";
import { getBrPackRows } from "../../../service/superAdminService";
import { Messages, Field, Table, card, input, useLoad, cell } from "./brShared";

// Read-only view of one statutory rule_type in the Active Brazil (CLT) pack in
// force on a chosen date — mirrors the Netherlands NLPackRowsTab's Section.
// The rows NEVER change here: they change only through the governed pack
// editor (the Rates / Slabs tabs: draft -> review -> approve).
export default function BRStatutorySectionTab({ ruleType, title, extraColumns = [] }) {
  const [on, setOn] = useState(new Date().toISOString().slice(0, 10));
  const [data, error] = useLoad(() => getBrPackRows(ruleType, on), [ruleType, on]);
  return (
    <div className="flex flex-col gap-4">
      <div className={card}>
        <p className="mb-2 text-[12px] text-foreground-muted">
          Read-only view of the Active Brazil pack in force on the chosen date. Changes only via the governed
          pack editor — the Rates / Slabs tabs, where a value goes through review and approval.
        </p>
        <Field label="Pack in force on">
          <input type="date" className={input} value={on} onChange={(e) => setOn(e.target.value)} />
        </Field>
      </div>
      <div className={card}>
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">{title}</h3>
        <Messages error={error} />
        {data && !data.packId && !Array.isArray(data) && (
          <p className="text-[12px] text-foreground-muted">No Active Brazil pack on this date.</p>
        )}
        <Table rows={data?.rows ?? data} empty="No statutory rows for this rule yet." columns={[
          { key: "key", label: "Key", render: cell("key", "code", "label") },
          { key: "rate", label: "Rate %", render: cell("rate", "ratePct", "rate_pct") },
          { key: "amount", label: "Amount (R$)", render: cell("amount", "flatAmount", "flat_amount") },
          { key: "min", label: "From amount", render: cell("min", "minAmount", "min_amount") },
          { key: "max", label: "To amount", render: cell("max", "maxAmount", "max_amount") },
          ...extraColumns,
          { key: "effectiveFrom", label: "Valid from", render: cell("effectiveFrom", "effective_from") },
          { key: "effectiveTo", label: "Valid to", render: cell("effectiveTo", "effective_to") },
        ]} />
      </div>
    </div>
  );
}
