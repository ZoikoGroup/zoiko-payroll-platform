import { isPending, th, td } from "./zaFormat";

export function Table({ rows, columns, empty = "No rows configured.", rowKey = (row) => row.id }) {
  if (!rows || rows.length === 0) {
    return <p className="py-4 text-[12px] text-foreground-muted">{empty}</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full" aria-label="Statutory rows">
        <thead>
          <tr>
            {columns.map((column) => <th key={column.label} className={th}>{column.label}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={rowKey(row, index)} className="border-t border-border">
              {columns.map((column) => (
                <td key={column.label} className={td}>
                  {column.render ? column.render(row, index) : row[column.key] ?? "—"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PendingPill({ row }) {
  if (!isPending(row)) return <span className="text-[11px] text-foreground-muted">Configured</span>;
  return (
    <span className="inline-flex rounded border border-warning/40 bg-warning/10 px-1.5 py-0.5 text-[10px] font-semibold text-warning">
      PENDING G1
    </span>
  );
}
