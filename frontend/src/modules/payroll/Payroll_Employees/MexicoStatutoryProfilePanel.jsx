import { useState } from "react";
import { ShieldAlert, X } from "lucide-react";
import {
  createEmployeeStatutoryProfile, getMxEmployer, getMxEmployeeReadiness, getMxEmployeeRecord, listMxEmployers,
} from "../../../service/payrollService";
import { Field, Messages, Table, btnPrimary, input, useAction, useLoad } from "../../../components/jurisdiction/mexico/mxShared";
import { Badge, ReadinessDateBar } from "../../../components/jurisdiction/mexico/employer/employerShared";
import { localToday } from "../../../components/jurisdiction/mexico/employer/employerUtils";
import { MX_FEDERAL_ENTITIES } from "../../../components/jurisdiction/mexico/employer/mxStateCodes";
import MXInfonavitNoticePanel from "./MXInfonavitNoticePanel";

// Mexico employee record (ZP-MX-ENG-001 §12 — the spec's "People → Employee →
// Payroll → Mexico"). FACTS only: no tax rate, no subsidy amount, no SBC is
// typed here (the engine derives them in Phase 5). RFC / CURP / NSS are held
// masked on the employee; the profile keeps keyed tokens and their validation
// status (FORMAT_ONLY until the CURP/NSS check-digit sources are saved). Each
// save is a new effective-dated version; nothing is edited in place.
const camel = (k) => k.replace(/_([a-z])/g, (_, c) => c.toUpperCase());

const SECTIONS = [
  ["Employment (MX-038: the work state is the employee's own)", [
    ["mx_work_state", "Work state", "state"], ["mx_work_municipality", "Work municipality", "text"],
    ["mx_remote_state_exception_ref", "Remote / multi-state exception ref", "text"],
    ["mx_seniority_date", "Seniority date", "date"], ["mx_contract_type_code", "Contract type (c_TipoContrato)", "text"],
    ["mx_regime_type_code", "Regime type (c_TipoRegimen)", "text"], ["mx_workday_type_code", "Workday (c_TipoJornada)", "text"],
    ["mx_professional_min_code", "Professional minimum code (only from Active content)", "text"],
  ]],
  ["IMSS", [["mx_job_risk_code", "Job risk (c_RiesgoPuesto)", "text"]]],
  ["Pay (SBC is computed and shown separately — MX-037)", [
    ["mx_pay_frequency_code", "Pay frequency (c_PeriodicidadPago)", "text"], ["mx_daily_salary", "Daily salary (MXN)", "number"],
    ["mx_salary_type", "Salary type", "select", ["FIXED", "VARIABLE", "MIXED"]],
  ]],
  ["CFDI receiver", [
    ["mx_fiscal_postal_code", "Fiscal postal code", "text"], ["mx_receiver_fiscal_regime", "Fiscal regime (c_RegimenFiscal)", "text"],
  ]],
  ["ISR (no personal tax-rate field; subsidy and annual-adjustment eligibility are computed)", [
    ["mx_annual_adjustment_exclusion", "Declared annual-adjustment exclusion (code)", "text"],
    ["mx_annual_adjustment_exclusion_evidence_ref", "Evidence reference for the declaration", "text"],
  ]],
];

function Section({ title, children }) {
  return (
    <fieldset className="rounded-xl border border-border p-4">
      <legend className="px-1 text-[12px] font-semibold text-foreground">{title}</legend>
      <div className="flex flex-col gap-3">{children}</div>
    </fieldset>
  );
}

