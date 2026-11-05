import { useState } from "react";
import { Pencil } from "lucide-react";
import { byKeys, card, rateValue } from "../japan/jpFormat";
import { Table } from "../japan/jpShared";
import NZRowEditor from "./NZRowEditor";
import { isEditablePack } from "./nzContent";
import { band } from "./nzForm";
import { SignedPill } from "./nzShared";

// One group of the New Zealand pack: its parameters and its tables. Values
// change only through "Edit / sign" (the governed console) on an editable
// pack version; an Active pack is read-only (create a new version to change it).

export function EditButton({ onClick, label = "Edit / sign" }) {
  return (
    <button type="button" onClick={onClick}
      className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 text-[11px] font-semibold text-foreground-secondary hover:bg-surface-muted">
      <Pencil size={11} /> {label}
    </button>
  );
}

export default function NZPackRowsTab({ title, description, pack, rates, slabs, keys = [], tables = [], onReload }) {
  const [editing, setEditing] = useState(null);
  const editable = isEditablePack(pack);
  const scalarRows = byKeys(rates, keys);
  const missing = keys.filter((key) => !scalarRows.some((row) => row.componentKey === key));
  const actions = (kind) => (editable
    ? [{ label: "", render: (row) => <EditButton onClick={() => setEditing({ kind, row })} /> }] : []);

  return (
    <div className="space-y-4" data-testid="nz-pack-rows">
      <div className={card}>
        <h3 className="mb-1 text-[14px] font-semibold text-foreground">{title}</h3>
        {description && <p className="mb-3 rounded-lg bg-surface-muted p-2 text-[12px] text-foreground-secondary">{description}</p>}
        {!editable && pack && (
          <p className="mb-3 text-[11px] text-foreground-muted">
            {pack.status} pack — read-only. Create a new version to change a value.
          </p>
        )}
        <Table rows={scalarRows} empty="No rows for this group in the selected pack."
          columns={[
            { label: "Parameter", render: (row) => String(row.label || "").replace("[PENDING G1]", "").trim() },
            { label: "Key", render: (row) => <span className="font-mono text-[11px] text-foreground-muted">{row.componentKey}</span> },
            { label: "Value", render: (row) => {
              const value = rateValue(row);
              return value === "—" || value === "PENDING_G1" ? <span className="text-warning">Not configured</span> : value;
            } },
            { label: "In force", render: (row) => (row.effectiveFrom ? `${row.effectiveFrom} → ${row.effectiveTo || "open"}` : "Pack window") },
            { label: "Status", render: (row) => <SignedPill row={row} /> },
            ...actions("rate"),
          ]} />
        {missing.length > 0 && <p className="mt-2 text-[11px] text-error">Missing from this pack: {missing.join(", ")}</p>}
      </div>
      {tables.map(({ ruleType, label, gate }) => {
        const rows = (slabs || []).filter((row) => row.ruleType === ruleType);
        return (
          <div key={ruleType} className={card} data-testid={`nz-table-${ruleType}`}>
            <h3 className="mb-1 text-[14px] font-semibold text-foreground">{label}</h3>
            <p className="mb-2 text-[11px] text-foreground-muted">
              <span className="font-mono">{ruleType}</span> · {rows.length} row{rows.length === 1 ? "" : "s"} · signed at {gate}
            </p>
            <Table rows={rows} empty={`Empty — signed at ${gate}; every calculation that needs it is blocked.`}
              columns={[
                { label: "Code / band", render: (row) => [row.filingStatus, row.taxRegime, row.taxColumn].filter(Boolean).join(" · ") || band(row) },
                { label: "Band", render: (row) => band(row) },
                { label: "Value", render: (row) => (row.ratePct != null && Number(row.ratePct) !== 0 ? `${row.ratePct}%` : row.assessmentBasis || row.flatAmount || "—") },
                { label: "Status", render: (row) => <SignedPill row={row} /> },
                ...actions("slab"),
              ]} />
          </div>
        );
      })}
      {editing && (
        <NZRowEditor kind={editing.kind} row={editing.row} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); onReload?.(); }} />
      )}
    </div>
  );
}
