import { useState } from "react";
import { X, Loader2, CheckCircle } from "lucide-react";
import { useToast } from "../ToastContext";
import { convertMessageToLeaveRequest } from "../../../service/payrollService";

const LEAVE_TYPES = [
  { key: "paid", label: "Paid" },
  { key: "unpaid", label: "Unpaid" },
  { key: "sick", label: "Sick" },
  { key: "compOff", label: "Comp-Off" },
];

export default function ConvertToLeaveRequestModal({ message, onClose, onConverted }) {
  const { addToast } = useToast();
  const [leaveType, setLeaveType] = useState("paid");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [reason, setReason] = useState(message?.subject || "");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit() {
    if (!startDate) { addToast?.("Select a start date.", "error"); return; }
    if (!endDate) { addToast?.("Select an end date.", "error"); return; }
    if (endDate < startDate) { addToast?.("End date must be on or after start date.", "error"); return; }

    setSubmitting(true);
    try {
      await convertMessageToLeaveRequest(message.id, {
        leaveType,
        startDate,
        endDate,
        reason,
      });
      addToast?.("Leave request created from email.", "success");
      onConverted?.();
      onClose?.();
    } catch (err) {
      addToast?.(err?.message || "Failed to convert message to a leave request.", "error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-[#1A1816]/40 backdrop-blur-sm p-4" onClick={onClose}>
      <div
        className="bg-white dark:bg-[#221D1A] rounded-[18px] shadow-[0_24px_48px_rgba(0,0,0,0.15)] w-full max-w-md p-6 mx-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-[10px] bg-[#35B6F5]/10 flex items-center justify-center">
              <CheckCircle size={16} className="text-[#35B6F5]" />
            </div>
            <h3 className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">Convert to Leave Request</h3>
          </div>
          <button
            onClick={onClose}
            className="rounded-[10px] p-1.5 text-[#9E9690] hover:bg-[#F8F7F4] dark:hover:bg-[#2A2520] hover:text-[#6B6560] dark:hover:text-[#A69B93] transition-colors"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>

        <div className="mb-4 rounded-[12px] bg-[#F8F7F4] dark:bg-[#1A1816] border border-[#E5E0D9] dark:border-[#38312D] p-3">
          <p className="text-[12px] text-[#9E9690]">From <span className="font-semibold text-[#1A1816] dark:text-[#F0EDE8]">{message?.matchedEmployeeName || message?.fromEmail}</span></p>
          <p className="text-[12px] text-[#9E9690] mt-0.5">Subject: {message?.subject || "—"}</p>
        </div>

        <div className="space-y-4">
          <div>
            <label className="text-[11px] font-bold text-[#9E9690] uppercase tracking-widest mb-1.5 block">Leave Type</label>
            <div className="grid grid-cols-2 gap-2">
              {LEAVE_TYPES.map((lt) => (
                <button
                  key={lt.key}
                  type="button"
                  onClick={() => setLeaveType(lt.key)}
                  className={`rounded-[12px] border-2 py-2 text-[13px] font-semibold transition-all duration-200 ${
                    leaveType === lt.key
                      ? "border-[#35B6F5] bg-[#35B6F5]/10 text-[#35B6F5]"
                      : "border-[#E5E0D9] dark:border-[#38312D] bg-white dark:bg-[#221D1A] text-[#9E9690] hover:border-[#E5E0D9] hover:bg-[#F8F7F4] dark:hover:bg-[#2A2520]"
                  }`}
                >
                  {lt.label}
                </button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] font-bold text-[#9E9690] uppercase tracking-widest mb-1.5 block">From</label>
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="w-full rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-3.5 py-2.5 text-[13px] text-[#1A1816] dark:text-[#F0EDE8] focus:outline-none focus:border-[#35B6F5] focus:ring-2 focus:ring-[#35B6F5]/20 transition-all duration-200"
              />
            </div>
            <div>
              <label className="text-[11px] font-bold text-[#9E9690] uppercase tracking-widest mb-1.5 block">To</label>
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="w-full rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-3.5 py-2.5 text-[13px] text-[#1A1816] dark:text-[#F0EDE8] focus:outline-none focus:border-[#35B6F5] focus:ring-2 focus:ring-[#35B6F5]/20 transition-all duration-200"
              />
            </div>
          </div>

          <div>
            <label className="text-[11px] font-bold text-[#9E9690] uppercase tracking-widest mb-1.5 block">Reason</label>
            <input
              type="text"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="w-full rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-3.5 py-2.5 text-[13px] text-[#1A1816] dark:text-[#F0EDE8] focus:outline-none focus:border-[#35B6F5] focus:ring-2 focus:ring-[#35B6F5]/20 transition-all duration-200"
            />
          </div>

          <div className="flex gap-2 pt-1">
            <button
              onClick={handleSubmit}
              disabled={submitting}
              className="flex-1 bg-[#35B6F5] rounded-[12px] px-4 py-2.5 text-[13px] font-bold text-white transition-all duration-200 hover:bg-[#1FA3E8] shadow-[0_2px_8px_rgba(53,182,245,0.3)] disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {submitting ? (
                <span className="flex items-center justify-center gap-2"><Loader2 size={14} className="animate-spin" /> Converting…</span>
              ) : (
                <span className="flex items-center justify-center gap-2"><CheckCircle size={14} /> Create Leave Request</span>
              )}
            </button>
            <button
              onClick={onClose}
              className="rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-white dark:bg-[#2A2520] px-4 py-2.5 text-[13px] font-semibold text-[#6B6560] dark:text-[#A69B93] transition-all duration-200 hover:border-[#35B6F5] hover:text-[#35B6F5]"
            >
              Cancel
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
