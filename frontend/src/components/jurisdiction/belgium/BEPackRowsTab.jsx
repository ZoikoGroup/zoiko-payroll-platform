import { useState } from "react";
import { card, useLoad } from "../japan/jpFormat";
import { Table } from "../japan/jpShared";
import { EditButton } from "../new_zealand/NZPackRowsTab";
import { ErrorNote, SignedPill } from "../new_zealand/nzShared";
import BERowEditor from "./BERowEditor";
import BESlabRowsSection from "./BESlabRowsSection";
import { cleanLabel, displayValue, isEditablePack, loadConfiguration } from "./beShared";

// One console tab of the Belgium pack: the rows of its catalogue groups, read
// from the configuration API (labels, kinds, references, vocabularies and the
// reference-only notes all come from the backend). Values change only through
// "Edit / sign" on an editable pack version; an Active pack is read-only.
// ONSS employer rows are REFERENCE ONLY: each shows the backend referenceNote,
// and the console never combines rows into one all-in employer rate.

function GroupRows({ pack, config, group, onReload }) {
  const [editing, setEditing] = useState(null);
  const editable = isEditablePack(pack);
  const section = config.groups?.[group];
  if (!section) return null;
  const slabKeys = section.rows.filter((row) => config.slabSpecs?.[row.componentKey]).map((row) => row.componentKey);
  const notSupported = (row) => row.textValue && row.textValue === config.vocabulary?.[row.componentKey]?.notSupported;
  return (
    <div className="space-y-3">
      <div className={card} data-testid={`be-group-${group}`}>
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">{section.label}</h3>
        <Table rows={section.rows} empty="No rows for this group in the selected pack."
          columns={[
            { label: "Parameter", render: (row) => (
              <div>
                <div>{cleanLabel(row.label)}</div>
                {row.referenceOnly && (
                  <div className="mt-1 text-[11px] text-warning" data-testid="be-reference-note">{row.referenceNote}</div>
                )}
              </div>
            ) },
            { label: "Key", render: (row) => <span className="font-mono text-[11px] text-foreground-muted">{row.componentKey}</span> },
            { label: "Kind", render: (row) => row.valueKind },
            { label: "Spec", render: (row) => <span className="text-[11px] text-foreground-muted">{row.specReference}</span> },
            { label: "Value", render: (row) => {
              if (notSupported(row)) return <span className="text-foreground-muted">Not supported (blocked)</span>;
              const value = displayValue(row);
              return value ? value : <span className="text-warning">Not configured</span>;
            } },
            { label: "In force", render: (row) => (row.effectiveFrom ? `${row.effectiveFrom} → ${row.effectiveTo || "open"}` : "Pack window") },
            { label: "Status", render: (row) => <SignedPill row={row} /> },
            ...(editable ? [{ label: "", render: (row) => <EditButton onClick={() => setEditing(row)} /> }] : []),
          ]} />
      </div>
      {slabKeys.map((key) => {
        const row = section.rows.find((r) => r.componentKey === key);
        return <BESlabRowsSection key={key} pack={pack} config={config} rowKey={key} title={cleanLabel(row?.label)} onReload={onReload} />;
      })}
      {editing && (
        <BERowEditor kind="rate" row={editing} config={config} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); onReload(); }} />
      )}
    </div>
  );
}

function Loaded({ pack, groups, title, description }) {
  const [config, error, loading, reload] = useLoad(() => loadConfiguration(pack));
  if (loading && !config) return <p className="text-[12px] text-foreground-muted">Loading…</p>;
  if (error) return <ErrorNote message={error} />;
  if (!config) return null;
  return (
    <div className="space-y-4" data-testid="be-pack-rows">
      {(title || description) && (
        <div className={card}>
          {title && <h3 className="mb-1 text-[14px] font-semibold text-foreground">{title}</h3>}
          {description && <p className="text-[12px] text-foreground-secondary">{description}</p>}
          {!isEditablePack(pack) && (
            <p className="mt-2 text-[11px] text-foreground-muted">{pack.status} pack — read-only. Create a new version to change a value.</p>
          )}
        </div>
      )}
      {groups.map((group) => <GroupRows key={group} pack={pack} config={config} group={group} onReload={reload} />)}
    </div>
  );
}

export default function BEPackRowsTab({ pack, groups, title, description }) {
  if (!pack) return <p className="text-[12px] text-foreground-muted">Select a Belgium pack.</p>;
  return <Loaded key={pack.id} pack={pack} groups={groups} title={title} description={description} />;
}
