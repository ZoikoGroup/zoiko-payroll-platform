import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { getHkEmployerReadiness } from "../../../service/payrollService";
import HKChecksList, { HKStatusLine } from "../../../components/jurisdiction/hong_kong/HKChecksList";
import { hkLabel } from "../../../components/jurisdiction/hong_kong/hkLabels";

// Hong Kong payroll readiness (gap-closure D-12). GET /hong-kong/readiness is
// built from the SAME check builders as the run preflight and the calculator's
// own statutory-profile resolution, so this view can never say CLEAR for an
// organisation the payroll run would BLOCK. Read-only.

export function useHkReadiness() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let active = true;
    getHkEmployerReadiness()
      .then((res) => active && setData(res))
      .catch((err) => active && setError(err?.message || "Hong Kong readiness could not be loaded."));
    return () => { active = false; };
  }, []);
  return { data, error };
}

const tile = "rounded-xl border border-border bg-surface p-3";
const tileLabel = "text-[11px] font-semibold uppercase tracking-wide text-foreground-muted";
const tileValue = "mt-1 text-[13px] font-semibold text-foreground";

export default function HKReadinessPanel() {
  const { data, error } = useHkReadiness();
  if (error) return <p className="text-[12px] text-error" role="alert">{error}</p>;
  if (!data) {
    return (
      <div className="flex items-center gap-2 text-[12px] text-foreground-muted" role="status">
        <Loader2 size={14} className="animate-spin" /> Checking Hong Kong readiness…
      </div>
    );
  }
  const reg = data.registration || {};
  return (
    <div className="space-y-4">
      <p className="text-[12px] text-foreground-muted">As of {data.asOf} · <HKStatusLine data={data} /></p>
      {data.status === "BLOCKED" && (
        <p className="text-[12px] text-error">A Hong Kong payroll run cannot be approved until every BLOCK item is resolved.</p>
      )}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className={tile}>
          <p className={tileLabel}>Rule pack in force</p>
          <p className={tileValue}>
            {data.pack ? `${data.pack.packId} v${data.pack.version} · YA ${data.pack.yearOfAssessment}` : "None Active"}
          </p>
        </div>
        <div className={tile}>
          <p className={tileLabel}>Employer registration</p>
          <p className={tileValue}>
            BR {reg.br_number ? "✓" : "✗"} · IRD file {reg.ird_employer_file_number ? "✓" : "✗"} · eMPF {reg.empf_employer_account ? "✓" : "✗"} · EC {reg.ec_insurance_policy_number ? "✓" : "✗"}
          </p>
        </div>
        <div className={tile}>
          <p className={tileLabel}>Workforce</p>
          <p className={tileValue}>
            {data.workforce?.hongKongEmployees ?? 0} employees · {data.workforce?.withoutStatutoryProfile ?? 0} without a profile
          </p>
        </div>
        <div className={tile}>
          <p className={tileLabel}>IRD / eMPF / IR56G</p>
          <p className={tileValue}>
            {data.ird?.openCases ?? 0} open IRD · {data.taxClearance?.openCases ?? 0} IR56G · eMPF {data.empf ? `${data.empf.contributionPeriod} ${hkLabel(data.empf.status)}` : "none yet"}
          </p>
        </div>
      </div>
      <p className="text-[12px] text-foreground-secondary">Salaries Tax: {data.salariesTax}.</p>
      <HKChecksList checks={data.checks} empty="No readiness findings." />
    </div>
  );
}
