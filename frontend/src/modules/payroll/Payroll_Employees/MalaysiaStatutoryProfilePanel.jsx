import { useState } from "react";
import { X } from "lucide-react";
import {
  approveMyAssignment, approveMyDeclaration, approveMyHoldRelease, approveMyWorkerProfile, buildMyEventFiling,
  cancelMyEmployerEvent,
  createMyAssignment, createMyDeclaration, createMyEmployerEvent, createMyWorkerProfile, getMyEmployeeSummary,
  getMyHolidays, getMyLeaveEntitlement, listMyAssignments, listMyDeclarations, listMyEmployerEvents,
  listMyWorkerProfiles, openMyClearanceHold, requestMyHoldRelease, submitMyEmployerEvent, withdrawMyDeclaration,
} from "../../../service/payrollService";
import { card } from "../../../components/jurisdiction/japan/jpFormat";
import JPRecordSection, { btn, isDraft, statusCol } from "../../../components/jurisdiction/japan/JPRecordSection";
import { REASON_FIELD, errorText, period } from "../../../components/jurisdiction/new_zealand/nzOrgOptions";
import {
  ASSIGNMENT_REASONS, CITIZENSHIP, CONTRACT_TYPES, DECLARATION_TYPES, EIS_STATES, EPF_MEMBER_CLASSES, EVENT_TYPES,
  HOLIDAY_STATES, PAY_FREQUENCIES, REST_DAYS, SOCSO_CATEGORIES, SOURCE_CHANNELS, TAX_RESIDENCE, TERRITORIES,
  WORK_PASS_TYPES, declarationPayload,
} from "../../../components/jurisdiction/malaysia/myOrgOptions";
import MYIdentifierField from "./MYIdentifierField";

// Every Malaysia record for one employee (ZP-MY-ENG-001 §4-§11). Versioned
// facts are captured as DRAFT with a reason and count only after a SECOND
// user approves them; declarations are captured as RECEIVED with their
// evidence (MY-010). The engine selects by the pay date / period and BLOCKS
// the affected obligation while a fact it needs is missing (MY-008) — coverage
// is never inferred, tax residence never follows citizenship (MY-007).

const periodCol = { label: "In force", render: period };
const ask = (message) => {
  const value = window.prompt(message);
  return value && value.trim() ? value.trim() : null;
};
const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";

function LeaveAndHolidays({ employeeId }) {
  const [asOf, setAsOf] = useState(new Date().toISOString().slice(0, 10));
  const [leave, setLeave] = useState(null);
  const [holidays, setHolidays] = useState(null);
  const load = async () => {
    setLeave(await getMyLeaveEntitlement(employeeId, asOf).catch((e) => ({ error: errorText(e) })));
    setHolidays(await getMyHolidays(employeeId, asOf.slice(0, 4)).catch((e) => ({ error: errorText(e) })));
  };
  return (
    <section className={card} data-testid="my-leave-holidays">
      <h3 className="text-[14px] font-semibold text-foreground">Leave and public holidays (by territory)</h3>
      <p className="mb-2 text-[12px] text-foreground-muted">
        Read-only views from the employee&apos;s work assignment and the signed territorial rules; refused with the
        reason when a fact or a signed rule is missing — never a guessed figure.
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <input className={input} type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} aria-label="As of" />
        <button type="button" className={btn} onClick={load}>Show</button>
      </div>
      {leave && (
        <p className="mt-2 text-[12px]">
          {leave.error ? <span className="text-warning">Leave: {leave.error}</span> : (
            <>{leave.territory}: annual <strong>{leave.annualDays}</strong>, sick <strong>{leave.sickDays}</strong>,
              hospitalisation {leave.hospitalisationDays}, maternity {leave.maternityDays}, paternity {leave.paternityDays}
              {" "}days (service {leave.serviceYears} years)</>
          )}
        </p>
      )}
      {holidays && (
        <div className="mt-2 text-[12px]">
          {holidays.error ? <span className="text-warning">Holidays: {holidays.error}</span> : (
            <>
              <p>{holidays.holidayState} ({holidays.territory}) — {holidays.holidays.length} holiday(s) in {holidays.year}</p>
              <ul className="text-foreground-muted">{holidays.holidays.map((h) => <li key={h.date}>{h.date} · {h.name}</li>)}</ul>
            </>
          )}
        </div>
      )}
    </section>
  );
}

