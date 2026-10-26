import { useState } from "react";
import {
  createNlAbsencePayPolicy,
  createNlEmployerProfile,
  getNlEmployerProfile,
  getNlWkr,
  listNlAbsencePayPolicies,
  listNlCaos,
  createNlSalaryBatch,
  downloadNlPaymentBatchFile,
  listNlPaymentBatches,
  previewNlSalaryBatch,
  reconcileNlPaymentBatch,
  recordNlPaymentBankResult,
  submitNlPaymentBatch,
} from "../../../service/payrollService";
import { Field, Messages, Table, btn, btnPrimary, card, input, useAction, useLoad } from "../../../components/jurisdiction/netherlands/nlShared";
import NLReadinessPanel from "./NLReadinessPanel";
import NLLoonaangiftePanel from "../Reports/NLLoonaangiftePanel";
import NLJaaropgaafPanel from "../Reports/NLJaaropgaafPanel";

// Netherlands Compliance Centre (ZP-NL-ENG-001 §10/§13). Everything here acts
// on YOUR organisation only. The employer registration is versioned (a change
// is a new version from its effective date). Wage-tax tables, premium rates
// and Whk/Aof decisions are platform data maintained by Zoiko, so there is no
// rate editor here.
const eur = (v) => (v == null ? "—" : Number(v).toLocaleString("nl-NL", { style: "currency", currency: "EUR" }));

const REG_FIELDS = [
  ["legalName", "Legal name", true], ["kvkNumber", "KVK number"], ["rsin", "RSIN"],
  ["loonheffingennummer", "Loonheffingennummer (e.g. 123456789L01)"], ["loonheffingenSubnumber", "Sub-number"],
  ["registrationLetterRef", "Belastingdienst registration letter ref"], ["bankBic", "Employer bank BIC"],
];
const REG_SELECTS = {
  returnPeriod: ["Return period", ["MONTH", "FOUR_WEEK"]],
  payrollSchedule: ["Payroll schedule", ["MONTH", "FOUR_WEEK", "WEEK"]],
  caoStatus: ["CAO applicability", ["NONE", "APPLICABLE", "UNKNOWN"]],
  wkrMode: ["WKR mode", ["STANDALONE", "CONCERN"]],
};

