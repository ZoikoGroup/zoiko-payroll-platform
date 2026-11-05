import { useState } from "react";
import {
  approveNzCashUp, approveNzEmployment, approveNzFinalPay, approveNzPublicHolidayDecision, calculateNzFinalPay,
  calculateNzLeavePay, calculateNzPublicHolidayPay, cancelNzFinalPay, cancelNzLeaveEvent, createNzEmployment,
  endNzEmployment, getNzLeaveEntitlements, listNzCashUps, listNzEmployments, listNzFinalPayCases, listNzGrossEarnings,
  listNzLeaveEvents, listNzLeavePayCalculations, listNzPublicHolidayDecisions, openNzFinalPayCase, rehireNz,
  rejectNzCashUp, requestNzCashUp, updateNzPublicHolidayDecision,
} from "../../../service/payrollService";
import { card, useLoad } from "../../../components/jurisdiction/japan/jpFormat";
import { Table } from "../../../components/jurisdiction/japan/jpShared";
import JPRecordSection, { btn } from "../../../components/jurisdiction/japan/JPRecordSection";
import {
  CONTINUITY, OWD_DECISIONS, PAYG_BASES, REASON_FIELD, TIMEZONES, errorText,
} from "../../../components/jurisdiction/new_zealand/nzOrgOptions";

// New Zealand Holidays Act records for one employee (ZP-NZ-ENG-001 P5/P6).
// Entitlements are LEGAL quantities (weeks / days), never an hours accrual;
// the allocation JSON is shown only as a planning view. Leave pay keeps both
// candidates (OWP/AWE or RDP/ADP), the winner and the statutory reason.
// Family-violence items arrive from the server only for a permitted viewer.

const ask = (message) => {
  const value = window.prompt(message);
  return value && value.trim() ? value.trim() : null;
};
const money = (v) => (v == null || v === "" ? "—" : `$${Number(v).toLocaleString("en-NZ", { minimumFractionDigits: 2 })}`);

export function NZEmployments({ employeeId }) {
  const [rehire, setRehire] = useState(false);
  return (
    <>
      <JPRecordSection
        title="Employment instances" testId="nz-employments"
        description="The anniversary anchor for every entitlement. A rehire is a new instance unless continuity is evidenced. Pay-as-you-go holiday pay only on a recorded basis with the written agreement."
        load={() => listNzEmployments(employeeId)} create={(p) => createNzEmployment(employeeId, p)}
        empty="No employment instance — entitlements cannot vest."
        columns={[
          { label: "Start → end", render: (r) => `${r.startDate} → ${r.endDate || "open"}` },
          { label: "Continuity", key: "continuityRule" },
          { label: "Pay-as-you-go", render: (r) => (r.paygEligible ? r.paygBasis : "No") },
          { label: "Status", key: "status" }]}
        actions={[
          { label: "Approve", show: (r) => r.status === "DRAFT", run: (r) => approveNzEmployment(r.id), ok: "Employment approved." },
          { label: "End", show: (r) => r.status === "ACTIVE", ok: "Employment ended.",
            run: async (r) => {
              const endDate = ask("End date (YYYY-MM-DD)");
              const reason = endDate && ask("Reason");
              if (!endDate || !reason) throw new Error("An end date and a reason are required.");
              await endNzEmployment(r.id, { endDate, terminationReason: ask("Termination reason (optional)") || undefined, reason });
            } },
        ]}
        fields={[
          { key: "start_date", label: "Start date", type: "date", required: true },
          { key: "continuity_rule", label: "Continuity", type: "select", options: CONTINUITY },
          { key: "prior_employment_id", label: "Prior employment id (continuous)", type: "number" },
          { key: "payg_eligible", label: "Pay-as-you-go eligible", type: "bool" },
          { key: "payg_basis", label: "Pay-as-you-go basis", type: "select", options: PAYG_BASES },
          { key: "payg_agreement_ref", label: "Written agreement reference" },
          { key: "evidence_ref", label: "Evidence reference" },
          REASON_FIELD,
        ]} />
      <div className="flex justify-end">
        <button type="button" className={btn} onClick={() => setRehire(!rehire)}>{rehire ? "Close rehire" : "Rehire…"}</button>
      </div>
      {rehire && (
        <JPRecordSection
          title="Rehire" testId="nz-rehire"
          description="Only after the previous instance ENDED. A new instance starts new anniversaries unless continuity is evidenced."
          load={async () => []} create={(p) => rehireNz(employeeId, p)} createLabel="Create DRAFT instance"
          empty="" columns={[]}
          fields={[
            { key: "start_date", label: "Start date", type: "date", required: true },
            { key: "continuity_rule", label: "Continuity", type: "select", options: CONTINUITY },
            { key: "evidence_ref", label: "Evidence (continuous)" },
            REASON_FIELD,
          ]} />
      )}
    </>
  );
}

