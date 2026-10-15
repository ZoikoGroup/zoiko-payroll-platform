import { useState } from "react";
import { getNlPackRows } from "../../../service/superAdminService";
import { Messages, Field, Table, card, input, useLoad } from "./nlShared";

// Statutory pack content (minimum wage, WKR bands, car-addition windows, VCR
// period maxima) — READ-ONLY here. These rows change only through the
// governed pack editor (the Rates / Slabs tabs: draft -> review -> approve),
// never by a direct edit.
const KINDS = [
  ["minimum-wage", "Statutory minimum wage (hourly, by age)"],
  ["wkr-bands", "WKR free space and excess levy"],
  ["car-bands", "Company-car addition windows"],
  ["period-maxima", "VCR time-period maxima"],
];

function Section({ kind, title, on }) {
  const [data, error] = useLoad(() => getNlPackRows(kind, on), [kind, on]);
  return (
    <div className={card}>
      <h3 className="mb-2 text-[14px] font-semibold text-foreground">{title}</h3>
      <Messages error={error} />
      {data && !data.packId && <p className="text-[12px] text-foreground-muted">No Active Netherlands pack on this date.</p>}
      <Table rows={data?.rows} columns={[
        { key: "key", label: "Key" }, { key: "rate", label: "Rate %" }, { key: "amount", label: "Amount" },
        { key: "min", label: "From amount" }, { key: "max", label: "To amount" },
        { key: "effectiveFrom", label: "Valid from" }, { key: "effectiveTo", label: "Valid to" },
      ]} />
    </div>
  );
}

export default function NLPackRowsTab() {
  const [on, setOn] = useState(new Date().toISOString().slice(0, 10));
  return (
    <div className="flex flex-col gap-4">
      <div className={card}>
        <p className="mb-2 text-[12px] text-foreground-muted">
          Read-only view of the Active pack in force on the chosen date. To change a value, edit the pack in the
          Rates / Slabs tabs, where it goes through review and approval.
        </p>
        <Field label="Pack in force on"><input type="date" className={input} value={on} onChange={(e) => setOn(e.target.value)} /></Field>
      </div>
      {KINDS.map(([kind, title]) => <Section key={kind} kind={kind} title={title} on={on} />)}
    </div>
  );
}