export default function MexicoStatutoryProfilePanel({ employee, onClose }) {
  const [record, recordError, loading, reload] = useLoad(() => getMxEmployeeRecord(employee.id), [employee.id]);
  const [employers] = useLoad(() => listMxEmployers(), []);
  const [employerId, setEmployerId] = useState(null);
  const effectiveEmployer = employerId ?? employers?.[0]?.employerId ?? null;
  const [detail] = useLoad(() => (effectiveEmployer ? getMxEmployer(effectiveEmployer) : Promise.resolve(null)),
    [effectiveEmployer]);
  const [on, setOn] = useState(localToday);
  const [readiness, readinessError, , reloadReadiness] = useLoad(() => getMxEmployeeReadiness(employee.id, on),
    [employee.id, on]);
  const { run, error, notice, busy } = useAction(() => { reload(); reloadReadiness(); });
  const [changes, setChanges] = useState({});
  const [effectiveFrom, setEffectiveFrom] = useState(localToday);

  const versions = record?.profiles || [];
  const current = versions[versions.length - 1] || {};
  const value = (k) => (k in changes ? changes[k] : current[camel(k)] ?? "");
  const setFact = (k) => (e) => setChanges((c) => ({ ...c, [k]: e.target.value === "" ? null : e.target.value }));

  const save = async (e) => {
    e.preventDefault();
    const payload = { countryCode: "MX", effectiveFrom };
    Object.entries(changes).forEach(([k, v]) => { payload[camel(k)] = v; });
    if (await run(() => createEmployeeStatutoryProfile(employee.id, payload),
      `New Mexico profile version recorded, effective ${effectiveFrom}. Earlier versions are unchanged.`)) {
      setChanges({});
    }
  };

  const factInput = ([k, label, kind, choices]) => (
    <Field key={k} label={label}>
      {kind === "select" || kind === "state" ? (
        <select className={input} name={k} value={value(k)} onChange={setFact(k)}>
          <option value="">—</option>
          {(kind === "state" ? MX_FEDERAL_ENTITIES.map((s) => ({ value: s.code, label: `${s.code} — ${s.name}` }))
            : choices.map((c) => ({ value: c, label: c }))).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      ) : (
        <input className={input} name={k} type={kind} step={kind === "number" ? "any" : undefined} value={value(k)}
          onChange={setFact(k)} />
      )}
    </Field>
  );

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-background/40 backdrop-blur-sm" onClick={onClose}>
      <div className="flex h-full w-full max-w-3xl flex-col border-l border-border bg-surface shadow-[0_24px_48px_rgba(0,0,0,0.15)]"
        onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="mx-profile-title"
        data-testid="mx-employee-panel">
        <div className="flex items-center justify-between border-b border-border px-6 py-5">
          <div>
            <h2 id="mx-profile-title" className="text-[15px] font-bold text-foreground">Mexico statutory profile</h2>
            <p className="mt-0.5 text-[12px] text-foreground-muted">{employee.name} · {employee.employeeCode}</p>
          </div>
          <button onClick={onClose} aria-label="Close panel"
            className="rounded-xl border border-border bg-surface-muted p-2 text-foreground-muted hover:border-primary hover:text-primary">
            <X size={15} />
          </button>
        </div>
        <div className="flex flex-1 flex-col gap-5 overflow-y-auto px-6 py-5">
          <div className="flex items-start gap-3 rounded-[14px] border border-warning/30 bg-warning/10 px-4 py-3">
            <ShieldAlert size={16} className="mt-0.5 shrink-0 text-warning" />
            <p className="text-[12px] text-foreground">
              Facts only. ISR, subsidy, SBC, IMSS and INFONAVIT amounts are computed by the server from the versions in
              force on each pay date (Phase 5). Mexican payroll stays blocked until its release gates are signed.
            </p>
          </div>
          <Messages error={recordError || error} notice={notice} />
          {loading && !record && <p className="text-[12px] text-foreground-muted" role="status">Loading…</p>}
          {record && (
            <>
              <Section title="Identity (held masked on the employee record)">
                <div className="flex flex-wrap gap-4 text-[12px] text-foreground" data-testid="mx-identifiers">
                  {["rfc", "curp", "nss"].map((k) => (
                    <span key={k}><span className="font-semibold uppercase">{k}</span> {record.identifiers[k] || "not recorded"}</span>
                  ))}
                  <Badge value={current.identifierValidationStatus || "NOT_STARTED"} />
                </div>
                {(current.identifierFindings || []).map((f) => (
                  <p key={f.check} className="text-[11px] text-foreground-muted">• {f.check}: {f.result} — {f.detail}</p>
                ))}
              </Section>
              <form onSubmit={save} className="flex flex-col gap-4" aria-label="Record a new Mexico statutory profile version"
                data-testid="mx-profile-form">
                <Section title="Workplace">
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                    <Field label="Legal employer">
                      <select className={input} aria-label="Legal employer" value={effectiveEmployer ?? ""}
                        onChange={(e) => setEmployerId(Number(e.target.value))}>
                        {(employers || []).map((e) => <option key={e.employerId} value={e.employerId}>{e.legalName}</option>)}
                      </select>
                    </Field>
                    <Field label="Establishment">
                      <select className={input} name="mx_establishment_id" value={value("mx_establishment_id")}
                        onChange={setFact("mx_establishment_id")}>
                        <option value="">—</option>
                        {(detail?.establishments || []).filter((e) => e.isActive)
                          .map((e) => <option key={e.id} value={e.id}>{e.name} ({e.stateCode})</option>)}
                      </select>
                    </Field>
                    <Field label="IMSS registration">
                      <select className={input} name="mx_imss_registration_id" value={value("mx_imss_registration_id")}
                        onChange={setFact("mx_imss_registration_id")}>
                        <option value="">—</option>
                        {(detail?.imssRegistrations || []).filter((r) => r.status === "ACTIVE")
                          .map((r) => <option key={r.id} value={r.id}>{r.registroPatronal}</option>)}
                      </select>
                    </Field>
                  </div>
                </Section>
                {SECTIONS.map(([title, fields]) => (
                  <Section key={title} title={title}>
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">{fields.map(factInput)}</div>
                  </Section>
                ))}
                <div className="flex flex-wrap items-end gap-3">
                  <Field label="Effective from">
                    <input className={input} type="date" name="effective_from" value={effectiveFrom}
                      onChange={(e) => setEffectiveFrom(e.target.value)} />
                  </Field>
                  <button type="submit" className={btnPrimary} disabled={busy}>Record new version</button>
                </div>
              </form>
              <Section title="Versions">
                <Table rows={versions} empty="No Mexico profile version yet." columns={[
                  { key: "effectiveFrom", label: "From" }, { key: "effectiveTo", label: "To", render: (r) => r.effectiveTo || "open" },
                  { key: "mxWorkState", label: "Work state" }, { key: "mxDailySalary", label: "Daily salary" },
                  { key: "mxSalaryType", label: "Type" }, { key: "mxSeniorityDate", label: "Seniority" },
                  { key: "identifierValidationStatus", label: "Identifiers", render: (r) => <Badge value={r.identifierValidationStatus} /> },
                ]} />
              </Section>
              <MXInfonavitNoticePanel employeeId={employee.id} notices={record.infonavitNotices} onChange={reload} />
              <Section title="Readiness">
                <ReadinessDateBar on={on} onChange={setOn} />
                <Messages error={readinessError} />
                {readiness && (
                  <div data-testid="mx-employee-readiness">
                    <Table rows={readiness.items} rowKey={(r) => r.key} columns={[
                      { key: "label", label: "Item" }, { key: "status", label: "Status", render: (r) => <Badge value={r.status} /> },
                      { key: "detail", label: "Detail" },
                      { key: "gates", label: "Feeds gate", render: (r) => (r.gates.length ? r.gates.join(", ") : "unmapped") },
                    ]} />
                  </div>
                )}
              </Section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
