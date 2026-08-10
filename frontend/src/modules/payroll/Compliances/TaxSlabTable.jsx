import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import { fetchTaxSlabs } from "../../../service/payrollService";

// Each country withholds income tax under a different statutory name — this
// table's caption was hardcoded to "TDS" (India's term) regardless of which
// jurisdiction was open.
const WITHHOLDING_TERM_BY_COUNTRY = {
  IN: "TDS",
  US: "Federal Income Tax Withholding",
  UK: "PAYE Income Tax",
  AU: "PAYG Withholding",
  DE: "Lohnsteuer (Wage Tax)",
  CA: "Federal Income Tax Withholding",
};

function withholdingTerm(country) {
  return WITHHOLDING_TERM_BY_COUNTRY[country] || "income tax";
}

export default function TaxSlabTable({ documents = [], country, onStatusChange }) {
  const [activeSlabs, setActiveSlabs] = useState([]);
  const [loadState, setLoadState] = useState("loading");

  useEffect(() => {
    let cancelled = false;
    setLoadState("loading");
    fetchTaxSlabs(country)
      .then((rows) => {
        if (cancelled) return;
        setActiveSlabs(Array.isArray(rows) ? rows : []);
        setLoadState("ready");
      })
      .catch(() => {
        if (!cancelled) setLoadState("error");
      });
    return () => { cancelled = true; };
  }, [country]);

  // Optional — lets a host screen (e.g. the jurisdiction config workspace)
  // reflect this table's own load state in its own progress/summary UI
  // without duplicating the fetch. No-op for callers that don't pass it.
  useEffect(() => {
    onStatusChange?.({ loadState, activeSlabCount: activeSlabs.length });
  }, [loadState, activeSlabs.length, onStatusChange]);

  const extractedSlabs = [];
  documents.forEach((doc) => {
    if (doc.extracted?.taxSlabs?.length > 0) {
      extractedSlabs.push(...doc.extracted.taxSlabs);
    }
  });

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center gap-2 mb-2">
          <h3 className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">Active Income Tax Slabs</h3>
          {loadState === "ready" && (
            <span className="flex items-center gap-1 text-[11px] font-bold text-[#19C58A]">
              <CheckCircle2 size={12} /> Live from payroll engine
            </span>
          )}
        </div>

        {loadState === "loading" && (
          <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-6 flex items-center gap-2 text-[13px] text-[#9E9690] shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <Loader2 size={14} className="animate-spin" /> Loading active tax slabs...
          </div>
        )}

        {loadState === "error" && (
          <div className="bg-[#FF6E86]/5 border border-[#FF6E86]/20 rounded-[18px] p-4 flex items-start gap-3">
            <AlertCircle size={16} className="text-[#FF6E86] shrink-0 mt-0.5" />
            <p className="text-[13px] text-[#FF6E86]">
              Couldn't load the org's active tax slabs. This is the table {withholdingTerm(country)} is actually
              calculated against — try refreshing before relying on the extracted-document values below.
            </p>
          </div>
        )}

        {loadState === "ready" && activeSlabs.length === 0 && (
          <div className="bg-[#35B6F5]/5 border border-[#35B6F5]/20 rounded-[18px] p-4 flex items-start gap-3">
            <AlertCircle size={16} className="text-[#35B6F5] shrink-0 mt-0.5" />
            <p className="text-[13px] text-[#35B6F5]">
              No active tax slabs are configured for this jurisdiction yet.
            </p>
          </div>
        )}

        {loadState === "ready" && activeSlabs.length > 0 && (
          <SlabsTable rows={activeSlabs} caption={`Currently applied when calculating ${withholdingTerm(country)} in this jurisdiction.`} />
        )}
      </div>

      <div>
          <h3 className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8] mb-2">Extracted From Documents</h3>
        {extractedSlabs.length === 0 ? (
          <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-4 flex items-start gap-3 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <AlertCircle size={16} className="text-[#9E9690] shrink-0 mt-0.5" />
            <p className="text-[13px] text-[#9E9690]">
              No tax slabs extracted yet. Upload a compliance document to see slabs here.
            </p>
          </div>
        ) : (
          <SlabsTable
            rows={extractedSlabs}
            caption="Reference only — nothing here is applied to payroll until you promote a row on the Documents tab."
          />
        )}
      </div>
    </div>
  );
}

function SlabsTable({ rows, caption }) {
  return (
    <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] shadow-[0_1px_3px_rgba(0,0,0,0.04)] overflow-hidden">
      <div className="px-6 py-3 border-b border-[#E5E0D9] dark:border-[#38312D]">
        <p className="text-[13px] text-[#9E9690]">{caption}</p>
      </div>
      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b border-[#E5E0D9] dark:border-[#38312D]">
            <th className="px-5 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Min</th>
            <th className="px-5 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Max</th>
            <th className="px-5 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Rate</th>
            <th className="px-5 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Tax Calculation</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[#E5E0D9] dark:divide-[#38312D]">
          {rows.map((s, i) => (
            <tr key={s.id ?? i} className="hover:bg-[#F8F7F4] dark:hover:bg-[#2A2520] transition-colors duration-150">
              <td className="px-5 py-3.5 font-mono text-[13px] text-[#6B6560] dark:text-[#A69B93]">{s.min}</td>
              <td className="px-5 py-3.5 font-mono text-[13px] text-[#6B6560] dark:text-[#A69B93]">{s.max}</td>
              <td className="px-5 py-3.5">
                <span className="rounded-full px-3 py-1 text-[11px] font-bold bg-[#F8A60A]/10 text-[#F8A60A]">
                  {s.rate}
                </span>
              </td>
              <td className="px-5 py-3.5 text-[13px] text-[#6B6560] dark:text-[#A69B93]">{s.tax}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
