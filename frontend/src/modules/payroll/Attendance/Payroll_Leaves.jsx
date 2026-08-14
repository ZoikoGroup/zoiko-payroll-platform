import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { BookOpen, Plus, Loader2, X, CheckCircle, Check, Ban } from "lucide-react";
import { useToast } from "../ToastContext";
import {
  getEmployees, getLeaveRecords, getPayrollLeaveRequests, createPayrollLeaveRequest, reviewPayrollLeaveRequest,
  getPayrollHolidays, upsertPayrollHolidays, deletePayrollHoliday,
} from "../../../service/payrollService";
import LeaveRequestsTab from "./LeaveRequestsTab";
import HolidaysTab from "./HolidaysTab";
import LeaveBalancesTab from "./LeaveBalancesTab";

const TYPE_PILL = {
  paid:    "bg-info/10 text-info border-info/20",
  unpaid:  "bg-foreground-muted/10 text-foreground-muted border-border",
  sick:    "bg-error/10 text-error border-error/20",
  compOff: "bg-category-teal/10 text-category-teal border-category-teal/20",
};

const TYPE_STATUS = {
  pending:  "bg-warning/10 text-warning border-warning/20",
  approved: "bg-primary/10 text-primary border-primary/20",
  rejected: "bg-error/10 text-error border-error/20",
};

function formatDateShort(d) {
  if (!d) return "—";
  try {
    return new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
  } catch { return d; }
}

