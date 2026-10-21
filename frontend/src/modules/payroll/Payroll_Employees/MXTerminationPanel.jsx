import { useCallback, useEffect, useState } from "react";
import {
  approveMxTermination, cancelMxTermination, getMxTerminationReasons, listMxTerminations, openMxFiniquitoRun,
  recordMxTermination,
} from "../../../service/payrollService";
import { Messages, Table, useAction } from "../../../components/jurisdiction/mexico/mxShared";
import { Badge, MiniForm, Panel } from "../../../components/jurisdiction/mexico/employer/employerShared";
import { blankToNull } from "../../../components/jurisdiction/mexico/employer/employerUtils";

// Termination and finiquito (ZP-MX-ENG-001 §17, MX-057 / MX-058; Phase 9c).
// The reason comes only from the transcribed catalog (S26) — an operator never
// picks a component or a tax treatment. Recorded with evidence by one person,
// approved by another: approval sets the date of leaving and generates the IMSS
// BAJA. The FINIQUITO run pays the proportional aguinaldo, the vacation still
// owed with its premium and the separation components the reason triggers;
// until the rules are transcribed it blocks with a named code.
export default function MXTerminationPanel({ employeeId }) {
  const [rows, setRows] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [payDates, setPayDates] = useState({});
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  const { run, error, notice, busy } = useAction(reload);

  useEffect(() => {
    let active = true;
    Promise.all([listMxTerminations(employeeId), getMxTerminationReasons()])
      .then(([list, reasons]) => { if (active) { setRows(list); setCatalog(reasons); setLoadError(null); } })
      .catch((e) => active && setLoadError(e?.message || "The terminations could not be loaded."));
    return () => { active = false; };
  }, [employeeId, tick]);

  const reasonCodes = (catalog?.reasons || []).map((r) => r.code);
  const live = (rows || []).some((r) => r.status !== "CANCELLED");

  return (
    <Panel title="Termination and finiquito" testId="mx-termination"
      hint="Approving a termination sets the date of leaving and generates the IMSS BAJA. It can be cancelled only before its finiquito run exists.">
      {loadError && <p className="text-[12px] text-error" role="alert">{loadError}</p>}
      {catalog?.block && (
        <p className="text-[12px] text-warning" role="status" data-testid="mx-termination-block">
          {catalog.block.code}: {catalog.block.message}
        </p>
      )}
      {rows && (
        <Table rows={rows} empty="No termination recorded." columns={[
          { key: "terminationDate", label: "Last day" },
          { key: "reasonCode", label: "Reason" },
          { key: "evidenceRef", label: "Evidence" },
          { key: "status", label: "Status", render: (r) => <Badge value={r.status} /> },
          { key: "baja", label: "BAJA", render: (r) => (r.bajaMovementIds.length ? `movement #${r.bajaMovementIds.join(", #")}` : "—") },
          { key: "finiquito", label: "Finiquito run", render: (r) => (r.finiquitoRun
            ? `#${r.finiquitoRun.id} · ${r.finiquitoRun.status}${r.finiquitoRun.committed ? " · committed" : ""}`
            : "—") },
          { key: "act", label: "", render: (r) => (
            <span className="flex flex-wrap items-center gap-2">
              {r.status === "DRAFT" && (
                <button type="button" className="text-[12px] text-primary underline" disabled={busy}
                  onClick={() => run(() => approveMxTermination(r.id), "Approved — the date of leaving is set.")}>
                  Approve (another person)
                </button>
              )}
              {r.status === "APPROVED" && !r.finiquitoRun && (
                <>
                  <input type="date" aria-label="Finiquito pay date" className="rounded border border-border px-1 text-[12px]"
                    value={payDates[r.id] || ""} onChange={(e) => setPayDates((p) => ({ ...p, [r.id]: e.target.value }))} />
                  <button type="button" className="text-[12px] text-primary underline" disabled={busy || !payDates[r.id]}
                    onClick={() => run(() => openMxFiniquitoRun(r.id, payDates[r.id]), "Finiquito run opened.")}>
                    Open finiquito run
                  </button>
                </>
              )}
              {(r.status === "DRAFT" || r.status === "APPROVED") && !r.finiquitoRun && (
                <button type="button" className="text-[12px] text-foreground-muted underline" disabled={busy}
                  onClick={() => run(() => cancelMxTermination(r.id, "Cancelled from the employee screen"), "Cancelled.")}>
                  Cancel
                </button>
              )}
            </span>
          ) },
        ]} />
      )}
      {reasonCodes.length > 0 && !live && (
        <MiniForm
          testId="mx-new-termination" submitLabel="Record termination" busy={busy} error={error} notice={notice}
          initial={{ reasonCode: reasonCodes[0] }}
          fields={[
            { key: "terminationDate", label: "Last day employed", type: "date", required: true },
            { key: "reasonCode", label: "Reason (transcribed catalog)", type: "select", options: reasonCodes, required: true },
            { key: "evidenceRef", label: "Evidence reference", required: true },
            { key: "note", label: "Note" },
          ]}
          onSubmit={(s) => run(() => recordMxTermination(employeeId, blankToNull(s)),
            "Recorded — another person must approve it.")}
        />
      )}
      {(reasonCodes.length === 0 || live) && <Messages error={error} notice={notice} />}
    </Panel>
  );
}
