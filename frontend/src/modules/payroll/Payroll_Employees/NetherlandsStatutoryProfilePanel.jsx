import { useState } from "react";
import { ShieldAlert, X } from "lucide-react";
import {
  addNlCompanyCar,
  approveNlTerminationSettlement,
  closeNlIncomeRelationship,
  closeNlSicknessEvent,
  createEmployeeStatutoryProfile,
  createNlContractVersion,
  createNlIncomeRelationship,
  createNlTaxCreditInstruction,
  getNlEmployeeRecord,
  listNlAbsencePayPolicies,
  listNlPensionSchemes,
  prepareNlTerminationSettlement,
  recordNlSicknessEvent,
} from "../../../service/payrollService";
import { Field, Messages, Table, btn, btnPrimary, input, useAction, useLoad } from "../../../components/jurisdiction/netherlands/nlShared";

// Netherlands employee record (ZP-NL-ENG-001 §11). FACTS and signed
// instructions only — the server derives every statutory figure:
//   * wage tax: the employee's signed loonheffingskorting yes/no instruction,
//     never a credit amount (NL-006/NL-031);
//   * AWf: derived from the contract version, with the reason shown — never
//     chosen here (NL-016);
//   * statutory-profile facts are a new effective-dated version; nothing is
//     edited in place, so every past payslip stays replayable.
// Expat (30%) decisions are verified by Super Admin against the Belastingdienst
// letter and are read-only here.
const today = () => new Date().toISOString().slice(0, 10);
const eur = (v) => (v == null || v === "" ? "—" : Number(v).toLocaleString("nl-NL", { style: "currency", currency: "EUR" }));

// statutory-profile facts: [responseKey, label, kind, choices]
const PROFILE_SECTIONS = [
  ["Identity", [
    ["identityStatus", "Identity check status", "text"],
    ["personnelNumber", "Personnel number", "text"],
    ["residenceCountry", "Country of residence (ISO-2)", "text"],
    ["residenceVariant", "Residence variant of the wage-tax table (e.g. NL)", "text"],
  ]],
  ["Payroll tax", [
    ["tableColor", "Wage-tax table", "select", ["WHITE", "GREEN"]],
    ["voluntaryExtraWithholding", "Voluntary extra withholding per period (EUR — can only add tax)", "number"],
  ]],
  ["Insurance / Zvw", [
    ["eiInsured", "Insured for employee insurance (WW/WIA/ZW)", "bool"],
    ["insuranceExceptionCode", "Insurance exception code", "text"],
    ["insuranceEvidenceRef", "Insurance exception evidence reference", "text"],
    ["zvwPath", "Zvw path", "select", ["EMPLOYER_LEVY", "EMPLOYEE_CONTRIB", "SPECIAL"]],
    ["crossBorderStatus", "Cross-border status", "select", ["NONE", "SUPPORTED", "BLOCKED"]],
    ["a1Reference", "A1 certificate reference", "text"],
  ]],
  ["CAO / pension", []],
  ["Leave & minimum wage", [
    ["contractHoursPerWeek", "Contract hours per week", "number"],
    ["vacationAllowancePct", "Holiday allowance % (vakantiegeld, CAO may raise it)", "number"],
  ]],
];
const alias = (k) => `nl${k.charAt(0).toUpperCase()}${k.slice(1)}`;

function Section({ title, children }) {
  return (
    <fieldset className="rounded-xl border border-border p-4">
      <legend className="px-1 text-[12px] font-bold uppercase tracking-wide text-foreground-muted">{title}</legend>
      <div className="flex flex-col gap-3">{children}</div>
    </fieldset>
  );
}

