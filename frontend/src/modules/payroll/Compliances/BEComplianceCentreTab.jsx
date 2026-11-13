import { useEffect, useState } from "react";
import {
  approveBeComponentMapping, approveBeRegistration, approveBeUnit, createBeComponentMapping, createBeRegistration,
  createBeSubstituteDay, createBeUnit, getBeOptions, getEmployees, listBeComponentMappings,
  listBeJointCommitteesForOrg, listBeRegistrations, listBeSubstituteDays, listBeUnits, resolveBeClassification,
  setBeEmployerOnss, verifyBeRegistration,
} from "../../../service/payrollService";
import { card, useLoad } from "../../../components/jurisdiction/japan/jpFormat";
import JPRecordSection, { btn, isDraft, statusCol } from "../../../components/jurisdiction/japan/JPRecordSection";
import { REASON_FIELD, errorText, period } from "../../../components/jurisdiction/new_zealand/nzOrgOptions";
import { BEResolverResult, BelgiumEmployeeRecords } from "../Payroll_Employees/BelgiumStatutoryProfilePanel";
import { registrationPayload } from "../Payroll_Employees/beOrgPayloads";
import BEFilingSettlementPanel from "./BEFilingSettlementPanel";
import BEParallelCyclesSection from "./BEParallelCyclesSection";

// Belgium Compliance Centre (ZP-BE-ENG-001 §2 / §15; Block A4). Employer
// registration per legal employer (enterprise number, ONSS employer category,
// legal language, mandates as REFERENCES only), the employer ONSS number
// (vault, masked), establishment units, Joint Committee coverage from the
// platform definitions, the resolver's blockers per employee and every
// employee's Belgium records. Nothing here calculates: the engine reads only
// APPROVED versions on the pay date and BLOCKS when a fact or a signed rule is
// missing.

const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
const ask = (message) => {
  const value = window.prompt(message);
  return value && value.trim() ? value.trim() : null;
};
const today = () => new Date().toISOString().slice(0, 10);


function SetupStatus() {
  return (
    <div className="rounded-xl border border-warning/40 bg-warning/10 p-3 text-[12px] text-foreground-secondary"
      data-testid="be-setup-status">
      <p className="font-semibold text-foreground">Belgian payroll is not yet certified.</p>
      <p className="mt-1">
        Every Belgian rule comes from a rule pack signed by a Belgian specialist. Until the rows a calculation needs
        are signed, every Belgian payslip is blocked with its reason — never estimated. Records approved here are
        used only from their effective date, and only after a second user approves them.
      </p>
    </div>
  );
}

function EmployerOnss({ registrations, onDone }) {
  const [registrationId, setRegistrationId] = useState("");
  const [onss, setOnss] = useState("");
  const [state, setState] = useState({ error: null, notice: null });
  const submit = async (e) => {
    e.preventDefault();
    const value = onss;
    setOnss("");                                // never keep the typed number around
    try {
      await setBeEmployerOnss(registrationId, value);
      setState({ error: null, notice: "Employer ONSS number stored (encrypted)." });
      onDone();
    } catch (err) {
      setState({ error: errorText(err), notice: null });
    }
  };
  return (
    <form onSubmit={submit} className="mt-3 flex flex-wrap items-end gap-2" aria-label="Employer ONSS number"
      data-testid="be-employer-onss">
      <select className={input} value={registrationId} required onChange={(e) => setRegistrationId(e.target.value)}
        aria-label="Employer registration">
        <option value="">Employer registration…</option>
        {(registrations || []).filter((r) => r.status === "DRAFT").map((r) => (
          <option key={r.id} value={r.id}>{r.legal_name} · from {r.effective_from}</option>
        ))}
      </select>
      <input className={input} type="password" autoComplete="off" required aria-label="ONSS number"
        placeholder="ONSS employer number" value={onss} onChange={(e) => setOnss(e.target.value.replace(/[^\d.\- ]/g, ""))} />
      <button type="submit" className={btn}>Store ONSS number</button>
      {state.error && <span role="alert" className="text-[12px] text-error">{state.error}</span>}
      {state.notice && <span role="status" className="text-[12px] text-success">{state.notice}</span>}
    </form>
  );
}

