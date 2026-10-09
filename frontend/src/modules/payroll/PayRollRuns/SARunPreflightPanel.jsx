import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { getSaRunPreflight } from "../../../service/payrollService";
import SAChecksList, { SAStatusLine } from "../../../components/jurisdiction/saudi_arabia/SAChecksList";

// Saudi Arabia run workspace — preflight (ZP-SA-ENG-001 §16).
// The server dry-runs the engine and decides every check; a BLOCK
// refuses approval server-side (409). Saudi Arabia has no monthly
// PAYE withholding — no tax-clearance hold equivalent.
export default function SARunPreflightPanel({ runId }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    getSaRunPreflight(runId)
      .then((res) => active && setData(res))
      .catch((err) => active && setError(err?.message || "Saudi Arabia preflight could not be loaded."));
    return () => { active = false; };
  }, [runId]);

  if (error) return <p className="mb-5 text-[12px] text-error" role="alert">{error}</p>;
  if (!data) {
    return (
      <div className="mb-5 flex items-center gap-2 text-[12px] text-foreground-muted" role="status">
        <Loader2 size={14} className="animate-spin" /> Running Saudi Arabia preflight…
      </div>
    );
  }
  return (
    <section className="mb-5 rounded-[18px] border border-border p-5" aria-labelledby="sa-preflight-heading">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h4 id="sa-preflight-heading" className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">
          Saudi Arabia preflight
        </h4>
        <p className="text-[12px] text-foreground-muted">
          {data.pack || "no Active pack"} · pay date {data.payDate || "—"} · <SAStatusLine data={data} />
        </p>
      </div>
      {data.status === "BLOCKED" && (
        <p className="mb-3 text-[12px] text-error">Approval is refused until every BLOCK item is resolved.</p>
      )}
      <SAChecksList checks={data.checks} empty="No preflight findings." />
      <p className="mt-3 text-[11px] text-foreground-muted">
        Saudi Arabia has no monthly income-tax withholding (GOSI only); there is no tax-clearance hold equivalent.
      </p>
    </section>
  );
}