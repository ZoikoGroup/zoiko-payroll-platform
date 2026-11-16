import { useState } from "react";
import {
  approveMyFiling, buildMyAnnualFilings, getMyFiling, listMyFilings, listMySettlements, listMyVariances,
  reconcileMySettlement, recordMyFilingResponse, recordMyFilingSubmission, recordMySettlementPayment,
  resolveMyVariance,
} from "../../../service/payrollService";
import { card, useLoad } from "../../../components/jurisdiction/japan/jpFormat";
import { Table } from "../../../components/jurisdiction/japan/jpShared";
import { btn } from "../../../components/jurisdiction/japan/JPRecordSection";
import { errorText } from "../../../components/jurisdiction/new_zealand/nzOrgOptions";

// Malaysia filings, settlements and reconciliation (ZP-MY-ENG-001 Phase 9;
// MY-021 / MY-022 / MY-028). Monthly PCB, EPF, PERKESO-EIS and HRD payloads and
// the PCB / EPF / PERKESO / HRD liabilities are built when a run is PAID; EA,
// Form E and CP8D for a closed year on request; CP22 / CP22A / CP21 from an
// employer event. Payloads are canonical previews with masked identifiers:
// approval needs an archived authority layout (none is archived yet) and a
// second person. Nothing is sent from here (decision D-5): a submission, the
// authority's receipt or rejection and every payment are recorded by hand;
// repeating the same reference is the same event, never a duplicate.

const ask = (message) => {
  const value = window.prompt(message);
  return value && value.trim() ? value.trim() : null;
};

function useAction(reload) {
  const [state, setState] = useState({ busy: false, error: null, notice: null });
  const run = async (fn, notice) => {
    setState({ busy: true, error: null, notice: null });
    try {
      await fn();
      setState({ busy: false, error: null, notice });
      reload();
    } catch (err) {
      setState({ busy: false, error: errorText(err), notice: null });
    }
  };
  return [state, run];
}

function Messages({ state, error }) {
  return (
    <>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {state.error && <p role="alert" className="text-[12px] text-error">{state.error}</p>}
      {state.notice && <p role="status" className="text-[12px] text-success">{state.notice}</p>}
    </>
  );
}

function Filings() {
  const [rows, error, loading, reload] = useLoad(() => listMyFilings());
  const [state, run] = useAction(reload);
  const [preview, setPreview] = useState(null);
  const [year, setYear] = useState(String(new Date().getFullYear() - 1));

  const actions = (r) => {
    if (r.status === "DRAFT") {
      return (
        <div className="flex flex-wrap gap-1">
          <button type="button" className={btn} disabled={state.busy || !r.schemaArchived}
            title={r.schemaArchived ? "" : "No archived authority layout yet (MY-022)"}
            onClick={() => run(() => approveMyFiling(r.id), "Filing approved.")}>Approve</button>
        </div>
      );
    }
    if (r.status === "APPROVED") {
      return (
        <button type="button" className={btn} disabled={state.busy} onClick={() => {
          const ref = ask("Submission reference (from the HASiL / KWSP / PERKESO / HRD Corp channel)");
          if (ref) run(() => recordMyFilingSubmission(r.id, ref), "Submission recorded.");
        }}>Record submission</button>
      );
    }
    if (r.status === "SUBMITTED") {
      return (
        <div className="flex flex-wrap gap-1">
          <button type="button" className={btn} disabled={state.busy} onClick={() => {
            const receiptRef = ask("Receipt / acknowledgement reference");
            if (receiptRef) run(() => recordMyFilingResponse(r.id, { outcome: "ACCEPTED", receiptRef }), "Acceptance recorded.");
          }}>Accepted</button>
          <button type="button" className={btn} disabled={state.busy} onClick={() => {
            const codes = ask("Rejection error codes (comma separated)");
            if (codes) {
              run(() => recordMyFilingResponse(r.id, { outcome: "REJECTED", errorCodes: codes.split(",") }),
                "Rejection recorded; payroll is unchanged.");
            }
          }}>Rejected</button>
        </div>
      );
    }
    return "—";
  };

  return (
    <section className={card} data-testid="my-filings">
      <h3 className="text-[14px] font-semibold text-foreground">Filings (canonical payloads)</h3>
      <p className="mb-2 text-[12px] text-foreground-muted">
        No live transport: payloads are generated and versioned here, submitted outside the platform and their
        outcome recorded. Approval stays blocked until the official authority layout is archived.
      </p>
      <Messages state={state} error={error} />
      <div className="mb-2 flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-[11px] font-semibold text-foreground-muted">
          Year
          <input className="rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground"
            value={year} onChange={(e) => setYear(e.target.value)} inputMode="numeric" aria-label="Tax year" />
        </label>
        <button type="button" className={btn} disabled={state.busy}
          onClick={() => run(() => buildMyAnnualFilings(Number(year), null), "EA / Form E / CP8D built.")}>
          Build EA / Form E / CP8D
        </button>
      </div>
      {loading ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        <Table rows={rows} empty="No Malaysia filings yet — they are built when a run is paid."
          columns={[
            { label: "Form", key: "formCode" }, { label: "Period", key: "periodKey" },
            { label: "Kind", render: (r) => `${r.kind} v${r.version}` }, { label: "Status", key: "status" },
            { label: "Schema", render: (r) => r.schemaVersion || (r.schemaArchived ? "available" : "not archived") },
            { label: "Due", render: (r) => r.dueOn || "not determined" },
            { label: "Reference", render: (r) => r.receiptRef || r.submissionRef || "—" },
            { label: "Payload", render: (r) => (
              <button type="button" className={btn} onClick={() => getMyFiling(r.id).then(setPreview)
                .catch((e) => run(() => Promise.reject(e)))}>View</button>) },
            { label: "Actions", render: actions },
          ]} />
      )}
      {preview && (
        <div className="mt-3" data-testid="my-filing-preview">
          <div className="flex items-center justify-between">
            <p className="text-[12px] font-semibold text-foreground">
              {preview.formCode} {preview.periodKey} v{preview.version} — hash {preview.payloadHash.slice(0, 12)}…
            </p>
            <button type="button" className={btn} onClick={() => setPreview(null)}>Close</button>
          </div>
          <pre className="mt-1 max-h-72 overflow-auto rounded-lg bg-surface-muted p-2 text-[11px] text-foreground">
            {JSON.stringify(preview.payload, null, 2)}
          </pre>
        </div>
      )}
    </section>
  );
}

