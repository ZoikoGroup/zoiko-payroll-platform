import { X } from "lucide-react";
import {
  approveNzKiwiSaver, approveNzOpeningBalance, approveNzTaxProfile, approveNzWorkPattern, createNzKiwiSaver,
  createNzTaxProfile, createNzWorkPattern, listNzKiwiSaver, listNzOpeningBalances, listNzTaxProfiles,
  listNzWorkPatterns, requestNzOpeningBalance,
} from "../../../service/payrollService";
import JPRecordSection, { isDraft, statusCol } from "../../../components/jurisdiction/japan/JPRecordSection";
import {
  ESCT_BASES, HOURS_SOURCES, IRD_NUMBER_STATES, KS_DESTINATIONS, KS_MEMBERSHIP, KS_ROUTES, MIN_WAGE_CATEGORIES,
  NZ_WEEKDAYS, OBLIGATIONS, PATTERN_TYPES, REASON_FIELD, RESIDENCY, SL_CERTIFICATES, TAX_CODES, TAX_CODE_SOURCES, period,
} from "../../../components/jurisdiction/new_zealand/nzOrgOptions";
import NZIrdNumberField from "./NZIrdNumberField";
import NZNoticeSection from "./NZNoticeSection";
import {
  NZCashUps, NZEmployments, NZEntitlements, NZFinalPay, NZGrossEarnings, NZLeaveEvents, NZLeavePay, NZPublicHolidays,
} from "./NZLeaveSections";

// Every New Zealand record for one employee (ZP-NZ-ENG-001 §3-§8, §10). Each
// version is captured as DRAFT with a reason and counts only after a SECOND
// user approves it; the engine selects by the payday and BLOCKS while a fact
// it needs is missing — nothing is inferred (e.g. the minimum-wage category is
// never derived from age).

const periodCol = { label: "In force", render: period };

// weekly_schedule: the MON..SUN hours inputs become one object.
function workPatternPayload(values) {
  const out = { ...values };
  const schedule = {};
  for (const day of NZ_WEEKDAYS) {
    const key = `hours_${day.toLowerCase()}`;
    if (out[key] !== undefined) schedule[day] = out[key];
    delete out[key];
  }
  if (Object.keys(schedule).length) {
    out.weekly_schedule = Object.fromEntries(NZ_WEEKDAYS.map((d) => [d, schedule[d] ?? "0"]));
  }
  if (out.roster_schedule_json) {
    out.roster_schedule = JSON.parse(out.roster_schedule_json);
    delete out.roster_schedule_json;
  }
  return out;
}

