import { useState } from "react";
import { X } from "lucide-react";
import {
  approveBeAbsenceEpisode, approveBeClassification, approveBeDeclaration, approveBeHolidayCertificate,
  approveBeSchedule, approveBeWorkerProfile, cancelBeAbsenceEpisode, createBeAbsenceEpisode, createBeClassification,
  createBeDeclaration, createBeHolidayCertificate, createBeSchedule, createBeWorkerProfile, getBeOptions,
  listBeAbsenceEpisodes, listBeClassifications, listBeDeclarations, listBeHolidayCertificates,
  listBeJointCommitteesForOrg, listBeSchedules, listBeWorkerProfiles, resolveBeClassification, withdrawBeDeclaration,
} from "../../../service/payrollService";
import { card, useLoad } from "../../../components/jurisdiction/japan/jpFormat";
import JPRecordSection, { btn, isDraft, statusCol } from "../../../components/jurisdiction/japan/JPRecordSection";
import { REASON_FIELD, errorText, period } from "../../../components/jurisdiction/new_zealand/nzOrgOptions";
import BEIdentifierField from "./BEIdentifierField";
import { declarationPayload } from "./beOrgPayloads";

// Every Belgium record for one employee (ZP-BE-ENG-001 §2, §15; Block A4).
// Versioned facts are captured as DRAFT with a reason and count only after a
// SECOND user approves them; declarations are captured as RECEIVED with their
// evidence. Choice lists come from the server's catalogue (/belgium/options) and
// Joint Committees from the platform definitions (/belgium/joint-committees).
// Nothing here calculates: the resolver panel only SHOWS the server's decision
// and every blocking reason for a pay date.

const periodCol = { label: "In force", render: period };
const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
const ask = (message) => {
  const value = window.prompt(message);
  return value && value.trim() ? value.trim() : null;
};


function ResultList({ title, rows, tone, testId }) {
  if (!rows || rows.length === 0) return null;
  return (
    <div className="mt-2" data-testid={testId}>
      <p className={`text-[12px] font-semibold ${tone}`}>{title}</p>
      <ul className="ml-4 list-disc text-[12px]">
        {rows.map((r) => <li key={r.code}><span className="font-mono">{r.code}</span> — {r.reason}</li>)}
      </ul>
    </div>
  );
}

export function BEResolverResult({ result }) {
  if (!result) return null;
  const worker = result.worker || {};
  const employer = result.employer || {};
  return (
    <div className="mt-3 rounded-lg border border-border p-3 text-[12px]" data-testid="be-resolver-result">
      <p>
        Decision for {result.payDate}: <strong data-testid="be-resolver-decision">{result.decision}</strong>
        {" "}({result.confidence})
      </p>
      {result.decision !== "BLOCKED" || employer.registrationId ? (
        <p className="mt-1 text-foreground-muted">
          Employer category {employer.employerCategory || "—"} · worker category {worker.workerCategory || "—"} ·
          worker code {worker.workerCode || "—"} · contract {worker.contractType || "—"} · pay frequency{" "}
          {worker.payFrequency || "—"}
        </p>
      ) : null}
      {(result.employmentLines || []).map((line) => (
        <p key={line.employmentLine} className="mt-1 text-foreground-muted">
          Line {line.employmentLine}: Joint Committee {line.jointCommittee || "—"}
          {line.subCommittee ? `/${line.subCommittee}` : ""} · agreement {line.agreement?.agreementCode || "none linked"} ·
          schedule {line.schedule ? `${line.schedule.regime}, ${line.schedule.weeklyHours} h/week` : "—"}
          {line.unit ? ` · unit ${line.unit.unitNumber}` : ""}
        </p>
      ))}
      <ResultList title="Blocking reasons (payroll cannot run)" rows={result.blocking} tone="text-error"
        testId="be-resolver-blocking" />
      <ResultList title="Exceptions (stop approval)" rows={result.exceptions} tone="text-warning"
        testId="be-resolver-exceptions" />
    </div>
  );
}