function EntitlementGroup({ name, group }) {
  if (!group) return null;
  return (
    <div className="mb-3">
      <p className="text-[12px] font-semibold text-foreground">
        {name} — balance {group.balance} {group.unit.toLowerCase()}
      </p>
      <Table rows={group.entitlements} empty="None vested."
        columns={[
          { label: "Vested", key: "entitlementDate" }, { label: "Quantity", render: (r) => `${r.quantity} ${r.unit.toLowerCase()}` },
          { label: "Carried in", key: "carriedIn" }, { label: "Taken", key: "taken" }, { label: "Paid out", key: "paidOut" },
          { label: "Balance", key: "balance" }, { label: "Status", key: "status" }]} />
    </div>
  );
}

export function NZEntitlements({ employeeId }) {
  const [data, error, loading] = useLoad(() => getNzLeaveEntitlements(employeeId));
  return (
    <section className={card} data-testid="nz-entitlements">
      <h3 className="text-[14px] font-semibold text-foreground">Leave entitlements (legal)</h3>
      <p className="mb-3 text-[12px] text-foreground-muted">
        Annual holidays in weeks per anniversary; sick, bereavement and alternative days. Vested in the Compliance Centre.
      </p>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {loading || !data ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        <>
          <EntitlementGroup name="Annual holidays" group={data.annual} />
          <EntitlementGroup name="Sick leave" group={data.sick} />
          <EntitlementGroup name="Bereavement" group={data.bereavement} />
          <EntitlementGroup name="Alternative holidays" group={data.alternative} />
          {data.familyViolence && <EntitlementGroup name="Family violence leave (restricted)" group={data.familyViolence} />}
          <div className="rounded-lg border border-dashed border-border p-2 text-[11px] text-foreground-muted" data-testid="nz-planning-view">
            <span className="font-semibold">{data.planningView?.label}</span>
            {" "}{JSON.stringify(data.planningView?.balances || {})}
          </div>
        </>
      )}
    </section>
  );
}

export function NZLeaveEvents({ employeeId }) {
  return (
    <JPRecordSection
      title="Leave taken" testId="nz-leave-events"
      description="Created when a leave request is approved. Calculate its pay before the run that covers it is approved."
      load={() => listNzLeaveEvents(employeeId)} empty="No leave events."
      columns={[
        { label: "Type", render: (r) => (r.restricted ? "Restricted leave" : r.leaveType) },
        { label: "Dates", render: (r) => `${r.startDate} → ${r.endDate}` },
        { label: "Quantity", render: (r) => `${r.quantity} ${String(r.unit).toLowerCase()}` },
        { label: "Pay", render: (r) => (r.leavePayCalculationId ? `Calculation #${r.leavePayCalculationId}` : "Not calculated") },
        { label: "Status", key: "status" }]}
      actions={[
        { label: "Calculate pay", show: (r) => r.status === "APPROVED" && !r.leavePayCalculationId,
          run: (r) => calculateNzLeavePay(r.id), ok: "Leave pay calculated." },
        { label: "Cancel", show: (r) => r.status === "APPROVED", ok: "Leave cancelled; the entitlement is restored.",
          run: async (r) => {
            const reason = ask("Why is this leave being cancelled?");
            if (!reason) throw new Error("A reason is required.");
            await cancelNzLeaveEvent(r.id, reason);
          } },
      ]} />
  );
}

