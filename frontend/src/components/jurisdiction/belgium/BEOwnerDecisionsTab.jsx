import { getBeDecisions } from "../../../service/superAdminService";
import { card, useLoad } from "../japan/jpFormat";
import { Table } from "../japan/jpShared";
import { ErrorNote } from "../new_zealand/nzShared";

// Owner / specialist decisions from the gaps register (read-only): each stays
// OPEN until reviewed evidence tagged BE-DECISION-<key> is recorded (uploader
// and reviewer must differ). The list comes from the backend.

const STATE_TONE = { RECORDED: "text-success", SUBMITTED: "text-info", OPEN: "text-warning" };

export default function BEOwnerDecisionsTab() {
  const [decisions, error] = useLoad(getBeDecisions);
  if (error) return <ErrorNote message={error} />;
  return (
    <div className={card} data-testid="be-owner-decisions">
      <h3 className="mb-2 text-[14px] font-semibold text-foreground">Owner and specialist decisions</h3>
      <Table rows={decisions || []} rowKey={(row) => row.key} empty="Loading…"
        columns={[
          { label: "Gap", render: (row) => <span className="font-mono">{row.key}</span> },
          { label: "Decision", render: (row) => row.label },
          { label: "Blocks launch", render: (row) => (row.blocksLaunch ? "Yes" : "No") },
          { label: "Evidence tag", render: (row) => <span className="font-mono text-[11px]">{row.evidenceTag}</span> },
          { label: "State", render: (row) => <span className={`font-semibold ${STATE_TONE[row.state] || ""}`}>{row.state}</span> },
        ]} />
    </div>
  );
}
