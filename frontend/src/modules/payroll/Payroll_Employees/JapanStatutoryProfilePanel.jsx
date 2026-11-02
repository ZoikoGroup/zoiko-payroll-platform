import { X } from "lucide-react";
import {
  applyJpSocialInsuranceEvent, approveJpAttendanceApproval, approveJpEmploymentInsurance,
  approveJpResidentTaxNotice, approveJpSocialInsurance, approveJpSocialInsuranceEvent, approveJpTaxProfile,
  createJpEmploymentInsurance, createJpResidentTaxNotice, createJpSocialInsurance, createJpSocialInsuranceEvent,
  createJpTaxProfile, listJpAttendanceApprovals, listJpEmploymentInsurance, listJpResidentTaxNotices,
  listJpSocialInsurance, listJpSocialInsuranceEvents, listJpTaxProfiles, requestJpAttendanceApproval,
} from "../../../service/payrollService";
import JPRecordSection, { isDraft, periodCol, statusCol } from "../../../components/jurisdiction/japan/JPRecordSection";
import { formatJpyAuto } from "../../../components/jurisdiction/japan/jpComponentConfig";
import JPMyNumberField from "./JPMyNumberField";

// Every Japan record for one employee (ZP-JP-ENG-001 §3-§6). Each version is
// captured as DRAFT and counts only after a second user approves it; the
// engine BLOCKS a payslip while a fact it needs is missing.

const EVENT_TYPES = ["QUALIFICATION", "LOSS", "ANNUAL_DETERMINATION", "ADHOC_REVISION",
  "MATERNITY_EXEMPTION", "CHILDCARE_EXEMPTION", "RETURN_TO_WORK_REVISION"];
const SMR_KEYS = ["smr_health_grade", "smr_health_amount", "smr_pension_grade", "smr_pension_amount"];

function residentTaxPayload(values) {
  // The notice's twelve monthly amounts, from the first deduction month on.
  const amounts = String(values.monthly_amounts_list || "").split(/[,\s]+/).filter(Boolean);
  const start = String(values.first_deduction_month || "");
  const out = { ...values };
  delete out.monthly_amounts_list;
  if (/^\d{4}-\d{2}/.test(start)) {
    const year = Number(start.slice(0, 4));
    const month = Number(start.slice(5, 7)) - 1;
    out.monthly_amounts = Object.fromEntries(amounts.map((amount, i) => {
      const index = year * 12 + month + i;
      return [`${Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, "0")}`, amount];
    }));
  }
  return out;
}

function eventPayload(values) {
  const out = {};
  const smr = {};
  for (const [key, value] of Object.entries(values)) {
    if (SMR_KEYS.includes(key)) smr[key] = value;
    else out[key] = value;
  }
  if (Object.keys(smr).length) out.payload = smr;
  return out;
}

