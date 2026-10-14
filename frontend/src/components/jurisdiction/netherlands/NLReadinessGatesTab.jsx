import { getNlReadiness } from "../../../service/superAdminService";
import { Messages, Table, card, useLoad } from "./nlShared";

// Go-live gates G1–G8 and owner decisions (spec §19). A gate is SIGNED only
// when its evidence (SourceArtifact NL-GATE-Gn) was reviewed by someone other
// than the uploader. Live Dutch payroll stays unavailable until all are signed.
export default function NLReadinessGatesTab() {
  const [data, error] = useLoad(() => getNlReadiness(), []);
  return (
    <div className="flex flex-col gap-4">
      <Messages error={error} />
      {data && (
        <>
          <div className={card}>
            <p className="text-[12px] text-foreground-muted">{data.note}</p>
            <p className="mt-1 text-[12px] text-foreground">Engine {data.engineVersion} · Available: {data.available ? "Yes" : "No"}</p>
          </div>
          <div className={card}>
            <h3 className="mb-2 text-[14px] font-semibold text-foreground">Gates</h3>
            <Table rows={data.gates} rowKey={(g) => g.gate} columns={[
              { key: "gate", label: "Gate" }, { key: "label", label: "Area" }, { key: "state", label: "State" },
            ]} />
          </div>
          <div className={card}>
            <h3 className="mb-2 text-[14px] font-semibold text-foreground">Owner decisions</h3>
            <Table rows={data.decisions} rowKey={(d) => d.key} columns={[
              { key: "key", label: "Decision" }, { key: "label", label: "Subject" }, { key: "state", label: "State" },
              { key: "evidenceTag", label: "Evidence tag" },
            ]} />
          </div>
        </>
      )}
    </div>
  );
}
