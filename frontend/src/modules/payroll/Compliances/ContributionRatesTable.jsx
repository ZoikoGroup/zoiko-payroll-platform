import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import { fetchContributionRates } from "../../../service/payrollService";

export default function ContributionRatesTable({ documents = [], country }) {
  const [activeRates, setActiveRates] = useState([]);
  const [loadState, setLoadState] = useState("loading");

  useEffect(() => {
    let cancelled = false;
    setLoadState("loading");
    fetchContributionRates(country)
      .then((rows) => {
        if (cancelled) return;
        setActiveRates(Array.isArray(rows) ? rows : []);
        setLoadState("ready");
      })
      .catch(() => {
        if (!cancelled) setLoadState("error");
      });
    return () => { cancelled = true; };
  }, [country]);

  const extractedRows = [];
  documents.forEach((doc) => {
    if (doc.extracted?.contributionRates?.length > 0) {
      extractedRows.push(...doc.extracted.contributionRates);
    }
  });

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center gap-2 mb-2">
          <h3 className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">Active Contribution Rates</h3>
          {loadState === "ready" && (
            <span className="flex items-center gap-1 text-[11px] font-bold text-[#19C58A]">
              <CheckCircle2 size={12} /> Live from payroll engine
            </span>
          )}
        </div>

        {loadState === "loading" && (
          <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-6 flex items-center gap-2 text-[13px] text-[#9E9690] shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <Loader2 size={14} className="animate-spin" /> Loading active rates...
          </div>
        )}

        {loadState === "error" && (
          <div className="bg-[#FF6E86]/5 border border-[#FF6E86]/20 rounded-[18px] p-4 flex items-start gap-3">
            <AlertCircle size={16} className="text-[#FF6E86] shrink-0 mt-0.5" />
            <p className="text-[13px] text-[#FF6E86]">
              Couldn't load the org's active contribution rates. This is the data payroll runs are actually
              calculated against — try refreshing before relying on the extracted-document values below.
            </p>
          </div>
        )}

        {loadState === "ready" && activeRates.length === 0 && (
          <div className="bg-[#35B6F5]/5 border border-[#35B6F5]/20 rounded-[18px] p-4 flex items-start gap-3">
            <AlertCircle size={16} className="text-[#35B6F5] shrink-0 mt-0.5" />
            <p className="text-[13px] text-[#35B6F5]">
              No active contribution rates are configured for this jurisdiction yet.
            </p>
          </div>
        )}

        {loadState === "ready" && activeRates.length > 0 && (
          <RatesTable rows={activeRates} caption="Currently applied to every payslip in this jurisdiction." />
        )}
      </div>

      <div>
          <h3 className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8] mb-2">Extracted From Documents</h3>
        {extractedRows.length === 0 ? (
          <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-4 flex items-start gap-3 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <AlertCircle size={16} className="text-[#9E9690] shrink-0 mt-0.5" />
            <p className="text-[13px] text-[#9E9690]">
              No contribution rates extracted yet. Upload a compliance document to see rates here.
            </p>
          </div>
        ) : (
          <RatesTable
            rows={extractedRows}
            caption="Reference only — nothing here is applied to payroll until you promote a row on the Documents tab."
          />
        )}
      </div>
    </div>
  );
}

function RatesTable({ rows, caption }) {
  return (
    <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] shadow-[0_1px_3px_rgba(0,0,0,0.04)] overflow-hidden">
      <div className="px-6 py-3 border-b border-[#E5E0D9] dark:border-[#38312D]">
        <p className="text-[13px] text-[#9E9690]">{caption}</p>
      </div>
      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b border-[#E5E0D9] dark:border-[#38312D]">
            <th className="px-5 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Component</th>
            <th className="px-5 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Employee Share</th>
            <th className="px-5 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Employer Share</th>
            <th className="px-5 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Total</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[#E5E0D9] dark:divide-[#38312D]">
          {rows.map((r, i) => (
            <tr key={r.id ?? r.label ?? i} className="hover:bg-[#F8F7F4] dark:hover:bg-[#2A2520] transition-colors duration-150">
              <td className="px-5 py-3.5 font-bold text-[#1A1816] dark:text-[#F0EDE8]">{r.label}</td>
              <td className="px-5 py-3.5 text-[#6B6560] dark:text-[#A69B93]">{r.employee}</td>
              <td className="px-5 py-3.5 text-[#6B6560] dark:text-[#A69B93]">{r.employer}</td>
              <td className="px-5 py-3.5 font-bold text-[#1A1816] dark:text-[#F0EDE8]">{r.total}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
