import { useState } from "react";
import { X } from "lucide-react";
import {
  approvePlEpisode, approvePlPpk, approvePlStatement, approvePlWorkerProfile, cancelPlEpisode, createPlEpisode,
  createPlPpk, createPlStatement, createPlWorkerProfile, getPlAnnualCap, getPlLeaveEntitlement, listPlEpisodes,
  listPlPpk, listPlStatements, listPlWorkerProfiles, withdrawPlStatement,
} from "../../../service/payrollService";
import { card } from "../../../components/jurisdiction/japan/jpFormat";
import JPRecordSection, { btn, isDraft, statusCol } from "../../../components/jurisdiction/japan/JPRecordSection";
import { REASON_FIELD, errorText, period } from "../../../components/jurisdiction/new_zealand/nzOrgOptions";
import {
  CONTRACT_TYPES, DECLARATION_TYPES, INCAPACITY_CATEGORIES, PAY_FREQUENCIES, PIT2_ALLOCATIONS, PPK_NOTICE_STATES,
  PPK_STATES, RESIDENCY, SOURCE_CHANNELS, statementPayload,
} from "../../../components/jurisdiction/poland/plOrgOptions";
import PLIdentifierField from "./PLIdentifierField";

// Every Poland record for one employee (ZP-PL-ENG-001 §3-§9). Versioned facts
// are captured as DRAFT with a reason and count only after a SECOND user
// approves them; statements are captured as RECEIVED with their evidence
// (PL-005). The engine selects by the pay date and BLOCKS while a fact it needs
// is missing — coverage is never inferred from the contract label (PL-002).

const periodCol = { label: "In force", render: period };
const ask = (message) => {
  const value = window.prompt(message);
  return value && value.trim() ? value.trim() : null;
};
const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";

function AnnualCapAndLeave({ employeeId }) {
  const [year, setYear] = useState(String(new Date().getFullYear()));
  const [asOf, setAsOf] = useState(new Date().toISOString().slice(0, 10));
  const [cap, setCap] = useState(null);
  const [leave, setLeave] = useState(null);
  const [error, setError] = useState(null);
  const load = async () => {
    setError(null);
    try {
      setCap(await getPlAnnualCap(employeeId, year));
      setLeave(await getPlLeaveEntitlement(employeeId, asOf).catch((e) => ({ error: errorText(e) })));
    } catch (e) {
      setError(errorText(e));
    }
  };
  return (
    <section className={card} data-testid="pl-annual-cap">
      <h3 className="text-[14px] font-semibold text-foreground">Annual cap and leave</h3>
      <p className="mb-2 text-[12px] text-foreground-muted">
        Year-to-date pension / disability bases behind the 30x cap (with prior-employer evidence) and the annual leave
        entitlement — read-only views of the ledger and the signed pack.
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <input className={input} inputMode="numeric" value={year} onChange={(e) => setYear(e.target.value)} aria-label="Year" />
        <input className={input} type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} aria-label="Leave as of" />
        <button type="button" className={btn} onClick={load}>Show</button>
      </div>
      {error && <p role="alert" className="mt-2 text-[12px] text-error">{error}</p>}
      {cap && (
        <div className="mt-2 text-[12px]">
          <p>Pension base YTD: <strong>{cap.totals?.ZUS_CAP_PENSION_BASE}</strong> · Disability base YTD:{" "}
            <strong>{cap.totals?.ZUS_CAP_DISABILITY_BASE}</strong> ({(cap.entries || []).length} ledger entries)</p>
          {(cap.entries || []).filter((e) => e.kind === "PRIOR_EMPLOYER").map((e) => (
            <p key={e.id} className="text-foreground-muted">Prior employer {e.accumulator}: {e.amount} · evidence {e.evidenceRef}</p>
          ))}
        </div>
      )}
      {leave && (
        <p className="mt-2 text-[12px]">
          {leave.error ? <span className="text-warning">Leave: {leave.error}</span>
            : <>Annual leave: <strong>{leave.days} days</strong> ({leave.tier}, FTE {leave.fte}, service {leave.serviceYears} years)</>}
        </p>
      )}
    </section>
  );
}

