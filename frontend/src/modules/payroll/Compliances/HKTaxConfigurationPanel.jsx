import { Loader2 } from "lucide-react";
import { useHkReadiness } from "./HKReadinessPanel";
import { hkLabel } from "../../../components/jurisdiction/hong_kong/hkLabels";

// Hong Kong Organization Compliance > Tax Configuration (gap-closure D-6).
// Hong Kong has no per-organisation slab or rate rows. The calculator resolves
// the platform pack in force, so this view shows exactly that resolved pack
// (from /hong-kong/readiness), read-only. Salaries Tax is never withheld. Its
// bands are shown only because the informational estimate uses them.

const th = "px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-foreground-muted";
const td = "px-3 py-1.5 text-[12px] text-foreground";

function value(p) {
  if (p.flatAmount != null) return `HK$ ${p.flatAmount}`;
  if (p.textValue) return hkLabel(p.textValue);      // e.g. MONTHLY_LEVELS → "Monthly levels"
  const parts = [];
  if (p.ratePct != null) parts.push(`${(Number(p.ratePct) * 100).toFixed(2).replace(/\.00$/, "")}%`);
  if (p.employerRatePct != null) parts.push(`employer ${(Number(p.employerRatePct) * 100).toFixed(2).replace(/\.00$/, "")}%`);
  return parts.join(" · ") || "—";
}

export default function HKTaxConfigurationPanel() {
  const { data, error } = useHkReadiness();
  if (error) return <p className="text-[12px] text-error" role="alert">{error}</p>;
  if (!data) {
    return (
      <div className="flex items-center gap-2 text-[12px] text-foreground-muted" role="status">
        <Loader2 size={14} className="animate-spin" /> Loading the Hong Kong pack in force…
      </div>
    );
  }
  const mpf = (data.parameters || []).filter((p) => p.componentKey.startsWith("hk_mpf"));
  const other = (data.parameters || []).filter((p) => !p.componentKey.startsWith("hk_mpf"));
  const bands = data.salariesTaxBands || [];
  return (
    <div className="space-y-5">
      <div>
        <h3 className="mb-1 text-[15px] font-bold text-foreground">Tax Configuration — Hong Kong</h3>
        <p className="text-[13px] text-foreground-muted">
          {data.pack
            ? `Pack ${data.pack.packId} v${data.pack.version} · year of assessment ${data.pack.yearOfAssessment} · ${data.pack.effectiveFrom} to ${data.pack.effectiveTo || "open"}. Values are platform-governed and read-only.`
            : "No Active Hong Kong pack is in force. Hong Kong payroll is blocked until a Super Admin activates one."}
        </p>
      </div>
      <p className="rounded-[12px] border border-info/20 bg-info/5 px-3 py-2 text-[12px] text-info">
        Salaries Tax is assessed by the IRD on the employee and is never withheld from Hong Kong payroll.
        Only MPF mandatory contributions are deducted.
      </p>
      {[["MPF mandatory contributions", mpf], ["Salaries Tax (informational) and other parameters", other]].map(([title, rows]) => (
        <div key={title}>
          <h4 className="mb-2 text-[14px] font-bold text-foreground">{title}</h4>
          {rows.length === 0 ? (
            <p className="rounded-[18px] border border-dashed border-border-light px-4 py-6 text-center text-[13px] text-foreground-disabled">None in force.</p>
          ) : (
            <div className="overflow-x-auto rounded-[12px] border border-border">
              <table className="w-full">
                <caption className="sr-only">{title}</caption>
                <thead className="bg-surface-muted"><tr><th scope="col" className={th}>Parameter</th><th scope="col" className={th}>Value</th></tr></thead>
                <tbody>
                  {rows.map((p) => (
                    <tr key={p.componentKey} className="border-t border-border">
                      <td className={td} title={`Configuration reference: ${p.componentKey}`}>{p.label}</td>
                      <td className={`${td} tabular-nums`}>{value(p)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ))}
      {bands.length > 0 && (
        <div>
          <h4 className="mb-2 text-[14px] font-bold text-foreground">Salaries Tax bands (estimate only)</h4>
          <div className="overflow-x-auto rounded-[12px] border border-border">
            <table className="w-full">
              <caption className="sr-only">Salaries Tax progressive and standard-rate bands</caption>
              <thead className="bg-surface-muted"><tr><th scope="col" className={th}>Basis</th><th scope="col" className={th}>From (HK$)</th><th scope="col" className={th}>To (HK$)</th><th scope="col" className={th}>Rate</th></tr></thead>
              <tbody>
                {bands.map((b) => (
                  <tr key={`${b.ruleType}-${b.minAmount}`} className="border-t border-border">
                    <td className={td}>{b.ruleType === "HK_SALARIES_TAX_STANDARD" ? "Standard rate" : "Progressive"}</td>
                    <td className={`${td} tabular-nums`}>{b.minAmount}</td>
                    <td className={`${td} tabular-nums`}>{b.maxAmount ?? "and above"}</td>
                    <td className={`${td} tabular-nums`}>{Number(b.ratePct)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