export function BEResolverPanel({ employeeId }) {
  const [payDate, setPayDate] = useState(new Date().toISOString().slice(0, 10));
  const [periodStart, setPeriodStart] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const run = async () => {
    setError(null);
    try {
      setResult(await resolveBeClassification(employeeId, payDate, periodStart ? { periodStart } : {}));
    } catch (e) {
      setResult(null);
      setError(errorText(e));
    }
  };
  return (
    <section className={card} data-testid="be-resolver">
      <h3 className="text-[14px] font-semibold text-foreground">Applicability resolver</h3>
      <p className="mb-2 text-[12px] text-foreground-muted">
        Read-only: which employer and worker category, Joint Committee, schedule and declarations apply on a pay
        date, and every reason that blocks Belgian payroll (spec §2). Nothing is calculated or saved.
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-[11px] font-semibold text-foreground-muted">Pay date
          <input className={input} type="date" value={payDate} onChange={(e) => setPayDate(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-[11px] font-semibold text-foreground-muted">Period start (optional)
          <input className={input} type="date" value={periodStart} onChange={(e) => setPeriodStart(e.target.value)} />
        </label>
        <button type="button" className={btn} onClick={run} disabled={!payDate}>Resolve</button>
      </div>
      {error && <p role="alert" className="mt-2 text-[12px] text-error">{error}</p>}
      <BEResolverResult result={result} />
    </section>
  );
}

export function BelgiumEmployeeRecords({ employeeId }) {
  const id = employeeId;
  const [options, optionsError] = useLoad(() => getBeOptions());
  const [committees] = useLoad(() => listBeJointCommitteesForOrg());
  if (optionsError) return <p role="alert" className="text-[12px] text-error">{optionsError}</p>;
  if (!options) return <p className="text-[12px] text-foreground-muted">Loading…</p>;
  const active = (committees || []).filter((c) => c.codeValid && c.status === "Active");
  const committeeCodes = [...new Set(active.map((c) => c.jointCommittee))];
  const agreements = active.map((c) => [String(c.id), `${c.agreementCode} · ${c.name}`]);
  return (
    <div className="space-y-4" data-testid="be-employee-records">
      <JPRecordSection
        title="Worker statutory profile" testId="be-worker-profile"
        description="Worker category (manual / white-collar, special regimes), ONSS worker code, residency and special status — evidenced and effective-dated. Approved by a second user; unsupported categories block."
        load={() => listBeWorkerProfiles(id)} create={(p) => createBeWorkerProfile(id, p)}
        empty="No worker profile — Belgian payroll is blocked until one is approved."
        columns={[periodCol, { label: "Category", key: "worker_category" }, { label: "ONSS code", key: "onss_worker_code" },
          { label: "Residency", key: "residency" }, { label: "Special status", render: (r) => r.special_status || "—" },
          statusCol]}
        actions={[{ label: "Approve", show: isDraft, run: (r) => approveBeWorkerProfile(r.id), ok: "Worker profile approved." }]}
        fields={[
          { key: "effective_from", label: "Effective from", type: "date", required: true },
          { key: "worker_category", label: "Worker category", type: "select", options: options.workerCategories, required: true },
          { key: "onss_worker_code", label: "ONSS worker code" },
          { key: "residency", label: "Residency", type: "select", options: options.residency },
          { key: "pay_basis", label: "Pay basis (required to calculate)", type: "select", options: options.payBases },
          { key: "tax_status", label: "Tax status" },
          { key: "special_status", label: "Special status (blocks until its regime is certified)" },
          { key: "evidence_ref", label: "Evidence reference" },
          REASON_FIELD,
        ]} />

      <JPRecordSection
        title="Work schedules" testId="be-schedules"
        description="An explicit schedule per employment line (BE-022): regime and weekly hours. A new version names the schedule it supersedes; other lines' schedules are never touched."
        load={() => listBeSchedules(id)} create={(p) => createBeSchedule(id, p)}
        empty="No work schedule — Belgian payroll is blocked until one is approved."
        columns={[periodCol, { label: "Regime", key: "regime" }, { label: "Hours / week", key: "weekly_hours" }, statusCol]}
        actions={[{ label: "Approve", show: isDraft, run: (r) => approveBeSchedule(r.id), ok: "Work schedule approved." }]}
        fields={[
          { key: "effective_from", label: "Effective from", type: "date", required: true },
          { key: "regime", label: "Regime", type: "select", options: options.scheduleRegimes, required: true },
          { key: "weekly_hours", label: "Weekly hours", type: "number", required: true },
          { key: "reference_period", label: "Reference period" },
          { key: "supersedes_id", label: "Supersedes schedule id", type: "number" },
          { key: "evidence_ref", label: "Evidence reference" },
          REASON_FIELD,
        ]} />

      <JPRecordSection
        title="Employment classification" testId="be-classifications"
        description="Per employment line: Joint Committee / sub-committee (from the platform's committee definitions), the linked Joint Committee agreement, function class, seniority, establishment unit and schedule (BE-003, BE-020)."
        load={() => listBeClassifications(id)} create={(p) => createBeClassification(id, p)}
        empty="No classification — Belgian payroll is blocked until one is approved."
        columns={[periodCol, { label: "Line", key: "employment_line" },
          { label: "Joint Committee", render: (r) => [r.joint_committee, r.sub_committee].filter(Boolean).join("/") || "—" },
          { label: "Function", render: (r) => r.function_class || "—" }, statusCol]}
        actions={[{ label: "Approve", show: isDraft, run: (r) => approveBeClassification(r.id), ok: "Classification approved." }]}
        fields={[
          { key: "effective_from", label: "Effective from", type: "date", required: true },
          { key: "employment_line", label: "Employment line", required: true },
          { key: "contract_type", label: "Contract type (required to calculate)", type: "select",
            options: options.contractTypes },
          { key: "contract_start_date", label: "Contract start", type: "date" },
          { key: "contract_end_date", label: "Contract end (fixed term)", type: "date" },
          { key: "joint_committee", label: "Joint Committee", type: "select", options: committeeCodes },
          { key: "sub_committee", label: "Sub-committee" },
          { key: "collective_agreement_id", label: "Joint Committee agreement", type: "select", options: agreements },
          { key: "function_class", label: "Function class" },
          { key: "seniority_months", label: "Seniority (months)", type: "number" },
          { key: "establishment_unit_id", label: "Establishment unit id", type: "number" },
          { key: "work_schedule_id", label: "Work schedule id", type: "number" },
          { key: "evidence_ref", label: "Evidence reference" },
          REASON_FIELD,
        ]} />
      {active.length === 0 && (
        <p className="text-[12px] text-warning" data-testid="be-no-committees">
          No Active Joint Committee definition exists yet — the classification can name a committee only once the
          platform signs one.
        </p>
      )}

      <JPRecordSection
        title="Declarations" testId="be-declarations"
        description="Each declaration keeps its received date, evidence and channel, and counts only once a second user approves it; a later approved declaration of the same type supersedes it (history kept)."
        load={() => listBeDeclarations(id)} create={(p) => createBeDeclaration(id, p)} transform={declarationPayload}
        createLabel="Record as RECEIVED" createdNotice="Recorded — a second user must approve it."
        empty="No declarations."
        columns={[periodCol, { label: "Type", key: "declaration_type" },
          { label: "Value", render: (r) => (r.value && Object.keys(r.value).length ? JSON.stringify(r.value) : "—") },
          { label: "Received", render: (r) => String(r.received_at || "").slice(0, 10) }, statusCol]}
        actions={[
          { label: "Approve", show: (r) => r.status === "RECEIVED", run: (r) => approveBeDeclaration(r.id), ok: "Declaration approved." },
          { label: "Withdraw", show: (r) => r.status === "APPROVED", ok: "Declaration withdrawn.",
            run: async (r) => {
              const reason = ask("Reason for the withdrawal");
              const end = reason && ask("Last day the declaration applies (YYYY-MM-DD)");
              if (!reason || !end) throw new Error("A reason and an end date are required.");
              await withdrawBeDeclaration(r.id, reason, end);
            } },
        ]}
        fields={[
          { key: "declaration_type", label: "Declaration", type: "select", options: options.declarationTypes, required: true },
          { key: "received_at", label: "Received on", type: "date", required: true },
          { key: "effective_from", label: "Effective from", type: "date", required: true },
          { key: "effective_to", label: "Effective to (optional)", type: "date" },
          { key: "source_channel", label: "Channel", type: "select", options: options.sourceChannels, required: true },
          { key: "evidence_ref", label: "Evidence reference", required: true },
          { key: "count", label: "Dependants (count, when relevant)", type: "number" },
          { key: "note", label: "Note" },
        ]} />

      <JPRecordSection
        title="Absence episodes" testId="be-absence-episodes"
        description="Dates, kind and the worker category at the start only, never a diagnosis. A relapse names the earlier episode; a declared different cause starts a new guaranteed period for review. Approved by a second user."
        load={() => listBeAbsenceEpisodes(id)} create={(p) => createBeAbsenceEpisode(id, p)}
        empty="No absence episodes."
        columns={[{ label: "From - to", render: (r) => `${r.start_date} to ${r.end_date || "open"}` },
          { label: "Kind", key: "kind" }, { label: "Category at start", key: "worker_category_at_start" },
          { label: "Relapse of", render: (r) => r.cause_link_id || "-" }, statusCol]}
        actions={[
          { label: "Approve", show: isDraft, run: (r) => approveBeAbsenceEpisode(r.id), ok: "Episode approved." },
          { label: "Cancel", show: (r) => r.status === "DRAFT" || r.status === "ACTIVE", ok: "Episode cancelled.",
            run: async (r) => {
              const reason = ask("Reason for cancelling the episode");
              if (!reason) throw new Error("A reason is required.");
              await cancelBeAbsenceEpisode(r.id, reason);
            } },
        ]}
        fields={[
          { key: "kind", label: "Kind", type: "select", options: options.absenceKinds, required: true },
          { key: "start_date", label: "From", type: "date", required: true },
          { key: "end_date", label: "To", type: "date" },
          { key: "employment_line", label: "Employment line" },
          { key: "cause_link_id", label: "Relapse of episode id", type: "number" },
          { key: "different_cause", label: "Declared different cause", type: "bool" },
          { key: "certificate_ref", label: "Certificate reference" },
          { key: "evidence_ref", label: "Evidence reference" },
          REASON_FIELD,
        ]} />

      <JPRecordSection
        title="Holiday certificates" testId="be-holiday-certificates"
        description="IN from a prior employer (offsets the double holiday pay of the same service year) or OUT on departure. Immutable once a second user approves it; a correction is a new version naming the one it supersedes."
        load={() => listBeHolidayCertificates(id)} create={(p) => createBeHolidayCertificate(id, p)}
        empty="No holiday certificates."
        columns={[{ label: "Direction", key: "direction" }, { label: "Service year", key: "service_year" },
          { label: "Double pay", render: (r) => r.double_pay_amount ?? "-" },
          { label: "Prior employer", render: (r) => r.prior_employer_ref || "-" }, statusCol]}
        actions={[{ label: "Approve", show: isDraft, run: (r) => approveBeHolidayCertificate(r.id),
          ok: "Certificate approved (now immutable)." }]}
        fields={[
          { key: "direction", label: "Direction", type: "select", options: options.certificateDirections, required: true },
          { key: "service_year", label: "Service year", type: "number", required: true },
          { key: "issued_on", label: "Issued on", type: "date" },
          { key: "gross_base_amount", label: "Gross base", type: "number" },
          { key: "simple_pay_amount", label: "Simple holiday pay", type: "number" },
          { key: "double_pay_amount", label: "Double holiday pay", type: "number" },
          { key: "days_paid", label: "Days paid", type: "number" },
          { key: "prior_employer_ref", label: "Prior employer reference" },
          { key: "supersedes_id", label: "Supersedes certificate id", type: "number" },
          { key: "evidence_ref", label: "Evidence reference" },
          REASON_FIELD,
        ]} />

      <BEIdentifierField employeeId={id} identifierTypes={options.employeeIdentifierTypes} />
      <BEResolverPanel employeeId={id} />
    </div>
  );
}

export default function BelgiumStatutoryProfilePanel({ employee, onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-background/40 backdrop-blur-sm" onClick={onClose}>
      <div className="flex h-full w-full max-w-3xl flex-col bg-surface border-l border-border shadow-[0_24px_48px_rgba(0,0,0,0.15)]"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-5 border-b border-border">
          <div>
            <h2 className="text-[15px] font-bold text-foreground">Belgium statutory records</h2>
            <p className="text-[12px] text-foreground-muted mt-0.5">{employee?.name} · {employee?.employeeCode}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-foreground-muted hover:bg-surface-muted">
            <X size={16} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5">
          <BelgiumEmployeeRecords employeeId={employee?.id} />
        </div>
      </div>
    </div>
  );
}