function LeaveTypeTab({ typeKey, typeInfo, requests, allocations, employees, onApprove, onReject }) {
  const [statusFilter, setStatusFilter] = useState("all");
  const [search, setSearch] = useState("");

  const typeRequests = useMemo(() => {
    return requests.filter((r) => {
      if (r.leaveType !== typeKey) return false;
      if (statusFilter !== "all" && r.status !== statusFilter) return false;
      if (search) {
        const q = search.toLowerCase();
        const name = (r.employeeName || "").toLowerCase();
        const reason = (r.reason || "").toLowerCase();
        if (!name.includes(q) && !reason.includes(q)) return false;
      }
      return true;
    });
  }, [requests, typeKey, statusFilter, search]);

  const typeStats = useMemo(() => {
    const approved = typeRequests.filter((r) => r.status === "approved");
    const pending = typeRequests.filter((r) => r.status === "pending");
    const totalDaysUsed = approved.reduce((s, r) => s + (r.days || daysBetween(r.startDate, r.endDate) || 0), 0);
    let totalAllowed = 0;
    allocations.forEach((a) => {
      const b = a.leaveBalances?.[typeKey];
      totalAllowed += b?.total || typeInfo?.total || 0;
    });
    const totalUsedGlobal = allocations.reduce((s, a) => s + (a.leaveBalances?.[typeKey]?.used || 0), 0);
    return {
      totalRequests: typeRequests.length,
      approvedCount: approved.length,
      pendingCount: pending.length,
      totalDaysUsed: totalDaysUsed || totalUsedGlobal,
      totalAllowed,
      remaining: Math.max(0, totalAllowed - (totalDaysUsed || totalUsedGlobal)),
    };
  }, [typeRequests, allocations, typeKey, typeInfo]);

  return (
    <div className="space-y-4">
      <div className="bg-surface border border-border rounded-[18px] p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
        <div className="flex items-center gap-3 mb-4">
          <span className="text-[20px]">{typeInfo?.icon}</span>
          <div>
            <h3 className="text-[15px] font-bold text-foreground">{typeInfo?.label || typeKey}</h3>
            <p className="text-[11px] text-foreground-muted">{typeStats.totalRequests} request{typeStats.totalRequests !== 1 ? "s" : ""} · {typeStats.pendingCount} pending</p>
          </div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="bg-background rounded-[12px] p-3 border border-border">
            <p className="text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Used</p>
            <p className="text-[18px] font-bold" style={{ color: typeInfo?.color }}>{typeStats.totalDaysUsed}<span className="text-[12px] font-semibold text-foreground-muted">/{typeStats.totalAllowed}</span></p>
          </div>
          <div className="bg-background rounded-[12px] p-3 border border-border">
            <p className="text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Remaining</p>
            <p className="text-[18px] font-bold text-primary">{typeStats.remaining}</p>
          </div>
          <div className="bg-background rounded-[12px] p-3 border border-border">
            <p className="text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Approved</p>
            <p className="text-[18px] font-bold text-primary">{typeStats.approvedCount}</p>
          </div>
          <div className="bg-background rounded-[12px] p-3 border border-border">
            <p className="text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Pending</p>
            <p className="text-[18px] font-bold text-warning">{typeStats.pendingCount}</p>
          </div>
        </div>
      </div>

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
        <div className="relative flex-1 min-w-[200px]">
          <input
            type="text"
            placeholder="Search by name or reason…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-[12px] border border-border bg-surface px-3.5 py-2.5 text-[13px] text-foreground placeholder:text-foreground-muted focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200"
          />
          {search && (
            <button onClick={() => setSearch("")} className="absolute right-3 top-1/2 -translate-y-1/2 text-foreground-muted hover:text-foreground-muted transition-colors">
              <X size={14} />
            </button>
          )}
        </div>
      </div>

      <div className="bg-surface border border-border rounded-[18px] overflow-hidden shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
        <div className="overflow-x-auto">
          <table className="min-w-full table-fixed">
            <thead>
              <tr className="bg-surface-muted border-b border-border">
                <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted w-52">Employee</th>
                <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted w-28">From</th>
                <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted w-28">To</th>
                <th className="px-4 py-3 text-center text-[10px] font-bold uppercase tracking-widest text-foreground-muted w-16">Days</th>
                <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Reason</th>
                <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted w-28">Status</th>
                <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted w-20">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {typeRequests.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-6 py-16 text-center">
                    <p className="text-[13px] text-foreground-muted font-medium">No {typeInfo?.label || typeKey} requests found</p>
                  </td>
                </tr>
              ) : (
                typeRequests.map((r, idx) => (
                  <tr key={r.id || idx} className={`transition-colors duration-150 hover:bg-background dark:hover:bg-surface-muted ${idx % 2 === 0 ? "bg-surface" : "bg-surface-muted/50"}`}>
                    <td className="px-4 py-3 text-[13px] font-semibold text-foreground">{r.employeeName || "—"}</td>
                    <td className="px-4 py-3 text-[13px] text-foreground-muted">{formatDateShort(r.startDate)}</td>
                    <td className="px-4 py-3 text-[13px] text-foreground-muted">{formatDateShort(r.endDate)}</td>
                    <td className="px-4 py-3 text-center">
                      <span className="text-[13px] font-bold text-foreground">{r.days || daysBetween(r.startDate, r.endDate)}</span>
                    </td>
                    <td className="px-4 py-3 text-[13px] text-foreground-muted max-w-[180px] truncate" title={r.reason}>{r.reason || "—"}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center px-2.5 py-1 rounded-full border text-[11px] font-bold ${TYPE_STATUS[r.status] || ""}`}>
                        {r.status ? r.status.charAt(0).toUpperCase() + r.status.slice(1) : "—"}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {r.status === "pending" ? (
                        <div className="flex items-center gap-1">
                          <button onClick={() => onApprove?.(r.id)} className="p-1.5 rounded-[10px] bg-primary/10 text-primary hover:bg-primary/20 transition-colors" title="Approve">
                            <Check size={14} />
                          </button>
                          <button onClick={() => onReject?.(r.id)} className="p-1.5 rounded-[10px] bg-error/10 text-error hover:bg-error/20 transition-colors" title="Reject">
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
      </div>
    </div>
  );
}

const LEAVE_TYPES = [
  { key: "paid",    label: "Paid Leave",    icon: "💰", color: "var(--color-info)", total: 20 },
  { key: "unpaid",  label: "Unpaid Leave",  icon: "🆓", color: "var(--color-foreground-muted)", total: 10 },
  { key: "sick",    label: "Sick Leave",    icon: "🏥", color: "var(--color-error)", total: 12 },
  { key: "compOff", label: "Comp-Off",      icon: "🔄", color: "var(--color-category-teal)", total: 5  },
];
const LEAVE_TYPE_MAP = Object.fromEntries(LEAVE_TYPES.map((lt) => [lt.key, lt]));

function daysBetween(from, to) {
  if (!from || !to) return 1;
  const a = new Date(from + "T00:00:00");
  const b = new Date(to + "T00:00:00");
  return Math.max(1, Math.round((b - a) / 86400000) + 1);
}

const TABS = [
  { id: "requests",  label: "Requests" },
  { id: "paid",      label: "Paid Leave",  color: "var(--color-info)" },
  { id: "unpaid",    label: "Unpaid Leave", color: "var(--color-foreground-muted)" },
  { id: "sick",      label: "Sick Leave",  color: "var(--color-error)" },
  { id: "compOff",   label: "Comp-Off",    color: "var(--color-category-teal)" },
  { id: "holidays",  label: "Holidays" },
  { id: "balances",  label: "All Balances" },
];

export default function PayrollLeavesPage() {
  const { addToast } = useToast();
  const today = useMemo(() => new Date(), []);
  const currentYear = today.getFullYear();

  const [loading, setLoading] = useState(true);
  const [employees, setEmployees] = useState([]);
  const [allocations, setAllocations] = useState([]);
  const [requests, setRequests] = useState([]);
  const requestsRef = useRef(requests);
  requestsRef.current = requests;
  const [activeTab, setActiveTab] = useState("requests");

  // Company holidays — the real backend list (payroll_holidays), the same
  // one Attendance's Bulk Generation "Exclude Holidays" reads from.
  const [holidays, setHolidays] = useState([]);
  const [holidaysLoading, setHolidaysLoading] = useState(false);

  // Apply Leave modal
  const [showApplyModal, setShowApplyModal] = useState(false);
  const [applyForm, setApplyForm] = useState({ employeeId: "", leaveType: "paid", startDate: "", endDate: "", reason: "" });
  const [submitting, setSubmitting] = useState(false);

  // Jurisdiction-based seeding now happens server-side (list_holidays in
  // service.py) the first time this org+country+year has no rows yet — this
  // component is just a thin read/write client. `source` here mirrors the
  // real `category` column ("National" for seeded defaults, "Company" for
  // admin-added), rather than guessing from name/date as before.
  const allHolidays = useMemo(() => {
    return holidays
      .map((h) => ({
        id: h.id,
        name: h.name,
        date: h.date,
        country: h.country,
        source: h.category === "Company" ? "company" : "government",
      }))
      .sort((a, b) => (a.date || "").localeCompare(b.date || ""));
  }, [holidays]);

  const jurisdictionCountry = allHolidays[0]?.country || "";

  const loadHolidays = useCallback(async () => {
    setHolidaysLoading(true);
    try {
      const data = await getPayrollHolidays(currentYear);
      const list = Array.isArray(data) ? data : data?.items || data?.holidays || [];
      setHolidays(list);
    } catch {
      setHolidays([]);
    } finally {
      setHolidaysLoading(false);
    }
  }, [currentYear]);

  useEffect(() => { loadHolidays(); }, [loadHolidays]);

  // ── Load data ──
  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [empData, leaveData, leaveRequests] = await Promise.allSettled([
        getEmployees(),
        getLeaveRecords(),
        getPayrollLeaveRequests(),
      ]);

      const empList = empData.status === "fulfilled" ? (Array.isArray(empData.value) ? empData.value : []) : [];
      const leaveList = leaveData.status === "fulfilled" ? (Array.isArray(leaveData.value) ? leaveData.value : []) : [];
      const requestList = leaveRequests.status === "fulfilled" ? (Array.isArray(leaveRequests.value) ? leaveRequests.value : []) : [];

      setEmployees(empList);

      // Build allocations with per-type balances
      const leaveMap = {};
      leaveList.forEach((l) => { leaveMap[l.employeeId] = l; });

      setAllocations(empList.map((e) => {
        const existing = leaveMap[e.id];
        const balances = existing?.leaveBalances || {};
        const getType = (k) => ({
          used: Number(balances[k]?.used) || 0,
          total: Number(balances[k]?.total) || LEAVE_TYPES.find((lt) => lt.key === k)?.total || 0,
        });
        return {
          employeeId: Number(e.id),
          name: e.name || "",
          department: e.department || "",
          leaveBalances: {
            paid: getType("paid"),
            unpaid: getType("unpaid"),
            sick: getType("sick"),
            compOff: getType("compOff"),
          },
        };
      }));

      setRequests(requestList);
    } catch {
      addToast?.("Failed to load leave data.", "error");
    } finally {
      setLoading(false);
    }
  }, [addToast]);

  useEffect(() => { loadData(); }, [loadData]);

  // ── Balance cards: aggregate first employee or system-wide ──
  const balanceCards = useMemo(() => {
    // Show system-wide totals across all employees
    return LEAVE_TYPES.map((lt) => {
      let totalUsed = 0;
      let totalAllowed = 0;
      allocations.forEach((a) => {
        const b = a.leaveBalances?.[lt.key];
        totalUsed += b?.used || 0;
        totalAllowed += b?.total || lt.total;
      });
      return {
        ...lt,
        used: totalUsed,
        total: totalAllowed,
        remaining: Math.max(0, totalAllowed - totalUsed),
        pct: totalAllowed > 0 ? Math.round((totalUsed / totalAllowed) * 100) : 0,
      };
    });
  }, [allocations]);

  // ── Apply Leave ──
  function openApplyModal() {
    setApplyForm({ employeeId: "", leaveType: "paid", startDate: "", endDate: "", reason: "" });
    setShowApplyModal(true);
  }

  function closeApplyModal() {
    setShowApplyModal(false);
    setApplyForm({ employeeId: "", leaveType: "paid", startDate: "", endDate: "", reason: "" });
  }

  async function handleSubmitLeave() {
    if (!applyForm.employeeId) { addToast?.("Select an employee.", "error"); return; }
    if (!applyForm.startDate) { addToast?.("Select a start date.", "error"); return; }
    if (!applyForm.endDate) { addToast?.("Select an end date.", "error"); return; }
    if (applyForm.endDate < applyForm.startDate) { addToast?.("End date must be on or after start date.", "error"); return; }

    setSubmitting(true);
    try {
      const created = await createPayrollLeaveRequest({
        employeeId: Number(applyForm.employeeId),
        leaveType: applyForm.leaveType,
        startDate: applyForm.startDate,
        endDate: applyForm.endDate,
        reason: applyForm.reason,
      });
      setRequests((prev) => [created, ...prev]);
      addToast?.("Leave request submitted.", "success");
      closeApplyModal();
    } catch {
      addToast?.("Failed to submit leave request.", "error");
    } finally {
      setSubmitting(false);
    }
  }

  // ── Approve / Reject ──
  async function handleApprove(id) {
    try {
      const req = requestsRef.current.find((r) => r.id === id);

      const updated = await reviewPayrollLeaveRequest(id, "approved");
      setRequests((prev) => prev.map((r) => r.id === id ? updated : r));

      // Update allocations: increment used for the leave type
      if (req) {
        const leaveDays = req.days || daysBetween(req.startDate, req.endDate) || 1;
        setAllocations((prev) => prev.map((a) => {
          if (Number(a.employeeId) !== Number(req.employeeId)) return a;
          const lt = req.leaveType || "paid";
          const b = a.leaveBalances?.[lt] || { used: 0, total: 0 };
          return {
            ...a,
            leaveBalances: {
              ...a.leaveBalances,
              [lt]: { ...b, used: b.used + leaveDays },
            },
          };
        }));
      }

      addToast?.("Leave request approved.", "success");
    } catch {
      addToast?.("Failed to approve request.", "error");
    }
  }

  async function handleReject(id) {
    try {
      const updated = await reviewPayrollLeaveRequest(id, "rejected");
      setRequests((prev) => prev.map((r) => r.id === id ? updated : r));
      addToast?.("Leave request rejected.", "success");
    } catch {
      addToast?.("Failed to reject request.", "error");
    }
  }

  // ── Holidays CRUD — writes to the real backend table so Attendance's
  // "Exclude Holidays" (which reads the same table) sees it too. ──
  async function handleAddHoliday(holiday) {
    try {
      await upsertPayrollHolidays([{ date: holiday.date, name: holiday.name }]);
      await loadHolidays();
      addToast?.("Holiday added.", "success");
    } catch (err) {
      addToast?.(err.message || "Failed to add holiday.", "error");
    }
  }

  async function handleDeleteHoliday(id) {
    try {
      await deletePayrollHoliday(id);
      await loadHolidays();
      addToast?.("Holiday removed.", "success");
    } catch (err) {
      addToast?.(err.message || "Failed to remove holiday.", "error");
    }
  }

  const pendingCount = requests.filter((r) => r.status === "pending").length;

  return (
    <div className="bg-background min-h-screen p-6 lg:p-8 space-y-6">

      {/* ── Page Header ── */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-[12px] bg-primary flex items-center justify-center shadow-[0_2px_8px_rgba(25,197,138,0.3)]">
            <BookOpen size={20} className="text-white" />
          </div>
          <div>
            <h1 className="text-[28px] font-extrabold tracking-tight text-foreground">Leave Management</h1>
            <p className="text-[13px] font-medium text-foreground-muted">Paid &amp; Unpaid leave tracking — leave days affect payroll deductions</p>
          </div>
        </div>
        <button
          onClick={openApplyModal}
          className="flex items-center gap-2 bg-primary rounded-[12px] px-5 py-2.5 text-[13px] font-bold text-white transition-all duration-200 hover:bg-primary-hover shadow-[0_2px_8px_rgba(25,197,138,0.3)] hover:shadow-[0_4px_14px_rgba(25,197,138,0.4)] hover:-translate-y-[1px]"
        >
          <Plus size={15} /> Apply Leave
        </button>
      </div>

      {/* ── Leave Type Balance Cards ── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 md:gap-4">
        {balanceCards.map((card) => (
          <div key={card.key} onClick={() => setActiveTab(card.key)} className="bg-surface border border-border rounded-[18px] p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)] transition-all duration-200 hover:shadow-[0_8px_24px_rgba(0,0,0,0.06)] dark:hover:shadow-[0_8px_24px_rgba(0,0,0,0.3)] hover:-translate-y-0.5 cursor-pointer">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <span className="text-[18px]">{card.icon}</span>
                <span className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">{card.label}</span>
              </div>
              <span className="text-[12px] font-bold" style={{ color: card.color }}>{card.pct}%</span>
            </div>
            {loading ? (
              <div className="space-y-2">
                <div className="w-20 h-7 bg-border rounded-[10px] animate-pulse" />
                <div className="w-full h-2 bg-border rounded-full animate-pulse" />
              </div>
            ) : (
              <>
                <p className="text-[26px] font-extrabold text-foreground leading-none">
                  {card.used}<span className="text-[16px] font-bold text-foreground-muted">/{card.total}</span>
                </p>
                <p className="text-[12px] text-foreground-muted mt-1">
                  {card.used} used · {card.remaining} remaining
                </p>
                <div className="mt-3 h-1.5 bg-border rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{ width: `${Math.min(card.pct, 100)}%`, backgroundColor: card.color }}
                  />
                </div>
              </>
            )}
          </div>
        ))}
      </div>

      {/* ── Tab Bar ── */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="bg-surface-muted rounded-[14px] p-1 flex">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id)}
              className={`flex items-center gap-1.5 px-4 py-2 rounded-[12px] text-[13px] font-medium transition-all duration-200 ${
                activeTab === t.id
                  ? "bg-surface shadow-[0_1px_3px_rgba(0,0,0,0.08)]"
                  : "text-foreground-muted hover:text-foreground-muted"
              }`}
              style={activeTab === t.id && t.color ? { color: t.color } : activeTab === t.id ? { color: "var(--color-primary)" } : undefined}
            >
              {t.label}
              {t.id === "requests" && pendingCount > 0 && (
                <span className="ml-1 px-1.5 py-0.5 rounded-full bg-warning/15 text-warning text-[10px] font-bold">{pendingCount}</span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* ── Tab Content ── */}
      {activeTab === "requests" && (
        <LeaveRequestsTab
          requests={requests}
          onApprove={handleApprove}
          onReject={handleReject}
        />
      )}

      {activeTab === "holidays" && (
        <HolidaysTab
          holidays={allHolidays}
          year={currentYear}
          jurisdictionCountry={jurisdictionCountry}
          onAdd={handleAddHoliday}
          onDelete={handleDeleteHoliday}
        />
      )}

      {activeTab === "balances" && (
        <LeaveBalancesTab
          employees={employees}
          allocations={allocations}
        />
      )}

      {["paid", "unpaid", "sick", "compOff"].includes(activeTab) && (
        <LeaveTypeTab
          typeKey={activeTab}
          typeInfo={LEAVE_TYPE_MAP[activeTab]}
          requests={requests}
          allocations={allocations}
          employees={employees}
          onApprove={handleApprove}
          onReject={handleReject}
        />
      )}

      {/* ── Apply Leave Modal ── */}
      {showApplyModal && (
        <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-background/40 backdrop-blur-sm p-4">
          <div className="bg-surface rounded-[18px] shadow-[0_24px_48px_rgba(0,0,0,0.15)] w-full max-w-md p-6 mx-auto">
            {/* Header */}
            <div className="flex items-center justify-between mb-5">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-[10px] bg-primary/10 flex items-center justify-center">
                  <Plus size={16} className="text-primary" />
                </div>
                <h3 className="text-[15px] font-bold text-foreground">Apply Leave</h3>
              </div>
              <button
                onClick={closeApplyModal}
                className="rounded-[10px] p-1.5 text-foreground-muted hover:bg-background dark:hover:bg-surface-muted hover:text-foreground-muted transition-colors"
                aria-label="Close"
              >
                <X size={16} />
              </button>
            </div>

            <div className="space-y-4">
              {/* Employee */}
              <div>
                <label className="text-[11px] font-bold text-foreground-muted uppercase tracking-widest mb-1.5 block">Employee</label>
                <select
                  value={applyForm.employeeId}
                  onChange={(e) => setApplyForm((f) => ({ ...f, employeeId: e.target.value }))}
                  className="w-full rounded-[12px] border border-border bg-background px-3.5 py-2.5 text-[13px] text-foreground placeholder:text-foreground-muted focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200 cursor-pointer"
                >
                  <option value="">Select employee…</option>
                  {employees.map((e) => (
                    <option key={e.id} value={e.id}>{e.name}</option>
                  ))}
                </select>
              </div>

              {/* Leave Type */}
              <div>
                <label className="text-[11px] font-bold text-foreground-muted uppercase tracking-widest mb-1.5 block">Leave Type</label>
                <div className="grid grid-cols-2 gap-2">
                  {LEAVE_TYPES.map((lt) => (
                    <button
                      key={lt.key}
                      type="button"
                      onClick={() => setApplyForm((f) => ({ ...f, leaveType: lt.key }))}
                      className={`flex items-center justify-center gap-2 rounded-[12px] border-2 py-2.5 text-[13px] font-semibold transition-all duration-200 ${
                        applyForm.leaveType === lt.key
                          ? "border-primary bg-primary/10 text-primary shadow-[0_1px_3px_rgba(0,0,0,0.08)]"
                          : "border-border bg-surface text-foreground-muted hover:border-border hover:bg-background dark:hover:bg-surface-muted"
                      }`}
                    >
                      <span>{lt.icon}</span> {lt.label}
                    </button>
                  ))}
                </div>
                {/* Pay impact hint */}
                <p className={`mt-1.5 text-[11px] font-semibold ${applyForm.leaveType === "unpaid" ? "text-error" : "text-primary"}`}>
                  {applyForm.leaveType === "unpaid" ? "No pay — will be deducted from salary" : "Full pay — no salary deduction"}
                </p>
              </div>

              {/* Date range */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[11px] font-bold text-foreground-muted uppercase tracking-widest mb-1.5 block">From</label>
                  <input
                    type="date"
                    value={applyForm.startDate}
                    onChange={(e) => setApplyForm((f) => ({ ...f, startDate: e.target.value }))}
                    className="w-full rounded-[12px] border border-border bg-background px-3.5 py-2.5 text-[13px] text-foreground placeholder:text-foreground-muted focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200"
                  />
                </div>
                <div>
                  <label className="text-[11px] font-bold text-foreground-muted uppercase tracking-widest mb-1.5 block">To</label>
                  <input
                    type="date"
                    value={applyForm.endDate}
                    onChange={(e) => setApplyForm((f) => ({ ...f, endDate: e.target.value }))}
                    className="w-full rounded-[12px] border border-border bg-background px-3.5 py-2.5 text-[13px] text-foreground placeholder:text-foreground-muted focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200"
                  />
                </div>
              </div>

              {/* Reason */}
              <div>
                <label className="text-[11px] font-bold text-foreground-muted uppercase tracking-widest mb-1.5 block">Reason</label>
                <input
                  type="text"
                  placeholder="e.g. Vacation, medical appointment…"
                  value={applyForm.reason}
                  onChange={(e) => setApplyForm((f) => ({ ...f, reason: e.target.value }))}
                  className="w-full rounded-[12px] border border-border bg-background px-3.5 py-2.5 text-[13px] text-foreground placeholder:text-foreground-muted focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200"
                />
              </div>

              {/* Actions */}
              <div className="flex gap-2 pt-1">
                <button
                  onClick={handleSubmitLeave}
                  disabled={submitting}
                  className="flex-1 bg-primary rounded-[12px] px-4 py-2.5 text-[13px] font-bold text-white transition-all duration-200 hover:bg-primary-hover shadow-[0_2px_8px_rgba(25,197,138,0.3)] hover:shadow-[0_4px_14px_rgba(25,197,138,0.4)] hover:-translate-y-[1px] disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {submitting ? (
                    <span className="flex items-center justify-center gap-2"><Loader2 size={14} className="animate-spin" /> Submitting…</span>
                  ) : (
                    <span className="flex items-center justify-center gap-2"><CheckCircle size={14} /> Submit Request</span>
                  )}
                </button>
                <button
                  onClick={closeApplyModal}
                  className="rounded-[12px] border border-border bg-surface-muted px-4 py-2.5 text-[13px] font-semibold text-foreground-muted transition-all duration-200 hover:border-primary hover:text-primary"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
