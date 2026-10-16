import { getBrReadiness } from "../../../service/superAdminService";
import { Messages, Table, card, useLoad, toRows, cell } from "./brShared";

// Go-live gates G1–G8 for Brazil (ZP-BR-ENG-001 §24). A gate is SIGNED only
// when its evidence was reviewed by someone other than the uploader. Live
// Brazilian payroll stays unavailable until all eight are signed — the
// backend refuses AVAILABLE until then (brazil_service.statutory_summary).
export default function BRReadinessGatesTab() {
  const [data, error] = useLoad(() => getBrReadiness(), []);
  const gates = toRows(data?.gates);
  return (
    <div className="flex flex-col gap-4">
      <Messages error={error} />
      {data && (
        <>
          <div className={card}>
            <p className="text-[12px] text-foreground-muted">{data.note}</p>
            <p className="mt-1 text-[12px] text-foreground">
              {data.spec ? `${data.spec} · ` : ""}Engine {data.engineVersion} · Phase {data.phase ?? "—"} · Available: {data.available ? "Yes" : "No"}
            </p>
          </div>
          <div className={card}>
            <h3 className="mb-2 text-[14px] font-semibold text-foreground">Gates</h3>
            <Table rows={gates} rowKey={(g) => g.gate ?? g.key} columns={[
              { key: "gate", label: "Gate", render: cell("gate") },
              { key: "label", label: "Area", render: cell("label") },
              { key: "state", label: "State", render: cell("state") },
            ]} />
          </div>
        </>
      )}
    </div>
  );
}
