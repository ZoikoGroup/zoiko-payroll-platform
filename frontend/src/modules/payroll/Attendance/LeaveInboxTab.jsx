import { useState, useEffect, useCallback, useMemo } from "react";
import { Mail, RefreshCw, Check, Ban, Loader2, Search } from "lucide-react";
import { useToast } from "../ToastContext";
import { useAuth } from "../../../context/AuthContext";
import { ROLES } from "../../../config/roles";
import { getInboundMessages, ignoreInboundMessage, pollMailboxNow } from "../../../service/payrollService";
import ConvertToLeaveRequestModal from "./ConvertToLeaveRequestModal";

const STATUS_PILL = {
  unmatched: "bg-[#F8A60A]/10 text-[#F8A60A] border-[#F8A60A]/20",
  matched: "bg-[#35B6F5]/10 text-[#35B6F5] border-[#35B6F5]/20",
  converted: "bg-[#19C58A]/10 text-[#19C58A] border-[#19C58A]/20",
  ignored: "bg-[#9E9690]/10 text-[#9E9690] border-[#E5E0D9]",
};

const STATUS_LABEL = {
  unmatched: "Unmatched",
  matched: "Matched",
  converted: "Converted",
  ignored: "Ignored",
};

function formatDateTime(d) {
  if (!d) return "—";
  try {
    return new Date(d).toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch { return d; }
}

// Inbound leave-request emails captured by the IMAP mail receiver — see
// backend/app/modules/payroll/mail/. Nothing here is live-pollable without
// an org admin first entering real IMAP credentials via Policy > Integrations.
export default function LeaveInboxTab() {
  const { addToast } = useToast();
  const { hasRole } = useAuth();
  const canManage = hasRole([ROLES.ADMIN, ROLES.SUPER_ADMIN, ROLES.HR_ADMIN]);

  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [polling, setPolling] = useState(false);
  const [statusFilter, setStatusFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [convertTarget, setConvertTarget] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getInboundMessages();
      setMessages(Array.isArray(data) ? data : []);
    } catch {
      addToast?.("Failed to load leave-request inbox.", "error");
    } finally {
      setLoading(false);
    }
  }, [addToast]);

  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => {
    return messages.filter((m) => {
      if (statusFilter !== "all" && m.status !== statusFilter) return false;
      if (search) {
        const q = search.toLowerCase();
        const from = (m.fromEmail || "").toLowerCase();
        const subject = (m.subject || "").toLowerCase();
        const name = (m.matchedEmployeeName || "").toLowerCase();
        if (!from.includes(q) && !subject.includes(q) && !name.includes(q)) return false;
      }
      return true;
    });
  }, [messages, statusFilter, search]);

  async function handlePollNow() {
    setPolling(true);
    try {
      const result = await pollMailboxNow();
      if (result?.success) {
        addToast?.(result.message || "Mailbox polled.", "success");
        await load();
      } else {
        addToast?.(result?.message || "IMAP isn't configured for this organization yet.", "error");
      }
    } catch {
      addToast?.("Failed to poll mailbox.", "error");
    } finally {
      setPolling(false);
    }
  }

  async function handleIgnore(id) {
    try {
      const updated = await ignoreInboundMessage(id);
      setMessages((prev) => prev.map((m) => (m.id === id ? updated : m)));
      addToast?.("Message marked ignored.", "success");
    } catch {
      addToast?.("Failed to ignore message.", "error");
    }
  }

  const thCls = "px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690] select-none whitespace-nowrap";

  return (
    <div className="space-y-4">
      <div className="rounded-[14px] border border-[#35B6F5]/20 bg-[#35B6F5]/5 px-4 py-3 flex items-start gap-2.5">
        <Mail size={16} className="text-[#35B6F5] mt-0.5 shrink-0" />
        <p className="text-[12px] text-[#6B6560] dark:text-[#A69B93]">
          Employees can email your organization's configured leave-request mailbox directly. Messages that match a
          known employee's email address can be converted into a real leave request below. Set up your mailbox
          under Payroll Policy → Integrations → Notifications.
        </p>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-white dark:bg-[#221D1A] px-3.5 py-2.5 text-[13px] text-[#6B6560] dark:text-[#A69B93] font-medium focus:outline-none focus:border-[#35B6F5] focus:ring-2 focus:ring-[#35B6F5]/20 transition-all duration-200 cursor-pointer"
        >
          <option value="all">All Status</option>
          <option value="unmatched">Unmatched</option>
          <option value="matched">Matched</option>
          <option value="converted">Converted</option>
          <option value="ignored">Ignored</option>
        </select>
        <div className="relative flex-1 min-w-[200px]">
          <Search size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#9E9690] pointer-events-none" />
          <input
            type="text"
            placeholder="Search by sender, subject, or employee…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-white dark:bg-[#221D1A] pl-10 pr-4 py-2.5 text-[13px] text-[#1A1816] dark:text-[#F0EDE8] placeholder:text-[#9E9690] focus:outline-none focus:border-[#35B6F5] focus:ring-2 focus:ring-[#35B6F5]/20 transition-all duration-200"
          />
        </div>
        {canManage && (
          <button
            onClick={handlePollNow}
            disabled={polling}
            className="flex items-center gap-2 rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-white dark:bg-[#221D1A] px-4 py-2.5 text-[13px] font-semibold text-[#6B6560] dark:text-[#A69B93] hover:border-[#35B6F5] hover:text-[#35B6F5] transition-all duration-200 disabled:opacity-50"
            title="Manually check the configured mailbox for new messages"
          >
            {polling ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
            Poll Now
          </button>
        )}
      </div>

      <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] overflow-hidden shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
        <div className="overflow-x-auto">
          <table className="min-w-full table-fixed">
            <thead>
              <tr className="bg-[#F8F7F4] dark:bg-[#2A2520] border-b border-[#E5E0D9] dark:border-[#38312D]">
                <th className={`${thCls} w-52`}>From</th>
                <th className={thCls}>Subject</th>
                <th className={`${thCls} w-40`}>Matched Employee</th>
                <th className={`${thCls} w-40`}>Received</th>
                <th className={`${thCls} w-28`}>Status</th>
                <th className={`${thCls} w-32`}>Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#F0EDE8] dark:divide-[#38312D]/50">
              {loading ? (
                <tr>
                  <td colSpan={6} className="px-6 py-16 text-center">
                    <p className="text-[13px] text-[#9E9690] font-medium">Loading inbox…</p>
                  </td>
                </tr>
              ) : filtered.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-6 py-16 text-center">
                    <div className="flex flex-col items-center">
                      <div className="w-14 h-14 rounded-[14px] bg-[#F0EDE8] dark:bg-[#2A2520] flex items-center justify-center mb-3">
                        <Mail size={22} className="text-[#9E9690]" />
                      </div>
                      <p className="text-[13px] font-semibold text-[#9E9690]">No inbound messages found</p>
                      <p className="text-[12px] text-[#9E9690] mt-1">
                        {canManage ? "Try Poll Now, or check your IMAP settings." : "Nothing to review right now."}
                      </p>
                    </div>
                  </td>
                </tr>
              ) : (
                filtered.map((m, idx) => (
                  <tr key={m.id} className={`transition-colors duration-150 hover:bg-[#F8F7F4] dark:hover:bg-[#2A2520] ${idx % 2 === 0 ? "bg-white dark:bg-[#221D1A]" : "bg-[#F8F7F4]/50 dark:bg-[#2A2520]/50"}`}>
                    <td className="px-4 py-3 text-[13px] font-semibold text-[#1A1816] dark:text-[#F0EDE8] truncate">{m.fromEmail}</td>
                    <td className="px-4 py-3 text-[13px] text-[#6B6560] dark:text-[#A69B93] max-w-[220px] truncate" title={m.subject}>{m.subject || "—"}</td>
                    <td className="px-4 py-3 text-[13px] text-[#6B6560] dark:text-[#A69B93]">{m.matchedEmployeeName || "—"}</td>
                    <td className="px-4 py-3 text-[13px] text-[#6B6560] dark:text-[#A69B93]">{formatDateTime(m.receivedAt)}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center px-2.5 py-1 rounded-full border text-[11px] font-bold ${STATUS_PILL[m.status] || ""}`}>
                        {STATUS_LABEL[m.status] || m.status}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {canManage && (m.status === "matched" || m.status === "unmatched") ? (
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => setConvertTarget(m)}
                            disabled={!m.matchedEmployeeId}
                            title={m.matchedEmployeeId ? "Convert to leave request" : "No matching employee email found"}
                            className="p-1.5 rounded-[10px] bg-[#19C58A]/10 text-[#19C58A] hover:bg-[#19C58A]/20 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                          >
                            <Check size={14} />
                          </button>
                          <button
                            onClick={() => handleIgnore(m.id)}
                            className="p-1.5 rounded-[10px] bg-[#FF6E86]/10 text-[#FF6E86] hover:bg-[#FF6E86]/20 transition-colors"
                            title="Ignore"
                          >
                            <Ban size={14} />
                          </button>
                        </div>
                      ) : (
                        <span className="text-[12px] text-[#9E9690]">—</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {convertTarget && (
        <ConvertToLeaveRequestModal
          message={convertTarget}
          onClose={() => setConvertTarget(null)}
          onConverted={load}
        />
      )}
    </div>
  );
}
