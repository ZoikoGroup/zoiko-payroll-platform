import { useEffect, useState } from "react";
import {
  approveJpEmployerRegistration, approveJpWorkConditions, createJpEmployerRegistration, createJpWorkConditions,
  getEmployees, getJpSummary, listJpBonusReports, listJpEmployerRegistrations, listJpWorkConditions,
} from "../../../service/payrollService";
import { card, useLoad } from "../../../components/jurisdiction/japan/jpFormat";
import { Table } from "../../../components/jurisdiction/japan/jpShared";
import { formatJpyAuto } from "../../../components/jurisdiction/japan/jpComponentConfig";
import JPRecordSection, { WEEKDAYS, isDraft, periodCol, statusCol } from "../../../components/jurisdiction/japan/JPRecordSection";
import { JapanEmployeeRecords } from "../Payroll_Employees/JapanStatutoryProfilePanel";
import JPObligationsPanel from "./JPObligationsPanel";
import JPYearEndPanel from "./JPYearEndPanel";

// Japan Compliance Centre (ZP-JP-ENG-001). Organisation-level setup (employer
// registration, work calendar), the JPS bonus report list, and every
// employee's Japan records. Nothing here calculates: the engine reads only
// APPROVED versions and BLOCKS when a fact is missing.

const weekdayList = (text) => (text ? String(text).split(",").map((d) => WEEKDAYS[Number(d)] || d).join(" ") : "—");

function SetupStatus() {
  const [summary, error] = useLoad(() => getJpSummary());
  if (error) return <p role="alert" className="text-[12px] text-error">{error}</p>;
  if (!summary) return null;
  const pack = (summary.packs || [])[0];
  return (
    <div className="rounded-xl border border-warning/40 bg-warning/10 p-3 text-[12px] text-foreground-secondary" data-testid="jp-setup-status">
      <p className="font-semibold text-foreground">Japan payroll is not yet certified.</p>
      <p className="mt-1">
        Rule pack {pack ? `${pack.packId} ${pack.version} (${pack.status})` : "not seeded"}. Until the official tables are
        signed (release gates G1–G5) every Japan payslip is blocked with its reason — never estimated.
      </p>
      <p className="mt-1">
        Approved here: {summary.activeEmployerRegistrations ?? 0} employer registration(s),{" "}
        {summary.activeWorkerTaxProfiles ?? 0} tax profile(s), {summary.activeSocialInsuranceEnrollments ?? 0} enrolment(s),{" "}
        {summary.approvedResidentTaxNotices ?? 0} resident-tax notice(s); {summary.pendingSocialInsuranceEvents ?? 0} event(s) awaiting approval.
      </p>
    </div>
  );
}

function BonusReports() {
  const [rows, error, loading] = useLoad(() => listJpBonusReports("OPEN"));
  return (
    <section className={card} data-testid="jp-bonus-reports">
      <h3 className="text-[14px] font-semibold text-foreground">Bonus payment reports (Japan Pension Service)</h3>
      <p className="mb-3 text-[12px] text-foreground-muted">
        Recorded automatically when a run with a bonus is paid. Due within the content&apos;s report window of the payment date.
      </p>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {loading ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        <Table rows={rows} empty="No open bonus reports."
          columns={[
            { label: "Employee", key: "employeeId" },
            { label: "Bonus paid", key: "bonusPaidOn" },
            { label: "Standard bonus amount", render: (r) => (r.sbaAmount == null ? "—" : formatJpyAuto(r.sbaAmount)) },
            { label: "Due", render: (r) => <span className={r.overdue ? "font-semibold text-error" : ""}>{r.reportDueOn}{r.overdue ? " — overdue" : ""}</span> },
            { label: "Status", key: "submissionStatus" },
          ]} />
      )}
    </section>
  );
}

function EmployeeRecords() {
  const [employees, setEmployees] = useState([]);
  const [selected, setSelected] = useState("");
  useEffect(() => {
    let ignore = false;
    getEmployees({}).then((list) => {
      if (!ignore) setEmployees(list.filter((e) => (e.countryCode || e.country) === "JP"));
    });
    return () => { ignore = true; };
  }, []);
  return (
    <section className={card} data-testid="jp-employee-records">
      <h3 className="text-[14px] font-semibold text-foreground">Employee records</h3>
      <label className="mt-2 flex flex-col gap-1 text-[11px] font-semibold text-foreground-muted">
        Employee
        <select className="rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground"
          value={selected} onChange={(e) => setSelected(e.target.value)}>
          <option value="">— Select a Japan employee —</option>
          {employees.map((e) => <option key={e.id} value={e.id}>{e.name} · {e.employeeCode}</option>)}
        </select>
      </label>
      {employees.length === 0 && <p className="mt-2 text-[12px] text-foreground-muted">No employees with country JP.</p>}
      {selected && <div className="mt-4"><JapanEmployeeRecords key={selected} employeeId={Number(selected)} /></div>}
    </section>
  );
}

