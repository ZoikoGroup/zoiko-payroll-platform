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

export function withholdingTerm(country) {
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
          <h3 className="text-[15px] font-bold text-foreground">Active {withholdingTerm(country)} Slabs</h3>
          {loadState === "ready" && (
            <span className="flex items-center gap-1 text-[11px] font-bold text-primary">
              <CheckCircle2 size={12} /> Live from payroll engine
            </span>
          )}
        </div>

        {loadState === "loading" && (
          <div className="bg-surface border border-border rounded-[18px] p-6 flex items-center gap-2 text-[13px] text-foreground-muted shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <Loader2 size={14} className="animate-spin" /> Loading active tax slabs...
          </div>
        )}

        {loadState === "error" && (
          <div className="bg-error/5 border border-error/20 rounded-[18px] p-4 flex items-start gap-3">
            <AlertCircle size={16} className="text-error shrink-0 mt-0.5" />
            <p className="text-[13px] text-error">
              Couldn't load the org's active tax slabs. This is the table {withholdingTerm(country)} is actually
              calculated against — try refreshing before relying on the extracted-document values below.
            </p>
          </div>
        )}

        {loadState === "ready" && activeSlabs.length === 0 && (
          <div className="bg-info/5 border border-info/20 rounded-[18px] p-4 flex items-start gap-3">
            <AlertCircle size={16} className="text-info shrink-0 mt-0.5" />
            <p className="text-[13px] text-info">
              No active tax slabs are configured for this jurisdiction yet.
            </p>
          </div>
        )}

        {loadState === "ready" && activeSlabs.length > 0 && (
          <SlabsTable rows={activeSlabs} caption={`Currently applied when calculating ${withholdingTerm(country)} in this jurisdiction.`} />
        )}
      </div>

      <div>
          <h3 className="text-[15px] font-bold text-foreground mb-2">Extracted From Documents</h3>
        {extractedSlabs.length === 0 ? (
          <div className="bg-surface border border-border rounded-[18px] p-4 flex items-start gap-3 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <AlertCircle size={16} className="text-foreground-muted shrink-0 mt-0.5" />
            <p className="text-[13px] text-foreground-muted">
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

// Exported for the same reason as ContributionRatesTable's RatesTable —
// TaxConfigurationTab.jsx re-presents already-fetched rows under
// jurisdiction-specific labels without a second fetch or API change.
export function SlabsTable({ rows, caption }) {
  return (
    <div className="bg-surface border border-border rounded-[18px] shadow-[0_1px_3px_rgba(0,0,0,0.04)] overflow-hidden">
      <div className="px-6 py-3 border-b border-border">
        <p className="text-[13px] text-foreground-muted">{caption}</p>
      </div>
      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b border-border">
            <th className="px-5 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Min</th>
            <th className="px-5 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Max</th>
            <th className="px-5 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Rate</th>
            <th className="px-5 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Tax Calculation</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((s, i) => (
            <tr key={s.id ?? i} className="hover:bg-background dark:hover:bg-surface-muted transition-colors duration-150">
              <td className="px-5 py-3.5 font-mono text-[13px] text-foreground-muted">{s.min}</td>
              <td className="px-5 py-3.5 font-mono text-[13px] text-foreground-muted">{s.max}</td>
              <td className="px-5 py-3.5">
                <span className="rounded-full px-3 py-1 text-[11px] font-bold bg-warning/10 text-warning">
                  {s.rate}
                </span>
              </td>
              <td className="px-5 py-3.5 text-[13px] text-foreground-muted">{s.tax}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
