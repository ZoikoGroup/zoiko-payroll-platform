import { useEffect, useState } from "react";
import {
  approveMyRegistration, createMyRegistration, getEmployees, getMySummary, listMyRegistrations, verifyMyRegistration,
} from "../../../service/payrollService";
import { card, useLoad } from "../../../components/jurisdiction/japan/jpFormat";
import JPRecordSection, { isDraft, statusCol } from "../../../components/jurisdiction/japan/JPRecordSection";
import { REASON_FIELD, period } from "../../../components/jurisdiction/new_zealand/nzOrgOptions";
import { HRD_CATEGORIES } from "../../../components/jurisdiction/malaysia/myOrgOptions";
import { MalaysiaEmployeeRecords } from "../Payroll_Employees/MalaysiaStatutoryProfilePanel";
import MYFilingSettlementPanel from "./MYFilingSettlementPanel";
import MYParallelCyclesSection from "./MYParallelCyclesSection";

// Malaysia Compliance Centre (ZP-MY-ENG-001 "Malaysia country setup"). The
// employer registration per legal employer (HASiL employer number, EPF /
// PERKESO references, the HRD category with its registration number, start
// date and evidence — never inferred from headcount, MY-016) and every
// employee's Malaysia records. Nothing here calculates: the engine reads only
// APPROVED versions on the pay date and BLOCKS when a fact or a signed rule is
// missing.

const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
const ask = (message) => {
  const value = window.prompt(message);
  return value && value.trim() ? value.trim() : null;
};

function SetupStatus() {
  const [summary, error] = useLoad(() => getMySummary());
  if (error) return <p role="alert" className="text-[12px] text-error">{error}</p>;
  if (!summary) return null;
  const pack = (summary.packs || [])[0];
  return (
    <div className="rounded-xl border border-warning/40 bg-warning/10 p-3 text-[12px] text-foreground-secondary" data-testid="my-setup-status">
      <p className="font-semibold text-foreground">Malaysian payroll is not yet certified.</p>
      <p className="mt-1">
        Rule pack {pack ? `${pack.packId} ${pack.version} (${pack.status})` : "not seeded"}: {summary.pendingRows ?? 0} row(s)
        awaiting signature. Until they are signed every Malaysian payslip is blocked with its reason — never estimated.
        PCB stays blocked until the HASiL 2026 specification is archived.
      </p>
      <p className="mt-1">
        Approved here: {summary.activeEmployerRegistrations ?? 0} employer registration(s)
        ({summary.verifiedEmployerRegistrations ?? 0} verified), {summary.activeWorkerProfiles ?? 0} worker profile(s),{" "}
        {summary.activeWorkAssignments ?? 0} work assignment(s), {summary.approvedDeclarations ?? 0} declaration(s).
      </p>
      {(summary.unmet || []).length > 0 && (
        <p className="mt-1">Not yet met: {summary.unmet.map((u) => u.label).join("; ")}. Malaysia opens only when all pass.</p>
      )}
    </div>
  );
}

function EmployerRegistrations() {
  return (
    <JPRecordSection
      title="Employer registration (per legal employer)" testId="my-employer-registrations"
      description="HASiL employer number, EPF and PERKESO employer references, the HRD Corp category with its registration number, start date and evidence (MY-016). Approve (second user), then verify (second user)."
      load={listMyRegistrations} create={createMyRegistration}
      empty="No employer registration — Malaysian payroll is blocked until one is approved and verified."
      columns={[{ label: "In force", render: period }, { label: "Legal name", key: "legal_name" },
        { label: "HASiL employer no.", key: "hasil_employer_no" }, { label: "HRD", key: "hrd_category" },
        { label: "Verification", key: "verification_state" }, statusCol]}
      actions={[
        { label: "Approve", show: isDraft, run: (r) => approveMyRegistration(r.id), ok: "Employer registration approved." },
        { label: "Verify", show: (r) => r.status === "ACTIVE" && r.verification_state !== "VERIFIED", ok: "Verified.",
          run: async (r) => {
            const reason = ask("Verification evidence / reason");
            if (!reason) throw new Error("A reason is required.");
            await verifyMyRegistration(r.id, "VERIFIED", reason);
          } },
        { label: "Reject", show: (r) => r.status === "ACTIVE" && r.verification_state === "UNVERIFIED", ok: "Marked rejected.",
          run: async (r) => {
            const reason = ask("Why is the registration rejected?");
            if (!reason) throw new Error("A reason is required.");
            await verifyMyRegistration(r.id, "REJECTED", reason);
          } },
      ]}
      fields={[
        { key: "effective_from", label: "Effective from", type: "date", required: true },
        { key: "legal_name", label: "Legal name", required: true },
        { key: "hasil_employer_no", label: "HASiL employer number (E)", required: true },
        { key: "epf_employer_no", label: "EPF employer number" },
        { key: "perkeso_employer_code", label: "PERKESO employer code" },
        { key: "hrd_category", label: "HRD Corp category", type: "select", options: HRD_CATEGORIES, required: true },
        { key: "hrd_registration_no", label: "HRD Corp registration number" },
        { key: "hrd_category_from", label: "HRD category from", type: "date" },
        { key: "hrd_category_evidence_ref", label: "HRD category evidence" },
        { key: "bank_export_ref", label: "Bank export reference" },
        { key: "filing_credential_ref", label: "Filing credential reference (never the secret)" },
        { key: "evidence_ref", label: "Evidence reference" },
        REASON_FIELD,
      ]} />
  );
}

function EmployeeRecords() {
  const [employees, setEmployees] = useState([]);
  const [selected, setSelected] = useState("");
  useEffect(() => {
    let ignore = false;
    getEmployees({}).then((list) => {
      if (!ignore) setEmployees(list.filter((e) => (e.countryCode || e.country) === "MY"));
    });
    return () => { ignore = true; };
  }, []);
  return (
    <section className={card} data-testid="my-employee-picker">
      <h3 className="text-[14px] font-semibold text-foreground">Employee records</h3>
      <label className="mt-2 flex flex-col gap-1 text-[11px] font-semibold text-foreground-muted">
        Employee
        <select className={input} value={selected} onChange={(e) => setSelected(e.target.value)}>
          <option value="">— Select a Malaysian employee —</option>
          {employees.map((e) => <option key={e.id} value={e.id}>{e.name} · {e.employeeCode}</option>)}
        </select>
      </label>
      {employees.length === 0 && <p className="mt-2 text-[12px] text-foreground-muted">No employees with country MY.</p>}
      {selected && <div className="mt-4"><MalaysiaEmployeeRecords key={selected} employeeId={Number(selected)} /></div>}
    </section>
  );
}

export default function MYComplianceCentreTab() {
  return (
    <div className="space-y-4" data-testid="my-compliance-centre">
      <SetupStatus />
      <EmployerRegistrations />
      <MYFilingSettlementPanel />
      <MYParallelCyclesSection />
      <EmployeeRecords />
    </div>
  );
}
