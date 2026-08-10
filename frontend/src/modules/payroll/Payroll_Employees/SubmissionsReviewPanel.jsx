import React, { useEffect, useState } from "react";
import { Loader2, Check, X, Inbox } from "lucide-react";
import { getFormSubmissions, approveFormSubmission, rejectFormSubmission } from "../../../service/payrollService";
import { useToast } from "../ToastContext";

function fmtValue(v) {
  if (v === null || v === undefined || v === "") return "—";
  return String(v);
}

export default function SubmissionsReviewPanel({ onApplied }) {
  const { addToast } = useToast();
  const [submissions, setSubmissions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [actingId, setActingId] = useState(null);

  const load = () => {
    setLoading(true);
    getFormSubmissions("pending")
      .then(setSubmissions)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  async function handleApprove(id) {
    setActingId(id);
    try {
      await approveFormSubmission(id);
      addToast?.("Submission approved and applied to the employee record.", "success");
      setSubmissions((prev) => prev.filter((s) => s.id !== id));
      onApplied?.();
    } catch (err) {
      addToast?.(err.message || "Could not approve submission.", "error");
    } finally {
      setActingId(null);
    }
  }

  async function handleReject(id) {
    setActingId(id);
    try {
      await rejectFormSubmission(id);
      addToast?.("Submission rejected.", "success");
      setSubmissions((prev) => prev.filter((s) => s.id !== id));
    } catch (err) {
      addToast?.(err.message || "Could not reject submission.", "error");
    } finally {
      setActingId(null);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 size={22} className="animate-spin text-[#19C58A]" />
      </div>
    );
  }

  if (submissions.length === 0) {
    return (
      <div className="text-center py-16">
        <Inbox size={40} className="mx-auto mb-3 text-[#9E9690]/40" />
        <p className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">No pending submissions</p>
        <p className="text-[13px] text-[#9E9690] mt-1">Submitted forms waiting for your review will appear here.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {submissions.map((s) => {
        const isActing = actingId === s.id;
        const changedFields = (s.fields || []).filter((f) => {
          const submitted = s.submittedData?.[f.key];
          return submitted !== undefined && submitted !== "" && submitted !== null;
        });
        return (
          <div key={s.id} className="rounded-[16px] border border-[#E5E0D9] dark:border-[#38312D] p-5">
            <div className="flex items-center justify-between mb-4">
              <div>
                <p className="text-[14px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">{s.employeeName}</p>
                <p className="text-[12px] text-[#9E9690]">{s.formName} · submitted {s.createdAt ? new Date(s.createdAt).toLocaleDateString() : ""}</p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => handleReject(s.id)}
                  disabled={isActing}
                  className="flex items-center gap-1.5 rounded-[10px] border border-[#E5E0D9] dark:border-[#38312D] px-3.5 py-2 text-[12.5px] font-semibold text-[#FF6E86] hover:bg-[#FF6E86]/10 transition-all duration-200 disabled:opacity-50"
                >
                  <X size={13} /> Reject
                </button>
                <button
                  onClick={() => handleApprove(s.id)}
                  disabled={isActing}
                  className="flex items-center gap-1.5 rounded-[10px] bg-[#19C58A] text-white px-3.5 py-2 text-[12.5px] font-bold hover:bg-[#15B07A] transition-all duration-200 disabled:opacity-50"
                >
                  <Check size={13} /> {isActing ? "…" : "Approve"}
                </button>
              </div>
            </div>

            <div className="rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] overflow-hidden">
              <table className="w-full text-[12.5px]">
                <thead>
                  <tr className="bg-[#F8F7F4] dark:bg-[#2A2520]">
                    <th className="px-3.5 py-2 text-left text-[10.5px] font-bold uppercase tracking-widest text-[#9E9690]">Field</th>
                    <th className="px-3.5 py-2 text-left text-[10.5px] font-bold uppercase tracking-widest text-[#9E9690]">Current</th>
                    <th className="px-3.5 py-2 text-left text-[10.5px] font-bold uppercase tracking-widest text-[#19C58A]">Submitted</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#E5E0D9]/50 dark:divide-[#38312D]/50">
                  {changedFields.map((f) => (
                    <tr key={f.key}>
                      <td className="px-3.5 py-2 font-semibold text-[#1A1816] dark:text-[#F0EDE8]">{f.label}</td>
                      <td className="px-3.5 py-2 text-[#9E9690]">{fmtValue(s.currentValues?.[f.key])}</td>
                      <td className="px-3.5 py-2 font-semibold text-[#19C58A]">{fmtValue(s.submittedData?.[f.key])}</td>
                    </tr>
                  ))}
                  {changedFields.length === 0 && (
                    <tr><td colSpan={3} className="px-3.5 py-3 text-center text-[#9E9690]">No fields were filled in.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}
    </div>
  );
}