function EmployerRegistration() {
  const [profile, loadError, , reload] = useLoad(() => getNlEmployerProfile(), []);
  const [caos] = useLoad(() => listNlCaos(), []);
  const [form, setForm] = useState(null);
  const { run, error, notice, busy } = useAction(reload);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const save = async (e) => {
    e.preventDefault();
    const payload = { effectiveFrom: form.effectiveFrom };
    [...REG_FIELDS.map(([k]) => k), ...Object.keys(REG_SELECTS), "collectiveAgreementId"].forEach((k) => {
      if (form[k] !== undefined && form[k] !== null && form[k] !== "") payload[k] = form[k];
    });
    if (await run(() => createNlEmployerProfile(payload), "New registration version recorded.")) setForm(null);
  };

  return (
    <div className="flex flex-col gap-3">
      <Messages error={loadError || error} notice={notice} />
      <div className={card}>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-[14px] font-semibold text-foreground">
            Employer registration {profile ? `— version ${profile.version} from ${profile.effectiveFrom}` : "— not recorded"}
          </h3>
          {!form && (
            <button type="button" className={btnPrimary}
              onClick={() => setForm({ ...(profile || {}), effectiveFrom: new Date().toISOString().slice(0, 10) })}>
              {profile ? "Record a change" : "Record registration"}
            </button>
          )}
        </div>
        {profile && !form && (
          <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-[12px] sm:grid-cols-2 md:grid-cols-3">
            {[...REG_FIELDS, ...Object.entries(REG_SELECTS).map(([k, [l]]) => [k, l])].map(([k, l]) => (
              <div key={k}><dt className="text-foreground-muted">{l}</dt><dd className="text-foreground">{profile[k] || "—"}</dd></div>
            ))}
            <div>
              <dt className="text-foreground-muted">Registration verified</dt>
              <dd className="text-foreground">{profile.registrationVerifiedAt ? String(profile.registrationVerifiedAt).slice(0, 10) : "Not yet — verified by Zoiko against the letter"}</dd>
            </div>
          </dl>
        )}
        {form && (
          <form onSubmit={save} className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-3" aria-label="Employer registration version">
            <Field label="Effective from">
              <input type="date" required className={input} value={form.effectiveFrom} onChange={set("effectiveFrom")} />
            </Field>
            {REG_FIELDS.map(([k, l, req]) => (
              <Field key={k} label={l}><input className={input} required={req} value={form[k] || ""} onChange={set(k)} /></Field>
            ))}
            {Object.entries(REG_SELECTS).map(([k, [l, opts]]) => (
              <Field key={k} label={l}>
                <select className={input} value={form[k] || ""} onChange={set(k)}>
                  <option value="">—</option>
                  {opts.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              </Field>
            ))}
            {form.caoStatus === "APPLICABLE" && (
              <Field label="Collective agreement (CAO)">
                <select className={input} value={form.collectiveAgreementId || ""} onChange={set("collectiveAgreementId")}>
                  <option value="">—</option>
                  {(caos || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </Field>
            )}
            <div className="flex items-end gap-2">
              <button type="submit" className={btnPrimary} disabled={busy}>Save version</button>
              <button type="button" className="text-[12px] text-foreground-muted" onClick={() => setForm(null)}>Cancel</button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

function SicknessPolicies() {
  const [rows, loadError, , reload] = useLoad(() => listNlAbsencePayPolicies(), []);
  const [form, setForm] = useState({ effective_from: "", year1_pct: "70", year2_pct: "70", waiting_days: "0" });
  const { run, error, notice, busy } = useAction(reload);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  return (
    <div className={card}>
      <h3 className="mb-2 text-[14px] font-semibold text-foreground">Sickness-pay policy</h3>
      <p className="mb-2 text-[12px] text-foreground-muted">
        Statutory floor: 70% for two years, never below the minimum wage in year one. A CAO may pay more.
      </p>
      <Messages error={loadError || error} notice={notice} />
      <Table rows={rows} empty="No policy recorded — the statutory floor applies." columns={[
        { key: "effective_from", label: "From" }, { key: "year1_pct", label: "Year 1 %" },
        { key: "year2_pct", label: "Year 2 %" }, { key: "waiting_days", label: "Waiting days" },
      ]} />
      <form className="mt-3 flex flex-wrap items-end gap-3" aria-label="Record a sickness-pay policy"
        onSubmit={(e) => { e.preventDefault(); run(() => createNlAbsencePayPolicy(form), "Policy recorded."); }}>
        <Field label="Effective from"><input type="date" required className={input} value={form.effective_from} onChange={set("effective_from")} /></Field>
        <Field label="Year 1 %"><input type="number" step="any" required className={input} value={form.year1_pct} onChange={set("year1_pct")} /></Field>
        <Field label="Year 2 %"><input type="number" step="any" required className={input} value={form.year2_pct} onChange={set("year2_pct")} /></Field>
        <Field label="Waiting days"><input type="number" className={input} value={form.waiting_days} onChange={set("waiting_days")} /></Field>
        <button type="submit" className={btnPrimary} disabled={busy}>Record policy</button>
      </form>
    </div>
  );
}

function Wkr() {
  const [year, setYear] = useState(new Date().getFullYear());
  const [data, error] = useLoad(() => getNlWkr(year), [year]);
  const latest = data?.latest;
  return (
    <div className={card}>
      <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
        <h3 className="text-[14px] font-semibold text-foreground">Work-related costs scheme (WKR)</h3>
        <Field label="Tax year"><input type="number" className={input} value={year} onChange={(e) => setYear(e.target.value)} /></Field>
      </div>
      <Messages error={error} />
      {!latest ? (
        <p className="text-[12px] text-foreground-muted">No committed payroll for this year yet.</p>
      ) : (
        <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-[12px] sm:grid-cols-2">
          {[["Fiscal wage (cumulative)", latest.fiscal_wage_cumulative], ["Free space available", latest.free_space_available],
            ["Designated wage used", latest.designated_wage_cumulative], ["Targeted exemptions", latest.targeted_exemptions_cumulative],
            ["Excess over free space", latest.excess_amount], ["80% final levy on the excess", latest.excess_levy_80]].map(([l, v]) => (
            <div key={l} className="flex justify-between gap-3"><dt className="text-foreground-muted">{l}</dt><dd className="text-foreground">{eur(v)}</dd></div>
          ))}
        </dl>
      )}
      {data?.settlements?.length > 0 && (
        <div className="mt-3">
          <Table rows={data.settlements} columns={[
            { key: "target_return_period", label: "Settled in return" },
            { key: "excess_levy_amount", label: "Final levy", render: (r) => eur(r.excess_levy_amount) },
            { key: "status", label: "Status" },
          ]} />
        </div>
      )}
    </div>
  );
}

// SEPA salary batches (Phase 4.2): DRAFT -> SUBMITTED -> ACCEPTED / REJECTED /
// UNKNOWN -> SETTLED. The file is the exact stored pain.001 (validated against
// the official XSD). One run is paid through ONE channel — a run whose bank
// transfer file was downloaded cannot also get a SEPA batch, and vice versa.
function Payments() {
  const [rows, loadError, , reload] = useLoad(() => listNlPaymentBatches(), []);
  const { run, error, notice, busy } = useAction(reload);
  const [runId, setRunId] = useState("");
  const [preview, setPreview] = useState(null);
  const [exclusions, setExclusions] = useState({});

  const loadPreview = () => run(async () => {
    setPreview(await previewNlSalaryBatch(Number(runId)));
    setExclusions({});
  });
  const create = () => run(() => createNlSalaryBatch(Number(runId), { exclusions }), "Salary batch created (DRAFT).");
  const settle = (id) => {
    const ref = window.prompt("Bank statement reference for this settlement:");
    if (ref) run(() => reconcileNlPaymentBatch(id, ref), "Batch settled.");
  };

  return (
    <div className={card}>
      <h3 className="mb-2 text-[14px] font-semibold text-foreground">SEPA salary payments</h3>
      <p className="mb-2 text-[12px] text-foreground-muted">
        A salary batch (pain.001) is created from an approved, committed payroll run. Every employee who cannot be
        paid must be fixed or excluded with a reason. Payments to the Belastingdienst stay locked until gate G3.
      </p>
      <Messages error={loadError || error} notice={notice} />
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-[11px] font-semibold text-foreground-muted">
          Payroll run ID
          <input className={input} value={runId} onChange={(e) => setRunId(e.target.value.replace(/\D/g, ""))} />
        </label>
        <button type="button" className={btn} disabled={busy || !runId} onClick={loadPreview}>Preview</button>
        <button type="button" className={btnPrimary} disabled={busy || !runId || !preview} onClick={create}>
          Create salary batch
        </button>
      </div>
      {preview && (
        <div className="mb-3 text-[12px]">
          <p className="text-foreground">{preview.payable.length} employee(s) will be paid.</p>
          {preview.exceptions.map((x) => (
            <label key={x.employeeId} className="mt-1 flex flex-wrap items-center gap-2 text-error">
              {x.name}: {x.reason} — exclude with reason:
              <input className={input} value={exclusions[x.employeeId] || ""}
                onChange={(e) => setExclusions((m) => ({ ...m, [x.employeeId]: e.target.value }))} />
            </label>
          ))}
        </div>
      )}
      <Table rows={rows} empty="No payment batches yet." columns={[
        { key: "payroll_run_id", label: "Run" }, { key: "batch_kind", label: "Kind" },
        { key: "message_id", label: "Message ID" }, { key: "status", label: "Status" },
        { key: "submitted_at", label: "Submitted" }, { key: "reconciled_at", label: "Settled" },
        {
          key: "actions", label: "", render: (r) => (
            <div className="flex flex-wrap gap-1">
              <button type="button" className={btn} disabled={busy}
                onClick={() => run(() => downloadNlPaymentBatchFile(r.id))}>Download file</button>
              {r.status === "DRAFT" && (
                <button type="button" className={btn} disabled={busy}
                  onClick={() => run(() => submitNlPaymentBatch(r.id), "Marked as handed to the bank.")}>Mark submitted</button>
              )}
              {["SUBMITTED", "UNKNOWN"].includes(r.status) && ["ACCEPTED", "REJECTED", "UNKNOWN"]
                .filter((o) => o !== r.status)
                .map((o) => (
                  <button key={o} type="button" className={btn} disabled={busy}
                    onClick={() => run(() => recordNlPaymentBankResult(r.id, o), `Bank result recorded: ${o}.`)}>
                    Bank: {o.toLowerCase()}
                  </button>
                ))}
              {r.status === "ACCEPTED" && (
                <button type="button" className={btn} disabled={busy} onClick={() => settle(r.id)}>Settle</button>
              )}
            </div>
          ),
        },
      ]} />
    </div>
  );
}

const SECTIONS = [
  ["registration", "Employer registration"],
  ["returns", "Payroll taxes / loonaangifte"],
  ["annual", "Annual statements"],
  ["wkr", "WKR"],
  ["payments", "Payments"],
  ["readiness", "Readiness"],
];

export default function NLComplianceCentreTab() {
  const [section, setSection] = useState("registration");
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Netherlands compliance sections">
        {SECTIONS.map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={section === key}
            onClick={() => setSection(key)}
            className={`rounded-lg px-3 py-1.5 text-[12px] font-semibold ${section === key
              ? "bg-primary text-white" : "border border-border text-foreground hover:bg-surface-muted"}`}>
            {label}
          </button>
        ))}
      </div>
      {section === "registration" && <><EmployerRegistration /><SicknessPolicies /></>}
      {section === "returns" && <NLLoonaangiftePanel />}
      {section === "annual" && <NLJaaropgaafPanel />}
      {section === "wkr" && <Wkr />}
      {section === "payments" && <Payments />}
      {section === "readiness" && <NLReadinessPanel />}
    </div>
  );
}