function ClearanceHolds({ employeeId }) {
  const [summary, setSummary] = useState(null);
  const [state, setState] = useState({ error: null, notice: null });
  const load = () => getMyEmployeeSummary(employeeId).then(setSummary).catch((e) => setState({ error: errorText(e) }));
  const act = async (fn, notice) => {
    try { await fn(); setState({ error: null, notice }); load(); } catch (e) { setState({ error: errorText(e), notice: null }); }
  };
  const holds = summary?.clearanceHolds || [];
  return (
    <section className={card} data-testid="my-clearance-holds">
      <h3 className="text-[14px] font-semibold text-foreground">Tax-clearance holds (MY-020)</h3>
      <p className="mb-2 text-[12px] text-foreground-muted">
        Cash due to a departing employee is held until HASiL&apos;s clearance or the signed maximum hold date. Held money
        remains owed to the employee — it is left out of the bank file, never deducted. A release needs HASiL&apos;s
        letter and a second user.
      </p>
      <button type="button" className={btn} onClick={load}>{summary ? "Refresh" : "Show holds"}</button>
      {state.error && <p role="alert" className="mt-2 text-[12px] text-error">{state.error}</p>}
      {state.notice && <p role="status" className="mt-2 text-[12px] text-success">{state.notice}</p>}
      {summary && holds.length === 0 && <p className="mt-2 text-[12px] text-foreground-muted">No clearance holds.</p>}
      {holds.map((h) => (
        <div key={h.id} className="mt-2 border-t border-border pt-2 text-[12px]">
          <p>Hold #{h.id} · {h.state} · {h.opened_on} → {h.hold_until} · held {h.heldTotal}</p>
          {h.state === "HELD" && (
            <button type="button" className={btn} onClick={() => act(async () => {
              const ref = ask("HASiL clearance letter reference");
              const evidence = ref && ask("Evidence reference (scan of the letter)");
              if (!ref || !evidence) throw new Error("The clearance reference and evidence are required.");
              await requestMyHoldRelease(h.id, ref, evidence);
            }, "Release requested — a second user must approve it.")}>Request release</button>
          )}
          {h.state === "RELEASE_REQUESTED" && (
            <button type="button" className={btn} onClick={() => act(() => approveMyHoldRelease(h.id),
              "Released — the held payslips are paid in the run's next bank file.")}>Approve release</button>
          )}
        </div>
      ))}
    </section>
  );
}