function EmployerRegistrations({ options }) {
  const [version, setVersion] = useState(0);
  const [registrations, , , reloadRegistrations] = useLoad(() => listBeRegistrations());
  const [verified, rejected] = options.verificationOutcomes || [];
  return (
    <div>
      <JPRecordSection
        key={version}
        title="Employer registration (per legal employer, BE-001)" testId="be-employer-registrations"
        description="Enterprise (KBO/BCE) number, ONSS employer category, legal language, withholding declaration frequency, holiday fund reference and mandates as references only. Approve (second user), then verify (second user)."
        load={listBeRegistrations} create={createBeRegistration} transform={registrationPayload}
        empty="No employer registration — Belgian payroll is blocked until one is approved and verified."
        columns={[{ label: "In force", render: period }, { label: "Legal name", key: "legal_name" },
          { label: "Enterprise no.", key: "enterprise_number" }, { label: "ONSS category", key: "employer_category_code" },
          { label: "ONSS number", render: (r) => (r.onss_number_vault_id ? "On file (masked)" : "Missing") },
          { label: "Mandates", render: (r) => (r.mandate_refs || []).join(", ") || "—" },
          { label: "Verification", key: "verification_state" }, statusCol]}
        actions={[
          { label: "Approve", show: isDraft, run: (r) => approveBeRegistration(r.id), ok: "Employer registration approved." },
          { label: "Verify", show: (r) => r.status === "ACTIVE" && r.verification_state !== verified, ok: "Verified.",
            run: async (r) => {
              const reason = ask("Verification evidence / reason");
              if (!reason) throw new Error("A reason is required.");
              await verifyBeRegistration(r.id, verified, reason);
            } },
          { label: "Reject", show: (r) => r.status === "ACTIVE" && r.verification_state === "UNVERIFIED", ok: "Marked rejected.",
            run: async (r) => {
              const reason = ask("Why is the registration rejected?");
              if (!reason) throw new Error("A reason is required.");
              await verifyBeRegistration(r.id, rejected, reason);
            } },
        ]}
        fields={[
          { key: "effective_from", label: "Effective from", type: "date", required: true },
          { key: "legal_name", label: "Legal name", required: true },
          { key: "enterprise_number", label: "Enterprise number (KBO/BCE)", required: true },
          { key: "employer_category_code", label: "ONSS employer category" },
          { key: "onss_special_160_status", label: "Special contribution (workforce test) applies?", type: "select",
            options: options.special160Statuses },
          { key: "special_160_evidence_ref", label: "Workforce test evidence" },
          { key: "legal_language", label: "Legal language", type: "select", options: options.legalLanguages },
          { key: "withholding_declaration_frequency", label: "Withholding declaration frequency" },
          { key: "holiday_fund_ref", label: "Holiday fund reference" },
          { key: "mandate_refs", label: "Mandate references (comma-separated, never secrets)" },
          { key: "filing_credential_ref", label: "Filing credential reference" },
          { key: "evidence_ref", label: "Evidence reference" },
          REASON_FIELD,
        ]} />
      <section className={card}>
        <h3 className="text-[14px] font-semibold text-foreground">Employer ONSS number</h3>
        <p className="text-[12px] text-foreground-muted">Stored encrypted on a DRAFT registration version; shown masked.</p>
        <EmployerOnss registrations={registrations} onDone={() => { setVersion((v) => v + 1); reloadRegistrations(); }} />
      </section>
    </div>
  );
}

function EstablishmentUnits() {
  const [registrations] = useLoad(() => listBeRegistrations());
  const choices = (registrations || []).map((r) => [String(r.id), `${r.legal_name} · from ${r.effective_from}`]);
  return (
    <JPRecordSection
      title="Establishment units" testId="be-establishment-units"
      description="The establishment units of each employer registration (unit number, region). An employment classification links to its unit."
      load={listBeUnits} create={createBeUnit}
      empty="No establishment unit."
      columns={[{ label: "In force", render: period }, { label: "Unit", key: "unit_number" }, { label: "Name", key: "name" },
        { label: "Region", render: (r) => r.region || "—" }, statusCol]}
      actions={[{ label: "Approve", show: isDraft, run: (r) => approveBeUnit(r.id), ok: "Establishment unit approved." }]}
      fields={[
        { key: "registration_id", label: "Employer registration", type: "select", options: choices, required: true },
        { key: "unit_number", label: "Unit number", required: true },
        { key: "name", label: "Name", required: true },
        { key: "region", label: "Region" },
        { key: "effective_from", label: "Effective from", type: "date", required: true },
        { key: "evidence_ref", label: "Evidence reference" },
        REASON_FIELD,
      ]} />
  );
}

