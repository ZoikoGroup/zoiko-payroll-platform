import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { getHkRunPreflight } from "../../../service/payrollService";
import HKChecksList, { HKStatusLine } from "../../../components/jurisdiction/hong_kong/HKChecksList";

// Hong Kong run workspace — preflight + exceptions (ZP-HK-ENG-001 §14 /
// HK-014; gap-closure D-8). The server dry-runs the engine and decides every
// check; a BLOCK refuses approval server-side (409). An IR56G hold shows here
// as a payment control — it is never a deduction on the payslip.
export default function HKRunPreflightPanel({ runId }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    getHkRunPreflight(runId)
      .then((res) => active && setData(res))
      .catch((err) => active && setError(err?.message || "Hong Kong preflight could not be loaded."));
    return () => { active = false; };
  }, [runId]);

  if (error) return <p className="mb-5 text-[12px] text-error" role="alert">{error}</p>;
  if (!data) {
    return (
      <div className="mb-5 flex items-center gap-2 text-[12px] text-foreground-muted" role="status">
        <Loader2 size={14} className="animate-spin" /> Running Hong Kong preflight…
      </div>
    );
  }
  const holds = (data.checks || []).filter((c) => c.code?.startsWith("HK_IR56G"));
  return (
    <section className="mb-5 rounded-[18px] border border-border p-5" aria-labelledby="hk-preflight-heading">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h4 id="hk-preflight-heading" className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">
          Hong Kong preflight &amp; exceptions
        </h4>
        <p className="text-[12px] text-foreground-muted">
          {data.pack || "no Active pack"} · pay date {data.payDate || "—"} · <HKStatusLine data={data} />
        </p>
      </div>
      {data.status === "BLOCKED" && (
        <p className="mb-3 text-[12px] text-error">Approval is refused until every BLOCK item is resolved.</p>
      )}
      {holds.length > 0 && (
        <p className="mb-3 rounded-[12px] border border-warning/30 bg-warning/10 px-3 py-2 text-[12px] text-warning">
          {holds.length} IR56G tax-clearance item(s) affect this run. Held monies are a legal hold on payment, not a deduction.
        </p>
      )}
      <HKChecksList checks={data.checks} empty="No preflight findings." />
      <p className="mt-3 text-[11px] text-foreground-muted">
        Salaries Tax is assessed by the IRD on the employee — no income tax is withheld from Hong Kong pay.
      </p>
    </section>
  );
}
