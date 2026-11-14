import { useState } from "react";
import { card } from "../japan/jpFormat";
import { Table } from "../japan/jpShared";
import { EditButton } from "../new_zealand/NZPackRowsTab";
import { ErrorNote, SignedPill } from "../new_zealand/nzShared";
import MYRowEditor, { useMyConfiguration } from "./MYRowEditor";
import { GROUPS, SCHEDULES, TERRITORIES, TERRITORY_KEYS, band, cleanLabel, isEditablePack, territoryKey, valueOf } from "./myContent";

// Malaysia statutory content tabs (ZP-MY-ENG-001 Phase 8a). Every tab reads
// the console's own configuration (national + territorial parameters,
// schedules, holidays, earning classes). Values change only through
// "Edit / sign" on an editable (Draft) pack or through the workbook; an Active
// pack is read-only.

function Value({ row }) {
  const value = valueOf(row);
  if (!value || value === "PENDING_G1") return <span className="text-warning">Not configured</span>;
  if (value === "NOT_SUPPORTED") return <span className="text-foreground-muted">Not supported (blocked)</span>;
  return <span>{value}</span>;
}

function Shell({ pack, title, description, error, children, testId }) {
  return (
    <div className={card} data-testid={testId}>
      <h3 className="mb-1 text-[14px] font-semibold text-foreground">{title}</h3>
      {description && <p className="mb-3 rounded-lg bg-surface-muted p-2 text-[12px] text-foreground-secondary">{description}</p>}
      {pack && !isEditablePack(pack) && (
        <p className="mb-3 text-[11px] text-foreground-muted">{pack.status} pack — read-only. Create a new version to change a value.</p>
      )}
      <ErrorNote message={error} />
      {children}
    </div>
  );
}

function useEditor(reload) {
  const [editing, setEditing] = useState(null);
  const editor = editing && (
    <MYRowEditor kind={editing.kind} row={editing.row} onClose={() => setEditing(null)}
      onSaved={() => { setEditing(null); reload(); }} />
  );
  return [setEditing, editor];
}

export function MYParametersTab({ pack, group }) {
  const [config, error, reload] = useMyConfiguration(pack);
  const [edit, editor] = useEditor(reload);
  const { title, description, keys } = GROUPS[group];
  const map = new Map((config?.rates || []).map((r) => [r.componentKey, r]));
  const rows = keys.map((k) => map.get(k)).filter(Boolean);
  const missing = config ? keys.filter((k) => !map.has(k)) : [];
  const editable = isEditablePack(pack);
  return (
    <Shell pack={pack} title={title} description={description} error={error} testId="my-parameters">
      <Table rows={rows} empty={config ? "No rows for this group." : "Loading…"} columns={[
        { label: "Parameter", render: (row) => cleanLabel(row) },
        { label: "Key", render: (row) => <span className="font-mono text-[11px] text-foreground-muted">{row.componentKey}</span> },
        { label: "Value", render: (row) => <Value row={row} /> },
        { label: "Basis", render: (row) => row.dateBasis || "—" },
        { label: "In force", render: (row) => (row.effectiveFrom ? `${row.effectiveFrom} → ${row.effectiveTo || "open"}` : "Pack window") },
        { label: "Status", render: (row) => <SignedPill row={row} /> },
        ...(editable ? [{ label: "", render: (row) => <EditButton onClick={() => edit({ kind: "rate", row })} /> }] : []),
      ]} />
      {missing.length > 0 && <p className="mt-2 text-[11px] text-error">Missing from this pack: {missing.join(", ")}</p>}
      {editor}
    </Shell>
  );
}

