import { useState } from "react";
import { byKeys, card, rateValue } from "../japan/jpFormat";
import { Table } from "../japan/jpShared";
import { EditButton } from "../new_zealand/NZPackRowsTab";
import { SignedPill } from "../new_zealand/nzShared";
import PLRowEditor from "./PLRowEditor";
import { band, isEditablePack } from "./plContent";

// One group of the Poland pack: its parameters (and the PIT scale on the PIT
// tab). Values change only through "Edit / sign" on an editable pack version;
// an Active pack is read-only (create a new version to change it).

export default function PLPackRowsTab({ title, description, pack, rates, slabs, keys = [], pitBands = false, onReload }) {
  const [editing, setEditing] = useState(null);
  const editable = isEditablePack(pack);
  const rows = byKeys(rates, keys);
  const missing = keys.filter((key) => !rows.some((row) => row.componentKey === key));
  const actions = (kind) => (editable
    ? [{ label: "", render: (row) => <EditButton onClick={() => setEditing({ kind, row })} /> }] : []);
  const bands = (slabs || []).filter((row) => row.ruleType === "PL_PIT_BAND");

  return (
    <div className="space-y-4" data-testid="pl-pack-rows">
      <div className={card}>
        <h3 className="mb-1 text-[14px] font-semibold text-foreground">{title}</h3>
        {description && <p className="mb-3 rounded-lg bg-surface-muted p-2 text-[12px] text-foreground-secondary">{description}</p>}
        {!editable && pack && (
          <p className="mb-3 text-[11px] text-foreground-muted">{pack.status} pack — read-only. Create a new version to change a value.</p>
        )}
        <Table rows={rows} empty="No rows for this group in the selected pack."
          columns={[
            { label: "Parameter", render: (row) => String(row.label || "").replace("[PENDING G1]", "").trim() },
            { label: "Key", render: (row) => <span className="font-mono text-[11px] text-foreground-muted">{row.componentKey}</span> },
            { label: "Value", render: (row) => {
              const value = rateValue(row);
              if (value === "—" || value === "PENDING_G1") return <span className="text-warning">Not configured</span>;
              if (value === "NOT_SUPPORTED") return <span className="text-foreground-muted">Not supported (blocked)</span>;
              return value;
            } },
            { label: "In force", render: (row) => (row.effectiveFrom ? `${row.effectiveFrom} → ${row.effectiveTo || "open"}` : "Pack window") },
            { label: "Status", render: (row) => <SignedPill row={row} /> },
            ...actions("rate"),
          ]} />
        {missing.length > 0 && <p className="mt-2 text-[11px] text-error">Missing from this pack: {missing.join(", ")}</p>}
      </div>
      {pitBands && (
        <div className={card} data-testid="pl-pit-bands">
          <h3 className="mb-1 text-[14px] font-semibold text-foreground">PIT scale (annual taxable income)</h3>
          <p className="mb-2 text-[11px] text-foreground-muted">
            Published bases: the top band's base already nets the annual tax-reducing amount (applied monthly via PIT-2).
          </p>
          <Table rows={bands} empty="No PIT scale in this pack — every calculation is blocked."
            columns={[
              { label: "Band", render: (row) => band(row) },
              { label: "Rate", render: (row) => `${Number(row.ratePct)}%` },
              { label: "Published base", render: (row) => row.flatAmount ?? "—" },
              { label: "Status", render: (row) => <SignedPill row={row} /> },
              ...actions("slab"),
            ]} />
        </div>
      )}
      {editing && (
        <PLRowEditor kind={editing.kind} row={editing.row} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); onReload?.(); }} />
      )}
    </div>
  );
}
