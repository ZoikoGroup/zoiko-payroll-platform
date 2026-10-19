import { btn, btnPrimary, card, Messages, Table, useAction } from "../mxShared";
import {
  exportMxMovementWorklist, generateMxMovements, recordMxMovementOutcome, regenerateMxMovement, withdrawMxMovement,
} from "../../../../service/payrollService";
import { DueCell, MarkUnknownButton, PromptButton, Status, UnknownActions } from "./authShared";

// IMSS affiliation movements (MX-025) generated once from committed events.
// The export is a Zoiko worklist for keying into IDSE — not an IDSE file
// (layout X1) — downloaded once and never stored; the NSS is masked here.
export default function MXMovementsPanel({ rows, reload }) {
  const { run, error, notice, busy } = useAction(reload);
  const pending = (rows || []).filter((r) => r.status === "PENDING");
  return (
    <section className={card} data-testid="mx-movements">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-[14px] font-semibold text-foreground">Affiliation movements (alta / baja / modificación)</h3>
        <span className="flex gap-2">
          <button type="button" className={btn} disabled={busy} onClick={() => run(async () => {
            const out = await generateMxMovements();
            if (out.skipped?.length) throw new Error(`${out.created.length} generated; skipped: ${out.skipped.map((s) => `#${s.employeeId} ${s.code}`).join(", ")}`);
          }, "Movements generated from committed events.")}>Generate from committed runs</button>
          <button type="button" className={btnPrimary} disabled={busy || pending.length === 0} data-testid="mx-export-worklist"
            onClick={() => run(() => exportMxMovementWorklist(), "Worklist downloaded — key it into IDSE, then record each outcome here.")}>
            Export worklist ({pending.length})
          </button>
        </span>
      </div>
      <p className="mb-2 text-[11px] text-foreground-muted">
        The worklist is not an IMSS / IDSE file: the official layouts (S12 / S13 / S16) are not transcribed. It contains
        the NSS, is generated on request, audited, and never stored by Zoiko.
      </p>
      <Messages error={error} notice={notice} />
      <Table
        rows={rows}
        empty="No movements yet — generate them from committed runs."
        columns={[
          { key: "type", label: "Type", render: (r) => <span data-testid="mx-movement-row">{r.type}</span> },
          { key: "employeeName", label: "Employee", render: (r) => `${r.employeeName || "—"} · NSS ${r.nssMasked || "—"}` },
          { key: "registroPatronal", label: "Registro patronal" },
          { key: "eventDate", label: "Event date" },
          { key: "sbc", label: "SBC" },
          { key: "due", label: "Due", render: (r) => <DueCell row={r} /> },
          { key: "status", label: "Status", render: (r) => <Status value={r.status} /> },
          { key: "act", label: "", render: (r) => (
            <span className="flex flex-col gap-1">
              {r.status === "PENDING" && !r.unknown && (
                <PromptButton label="Withdraw…" placeholder="Why this movement is not required"
                  onSubmit={(reason) => run(() => withdrawMxMovement(r.id, reason), "Withdrawn.")} />
              )}
              {r.status === "EXPORTED" && (
                <span className="flex flex-wrap gap-1">
                  <PromptButton label="Record FILED…" placeholder="IDSE acuse / folio" testId="mx-movement-filed"
                    onSubmit={(ref) => run(() => recordMxMovementOutcome(r.id, { outcome: "FILED", reference: ref }), "Filed.")} />
                  <MarkUnknownButton kind="movements" row={r} run={run} />
                </span>
              )}
              {r.status === "FILED" && (
                <span className="flex flex-wrap gap-1">
                  <button type="button" className={btn}
                    onClick={() => run(() => recordMxMovementOutcome(r.id, { outcome: "ACCEPTED" }), "Accepted.")}>Accepted (second person)</button>
                  <PromptButton label="Rejected…" placeholder="IMSS rejection reason"
                    onSubmit={(reason) => run(() => recordMxMovementOutcome(r.id, { outcome: "REJECTED", reason }), "Rejected.")} />
                </span>
              )}
              {r.status === "REJECTED" && (
                <button type="button" className={btn} onClick={() => run(() => regenerateMxMovement(r.id), "Re-issued.")}>Re-issue</button>
              )}
              <UnknownActions kind="movements" row={r} run={run} />
            </span>
          ) },
        ]}
      />
    </section>
  );
}