function Settlements() {
  const [rows, error, loading, reload] = useLoad(() => listMySettlements());
  const [variances, varianceError, , reloadVariances] = useLoad(() => listMyVariances({ status: "OPEN" }));
  const [state, run] = useAction(() => { reload(); reloadVariances(); });

  const pay = (r) => {
    const amount = ask(`Amount paid for ${r.liabilityType} ${r.periodKey} (RM)`);
    if (!amount) return;
    const paidOn = ask("Payment date (YYYY-MM-DD)");
    if (!paidOn) return;
    const paymentRef = ask("Bank payment reference");
    if (paymentRef) run(() => recordMySettlementPayment(r.id, { amount, paidOn, paymentRef }), "Payment recorded.");
  };

  return (
    <section className={card} data-testid="my-settlements">
      <h3 className="text-[14px] font-semibold text-foreground">Settlements and reconciliation</h3>
      <p className="mb-2 text-[12px] text-foreground-muted">
        PCB, EPF, PERKESO (SOCSO + EIS) and HRD liabilities from the paid payslips. Acceptance of a filing never marks a liability paid; a
        difference becomes a variance that only a second person can resolve.
      </p>
      <Messages state={state} error={error || varianceError} />
      {loading ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        <Table rows={rows} empty="No Malaysia liabilities yet."
          columns={[
            { label: "Liability", key: "liabilityType" }, { label: "Period", key: "periodKey" },
            { label: "Due", key: "amountDue" }, { label: "Paid", key: "paidAmount" },
            { label: "Outstanding", key: "outstanding" }, { label: "Due on", render: (r) => r.dueOn || "not determined" },
            { label: "Status", key: "status" },
            { label: "Actions", render: (r) => (r.status === "RECONCILED" ? "—" : (
              <div className="flex flex-wrap gap-1">
                <button type="button" className={btn} disabled={state.busy} onClick={() => pay(r)}>Record payment</button>
                <button type="button" className={btn} disabled={state.busy}
                  onClick={() => run(() => reconcileMySettlement(r.id), "Reconciliation checked.")}>Reconcile</button>
              </div>
            )) },
          ]} />
      )}
      <div className="mt-3" data-testid="my-variances">
        <p className="text-[12px] font-semibold text-foreground">Open variances</p>
        <Table rows={variances} empty="No open variances."
          columns={[
            { label: "Settlement", render: (v) => `#${v.settlementId}` }, { label: "Kind", key: "kind" },
            { label: "Expected", key: "expected" }, { label: "Actual", key: "actual" },
            { label: "Difference", key: "difference" },
            { label: "Actions", render: (v) => (
              <button type="button" className={btn} disabled={state.busy} onClick={() => {
                const reason = ask("How is this difference explained? (a second person resolves it)");
                if (reason) run(() => resolveMyVariance(v.id, reason), "Variance resolved.");
              }}>Resolve</button>) },
          ]} />
      </div>
    </section>
  );
}

export default function MYFilingSettlementPanel() {
  return (
    <div className="space-y-4">
      <Filings />
      <Settlements />
    </div>
  );
}