function MiniForm({ fields, onSubmit, submitLabel, busy, initial = {} }) {
  const [form, setForm] = useState(initial);
  const set = (k, kind) => (e) => setForm((f) => ({ ...f, [k]: kind === "bool" ? e.target.checked : e.target.value }));
  return (
    <form
      className="grid grid-cols-1 gap-2 sm:grid-cols-3"
      onSubmit={async (e) => { e.preventDefault(); if (await onSubmit(form)) setForm(initial); }}
    >
      {fields.map(([k, label, kind = "text", choices, required]) => (
        <Field key={k} label={label}>
          {kind === "select" ? (
            <select className={input} required={required} value={form[k] ?? ""} onChange={set(k)}>
              <option value="">—</option>
              {choices.map((c) => (Array.isArray(c)
                ? <option key={c[0]} value={c[0]}>{c[1]}</option>
                : <option key={c} value={c}>{c}</option>))}
            </select>
          ) : kind === "bool" ? (
            <input type="checkbox" checked={Boolean(form[k])} onChange={set(k, "bool")} />
          ) : (
            <input className={input} required={required} type={kind} step={kind === "number" ? "any" : undefined}
              value={form[k] ?? ""} onChange={set(k)} />
          )}
        </Field>
      ))}
      <div className="flex items-end"><button type="submit" className={btnPrimary} disabled={busy}>{submitLabel}</button></div>
    </form>
  );
}

