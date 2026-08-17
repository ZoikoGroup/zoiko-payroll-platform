import { useState, useMemo } from "react";
import { Search, X, ChevronUp, ChevronDown, ChevronsUpDown } from "lucide-react";

const COLORS = [
  "bg-primary", "bg-info", "bg-category-teal",
  "bg-error", "bg-warning", "bg-brand-cyan",
];

const TYPE_COLS = [
  { key: "paid",    label: "Paid",    color: "var(--color-info)" },
  { key: "unpaid",  label: "Unpaid",  color: "var(--color-foreground-muted)" },
  { key: "sick",    label: "Sick",    color: "var(--color-error)" },
  { key: "compOff", label: "Comp-Off", color: "var(--color-category-teal)" },
];

function InitialsAvatar({ name }) {
  const parts = (name || "").trim().split(" ");
  const initials = parts.length >= 2
    ? parts[0][0] + parts[parts.length - 1][0]
    : (parts[0]?.[0] || "?");
  const idx = (name || "").charCodeAt(0) % COLORS.length;
  return (
    <div className={`w-8 h-8 rounded-full flex items-center justify-center text-[11px] font-bold text-white flex-shrink-0 ${COLORS[idx]}`}>
      {initials.toUpperCase()}
    </div>
  );
}

function SortIcon({ col, sortKey, sortOrder }) {
  if (sortKey !== col) return <ChevronsUpDown size={12} className="text-foreground-muted ml-1 inline" />;
  return sortOrder === "asc"
    ? <ChevronUp size={12} className="text-primary ml-1 inline" />
    : <ChevronDown size={12} className="text-primary ml-1 inline" />;
}

function UtilBar({ used, total }) {
  const pct = total > 0 ? Math.round((used / total) * 100) : 0;
  return (
    <div className="flex items-center gap-2 min-w-[100px]">
      <div className="flex-1 h-1.5 bg-border rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-300"
          style={{ width: `${Math.min(pct, 100)}%`, backgroundColor: pct > 80 ? "#FF6E86" : pct > 50 ? "#F8A60A" : "#19C58A" }}
        />
      </div>
      <span className="text-[11px] font-bold text-foreground-muted w-[36px] text-right">{pct}%</span>
    </div>
  );
}

