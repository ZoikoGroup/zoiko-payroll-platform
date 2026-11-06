import { useEffect, useState } from "react";
import {
  approvePlRegistration, createPlRegistration, getEmployees, getPlSummary, listPlPpkReenrolmentDue,
  listPlRegistrations, setPlEmployerNrs, verifyPlRegistration,
} from "../../../service/payrollService";
import { card, useLoad } from "../../../components/jurisdiction/japan/jpFormat";
import JPRecordSection, { btn, isDraft, statusCol } from "../../../components/jurisdiction/japan/JPRecordSection";
import { REASON_FIELD, errorText, period } from "../../../components/jurisdiction/new_zealand/nzOrgOptions";
import { ACCIDENT_RATE_SOURCES, ZUS_DEADLINE_CLASSES } from "../../../components/jurisdiction/poland/plOrgOptions";
import { PolandEmployeeRecords } from "../Payroll_Employees/PolandStatutoryProfilePanel";
import PLFilingSettlementPanel from "./PLFilingSettlementPanel";

// Poland Compliance Centre (ZP-PL-ENG-001 §12 "Poland country setup"). Employer
// registration per legal employer (NIP / REGON / KRS, tax office, ZUS deadline
// class, accident rate with its contribution year, PPK institution, fund
// applicability), the ZUS contribution account (NRS, vault), PPK re-enrolment
// checkpoints and every employee's Poland records. Nothing here calculates:
// the engine reads only APPROVED versions on the pay date and BLOCKS when a
// fact or a signed rule is missing.

const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
const ask = (message) => {
  const value = window.prompt(message);
  return value && value.trim() ? value.trim() : null;
};

function SetupStatus() {
  const [summary, error] = useLoad(() => getPlSummary());
  if (error) return <p role="alert" className="text-[12px] text-error">{error}</p>;
  if (!summary) return null;
  const pack = (summary.packs || [])[0];
  return (
    <div className="rounded-xl border border-warning/40 bg-warning/10 p-3 text-[12px] text-foreground-secondary" data-testid="pl-setup-status">
      <p className="font-semibold text-foreground">Polish payroll is not yet certified.</p>
      <p className="mt-1">
        Rule pack {pack ? `${pack.packId} ${pack.version} (${pack.status})` : "not seeded"}: {summary.pendingRows ?? 0} row(s)
        awaiting signature. Until they are signed every Polish payslip is blocked with its reason — never estimated.
      </p>
      <p className="mt-1">
        Approved here: {summary.activeEmployerRegistrations ?? 0} employer registration(s)
        ({summary.verifiedEmployerRegistrations ?? 0} verified), {summary.activeWorkerProfiles ?? 0} worker profile(s),{" "}
        {summary.approvedStatements ?? 0} statement(s).
      </p>
      {(summary.unmet || []).length > 0 && (
        <p className="mt-1">Not yet met: {summary.unmet.map((u) => u.label).join("; ")}. Poland opens only when all pass.</p>
      )}
    </div>
  );
}

function EmployerNrs({ registrations, onDone }) {
  const [registrationId, setRegistrationId] = useState("");
  const [nrs, setNrs] = useState("");
  const [state, setState] = useState({ error: null, notice: null });
  const submit = async (e) => {
    e.preventDefault();
    const value = nrs;
    setNrs("");                                 // never keep the typed account number around
    try {
      await setPlEmployerNrs(registrationId, value);
      setState({ error: null, notice: "ZUS contribution account (NRS) stored (encrypted)." });
      onDone();
    } catch (err) {
      setState({ error: errorText(err), notice: null });
    }
  };
  return (
    <form onSubmit={submit} className="mt-3 flex flex-wrap items-end gap-2" aria-label="ZUS contribution account" data-testid="pl-employer-nrs">
      <select className={input} value={registrationId} required onChange={(e) => setRegistrationId(e.target.value)}
        aria-label="Employer registration">
        <option value="">Employer registration…</option>
        {(registrations || []).filter((r) => r.status === "DRAFT").map((r) => (
          <option key={r.id} value={r.id}>{r.legal_name} · from {r.effective_from}</option>
        ))}
      </select>
      <input className={input} type="password" autoComplete="off" required aria-label="NRS" placeholder="NRS (26 digits or PL IBAN)"
        value={nrs} onChange={(e) => setNrs(e.target.value.replace(/[^\dPLpl ]/g, ""))} />
      <button type="submit" className={btn}>Store NRS</button>
      {state.error && <span role="alert" className="text-[12px] text-error">{state.error}</span>}
      {state.notice && <span role="status" className="text-[12px] text-success">{state.notice}</span>}
    </form>
  );
}