function DecisionEditor({ decision, onDone }) {
  const [values, setValues] = useState({ timezone: decision.timezone || "Pacific/Auckland" });
  const [error, setError] = useState(null);
  const set = (key) => (e) => setValues({ ...values, [key]: e.target.value });
  const save = async () => {
    const body = Object.fromEntries(Object.entries(values).filter(([, v]) => v !== "" && v != null));
    if (body.worked !== undefined) body.worked = body.worked === "true";
    try {
      await updateNzPublicHolidayDecision(decision.id, body);
      onDone();
    } catch (e) {
      setError(errorText(e));
    }
  };
  const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px]";
  return (
    <div className="mt-3 grid grid-cols-1 gap-2 rounded-lg border border-dashed border-border p-3 sm:grid-cols-3" data-testid="nz-decision-editor">
      <p className="sm:col-span-3 text-[12px] font-semibold">{decision.holidayName} — {decision.holidayDate}</p>
      <select className={input} value={values.otherwise_working_day || ""} onChange={set("otherwise_working_day")} aria-label="Otherwise working day">
        <option value="">Working day? (keep)</option>
        {OWD_DECISIONS.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
      <input className={input} placeholder="Evidence for the decision" value={values.owd_evidence_ref || ""} onChange={set("owd_evidence_ref")} />
      <select className={input} value={values.worked ?? ""} onChange={set("worked")} aria-label="Worked">
        <option value="">Worked? (keep)</option><option value="true">Worked</option><option value="false">Not worked</option>
      </select>
      <input className={input} type="datetime-local" value={values.shift_start || ""} onChange={set("shift_start")} aria-label="Shift start" />
      <input className={input} type="datetime-local" value={values.shift_end || ""} onChange={set("shift_end")} aria-label="Shift end" />
      <select className={input} value={values.timezone} onChange={set("timezone")} aria-label="Time zone">
        {TIMEZONES.map((t) => <option key={t} value={t}>{t}</option>)}
      </select>
      <input className={`${input} sm:col-span-2`} placeholder="Reason for the change *" value={values.reason || ""} onChange={set("reason")} />
      <div className="flex gap-2">
        <button type="button" className={btn} disabled={!values.reason?.trim()} onClick={save}>Save</button>
        <button type="button" className={btn} onClick={onDone}>Close</button>
      </div>
      {error && <p role="alert" className="sm:col-span-3 text-[12px] text-error">{error}</p>}
    </div>
  );
}

export function NZPublicHolidays({ employeeId }) {
  const [editing, setEditing] = useState(null);
  const [version, setVersion] = useState(0);
  return (
    <div>
      <JPRecordSection
        key={version}
        title="Public holidays" testId="nz-public-holidays"
        description="Proposed in the Compliance Centre. An UNDETERMINED working-day test needs an evidenced YES/NO; working an otherwise working day earns one alternative holiday on approval."
        load={() => listNzPublicHolidayDecisions(employeeId)} empty="No public-holiday decisions yet."
        columns={[
          { label: "Holiday", render: (r) => `${r.holidayDate} ${r.holidayName}${r.region ? ` (${r.region})` : ""}` },
          { label: "Working day", render: (r) => `${r.otherwiseWorkingDay} · ${r.owdBasis}` },
          { label: "Worked", render: (r) => (r.worked ? `${r.hoursOnHoliday ?? "—"} h` : "No") },
          { label: "Alternative", render: (r) => (r.alternativeHolidayDue ? "Due" : "—") },
          { label: "Status", key: "status" }]}
        actions={[
          { label: "Edit", show: (r) => r.status === "DRAFT", run: async (r) => setEditing(r), ok: null },
          { label: "Approve", show: (r) => r.status === "DRAFT", run: (r) => approveNzPublicHolidayDecision(r.id), ok: "Decision approved." },
          { label: "Calculate pay", show: (r) => r.status === "APPROVED" && (r.worked || r.otherwiseWorkingDay === "YES"),
            run: (r) => calculateNzPublicHolidayPay(r.id), ok: "Holiday pay calculated." },
        ]} />
      {editing && <DecisionEditor decision={editing} onDone={() => { setEditing(null); setVersion((v) => v + 1); }} />}
    </div>
  );
}

export function NZLeavePay({ employeeId }) {
  const [rows, error, loading] = useLoad(() => listNzLeavePayCalculations(employeeId));
  return (
    <section className={card} data-testid="nz-leave-pay">
      <h3 className="text-[14px] font-semibold text-foreground">Leave-pay calculations</h3>
      <p className="mb-3 text-[12px] text-foreground-muted">
        Both candidates are kept with the statutory reason for the winner. A missing candidate blocks — it is never assumed.
      </p>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {loading ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        <Table rows={rows} empty="No leave-pay calculations."
          columns={[
            { label: "Date", key: "payOn" }, { label: "Purpose", render: (r) => (r.restricted ? "Restricted leave" : r.purpose) },
            { label: "Candidates", render: (r) => [r.candidateA, r.candidateB].filter((c) => c?.name)
              .map((c) => `${c.name} ${c.rate == null ? "—" : money(c.rate)}`).join(" vs ") || "—" },
            { label: "Chosen", render: (r) => <span title={r.statutoryReason}>{r.chosen}</span> },
            { label: "Units", render: (r) => `${r.units} ${String(r.unit).toLowerCase()}` },
            { label: "Amount", render: (r) => money(r.amount) }, { label: "Replaces", render: (r) => money(r.displaced) },
            { label: "Status", key: "status" }]} />
      )}
    </section>
  );
}

