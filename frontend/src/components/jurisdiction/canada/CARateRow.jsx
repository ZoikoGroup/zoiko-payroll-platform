import { Pencil, Trash2 } from "lucide-react";

// Mirrors india/INComponentCard.jsx's role — the single-row display used
// by CARateGroupTab's list. Shows Employee/Employer % when either is
// set, otherwise the Flat Amount, never both — matches how a row's
// `shape` (see caComponentConfig.js) means only one of those was ever
// entered for it.
export default function CARateRow({ row, onEdit, onDelete }) {
  const isPct = row.employeeRatePct != null || row.employerRatePct != null;
  return (
    <div className="flex items-center justify-between rounded-lg border border-border-light p-3">
      <div>
        <p className="text-xs font-semibold text-foreground">{row.label}</p>
        <p className="font-mono text-[10px] text-foreground-disabled">{row.componentKey}</p>
      </div>
      <div className="flex items-center gap-3">
        <span className="font-mono text-xs tabular-nums text-foreground whitespace-nowrap">
          {isPct
            ? [
                row.employeeRatePct != null ? `Employee ${Number(row.employeeRatePct)}%` : null,
                row.employerRatePct != null ? `Employer ${Number(row.employerRatePct)}%` : null,
              ].filter(Boolean).join(" · ") || "—"
            : row.flatAmount != null ? `C$${Number(row.flatAmount).toLocaleString()}` : "—"}
        </span>
        <button onClick={() => onEdit(row)} className="rounded p-1 text-foreground-disabled hover:text-primary hover:bg-surface-muted"><Pencil size={12} /></button>
        <button onClick={() => onDelete(row)} className="rounded p-1 text-foreground-disabled hover:text-error hover:bg-error-light"><Trash2 size={12} /></button>
      </div>
    </div>
  );
}