function EmployerRegistrations() {
  const [version, setVersion] = useState(0);
  const [registrations] = useLoad(() => listPlRegistrations());
  return (
    <div>
      <JPRecordSection
        key={version}
        title="Employer registration (per legal employer, PL-001)" testId="pl-employer-registrations"
        description="NIP / REGON / KRS, tax office, ZUS deadline class with evidence, the accident rate with its source and contribution year, PPK institution and fund applicability (unknown blocks). Approve (second user), then verify (second user)."
        load={listPlRegistrations} create={createPlRegistration}
        empty="No employer registration — Polish payroll is blocked until one is approved and verified."
        columns={[{ label: "In force", render: period }, { label: "Legal name", key: "legal_name" }, { label: "NIP", key: "nip" },
          { label: "ZUS class / accident", render: (r) => `${r.zus_deadline_class} · ${r.accident_rate_pct ?? "—"}%` },
          { label: "NRS", render: (r) => (r.nrs_vault_id ? "On file (masked)" : "Missing") },
          { label: "Verification", key: "verification_state" }, statusCol]}
        actions={[
          { label: "Approve", show: isDraft, run: (r) => approvePlRegistration(r.id), ok: "Employer registration approved." },
          { label: "Verify", show: (r) => r.status === "ACTIVE" && r.verification_state !== "VERIFIED", ok: "Verified.",
            run: async (r) => {
              const reason = ask("Verification evidence / reason");
              if (!reason) throw new Error("A reason is required.");
              await verifyPlRegistration(r.id, "VERIFIED", reason);
            } },
          { label: "Reject", show: (r) => r.status === "ACTIVE" && r.verification_state === "UNVERIFIED", ok: "Marked rejected.",
            run: async (r) => {
              const reason = ask("Why is the registration rejected?");
              if (!reason) throw new Error("A reason is required.");
              await verifyPlRegistration(r.id, "REJECTED", reason);
            } },
        ]}
        fields={[
          { key: "effective_from", label: "Effective from", type: "date", required: true },
          { key: "legal_name", label: "Legal name", required: true },
          { key: "nip", label: "NIP", required: true },
          { key: "regon", label: "REGON" },
          { key: "krs", label: "KRS" },
          { key: "tax_office_code", label: "Tax office code" },
          { key: "zus_deadline_class", label: "ZUS deadline class", type: "select", options: ZUS_DEADLINE_CLASSES, required: true },
          { key: "zus_deadline_evidence_ref", label: "Deadline class evidence" },
          { key: "accident_rate_pct", label: "Accident rate %", type: "number" },
          { key: "accident_rate_source", label: "Accident rate source", type: "select", options: ACCIDENT_RATE_SOURCES },
          { key: "accident_rate_from", label: "Contribution year from", type: "date" },
          { key: "accident_rate_to", label: "Contribution year to", type: "date" },
          { key: "accident_rate_evidence_ref", label: "Accident rate evidence" },
          { key: "small_payer", label: "Small payer", type: "bool" },
          { key: "fp_fs_applicable", label: "FP/FS applicable", type: "bool" },
          { key: "fgsp_applicable", label: "FGŚP applicable", type: "bool" },
          { key: "ppk_institution", label: "PPK institution" },
          { key: "ppk_agreement_ref", label: "PPK agreement reference" },
          { key: "ppk_employer_additional_pct", label: "Employer additional PPK %", type: "number" },
          { key: "evidence_ref", label: "Evidence reference" },
          REASON_FIELD,
        ]} />
      <section className={card}>
        <h3 className="text-[14px] font-semibold text-foreground">ZUS contribution account (NRS)</h3>
        <p className="text-[12px] text-foreground-muted">Stored encrypted on a DRAFT registration version; shown masked.</p>
        <EmployerNrs registrations={registrations} onDone={() => setVersion((v) => v + 1)} />
      </section>
    </div>
  );
}

function PpkReenrolment() {
  const [on, setOn] = useState(new Date().toISOString().slice(0, 10));
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const load = () => listPlPpkReenrolmentDue(on).then(setRows).catch((e) => setError(errorText(e)));
  return (
    <section className={card} data-testid="pl-ppk-reenrolment">
      <h3 className="text-[14px] font-semibold text-foreground">PPK auto re-enrolment</h3>
      <p className="mb-2 text-[12px] text-foreground-muted">Opted-out participants whose re-enrolment checkpoint has come (spec §7).</p>
      <div className="flex items-end gap-2">
        <input className={input} type="date" value={on} onChange={(e) => setOn(e.target.value)} aria-label="Checkpoint date" />
        <button type="button" className={btn} onClick={load}>Check</button>
      </div>
      {error && <p role="alert" className="mt-2 text-[12px] text-error">{error}</p>}
      {rows && (rows.length === 0
        ? <p className="mt-2 text-[12px] text-foreground-muted">Nobody is due.</p>
        : <ul className="mt-2 text-[12px]">{rows.map((r) => (
          <li key={r.participationId}>Employee #{r.employeeId} — due {r.nextReenrolmentDate}</li>))}</ul>)}
    </section>
  );
}

function EmployeeRecords() {
  const [employees, setEmployees] = useState([]);
  const [selected, setSelected] = useState("");
  useEffect(() => {
    let ignore = false;
    getEmployees({}).then((list) => {
      if (!ignore) setEmployees(list.filter((e) => (e.countryCode || e.country) === "PL"));
    });
    return () => { ignore = true; };
  }, []);
  return (
    <section className={card} data-testid="pl-employee-picker">
      <h3 className="text-[14px] font-semibold text-foreground">Employee records</h3>
      <label className="mt-2 flex flex-col gap-1 text-[11px] font-semibold text-foreground-muted">
        Employee
        <select className={input} value={selected} onChange={(e) => setSelected(e.target.value)}>
          <option value="">— Select a Polish employee —</option>
          {employees.map((e) => <option key={e.id} value={e.id}>{e.name} · {e.employeeCode}</option>)}
        </select>
      </label>
      {employees.length === 0 && <p className="mt-2 text-[12px] text-foreground-muted">No employees with country PL.</p>}
      {selected && <div className="mt-4"><PolandEmployeeRecords key={selected} employeeId={Number(selected)} /></div>}
    </section>
  );
}

export default function PLComplianceCentreTab() {
  return (
    <div className="space-y-4">
      <SetupStatus />
      <EmployerRegistrations />
      <PpkReenrolment />
      <EmployeeRecords />
      <PLFilingSettlementPanel />
    </div>
  );
}