export function NewZealandEmployeeRecords({ employeeId }) {
  const id = employeeId;
  return (
    <div className="space-y-4" data-testid="nz-employee-records">
      <JPRecordSection
        title="Tax profile" testId="nz-tax-profile"
        description="Tax code and its source (IR330 / IRD notice / no notification), residency, tailored-code and student-loan certificates, and the evidenced minimum-wage category."
        load={() => listNzTaxProfiles(id)} create={(p) => createNzTaxProfile(id, p)}
        empty="No tax profile — New Zealand payslips are blocked until one is approved."
        columns={[periodCol, { label: "Code", key: "tax_code" }, { label: "Source", key: "tax_code_source" },
          { label: "IRD number", key: "ird_number_state" }, { label: "Min wage", key: "min_wage_category" }, statusCol]}
        actions={[{ label: "Approve", show: isDraft, run: (r) => approveNzTaxProfile(r.id), ok: "Tax profile approved." }]}
        fields={[
          { key: "effective_from", label: "Effective from", type: "date", required: true },
          { key: "tax_code", label: "Tax code", type: "select", options: TAX_CODES, required: true },
          { key: "tax_code_source", label: "Code source", type: "select", options: TAX_CODE_SOURCES, required: true },
          { key: "ird_number_state", label: "IRD number state", type: "select", options: IRD_NUMBER_STATES, required: true },
          { key: "declaration_received_on", label: "Declaration received", type: "date" },
          { key: "declaration_ref", label: "Declaration reference" },
          { key: "residency_status", label: "Residency", type: "select", options: RESIDENCY },
          { key: "tailored_certificate_ref", label: "STC certificate" },
          { key: "tailored_rate_pct", label: "STC rate %", type: "number" },
          { key: "tailored_valid_from", label: "STC valid from", type: "date" },
          { key: "tailored_valid_to", label: "STC valid to", type: "date" },
          { key: "sl_certificate_type", label: "Student-loan certificate", type: "select", options: SL_CERTIFICATES },
          { key: "sl_certificate_ref", label: "SL certificate reference" },
          { key: "sl_certificate_rate_pct", label: "SL certificate rate %", type: "number" },
          { key: "sl_certificate_valid_from", label: "SL certificate from", type: "date" },
          { key: "sl_certificate_valid_to", label: "SL certificate to", type: "date" },
          { key: "min_wage_category", label: "Minimum-wage category", type: "select", options: MIN_WAGE_CATEGORIES },
          { key: "min_wage_evidence_ref", label: "Category evidence (not ADULT)" },
          { key: "evidence_ref", label: "Evidence reference" },
          REASON_FIELD,
        ]} />

      <JPRecordSection
        title="KiwiSaver" testId="nz-kiwisaver"
        description="Membership, rates (checked against the pack on the payday), temporary reduction and savings suspension each with evidence and dates, ESCT rate and settlement destination."
        load={() => listNzKiwiSaver(id)} create={(p) => createNzKiwiSaver(id, p)}
        empty="No KiwiSaver election."
        columns={[periodCol, { label: "Membership", key: "membership_state" },
          { label: "Rates (ee / er)", render: (r) => `${r.employee_rate_pct ?? "default"} / ${r.employer_rate_pct ?? "minimum"}` },
          { label: "ESCT", render: (r) => (r.esct_rate_pct == null ? "—" : `${r.esct_rate_pct}%`) }, statusCol]}
        actions={[{ label: "Approve", show: isDraft, run: (r) => approveNzKiwiSaver(r.id), ok: "KiwiSaver election approved." }]}
        fields={[
          { key: "effective_from", label: "Effective from", type: "date", required: true },
          { key: "membership_state", label: "Membership", type: "select", options: KS_MEMBERSHIP, required: true },
          { key: "enrolment_route", label: "Enrolment route", type: "select", options: KS_ROUTES },
          { key: "opt_out_evidence_ref", label: "Opt-out evidence" },
          { key: "employee_rate_pct", label: "Employee rate %", type: "number" },
          { key: "employer_rate_pct", label: "Employer rate %", type: "number" },
          { key: "reduction_ref", label: "Temporary reduction reference" },
          { key: "reduction_from", label: "Reduction from", type: "date" },
          { key: "reduction_to", label: "Reduction to", type: "date" },
          { key: "employer_matches_reduction", label: "Employer matches reduction", type: "bool" },
          { key: "suspension_ref", label: "Savings suspension reference" },
          { key: "suspension_from", label: "Suspension from", type: "date" },
          { key: "suspension_to", label: "Suspension to", type: "date" },
          { key: "esct_rate_pct", label: "ESCT rate %", type: "number" },
          { key: "esct_basis", label: "ESCT basis", type: "select", options: ESCT_BASES },
          { key: "esct_basis_amount", label: "ESCT basis amount", type: "number" },
          { key: "esct_tax_year", label: "ESCT tax year (e.g. 2026-27)" },
          { key: "settlement_destination", label: "Settlement", type: "select", options: KS_DESTINATIONS },
          { key: "complying_fund_ref", label: "Complying fund reference" },
          { key: "evidence_ref", label: "Evidence reference" },
          REASON_FIELD,
        ]} />

      <JPRecordSection
        title="Work pattern" testId="nz-work-pattern"
        description="Days and hours from the contract or roster: used by the minimum-wage test, the working-day test and leave."
        load={() => listNzWorkPatterns(id)} create={(p) => createNzWorkPattern(id, p)} transform={workPatternPayload}
        empty="No work pattern."
        columns={[periodCol, { label: "Type", key: "pattern_type" },
          { label: "Hours / days per week", render: (r) => `${r.contracted_hours_per_week ?? "—"} / ${r.contracted_days_per_week ?? "—"}` },
          { label: "Week", render: (r) => (r.weekly_schedule ? NZ_WEEKDAYS.map((d) => `${d[0]}${r.weekly_schedule[d] ?? 0}`).join(" ") : "—") },
          statusCol]}
        actions={[{ label: "Approve", show: isDraft, run: (r) => approveNzWorkPattern(r.id), ok: "Work pattern approved." }]}
        fields={[
          { key: "effective_from", label: "Effective from", type: "date", required: true },
          { key: "pattern_type", label: "Pattern", type: "select", options: PATTERN_TYPES, required: true },
          { key: "hours_source", label: "Hours source", type: "select", options: HOURS_SOURCES, required: true },
          { key: "contracted_hours_per_week", label: "Hours per week", type: "number" },
          { key: "contracted_days_per_week", label: "Days per week", type: "number" },
          ...NZ_WEEKDAYS.map((d) => ({ key: `hours_${d.toLowerCase()}`, label: `${d} hours (fixed)`, type: "number" })),
          { key: "roster_cycle_weeks", label: "Roster cycle (weeks)", type: "number" },
          { key: "roster_schedule_json", label: "Roster JSON ({\"0\": {\"MON\": 8}, …})" },
          { key: "evidence_ref", label: "Evidence reference" },
          REASON_FIELD,
        ]} />

      <NZNoticeSection employeeId={id} />

      <JPRecordSection
        title="Year-to-date opening balances" testId="nz-opening-balances"
        description="Carried in from an incumbent payroll for a mid-year start (e.g. ACC liable earnings for the annual cap). Evidence required; a second user approves."
        load={() => listNzOpeningBalances(id)} create={(p) => requestNzOpeningBalance(id, p)} createLabel="Request"
        createdNotice="Requested — a second user must approve it." empty="No opening balances."
        columns={[{ label: "Tax year", key: "taxYear" }, { label: "Obligation", key: "obligation" },
          { label: "Amount", key: "amount" }, { label: "Evidence", key: "evidenceRef" },
          { label: "Status", render: (r) => (r.decided ? "Approved" : "Requested") }]}
        actions={[{ label: "Approve", show: (r) => !r.decided, run: (r) => approveNzOpeningBalance(r.requestId), ok: "Opening balance approved." }]}
        fields={[
          { key: "tax_year", label: "Tax year (e.g. 2026-27)", required: true },
          { key: "obligation", label: "Obligation", type: "select", options: OBLIGATIONS, required: true },
          { key: "amount", label: "Amount", type: "number", required: true },
          { key: "evidence_ref", label: "Evidence (incumbent figures)", required: true },
          REASON_FIELD,
        ]} />

      <NZIrdNumberField employeeId={id} />

      <h4 className="pt-2 text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Holidays Act</h4>
      <NZEmployments employeeId={id} />
      <NZEntitlements employeeId={id} />
      <NZLeaveEvents employeeId={id} />
      <NZPublicHolidays employeeId={id} />
      <NZLeavePay employeeId={id} />
      <NZCashUps employeeId={id} />
      <NZFinalPay employeeId={id} />
      <NZGrossEarnings employeeId={id} />
    </div>
  );
}

export default function NewZealandStatutoryProfilePanel({ employee, onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-background/40 backdrop-blur-sm" onClick={onClose}>
      <div className="flex h-full w-full max-w-3xl flex-col bg-surface border-l border-border shadow-[0_24px_48px_rgba(0,0,0,0.15)]"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-5 border-b border-border">
          <div>
            <h2 className="text-[15px] font-bold text-foreground">New Zealand statutory records</h2>
            <p className="text-[12px] text-foreground-muted mt-0.5">{employee?.name} · {employee?.employeeCode}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-foreground-muted hover:bg-surface-muted">
            <X size={16} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5">
          <NewZealandEmployeeRecords employeeId={employee?.id} />
        </div>
      </div>
    </div>
  );
}