export function JapanEmployeeRecords({ employeeId }) {
  const id = employeeId;
  return (
    <div className="space-y-4">
      <JPRecordSection
        title="Worker tax profile" testId="jp-tax-profile"
        description="Residency, withholding column (PRIMARY with the dependant declaration, otherwise SECONDARY), dependants and resident-tax collection."
        load={() => listJpTaxProfiles(id)} create={(p) => createJpTaxProfile(id, p)}
        empty="No tax profile — Japan payslips for this employee are blocked."
        columns={[periodCol,
          { label: "Residency", key: "residency_status" },
          { label: "Column", key: "declaration_class" },
          { label: "Dependants", key: "dependants_count" },
          { label: "Resident tax", key: "resident_tax_collection" },
          statusCol]}
        actions={[{ label: "Approve", show: isDraft, run: (r) => approveJpTaxProfile(r.id), ok: "Tax profile approved." }]}
        fields={[
          { key: "effective_from", label: "Effective from", type: "date", required: true },
          { key: "residency_status", label: "Residency", type: "select", options: ["RESIDENT", "NON_RESIDENT"] },
          { key: "declaration_class", label: "Withholding column", type: "select", options: ["PRIMARY", "SECONDARY"] },
          { key: "declaration_received_on", label: "Declaration received", type: "date" },
          { key: "dependants_count", label: "Dependants (0-7)", type: "number" },
          { key: "municipality_code", label: "Municipality code", placeholder: "6 digits" },
          { key: "resident_tax_collection", label: "Resident tax", type: "select", options: ["SPECIAL", "NOT_APPLICABLE"] },
          { key: "evidence_ref", label: "Evidence reference" },
        ]} />

      <JPRecordSection
        title="Social-insurance enrolment" testId="jp-social-insurance"
        description="Health and pension standard monthly remuneration are separate amounts; neither is ever derived from pay here."
        load={() => listJpSocialInsurance(id)} create={(p) => createJpSocialInsurance(id, p)}
        empty="No enrolment — Japan payslips for this employee are blocked."
        columns={[periodCol,
          { label: "Health SMR", render: (r) => (r.smr_health_amount == null ? "—" : formatJpyAuto(r.smr_health_amount)) },
          { label: "Pension SMR", render: (r) => (r.smr_pension_amount == null ? "—" : formatJpyAuto(r.smr_pension_amount)) },
          { label: "Basis", key: "smr_basis" },
          { label: "Care", key: "care_state" },
          statusCol]}
        actions={[{ label: "Approve", show: isDraft, run: (r) => approveJpSocialInsurance(r.id), ok: "Enrolment approved." }]}
        fields={[
          { key: "effective_from", label: "Effective from", type: "date", required: true },
          { key: "health_eligible", label: "Health insured", type: "bool", required: true },
          { key: "pension_eligible", label: "Pension insured", type: "bool", required: true },
          { key: "smr_health_grade", label: "Health grade", type: "number" },
          { key: "smr_health_amount", label: "Health SMR (JPY)", type: "number" },
          { key: "smr_pension_grade", label: "Pension grade", type: "number" },
          { key: "smr_pension_amount", label: "Pension SMR (JPY)", type: "number" },
          { key: "smr_basis", label: "SMR basis", type: "select",
            options: ["QUALIFICATION", "ANNUAL_DETERMINATION", "ADHOC_REVISION", "RETURN_TO_WORK", "OTHER"] },
          { key: "care_state", label: "Care insurance", type: "select", options: ["NOT_COVERED", "COVERED", "EXEMPT"] },
          { key: "child_support_state", label: "Child support", type: "select", options: ["COVERED", "EXEMPT"] },
          { key: "qualification_date", label: "Qualification date", type: "date" },
          { key: "evidence_ref", label: "Evidence reference" },
        ]} />

      <JPRecordSection
        title="Social-insurance events" testId="jp-si-events"
        description="An SMR revision is a proposal: it changes the enrolment only after a second user approves it and it is applied as a new version."
        load={() => listJpSocialInsuranceEvents(id)} create={(p) => createJpSocialInsuranceEvent(id, p)}
        transform={eventPayload} createLabel="Record event"
        createdNotice="Event recorded — a second user must approve it before it can be applied."
        empty="No events."
        columns={[
          { label: "Event", key: "event_type" },
          { label: "From", key: "effective_from" },
          { label: "Bonus paid", key: "bonus_paid_on" },
          { label: "Report due", key: "report_due_on" },
          { label: "Status", key: "submission_status" }]}
        actions={[
          { label: "Approve", show: (r) => r.submission_status === "CREATED" && r.event_type !== "BONUS",
            run: (r) => approveJpSocialInsuranceEvent(r.id), ok: "Event approved." },
          { label: "Apply", show: (r) => r.submission_status === "APPROVED"
              && ["ANNUAL_DETERMINATION", "ADHOC_REVISION", "RETURN_TO_WORK_REVISION"].includes(r.event_type)
              && !(r.payload && r.payload.applied_enrollment_id),
            run: (r) => applyJpSocialInsuranceEvent(r.id), ok: "Applied as a new enrolment version." },
        ]}
        fields={[
          { key: "event_type", label: "Event", type: "select", options: EVENT_TYPES, required: true },
          { key: "effective_from", label: "Effective from", type: "date", required: true },
          { key: "effective_to", label: "Effective to", type: "date" },
          { key: "smr_health_grade", label: "New health grade", type: "number" },
          { key: "smr_health_amount", label: "New health SMR", type: "number" },
          { key: "smr_pension_grade", label: "New pension grade", type: "number" },
          { key: "smr_pension_amount", label: "New pension SMR", type: "number" },
          { key: "evidence_ref", label: "Evidence reference (required for exemptions)" },
        ]} />

      <JPRecordSection
        title="Employment insurance" testId="jp-employment-insurance"
        load={() => listJpEmploymentInsurance(id)} create={(p) => createJpEmploymentInsurance(id, p)}
        empty="No employment-insurance profile — Japan payslips for this employee are blocked."
        columns={[periodCol,
          { label: "Insured", render: (r) => (r.insured ? "Yes" : "No") },
          { label: "Class", key: "industry_class" }, statusCol]}
        actions={[{ label: "Approve", show: isDraft, run: (r) => approveJpEmploymentInsurance(r.id), ok: "Profile approved." }]}
        fields={[
          { key: "effective_from", label: "Effective from", type: "date", required: true },
          { key: "insured", label: "Insured", type: "bool", required: true },
          { key: "industry_class", label: "Industry class", type: "select",
            options: ["GENERAL", "AGRICULTURE_SAKE", "CONSTRUCTION"], required: true },
          { key: "qualification_date", label: "Qualification date", type: "date" },
          { key: "evidence_ref", label: "Evidence reference" },
        ]} />

      <JPRecordSection
        title="Resident-tax notices" testId="jp-resident-tax"
        description="Resident tax is never calculated: the twelve monthly amounts come from the municipality's notice. A change notice is a new version; earlier months keep the notice in force then."
        load={() => listJpResidentTaxNotices(id)} create={(p) => createJpResidentTaxNotice(id, p)}
        transform={residentTaxPayload} createLabel="Record notice"
        empty="No notice — special collection blocks until one is approved."
        columns={[
          { label: "Municipality", key: "municipality_code" },
          { label: "Year", key: "fiscal_notice_year" },
          { label: "Notice", key: "notice_id" },
          { label: "Version", key: "version" },
          { label: "Total", render: (r) => (r.total_amount == null ? "—" : formatJpyAuto(r.total_amount)) },
          statusCol]}
        actions={[{ label: "Approve", show: (r) => r.status === "IMPORTED",
          run: (r) => approveJpResidentTaxNotice(r.id), ok: "Notice approved." }]}
        fields={[
          { key: "municipality_code", label: "Municipality code", required: true, placeholder: "6 digits" },
          { key: "fiscal_notice_year", label: "Notice year", type: "number", required: true },
          { key: "notice_id", label: "Notice reference", required: true },
          { key: "received_on", label: "Received on", type: "date", required: true },
          { key: "first_deduction_month", label: "First deduction month", type: "date", required: true },
          { key: "monthly_amounts_list", label: "12 monthly amounts (comma-separated)", required: true },
          { key: "total_amount", label: "Notice total (JPY)", type: "number", required: true },
          { key: "source_hash", label: "Notice file SHA-256", required: true },
          { key: "evidence_ref", label: "Evidence reference" },
        ]} />

      <JPRecordSection
        title="Attendance approvals" testId="jp-attendance"
        description="Hours come only from the attendance records. A second user approves a period; any change to its attendance afterwards makes the approval stale and the engine treats the hours as unapproved."
        load={() => listJpAttendanceApprovals(id)} create={(p) => requestJpAttendanceApproval(id, p)}
        createLabel="Request approval"
        createdNotice="Requested — a second user must approve the period."
        empty="No attendance approvals."
        columns={[
          { label: "Period", render: (r) => `${r.period_start} → ${r.period_end}` },
          { label: "Rows", key: "row_count" },
          { label: "Status", key: "status" }]}
        actions={[{ label: "Approve", show: (r) => r.status === "REQUESTED",
          run: (r) => approveJpAttendanceApproval(r.id), ok: "Attendance approved." }]}
        fields={[
          { key: "period_start", label: "Period start", type: "date", required: true },
          { key: "period_end", label: "Period end", type: "date", required: true },
          { key: "evidence_ref", label: "Evidence reference" },
        ]} />

      <JPMyNumberField employeeId={id} />
    </div>
  );
}

export default function JapanStatutoryProfilePanel({ employee, onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-background/40 backdrop-blur-sm" onClick={onClose}>
      <div className="flex h-full w-full max-w-3xl flex-col bg-surface border-l border-border shadow-[0_24px_48px_rgba(0,0,0,0.15)]"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-5 border-b border-border">
          <div>
            <h2 className="text-[15px] font-bold text-foreground">Japan statutory records</h2>
            <p className="text-[12px] text-foreground-muted mt-0.5">{employee?.name} · {employee?.employeeCode}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-foreground-muted hover:bg-surface-muted">
            <X size={16} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5">
          <JapanEmployeeRecords employeeId={employee?.id} />
        </div>
      </div>
    </div>
  );
}
