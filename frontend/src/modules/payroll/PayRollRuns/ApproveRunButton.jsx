import { useState } from "react";
import { CheckCircle2, Loader2 } from "lucide-react";
import { approveRun } from "../../../service/payrollService";
import { useToast } from "../ToastContext";

export default function ApproveRunButton({ runId, onApproved, disabled = false, className = "" }) {
  const { addToast } = useToast();
  const [approving, setApproving] = useState(false);

  const handleApprove = async (e) => {
    e?.stopPropagation();
    if (approving || disabled) return;
    setApproving(true);
    try {
      await approveRun(runId);
      addToast?.("Payroll run approved successfully.", "success");
      if (onApproved) onApproved(runId);
    } catch {
      addToast?.("Failed to approve payroll run.", "error");
    } finally {
      setApproving(false);
    }
  };

  return (
    <button
      onClick={handleApprove}
      disabled={disabled || approving}
      className={`flex items-center gap-2 rounded-[12px] px-5 py-2.5 text-[13px] font-bold transition-all duration-200 ${
        disabled || approving
          ? "opacity-50 cursor-not-allowed bg-[#F8F7F4] dark:bg-[#2A2520] text-[#9E9690]"
          : "bg-[#19C58A] text-white hover:bg-[#15B07A] shadow-[0_2px_8px_rgba(25,197,138,0.3)] hover:shadow-[0_4px_14px_rgba(25,197,138,0.4)] hover:-translate-y-[1px]"
      } ${className}`}
    >
      {approving ? (
        <Loader2 size={14} className="animate-spin text-[#19C58A]" />
      ) : (
        <CheckCircle2 size={14} />
      )}
      {approving ? "Submitting…" : "Submit Payroll Run"}
    </button>
  );
}