export function PolandEmployeeRecords({ employeeId }) {
  const id = employeeId;
  return (
    <div className="space-y-4" data-testid="pl-employee-records">
      <JPRecordSection
        title="Worker statutory profile" testId="pl-worker-profile"
        description="Contract, ZUS insurance title and each coverage flag (unknown blocks — never the lowest-cost guess), FTE, service credit, residency, other titles / A1 / FEP with evidence."
        load={() => listPlWorkerProfiles(id)} create={(p) => createPlWorkerProfile(id, p)}
        empty="No worker profile — Polish payslips are blocked until one is approved."
        columns={[periodCol, { label: "Contract", key: "contract_type" }, { label: "ZUS title", key: "insurance_title_code" },
          { label: "FTE", render: (r) => (r.fte_numerator ? `${r.fte_numerator}/${r.fte_denominator}` : "—") }, statusCol]}
        actions={[{ label: "Approve", show: isDraft, run: (r) => approvePlWorkerProfile(r.id), ok: "Worker profile approved." }]}
        fields={[
          { key: "effective_from", label: "Effective from", type: "date", required: true },
          { key: "contract_type", label: "Contract type", type: "select", options: CONTRACT_TYPES, required: true },
          { key: "insurance_title_code", label: "ZUS insurance title (6 digits)" },
          { key: "pay_frequency", label: "Pay frequency", type: "select", options: PAY_FREQUENCIES },
          { key: "tax_residency", label: "Tax residency", type: "select", options: RESIDENCY },
          { key: "fte_numerator", label: "FTE numerator", type: "number" },
          { key: "fte_denominator", label: "FTE denominator", type: "number" },
          { key: "service_credit_months", label: "Service credit (months)", type: "number" },
          { key: "cov_pension", label: "Pension coverage", type: "bool" },
          { key: "cov_disability", label: "Disability coverage", type: "bool" },
          { key: "cov_sickness", label: "Sickness coverage", type: "bool" },
          { key: "cov_accident", label: "Accident coverage", type: "bool" },
          { key: "cov_health", label: "Health coverage", type: "bool" },
          { key: "is_student", label: "Student", type: "bool" },
          { key: "is_pensioner", label: "Pensioner", type: "bool" },
          { key: "other_titles_declared", label: "Other insurance titles", type: "bool" },
          { key: "other_titles_evidence_ref", label: "Other titles evidence" },
          { key: "a1_certificate", label: "A1 certificate", type: "bool" },
          { key: "fep_qualifying", label: "FEP qualifying work", type: "bool" },
          { key: "fep_evidence_ref", label: "FEP evidence" },
          { key: "fep_from", label: "FEP from", type: "date" },
          { key: "evidence_ref", label: "Evidence reference" },
          REASON_FIELD,
        ]} />

      <JPRecordSection
        title="Statements (PIT-2, costs, reliefs, PPK, prior-employer cap)" testId="pl-statements"
        description="Each statement keeps its received date, evidence and channel (PL-005), and stays effective until withdrawn or replaced (PL-007). A second user approves it; a prior-employer cap statement then posts its evidenced bases (PL-010)."
        load={() => listPlStatements(id)} create={(p) => createPlStatement(id, p)} transform={statementPayload}
        createLabel="Record as RECEIVED" createdNotice="Recorded — a second user must approve it."
        empty="No statements."
        columns={[periodCol, { label: "Type", key: "declaration_type" },
          { label: "Value", render: (r) => (r.value && Object.keys(r.value).length ? JSON.stringify(r.value) : "—") },
          { label: "Received", render: (r) => String(r.received_at || "").slice(0, 10) }, statusCol]}
        actions={[
          { label: "Approve", show: (r) => r.status === "RECEIVED", run: (r) => approvePlStatement(r.id), ok: "Statement approved." },
          { label: "Withdraw", show: (r) => r.status === "APPROVED" && r.declaration_type !== "PRIOR_EMPLOYER_CAP", ok: "Statement withdrawn.",
            run: async (r) => {
              const reason = ask("Reason for the withdrawal");
              const end = reason && ask("Last day the statement applies (YYYY-MM-DD)");
              if (!reason || !end) throw new Error("A reason and an end date are required.");
              await withdrawPlStatement(r.id, reason, end);
            } },
        ]}
        fields={[
          { key: "declaration_type", label: "Statement", type: "select", options: DECLARATION_TYPES, required: true },
          { key: "received_at", label: "Received on", type: "date", required: true },
          { key: "effective_from", label: "Effective from", type: "date", required: true },
          { key: "effective_to", label: "Effective to (optional)", type: "date" },
          { key: "source_channel", label: "Channel", type: "select", options: SOURCE_CHANNELS, required: true },
          { key: "evidence_ref", label: "Evidence reference", required: true },
          { key: "allocation", label: "PIT-2 allocation", type: "select", options: PIT2_ALLOCATIONS },
          { key: "ratePct", label: "PPK rate % (reduced / additional)", type: "number" },
          { key: "otherSourcesIncome", label: "PPK other-sources income", type: "number" },
          { key: "pensionBase", label: "Prior employer pension base", type: "number" },
          { key: "disabilityBase", label: "Prior employer disability base", type: "number" },
        ]} />

      <JPRecordSection
        title="PPK participation" testId="pl-ppk"
        description="Eligibility and enrolment state (spec §7). Opting out needs the employee's approved PPK_OPT_OUT statement; rates come from statements and the employer registration."
        load={() => listPlPpk(id)} create={(p) => createPlPpk(id, p)}
        empty="No PPK participation — Polish payslips are blocked until a state is approved."
        columns={[periodCol, { label: "State", key: "state" }, { label: "Enrolled", key: "enrolment_date" },
          { label: "Re-enrolment", key: "next_reenrolment_date" }, statusCol]}
        actions={[{ label: "Approve", show: isDraft, run: (r) => approvePlPpk(r.id), ok: "PPK participation approved." }]}
        fields={[
          { key: "effective_from", label: "Effective from", type: "date", required: true },
          { key: "state", label: "State", type: "select", options: PPK_STATES, required: true },
          { key: "enrolment_date", label: "Enrolment date", type: "date" },
          { key: "notice_state", label: "Notice", type: "select", options: PPK_NOTICE_STATES },
          { key: "opt_out_declaration_id", label: "Opt-out statement id", type: "number" },
          { key: "next_reenrolment_date", label: "Next re-enrolment", type: "date" },
          { key: "evidence_ref", label: "Evidence reference" },
          REASON_FIELD,
        ]} />

      <JPRecordSection
        title="Incapacity episodes" testId="pl-episodes"
        description="Dates and statutory category only (PL-017): the certificate reference is held on the restricted record and no medical detail is ever stored. A correction is a new episode that supersedes the old one (PL-018)."
        load={() => listPlEpisodes(id)} create={(p) => createPlEpisode(id, p)}
        empty="No incapacity episodes."
        columns={[{ label: "From – to", render: (r) => `${r.date_from} → ${r.date_to}` }, { label: "Category", key: "category" },
          { label: "Daily base", render: (r) => r.daily_base_amount ?? "—" }, statusCol]}
        actions={[
          { label: "Approve", show: isDraft, run: (r) => approvePlEpisode(r.id), ok: "Episode approved." },
          { label: "Cancel", show: (r) => r.status === "DRAFT" || r.status === "APPROVED", ok: "Episode cancelled.",
            run: async (r) => {
              const reason = ask("Reason for cancelling the episode");
              if (!reason) throw new Error("A reason is required.");
              await cancelPlEpisode(r.id, reason);
            } },
        ]}
        fields={[
          { key: "date_from", label: "From", type: "date", required: true },
          { key: "date_to", label: "To", type: "date", required: true },
          { key: "category", label: "Category", type: "select", options: INCAPACITY_CATEGORIES, required: true },
          { key: "certificate_ref", label: "Certificate (e-ZLA) reference" },
          { key: "evidence_ref", label: "Other evidence" },
          { key: "daily_base_amount", label: "Approved daily benefit base", type: "number" },
          { key: "base_reference_from", label: "Base reference from", type: "date" },
          { key: "base_reference_to", label: "Base reference to", type: "date" },
          { key: "base_evidence_ref", label: "Base calculation evidence" },
          { key: "supersedes_id", label: "Supersedes episode id", type: "number" },
          REASON_FIELD,
        ]} />

      <PLIdentifierField employeeId={id} />
      <AnnualCapAndLeave employeeId={id} />
    </div>
  );
}

export default function PolandStatutoryProfilePanel({ employee, onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-background/40 backdrop-blur-sm" onClick={onClose}>
      <div className="flex h-full w-full max-w-3xl flex-col bg-surface border-l border-border shadow-[0_24px_48px_rgba(0,0,0,0.15)]"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-5 border-b border-border">
          <div>
            <h2 className="text-[15px] font-bold text-foreground">Poland statutory records</h2>
            <p className="text-[12px] text-foreground-muted mt-0.5">{employee?.name} · {employee?.employeeCode}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-foreground-muted hover:bg-surface-muted">
            <X size={16} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5">
          <PolandEmployeeRecords employeeId={employee?.id} />
        </div>
      </div>
    </div>
  );
}