function ComponentMappings({ options }) {
  const keyHint = (options.platformPayFields || []).join(", ");
  return (
    <JPRecordSection
      title="Pay component mappings" testId="be-component-mappings"
      description={`Map each platform pay field (${keyHint}) or policy allowance key to a Belgian pay component. A component paid without an ACTIVE mapping blocks Belgian payroll (BE-008). Approved by a second user.`}
      load={listBeComponentMappings} create={createBeComponentMapping}
      empty="No mapping yet: Belgian payslips are blocked until the platform pay is mapped."
      columns={[{ label: "In force", render: period }, { label: "Source", key: "platform_component_source" },
        { label: "Platform key", key: "platform_component_key" }, { label: "Belgian component", key: "be_component" },
        statusCol]}
      actions={[{ label: "Approve", show: isDraft, run: (r) => approveBeComponentMapping(r.id), ok: "Mapping approved." }]}
      fields={[
        { key: "platform_component_source", label: "Source", type: "select", options: options.componentSources,
          required: true },
        { key: "platform_component_key", label: "Platform key", required: true },
        { key: "be_component", label: "Belgian component", type: "select", options: options.components, required: true },
        { key: "effective_from", label: "Effective from", type: "date", required: true },
        { key: "evidence_ref", label: "Evidence reference" },
        REASON_FIELD,
      ]} />
  );
}

function SubstituteDays() {
  const [rows, error, , reload] = useLoad(() => listBeSubstituteDays());
  const [form, setForm] = useState({ date: "", replacesHoliday: "", name: "", reason: "" });
  const [state, setState] = useState({ error: null, notice: null });
  const submit = async (e) => {
    e.preventDefault();
    try {
      await createBeSubstituteDay(form);
      setForm({ date: "", replacesHoliday: "", name: "", reason: "" });
      setState({ error: null, notice: "Substitute day recorded (audited)." });
      reload();
    } catch (err) {
      setState({ error: errorText(err), notice: null });
    }
  };
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });
  return (
    <section className={card} data-testid="be-substitute-days">
      <h3 className="text-[14px] font-semibold text-foreground">Substitute holidays</h3>
      <p className="mb-2 text-[12px] text-foreground-muted">
        The employer&apos;s replacement day for a public holiday that falls on a Sunday or a non-working day. Public
        holidays themselves come only from the signed rule pack.
      </p>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      <ul className="text-[12px]">{(rows || []).map((r) => <li key={r.id}>{r.date} · {r.name}</li>)}</ul>
      <form onSubmit={submit} className="mt-2 flex flex-wrap items-end gap-2" aria-label="Record a substitute day">
        <input className={input} type="date" required value={form.date} onChange={set("date")} aria-label="Substitute day" />
        <input className={input} type="date" required value={form.replacesHoliday} onChange={set("replacesHoliday")}
          aria-label="Replaces holiday" />
        <input className={input} placeholder="Name" value={form.name} onChange={set("name")} aria-label="Name" />
        <input className={input} placeholder="Reason" required value={form.reason} onChange={set("reason")}
          aria-label="Reason" />
        <button type="submit" className={btn}>Record</button>
        {state.error && <span role="alert" className="text-[12px] text-error">{state.error}</span>}
        {state.notice && <span role="status" className="text-[12px] text-success">{state.notice}</span>}
      </form>
    </section>
  );
}

