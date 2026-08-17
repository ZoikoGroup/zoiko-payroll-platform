import React, { useState, useMemo } from "react";
import { Users } from "lucide-react";

const DEPARTMENT_STYLES = {
  Engineering: "bg-info/10 text-info",
  Sales: "bg-primary/10 text-primary",
  Marketing: "bg-category-teal/10 text-category-teal",
  HR: "bg-error/10 text-error",
  Finance: "bg-warning/10 text-warning",
};

function DepartmentBadge({ dept }) {
  const style = DEPARTMENT_STYLES[dept] || "bg-foreground-muted/10 text-foreground-muted";
  return (
    <span className={`inline-flex items-center rounded-full px-3 py-1 text-[11px] font-bold ${style}`}>
      {dept}
    </span>
  );
}

const STATUS_STYLES = {
  Active: "bg-primary/10 text-primary",
  "On Leave": "bg-warning/10 text-warning",
  Inactive: "bg-error/10 text-error",
};

function StatusBadge({ status }) {
  const style = STATUS_STYLES[status] || STATUS_STYLES.Inactive;
  return (
    <span className={`inline-flex items-center rounded-full px-3 py-1 text-[11px] font-bold ${style}`}>
      {status}
    </span>
  );
}

function formatCurrency(value, info) {
  if (value === null || value === undefined) return "—";
  if (!info) return value;
  try {
    return new Intl.NumberFormat(info.locale, {
      style: "currency",
      currency: info.code,
      maximumFractionDigits: 0,
    }).format(value);
  } catch {
    return `${info.symbol}${value}`;
  }
}

const COLUMNS = [
  { key: "employeeCode", label: "ID" },
  { key: "name", label: "Name" },
  { key: "department", label: "Department" },
  { key: "designation", label: "Designation" },
  { key: "ctc", label: "Annual CTC" },
  { key: "status", label: "Status" },
];

export default function EmployeeTable({ employees, loading, onRowClick, selectedEmployeeId, selectedIds, onSelectionChange, currencyInfo }) {
  const [sortKey, setSortKey] = useState("name");
  const [sortDir, setSortDir] = useState("asc");

  function extractNumericCode(val) {
    if (!val) return 0;
    const match = String(val).match(/(\d+)$/);
    return match ? parseInt(match[1], 10) : 0;
  }

  function initials(name) {
    if (!name) return "";
    const parts = name.trim().split(/\s+/);
    return parts.length > 1 ? `${parts[0][0]}${parts[parts.length - 1][0]}` : parts[0].slice(0, 2);
  }

  const sorted = useMemo(() => {
    const rows = [...(employees || [])];
    rows.sort((a, b) => {
      const aVal = sortKey === "name" ? a.name : a[sortKey];
      const bVal = sortKey === "name" ? b.name : b[sortKey];
      if (aVal === bVal) return 0;
      if (sortKey === "employeeCode") {
        const aNum = extractNumericCode(aVal);
        const bNum = extractNumericCode(bVal);
        if (aNum !== bNum) return sortDir === "asc" ? aNum - bNum : bNum - aNum;
      }
      const result = aVal > bVal ? 1 : -1;
      return sortDir === "asc" ? result : -result;
    });
    return rows;
  }, [employees, sortKey, sortDir]);

  function toggleSort(key) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  if (loading) {
    return (
      <div className="bg-surface border border-border rounded-[18px] overflow-hidden shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
        <div className="flex items-center justify-center py-16">
          <div className="flex flex-col items-center gap-3">
            <div className="animate-pulse w-8 h-8 rounded-full bg-border" />
            <span className="text-[13px] text-foreground-muted">Loading employees…</span>
          </div>
        </div>
      </div>
    );
  }

  if (!sorted.length) {
    return (
      <div className="bg-surface border border-border rounded-[18px] shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
        <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
          <Users size={32} className="text-foreground-muted" />
          <p className="text-[15px] font-bold text-foreground">No employees found</p>
          <p className="text-[13px] text-foreground-muted">Try adjusting your filters, or add a new employee.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-surface border border-border rounded-[18px] overflow-hidden shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
      <div className="overflow-x-auto">
        <table className="min-w-full">
          <thead>
            <tr className="bg-surface-muted">
              <th scope="col" className="w-10 px-4 py-3.5 text-left">
                <input
                  type="checkbox"
                  checked={sorted.length > 0 && sorted.every((e) => selectedIds?.has(e.id))}
                  onChange={() => {
                    if (sorted.every((e) => selectedIds?.has(e.id))) {
                      onSelectionChange?.(new Set());
                    } else {
                      onSelectionChange?.(new Set(sorted.map((e) => e.id)));
                    }
                  }}
                  className="h-4 w-4 rounded border-border text-primary focus:ring-primary/20 bg-background"
                />
              </th>
              {COLUMNS.map((col) => (
                <th
                  key={col.key}
                  scope="col"
                  onClick={() => toggleSort(col.key)}
                  className="cursor-pointer select-none px-4 py-3.5 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted transition-colors duration-150 hover:text-primary"
                >
                  <span className="inline-flex items-center gap-1">
                    {col.label}
                    {sortKey === col.key && (
                      <span className="text-primary">{sortDir === "asc" ? "▲" : "▼"}</span>
                    )}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {sorted.map((emp) => (
              <tr
                key={emp.id}
                onClick={() => onRowClick?.(emp)}
                className={`cursor-pointer transition-all duration-150 hover:bg-background dark:hover:bg-surface-muted ${
                  selectedEmployeeId === emp.id ? "bg-primary/5 dark:bg-primary/10" : ""
                }`}
              >
                <td className="w-10 whitespace-nowrap px-4 py-3.5" onClick={(e) => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    checked={selectedIds?.has(emp.id) || false}
                    onChange={() => {
                      const next = new Set(selectedIds);
                      if (next.has(emp.id)) next.delete(emp.id);
                      else next.add(emp.id);
                      onSelectionChange?.(next);
                    }}
                    className="h-4 w-4 rounded border-border text-primary focus:ring-primary/20 bg-background"
                  />
                </td>
                <td className="whitespace-nowrap px-4 py-3.5 text-[13px] font-semibold text-foreground-muted">
                  <div className="flex flex-col">
                    <span>{emp.employeeCode}</span>
                  </div>
                </td>
                <td className="whitespace-nowrap px-4 py-3.5">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-full bg-info/10 text-info flex items-center justify-center text-[11px] font-bold">
                      {initials(emp.name)}
                    </div>
                    <div>
                      <div className="text-[13px] font-semibold text-foreground">
                        {emp.name}
                      </div>
                    </div>
                  </div>
                </td>
                <td className="whitespace-nowrap px-4 py-3.5">
                  <DepartmentBadge dept={emp.department} />
                </td>
                <td className="whitespace-nowrap px-4 py-3.5 text-[13px] text-foreground-muted">{emp.designation}</td>
                <td className="whitespace-nowrap px-4 py-3.5 text-[13px] font-semibold text-foreground">{formatCurrency(emp.ctc, currencyInfo)}</td>
                <td className="whitespace-nowrap px-4 py-3.5">
                  <StatusBadge status={emp.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
