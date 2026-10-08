import { useEffect, useState } from "react";
import { CheckCircle2, CircleAlert } from "lucide-react";
import { getSwissReadiness } from "../../../service/superAdminService";
import StatusPill from "../../StatusPill";

const QST_STATUS_PILL = { ACTIVE: "active", APPROVED: "approved", REJECTED: "rejected" };

// Switzerland's per-canton readiness, rendered exactly as the backend
// re-derives it on every read (get_ch_readiness -> _canton_status): the
// canton's Active pack, its QST model, its ACTIVE tariff file, and the FAK
// child/education amounts against the federal minimum. A canton is "ready"
// only when all of those hold — never a client-side guess.
//
// The endpoint is org-independent, so this tab renders once regardless of
// which pack is selected; the canton packs themselves are configured in the
// dropdown above (each canton is a jurisdiction_state with its own pack).
export default function CHCantonStatusTab() {
  const [result, setResult] = useState({ key: null, data: null, error: null });
  useEffect(() => {
    let live = true;
    getSwissReadiness()
      .then((data) => { if (live) setResult({ key: "load", data, error: null }); })
      .catch((e) => { if (live) setResult({ key: "load", data: null, error: e?.message || "Failed to load canton status" }); });
    return () => { live = false; };
  }, []);
  if (result.error) return <p role="alert" className="text-xs text-error">{result.error}</p>;
  const cantons = result.data?.cantons;
  if (!cantons) return <p className="text-xs text-foreground-muted">Loading canton status…</p>;

  const readyCount = cantons.filter((c) => c.ready).length;

  return (
    <section aria-labelledby="ch-cantons-heading" className="space-y-3">
      <div>
        <h3 id="ch-cantons-heading" className="text-sm font-semibold text-foreground">
          Canton status <span className="ml-1 text-xs font-normal text-foreground-muted">({readyCount}/26 ready)</span>
        </h3>
        <p className="text-xs text-foreground-muted">
          Each canton is a jurisdiction state with its own tax pack. Ready = an Active pack in force carrying a QST
          model, an ACTIVE tariff file for that canton, and FAK child/education amounts at or above the federal minimum.
        </p>
      </div>
      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border text-left text-foreground-muted">
              <th className="px-3 py-2 font-medium">Canton</th>
              <th className="px-3 py-2 font-medium">Pack</th>
              <th className="px-3 py-2 font-medium">QST model</th>
              <th className="px-3 py-2 font-medium">Tariff file</th>
              <th className="px-3 py-2 font-medium">FAK child / education (CHF)</th>
              <th className="px-3 py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-light">
            {cantons.map((c) => (
              <tr key={c.canton}>
                <td className="px-3 py-2 font-medium text-foreground">
                  {c.canton} <span className="text-foreground-muted">— {c.name}</span>
                </td>
                <td className="px-3 py-2">
                  {c.packId ? (
                    <span className="font-mono">{c.packId}</span>
                    ) : (
                    <span className="text-foreground-disabled">no pack</span>
                  )}
                  {c.packVersion ? <span className="text-foreground-muted"> v{c.packVersion}</span> : null}
                </td>
                <td className="px-3 py-2">
                  {c.qstModel || <span className="text-foreground-disabled">—</span>}
                  {c.annualModel && <span className="ml-1 rounded-full bg-warning-light px-1.5 py-0.5 text-[10px] font-semibold text-warning" title="Jahresmodell — annual tariff model (S9)">annual</span>}
                </td>
                <td className="px-3 py-2">
                  {c.tariffFileId ? (
                    <span className="font-mono">#{c.tariffFileId}</span>
                  ) : (
                    <span className="text-foreground-disabled">none</span>
                  )}
                  {c.tariffFileStatus ? (
                    <StatusPill status={QST_STATUS_PILL[c.tariffFileStatus] || "pending"} label={c.tariffFileStatus} />
                  ) : null}
                </td>
                <td className="px-3 py-2">
                  <span className="font-mono">{c.fak?.child?.amount ?? "—"}</span>
                  <span className="text-foreground-muted"> / </span>
                  <span className="font-mono">{c.fak?.education?.amount ?? "—"}</span>
                  {c.fak?.child && !c.fak.child.aboveMinimum && (
                    <span className="ml-1 text-warning" title={`Federal minimum is ${c.fak.child.federalMinimum ?? "—"}`}>below min</span>
                  )}
                  {c.fak?.education && !c.fak.education.aboveMinimum && (
                    <span className="ml-1 text-warning" title={`Federal minimum is ${c.fak.education.federalMinimum ?? "—"}`}>below min</span>
                  )}
                </td>
                <td className="px-3 py-2">
                  {c.ready
                    ? <span className="flex items-center gap-1 text-success"><CheckCircle2 size={13} /> Ready</span>
                    : <span className="flex items-center gap-1 text-warning"><CircleAlert size={13} /> Not ready</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}