export default function NetherlandsStatutoryProfilePanel({ employee, onClose }) {
  const [record, recordError, loading, reload] = useLoad(() => getNlEmployeeRecord(employee.id), [employee.id]);
  const [schemes] = useLoad(() => listNlPensionSchemes(), []);
  const [policies] = useLoad(() => listNlAbsencePayPolicies(), []);
  const { run, error, notice, busy } = useAction(reload);
  const [changes, setChanges] = useState({});
  const [effectiveFrom, setEffectiveFrom] = useState(today());
  const [bsnVerified, setBsnVerified] = useState(false);

  const current = record?.statutoryFields || {};
  const value = (k) => (k in changes ? changes[k] : current[k] ?? "");
  const setFact = (k, kind) => (e) => {
    const v = kind === "bool" ? e.target.checked : e.target.value;
    setChanges((c) => ({ ...c, [k]: v === "" ? null : v }));
  };

  const saveFacts = async (e) => {
    e.preventDefault();
    const payload = { countryCode: "NL", effectiveFrom };
    Object.entries(changes).forEach(([k, v]) => { payload[alias(k)] = v; });
    if (bsnVerified) payload.nlBsnVerifiedAt = new Date().toISOString();
    if (await run(() => createEmployeeStatutoryProfile(employee.id, payload),
      `New statutory-profile version recorded, effective ${effectiveFrom}. Earlier versions are unchanged.`)) {
      setChanges({});
      setBsnVerified(false);
    }
  };

  const factInput = ([k, label, kind, choices]) => (
    <Field key={k} label={label}>
      {kind === "select" ? (
        <select className={input} value={value(k)} onChange={setFact(k)}>
          <option value="">—</option>
          {choices.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      ) : kind === "bool" ? (
        <input type="checkbox" checked={Boolean(value(k))} onChange={setFact(k, "bool")} />
      ) : (
        <input className={input} type={kind} step={kind === "number" ? "any" : undefined} value={value(k)} onChange={setFact(k)} />
      )}
    </Field>
  );

  const ikvs = record?.incomeRelationships || [];
  const contracts = record?.contracts || [];
  const instructions = record?.taxCreditInstructions || [];
  const activeInstruction = instructions.find((i) => !i.supersededById);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-background/40 backdrop-blur-sm" onClick={onClose}>
      <div className="flex h-full w-full max-w-3xl flex-col border-l border-border bg-surface shadow-[0_24px_48px_rgba(0,0,0,0.15)]"
        onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="nl-profile-title">
        <div className="flex items-center justify-between border-b border-border px-6 py-5">
          <div>
            <h2 id="nl-profile-title" className="text-[15px] font-bold text-foreground">Netherlands statutory profile</h2>
            <p className="mt-0.5 text-[12px] text-foreground-muted">{employee.name} · {employee.employeeCode}</p>
          </div>
          <button onClick={onClose} aria-label="Close panel"
            className="rounded-[12px] border border-border bg-surface-muted p-2 text-foreground-muted hover:border-primary hover:text-primary">
            <X size={15} />
          </button>
        </div>
        <div className="flex flex-1 flex-col gap-5 overflow-y-auto px-6 py-5">
          <div className="flex items-start gap-3 rounded-[14px] border border-warning/30 bg-warning/10 px-4 py-3">
            <ShieldAlert size={16} className="mt-0.5 shrink-0 text-warning" />
            <p className="text-[12px] text-foreground">
              Facts and signed instructions only. Loonheffing, premiums, the AWf class and the minimum-wage check are
              computed by the server from the versions in force on each pay date. The BSN is held masked in the
              employee record.
            </p>
          </div>
          <Messages error={recordError || error} notice={notice} />
          {loading && !record && <p className="text-[12px] text-foreground-muted" role="status">Loading…</p>}

          {record && (
            <>
              {/* 1. Identity + 3/5/9 statutory facts — one effective-dated version */}
              <form onSubmit={saveFacts} className="flex flex-col gap-4" aria-label="Record a new Netherlands statutory profile version">
                <Section title="Identity">
                  <p className="text-[12px] text-foreground-muted">
                    BSN {record.employee.bsnRecorded ? "recorded (masked)" : "NOT recorded — add it on the employee form"}
                    {current.bsnVerifiedAt ? ` · verified ${String(current.bsnVerifiedAt).slice(0, 10)}` : " · not verified"}
                  </p>
                  {record.employee.bsnRecorded && !current.bsnVerifiedAt && (
                    <label className="flex items-center gap-2 text-[12px] text-foreground-secondary">
                      <input type="checkbox" checked={bsnVerified} onChange={(e) => setBsnVerified(e.target.checked)} />
                      I checked the BSN against the employee&apos;s identity document
                    </label>
                  )}
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">{PROFILE_SECTIONS[0][1].map(factInput)}</div>
                </Section>
                {PROFILE_SECTIONS.slice(1).map(([title, fields]) => (
                  <Section key={title} title={title}>
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">{fields.map(factInput)}</div>
                    {title === "CAO / pension" && (
                      <p className="text-[12px] text-foreground-muted">
                        The CAO is set on the employer registration; choose the pension scheme this employee is in.
                      </p>
                    )}
                    {title === "CAO / pension" && (
                      <Field label="Pension scheme (CAO / pension)">
                        <select className={input} value={value("pensionSchemeId")} onChange={setFact("pensionSchemeId")}>
                          <option value="">— none —</option>
                          {(schemes || []).map((s) => <option key={s.id} value={s.id}>{s.fund_name} ({s.scheme_code})</option>)}
                        </select>
                      </Field>
                    )}
                  </Section>
                ))}
                <div className="flex flex-wrap items-end gap-3">
                  <Field label="Effective from">
                    <input type="date" required className={input} value={effectiveFrom} onChange={(e) => setEffectiveFrom(e.target.value)} />
                  </Field>
                  <button type="submit" className={btnPrimary}
                    disabled={busy || (Object.keys(changes).length === 0 && !bsnVerified)}>
                    Record new version
                  </button>
                </div>
              </form>

              {/* 2. Income relationship (IKV) */}
              <Section title="Income relationship (inkomstenverhouding)">
                <Table rows={ikvs} empty="No income relationship yet — payroll needs one." columns={[
                  { key: "ikvNumber", label: "IKV no." }, { key: "incomeRelationCode", label: "Code" },
                  { key: "payrollPeriod", label: "Period" }, { key: "startDate", label: "Start" },
                  { key: "endDate", label: "End" }, { key: "status", label: "Status" },
                  { key: "x", label: "", render: (r) => (r.status === "ACTIVE" ? (
                    <button type="button" className={btn} disabled={busy} onClick={() => {
                      const reason = window.prompt("Reason for closing this income relationship?");
                      const endDate = reason && window.prompt("End date (YYYY-MM-DD)?", today());
                      if (reason && endDate) run(() => closeNlIncomeRelationship(r.id, { endDate, closedReason: reason }), "Income relationship closed.");
                    }}>Close</button>
                  ) : null) },
                ]} />
                <MiniForm busy={busy} submitLabel="Open relationship"
                  initial={{ payrollPeriod: "MONTH" }}
                  fields={[["ikvNumber", "IKV number", "text", null, true], ["incomeRelationCode", "Income relation code", "text", null, true],
                    ["payrollPeriod", "Payroll period", "select", ["MONTH", "FOUR_WEEK", "WEEK"], true], ["startDate", "Start date", "date", null, true]]}
                  onSubmit={(f) => run(() => createNlIncomeRelationship(employee.id, f), "Income relationship opened.")} />
              </Section>

              {/* 3. Payroll tax — the signed instruction only */}
              <Section title="Loonheffingskorting — signed instruction (no amount)">
                <p className="text-[12px] text-foreground-muted">
                  {activeInstruction
                    ? `In force since ${activeInstruction.effectiveFrom}: ${activeInstruction.applyTaxCredit ? "APPLY" : "DO NOT apply"} the tax credit (signed ${String(activeInstruction.signedAt).slice(0, 10)}, ${activeInstruction.formVersion}).`
                    : "No signed instruction: wage tax is withheld WITHOUT the tax credit."}
                </p>
                <MiniForm busy={busy} submitLabel="Record signed instruction"
                  initial={{ applyTaxCredit: true, formVersion: "Model opgaaf 2026-08" }}
                  fields={[["applyTaxCredit", "Employee asks to apply the tax credit", "bool"],
                    ["signedAt", "Signed on", "date", null, true], ["effectiveFrom", "Effective from", "date", null, true],
                    ["formVersion", "Form version", "text", null, true]]}
                  onSubmit={(f) => run(() => createNlTaxCreditInstruction(employee.id, { ...f, signedAt: `${f.signedAt}T00:00:00` }),
                    "Signed instruction recorded; the previous one is superseded.")} />
              </Section>

              {/* 4. Contract / AWf */}
              <Section title="Contract — AWf class is derived">
                <Table rows={contracts} empty="No contract version." columns={[
                  { key: "version", label: "v" }, { key: "contractTerm", label: "Term" },
                  { key: "writtenRecord", label: "Written", render: (r) => (r.writtenRecord ? "Yes" : "No") },
                  { key: "onCall", label: "On-call", render: (r) => (r.onCall ? "Yes" : "No") },
                  { key: "startDate", label: "Start" },
                  { key: "derivedAwfClass", label: "AWf", render: (r) => <strong>{r.derivedAwfClass || "—"}</strong> },
                  { key: "awfDerivationReason", label: "Why" },
                ]} />
                <MiniForm busy={busy} submitLabel="Record new contract version"
                  initial={{ contractTerm: "INDEFINITE", writtenRecord: true }}
                  fields={[["contractTerm", "Contract term", "select", ["INDEFINITE", "FIXED"], true],
                    ["writtenRecord", "Written contract on file", "bool"], ["writtenEvidenceRef", "Written-contract evidence ref"],
                    ["onCall", "On-call / zero-hours", "bool"], ["agreedHoursPerWeek", "Agreed hours per week", "number"],
                    ["statutoryExceptionCode", "Statutory exception code"], ["startDate", "Start date", "date", null, true]]}
                  onSubmit={(f) => run(() => createNlContractVersion(employee.id, f), "New contract version recorded; AWf class derived.")} />
              </Section>

              {/* 7. Expat decision card (read-only) */}
              <Section title="Expat 30% facility (verified by Super Admin)">
                <Table rows={record.expatDecisions} empty="No 30% decision recorded." columns={[
                  { key: "decision_reference", label: "Decision" }, { key: "granted_from", label: "From" },
                  { key: "granted_to", label: "To" }, { key: "allowance_pct", label: "%" }, { key: "status", label: "Status" },
                ]} />
              </Section>

              {/* 8. Benefits / company car */}
              <Section title="Company car">
                <Table rows={record.companyCars} empty="No company car." columns={[
                  { key: "plate_masked", label: "Plate" }, { key: "catalog_value", label: "Catalog value", render: (r) => eur(r.catalog_value) },
                  { key: "addition_rate_window_key", label: "Addition window" }, { key: "private_use_status", label: "Private use" },
                  { key: "effective_from", label: "From" }, { key: "status", label: "Status" },
                ]} />
                <MiniForm busy={busy} submitLabel="Register car" initial={{ private_use_status: "PRIVATE" }}
                  fields={[["catalog_value", "Catalog value (EUR)", "number", null, true],
                    ["first_admission_date", "First admission", "date", null, true],
                    ["addition_rate_window_key", "Pack addition window key", "text", null, true],
                    ["plate_masked", "Plate (masked)"], ["private_use_status", "Private use", "select", ["PRIVATE", "NO_PRIVATE_USE"]],
                    ["no_private_use_evidence_ref", "Verklaring geen privégebruik ref"],
                    ["employee_own_contribution", "Employee's own contribution (EUR/period)", "number"],
                    ["effective_from", "Effective from", "date", null, true]]}
                  onSubmit={(f) => run(() => addNlCompanyCar(employee.id, f), "Company car registered.")} />
              </Section>

              {/* 9. Leave — sickness and termination */}
              <Section title="Sickness">
                <Table rows={record.sicknessEvents} empty="No sickness recorded." columns={[
                  { key: "first_sick_day", label: "First sick day" }, { key: "recovery_date", label: "Recovered" },
                  { key: "status", label: "Status" },
                  { key: "x", label: "", render: (r) => (!r.recovery_date ? (
                    <button type="button" className={btn} disabled={busy} onClick={() => {
                      const d = window.prompt("Recovery date (YYYY-MM-DD)?", today());
                      if (d) run(() => closeNlSicknessEvent(r.id, { recovery_date: d }), "Recovery recorded.");
                    }}>Recovered</button>
                  ) : null) },
                ]} />
                <MiniForm busy={busy} submitLabel="Record first sick day"
                  fields={[["first_sick_day", "First sick day", "date", null, true],
                    ["policy_id", "Sickness-pay policy", "select", (policies || []).map((p) => [p.id, `${p.year1_pct}% / ${p.year2_pct}% from ${p.effective_from}`])]]}
                  onSubmit={(f) => run(() => recordNlSicknessEvent(employee.id, f), "Sickness recorded.")} />
              </Section>

              <Section title="Termination settlement (four-eyes)">
                <Table rows={record.terminationSettlements} empty="No settlement." columns={[
                  { key: "termination_date", label: "Date" }, { key: "reason", label: "Reason" },
                  { key: "transition_payment_amount", label: "Transition payment", render: (r) => eur(r.transition_payment_amount) },
                  { key: "leave_payout", label: "Leave payout", render: (r) => eur(r.leave_payout) },
                  { key: "vacation_allowance_payout", label: "Holiday allowance", render: (r) => eur(r.vacation_allowance_payout) },
                  { key: "status", label: "Status" },
                  { key: "x", label: "", render: (r) => (r.status === "DRAFT" ? (
                    <button type="button" className={btn} disabled={busy}
                      onClick={() => run(() => approveNlTerminationSettlement(r.id), "Settlement approved.")}>Approve</button>
                  ) : null) },
                ]} />
                <p className="text-[11px] text-foreground-muted">The person who prepares a settlement cannot approve it.</p>
                <MiniForm busy={busy} submitLabel="Prepare settlement"
                  fields={[["termination_date", "Termination date", "date", null, true], ["reason", "Reason", "text", null, true],
                    ["initiated_by", "Initiated by", "select", ["EMPLOYER", "EMPLOYEE", "MUTUAL"], true],
                    ["service_months", "Months of service", "number", null, true], ["monthly_salary", "Monthly salary (EUR)", "number", null, true],
                    ["annual_salary", "Annual salary (EUR)", "number", null, true], ["hourly_wage", "Hourly wage (EUR)", "number", null, true],
                    ["unused_leave_hours", "Unused leave hours", "number"],
                    ["income_relationship_id", "Income relationship", "select", ikvs.map((i) => [i.id, `IKV ${i.ikvNumber}`])]]}
                  onSubmit={(f) => run(() => prepareNlTerminationSettlement(employee.id, f), "Settlement prepared — a second person approves it.")} />
              </Section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