export default function JPComplianceCentreTab() {
  return (
    <div className="space-y-4">
      <SetupStatus />
      <JPRecordSection
        title="Employer registration" testId="jp-employer-registration"
        description="Corporate number, withholding office, Japan Pension Service and labour-insurance numbers, and the health insurer whose rates apply."
        load={listJpEmployerRegistrations} create={createJpEmployerRegistration}
        empty="No employer registration — Japan payroll is blocked until one is approved."
        columns={[periodCol,
          { label: "Health insurer", render: (r) => `${r.health_insurer_type || "—"} ${r.health_insurer_prefecture || r.health_insurer_code || ""}` },
          { label: "EI class", key: "ei_industry_class" }, statusCol]}
        actions={[{ label: "Approve", show: isDraft, run: (r) => approveJpEmployerRegistration(r.id), ok: "Registration approved." }]}
        fields={[
          { key: "effective_from", label: "Effective from", type: "date", required: true },
          { key: "corporate_number", label: "Corporate number (13 digits)" },
          { key: "withholding_tax_office", label: "Withholding tax office" },
          { key: "withholding_payer_status", label: "Withholding payment", type: "select", options: ["STANDARD", "SMALL_EMPLOYER_SPECIAL"] },
          { key: "jps_office_symbol", label: "JPS office symbol" },
          { key: "jps_office_number", label: "JPS office number" },
          { key: "health_insurer_type", label: "Health insurer", type: "select", options: ["KYOKAI_KENPO", "HEALTH_INSURANCE_SOCIETY"], required: true },
          { key: "health_insurer_prefecture", label: "Kyokai prefecture (JIS 01-47)" },
          { key: "health_insurer_code", label: "Society insurer code" },
          { key: "si_deduction_timing", label: "SI deduction timing", type: "select", options: ["CURRENT_MONTH", "FOLLOWING_MONTH"] },
          { key: "labour_insurance_number", label: "Labour insurance number (14 digits)" },
          { key: "ei_office_number", label: "Employment insurance office number" },
          { key: "ei_industry_class", label: "EI industry class", type: "select", options: ["GENERAL", "AGRICULTURE_SAKE", "CONSTRUCTION"], required: true },
          { key: "evidence_ref", label: "Evidence reference" },
        ]} />
      <JPRecordSection
        title="Work conditions and calendar" testId="jp-work-conditions"
        description="Company-wide working time from the work rules. Only the standard system is certified; the statutory day off is never a national holiday unless the rules make it so."
        load={listJpWorkConditions} create={createJpWorkConditions}
        empty="No work conditions — salary payslips are blocked until approved."
        columns={[periodCol,
          { label: "Daily / monthly", render: (r) => `${r.scheduled_daily_minutes ?? "—"} min / ${r.scheduled_monthly_hours ?? "—"} h` },
          { label: "Work days", render: (r) => weekdayList(r.scheduled_weekdays) },
          { label: "Statutory day off", render: (r) => (r.statutory_day_off_weekday == null ? "Not recorded" : WEEKDAYS[r.statutory_day_off_weekday]) },
          { label: "Holidays off", render: (r) => (r.public_holidays_off == null ? "Not recorded" : r.public_holidays_off ? "Yes" : "No") },
          { label: "Prefecture", key: "workplace_prefecture" }, statusCol]}
        actions={[{ label: "Approve", show: isDraft, run: (r) => approveJpWorkConditions(r.id), ok: "Work conditions approved." }]}
        fields={[
          { key: "effective_from", label: "Effective from", type: "date", required: true },
          { key: "working_time_system", label: "Working-time system", type: "select", options: ["STANDARD"], required: true },
          { key: "week_start_day", label: "Week starts", type: "select", options: WEEKDAYS.map((d, i) => [String(i), d]), required: true },
          { key: "scheduled_weekdays", label: "Scheduled work days", type: "weekdays" },
          { key: "statutory_day_off_weekday", label: "Statutory day off", type: "select", options: WEEKDAYS.map((d, i) => [String(i), d]) },
          { key: "public_holidays_off", label: "National holidays are days off", type: "bool" },
          { key: "scheduled_daily_minutes", label: "Scheduled minutes per day", type: "number", required: true },
          { key: "scheduled_monthly_hours", label: "Scheduled hours per month", type: "number", required: true },
          { key: "workplace_prefecture", label: "Workplace prefecture (JIS 01-47)", required: true },
          { key: "evidence_ref", label: "Evidence reference" },
        ]} />
      <BonusReports />
      <JPObligationsPanel />
      <JPYearEndPanel />
      <EmployeeRecords />
    </div>
  );
}
