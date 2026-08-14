import { Search } from "lucide-react";

export default function PayslipFilters({
  search,
  onSearchChange,
  periodFilter,
  onPeriodChange,
  employeeFilter,
  onEmployeeChange,
  employees,
  periods = ["All Periods"],
}) {
  return (
    <div className="bg-surface border border-border rounded-[18px] p-4 shadow-[0_1px_3px_rgba(0,0,0,0.04)] flex items-center gap-3 flex-wrap">
      <div className="relative flex-1 min-w-[200px]">
        <Search size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-foreground-muted" />
        <input
          type="text"
          placeholder="Search by employee name…"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          className="w-full rounded-[12px] border border-border bg-background pl-10 pr-4 py-2.5 text-[13px] text-foreground placeholder:text-foreground-muted focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200"
        />
      </div>
      <select
        value={periodFilter}
        onChange={(e) => onPeriodChange(e.target.value)}
        className="rounded-[12px] border border-border bg-background px-3.5 py-2.5 text-[13px] text-foreground placeholder:text-foreground-muted focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200"
      >
        {periods.map((p) => <option key={p}>{p}</option>)}
      </select>
      <select
        value={employeeFilter}
        onChange={(e) => onEmployeeChange(e.target.value)}
        className="rounded-[12px] border border-border bg-background px-3.5 py-2.5 text-[13px] text-foreground placeholder:text-foreground-muted focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200"
      >
        <option value="">All Employees</option>
        {employees.map((emp) => (
          <option key={emp.id} value={emp.id}>{emp.name}</option>
        ))}
      </select>
    </div>
  );
}