export function MalaysiaEmployeeRecords({ employeeId }) {
  const id = employeeId;
  return (
    <div className="space-y-4" data-testid="my-employee-records">
      <JPRecordSection
        title="Worker statutory profile" testId="my-worker-profile"
        description="Contract and pay frequency, citizenship and work pass, reviewed tax residence with evidence (MY-007), EPF member class, SOCSO category and EIS state (unknown blocks that obligation only), manual-worker flag, normal weekly hours, rest day, service start and the vault references."
        load={() => listMyWorkerProfiles(id)} create={(p) => createMyWorkerProfile(id, p)}
        empty="No worker profile — Malaysian payslips are blocked until one is approved."
        columns={[periodCol, { label: "Contract", key: "contract_type" }, { label: "EPF class", key: "epf_member_class" },
          { label: "SOCSO / EIS", render: (r) => `${r.socso_category || "?"} · ${r.eis_state || "?"}` },
          { label: "Residence", key: "tax_residence" }, statusCol]}
        actions={[{ label: "Approve", show: isDraft, run: (r) => approveMyWorkerProfile(r.id), ok: "Worker profile approved." }]}
        fields={[
          { key: "effective_from", label: "Effective from", type: "date", required: true },
          { key: "contract_type", label: "Contract type", type: "select", options: CONTRACT_TYPES, required: true },
          { key: "pay_frequency", label: "Pay frequency", type: "select", options: PAY_FREQUENCIES, required: true },
          { key: "citizenship", label: "Citizenship", type: "select", options: CITIZENSHIP },
          { key: "date_of_birth", label: "Date of birth", type: "date" },
          { key: "tax_residence", label: "Tax residence (reviewed)", type: "select", options: TAX_RESIDENCE },
          { key: "residence_evidence_ref", label: "Residence evidence" },
          { key: "residence_from", label: "Residence from", type: "date" },
          { key: "work_pass_type", label: "Work pass type", type: "select", options: WORK_PASS_TYPES },
          { key: "work_pass_valid_from", label: "Work pass valid from", type: "date" },
          { key: "work_pass_valid_to", label: "Work pass valid to", type: "date" },
          { key: "epf_member_class", label: "EPF member class", type: "select", options: EPF_MEMBER_CLASSES },
          { key: "socso_category", label: "SOCSO category", type: "select", options: SOCSO_CATEGORIES },
          { key: "eis_state", label: "EIS state", type: "select", options: EIS_STATES },
          { key: "manual_worker", label: "Manual worker", type: "bool" },
          { key: "normal_hours_week", label: "Normal weekly hours", type: "number" },
          { key: "rest_day", label: "Rest day", type: "select", options: REST_DAYS },
          { key: "service_start", label: "Service start", type: "date" },
          { key: "nric_vault_id", label: "NRIC vault id", type: "number" },
          { key: "tin_vault_id", label: "TIN vault id", type: "number" },
          { key: "epf_vault_id", label: "EPF no. vault id", type: "number" },
          { key: "socso_vault_id", label: "SOCSO no. vault id", type: "number" },
          { key: "work_pass_vault_id", label: "Work pass vault id", type: "number" },
          { key: "evidence_ref", label: "Evidence reference" },
          REASON_FIELD,
        ]} />

      <JPRecordSection
        title="Work assignment (labour territory + holiday state)" testId="my-work-assignments"
        description="Where the employee works decides the labour law (Peninsular + Labuan, Sabah, Sarawak) and the state holiday calendar (MY-001 / MY-003). A conflicting state and territory is refused; a transfer is a new version."
        load={() => listMyAssignments(id)} create={(p) => createMyAssignment(id, p)}
        empty="No work assignment — the LABOUR obligation is blocked until one is approved."
        columns={[periodCol, { label: "Territory", key: "labour_territory" }, { label: "State", key: "holiday_state" },
          { label: "Reason", key: "assignment_reason" }, statusCol]}
        actions={[{ label: "Approve", show: isDraft, run: (r) => approveMyAssignment(r.id), ok: "Work assignment approved." }]}
        fields={[
          { key: "effective_from", label: "Effective from", type: "date", required: true },
          { key: "labour_territory", label: "Labour territory", type: "select", options: TERRITORIES, required: true },
          { key: "holiday_state", label: "Holiday state", type: "select", options: HOLIDAY_STATES, required: true },
          { key: "assignment_reason", label: "Reason", type: "select", options: ASSIGNMENT_REASONS, required: true },
          { key: "work_location_label", label: "Work location" },
          { key: "remote", label: "Remote", type: "bool" },
          { key: "evidence_ref", label: "Evidence reference" },
          REASON_FIELD,
        ]} />

      <JPRecordSection
        title="Tax declarations (TP1, TP3, CP38, zakat, tax borne, EPF voluntary excess)" testId="my-declarations"
        description="Each declaration keeps its received date, channel and evidence and covers one tax year (MY-010). A second user approves it; an approved TP3 posts the prior employer's figures to the year-to-date ledger. How PCB uses them follows the HASiL specification (Phase 4)."
        load={() => listMyDeclarations(id)} create={(p) => createMyDeclaration(id, p)} transform={declarationPayload}
        createLabel="Record as RECEIVED" createdNotice="Recorded — a second user must approve it."
        empty="No declarations."
        columns={[periodCol, { label: "Type", key: "declaration_type" }, { label: "Tax year", key: "tax_year" },
          { label: "Value", render: (r) => (r.value && Object.keys(r.value).length ? JSON.stringify(r.value) : "—") },
          { label: "Received", render: (r) => String(r.received_at || "").slice(0, 10) }, statusCol]}
        actions={[
          { label: "Approve", show: (r) => r.status === "RECEIVED", run: (r) => approveMyDeclaration(r.id), ok: "Declaration approved." },
          { label: "Withdraw", show: (r) => r.status === "APPROVED" && r.declaration_type !== "TP3", ok: "Declaration withdrawn.",
            run: async (r) => {
              const reason = ask("Reason for the withdrawal");
              const end = reason && ask("Last day the declaration applies (YYYY-MM-DD)");
              if (!reason || !end) throw new Error("A reason and an end date are required.");
              await withdrawMyDeclaration(r.id, reason, end);
            } },
        ]}
        fields={[
          { key: "declaration_type", label: "Declaration", type: "select", options: DECLARATION_TYPES, required: true },
          { key: "received_at", label: "Received on", type: "date", required: true },
          { key: "effective_from", label: "Effective from", type: "date", required: true },
          { key: "effective_to", label: "Effective to (optional, same tax year)", type: "date" },
          { key: "source_channel", label: "Channel", type: "select", options: SOURCE_CHANNELS, required: true },
          { key: "evidence_ref", label: "Evidence reference", required: true },
          { key: "amount", label: "Amount (CP38 / zakat)", type: "number" },
          { key: "instructionRef", label: "CP38 HASiL reference" },
          { key: "ratePct", label: "EPF voluntary excess %", type: "number" },
          { key: "priorEmployer", label: "TP3 prior employer" },
          { key: "accumulatorsJson", label: "TP3 accumulators (JSON)" },
          { key: "claimsJson", label: "TP1 claims (JSON)" },
        ]} />

      <JPRecordSection
        title="Employer events (CP22, CP22A, CP21, death notice)" testId="my-employer-events"
        description="The due date comes from the signed pack (empty until signed — the run is then refused). The HASiL receipt is recorded by a second user. A CP22A / CP21 that requires tax clearance needs its hold opened before final pay (MY-019 / MY-020)."
        load={() => listMyEmployerEvents(id)} create={(p) => createMyEmployerEvent(id, p)}
        empty="No employer events."
        columns={[{ label: "Type", key: "event_type" }, { label: "Event date", key: "event_date" },
          { label: "Due", render: (r) => r.due_date || <span className="text-warning">{r.due_rule || "not computable"}</span> },
          { label: "Clearance", render: (r) => (r.clearance_required ? "Required" : "—") },
          { label: "Receipt", render: (r) => r.receipt_ref || "—" }, statusCol]}
        actions={[
          { label: "Record submission", show: (r) => r.status === "OPEN", ok: "Submission recorded.",
            run: async (r) => {
              const on = ask("Submitted on (YYYY-MM-DD)");
              const receipt = on && ask("HASiL receipt reference");
              const evidence = receipt && ask("Evidence reference");
              if (!on || !receipt || !evidence) throw new Error("The date, receipt and evidence are required.");
              await submitMyEmployerEvent(r.id, on, receipt, evidence);
            } },
          { label: "Open clearance hold", show: (r) => r.clearance_required && r.status !== "CANCELLED", ok: "Hold opened.",
            run: async (r) => {
              const on = ask("Hold the employee's cash from (YYYY-MM-DD)");
              const reason = on && ask("Reason");
              if (!on || !reason) throw new Error("A start date and a reason are required.");
              await openMyClearanceHold(r.id, on, reason);
            } },
          { label: "Build HASiL form", show: (r) => ["CP22", "CP22A", "CP21"].includes(r.event_type) && r.status !== "CANCELLED",
            ok: "Form payload built (DRAFT) — see Filings in the Compliance Centre.", run: (r) => buildMyEventFiling(r.id) },
          { label: "Cancel", show: (r) => r.status === "OPEN", ok: "Event cancelled.",
            run: async (r) => {
              const reason = ask("Reason for cancelling the event");
              if (!reason) throw new Error("A reason is required.");
              await cancelMyEmployerEvent(r.id, reason);
            } },
        ]}
        fields={[
          { key: "event_type", label: "Event", type: "select", options: EVENT_TYPES, required: true },
          { key: "event_date", label: "Start / cessation / departure / date learned", type: "date", required: true },
          { key: "clearance_required", label: "Tax clearance required (CP22A / CP21)", type: "bool" },
          { key: "evidence_ref", label: "Evidence reference" },
          REASON_FIELD,
        ]} />

      <ClearanceHolds employeeId={id} />
      <MYIdentifierField employeeId={id} />
      <LeaveAndHolidays employeeId={id} />
    </div>
  );
}

export default function MalaysiaStatutoryProfilePanel({ employee, onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-background/40 backdrop-blur-sm" onClick={onClose}>
      <div className="flex h-full w-full max-w-3xl flex-col bg-surface border-l border-border shadow-[0_24px_48px_rgba(0,0,0,0.15)]"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-5 border-b border-border">
          <div>
            <h2 className="text-[15px] font-bold text-foreground">Malaysia statutory records</h2>
            <p className="text-[12px] text-foreground-muted mt-0.5">{employee?.name} · {employee?.employeeCode}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-foreground-muted hover:bg-surface-muted">
            <X size={16} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5">
          <MalaysiaEmployeeRecords employeeId={employee?.id} />
        </div>
      </div>
    </div>
  );
}
