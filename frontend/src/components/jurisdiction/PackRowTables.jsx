import { Plus, Pencil, Trash2 } from "lucide-react";

// Presentational pieces shared by every Jurisdiction Compliance page: the
// Contribution Rates table, the Tax Slabs table and the header above each
// (description + locked-pack notice or Add button). RatesTab / SlabsTab wrap
// these for the generic canonical editor; a country with a governed editor
// (Belgium) feeds the same tables its own rows and edit handlers, so every
// country's rate and slab tables look the same. No value is computed here —
// cells show what the caller passes.

const th = "px-3 py-2";
const td = "px-3 py-2 text-foreground-secondary";
const iconBtn = "rounded p-1 text-foreground-disabled";
const iconBtnDisabled = " disabled:cursor-not-allowed disabled:opacity-40";

export function LockedPackNotice({ noun }) {
  return (
    <span className="rounded-lg border border-error/40 bg-error/5 px-3 py-1.5 text-xs font-medium text-error">
      Active pack — {noun} are locked. Use &quot;New Version&quot; to create an editable draft.
    </span>
  );
}

// `locked` shows the locked notice instead of the Add button; `onAdd` absent
// hides the button (a country whose rows are added elsewhere).
export function PackTableHeader({ description, locked, lockedNoun, addLabel, onAdd }) {
  return (
    <div className="flex items-center justify-between">
      <p className="text-xs text-foreground-muted">{description}</p>
      {locked ? (
        <LockedPackNotice noun={lockedNoun} />
      ) : onAdd ? (
        <button onClick={onAdd} disabled={locked} className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover disabled:opacity-50 disabled:hover:bg-primary">
          <Plus size={13} /> {addLabel}
        </button>
      ) : null}
    </div>
  );
}

function RowActions({ row, onEdit, onDelete, disabled }) {
  const extra = disabled ? iconBtnDisabled : "";
  return (
    <div className="flex items-center gap-1">
      {onEdit && (
        <button onClick={() => onEdit(row)} disabled={disabled} aria-label="Edit"
          className={`${iconBtn} hover:text-primary hover:bg-surface-muted${extra}`}><Pencil size={12} /></button>
      )}
      {onDelete && (
        <button onClick={() => onDelete(row)} disabled={disabled} aria-label="Delete"
          className={`${iconBtn} hover:text-error hover:bg-error-light${extra}`}><Trash2 size={12} /></button>
      )}
    </div>
  );
}

// columns: [{ key, label, render(row) }]. sections: [{ key, label, rows }] —
// when given, rows are grouped under a section heading inside one table.
function PackTable({ columns, rows, sections, onEdit, onDelete, actionsDisabled, emptyText }) {
  const groups = sections || [{ key: "all", label: null, rows: rows || [] }];
  const total = groups.reduce((n, g) => n + g.rows.length, 0);
  const hasActions = Boolean(onEdit || onDelete);
  const span = columns.length + (hasActions ? 1 : 0);
  if (total === 0) {
    return <p className="rounded-lg border border-dashed border-border-light px-3 py-8 text-center text-xs text-foreground-disabled">{emptyText}</p>;
  }
  return (
    <div className="overflow-x-auto rounded-xl border border-border">
      <table className="w-full text-xs">
        <thead className="bg-background text-left text-foreground-muted">
          <tr>{columns.map((c) => <th key={c.key} className={th}>{c.label}</th>)}{hasActions && <th className={`${th} w-16`}></th>}</tr>
        </thead>
        <tbody>
          {groups.map((group) => [
            group.label ? (
              <tr key={`section-${group.key}`} className="border-t border-border-light bg-surface-muted">
                <td colSpan={span} className="px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-foreground-muted">
                  {group.label}
                </td>
              </tr>
            ) : null,
            group.label && group.rows.length === 0 ? (
              <tr key={`empty-${group.key}`} className="border-t border-border-light">
                <td colSpan={span} className="px-3 py-2 text-foreground-disabled">No rows in this section.</td>
              </tr>
            ) : null,
            ...group.rows.map((row) => (
              <tr key={row.id} className="border-t border-border-light">
                {columns.map((c) => <td key={c.key} className={c.cellClass || td}>{c.render(row)}</td>)}
                {hasActions && (
                  <td className="px-3 py-2">
                    <RowActions row={row} onEdit={onEdit} onDelete={onDelete} disabled={actionsDisabled} />
                  </td>
                )}
              </tr>
            )),
          ])}
        </tbody>
      </table>
    </div>
  );
}

const pick = (columns, hideColumns, extraColumns) => [...columns.filter((c) => !hideColumns.includes(c.key)), ...extraColumns];
const defaultRateFormat = (value) => `${value}%`;

// Contribution Rates: Component (label + key) | State | Filing Status |
// Employee % | Employer % | Flat Amount. `formatRate` renders a stored
// rate value; `componentNote(row)` adds a line under the component key.
export function ContributionRatesTable({
  rows, sections, onEdit, onDelete, actionsDisabled = false, hideColumns = [], extraColumns = [],
  componentNote, formatRate = defaultRateFormat, emptyText = "No contribution rates yet.",
}) {
  const columns = [
    { key: "component", label: "Component", cellClass: "px-3 py-2", render: (r) => (
      <>
        <p className="font-semibold text-foreground">{r.label}</p>
        <p className="font-mono text-[10px] text-foreground-disabled">{r.componentKey}</p>
        {componentNote ? componentNote(r) : null}
      </>
    ) },
    { key: "state", label: "State", render: (r) => r.jurisdictionState || "—" },
    { key: "filingStatus", label: "Filing Status", render: (r) => r.filingStatus || "—" },
    { key: "employee", label: "Employee %", render: (r) => (r.employeeRatePct != null ? formatRate(r.employeeRatePct, r) : "—") },
    { key: "employer", label: "Employer %", render: (r) => (r.employerRatePct != null ? formatRate(r.employerRatePct, r) : "—") },
    { key: "flat", label: "Flat Amount", render: (r) => (r.flatAmount != null ? r.flatAmount : "—") },
  ];
  return (
    <PackTable columns={pick(columns, hideColumns, extraColumns)} rows={rows} sections={sections}
      onEdit={onEdit} onDelete={onDelete} actionsDisabled={actionsDisabled} emptyText={emptyText} />
  );
}

// Tax Slabs: Min | Max | Rate % | Label | State | Filing Status.
export function TaxSlabsTable({
  rows, sections, onEdit, onDelete, actionsDisabled = false, hideColumns = [], extraColumns = [],
  emptyText = "No tax slabs yet.",
}) {
  const columns = [
    { key: "min", label: "Min", render: (s) => s.minAmount ?? "—" },
    { key: "max", label: "Max", render: (s) => s.maxAmount ?? "and above" },
    { key: "rate", label: "Rate %", cellClass: "px-3 py-2 font-medium text-foreground", render: (s) => (s.ratePct != null ? `${s.ratePct}%` : "—") },
    { key: "label", label: "Label", render: (s) => s.rateLabel },
    { key: "state", label: "State", render: (s) => s.jurisdictionState || "—" },
    { key: "filingStatus", label: "Filing Status", render: (s) => s.filingStatus || "—" },
  ];
  return (
    <PackTable columns={pick(columns, hideColumns, extraColumns)} rows={rows} sections={sections}
      onEdit={onEdit} onDelete={onDelete} actionsDisabled={actionsDisabled} emptyText={emptyText} />
  );
}
