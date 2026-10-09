import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { getSaEmployerReadiness } from "../../../service/payrollService";
import SAChecksList, { SAStatusLine } from "../../../components/jurisdiction/saudi_arabia/SAChecksList";

// Saudi Arabia employer readiness (ZP-SA-ENG-001 §16). GET /saudi-arabia/readiness
// is built from the SAME check builders as the run preflight and the
// calculator's own statutory-profile resolution, so this view can never say
// CLEAR for an organisation the payroll run would BLOCK. Read-only.

export function useSaReadiness() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let active = true;
    getSaEmployerReadiness()
      .then((res) => active && setData(res))
      .catch((err) => active && setError(err?.message || "Saudi Arabia readiness could not be loaded."));
    return () => { active = false; };
  }, []);
  return { data, error };
}

const tile = "rounded-xl border border-border bg-surface p-3";
const tileLabel = "text-[11px] font-semibold uppercase tracking-wide text-foreground-muted";
const tileValue = "mt-1 text-[13px] font-semibold text-foreground";

export default function SAReadinessPanel() {
  const { data, error } = useSaReadiness();
  if (error) return <p className="text-[12px] text-error" role="alert">{error}</p>;
  if (!data) {
    return (
      <div className="flex items-center gap-2 text-[12px] text-foreground-muted" role="status">
        <Loader2 size={14} className="animate-spin" /> Checking Saudi Arabia readiness…
      </div>
    );
  }
  return (
    <div className="space-y-4">
      <p className="text-[12px] text-foreground-muted">As of {data.asOf} · <SAStatusLine data={data} /></p>
      {data.status === "BLOCKED" && (
        <p className="text-[12px] text-error">A Saudi Arabia payroll run cannot be approved until every BLOCK item is resolved.</p>
      )}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className={tile}>
          <p className={tileLabel}>Rule pack in force</p>
          <p className={tileValue}>
            {data.pack ? `${data.pack.packId} v${data.pack.version} · year ${data.pack.taxYear || "—"}` : "None Active"}
          </p>
        </div>
        <div className={tile}>
          <p className={tileLabel}>GOSI registration</p>
          <p className={tileValue}>
            GOSI employer # {data.gosi?.employerNumber ? "✓" : "✗"} · MHRSD est. {data.gosi?.establishmentNumber ? "✓" : "✗"} · Mudad {data.gosi?.mudadId ? "✓" : "✗"}
          </p>
        </div>
        <div className={tile}>
          <p className={tileLabel}>Workforce</p>
          <p className={tileValue}>
            {data.workforce?.saudiEmployees ?? 0} Saudi · {data.workforce?.gccEmployees ?? 0} GCC
            · {data.workforce?.nonSaudiEmployees ?? 0} non-Saudi · {data.workforce?.domesticEmployees ?? 0} domestic
          </p>
        </div>
        <div className={tile}>
          <p className={tileLabel}>Statutory profiles</p>
          <p className={tileValue}>
            {data.workforce?.withStatutoryProfile ?? 0} with profile · {data.workforce?.withoutStatutoryProfile ?? 0} without
          </p>
        </div>
      </div>
      <p className="text-[12px] text-foreground-secondary">Monthly income-tax withholding: none (Saudi Arabia has no PAYE; income tax is assessed separately for the few Saudi/GCC nationals it applies to).</p>
      <SAChecksList checks={data.checks} empty="No readiness findings." />
    </div>
  );
}