export function MYTerritoryTab({ pack }) {
  const [config, error, reload] = useMyConfiguration(pack);
  const [edit, editor] = useEditor(reload);
  const map = new Map((config?.rates || []).map((r) => [r.componentKey, r]));
  const editable = isEditablePack(pack);
  return (
    <Shell pack={pack} title="Labour law by territory" error={error} testId="my-territory-matrix"
      description="Peninsular Malaysia + Labuan, Sabah and Sarawak each have their own labour framework (MY-024). A worker's territory comes only from the approved work assignment; a missing or unsigned value blocks the LABOUR obligation.">
      <div className="overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead>
            <tr>
              <th className="px-2 py-1.5 text-left text-[11px] font-semibold uppercase text-foreground-muted">Rule</th>
              {TERRITORIES.map((t) => <th key={t.code} className="px-2 py-1.5 text-left text-[11px] font-semibold uppercase text-foreground-muted">{t.label}</th>)}
            </tr>
          </thead>
          <tbody>
            {TERRITORY_KEYS.map(([base, label]) => (
              <tr key={base} className="border-t border-border">
                <td className="px-2 py-1.5 text-foreground">{label}<span className="block font-mono text-[10px] text-foreground-muted">{base}</span></td>
                {TERRITORIES.map((t) => {
                  const row = map.get(territoryKey(base, t));
                  return (
                    <td key={t.code} className="px-2 py-1.5 align-top">
                      {row ? (
                        <div className="space-y-1">
                          <Value row={row} />
                          <div className="flex items-center gap-1"><SignedPill row={row} />
                            {editable && <EditButton label="Edit" onClick={() => edit({ kind: "rate", row })} />}</div>
                        </div>
                      ) : <span className="text-error">missing</span>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {editor}
    </Shell>
  );
}

export function MYTablesTab({ pack }) {
  const [config, error, reload] = useMyConfiguration(pack);
  const [edit, editor] = useEditor(reload);
  const [rule, setRule] = useState(SCHEDULES[0][0]);
  const editable = isEditablePack(pack);
  const rows = config?.schedules?.[rule] || [];
  return (
    <div className="space-y-4">
      <Shell pack={pack} title="Contribution schedules" error={error} testId="my-schedules"
        description="Contributions are read from these schedule rows — never computed from a percentage (MY-005 / MY-011). Load whole tables with the statutory workbook (Import & verify); each row then needs signing.">
        <div className="mb-3 flex flex-wrap gap-2">
          {SCHEDULES.map(([code, label]) => (
            <button key={code} type="button" onClick={() => setRule(code)}
              className={`rounded-lg border px-3 py-1 text-[12px] font-semibold ${rule === code ? "border-primary bg-primary/10 text-primary" : "border-border text-foreground-secondary"}`}>
              {label} ({(config?.schedules?.[code] || []).length})
            </button>
          ))}
        </div>
        <Table rows={rows} empty="No rows yet — this schedule blocks its obligation until it is loaded and signed." columns={[
          { label: "Class", render: (row) => row.memberClass },
          { label: "Side", render: (row) => row.side },
          { label: "Wage band (RM)", render: (row) => band(row) },
          { label: "Amount (RM)", render: (row) => row.flatAmount ?? "—" },
          { label: "Status", render: (row) => <SignedPill row={row} /> },
          ...(editable ? [{ label: "", render: (row) => <EditButton onClick={() => edit({ kind: "slab", row })} /> }] : []),
        ]} />
      </Shell>
      <Shell pack={pack} title="Public holidays (federal + state)" testId="my-holidays"
        description="A worker's calendar is the national rows plus the rows of their work assignment's holiday state. Loaded with the workbook; never a guessed list.">
        <Table rows={config?.holidays || []} empty="No holidays loaded — public-holiday overtime stays blocked." columns={[
          { label: "Date", render: (row) => String(row.detail || "").split(" ")[0] },
          { label: "Holiday", render: (row) => cleanLabel({ label: row.label }) },
          { label: "State", render: (row) => row.state || "National" },
          { label: "Status", render: (row) => <SignedPill row={row} /> },
        ]} />
      </Shell>
      {editor}
    </div>
  );
}

export function MYEarningClassTab({ pack }) {
  const [config, error, reload] = useMyConfiguration(pack);
  const [edit, editor] = useEditor(reload);
  const editable = isEditablePack(pack);
  const rows = [...(config?.earningClasses || [])].sort((a, b) =>
    String(a.obligation).localeCompare(String(b.obligation)) || String(a.component).localeCompare(String(b.component)));
  return (
    <Shell pack={pack} title="Earning classification" error={error} testId="my-earning-classes"
      description="Each pay component is classified for every obligation separately (PCB normal / additional, EPF, SOCSO, EIS, HRD, minimum-wage basic, overtime-rate base). REVIEW blocks that obligation only when the component has a non-zero amount.">
      <Table rows={rows} empty={config ? "No classification rows." : "Loading…"} columns={[
        { label: "Obligation", render: (row) => row.obligation },
        { label: "Component", render: (row) => row.component },
        { label: "Treatment", render: (row) => <span className={row.treatment === "REVIEW" ? "text-warning" : ""}>{row.treatment}</span> },
        { label: "Basis", render: (row) => cleanLabel({ label: row.label }) },
        { label: "Status", render: (row) => <SignedPill row={row} /> },
        ...(editable ? [{ label: "", render: (row) => <EditButton onClick={() => edit({ kind: "slab", row })} /> }] : []),
      ]} />
      {editor}
    </Shell>
  );
}