export default function LeaveBalancesTab({ employees = [], allocations = [] }) {
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState("name");
  const [sortOrder, setSortOrder] = useState("asc");

  function toggleSort(key) {
    if (sortKey === key) setSortOrder((o) => o === "asc" ? "desc" : "asc");
    else { setSortKey(key); setSortOrder("asc"); }
  }

  const rows = useMemo(() => {
    return allocations.map((a) => {
      const emp = employees.find((e) => Number(e.id) === Number(a.employeeId)) || {};
      const balances = a.leaveBalances || {};
      const getType = (k) => ({ used: Number(balances[k]?.used) || 0, total: Number(balances[k]?.total) || 0 });
      const paid = getType("paid");
      const unpaid = getType("unpaid");
      const sick = getType("sick");
      const compOff = getType("compOff");
      const totalUsed = paid.used + unpaid.used + sick.used + compOff.used;
      const totalAllowed = (paid.total || 20) + (unpaid.total || 10) + (sick.total || 12) + (compOff.total || 5);
      return {
        employeeId: a.employeeId,
        name: a.name || emp.name || "",
        department: emp.department || a.department || "",
        paid, unpaid, sick, compOff,
        totalUsed,
        totalAllowed,
        utilPct: totalAllowed > 0 ? Math.round((totalUsed / totalAllowed) * 100) : 0,
      };
    });
  }, [allocations, employees]);

  const filtered = useMemo(() => {
    let list = rows;
    if (search) {
      const q = search.toLowerCase();
      list = list.filter((r) => r.name?.toLowerCase().includes(q) || r.department?.toLowerCase().includes(q));
    }
    return [...list].sort((a, b) => {
      let av, bv;
      switch (sortKey) {
        case "name":       av = a.name || ""; bv = b.name || ""; break;
        case "department": av = a.department || ""; bv = b.department || ""; break;
        case "totalUsed":  av = a.totalUsed; bv = b.totalUsed; break;
        case "utilPct":    av = a.utilPct; bv = b.utilPct; break;
        case "paid":       av = a.paid?.used || 0; bv = b.paid?.used || 0; break;
        case "unpaid":     av = a.unpaid?.used || 0; bv = b.unpaid?.used || 0; break;
        case "sick":       av = a.sick?.used || 0; bv = b.sick?.used || 0; break;
        case "compOff":    av = a.compOff?.used || 0; bv = b.compOff?.used || 0; break;
        default:           av = a.name || ""; bv = b.name || "";
      }
      if (typeof av === "string") return sortOrder === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
      return sortOrder === "asc" ? av - bv : bv - av;
    });
  }, [rows, search, sortKey, sortOrder]);

  const thCls = "px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted select-none whitespace-nowrap";
  const thCenterCls = "px-4 py-3 text-center text-[10px] font-bold uppercase tracking-widest text-foreground-muted select-none whitespace-nowrap cursor-pointer hover:bg-surface-muted transition-all duration-150";

  return (
    <div className="space-y-4">
      {/* Search */}
      <div className="relative max-w-sm">
        <Search size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-foreground-muted pointer-events-none" />
        <input
          type="text"
          placeholder="Search by name or department…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full rounded-[12px] border border-border bg-surface pl-10 pr-10 py-2.5 text-[13px] text-foreground placeholder:text-foreground-muted focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200"
        />
        {search && (
          <button onClick={() => setSearch("")} className="absolute right-3 top-1/2 -translate-y-1/2 text-foreground-muted hover:text-foreground-muted transition-colors" aria-label="Clear">
            <X size={14} />
          </button>
        )}
      </div>

      {/* Table */}
      <div className="bg-surface border border-border rounded-[18px] overflow-hidden shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
        <div className="overflow-x-auto">
          <table className="min-w-full table-fixed">
            <thead>
              <tr className="bg-surface-muted border-b border-border">
                <th className={`${thCls} w-52 cursor-pointer hover:bg-surface-muted transition-all duration-150`} onClick={() => toggleSort("name")}>
                  Employee <SortIcon col="name" sortKey={sortKey} sortOrder={sortOrder} />
                </th>
                <th className={`${thCls} w-32 cursor-pointer hover:bg-surface-muted transition-all duration-150`} onClick={() => toggleSort("department")}>
                  Dept <SortIcon col="department" sortKey={sortKey} sortOrder={sortOrder} />
                </th>
                {TYPE_COLS.map((tc) => (
                  <th key={tc.key} className={`${thCenterCls} w-28`} onClick={() => toggleSort(tc.key)}>
                    <span style={{ color: tc.color }}>{tc.label}</span>
                  </th>
                ))}
                <th className={`${thCenterCls} w-20`} onClick={() => toggleSort("totalUsed")}>
                  Used <SortIcon col="totalUsed" sortKey={sortKey} sortOrder={sortOrder} />
                </th>
                <th className={`${thCenterCls} w-32`} onClick={() => toggleSort("utilPct")}>
                  Util % <SortIcon col="utilPct" sortKey={sortKey} sortOrder={sortOrder} />
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-6 py-16 text-center">
                    <p className="text-[13px] text-foreground-muted font-medium">No employees found</p>
                  </td>
                </tr>
              ) : (
                filtered.map((r, idx) => (
                  <tr key={r.employeeId} className={`transition-colors duration-150 hover:bg-background dark:hover:bg-surface-muted ${idx % 2 === 0 ? "bg-surface" : "bg-surface-muted/50"}`}>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2.5">
                        <InitialsAvatar name={r.name} />
                        <div className="min-w-0">
                          <p className="text-[13px] font-semibold text-foreground truncate">{r.name || "—"}</p>
                          <p className="text-[10px] text-foreground-muted">ID #{r.employeeId}</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      {r.department ? (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-[8px] bg-info/10 text-info text-[11px] font-semibold">{r.department}</span>
                      ) : (
                        <span className="text-foreground-muted text-[11px]">—</span>
                      )}
                    </td>
                    {TYPE_COLS.map((tc) => {
                      const data = r[tc.key];
                      return (
                        <td key={tc.key} className="px-4 py-3 text-center">
                          <span className="text-[13px] font-semibold text-foreground">
                            {data.used}<span className="text-foreground-muted font-normal">/{data.total}</span>
                          </span>
                        </td>
                      );
                    })}
                    <td className="px-4 py-3 text-center">
                      <span className="text-[13px] font-bold text-foreground">{r.totalUsed}</span>
                    </td>
                    <td className="px-4 py-3">
                      <UtilBar used={r.totalUsed} total={r.totalAllowed} />
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        <div className="bg-surface-muted border-t border-border px-4 py-2.5 flex items-center justify-between">
          <p className="text-[11px] text-foreground-muted">
            Showing <span className="font-semibold text-foreground">{filtered.length}</span> employee{filtered.length !== 1 ? "s" : ""}
          </p>
          <p className="text-[11px] text-foreground-muted">Defaults: Paid 20 · Unpaid 10 · Sick 12 · Comp-Off 5</p>
        </div>
      </div>
    </div>
  );
}