export function NZCashUps({ employeeId }) {
  return (
    <JPRecordSection
      title="Annual-holiday cash-up" testId="nz-cash-ups"
      description="Only on the employee's written request, within the signed weekly limit and the remaining balance; a second user approves."
      load={() => listNzCashUps(employeeId)} create={(p) => requestNzCashUp(employeeId, p)} createLabel="Record request"
      createdNotice="Recorded — a second user must approve it." empty="No cash-up requests."
      columns={[
        { label: "Requested", key: "requestedOn" }, { label: "Weeks", key: "weeks" },
        { label: "Written request", key: "writtenRequestRef" },
        { label: "Calculation", render: (r) => (r.leavePayCalculationId ? `#${r.leavePayCalculationId}` : "—") },
        { label: "Status", key: "status" }]}
      actions={[
        { label: "Approve", show: (r) => r.status === "REQUESTED", run: (r) => approveNzCashUp(r.id), ok: "Cash-up approved and calculated." },
        { label: "Reject", show: (r) => r.status === "REQUESTED", ok: "Cash-up rejected.",
          run: async (r) => {
            const reason = ask("Why is the cash-up rejected?");
            if (!reason) throw new Error("A reason is required.");
            await rejectNzCashUp(r.id, reason);
          } },
      ]}
      fields={[
        { key: "entitlement_id", label: "Annual entitlement id", type: "number", required: true },
        { key: "weeks", label: "Weeks", type: "number", required: true },
        { key: "requested_on", label: "Requested on", type: "date" },
        { key: "written_request_ref", label: "Written request reference", required: true },
        REASON_FIELD,
      ]} />
  );
}

export function NZFinalPay({ employeeId }) {
  return (
    <JPRecordSection
      title="Final pay" testId="nz-final-pay"
      description="Calculating vests everything due to the termination date first, then resolves every entitlement: paid, or listed as not payable — never zeroed."
      load={() => listNzFinalPayCases(employeeId)} create={(p) => openNzFinalPayCase(employeeId, p)} createLabel="Open case"
      createdNotice="Final pay case opened." empty="No final pay case."
      columns={[
        { label: "Termination", render: (r) => `${r.terminationDate} · ${r.terminationReason}` },
        { label: "Since", render: (r) => r.lastAnniversary || "start" },
        { label: "Resolved", render: (r) => (r.outstanding || []).map((o) => `${o.purpose} ${o.amount === "0" ? "(not payable)" : money(o.amount)}`).join("; ") || "—" },
        { label: "Status", key: "status" }]}
      actions={[
        { label: "Calculate", show: (r) => ["OPEN", "CALCULATED"].includes(r.status), run: (r) => calculateNzFinalPay(r.id), ok: "Final pay calculated." },
        { label: "Approve", show: (r) => r.status === "CALCULATED", run: (r) => approveNzFinalPay(r.id), ok: "Final pay approved." },
        { label: "Cancel", show: (r) => !["PAID", "CANCELLED"].includes(r.status), ok: "Case cancelled.",
          run: async (r) => {
            const reason = ask("Why is the case cancelled?");
            if (!reason) throw new Error("A reason is required.");
            await cancelNzFinalPay(r.id, reason);
          } },
      ]}
      transform={(p) => ({ terminationDate: p.termination_date, terminationReason: p.termination_reason, reason: p.reason })}
      fields={[
        { key: "termination_date", label: "Termination date", type: "date", required: true },
        { key: "termination_reason", label: "Termination reason", required: true },
        REASON_FIELD,
      ]} />
  );
}

export function NZGrossEarnings({ employeeId }) {
  const [rows, error, loading] = useLoad(() => listNzGrossEarnings(employeeId));
  return (
    <section className={card} data-testid="nz-gross-earnings">
      <h3 className="text-[14px] font-semibold text-foreground">Gross earnings ledger</h3>
      <p className="mb-3 text-[12px] text-foreground-muted">Written once per paid payslip; the base for average weekly earnings and final pay.</p>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {loading ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        <Table rows={rows} empty="No paid payslips yet."
          columns={[
            { label: "Paid", key: "payDate" }, { label: "Period", render: (r) => `${r.periodStart} → ${r.periodEnd}` },
            { label: "Component", key: "component" }, { label: "Amount", render: (r) => money(r.amount) },
            { label: "Counts", render: (r) => (r.included ? "Included" : r.treatment) }, { label: "Days", key: "daysWorked" }]} />
      )}
    </section>
  );
}
