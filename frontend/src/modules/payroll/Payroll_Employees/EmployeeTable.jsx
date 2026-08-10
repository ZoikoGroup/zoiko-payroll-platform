import React, { useState, useMemo } from "react";
import { Users } from "lucide-react";

const DEPARTMENT_STYLES = {
  Engineering: "bg-[#35B6F5]/10 text-[#35B6F5]",
  Sales: "bg-[#19C58A]/10 text-[#19C58A]",
  Marketing: "bg-[#9D7BF2]/10 text-[#9D7BF2]",
  HR: "bg-[#FF6E86]/10 text-[#FF6E86]",
  Finance: "bg-[#F8A60A]/10 text-[#F8A60A]",
};

function DepartmentBadge({ dept }) {
  const style = DEPARTMENT_STYLES[dept] || "bg-[#9E9690]/10 text-[#9E9690]";
  return (
    <span className={`inline-flex items-center rounded-full px-3 py-1 text-[11px] font-bold ${style}`}>
      {dept}
    </span>
  );
}

const STATUS_STYLES = {
  Active: "bg-[#19C58A]/10 text-[#19C58A]",
  "On Leave": "bg-[#F8A60A]/10 text-[#F8A60A]",
  Inactive: "bg-[#FF6E86]/10 text-[#FF6E86]",
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
      <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] overflow-hidden shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
        <div className="flex items-center justify-center py-16">
          <div className="flex flex-col items-center gap-3">
            <div className="animate-pulse w-8 h-8 rounded-full bg-[#E5E0D9] dark:bg-[#38312D]" />
            <span className="text-[13px] text-[#9E9690]">Loading employees…</span>
          </div>
        </div>
      </div>
    );
  }

  if (!sorted.length) {
    return (
      <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
        <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
          <Users size={32} className="text-[#9E9690]" />
          <p className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">No employees found</p>
          <p className="text-[13px] text-[#9E9690]">Try adjusting your filters, or add a new employee.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] overflow-hidden shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
      <div className="overflow-x-auto">
        <table className="min-w-full">
          <thead>
            <tr className="bg-[#F8F7F4] dark:bg-[#2A2520]">
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
                  className="h-4 w-4 rounded border-[#E5E0D9] dark:border-[#38312D] text-[#19C58A] focus:ring-[#19C58A]/20 bg-[#F8F7F4] dark:bg-[#1A1816]"
                />
              </th>
              {COLUMNS.map((col) => (
                <th
                  key={col.key}
                  scope="col"
                  onClick={() => toggleSort(col.key)}
                  className="cursor-pointer select-none px-4 py-3.5 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690] transition-colors duration-150 hover:text-[#19C58A]"
                >
                  <span className="inline-flex items-center gap-1">
                    {col.label}
                    {sortKey === col.key && (
                      <span className="text-[#19C58A]">{sortDir === "asc" ? "▲" : "▼"}</span>
                    )}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[#E5E0D9] dark:divide-[#38312D]">
            {sorted.map((emp) => (
              <tr
                key={emp.id}
                onClick={() => onRowClick?.(emp)}
                className={`cursor-pointer transition-all duration-150 hover:bg-[#F8F7F4] dark:hover:bg-[#2A2520] ${
                  selectedEmployeeId === emp.id ? "bg-[#19C58A]/5 dark:bg-[#19C58A]/10" : ""
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
                    className="h-4 w-4 rounded border-[#E5E0D9] dark:border-[#38312D] text-[#19C58A] focus:ring-[#19C58A]/20 bg-[#F8F7F4] dark:bg-[#1A1816]"
                  />
                </td>
                <td className="whitespace-nowrap px-4 py-3.5 text-[13px] font-semibold text-[#9E9690]">
                  <div className="flex flex-col">
                    <span>{emp.employeeCode}</span>
                  </div>
                </td>
                <td className="whitespace-nowrap px-4 py-3.5">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-full bg-[#35B6F5]/10 text-[#35B6F5] flex items-center justify-center text-[11px] font-bold">
                      {initials(emp.name)}
                    </div>
                    <div>
                      <div className="text-[13px] font-semibold text-[#1A1816] dark:text-[#F0EDE8]">
                        {emp.name}
                      </div>
                    </div>
                  </div>
                </td>
                <td className="whitespace-nowrap px-4 py-3.5">
                  <DepartmentBadge dept={emp.department} />
                </td>
                <td className="whitespace-nowrap px-4 py-3.5 text-[13px] text-[#6B6560] dark:text-[#A69B93]">{emp.designation}</td>
                <td className="whitespace-nowrap px-4 py-3.5 text-[13px] font-semibold text-[#1A1816] dark:text-[#F0EDE8]">{formatCurrency(emp.ctc, currencyInfo)}</td>
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
