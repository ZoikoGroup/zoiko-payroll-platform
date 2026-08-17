import { useState, useMemo } from "react";
import { Search, X, Check, Ban, Mail, UserPlus, CalendarDays, Download } from "lucide-react";
import * as XLSX from "xlsx";
import { useToast } from "../ToastContext";

const STATUS_COLORS = {
  pending:  "bg-warning/10 text-warning border-warning/20",
  approved: "bg-primary/10 text-primary border-primary/20",
  rejected: "bg-error/10 text-error border-error/20",
};

const TYPE_PILL = {
  paid:    "bg-info/10 text-info border-info/20",
  unpaid:  "bg-foreground-muted/10 text-foreground-muted border-border",
  sick:    "bg-error/10 text-error border-error/20",
  compOff: "bg-category-teal/10 text-category-teal border-category-teal/20",
};

const TYPE_LABEL = { paid: "Paid", unpaid: "Unpaid", sick: "Sick", compOff: "Comp-Off" };

const COLORS = [
  "bg-primary", "bg-info", "bg-category-teal",
  "bg-error", "bg-warning", "bg-brand-cyan",
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

function formatDate(d) {
  if (!d) return "—";
  try {
    return new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
  } catch { return d; }
}

function daysBetween(from, to) {
  if (!from || !to) return 0;
  const a = new Date(from + "T00:00:00");
  const b = new Date(to + "T00:00:00");
  return Math.max(1, Math.round((b - a) / 86400000) + 1);
}

export default function LeaveRequestsTab({ requests = [], onApprove, onReject }) {
  const { addToast } = useToast();
  const [statusFilter, setStatusFilter] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");

  const filtered = useMemo(() => {
    return requests.filter((r) => {
      if (statusFilter !== "all" && r.status !== statusFilter) return false;
      if (typeFilter !== "all" && r.leaveType !== typeFilter) return false;
      if (fromDate && (r.endDate || r.startDate) < fromDate) return false;
      if (toDate && (r.startDate || r.endDate) > toDate) return false;
      if (search) {
        const q = search.toLowerCase();
        const name = (r.employeeName || "").toLowerCase();
        const reason = (r.reason || "").toLowerCase();
        if (!name.includes(q) && !reason.includes(q)) return false;
      }
      return true;
    });
  }, [requests, statusFilter, typeFilter, fromDate, toDate, search]);

  function exportLeaveRequests() {
    if (filtered.length === 0) {
      addToast?.("No leave requests to export for the current filters.", "error");
      return;
    }
    const rows = filtered.map((r) => ({
      "Employee": r.employeeName || "",
      "Department": r.department || "",
      "Type": TYPE_LABEL[r.leaveType] || r.leaveType || "",
      "From": formatDate(r.startDate),
      "To": formatDate(r.endDate),
      "Days": r.days || daysBetween(r.startDate, r.endDate),
      "Request Code": r.requestCode || "",
      "Reason": r.reason || "",
      "Pay Impact": r.leaveType === "unpaid" ? "No pay — deducted" : "Full pay",
      "Source": r.isAutoCreated ? "Attendance" : r.source === "email" ? "Email" : "Manual",
      "Status": r.status ? r.status.charAt(0).toUpperCase() + r.status.slice(1) : "",
    }));
    const headers = Object.keys(rows[0]);
    const ws = XLSX.utils.json_to_sheet(rows, { header: headers });
    ws["!cols"] = headers.map((h) => ({ wch: Math.max(h.length, 16) }));
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Leave Requests");
    const rangeTag = fromDate || toDate ? `_${fromDate || "start"}_to_${toDate || "end"}` : "";
    const dateStamp = new Date().toISOString().slice(0, 10);
    XLSX.writeFile(wb, `leave_requests${rangeTag}_${dateStamp}.xlsx`);
    addToast?.(`Exported ${filtered.length} leave request${filtered.length !== 1 ? "s" : ""}.`, "success");
  }

  const thCls = "px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted select-none whitespace-nowrap";

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex items-center gap-2 flex-wrap">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-[12px] border border-border bg-surface px-3.5 py-2.5 text-[13px] text-foreground-muted font-medium focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200 cursor-pointer"
        >
          <option value="all">All Status</option>
          <option value="pending">Pending</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
        </select>
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="rounded-[12px] border border-border bg-surface px-3.5 py-2.5 text-[13px] text-foreground-muted font-medium focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200 cursor-pointer"
        >
          <option value="all">All Types</option>
          <option value="paid">Paid</option>
          <option value="unpaid">Unpaid</option>
          <option value="sick">Sick</option>
          <option value="compOff">Comp-Off</option>
        </select>
        <input
          type="date"
          value={fromDate}
          onChange={(e) => setFromDate(e.target.value)}
          title="From date"
          className="rounded-[12px] border border-border bg-surface px-3.5 py-2.5 text-[13px] text-foreground-muted font-medium focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200"
        />
        <input
          type="date"
          value={toDate}
          onChange={(e) => setToDate(e.target.value)}
          title="To date"
          className="rounded-[12px] border border-border bg-surface px-3.5 py-2.5 text-[13px] text-foreground-muted font-medium focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200"
        />
        <div className="relative flex-1 min-w-[200px]">
          <Search size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-foreground-muted pointer-events-none" />
          <input
            type="text"
            placeholder="Search by name or reason…"
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
        <button
          onClick={exportLeaveRequests}
          className="flex items-center gap-2 rounded-[12px] border border-border bg-surface px-4 py-2.5 text-[13px] font-semibold text-foreground-muted hover:border-primary hover:text-primary transition-all duration-200"
          title="Download filtered leave records"
        >
          <Download size={15} /> Export
        </button>
      </div>

      {/* Table */}
      <div className="bg-surface border border-border rounded-[18px] overflow-hidden shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
        <div className="overflow-x-auto">
          <table className="min-w-full table-fixed">
            <thead>
              <tr className="bg-surface-muted border-b border-border">
                <th className={`${thCls} w-52`}>Employee</th>
                <th className={`${thCls} w-24`}>Type</th>
                <th className={`${thCls} w-28`}>From</th>
                <th className={`${thCls} w-28`}>To</th>
                <th className={`${thCls} w-16`}>Days</th>
                <th className={`${thCls} w-28`}>Request Code</th>
                <th className={`${thCls}`}>Reason</th>
                <th className={`${thCls} w-28`}>Pay Impact</th>
                <th className={`${thCls} w-28`}>Source</th>
                <th className={`${thCls} w-28`}>Status</th>
                <th className={`${thCls} w-20`}>Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {filtered.length === 0 ? (
                <tr>
                    <td colSpan={11} className="px-6 py-16 text-center">
                    <div className="flex flex-col items-center">
                      <div className="w-14 h-14 rounded-[14px] bg-surface-muted flex items-center justify-center mb-3">
                        <Search size={22} className="text-foreground-muted" />
                      </div>
                      <p className="text-[13px] font-semibold text-foreground-muted">No leave requests found</p>
                      <p className="text-[12px] text-foreground-muted mt-1">Try adjusting the filters</p>
                    </div>
                  </td>
                </tr>
              ) : (
                filtered.map((r, idx) => (
                  <tr key={r.id || idx} className={`transition-colors duration-150 hover:bg-background dark:hover:bg-surface-muted ${idx % 2 === 0 ? "bg-surface" : "bg-surface-muted/50"}`}>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2.5">
                        <InitialsAvatar name={r.employeeName} />
                        <span className="text-[13px] font-semibold text-foreground truncate">{r.employeeName || "—"}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center px-2.5 py-1 rounded-full border text-[11px] font-bold ${TYPE_PILL[r.leaveType] || "bg-background-secondary text-foreground-muted"}`}>
                        {TYPE_LABEL[r.leaveType] || r.leaveType}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-[13px] text-foreground-muted">{formatDate(r.startDate)}</td>
                    <td className="px-4 py-3 text-[13px] text-foreground-muted">{formatDate(r.endDate)}</td>
                    <td className="px-4 py-3 text-center">
                      <span className="text-[13px] font-bold text-foreground">{r.days || daysBetween(r.startDate, r.endDate)}</span>
                    </td>
                    <td className="px-4 py-3 text-[11px] font-mono font-semibold text-foreground-muted">{r.requestCode || "—"}</td>
                    <td className="px-4 py-3 text-[13px] text-foreground-muted max-w-[180px] truncate" title={r.reason}>{r.reason || "—"}</td>
                    <td className="px-4 py-3">
                      <span className={`text-[12px] font-semibold ${r.leaveType === "unpaid" ? "text-error" : "text-primary"}`}>
                        {r.leaveType === "unpaid" ? "No pay — deducted" : "Full pay"}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {r.isAutoCreated ? (
                        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-primary/10 border border-primary/20 text-[11px] font-bold text-primary" title="Auto-created from attendance">
                          <CalendarDays size={10} /> Attendance
                        </span>
                      ) : r.source === "email" ? (
                        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-info/10 border border-info/20 text-[11px] font-bold text-info">
                          <Mail size={10} /> Email
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-surface-muted border border-border text-[11px] font-bold text-foreground-muted">
                          <UserPlus size={10} /> Manual
                        </span>
                      )}
                      {r.linkedAttendanceDates && r.linkedAttendanceDates.length > 0 && (
                        <span className="ml-1 inline-flex items-center px-1.5 py-0.5 rounded text-[8px] font-mono text-foreground-muted bg-surface-muted border border-border"
                          title={r.linkedAttendanceDates.join(", ")}>
                          {r.linkedAttendanceDates.length}d
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center px-2.5 py-1 rounded-full border text-[11px] font-bold ${STATUS_COLORS[r.status] || ""}`}>
                        {r.status ? r.status.charAt(0).toUpperCase() + r.status.slice(1) : "—"}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {r.status === "pending" ? (
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => onApprove?.(r.id)}
                            className="p-1.5 rounded-[10px] bg-primary/10 text-primary hover:bg-primary/20 transition-colors"
                            title="Approve"
                          >
                            <Check size={14} />
                          </button>
                          <button
                            onClick={() => onReject?.(r.id)}
                            className="p-1.5 rounded-[10px] bg-error/10 text-error hover:bg-error/20 transition-colors"
                            title="Reject"
                          >
                            <Ban size={14} />
                          </button>
                        </div>
                      ) : (
                        <span className="text-[12px] text-foreground-muted">—</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        <div className="bg-surface-muted border-t border-border px-4 py-2.5 flex items-center justify-between">
          <p className="text-[11px] text-foreground-muted">
            Showing <span className="font-semibold text-foreground">{filtered.length}</span> of {requests.length} request{requests.length !== 1 ? "s" : ""}
          </p>
        </div>
      </div>
    </div>
  );
}
