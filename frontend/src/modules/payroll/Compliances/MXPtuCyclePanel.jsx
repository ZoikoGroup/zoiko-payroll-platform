import { useCallback, useEffect, useState } from "react";
import {
  allocateMxPtu, approveMxPtuAllocation, approveMxPtuAmount, approveMxPtuExclusion, cancelMxPtuCycle,
  createMxPtuCycle, getMxPtuExclusionReasons, listMxEmployers, listMxPtuCycles, openMxPtuRun, recordMxPtuExclusion,
} from "../../../service/payrollService";
import { Messages, Table, useAction } from "../../../components/jurisdiction/mexico/mxShared";
import { Badge, MiniForm, Panel } from "../../../components/jurisdiction/mexico/employer/employerShared";

const link = "text-[12px] text-primary underline disabled:opacity-40";

// PTU — employee profit sharing (ZP-MX-ENG-001 §17, MX-054–MX-056; Phase 9d).
// One cycle per legal employer and fiscal year. The distributable amount is the
// employer's own figure (its annual declaration) — Zoiko never derives it — and
// a second person approves it. The allocation comes only from committed runs
// and the transcribed rule (S26); operator exclusions only from the transcribed
// catalog, with evidence and a second approver. A PTU run then pays each
// eligible worker on its own (never as ordinary pay).
export default function MXPtuCyclePanel() {
  const [cycles, setCycles] = useState(null);
  const [employers, setEmployers] = useState([]);
  const [reasons, setReasons] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [payDate, setPayDate] = useState("");
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  const { run, error, notice, busy } = useAction(reload);

  useEffect(() => {
    let active = true;
    Promise.all([listMxPtuCycles(), listMxEmployers(), getMxPtuExclusionReasons()])
      .then(([c, e, r]) => { if (active) { setCycles(c); setEmployers(e || []); setReasons(r); setLoadError(null); } })
      .catch((e) => active && setLoadError(e?.message || "The PTU cycles could not be loaded."));
    return () => { active = false; };
  }, [tick]);

  const cycle = (cycles || []).find((c) => c.id === selected) || null;
  const employerName = (id) => employers.find((e) => e.employerId === id)?.legalName || `#${id}`;
  const reasonCodes = (reasons?.reasons || []).map((r) => r.code);

  return (
    <Panel title="PTU (profit sharing)" testId="mx-ptu"
      hint="The distributable amount is the employer's own figure; the allocation follows the transcribed rule and committed runs only.">
      {loadError && <p className="text-[12px] text-error" role="alert">{loadError}</p>}
      {cycles && (
        <Table rows={cycles} empty="No PTU cycle yet." columns={[
          { key: "fiscalYear", label: "Fiscal year" },
          { key: "employer", label: "Employer", render: (r) => employerName(r.employerId) },
          { key: "distributableAmount", label: "Distributable amount" },
          { key: "status", label: "Status", render: (r) => <Badge value={r.status} /> },
          { key: "deadline", label: "Pay by", render: (r) => r.paymentDeadline || "unsourced" },
          { key: "ptuRun", label: "PTU run", render: (r) => (r.ptuRun
            ? `#${r.ptuRun.id} · ${r.ptuRun.status}${r.ptuRun.committed ? " · committed" : ""}` : "—") },
          { key: "act", label: "", render: (r) => (
            <span className="flex flex-wrap items-center gap-2">
              <button type="button" className={link} onClick={() => setSelected(r.id)}>Open</button>
              {r.status === "DRAFT" && (
                <button type="button" className={link} disabled={busy}
                  onClick={() => run(() => approveMxPtuAmount(r.id), "Amount approved.")}>Approve amount (another person)</button>
              )}
              {(r.status === "AMOUNT_APPROVED" || r.status === "ALLOCATED") && (
                <button type="button" className={link} disabled={busy}
                  onClick={() => { setSelected(r.id); run(() => allocateMxPtu(r.id), "Allocated — review, then another person approves."); }}>
                  Allocate
                </button>
              )}
              {r.status === "ALLOCATED" && (
                <button type="button" className={link} disabled={busy}
                  onClick={() => run(() => approveMxPtuAllocation(r.id), "Allocation approved.")}>Approve allocation (another person)</button>
              )}
              {!["DISTRIBUTED", "CANCELLED"].includes(r.status) && !r.ptuRun && (
                <button type="button" className="text-[12px] text-foreground-muted underline" disabled={busy}
                  onClick={() => run(() => cancelMxPtuCycle(r.id, "Cancelled from the Compliance Centre"), "Cancelled.")}>
                  Cancel
                </button>
              )}
            </span>
          ) },
        ]} />
      )}
      <Messages error={error} notice={notice} />
      {cycle && (
        <div className="flex flex-col gap-2 rounded-lg border border-border p-3" data-testid="mx-ptu-cycle">
          <p className="text-[12px] text-foreground-muted">
            Cycle #{cycle.id} · {cycle.fiscalYear} · {employerName(cycle.employerId)} · evidence {cycle.evidenceRef}
            {cycle.residue != null && <> · allocated {cycle.allocatedTotal} + residue {cycle.residue}</>}
            {cycle.ruleSource && <> · rule {cycle.ruleSource}</>}
          </p>
          <Table rows={cycle.allocations} rowKey={(a) => a.employeeId} empty="Not allocated yet." columns={[
            { key: "employeeId", label: "Employee" },
            { key: "qualifyingDays", label: "Days" },
            { key: "daysShare", label: "Days share" },
            { key: "salaryShare", label: "Salary share" },
            { key: "cap", label: "Cap", render: (a) => (a.capApplied ? "applied" : "not applied") },
            { key: "finalAmount", label: "PTU" },
            { key: "exclusion", label: "Excluded", render: (a) => (a.eligible ? "—" : `${a.exclusionReason}${a.exclusionEvidenceRef ? ` (${a.exclusionEvidenceRef})` : ""}`) },
          ]} />
          {cycle.operatorExclusions.length > 0 && (
            <Table rows={cycle.operatorExclusions} rowKey={(e) => e.employeeId} columns={[
              { key: "employeeId", label: "Excluded employee" }, { key: "reason", label: "Reason" },
              { key: "evidenceRef", label: "Evidence" },
              { key: "approved", label: "Approved", render: (e) => (e.approvedById ? "yes" : (
                <button type="button" className={link} disabled={busy}
                  onClick={() => run(() => approveMxPtuExclusion(cycle.id, e.employeeId), "Exclusion approved.")}>
                  Approve (another person)
                </button>
              )) },
            ]} />
          )}
          {cycle.status === "AMOUNT_APPROVED" && (reasonCodes.length > 0 ? (
            <MiniForm testId="mx-ptu-exclusion" submitLabel="Record exclusion" busy={busy}
              fields={[
                { key: "employeeId", label: "Employee id", required: true },
                { key: "reasonCode", label: "Reason (transcribed catalog)", type: "select", options: reasonCodes, required: true },
                { key: "evidenceRef", label: "Evidence reference", required: true },
              ]}
              onSubmit={(s) => run(() => recordMxPtuExclusion(cycle.id, { ...s, employeeId: Number(s.employeeId) }),
                "Exclusion recorded — another person must approve it.")}
            />
          ) : (
            <p className="text-[12px] text-warning" role="status">
              {reasons?.block?.code}: {reasons?.block?.message}
            </p>
          ))}
          {cycle.status === "APPROVED" && !cycle.ptuRun && (
            <span className="flex items-center gap-2">
              <input type="date" aria-label="PTU pay date" className="rounded border border-border px-1 text-[12px]"
                value={payDate} onChange={(e) => setPayDate(e.target.value)} />
              <button type="button" className={link} disabled={busy || !payDate}
                onClick={() => run(() => openMxPtuRun(cycle.id, payDate), "PTU run opened — review and approve it in Payroll Runs.")}>
                Open PTU run
              </button>
            </span>
          )}
        </div>
      )}
      <MiniForm
        testId="mx-new-ptu-cycle" submitLabel="Record PTU cycle" busy={busy}
        fields={[
          { key: "employerId", label: "Legal employer", type: "select", required: true,
            options: employers.map((e) => ({ value: String(e.employerId), label: e.legalName })) },
          { key: "fiscalYear", label: "Fiscal year", required: true },
          { key: "distributableAmount", label: "Distributable amount", required: true },
          { key: "evidenceRef", label: "Evidence (annual declaration)", required: true },
        ]}
        onSubmit={(s) => run(() => createMxPtuCycle({ ...s, employerId: Number(s.employerId), fiscalYear: Number(s.fiscalYear) }),
          "Cycle recorded — another person must approve the amount.")}
      />
    </Panel>
  );
}
