import { useCallback, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import {
  getEmployees, getSgComplianceCentre, listSgCpfEzpay, prepareSgCpfEzpay, transitionSgCpfEzpay,
  downloadSgCpfEzpayFile, recordSgCessation,
} from "../../../service/payrollService";
import SGIr21CasesTab from "./SGIr21CasesTab";
import { SGComplianceReportsCard, SGCorrectionCard, SGDeductionCard, SGIr8aSubmissionCard, SGRestoreFreezeCard } from "./SGOperationsCards";

// Singapore Compliance Centre (ZP-SG-ENG-001 §14). Every status, date,
// evidence reference and blocker comes from the server
// (GET /singapore/compliance-centre); this tab performs no statutory
// arithmetic. It is an internal evaluation — not a CPF Board / IRAS / MOM
// approval — and says so.

const STATUS_STYLE = {
  PASS: "bg-primary/10 text-primary", FAIL: "bg-error/10 text-error", REVIEW: "bg-warning/10 text-warning",
  BLOCKED: "bg-error/10 text-error", INFO: "bg-surface-muted text-foreground-muted",
};
// Display-only mirror of service._SG_EZPAY_TRANSITIONS (the server decides).
const EZPAY_NEXT = { PREPARED: ["APPROVED"], APPROVED: ["SUBMITTED"], SUBMITTED: ["ACCEPTED", "REJECTED", "UNKNOWN"],
  UNKNOWN: ["ACCEPTED", "REJECTED"] };
const input = "rounded-lg border border-border bg-surface px-3 py-2 text-[13px] text-foreground";
const btn = "rounded-lg border border-border bg-surface-muted px-3 py-1.5 text-[12px] font-semibold text-foreground hover:border-primary disabled:opacity-50";

function Badge({ status }) {
  return <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${STATUS_STYLE[status] || ""}`}>{status}</span>;
}

function EzpayRow({ row, onDone }) {
  const [form, setForm] = useState({ status: EZPAY_NEXT[row.status]?.[0] || "", reference: "", note: "" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const data = row.renderedData || {};
  const next = EZPAY_NEXT[row.status] || [];

  async function act(fn) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onDone();
    } catch (err) {
      setError(err?.message || "The CPF EZPay step was not accepted.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="rounded-[12px] border border-border p-3 text-[12px]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span>
          <span className="font-mono">{data.filename}</span> · wage month {data.relevantMonth} · advice {data.adviceCode} ·
          total S${data.fileTotal} · {data.recordCount} records
        </span>
        <Badge status={row.status} />
      </div>
      {row.status === "UNKNOWN" && (
        <p className="mt-1 text-error">Outcome UNKNOWN — reconcile with CPF Board before any retry (SG-040).</p>
      )}
      <div className="mt-2 flex flex-wrap items-end gap-2">
        {!["PREPARED", "Superseded", "Void"].includes(row.status) && (
          <button type="button" className={btn} disabled={busy} onClick={() => act(() => downloadSgCpfEzpayFile(row.id))}>
            Download file (audited)
          </button>
        )}
        {next.length > 0 && (
          <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); act(() => transitionSgCpfEzpay(row.id, form)); }}>
            <label className="sr-only" htmlFor={`ez-${row.id}-status`}>Next status</label>
            <select id={`ez-${row.id}-status`} className={input} value={form.status}
                    onChange={(e) => setForm((f) => ({ ...f, status: e.target.value }))}>
              {next.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <label className="sr-only" htmlFor={`ez-${row.id}-ref`}>CPF Board reference</label>
            <input id={`ez-${row.id}-ref`} className={input} placeholder="CPF Board reference / acknowledgement"
                   value={form.reference} onChange={(e) => setForm((f) => ({ ...f, reference: e.target.value }))} />
            <label className="sr-only" htmlFor={`ez-${row.id}-note`}>Note</label>
            <input id={`ez-${row.id}-note`} className={input} placeholder="Note"
                   value={form.note} onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))} />
            <button type="submit" className={btn} disabled={busy}>Record</button>
          </form>
        )}
      </div>
      {error && <p className="mt-1 text-error" role="alert">{error}</p>}
    </li>
  );
}

function EzpayCard() {
  const today = new Date();
  const [rows, setRows] = useState([]);
  const [form, setForm] = useState({ year: today.getFullYear(), month: today.getMonth() || 12, adviceCode: "01" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [version, setVersion] = useState(0);
  const load = () => setVersion((v) => v + 1);
  useEffect(() => {
    let active = true;
    listSgCpfEzpay().then((r) => active && setRows(r)).catch(() => active && setRows([]));
    return () => { active = false; };
  }, [version]);

  async function prepare(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await prepareSgCpfEzpay({ year: Number(form.year), month: Number(form.month), adviceCode: form.adviceCode });
      load();
    } catch (err) {
      setError(err?.message || "The CPF EZPay file could not be prepared.");
    } finally {
      setBusy(false);
    }
  }

  const live = rows.filter((r) => !["Superseded", "Void"].includes(r.status));
  return (
    <section className="rounded-[18px] border border-border p-5" aria-labelledby="sg-ezpay-heading">
      <h3 id="sg-ezpay-heading" className="text-[13px] font-bold text-foreground">CPF EZPay contribution file</h3>
      <p className="mb-3 text-[12px] text-foreground-muted">
        Prepared to the CPF Board FTP specification (16 Jan 2025) and submitted by your Corppass user through CPF EZPay —
        Zoiko has no direct CPF API. Approval needs a second person; CPF Board&apos;s acceptance is recorded only from its
        acknowledgement.
      </p>
      <form className="mb-3 flex flex-wrap items-end gap-2" onSubmit={prepare}>
        {[["year", "Year", 2026, 2100], ["month", "Month", 1, 12]].map(([k, text, min, max]) => (
          <div key={k}>
            <label className="mb-1 block text-[12px] font-semibold text-foreground-secondary" htmlFor={`ez-new-${k}`}>{text}</label>
            <input id={`ez-new-${k}`} type="number" min={min} max={max} className={`${input} w-24`} value={form[k]}
                   onChange={(e) => setForm((f) => ({ ...f, [k]: e.target.value }))} />
          </div>
        ))}
        <div>
          <label className="mb-1 block text-[12px] font-semibold text-foreground-secondary" htmlFor="ez-new-advice">Advice code</label>
          <input id="ez-new-advice" className={`${input} w-20`} value={form.adviceCode} maxLength={2}
                 onChange={(e) => setForm((f) => ({ ...f, adviceCode: e.target.value }))} />
        </div>
        <button type="submit" className={btn} disabled={busy}>Prepare file</button>
      </form>
      {error && <p className="mb-2 text-[12px] text-error" role="alert">{error}</p>}
      {live.length ? <ul className="space-y-2">{live.map((r) => <EzpayRow key={`${r.id}-${r.status}`} row={r} onDone={load} />)}</ul>
        : <p className="text-[12px] text-foreground-muted">No CPF EZPay files yet.</p>}
    </section>
  );
}

function CessationCard({ onDone }) {
  const [employees, setEmployees] = useState([]);
  const [form, setForm] = useState({ employeeId: "", dateOfLeaving: "" });
  const [message, setMessage] = useState(null);
  useEffect(() => {
    getEmployees().then((res) => {
      const list = Array.isArray(res) ? res : res?.data || res?.items || [];
      setEmployees(list.filter((e) => (e.countryCode || e.country) === "SG"));
    }).catch(() => setEmployees([]));
  }, []);

  async function submit(e) {
    e.preventDefault();
    setMessage(null);
    try {
      const out = await recordSgCessation(Number(form.employeeId), form.dateOfLeaving);
      setMessage(out?.ir21Case ? `Cessation recorded — IR21 case ${out.ir21Case.id} opened; monies are HELD_FOR_IR21.`
        : "Cessation recorded — no tax clearance required (Singapore Citizen).");
      onDone();
    } catch (err) {
      setMessage(err?.message || "The cessation was not recorded.");
    }
  }

  return (
    <section className="rounded-[18px] border border-border p-5" aria-labelledby="sg-cessation-heading">
      <h3 id="sg-cessation-heading" className="text-[13px] font-bold text-foreground">Record a cessation</h3>
      <p className="mb-3 text-[12px] text-foreground-muted">
        For a non-citizen (foreign or SPR) employee, recording the last day of employment opens an IR21 case and withholds
        all monies from today (IRAS tax clearance).
      </p>
      <form className="flex flex-wrap items-end gap-2" onSubmit={submit}>
        <div>
          <label className="mb-1 block text-[12px] font-semibold text-foreground-secondary" htmlFor="sg-cess-emp">Employee</label>
          <select id="sg-cess-emp" required className={input} value={form.employeeId}
                  onChange={(e) => setForm((f) => ({ ...f, employeeId: e.target.value }))}>
            <option value="">Select…</option>
            {employees.map((e) => <option key={e.id} value={e.id}>{e.employeeCode || e.id} · {e.name}</option>)}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-[12px] font-semibold text-foreground-secondary" htmlFor="sg-cess-date">Last day of employment</label>
          <input id="sg-cess-date" type="date" required className={input} value={form.dateOfLeaving}
                 onChange={(e) => setForm((f) => ({ ...f, dateOfLeaving: e.target.value }))} />
        </div>
        <button type="submit" className={btn}>Record cessation</button>
      </form>
      {message && <p className="mt-2 text-[12px] text-foreground-muted" role="status">{message}</p>}
    </section>
  );
}

export default function SGComplianceCentreTab() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [version, setVersion] = useState(0);
  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    let active = true;
    getSgComplianceCentre()
      .then((res) => { if (active) { setData(res); setError(null); } })
      .catch((err) => active && setError(err?.message || "The Compliance Centre could not be loaded."));
    return () => { active = false; };
  }, [version]);

  return (
    <div className="space-y-5">
      <section aria-labelledby="sg-cc-heading">
        <h2 id="sg-cc-heading" className="text-[15px] font-bold text-foreground">Singapore Compliance Centre</h2>
        <p className="text-[12px] text-foreground-muted">{data?.certification || "Internal Zoiko evaluation."}</p>
        {error && <p className="mt-2 text-[12px] text-error" role="alert">{error}</p>}
        {!data && !error && (
          <p className="mt-3 flex items-center gap-2 text-[12px] text-foreground-muted" role="status">
            <Loader2 size={14} className="animate-spin" /> Loading…
          </p>
        )}
        {data && (
          <>
            <p className="mt-2 text-[12px] text-foreground-muted">
              {Object.entries(data.counts || {}).map(([k, v]) => `${k} ${v}`).join(" · ")} — as of {data.asOf}
            </p>
            <div className="mt-3 overflow-x-auto rounded-[14px] border border-border">
              <table className="w-full text-[12px]">
                <caption className="sr-only">Singapore compliance items with status, effective date, evidence, blocker, owner and action</caption>
                <thead className="bg-surface-muted text-foreground-muted">
                  <tr>
                    {["Area", "Item", "Status", "Effective", "Evidence / source", "Blocker", "Owner", "Action"].map((h) => (
                      <th key={h} scope="col" className="px-3 py-2 text-left">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((i) => (
                    <tr key={i.key} className="border-t border-border align-top">
                      <td className="px-3 py-2 font-semibold">{i.area}</td>
                      <td className="px-3 py-2">{i.label}</td>
                      <td className="px-3 py-2"><Badge status={i.status} /></td>
                      <td className="px-3 py-2">{i.effectiveDate || "—"}</td>
                      <td className="px-3 py-2">{i.evidence}{i.source && <span className="block text-foreground-muted">{i.source}</span>}</td>
                      <td className="px-3 py-2">{i.blocker || "—"}</td>
                      <td className="px-3 py-2">{i.owner}</td>
                      <td className="px-3 py-2">{i.action || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <h3 className="mt-4 text-[13px] font-bold text-foreground">Deadlines (three clocks + IR21)</h3>
            <ul className="mt-2 grid gap-2 sm:grid-cols-2">
              {data.clocks.map((c, n) => (
                <li key={`${c.clock}-${n}`} className="rounded-[12px] border border-border p-3 text-[12px]">
                  <span className="font-semibold">{c.clock.replaceAll("_", " ")}</span>
                  {c.wageMonth && ` · ${c.wageMonth}`} — due <span className="font-mono">{c.due || "—"}</span>
                  {c.enforcementAfter && <> · enforcement after <span className="font-mono">{c.enforcementAfter}</span></>}
                  {c.overtimeDue && <> · overtime by <span className="font-mono">{c.overtimeDue}</span></>}
                  <span className="block text-foreground-muted">{c.rule} ({c.source})</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
      <EzpayCard />
      <CessationCard onDone={refresh} />
      <SGCorrectionCard onDone={refresh} />
      <SGDeductionCard />
      <SGRestoreFreezeCard onDone={refresh} />
      <SGIr8aSubmissionCard />
      <SGComplianceReportsCard />
      <section aria-labelledby="sg-ir21-heading">
        <h3 id="sg-ir21-heading" className="mb-2 text-[13px] font-bold text-foreground">IR21 tax clearance</h3>
        <SGIr21CasesTab key={version} />
      </section>
    </div>
  );
}
