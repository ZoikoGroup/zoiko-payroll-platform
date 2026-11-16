import { useState } from "react";
import {
  decideBeDecision, getBeDecisions, importBeDecisionProposals, listBeDecisionRecords, proposeBeDecision,
} from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";
import { card, useLoad } from "../japan/jpFormat";
import { btn } from "../japan/JPRecordSection";
import { Table } from "../japan/jpShared";
import { ErrorNote } from "../new_zealand/nzShared";

// Owner / specialist decisions. The summary (launch-blocking decisions) is RECORDED once a decision record is
// DECIDED (or legacy reviewed evidence tagged BE-DECISION-<key> exists). Block K3: decision records — a proposal by
// one Super Admin, decided by ANOTHER (the server refuses the proposer); a later decision supersedes the earlier one,
// history kept. A decision changes no content: its linked content rows are entered and signed in the console.

const STATE_TONE = { RECORDED: "text-success", DECIDED: "text-success", SUBMITTED: "text-info", PROPOSED: "text-info",
  OPEN: "text-warning", SUPERSEDED: "text-foreground-muted" };

function DecisionRecord({ entry, onChange }) {
  const [proposal, setProposal] = useState("");
  const [state, setState] = useState({ busy: false, error: null });
  const run = async (fn) => {
    setState({ busy: true, error: null });
    try {
      await fn();
      setState({ busy: false, error: null });
      onChange();
    } catch (e) {
      setState({ busy: false, error: e.message || "Refused." });
    }
  };
  const decide = (row) => {
    const value = window.prompt(`Decided value for ${entry.gapKey}:`, row.proposal || "");
    if (!value || !value.trim()) return;
    const reason = window.prompt("Reason for the decision:");
    if (reason && reason.trim()) run(() => decideBeDecision(row.id, value.trim(), reason.trim()));
  };
  return (
    <details className="rounded-lg border border-border p-2" data-testid={`be-decision-${entry.gapKey}`}>
      <summary className="cursor-pointer text-[12px] text-foreground">
        <span className="font-mono">{entry.gapKey}</span> {entry.question} —{" "}
        <span className={`font-semibold ${STATE_TONE[entry.state] || ""}`}>{entry.state}</span>
        {entry.contentKeys?.length > 0 && (
          <span className="ml-2 text-foreground-muted">
            content: {entry.contentKeys.map((k) => `${k.key}${k.signed ? " (signed)" : " (pending)"}`).join(", ")}
          </span>
        )}
      </summary>
      <ul className="mt-2 space-y-2 text-[11px]">
        {entry.history.map((row) => (
          <li key={row.id} className="rounded border border-border p-2">
            <span className={`font-semibold ${STATE_TONE[row.status] || ""}`}>{row.status}</span>
            <span className="ml-2 text-foreground-muted">
              proposed by #{row.proposedBy}{row.decidedBy ? `, decided by #${row.decidedBy}` : ""}
              {row.supersededBy ? `, superseded by #${row.supersededBy}` : ""}
            </span>
            <p className="mt-1 text-foreground">{row.proposal}</p>
            {row.sources && <p className="text-foreground-muted">Sources: {row.sources}</p>}
            {row.decidedValue && <p className="mt-1 font-semibold text-foreground">Decided: {row.decidedValue}</p>}
            {row.status === "PROPOSED" && (
              <button type="button" className={`${btn} mt-1`} disabled={state.busy} onClick={() => decide(row)}>
                Decide (another person)
              </button>
            )}
          </li>
        ))}
      </ul>
      <div className="mt-2 flex flex-wrap items-end gap-2">
        <label className={`${labelClass} flex-1`}>New proposal
          <input className={inputClass} value={proposal} onChange={(e) => setProposal(e.target.value)} />
        </label>
        <button type="button" className={btn} disabled={state.busy || !proposal.trim()}
          onClick={() => run(() => proposeBeDecision({ gapKey: entry.gapKey, proposal: proposal.trim() }).then(() => setProposal("")))}>
          Propose
        </button>
      </div>
      <ErrorNote message={state.error} />
    </details>
  );
}

export default function BEOwnerDecisionsTab() {
  const [decisions, error, , reloadSummary] = useLoad(getBeDecisions);
  const [records, recordsError, , reloadRecords] = useLoad(listBeDecisionRecords);
  const [state, setState] = useState({ busy: false, error: null, notice: null });
  const reload = () => { reloadSummary(); reloadRecords(); };
  const importProposals = async () => {
    setState({ busy: true, error: null, notice: null });
    try {
      const out = await importBeDecisionProposals();
      setState({ busy: false, error: null, notice: `${(out?.created || []).length} proposal(s) imported (PROPOSED).` });
      reload();
    } catch (e) {
      setState({ busy: false, error: e.message || "Refused.", notice: null });
    }
  };
  if (error) return <ErrorNote message={error} />;
  return (
    <div className="space-y-4">
      <div className={card} data-testid="be-owner-decisions">
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">Owner and specialist decisions</h3>
        <Table rows={decisions || []} rowKey={(row) => row.key} empty="Loading…"
          columns={[
            { label: "Gap", render: (row) => <span className="font-mono">{row.key}</span> },
            { label: "Decision", render: (row) => row.label },
            { label: "Blocks launch", render: (row) => (row.blocksLaunch ? "Yes" : "No") },
            { label: "State", render: (row) => <span className={`font-semibold ${STATE_TONE[row.state] || ""}`}>{row.state}</span> },
          ]} />
      </div>
      <div className={`${card} space-y-2`} data-testid="be-decision-records">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-[14px] font-semibold text-foreground">Decision records</h3>
          <button type="button" className={btn} disabled={state.busy} onClick={importProposals}>Import drafted proposals</button>
        </div>
        <ErrorNote message={recordsError || state.error} />
        {state.notice && <p role="status" className="text-[12px] text-success">{state.notice}</p>}
        {(records || []).map((entry) => <DecisionRecord key={entry.gapKey} entry={entry} onChange={reload} />)}
      </div>
    </div>
  );
}
