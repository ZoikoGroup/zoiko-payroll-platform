import { useState } from "react";
import {
  approveZaDirective, approveZaEmployerRegistration, captureZaDirective, createZaEmployerRegistration,
  getEmployees, listZaDirectives, listZaEmployerRegistrations, listZaEtiLedger, revokeZaDirective,
} from "../../../service/payrollService";
import { card, useLoad } from "../../../components/jurisdiction/southAfrica/zaFormat";
import { Table } from "../../../components/jurisdiction/southAfrica/zaShared";

// South Africa Compliance Centre (ZP-ZA-ENG-001 Phase 7; "ZA" — "SA" is Saudi
// Arabia) — Payroll → Compliances, where every country's organisation set-up
// lives. Acts on YOUR organisation only. Four-eyes approval, evidence and the
// dormancy switch are enforced server-side; this screen only submits input
// and shows the server's answer.

const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
const btn = "rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground hover:bg-surface-muted disabled:opacity-40";
const btnPrimary = "rounded-lg bg-primary px-3 py-1.5 text-[12px] font-semibold text-white hover:opacity-90 disabled:opacity-40";
const labelCls = "flex flex-col gap-1 text-[11px] font-semibold text-foreground-muted";
const DIRECTIVE_TYPES = ["FIXED_PERCENTAGE", "FIXED_AMOUNT", "LUMP_SUM", "OTHER"];

function blankToNull(values) {
  return Object.fromEntries(Object.entries(values).map(([k, v]) => [k, v === "" ? null : v]));
}

function useRun(reload) {
  const [state, setState] = useState({ busy: false, error: null, notice: null });
  const run = async (fn, ok) => {
    setState({ busy: true, error: null, notice: null });
    try {
      await fn();
      setState({ busy: false, error: null, notice: ok });
      reload();
    } catch (e) {
      setState({ busy: false, error: e?.message || "The action failed.", notice: null });
    }
  };
  return [state, run];
}

function Status({ state, error }) {
  const message = error || state.error;
  return (
    <>
      {message && <p role="alert" className="text-[12px] text-error">{message}</p>}
      {state.notice && <p role="status" className="text-[12px] text-success">{state.notice}</p>}
    </>
  );
}

function Field({ label, children }) {
  return <label className={labelCls}>{label}{children}</label>;
}

const REG_BLANK = {
  effectiveFrom: "", payeReference: "", uifReference: "", sdlReference: "", coidaReference: "",
  sdlLiable: "true", sdlExemptionReason: "", etiRegistered: "false", sectorCode: "", bargainingCouncil: "", evidenceRef: "",
};

