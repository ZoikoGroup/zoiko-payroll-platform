import { useState, useEffect } from "react";
import { Check, Clock, ChevronRight, Loader2 } from "lucide-react";
import { getDashboardRecentRuns } from "../../../service/payrollService";
import { formatCurrency } from "../../../utils/currency";

function fmtCurrency(n, currencyCode) {
  return formatCurrency(n || 0, currencyCode);
}

function StatusBadge({ status }) {
  const isPaid = status === "Paid";
  const isDraft = status === "Draft";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-bold tracking-wide ${
      isPaid
        ? "bg-[#19C58A]/10 text-[#19C58A]"
        : isDraft
          ? "bg-[#F0EDE8] dark:bg-[#38312D] text-[#9E9690]"
          : "bg-[#F8A60A]/10 text-[#F8A60A]"
    }`}>
      {isPaid ? <Check size={11} strokeWidth={3} /> : <Clock size={11} strokeWidth={3} />}
      {status || "Draft"}
    </span>
  );
}

const HEADERS = ["PAY PERIOD", "PAY DATE", "EMPLOYEES", "GROSS", "NET", "STATUS", ""];

export default function RecentActivity({ onViewAll, filter, refreshTick, currencyCode }) {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await getDashboardRecentRuns(filter);
        if (!cancelled) setRuns(Array.isArray(res) ? res : []);
      } catch {
        if (!cancelled) setRuns([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [filter?.year, filter?.month, refreshTick]);

  return (
    <div className="rounded-[18px] border border-[#E5E0D9] dark:border-[#38312D] bg-white dark:bg-[#221D1A] p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
      {/* Header */}
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h3 className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">Recent Payroll Runs</h3>
          <p className="mt-1 text-[12px] font-medium text-[#9E9690]">
            {loading ? "Loading..." : `${runs.length} recent run${runs.length !== 1 ? "s" : ""}`}
          </p>
        </div>
        {onViewAll && (
          <button
            onClick={onViewAll}
            className="inline-flex items-center gap-1.5 rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-white dark:bg-[#2A2520] px-4 py-2 text-[12px] font-semibold text-[#6B6560] dark:text-[#A69B93] transition-all duration-200 hover:border-[#19C58A] hover:text-[#19C58A] hover:shadow-[0_2px_8px_rgba(25,197,138,0.15)]"
          >
            View All <ChevronRight size={13} />
          </button>
        )}
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex items-center justify-center py-14">
          <Loader2 size={22} className="animate-spin text-[#19C58A]" />
        </div>
      ) : runs.length === 0 ? (
        <div className="py-14 text-center">
          <div className="mx-auto mb-3 h-10 w-10 rounded-full bg-[#F0EDE8] dark:bg-[#38312D] flex items-center justify-center">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-[#9E9690]">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
            </svg>
          </div>
          <p className="text-[13px] font-medium text-[#9E9690]">No payroll runs yet</p>
          <p className="mt-1 text-[12px] text-[#9E9690]/70">Create your first run to get started.</p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-[#E5E0D9] dark:border-[#38312D]">
                {HEADERS.map((h) => (
                  <th
                    key={h}
                    className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {runs.map((run, idx) => (
                <tr
                  key={run.id}
                  className={`border-b border-[#F0EDE8] dark:border-[#38312D]/50 transition-all duration-150 hover:bg-[#F8F7F4] dark:hover:bg-[#2A2520] last:border-b-0 cursor-pointer`}
                >
                  <td className="whitespace-nowrap px-4 py-4 text-[13px] font-semibold text-[#1A1816] dark:text-[#F0EDE8]">
                    {run.period || "\u2014"}
                  </td>
                  <td className="whitespace-nowrap px-4 py-4 text-[13px] font-medium text-[#6B6560] dark:text-[#A69B93]">
                    {run.payDate || "\u2014"}
                  </td>
                  <td className="px-4 py-4 text-[13px] font-medium text-[#6B6560] dark:text-[#A69B93]">
                    {run.employees ?? 0}
                  </td>
                  <td className="whitespace-nowrap px-4 py-4 text-[13px] font-semibold text-[#35B6F5]">
                    {fmtCurrency(run.gross, currencyCode)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-4 text-[13px] font-bold text-[#19C58A]">
                    {fmtCurrency(run.net, currencyCode)}
                  </td>
                  <td className="px-4 py-4">
                    <StatusBadge status={run.status} />
                  </td>
                  <td className="px-4 py-4 text-[#9E9690]">
                    <ChevronRight size={15} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
