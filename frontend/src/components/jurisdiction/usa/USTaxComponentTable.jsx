import { Pencil, Trash2 } from "lucide-react";
import { classifyContributionRate, UI_TYPES } from "./usaComponentConfig";
import StatusPill from "../../StatusPill";
import { STATUS_PILL_MAP } from "../constants";

// USA-only compact presentation of the pack's Contribution Rate rows — one
// table row per `rate`, replacing the old stacked USAComponentCard list.
// Which columns actually show a value is resolved per-row via the existing
// classifyContributionRate classification, so a percentage component only
// shows its percentages, a wage-base component only shows its amount, etc.
// `packStatus` is optional: rate rows carry no per-row status or timestamp
// (the API shape has none), so "Status" reflects the owning pack's status
// and "Last Updated" renders "—" when absent — we never fabricate data.
export default function USTaxComponentTable({ rates, packStatus, onEdit, onDelete }) {
  if (!rates || rates.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-surface-muted py-10 text-center text-xs text-foreground-disabled">
        No contribution components configured yet.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-xs">
          <thead>
            <tr className="border-b border-border-light text-left text-[11px] font-semibold uppercase tracking-wider text-foreground-muted">
              <th className="px-3 py-2.5">Component</th>
              <th className="px-3 py-2.5">Type</th>
              <th className="px-3 py-2.5 text-right">Employee %</th>
              <th className="px-3 py-2.5 text-right">Employer %</th>
              <th className="px-3 py-2.5 text-right">Wage Base / Threshold</th>
              <th className="px-3 py-2.5">Applies To</th>
              <th className="px-3 py-2.5">Status</th>
              <th className="px-3 py-2.5">Last Updated</th>
              <th className="px-3 py-2.5 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rates.map((r) => {
              const desc = classifyContributionRate(r);
              return (
                <tr
                  key={r.id ?? `${r.componentKey}-${r.filingStatus || ""}`}
                  className="border-b border-border-light last:border-0 hover:bg-surface-muted"
                >
                  <td className="px-3 py-2.5">
                    <div className="font-semibold text-foreground">{r.label || r.componentKey || "—"}</div>
                    {r.componentKey && (
                      <div className="font-mono text-[10px] text-foreground-disabled">{r.componentKey}</div>
                    )}
                  </td>
                  <td className="px-3 py-2.5">
                    <TypeBadge uiType={desc.uiType} />
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums">
                    {r.employeeRatePct != null ? `${r.employeeRatePct}%` : "—"}
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums">
                    {r.employerRatePct != null ? `${r.employerRatePct}%` : "—"}
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums">
                    {desc.flatAmount && r.flatAmount != null ? r.flatAmount : "—"}
                  </td>
                  <td className="px-3 py-2.5">
                    <AppliesTo row={r} desc={desc} />
                  </td>
                  <td className="px-3 py-2.5">
                    <StatusPill status={STATUS_PILL_MAP[packStatus] || "pending"} label={packStatus || "—"} />
                  </td>
                  <td className="px-3 py-2.5 text-foreground-muted">{"—"}</td>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center justify-end gap-1">
                      <button
                        onClick={() => onEdit(r)}
                        title="Edit"
                        className="rounded-md p-1.5 text-foreground-muted hover:bg-surface hover:text-foreground"
                      >
                        <Pencil size={13} />
                      </button>
                      <button
                        onClick={() => onDelete(r)}
                        title="Delete"
                        className="rounded-md p-1.5 text-error hover:bg-error-light"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TypeBadge({ uiType }) {
  const label = {
    [UI_TYPES.PERCENTAGE]: "Percentage",
    [UI_TYPES.EMPLOYEE_EMPLOYER_PERCENTAGE]: "Employee + Employer",
    [UI_TYPES.EMPLOYER_ASSIGNED_RATE]: "Employer Rate",
    [UI_TYPES.WAGE_BASE]: "Wage Base",
    [UI_TYPES.THRESHOLD]: "Threshold",
    [UI_TYPES.FIXED_AMOUNT]: "Fixed",
    [UI_TYPES.DEDUCTION_AMOUNT]: "Deduction",
    [UI_TYPES.INCOME_TAX_POINTER]: "Income Tax",
  }[uiType] || "—";
  return (
    <span className="inline-flex rounded-md bg-surface-muted px-2 py-0.5 text-[11px] font-medium text-foreground-secondary">
      {label}
    </span>
  );
}

function AppliesTo({ row, desc }) {
  if (desc.pointer) {
    return <span className="text-foreground-disabled">via Brackets</span>;
  }
  if (row.filingStatus) return <span>{row.filingStatus}</span>;
  if (row.jurisdictionState) return <span>{row.jurisdictionState}</span>;
  return <span className="text-foreground-disabled">Any</span>;
}