function JointCommitteeCoverage() {
  const [rows, error] = useLoad(() => listBeJointCommitteesForOrg());
  return (
    <section className={card} data-testid="be-joint-committees">
      <h3 className="text-[14px] font-semibold text-foreground">Joint Committee coverage</h3>
      <p className="mb-2 text-[12px] text-foreground-muted">
        The platform&apos;s Joint Committee agreements. Only an Active agreement can be linked to a classification;
        a classification that points to a non-Active or different committee blocks Belgian payroll.
      </p>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {rows && rows.length === 0 && (
        <p className="text-[12px] text-foreground-muted">No Joint Committee agreement is defined yet.</p>
      )}
      {rows && rows.length > 0 && (
        <table className="w-full text-[12px]">
          <thead><tr className="text-left text-foreground-muted">
            <th>Agreement</th><th>Committee</th><th>Sub</th><th>Status</th><th>In force</th>
          </tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.id} className="border-t border-border">
              <td>{r.agreementCode}{r.codeValid ? "" : " (invalid code)"}</td><td>{r.jointCommittee || "—"}</td>
              <td>{r.subCommittee || "—"}</td><td>{r.status}</td>
              <td>{r.effectiveFrom || "—"} → {r.effectiveTo || "open"}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
    </section>
  );
}

function useBelgianEmployees() {
  const [employees, setEmployees] = useState([]);
  useEffect(() => {
    let ignore = false;
    getEmployees({}).then((list) => {
      if (!ignore) setEmployees(list.filter((e) => (e.countryCode || e.country) === "BE"));
    });
    return () => { ignore = true; };
  }, []);
  return employees;
}

function ResolverBlockers({ employees }) {
  const [payDate, setPayDate] = useState(today());
  const [results, setResults] = useState(null);
  const [error, setError] = useState(null);
  const run = async () => {
    setError(null);
    try {
      const out = [];
      for (const e of employees) {
        try {
          out.push({ employee: e, result: await resolveBeClassification(e.id, payDate) });
        } catch (err) {
          out.push({ employee: e, error: errorText(err) });
        }
      }
      setResults(out);
    } catch (err) {
      setError(errorText(err));
    }
  };
  return (
    <section className={card} data-testid="be-resolver-blockers">
      <h3 className="text-[14px] font-semibold text-foreground">Resolver blockers</h3>
      <p className="mb-2 text-[12px] text-foreground-muted">
        Runs the read-only applicability resolver for every Belgian employee on a pay date and lists what blocks
        their payroll. Nothing is calculated or saved.
      </p>
      <div className="flex items-end gap-2">
        <input className={input} type="date" value={payDate} onChange={(e) => setPayDate(e.target.value)} aria-label="Pay date" />
        <button type="button" className={btn} onClick={run} disabled={!payDate || employees.length === 0}>Check all</button>
      </div>
      {employees.length === 0 && <p className="mt-2 text-[12px] text-foreground-muted">No employees with country BE.</p>}
      {error && <p role="alert" className="mt-2 text-[12px] text-error">{error}</p>}
      {(results || []).map(({ employee, result, error: rowError }) => (
        <div key={employee.id} className="mt-3">
          <p className="text-[12px] font-semibold">{employee.name} · {employee.employeeCode}</p>
          {rowError ? <p role="alert" className="text-[12px] text-error">{rowError}</p> : <BEResolverResult result={result} />}
        </div>
      ))}
    </section>
  );
}

function EmployeeRecords({ employees }) {
  const [selected, setSelected] = useState("");
  return (
    <section className={card} data-testid="be-employee-picker">
      <h3 className="text-[14px] font-semibold text-foreground">Employee records</h3>
      <label className="mt-2 flex flex-col gap-1 text-[11px] font-semibold text-foreground-muted">
        Employee
        <select className={input} value={selected} onChange={(e) => setSelected(e.target.value)}>
          <option value="">— Select a Belgian employee —</option>
          {employees.map((e) => <option key={e.id} value={e.id}>{e.name} · {e.employeeCode}</option>)}
        </select>
      </label>
      {employees.length === 0 && <p className="mt-2 text-[12px] text-foreground-muted">No employees with country BE.</p>}
      {selected && <div className="mt-4"><BelgiumEmployeeRecords key={selected} employeeId={Number(selected)} /></div>}
    </section>
  );
}

export default function BEComplianceCentreTab() {
  const [options, optionsError] = useLoad(() => getBeOptions());
  const employees = useBelgianEmployees();
  return (
    <div className="space-y-4">
      <SetupStatus />
      {optionsError && <p role="alert" className="text-[12px] text-error">{optionsError}</p>}
      {options && <EmployerRegistrations options={options} />}
      <EstablishmentUnits />
      {options && <ComponentMappings options={options} />}
      <SubstituteDays />
      <JointCommitteeCoverage />
      <ResolverBlockers employees={employees} />
      <EmployeeRecords employees={employees} />
      <BEFilingSettlementPanel employees={employees} />
      <BEParallelCyclesSection />
    </div>
  );
}