function EmployerRegistrations() {
  const [rows, error, loading, reload] = useLoad(listZaEmployerRegistrations);
  const [form, setForm] = useState(REG_BLANK);
  const [state, run] = useRun(reload);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const submit = (e) => {
    e.preventDefault();
    run(async () => {
      await createZaEmployerRegistration(blankToNull({
        ...form, sdlLiable: form.sdlLiable === "true", etiRegistered: form.etiRegistered === "true",
      }));
      setForm(REG_BLANK);
    }, "Registration recorded as DRAFT — a second user must approve it before payroll uses it.");
  };
  return (
    <section className={card} data-testid="za-employer-registrations">
      <h3 className="text-[14px] font-semibold text-foreground">Employer registrations (SARS / UIF / SDL / COIDA)</h3>
      <p className="mb-3 text-[12px] text-foreground-muted">
        SDL liability is an employer fact, never inferred from a payroll run. A registration counts only once a second
        user has approved it.
      </p>
      <Status state={state} error={error} />
      {loading ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        <Table rows={rows} empty="No employer registration yet — South African payroll is blocked until one is approved."
          columns={[
            { label: "From", key: "effective_from" },
            { label: "To", key: "effective_to" },
            { label: "PAYE ref", key: "paye_reference" },
            { label: "UIF ref", key: "uif_reference" },
            { label: "SDL ref", key: "sdl_reference" },
            { label: "SDL", render: (r) => (r.sdl_liable ? "Liable" : `Exempt — ${r.sdl_exemption_reason || "no reason"}`) },
            { label: "ETI registered", render: (r) => (r.eti_registered ? "Yes" : "No") },
            { label: "Status", key: "status" },
            {
              label: "",
              render: (r) => (r.status === "DRAFT" ? (
                <button type="button" className={btn} disabled={state.busy}
                  onClick={() => run(() => approveZaEmployerRegistration(r.id), "Registration approved.")}>
                  Approve
                </button>
              ) : null),
            },
          ]} />
      )}
      <form onSubmit={submit} className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3" aria-label="Record an employer registration">
        <Field label="Effective from"><input type="date" required className={input} value={form.effectiveFrom} onChange={set("effectiveFrom")} /></Field>
        <Field label="PAYE reference (7 + 9 digits)"><input required className={input} value={form.payeReference} onChange={set("payeReference")} placeholder="7123456789" /></Field>
        <Field label="UIF reference (U + 9 digits)"><input className={input} value={form.uifReference} onChange={set("uifReference")} placeholder="U123456789" /></Field>
        <Field label="SDL reference (L + 9 digits)"><input className={input} value={form.sdlReference} onChange={set("sdlReference")} placeholder="L123456789" /></Field>
        <Field label="COIDA registration"><input className={input} value={form.coidaReference} onChange={set("coidaReference")} /></Field>
        <Field label="SDL liable">
          <select className={input} value={form.sdlLiable} onChange={set("sdlLiable")}>
            <option value="true">Yes</option><option value="false">No — exempt</option>
          </select>
        </Field>
        {form.sdlLiable === "false" && (
          <Field label="SDL exemption reason (required)"><input required className={input} value={form.sdlExemptionReason} onChange={set("sdlExemptionReason")} /></Field>
        )}
        <Field label="ETI registered">
          <select className={input} value={form.etiRegistered} onChange={set("etiRegistered")}>
            <option value="false">No</option><option value="true">Yes</option>
          </select>
        </Field>
        <Field label="Sector code"><input className={input} value={form.sectorCode} onChange={set("sectorCode")} /></Field>
        <Field label="Bargaining council"><input className={input} value={form.bargainingCouncil} onChange={set("bargainingCouncil")} /></Field>
        <Field label="Evidence reference"><input className={input} value={form.evidenceRef} onChange={set("evidenceRef")} /></Field>
        <div className="flex items-end"><button type="submit" className={btnPrimary} disabled={state.busy}>Record registration</button></div>
      </form>
    </section>
  );
}

const DIR_BLANK = {
  directiveNumber: "", directiveType: "FIXED_PERCENTAGE", ratePct: "", amount: "", taxYear: "", issueDate: "",
  effectiveFrom: "", effectiveTo: "", instruction: "", evidenceSha256: "",
};

