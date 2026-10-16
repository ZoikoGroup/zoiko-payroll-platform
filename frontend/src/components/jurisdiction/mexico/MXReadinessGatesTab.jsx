import { CheckCircle2, CircleAlert, XCircle } from "lucide-react";
import { getMxActivationReadiness, getMxReadiness, listMxPacks } from "../../../service/superAdminService";
import { Messages, Table, card, useLoad } from "./mxShared";

// Go-live gates G1–G8 (spec §22) and, per pack, every activation condition
// with its reason — the answer to "why can't I activate this pack?".
// A [PENDING G2] parameter is a warning, never a block (the engine blocks
// only the affected ZLFN employees, decision 4).
function PackReadiness({ pack }) {
  const [view, error] = useLoad(() => getMxActivationReadiness(pack.id), [pack.id]);
  return (
    <div className={card} data-testid={`mx-activation-${pack.packId}`}>
      <h3 className="mb-1 text-[14px] font-semibold text-foreground">
        {pack.packId} v{pack.version} · {pack.status}
      </h3>
      <Messages error={error} />
      {view && (
        <>
          <p className={`mb-2 text-[12px] font-semibold ${view.activatable ? "text-success" : "text-error"}`}>
            {view.activatable ? "Every Mexico activation condition is met." : "Cannot be activated yet."}
          </p>
          <ul className="flex flex-col gap-1">
            {view.checks.map((c) => (
              <li key={c.key} className="flex items-start gap-2 text-[12px] text-foreground">
                {c.met ? <CheckCircle2 size={14} className="mt-0.5 text-success" /> : <XCircle size={14} className="mt-0.5 text-error" />}
                <span><span className="font-semibold">{c.label}:</span> {c.detail}</span>
              </li>
            ))}
            {view.warnings.map((w) => (
              <li key={w.key} className="flex items-start gap-2 text-[12px] text-warning">
                <CircleAlert size={14} className="mt-0.5" /><span><span className="font-semibold">Warning:</span> {w.detail}</span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[11px] text-foreground-muted">{view.note}</p>
        </>
      )}
    </div>
  );
}

export default function MXReadinessGatesTab() {
  const [data, error] = useLoad(() => getMxReadiness(), []);
  const [packs, packsError] = useLoad(() => listMxPacks(), []);
  return (
    <div className="flex flex-col gap-4">
      <Messages error={error || packsError} />
      {data && (
        <>
          <div className={card}>
            <p className="text-[12px] text-foreground-muted">{data.note}</p>
            <p className="mt-1 text-[12px] text-foreground">Engine {data.engineVersion} · Available: {data.available ? "Yes" : "No"}</p>
          </div>
          <div className={card}>
            <h3 className="mb-2 text-[14px] font-semibold text-foreground">Release gates</h3>
            <Table rows={data.gates} rowKey={(g) => g.gate} columns={[
              { key: "gate", label: "Gate" }, { key: "label", label: "Area" }, { key: "state", label: "State" },
            ]} />
          </div>
        </>
      )}
      {(packs || []).map((p) => <PackReadiness key={p.id} pack={p} />)}
    </div>
  );
}
