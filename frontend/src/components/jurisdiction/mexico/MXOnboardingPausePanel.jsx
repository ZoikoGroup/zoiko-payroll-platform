import { useState } from "react";
import {
  approveMxOnboardingChange, getMxOnboardingPause, proposeMxOnboardingChange, withdrawMxOnboardingChange,
} from "../../../service/superAdminService";
import { Messages, Table, btn, card, input, useAction, useLoad } from "./mxShared";

// Phase 10g: the "no new Mexican organisations" switch (runbook §6). One Super
// Admin proposes PAUSE or RESUME, a different one approves. While paused no
// organisation can become Mexican and no pilot grant can be approved;
// organisations that are already Mexican keep running.
export default function MXOnboardingPausePanel() {
  const [data, error, , reload] = useLoad(() => getMxOnboardingPause(), []);
  const { run, error: actError, notice, busy } = useAction(reload);
  const [reason, setReason] = useState("");
  const paused = data?.paused;
  return (
    <div className={card} data-testid="mx-onboarding-pause">
      <h3 className="mb-1 text-[14px] font-semibold text-foreground">New Mexican organisations</h3>
      <p className="mb-2 text-[12px] text-foreground-muted">
        State: <span className="font-semibold text-foreground" data-testid="mx-onboarding-state">{paused ? "PAUSED" : "OPEN"}</span>.
        Pausing stops new organisations becoming Mexican and stops pilot grants; organisations that are already Mexican
        keep running. A different Super Admin approves each change.
      </p>
      <Messages error={error || actError} notice={notice} />
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <input className={input} aria-label="Pause reason" placeholder="Reason" value={reason}
          onChange={(e) => setReason(e.target.value)} />
        <button type="button" className={btn} disabled={busy}
          onClick={() => run(() => proposeMxOnboardingChange({ action: paused ? "RESUME" : "PAUSE", reason }),
            "Proposed — a different Super Admin approves it.")}>
          {paused ? "Propose resume" : "Propose pause"}
        </button>
      </div>
      <Table rows={data?.changes || []} empty="No change yet." columns={[
        { key: "id", label: "Change", render: (c) => `#${c.id}` },
        { key: "action", label: "Action" }, { key: "status", label: "Status" }, { key: "reason", label: "Reason" },
        { key: "act", label: "", render: (c) => (c.status === "PROPOSED" ? (
          <span className="flex gap-2">
            <button type="button" className={btn} disabled={busy}
              onClick={() => run(() => approveMxOnboardingChange(c.id), "Approved.")}>Approve (another Super Admin)</button>
            <button type="button" className={btn} disabled={busy}
              onClick={() => run(() => withdrawMxOnboardingChange(c.id), "Withdrawn.")}>Withdraw</button>
          </span>
        ) : "") },
      ]} />
    </div>
  );
}