function Directives({ employees }) {
  const [employeeId, setEmployeeId] = useState("");
  const [rows, setRows] = useState([]);
  const [loadError, setLoadError] = useState(null);
  const [form, setForm] = useState(DIR_BLANK);
  const reload = (id = employeeId) => {
    if (!id) { setRows([]); return; }
    listZaDirectives(id).then((r) => { setRows(r); setLoadError(null); })
      .catch((e) => setLoadError(e?.message || "Could not load directives."));
  };
  const [state, run] = useRun(() => reload());
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const choose = (e) => { setEmployeeId(e.target.value); reload(e.target.value); };
  const unsupported = ["LUMP_SUM", "OTHER"].includes(form.directiveType);
  const submit = (e) => {
    e.preventDefault();
    run(async () => {
      await captureZaDirective(employeeId, blankToNull(form));
      setForm(DIR_BLANK);
    }, "Directive captured — a second user must approve it before payroll applies it.");
  };
  return (
    <section className={card} data-testid="za-directives">
      <h3 className="text-[14px] font-semibold text-foreground">Tax directives (SARS)</h3>
      <p className="mb-3 text-[12px] text-foreground-muted">
        A directive overrides PAYE only for its own employee, tax year and dates, and only once approved by a second
        user. Lump-sum and other directives are recorded but block payroll until certified.
      </p>
      <Field label="Employee">
        <select className={input} value={employeeId} onChange={choose} aria-label="Employee">
          <option value="">Choose a South African employee…</option>
          {employees.map((emp) => <option key={emp.id} value={emp.id}>{emp.name} ({emp.employeeCode})</option>)}
        </select>
      </Field>
      <div className="mt-3"><Status state={state} error={loadError} /></div>
      {employeeId && (
        <>
          <Table rows={rows} empty="No directives for this employee."
            columns={[
              { label: "Number", key: "directive_number" },
              { label: "Type", key: "directive_type" },
              { label: "Rate %", key: "rate_pct" },
              { label: "Amount", key: "amount" },
              { label: "Tax year", key: "tax_year" },
              { label: "From", key: "effective_from" },
              { label: "To", key: "effective_to" },
              { label: "Status", key: "status" },
              {
                label: "",
                render: (r) => (
                  <div className="flex gap-2">
                    {r.status === "CAPTURED" && (
                      <button type="button" className={btn} disabled={state.busy}
                        onClick={() => run(() => approveZaDirective(r.id), "Directive approved.")}>Approve</button>
                    )}
                    {["CAPTURED", "APPROVED"].includes(r.status) && (
                      <button type="button" className={btn} disabled={state.busy}
                        onClick={() => run(() => revokeZaDirective(r.id), "Directive revoked; its evidence is kept.")}>Revoke</button>
                    )}
                  </div>
                ),
              },
            ]} />
          <form onSubmit={submit} className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3" aria-label="Capture a tax directive">
            <Field label="Directive number"><input required className={input} value={form.directiveNumber} onChange={set("directiveNumber")} /></Field>
            <Field label="Type">
              <select className={input} value={form.directiveType} onChange={set("directiveType")}>
                {DIRECTIVE_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </Field>
            {form.directiveType === "FIXED_PERCENTAGE"
              ? <Field label="Rate %"><input type="number" min="0" max="100" step="0.0001" required className={input} value={form.ratePct} onChange={set("ratePct")} /></Field>
              : <Field label="Amount (ZAR)"><input type="number" min="0" step="0.01" className={input} value={form.amount} onChange={set("amount")} /></Field>}
            <Field label="Tax year"><input required className={input} value={form.taxYear} onChange={set("taxYear")} placeholder="2027" /></Field>
            <Field label="Issue date"><input type="date" required className={input} value={form.issueDate} onChange={set("issueDate")} /></Field>
            <Field label="Effective from"><input type="date" required className={input} value={form.effectiveFrom} onChange={set("effectiveFrom")} /></Field>
            <Field label="Effective to"><input type="date" className={input} value={form.effectiveTo} onChange={set("effectiveTo")} /></Field>
            <Field label="Instruction"><input className={input} value={form.instruction} onChange={set("instruction")} /></Field>
            <Field label="Evidence SHA-256 (required)"><input required className={input} value={form.evidenceSha256} onChange={set("evidenceSha256")} /></Field>
            {unsupported && (
              <p className="sm:col-span-3 text-[12px] text-error">
                {form.directiveType} directives are not certified: once approved they will block this employee&apos;s payroll.
              </p>
            )}
            <div className="flex items-end"><button type="submit" className={btnPrimary} disabled={state.busy}>Capture directive</button></div>
          </form>
        </>
      )}
    </section>
  );
}

function EtiLedger() {
  const [rows, error, loading] = useLoad(() => listZaEtiLedger());
  return (
    <section className={card} data-testid="za-eti-ledger">
      <h3 className="text-[14px] font-semibold text-foreground">Employment Tax Incentive ledger</h3>
      <p className="mb-3 text-[12px] text-foreground-muted">
        ETI is an employer incentive offset against the employer&apos;s monthly PAYE remittance; it is never deducted from,
        or added to, an employee&apos;s pay. Read-only — corrections are reversals, never edits.
      </p>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {loading ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        <Table rows={rows} empty="No ETI months recorded yet."
          columns={[
            { label: "Employee", key: "employee_id" },
            { label: "Month", key: "claim_month" },
            { label: "Qualifying month", key: "qualifying_month_no" },
            { label: "Paid hours", key: "paid_hours" },
            { label: "Remuneration", key: "remuneration" },
            { label: "Normalised", key: "normalised_remuneration" },
            { label: "ETI", key: "eti_amount" },
            { label: "Status", key: "status" },
            { label: "Reverses", key: "reverses_id" },
          ]} />
      )}
    </section>
  );
}

export default function ZAComplianceCentreTab() {
  const [employees] = useLoad(async () =>
    (await getEmployees()).filter((emp) => (emp.countryCode || emp.country) === "ZA"));
  return (
    <div className="flex flex-col gap-4" data-testid="za-compliance-centre">
      <div>
        <h2 className="text-[16px] font-semibold text-foreground">South Africa Compliance Centre</h2>
        <p className="text-[12px] text-foreground-muted">
          South African payroll stays blocked until the platform release gates G1–G7 are signed; this is where your
          employer registrations, employees&apos; tax directives and the ETI ledger are managed.
        </p>
      </div>
      <EmployerRegistrations />
      <Directives employees={employees || []} />
      <EtiLedger />
    </div>
  );
}
